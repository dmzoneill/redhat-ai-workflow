"""Prometheus Basic Tools - Essential prometheus operations.

For advanced operations, see tools_extra.py.

Tools included (~9):
- prometheus_query, prometheus_alerts, prometheus_get_alerts, ...
"""

import logging
import os  # noqa: F401
from datetime import datetime, timedelta  # noqa: F401
from pathlib import Path  # noqa: F401

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

from server.auto_heal_decorator import auto_heal_stage
from server.http_client import prometheus_client
from server.timeouts import parse_duration_to_minutes  # noqa: F401
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
    """Register basic prometheus tools with the MCP server."""
    registry = ToolRegistry(server)

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

        def format_alert(alert):
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

        if firing:
            lines.append("### 🔴 Firing")
            for alert in firing[:20]:
                lines.append(format_alert(alert))
                lines.append("")

        if pending:
            lines.append("### 🟡 Pending")
            for alert in pending[:10]:
                lines.append(format_alert(alert))
                lines.append("")

        return [TextContent(type="text", text="\n".join(lines))]

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
        return await prometheus_alerts(environment=environment, state="firing", namespace=namespace)

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
        url, token = await get_prometheus_config(environment)

        success, result = await prometheus_api_request(url, "/api/v1/targets", token=token)

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to get targets: {result}")]

        if result.get("status") != "success":
            return [TextContent(type="text", text="❌ Failed to fetch targets")]

        active = result.get("data", {}).get("activeTargets", [])
        dropped = result.get("data", {}).get("droppedTargets", [])

        if state:
            active = [t for t in active if t.get("health") == state]

        up = len([t for t in active if t.get("health") == "up"])
        down = len([t for t in active if t.get("health") == "down"])

        lines = [
            f"## Targets in {environment}",
            f"**Up:** {up} | **Down:** {down} | **Dropped:** {len(dropped)}",
            "",
        ]

        down_targets = [t for t in active if t.get("health") == "down"]
        if down_targets:
            lines.append("### 🔴 Down Targets")
            for t in down_targets[:10]:
                job = t.get("labels", {}).get("job", "unknown")
                instance = t.get("labels", {}).get("instance", "unknown")
                error = t.get("lastError", "")
                lines.append(f"- **{job}** / `{instance}`")
                if error:
                    lines.append(f"  Error: {error[:100]}")
            lines.append("")

        up_targets = [t for t in active if t.get("health") == "up"]
        if up_targets:
            lines.append("### 🟢 Healthy Targets (by job)")
            jobs = {}
            for t in up_targets:
                job = t.get("labels", {}).get("job", "unknown")
                jobs[job] = jobs.get(job, 0) + 1

            for job, count in sorted(jobs.items()):
                lines.append(f"- **{job}**: {count} targets")

        return [TextContent(type="text", text="\n".join(lines))]

    # ==================== METADATA ====================

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
        url, token = await get_prometheus_config(environment)

        queries = {
            "CPU Usage": f'sum(rate(container_cpu_usage_seconds_total{{namespace="{namespace}"}}[5m])) by (pod)',
            "Memory Usage (MB)": f'sum(container_memory_usage_bytes{{namespace="{namespace}"}}) by (pod) / 1024 / 1024',
            "Pod Restarts": f'sum(kube_pod_container_status_restarts_total{{namespace="{namespace}"}}) by (pod)',
            "Request Rate": f'sum(rate(http_requests_total{{namespace="{namespace}"}}[5m])) by (pod)',
        }

        lines = [f"## Namespace Metrics: `{namespace}`", f"**Environment:** {environment}", ""]

        for name, query in queries.items():
            success, result = await prometheus_api_request(
                url,
                "/api/v1/query",
                params={"query": query},
                token=token,
            )

            lines.append(f"### {name}")

            if not success:
                lines.append(f"⚠️ Query failed: {result}")
                continue

            if result.get("status") != "success":
                lines.append("⚠️ No data")
                continue

            data = result.get("data", {}).get("result", [])
            if not data:
                lines.append("No data")
            else:
                for item in data[:10]:
                    pod = item.get("metric", {}).get("pod", "unknown")
                    value = item.get("value", [None, "N/A"])
                    if len(value) >= 2:
                        try:
                            val = float(value[1])
                            lines.append(f"- `{pod}`: **{val:.2f}**")
                        except ValueError:
                            lines.append(f"- `{pod}`: **{value[1]}**")

            lines.append("")

        return [TextContent(type="text", text="\n".join(lines))]

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
            f"**Environment:** {environment} | **Window:** {window}",
            "",
        ]

        if not success:
            lines.append(f"⚠️ Query failed: {result}")
            return [TextContent(type="text", text="\n".join(lines))]

        data = result.get("data", {}).get("result", [])

        if not data:
            lines.append("✅ No errors detected (or no HTTP metrics available)")
        else:
            total_error_rate = 0.0
            for item in data:
                code = item.get("metric", {}).get("code", "5xx")
                value = item.get("value", [None, "0"])
                try:
                    rate = float(value[1]) * 100
                    total_error_rate += rate
                    icon = "🔴" if rate > 1 else "🟡" if rate > 0.1 else "🟢"
                    lines.append(f"{icon} **{code}**: {rate:.2f}%")
                except (ValueError, IndexError):
                    pass

            lines.append("")
            if total_error_rate > 1:
                lines.append(f"⚠️ **Total error rate: {total_error_rate:.2f}%**")
            else:
                lines.append(f"✅ Total error rate: {total_error_rate:.2f}%")

        return [TextContent(type="text", text="\n".join(lines))]

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

    # ==================== ENTRY POINT ====================

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
        # Load namespace from config.json
        namespace = ""
        try:
            # Path: tools.py -> src -> aa_prometheus -> tool_modules -> redhat-ai-workflow
            config_path = Path(__file__).parent.parent.parent.parent / "config.json"
            if config_path.exists():
                import json

                with open(config_path) as f:
                    config = json.load(f)
                env_key = "production" if environment.lower() == "prod" else environment.lower()
                namespace = config.get("prometheus", {}).get("environments", {}).get(env_key, {}).get("namespace", "")
        except Exception:
            pass

        if not namespace:
            namespace = os.getenv(f"K8S_NAMESPACE_{environment.upper()}", "default")

        result = await prometheus_check_health(namespace=namespace, environment=environment)

        # Modify the output for pre-deploy context
        text = result[0].text
        if "is healthy" in text:
            text = text.replace("is healthy", "Pre-deploy check PASSED")
            text += "\n\nNo critical or warning alerts detected. Safe to proceed with deployment."
        else:
            text = text.replace("has issues", "Pre-deploy check FAILED")
            text += "\n\n⚠️ **Recommendation:** Resolve these alerts before deploying."

        return [TextContent(type="text", text=text)]

    # ==================== RULES ====================

    return registry.count
