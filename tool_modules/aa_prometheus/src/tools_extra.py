"""Prometheus MCP Server - Metrics and alerting tools.

Provides 14 tools for Prometheus queries, alerts, targets, and metrics.
"""

import logging

from mcp.server.fastmcp import FastMCP

# Setup project path for server imports (must be before server imports)
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization

from mcp.types import TextContent

from server.auto_heal_decorator import auto_heal_stage
from server.http_client import prometheus_client
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


async def _prometheus_check_health_impl(
    namespace: str,
    environment: str = "stage",
) -> list[TextContent]:
    """Implementation of prometheus_check_health tool."""
    url, token = await get_prometheus_config(environment)

    success, result = await prometheus_api_request(url, "/api/v1/alerts", token=token)

    if not success:
        return [TextContent(type="text", text=f"❌ Failed to check health: {result}")]

    alerts = result.get("data", {}).get("alerts", [])

    # Filter to namespace and non-info severity
    critical_alerts = []
    for alert in alerts:
        labels = alert.get("labels", {})
        if namespace not in labels.get("namespace", ""):
            continue
        if alert.get("state") != "firing":
            continue
        if labels.get("severity") in ["info"]:
            continue
        critical_alerts.append(alert)

    if not critical_alerts:
        return [
            TextContent(
                type="text",
                text=f"## ✅ {namespace} is healthy\n\nNo critical or warning alerts in {environment}.",
            )
        ]

    lines = [
        f"## ⚠️ {namespace} has issues",
        f"Found {len(critical_alerts)} alert(s) in {environment}:",
        "",
    ]

    for alert in critical_alerts:
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        name = labels.get("alertname", "Unknown")
        sev = labels.get("severity", "unknown")
        msg = annotations.get("message") or annotations.get("summary") or ""
        icon = "🔴" if sev == "critical" else "🟠"
        lines.append(f"- {icon} **{name}** ({sev})")
        if msg:
            lines.append(f"  {msg[:100]}")

    return [TextContent(type="text", text="\n".join(lines))]


async def _prometheus_error_rate_impl(
    namespace: str,
    environment: str = "stage",
    window: str = "5m",
) -> list[TextContent]:
    """Implementation of prometheus_error_rate tool."""
    url, token = await get_prometheus_config(environment)

    query = f"""
        sum(rate(http_requests_total{{namespace="{namespace}",code=~"5.."}}[{window}])) by (code)
        /
        sum(rate(http_requests_total{{namespace="{namespace}"}}[{window}]))
    """

    success, result = await prometheus_api_request(
        url,
        "/api/v1/query",
        params={"query": query},
        token=token,
    )

    lines = [
        f"## Error Rate: `{namespace}`",
        f"**Window:** {window} | **Environment:** {environment}",
        "",
    ]

    if not success or result.get("status") != "success":
        lines.append("⚠️ Query failed or no data")
        return [TextContent(type="text", text="\n".join(lines))]

    data = result.get("data", {}).get("result", [])
    if not data:
        lines.append("✅ No 5xx errors detected")
        return [TextContent(type="text", text="\n".join(lines))]

    for item in data:
        code = item.get("metric", {}).get("code", "unknown")
        value = item.get("value", [None, "0"])
        if len(value) >= 2:
            rate = float(value[1]) * 100  # Convert to percentage
            lines.append(f"- **{code}:** {rate:.2f}%")

    return [TextContent(type="text", text="\n".join(lines))]


async def _prometheus_get_alerts_impl(
    namespace: str,
    environment: str = "stage",
) -> list[TextContent]:
    """Implementation of prometheus_get_alerts tool."""
    # Re-use prometheus_alerts from tools_basic
    from .tools_basic import prometheus_alerts

    result = await prometheus_alerts(namespace=namespace, environment=environment)
    return result


async def _prometheus_labels_impl(
    environment: str = "stage",
    label: str = "__name__",
) -> list[TextContent]:
    """Implementation of prometheus_labels tool."""
    url, token = await get_prometheus_config(environment)

    success, result = await prometheus_api_request(
        url,
        f"/api/v1/label/{label}/values",
        token=token,
    )

    if not success:
        return [TextContent(type="text", text=f"❌ Failed to get labels: {result}")]

    if result.get("status") != "success":
        return [TextContent(type="text", text="❌ Failed to fetch labels")]

    values = result.get("data", [])

    if not values:
        return [TextContent(type="text", text=f"No values found for label `{label}`")]

    lines = [
        f"## Label Values: `{label}`",
        f"**Environment:** {environment}",
        f"**Count:** {len(values)}",
        "",
    ]

    for value in values[:50]:
        lines.append(f"- `{value}`")

    if len(values) > 50:
        lines.append(f"\n... and {len(values) - 50} more")

    return [TextContent(type="text", text="\n".join(lines))]


