"""Kibana MCP Server - Log searching and analysis tools.

Provides 9 tools for searching and analyzing logs via Kibana.
"""

import logging
import os
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast

from fastmcp import FastMCP

# Setup project path for server imports (must be before server imports)
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization

from mcp.types import TextContent

from server.auto_heal_decorator import auto_heal_stage
from server.config import get_token_from_kubeconfig
from server.http_client import kibana_client
from server.tool_registry import ToolRegistry
from server.utils import get_kubeconfig, load_config

# Setup project path for server imports


logger = logging.getLogger(__name__)


# ==================== Configuration ====================


@dataclass
class KibanaEnvironment:
    """Kibana environment configuration."""

    url: str
    kubeconfig: str
    index_pattern: str = "app-logs-*"  # Configure in config.json
    namespace: str = "default"  # Configure in config.json


def _load_kibana_config() -> dict:
    """Load Kibana config from config.json."""
    config = load_config()
    return cast(dict, config.get("kibana", {})).get("environments", {})


def get_kibana_environment(environment: str) -> "KibanaEnvironment":
    """Get Kibana environment config from config.json or env vars."""
    env_key = "production" if environment.lower() == "prod" else environment.lower()

    # Try config.json first
    config = _load_kibana_config()
    if env_key in config:
        env_config = config[env_key]
        # Use get_kubeconfig for consistent kubeconfig resolution
        kubeconfig = env_config.get("kubeconfig")
        if not kubeconfig:
            kubeconfig = get_kubeconfig(env_key)
        else:
            kubeconfig = os.path.expanduser(kubeconfig)
        return KibanaEnvironment(
            url=env_config.get("url", ""),
            kubeconfig=kubeconfig,
            index_pattern=env_config.get("index_pattern", "app-logs-*"),
            namespace=env_config.get("namespace", "default"),
        )

    # Fallback to environment variables
    url = os.getenv(f"KIBANA_{env_key.upper()}_URL", "")
    if not url:
        raise ValueError(f"Kibana URL not configured. " f"Set KIBANA_{env_key.upper()}_URL or configure in config.json")

    return KibanaEnvironment(
        url=url,
        kubeconfig=get_kubeconfig(env_key),  # Use centralized kubeconfig resolution
        index_pattern="app-logs-*",
        namespace="default",
    )


# Cache for loaded environments
_KIBANA_ENV_CACHE: dict = {}


def get_cached_kibana_config(environment: str) -> "KibanaEnvironment | None":
    """Get Kibana environment config, with caching.

    Note: Named to avoid confusion with utils.get_env_config() which
    retrieves service config from config.json.
    """
    env_key = "production" if environment.lower() == "prod" else environment.lower()
    if env_key not in _KIBANA_ENV_CACHE:
        try:
            _KIBANA_ENV_CACHE[env_key] = get_kibana_environment(env_key)
        except ValueError:
            _KIBANA_ENV_CACHE[env_key] = None
    return _KIBANA_ENV_CACHE.get(env_key)


# Legacy alias for backward compatibility
KIBANA_ENVIRONMENTS = _KIBANA_ENV_CACHE


def get_token(kubeconfig: str) -> str:
    """Get OpenShift token from kubeconfig.

    Delegates to shared get_token_from_kubeconfig() which:
    - Tries oc whoami -t first (active sessions)
    - Falls back to kubectl config view
    - Supports all environment kubeconfigs (~/.kube/config.{s,p,e,k})
    """
    token = get_token_from_kubeconfig(kubeconfig)
    if not token:
        logger.warning(f"Failed to get token from {kubeconfig}")
    return token


async def kibana_request(
    environment: str,
    endpoint: str,
    method: str = "GET",
    data: dict | None = None,
) -> tuple[bool, dict | str]:
    """Make authenticated request to Kibana using shared HTTP client."""
    env_config = get_cached_kibana_config(environment)
    if not env_config:
        return (
            False,
            f"Unknown environment: {environment}. Configure in config.json or set KIBANA_{environment.upper()}_URL",
        )

    token = get_token(env_config.kubeconfig)
    if not token:
        return (
            False,
            f"No auth token. Run 'kube {env_config.kubeconfig.split('.')[-1]}' to authenticate",
        )

    client = kibana_client(env_config.url, token)
    try:
        if method == "GET":
            return await client.get(endpoint)
        else:
            return await client.post(endpoint, json=data)
    finally:
        await client.close()


