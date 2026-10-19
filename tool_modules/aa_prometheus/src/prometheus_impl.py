"""Shared Prometheus query helpers and tool implementations."""

import logging
from datetime import datetime, timedelta

from mcp.types import TextContent

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from server.http_client import prometheus_client
from server.timeouts import parse_duration_to_minutes
from server.utils import (
    get_bearer_token,
    get_env_config,
    get_kubeconfig,
    get_service_url,
)

logger = logging.getLogger(__name__)


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


async def _shared_get_prometheus_config(environment: str) -> tuple[str, str | None]:
    """Get URL and token for Prometheus environment.

    Uses shared utilities from server for config loading.
    Auto-refreshes auth if credentials are stale.
    """
    url = get_service_url("prometheus", environment)
    env_config = get_env_config(environment, "prometheus")
    kubeconfig = env_config.get("kubeconfig", get_kubeconfig(environment))
    token = await get_bearer_token(kubeconfig, environment=environment, auto_auth=True)
    return url, token


async def get_prometheus_config(environment: str) -> tuple[str, str | None]:
    "Get prometheus config."
    return await _shared_get_prometheus_config(environment)


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

    msg = (
        annotations.get("message")
        or annotations.get("summary")
        or annotations.get("description")
        or ""
    )
    if len(msg) > 200:
        msg = msg[:200] + "..."

    return f"{icon} **{name}** {sev_icon} `{sev}`\n   Namespace: `{ns}`\n   {msg}"


async def _prometheus_alerts_impl(  # pylint: disable=too-many-branches,too-many-locals
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
            # pylint: disable-next=line-too-long
            f'sum(rate(container_cpu_usage_seconds_total{{namespace="{namespace}",pod=~"{pod}.*"}}[5m]))',
        ),
        (
            "Memory (MB)",
            # pylint: disable-next=line-too-long
            f'sum(container_memory_usage_bytes{{namespace="{namespace}",pod=~"{pod}.*"}}) / 1024 / 1024',
        ),
        (
            "Restarts",
            # pylint: disable-next=line-too-long
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


# pylint: disable-next=line-too-long
# pylint: disable-next=too-many-arguments,too-many-branches,too-many-locals,too-many-positional-arguments
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


async def _prometheus_rules_impl(  # pylint: disable=too-many-locals
    environment: str = "stage",
    rule_type: str = "",
    group: str = "",
) -> list[TextContent]:
    """Implementation of prometheus_rules tool."""
    url, token = await get_prometheus_config(environment)

    params = {}
    if rule_type:
        params["type"] = rule_type

    success, result = await prometheus_api_request(
        url, "/api/v1/rules", params=params, token=token
    )

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
                icon = {"firing": "🔴", "pending": "🟡", "inactive": "🟢"}.get(
                    state, "❓"
                )
                lines.append(f"  {icon} `{name}` ({state})")
            else:
                lines.append(f"  📊 `{name}` (recording)")

        if len(rules) > 5:
            lines.append(f"  ... and {len(rules) - 5} more rules")
        lines.append("")

    return [TextContent(type="text", text="\n".join(lines))]


async def _prometheus_check_health_impl(  # pylint: disable=too-many-locals
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
                # pylint: disable-next=line-too-long
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
    # Reuse prometheus_alerts implementation from tools_basic
    result = await _prometheus_alerts_impl(
        environment=environment, state="", namespace=namespace, severity=""
    )
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
        # pylint: disable-next=line-too-long
        "Memory (GB)": f'sum(container_memory_usage_bytes{{namespace="{namespace}"}}) / 1024 / 1024 / 1024',
        "Network RX (MB/s)": (
            # pylint: disable-next=line-too-long
            f'sum(rate(container_network_receive_bytes_total{{namespace="{namespace}"}}[5m])) / 1024 / 1024'
        ),
        "Network TX (MB/s)": (
            # pylint: disable-next=line-too-long
            f'sum(rate(container_network_transmit_bytes_total{{namespace="{namespace}"}}[5m])) / 1024 / 1024'
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
    # Load namespace from config.json
    namespace = ""
    try:
        from server.utils import load_config  # pylint: disable=import-outside-toplevel

        config = load_config()
        namespace = config.get("prometheus", {}).get("namespace", "")
    except Exception:  # pylint: disable=broad-exception-caught
        namespace = ""

    if not namespace:
        return [
            TextContent(
                type="text",
                # pylint: disable-next=line-too-long
                text="⚠️ No namespace configured for pre-deploy check. Set 'prometheus.namespace' in config.json.",
            )
        ]

    # Check for firing alerts
    result = await _prometheus_alerts_impl(
        environment=environment,
        state="firing",
        namespace=namespace,
        severity="",
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


async def _prometheus_targets_impl(  # pylint: disable=too-many-locals
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
        return [
            TextContent(
                type="text", text=f"No active targets{filter_msg} in {environment}"
            )
        ]

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