async def _prometheus_namespace_metrics_impl(
    namespace: str,
    environment: str = "stage",
) -> list[TextContent]:
    """Implementation of prometheus_namespace_metrics tool."""
    url, token = await get_prometheus_config(environment)

    queries = {
        "CPU Usage": f'sum(rate(container_cpu_usage_seconds_total{{namespace="{namespace}"}}[5m]))',
        "Memory (GB)": f'sum(container_memory_usage_bytes{{namespace="{namespace}"}}) / 1024 / 1024 / 1024',
        "Network RX (MB/s)": (
            f'sum(rate(container_network_receive_bytes_total{{namespace="{namespace}"}}[5m])) ' f"/ 1024 / 1024"
        ),
        "Network TX (MB/s)": (
            f'sum(rate(container_network_transmit_bytes_total{{namespace="{namespace}"}}[5m])) ' f"/ 1024 / 1024"
        ),
    }

    lines = [
        f"## Namespace Metrics: `{namespace}`",
        f"**Environment:** {environment}",
        "",
    ]

    for name, query in queries.items():
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


async def _prometheus_pre_deploy_check_impl(
    environment: str = "stage",
) -> list[TextContent]:
    """Implementation of prometheus_pre_deploy_check tool."""
    from .tools_basic import prometheus_alerts

    # Load namespace from config.json
    namespace = ""
    try:
        from server.utils import load_config

        config = load_config()
        namespace = config.get("prometheus", {}).get("namespace", "")
    except Exception:
        namespace = ""

    if not namespace:
        return [
            TextContent(
                type="text",
                text="⚠️ No namespace configured for pre-deploy check. Set 'prometheus.namespace' in config.json.",
            )
        ]

    # Check for firing alerts
    result = await prometheus_alerts(
        namespace=namespace,
        state="firing",
        environment=environment,
    )

    text = result[0].text if result else ""

    if "No alerts matching filters" in text or "healthy" in text:
        return [
            TextContent(
                type="text",
                text=(
                    f"## ✅ Pre-Deploy Check: PASSED\n\n{namespace} is ready for deployment "
                    f"in {environment}.\n\nNo firing alerts detected."
                ),
            )
        ]
    else:
        return [
            TextContent(
                type="text",
                text=(
                    f"## ⚠️ Pre-Deploy Check: WARNING\n\n{namespace} has firing alerts in "
                    f"{environment}.\n\n{text}\n\n**Recommendation:** Resolve alerts before deploying."
                ),
            )
        ]


async def _prometheus_series_impl(
    match: str,
    environment: str = "stage",
    limit: int = 100,
) -> list[TextContent]:
    """Implementation of prometheus_series tool."""
    url, token = await get_prometheus_config(environment)

    params = {"match[]": match, "limit": limit}

    success, result = await prometheus_api_request(
        url,
        "/api/v1/series",
        params=params,
        token=token,
    )

    if not success:
        return [TextContent(type="text", text=f"❌ Failed to get series: {result}")]

    if result.get("status") != "success":
        return [TextContent(type="text", text="❌ Failed to fetch series")]

    series = result.get("data", [])

    if not series:
        return [TextContent(type="text", text=f"No series found matching `{match}`")]

    lines = [
        f"## Series: `{match}`",
        f"**Environment:** {environment}",
        f"**Count:** {len(series)}",
        "",
    ]

    for item in series[:limit]:
        metric_str = ", ".join(f'{k}="{v}"' for k, v in item.items())
        lines.append(f"- `{{{metric_str}}}`")

    if len(series) > limit:
        lines.append(f"\n... and {len(series) - limit} more")

    return [TextContent(type="text", text="\n".join(lines))]


