"""Prometheus Extra Tools - Advanced prometheus operations.

For basic operations, see tools_basic.py.

Tools included (~4):
- prometheus_query_range, prometheus_rules, prometheus_labels, ...
"""

import logging
import os  # noqa: F401
from datetime import datetime, timedelta
from pathlib import Path  # noqa: F401

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

from server.auto_heal_decorator import auto_heal_stage
from server.http_client import prometheus_client
from server.timeouts import parse_duration_to_minutes
from server.tool_registry import ToolRegistry
from server.utils import get_bearer_token, get_env_config, get_kubeconfig, get_service_url

# Setup project path for server imports
from tool_modules.common import PROJECT_ROOT  # noqa: F401 - side effect: adds to sys.path

logger = logging.getLogger(__name__)


# ==================== Configuration ====================
# Using shared utilities: get_service_url, get_bearer_token, get_env_config


async def prometheus_api_request(
    url: str,
    endpoint: str,
    params: dict | None = None,
    token: str | None = None,
    timeout: int = 30,
) -> tuple[bool, dict | str]:
    """Make a request to Prometheus API using shared HTTP client."""
    client = prometheus_client(url, token, timeout)
    try:
        return await client.get(endpoint, params=params)
    finally:
        await client.close()


async def get_prometheus_config(environment: str) -> tuple[str, str | None]:
    """Get URL and token for Prometheus environment.

    Uses shared utilities from server for config loading.
    Auto-refreshes auth if credentials are stale.
    """
    url = get_service_url("prometheus", environment)
    env_config = get_env_config(environment, "prometheus")
    kubeconfig = env_config.get("kubeconfig", get_kubeconfig(environment))
    token = await get_bearer_token(kubeconfig, environment=environment, auto_auth=True)
    return url, token


# ==================== INSTANT QUERIES ====================


