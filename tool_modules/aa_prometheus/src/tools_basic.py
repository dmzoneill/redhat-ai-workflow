"""Prometheus MCP Server - Metrics and alerting tools.

Provides 14 tools for Prometheus queries, alerts, targets, and metrics.
"""

import logging
from datetime import datetime, timedelta

from fastmcp import FastMCP

# Setup project path for server imports (must be before server imports)
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization

from mcp.types import TextContent

from server.auto_heal_decorator import auto_heal_stage
from server.http_client import prometheus_client
from server.timeouts import parse_duration_to_minutes
from server.tool_registry import ToolRegistry
from server.utils import get_bearer_token, get_env_config, get_kubeconfig, get_service_url

# Setup project path for server imports


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


# ==================== TOOL IMPLEMENTATIONS ====================


def _format_alert(alert):
    """Format a single alert for display."""
    labels = alert.get("labels", {})
    annotations = alert.get("annotations", {})

    name = labels.get("alertname", "Unknown")
    sev = labels.get("severity", "unknown")
    ns = labels.get("namespace", "")
    state = alert.get("state", "unknown")

    icon = "🔴" if state == "firing" else "🟡"
    sev_icon = {"critical": "🚨", "warning": "⚠️", "info": "ℹ️"}.get(sev, "❓")

    msg = annotations.get("message") or annotations.get("summary") or annotations.get("description") or ""
    if len(msg) > 200:
        msg = msg[:200] + "..."

    return f"{icon} **{name}** {sev_icon} `{sev}`\n   Namespace: `{ns}`\n   {msg}"


async def _prometheus_alerts_impl(
    environment: str = "stage",
    state: str = "",
    namespace: str = "",
    severity: str = "",
) -> list[TextContent]:
    """Implementation of prometheus_alerts tool."""
    url, token = await get_prometheus_config(environment)

    success, result = await prometheus_api_request(
        url,
        "/api/v1/alerts",
        token=token,
    )

    if not success:
        return [TextContent(type="text", text=f"❌ Failed to get alerts: {result}")]

    if result.get("status") != "success":
        return [TextContent(type="text", text="❌ Failed to fetch alerts")]

    alerts = result.get("data", {}).get("alerts", [])

    # Filter alerts
    filtered = []
    for alert in alerts:
        labels = alert.get("labels", {})

        if state and alert.get("state") != state:
            continue
        if namespace and namespace not in labels.get("namespace", ""):
            continue
        if severity and labels.get("severity") != severity:
            continue

        filtered.append(alert)

    if not filtered:
        filters = []
        if state:
            filters.append(f"state={state}")
        if namespace:
            filters.append(f"namespace={namespace}")
        if severity:
            filters.append(f"severity={severity}")
        filter_str = ", ".join(filters) if filters else "none"
        return [
            TextContent(
                type="text",
                text=f"✅ No alerts matching filters ({filter_str}) in {environment}",
            )
        ]

    firing = [a for a in filtered if a.get("state") == "firing"]
    pending = [a for a in filtered if a.get("state") == "pending"]

    lines = [
        f"## Alerts in {environment}",
        f"**Firing:** {len(firing)} | **Pending:** {len(pending)}",
        "",
    ]

    if firing:
        lines.append("### 🔴 Firing")
        for alert in firing[:20]:
            lines.append(_format_alert(alert))
            lines.append("")

    if pending:
        lines.append("### 🟡 Pending")
        for alert in pending[:10]:
            lines.append(_format_alert(alert))
            lines.append("")

    return [TextContent(type="text", text="\n".join(lines))]


async def _prometheus_pod_health_impl(
    pod: str,
    namespace: str,
    environment: str = "stage",
) -> list[TextContent]:
    """Implementation of prometheus_pod_health tool."""
    url, token = await get_prometheus_config(environment)

    lines = [
        f"## Pod Health: `{pod}`",
        f"**Namespace:** {namespace} | **Environment:** {environment}",
        "",
    ]

    queries = [
        (
            "CPU Usage",
            f'sum(rate(container_cpu_usage_seconds_total{{namespace="{namespace}",pod=~"{pod}.*"}}[5m]))',
        ),
        (
            "Memory (MB)",
            f'sum(container_memory_usage_bytes{{namespace="{namespace}",pod=~"{pod}.*"}}) / 1024 / 1024',
        ),
        (
            "Restarts",
            f'sum(kube_pod_container_status_restarts_total{{namespace="{namespace}",pod=~"{pod}.*"}})',
        ),
        (
            "Ready",
            f'kube_pod_status_ready{{namespace="{namespace}",pod=~"{pod}.*",condition="true"}}',
        ),
    ]

    for name, query in queries:
        success, result = await prometheus_api_request(
            url,
            "/api/v1/query",
            params={"query": query},
            token=token,
        )

        if success and result.get("status") == "success":
            data = result.get("data", {}).get("result", [])
            if data:
                value = data[0].get("value", [None, "N/A"])
                if len(value) >= 2:
                    try:
                        val = float(value[1])
                        lines.append(f"- **{name}:** {val:.2f}")
                    except ValueError:
                        lines.append(f"- **{name}:** {value[1]}")
            else:
                lines.append(f"- **{name}:** No data")
        else:
            lines.append(f"- **{name}:** Query failed")

    return [TextContent(type="text", text="\n".join(lines))]