async def _prometheus_targets_impl(
    environment: str = "stage",
    state: str = "",
) -> list[TextContent]:
    """Implementation of prometheus_targets tool."""
    url, token = await get_prometheus_config(environment)

    success, result = await prometheus_api_request(
        url,
        "/api/v1/targets",
        token=token,
    )

    if not success:
        return [TextContent(type="text", text=f"❌ Failed to get targets: {result}")]

    if result.get("status") != "success":
        return [TextContent(type="text", text="❌ Failed to fetch targets")]

    active_targets = result.get("data", {}).get("activeTargets", [])

    # Filter by state if specified
    if state:
        active_targets = [t for t in active_targets if t.get("health") == state]

    if not active_targets:
        filter_msg = f" with state={state}" if state else ""
        return [TextContent(type="text", text=f"No active targets{filter_msg} in {environment}")]

    # Count by health
    up = len([t for t in active_targets if t.get("health") == "up"])
    down = len([t for t in active_targets if t.get("health") == "down"])
    unknown = len(active_targets) - up - down

    lines = [
        f"## Prometheus Targets: {environment}",
        f"**Up:** {up} | **Down:** {down} | **Unknown:** {unknown}",
        "",
    ]

    # Show down targets first
    down_targets = [t for t in active_targets if t.get("health") == "down"]
    if down_targets:
        lines.append("### ⚠️ Down Targets")
        for target in down_targets[:10]:
            job = target.get("labels", {}).get("job", "unknown")
            instance = target.get("labels", {}).get("instance", "unknown")
            error = target.get("lastError", "No error message")
            lines.append(f"- **{job}** / `{instance}`")
            lines.append(f"  Error: {error[:100]}")

    return [TextContent(type="text", text="\n".join(lines))]


def register_tools(server: "FastMCP") -> int:
    """Register tools with the MCP server."""
    registry = ToolRegistry(server)

    # ==================== TOOLS NOT USED IN SKILLS ====================
    @auto_heal_stage()
    @registry.tool()
    async def prometheus_check_health(
        namespace: str,
        environment: str = "stage",
    ) -> list[TextContent]:
        """
        Check if a namespace is healthy (no critical/warning alerts).

        Args:
            namespace: Namespace pattern to check (e.g., "your-app-stage")
            environment: "stage" or "prod"

        Returns:
            Health status and any firing alerts.
        """
        return await _prometheus_check_health_impl(namespace, environment)

    @auto_heal_stage()
    @registry.tool()
    async def prometheus_error_rate(
        namespace: str,
        environment: str = "stage",
        window: str = "5m",
    ) -> list[TextContent]:
        """
        Get HTTP error rates for a namespace.

        Args:
            namespace: Kubernetes namespace
            environment: Target environment (stage, production)
            window: Time window for rate calculation (e.g., "5m", "15m", "1h")

        Returns:
            Error rates by status code.
        """
        return await _prometheus_error_rate_impl(namespace, environment, window)

    @auto_heal_stage()
    @registry.tool()
    async def prometheus_get_alerts(
        environment: str = "stage",
        namespace: str = "",
    ) -> list[TextContent]:
        """
        Get firing alerts from Prometheus (simplified view).

        Args:
            environment: "stage" or "prod"
            namespace: Optional namespace filter (e.g., "your-app")

        Returns:
            List of firing alerts.
        """
        return await _prometheus_get_alerts_impl(namespace, environment)

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
        return await _prometheus_labels_impl(environment, label)

    @auto_heal_stage()
    @registry.tool()
    async def prometheus_namespace_metrics(
        namespace: str,
        environment: str = "stage",
    ) -> list[TextContent]:
        """
        Get key metrics for a Kubernetes namespace.

        Args:
            namespace: Kubernetes namespace (e.g., "your-app-stage")
            environment: Target environment (stage, production)

        Returns:
            CPU, memory, and request metrics for the namespace.
        """
        return await _prometheus_namespace_metrics_impl(namespace, environment)

    @auto_heal_stage()
    @registry.tool()
    async def prometheus_pre_deploy_check(
        environment: str = "stage",
    ) -> list[TextContent]:
        """
        Run pre-deployment checks for the application.

        Args:
            environment: "stage" or "prod"

        Returns:
            Whether it's safe to deploy based on current alerts.
        """
        return await _prometheus_pre_deploy_check_impl(environment)

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
        return await _prometheus_series_impl(match, environment, limit)

    @auto_heal_stage()
    @registry.tool()
    async def prometheus_targets(
        environment: str = "stage",
        state: str = "",
    ) -> list[TextContent]:
        """
        Get scrape targets and their health status.

        Args:
            environment: Target environment (stage, production)
            state: Filter by state (up, down, unknown, or empty for all)

        Returns:
            List of targets with health status.
        """
        return await _prometheus_targets_impl(environment, state)

    return registry.count
