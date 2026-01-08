"""Kibana MCP Server - Log searching and analysis tools.

Provides 9 tools for searching and analyzing logs via Kibana.
"""

import logging
import os
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

from server.auto_heal_decorator import auto_heal_stage
from server.config import get_token_from_kubeconfig
from server.http_client import kibana_client
from server.tool_registry import ToolRegistry
from server.utils import get_kubeconfig, load_config

# Setup project path for server imports
from tool_modules.common import PROJECT_ROOT  # noqa: F401 - side effect: adds to sys.path

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
                        {"range": {"@timestamp": {"gte": from_time.isoformat(), "lte": now.isoformat()}}},
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

    @auto_heal_stage()
    @registry.tool()
    async def kibana_get_errors(
        environment: str,
        namespace: str = "",
        time_range: str = "1h",
        size: int = 50,
    ) -> list[TextContent]:
        """
        Get error logs from the specified environment.

        Args:
            environment: "stage" or "production"
            namespace: Kubernetes namespace (from config.json config)
            time_range: Time range like "15m", "1h", "24h"
            size: Max number of errors to return

        Returns:
            Error log entries.
        """
        query = "level:error OR level:ERROR OR log.level:error"
        return await kibana_search_logs(
            environment=environment,
            query=query,
            namespace=namespace,
            time_range=time_range,
            size=size,
        )

    @auto_heal_stage()
    @registry.tool()
    async def kibana_get_pod_logs(
        environment: str,
        pod_name: str,
        namespace: str = "",
        time_range: str = "30m",
        size: int = 200,
    ) -> list[TextContent]:
        """
        Get logs for a specific pod.

        Args:
            environment: "stage" or "production"
            pod_name: Pod name (can be partial, e.g., "backend-abc")
            namespace: Kubernetes namespace
            time_range: Time range
            size: Max entries

        Returns:
            Pod log entries.
        """
        query = f'kubernetes.pod_name:"{pod_name}*"'
        return await kibana_search_logs(
            environment=environment,
            query=query,
            namespace=namespace,
            time_range=time_range,
            size=size,
        )

    @auto_heal_stage()
    @registry.tool()
    async def kibana_trace_request(
        environment: str,
        request_id: str,
        namespace: str = "",
        time_range: str = "1h",
    ) -> list[TextContent]:
        """
        Trace a request across services by request ID / correlation ID.

        Args:
            environment: "stage" or "production"
            request_id: Request ID, trace ID, or correlation ID
            namespace: Kubernetes namespace
            time_range: Time range to search

        Returns:
            All log entries for this request.
        """
        query = (
            f'"{request_id}" OR request_id:"{request_id}" '
            f'OR trace_id:"{request_id}" OR correlation_id:"{request_id}"'
        )
        return await kibana_search_logs(
            environment=environment,
            query=query,
            namespace=namespace,
            time_range=time_range,
            size=500,
        )

    # ==================== LINK TOOLS ====================

    @auto_heal_stage()
    @registry.tool()
    async def kibana_get_link(
        environment: str,
        query: str = "*",
        namespace: str = "",
        time_range: str = "1h",
    ) -> list[TextContent]:
        """
        Get a Kibana URL for the given query (to share or open in browser).

        Args:
            environment: "stage" or "production"
            query: Lucene query string
            namespace: Kubernetes namespace
            time_range: Time range

        Returns:
            Clickable Kibana URL.
        """
        env_config = get_cached_kibana_config(environment)
        if not env_config:
            return [TextContent(type="text", text=f"❌ Unknown environment: {environment}")]

        ns = namespace or env_config.namespace
        link = build_kibana_url(environment, query, ns, f"now-{time_range}", "now")

        lines = [
            f"## Kibana Link: {environment}",
            "",
            f"**Query:** `{query}`",
            f"**Namespace:** `{ns}`",
            f"**Time Range:** Last {time_range}",
            "",
            f"**URL:** {link}",
            "",
            "Copy this link to share or open in browser.",
        ]

        return [TextContent(type="text", text="\n".join(lines))]

    @auto_heal_stage()
    @registry.tool()
    async def kibana_error_link(
        environment: str,
        namespace: str = "",
        time_range: str = "1h",
    ) -> list[TextContent]:
        """
        Get a Kibana URL filtered to errors only.

        Args:
            environment: "stage" or "production"
            namespace: Kubernetes namespace
            time_range: Time range

        Returns:
            Kibana URL filtered to error logs.
        """
        query = "level:error OR level:ERROR"
        return await kibana_get_link(environment, query, namespace, time_range)

    # ==================== STATUS TOOLS ====================

    @auto_heal_stage()
    @registry.tool()
    async def kibana_status(
        environment: str = "",
    ) -> list[TextContent]:
        """
        Check Kibana connectivity and authentication status.

        Args:
            environment: Specific environment or empty for all

        Returns:
            Connection status for each environment.
        """
        envs = [environment] if environment else ["stage", "production"]

        lines = ["## Kibana Status", ""]

        for env in envs:
            env_config = get_cached_kibana_config(env)
            if not env_config:
                lines.append(f"**{env}:** ❌ Unknown environment")
                continue

            token = get_token(env_config.kubeconfig)

            if not token:
                kube_suffix = env_config.kubeconfig.split(".")[-1]
                lines.append(f"**{env}:** ⚠️ Not authenticated - run `kube {kube_suffix}`")
                continue

            success, result = await kibana_request(env, "/api/status")

            if success:
                status = result.get("status", {}).get("overall", {}).get("state", "unknown")
                version = result.get("version", {}).get("number", "unknown")
                lines.append(f"**{env}:** ✅ Connected (v{version}, status: {status})")
                lines.append(f"  URL: {env_config.url}")
            else:
                lines.append(f"**{env}:** ❌ {result}")

        return [TextContent(type="text", text="\n".join(lines))]

    @auto_heal_stage()
    @registry.tool()
    async def kibana_index_patterns(
        environment: str,
    ) -> list[TextContent]:
        """
        List available index patterns in Kibana.

        Args:
            environment: "stage" or "production"

        Returns:
            List of index patterns.
        """
        success, result = await kibana_request(
            environment,
            "/api/saved_objects/_find?type=index-pattern&per_page=100",
        )

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to list index patterns: {result}")]

        patterns = result.get("saved_objects", [])

        lines = [f"## Index Patterns: {environment}", ""]

        if not patterns:
            lines.append("No index patterns found.")
        else:
            lines.append("| Pattern | Title |")
            lines.append("|---------|-------|")
            for p in patterns:
                attrs = p.get("attributes", {})
                title = attrs.get("title", "N/A")
                lines.append(f"| `{title}` | {attrs.get('name', title)} |")

        return [TextContent(type="text", text="\n".join(lines))]

    @auto_heal_stage()
    @registry.tool()
    async def kibana_list_dashboards(
        environment: str,
        search: str = "",
    ) -> list[TextContent]:
        """
        List saved dashboards in Kibana.

        Args:
            environment: "stage" or "production"
            search: Optional search term to filter dashboards

        Returns:
            List of available dashboards with links.
        """
        endpoint = "/api/saved_objects/_find?type=dashboard&per_page=50"
        if search:
            endpoint += f"&search={urllib.parse.quote(search)}"

        success, result = await kibana_request(environment, endpoint)

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to list dashboards: {result}")]

        dashboards = result.get("saved_objects", [])
        env_config = get_cached_kibana_config(environment)

        lines = [f"## Dashboards: {environment}", ""]

        if not dashboards:
            lines.append("No dashboards found.")
        else:
            for d in dashboards[:20]:
                dash_id = d.get("id", "")
                title = d.get("attributes", {}).get("title", "Untitled")
                url = f"{env_config.url}/app/dashboards#/view/{dash_id}"
                lines.append(f"- **{title}**: [Open]({url})")

        return [TextContent(type="text", text="\n".join(lines))]

    # ==================== ENTRY POINT ====================

    return registry.count
