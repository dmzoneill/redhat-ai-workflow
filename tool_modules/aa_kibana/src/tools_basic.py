"""Kibana MCP Server - Log searching and analysis tools.

Provides 9 tools for searching and analyzing logs via Kibana.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastmcp import FastMCP
from mcp.types import TextContent

# Setup project path for server imports (must be before server imports)
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization

from server.auto_heal_decorator import auto_heal_stage
from server.tool_registry import ToolRegistry

from .common import build_kibana_url, get_cached_kibana_config, kibana_request

logger = logging.getLogger(__name__)

_RANGE_UNITS = {"m": "minutes", "h": "hours", "d": "days"}


def _time_window(time_range: str) -> tuple[datetime, datetime]:
    """Return (from, now) in UTC for a range like "15m", "1h" or "7d" (unknown units mean 1h)."""
    now = datetime.now(timezone.utc)
    unit_name = _RANGE_UNITS.get(time_range[-1])
    if unit_name is None:
        return now - timedelta(hours=1), now
    return now - timedelta(**{unit_name: int(time_range[:-1])}), now


def _hit_total(result: dict[str, Any]) -> Any:
    """Total hit count from an Elasticsearch response (ES 7+ wraps it in {"value": n})."""
    total = result.get("hits", {}).get("total", {})
    return total.get("value", 0) if isinstance(total, dict) else total


def _log_table(hits: list[dict[str, Any]]) -> list[str]:
    """Markdown table rows for up to 50 log hits."""
    if not hits:
        return ["No matching logs found."]
    lines = ["| Time | Level | Message |", "|------|-------|---------|"]
    for hit in hits[:50]:
        source = hit.get("_source", {})
        timestamp = source.get("@timestamp", "")[:19]
        level = source.get("level", source.get("log", {}).get("level", "INFO"))
        message = source.get("message", source.get("log", ""))[:80]
        if len(message) == 80:
            message += "..."
        lines.append(f"| {timestamp} | {level} | {message} |")
    return lines


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
        from_time, now = _time_window(time_range)

        # Build Elasticsearch query via Kibana proxy
        es_query: dict[str, Any] = {
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

        if not success or not isinstance(result, dict):
            link = build_kibana_url(environment, query, ns, f"now-{time_range}", "now")
            return [
                TextContent(
                    type="text",
                    text=f"❌ Direct search failed: {result}\n\n**Open in Kibana:** {link}",
                )
            ]

        hits = result.get("hits", {}).get("hits", [])

        lines = [
            f"## Log Search: {environment}",
            "",
            f"**Query:** `{query}`",
            f"**Namespace:** `{ns}`",
            f"**Time Range:** Last {time_range}",
            f"**Results:** {len(hits)} of {_hit_total(result)} total",
            "",
        ]

        lines.extend(_log_table(hits))

        link = build_kibana_url(environment, query, ns, f"now-{time_range}", "now")
        lines.extend(["", f"**[Open in Kibana]({link})**"])

        return [TextContent(type="text", text="\n".join(lines))]

    return registry.count  # Return number of tools registered