def register_tools(server: FastMCP) -> int:
    """Register extra prometheus tools with the MCP server."""
    registry = ToolRegistry(server)

    @auto_heal_stage()
    @registry.tool()
    async def prometheus_query_range(
        query: str,
        environment: str = "stage",
        start: str = "",
        end: str = "",
        step: str = "1m",
        duration: str = "1h",
    ) -> list[TextContent]:
        """
        Execute a range PromQL query over time.

        Args:
            query: PromQL query string
            environment: Target environment (stage, production)
            start: Start time (ISO format or relative like "-1h"). Default: now - duration
            end: End time (ISO format or "now"). Default: now
            step: Query resolution (e.g., "1m", "5m", "1h")
            duration: Time range if start not specified (e.g., "1h", "6h", "1d")

        Returns:
            Time series data.
        """
        url, token = await get_prometheus_config(environment)

        now = datetime.now()

        if not end:
            end_time = now
        elif end == "now":
            end_time = now
        else:
            end_time = datetime.fromisoformat(end)

        if not start:
            minutes = parse_duration_to_minutes(duration)
            start_time = end_time - timedelta(minutes=minutes)
        else:
            start_time = datetime.fromisoformat(start)

        params = {
            "query": query,
            "start": start_time.timestamp(),
            "end": end_time.timestamp(),
            "step": step,
        }

        success, result = await prometheus_api_request(
            url,
            "/api/v1/query_range",
            params=params,
            token=token,
        )

        if not success:
            return [TextContent(type="text", text=f"❌ Query failed: {result}")]

        if result.get("status") != "success":
            error = result.get("error", "Unknown error")
            return [TextContent(type="text", text=f"❌ PromQL error: {error}")]

        data = result.get("data", {})
        results = data.get("result", [])

        if not results:
            return [TextContent(type="text", text=f"No results for range query: `{query}`")]

        lines = [
            f"## Range Query: `{query}`",
            f"**Environment:** {environment}",
            f"**Range:** {start_time.isoformat()} to {end_time.isoformat()}",
            f"**Step:** {step}",
            f"**Series:** {len(results)}",
            "",
        ]

        for item in results[:10]:
            metric = item.get("metric", {})
            values = item.get("values", [])

            metric_str = ", ".join(f'{k}="{v}"' for k, v in metric.items())
            lines.append(f"### `{{{metric_str}}}`")
            lines.append(f"Points: {len(values)}")

            if values:
                lines.append("```")
                for ts, val in values[:3]:
                    dt = datetime.fromtimestamp(ts)
                    lines.append(f"{dt.strftime('%H:%M:%S')}: {val}")
                if len(values) > 6:
                    lines.append("...")
                for ts, val in values[-3:]:
                    dt = datetime.fromtimestamp(ts)
                    lines.append(f"{dt.strftime('%H:%M:%S')}: {val}")
                lines.append("```")
            lines.append("")

        if len(results) > 10:
            lines.append(f"... and {len(results) - 10} more series")

        return [TextContent(type="text", text="\n".join(lines))]

    # ==================== ALERTS ====================

    @auto_heal_stage()
    @registry.tool()
    async def prometheus_rules(
        environment: str = "stage",
        rule_type: str = "",
        group: str = "",
    ) -> list[TextContent]:
        """
        Get alerting and recording rules from Prometheus.

        Args:
            environment: Target environment (stage, production)
            rule_type: Filter by type (alert, record, or empty for all)
            group: Filter by rule group name

        Returns:
            List of rules.
        """
        url, token = await get_prometheus_config(environment)

        params = {}
        if rule_type:
            params["type"] = rule_type

        success, result = await prometheus_api_request(url, "/api/v1/rules", params=params, token=token)

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to get rules: {result}")]

        if result.get("status") != "success":
            return [TextContent(type="text", text="❌ Failed to fetch rules")]

        groups = result.get("data", {}).get("groups", [])

        if group:
            groups = [g for g in groups if group.lower() in g.get("name", "").lower()]

        if not groups:
            return [TextContent(type="text", text=f"No rules found in {environment}")]

        lines = [f"## Rules in {environment}", f"**Groups:** {len(groups)}", ""]

        for g in groups[:10]:
            lines.append(f"### {g.get('name', 'Unknown')}")
            lines.append(f"File: `{g.get('file', 'N/A')}`")

            rules = g.get("rules", [])
            for rule in rules[:5]:
                rtype = rule.get("type", "unknown")
                name = rule.get("name", "Unknown")

                if rtype == "alerting":
                    state = rule.get("state", "unknown")
                    icon = {"firing": "🔴", "pending": "🟡", "inactive": "🟢"}.get(state, "❓")
                    lines.append(f"  {icon} `{name}` ({state})")
                else:
                    lines.append(f"  📊 `{name}` (recording)")

            if len(rules) > 5:
                lines.append(f"  ... and {len(rules) - 5} more rules")
            lines.append("")

        return [TextContent(type="text", text="\n".join(lines))]

    # ==================== TARGETS ====================

    @auto_heal_stage()
    @registry.tool()
    async def prometheus_labels(
        environment: str = "stage",
        label: str = "",
    ) -> list[TextContent]:
        """
        Get label names or values from Prometheus.

        Args:
            environment: Target environment (stage, production)
            label: If provided, get values for this label. Otherwise, list all labels.

        Returns:
            Label names or values.
        """
        url, token = await get_prometheus_config(environment)

        if label:
            endpoint = f"/api/v1/label/{label}/values"
        else:
            endpoint = "/api/v1/labels"

        success, result = await prometheus_api_request(url, endpoint, token=token)

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to get labels: {result}")]

        if result.get("status") != "success":
            return [TextContent(type="text", text="❌ Failed to fetch labels")]

        data = result.get("data", [])

        if label:
            lines = [
                f"## Values for label `{label}` in {environment}",
                f"**Count:** {len(data)}",
                "",
            ]
        else:
            lines = [f"## Labels in {environment}", f"**Count:** {len(data)}", ""]

        for val in data[:100]:
            lines.append(f"- `{val}`")
        if len(data) > 100:
            lines.append(f"... and {len(data) - 100} more")

        return [TextContent(type="text", text="\n".join(lines))]

    @auto_heal_stage()
    @registry.tool()
    async def prometheus_series(
        match: str,
        environment: str = "stage",
        limit: int = 20,
    ) -> list[TextContent]:
        """
        Find time series matching a label selector.

        Args:
            match: Label selector (e.g., '{job="api"}', 'up{namespace="your-app-stage"}')
            environment: Target environment (stage, production)
            limit: Maximum series to return

        Returns:
            Matching time series.
        """
        url, token = await get_prometheus_config(environment)

        success, result = await prometheus_api_request(
            url,
            "/api/v1/series",
            params={"match[]": match},
            token=token,
        )

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to get series: {result}")]

        if result.get("status") != "success":
            return [TextContent(type="text", text="❌ Failed to fetch series")]

        data = result.get("data", [])

        lines = [
            f"## Series matching `{match}` in {environment}",
            f"**Found:** {len(data)} series",
            "",
        ]

        for series in data[:limit]:
            metric_str = ", ".join(f'{k}="{v}"' for k, v in series.items())
            lines.append(f"- `{{{metric_str}}}`")

        if len(data) > limit:
            lines.append(f"... and {len(data) - limit} more")

        return [TextContent(type="text", text="\n".join(lines))]

    # ==================== COMMON QUERIES ====================

    return registry.count
