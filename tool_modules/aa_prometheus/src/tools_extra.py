"""Prometheus Extra Tools - Advanced prometheus operations.

For basic operations, see tools_basic.py.

Tools included (~5):
- prometheus_query_range, prometheus_pre_deploy_check, prometheus_rules, prometheus_labels, prometheus_series
"""

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

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