def build_kibana_url(
    environment: str,
    query: str = "*",
    namespace: str = "",
    time_from: str = "now-1h",
    time_to: str = "now",
) -> str:
    """Build a Kibana Discover URL for the given parameters."""
    env_config = get_cached_kibana_config(environment)
    if not env_config:
        return ""

    base_url = env_config.url
    ns = namespace or env_config.namespace

    if ns and query == "*":
        full_query = f'kubernetes.namespace_name:"{ns}"'
    elif ns:
        full_query = f'kubernetes.namespace_name:"{ns}" AND ({query})'
    else:
        full_query = query

    params = {
        "_g": f"(time:(from:'{time_from}',to:'{time_to}'))",
        "_a": f"(query:(language:lucene,query:'{full_query}'))",
    }

    return f"{base_url}/app/discover#/?{urllib.parse.urlencode(params)}"


# ==================== SEARCH TOOLS ====================


def register_tools(server: "FastMCP") -> int:
    """Register tools with the MCP server."""
    registry = ToolRegistry(server)

    # ==================== TOOLS USED IN SKILLS ====================
    @auto_heal_stage()
    @registry.tool()
    async def kibana_search_logs(
        environment: str,
        query: str = "*",
        namespace: str = "",
        time_range: str = "1h",
        size: int = 100,
    ) -> list[TextContent]:
        """
        Search application logs in Kibana/Elasticsearch.

        Args:
            environment: "stage" or "production"
            query: Lucene query string (e.g., "level:error", "message:timeout")
            namespace: Kubernetes namespace (from config.json config)
            time_range: Time range like "15m", "1h", "24h", "7d"
            size: Max number of log entries to return

        Returns:
            Matching log entries.
        """
        env_config = get_cached_kibana_config(environment)
        if not env_config:
            return [TextContent(type="text", text=f"❌ Unknown environment: {environment}")]

        ns = namespace or env_config.namespace

        # Parse time range
        unit = time_range[-1]
        value = int(time_range[:-1])

        now = datetime.utcnow()
        if unit == "m":
            from_time = now - timedelta(minutes=value)
        elif unit == "h":
            from_time = now - timedelta(hours=value)
        elif unit == "d":
            from_time = now - timedelta(days=value)
        else:
            from_time = now - timedelta(hours=1)

        # Build Elasticsearch query via Kibana proxy
        es_query = {
            "query": {
                "bool": {
                    "must": [
                        {"query_string": {"query": query}},
                        {
                            "range": {
                                "@timestamp": {
                                    "gte": from_time.isoformat(),
                                    "lte": now.isoformat(),
                                }
                            }
                        },
                    ]
                }
            },
            "size": size,
            "sort": [{"@timestamp": {"order": "desc"}}],
        }

        if ns:
            es_query["query"]["bool"]["must"].append({"match": {"kubernetes.namespace_name": ns}})

        success, result = await kibana_request(
            environment,
            f"/api/console/proxy?path={env_config.index_pattern}/_search&method=POST",
            method="POST",
            data=es_query,
        )

        if not success:
            link = build_kibana_url(environment, query, ns, f"now-{time_range}", "now")
            return [
                TextContent(
                    type="text",
                    text=f"❌ Direct search failed: {result}\n\n**Open in Kibana:** {link}",
                )
            ]

        hits = result.get("hits", {}).get("hits", [])
        total = result.get("hits", {}).get("total", {})
        if isinstance(total, dict):
            total = total.get("value", 0)

        lines = [
            f"## Log Search: {environment}",
            "",
            f"**Query:** `{query}`",
            f"**Namespace:** `{ns}`",
            f"**Time Range:** Last {time_range}",
            f"**Results:** {len(hits)} of {total} total",
            "",
        ]

        if not hits:
            lines.append("No matching logs found.")
        else:
            lines.append("| Time | Level | Message |")
            lines.append("|------|-------|---------|")

            for hit in hits[:50]:
                source = hit.get("_source", {})
                timestamp = source.get("@timestamp", "")[:19]
                level = source.get("level", source.get("log", {}).get("level", "INFO"))
                message = source.get("message", source.get("log", ""))[:80]
                if len(message) == 80:
                    message += "..."
                lines.append(f"| {timestamp} | {level} | {message} |")

        link = build_kibana_url(environment, query, ns, f"now-{time_range}", "now")
        lines.extend(["", f"**[Open in Kibana]({link})**"])

        return [TextContent(type="text", text="\n".join(lines))]