async def _prometheus_query_impl(
    query: str,
    environment: str = "stage",
) -> list[TextContent]:
    """Implementation of prometheus_query tool."""
    url, token = await get_prometheus_config(environment)

    success, result = await prometheus_api_request(
        url,
        "/api/v1/query",
        params={"query": query},
        token=token,
    )

    if not success:
        return [TextContent(type="text", text=f"❌ Query failed: {result}")]

    if result.get("status") != "success":
        error = result.get("error", "Unknown error")
        return [TextContent(type="text", text=f"❌ PromQL error: {error}")]

    data = result.get("data", {})
    result_type = data.get("resultType", "unknown")
    results = data.get("result", [])

    if not results:
        return [TextContent(type="text", text=f"No results for query: `{query}`")]

    lines = [
        f"## Query: `{query}`",
        f"**Environment:** {environment}",
        f"**Type:** {result_type}",
        "",
    ]

    for item in results[:50]:
        metric = item.get("metric", {})
        value = item.get("value", [None, "N/A"])

        metric_str = ", ".join(f'{k}="{v}"' for k, v in metric.items())
        if len(value) >= 2:
            lines.append(f"- `{{{metric_str}}}` = **{value[1]}**")
        else:
            lines.append(f"- `{{{metric_str}}}`")

    if len(results) > 50:
        lines.append(f"\n... and {len(results) - 50} more results")

    return [TextContent(type="text", text="\n".join(lines))]


async def _prometheus_query_range_impl(
    query: str,
    environment: str = "stage",
    start: str = "",
    end: str = "",
    step: str = "1m",
    duration: str = "1h",
) -> list[TextContent]:
    """Implementation of prometheus_query_range tool."""
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


async def _prometheus_rules_impl(
    environment: str = "stage",
    rule_type: str = "",
    group: str = "",
) -> list[TextContent]:
    """Implementation of prometheus_rules tool."""
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


def register_tools(server: "FastMCP") -> int:
    """Register tools with the MCP server."""
    registry = ToolRegistry(server)

    # ==================== TOOLS USED IN SKILLS ====================
    @auto_heal_stage()
    @registry.tool()
    async def prometheus_alerts(
        environment: str = "stage",
        state: str = "",
        namespace: str = "",
        severity: str = "",
    ) -> list[TextContent]:
        """
        Get current alerts from Prometheus.

        Args:
            environment: Target environment (stage, production)
            state: Filter by state (firing, pending, or empty for all)
            namespace: Filter by namespace
            severity: Filter by severity (critical, warning, info)

        Returns:
            List of alerts with details.
        """
        return await _prometheus_alerts_impl(environment, state, namespace, severity)

    @auto_heal_stage()
    @registry.tool()
    async def prometheus_pod_health(
        pod: str,
        namespace: str,
        environment: str = "stage",
    ) -> list[TextContent]:
        """
        Get health metrics for a specific pod.

        Args:
            pod: Pod name (can be partial, will match with regex)
            namespace: Kubernetes namespace
            environment: Target environment (stage, production)

        Returns:
            Pod CPU, memory, restarts, and status.
        """
        return await _prometheus_pod_health_impl(pod, namespace, environment)

    @auto_heal_stage()
    @registry.tool()
    async def prometheus_query(
        query: str,
        environment: str = "stage",
    ) -> list[TextContent]:
        """
        Execute an instant PromQL query.

        Args:
            query: PromQL query string (e.g., "up", "rate(http_requests_total[5m])")
            environment: Target environment (stage, production)

        Returns:
            Query results with metric values.

        Examples:
            - up{namespace="your-app-stage"}
            - rate(http_requests_total{namespace="your-app-stage"}[5m])
            - sum(container_memory_usage_bytes{namespace="your-app-stage"}) by (pod)
        """
        return await _prometheus_query_impl(query, environment)

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
        return await _prometheus_query_range_impl(query, environment, start, end, step, duration)

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
        return await _prometheus_rules_impl(environment, rule_type, group)

    return registry.count
