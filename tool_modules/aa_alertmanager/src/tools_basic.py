"""Alertmanager MCP Server - Silence and alert management tools.

Provides 5 tools for Alertmanager silences and status.
"""

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

from server.auto_heal_decorator import auto_heal_stage
from server.http_client import alertmanager_client
from server.timeouts import parse_duration_to_minutes
from server.tool_registry import ToolRegistry
from server.utils import get_bearer_token, get_env_config, get_kubeconfig, get_service_url

# Setup project path for server imports
from tool_modules.common import PROJECT_ROOT  # noqa: F401 - side effect: adds to sys.path

logger = logging.getLogger(__name__)


# Using shared utilities: get_service_url, get_bearer_token, get_env_config


async def alertmanager_request(
    url: str,
    endpoint: str,
    method: str = "GET",
    data: dict | None = None,
    token: str | None = None,
    timeout: int = 30,
) -> tuple[bool, dict | str]:
    """Make a request to Alertmanager API using shared HTTP client."""
    client = alertmanager_client(url, token, timeout)
    try:
        if method == "GET":
            return await client.get(endpoint)
        elif method == "POST":
            return await client.post(endpoint, json=data)
        elif method == "DELETE":
            return await client.delete(endpoint)
        else:
            return False, f"Unsupported method: {method}"
    finally:
        await client.close()


async def get_alertmanager_config(environment: str) -> tuple[str, str | None]:
    """Get URL and token for Alertmanager environment.

    Uses shared utilities from server for config loading.
    Auto-refreshes auth if credentials are stale.
    """
    url = get_service_url("alertmanager", environment)
    env_config = get_env_config(environment, "alertmanager")
    kubeconfig = env_config.get("kubeconfig", get_kubeconfig(environment))
    token = await get_bearer_token(kubeconfig, environment=environment, auto_auth=True)
    return url, token


# ==================== TOOLS ====================


async def _alertmanager_alerts_impl(
    environment: str, filter_name: str, silenced: bool, inhibited: bool
) -> list[TextContent]:
    """Implementation of alertmanager_alerts tool."""
    url, token = await get_alertmanager_config(environment)

    # Build query params
    params = []
    if silenced:
        params.append("silenced=true")
    else:
        params.append("silenced=false")
    if inhibited:
        params.append("inhibited=true")
    else:
        params.append("inhibited=false")
    params.append("active=true")

    endpoint = "/alerts?" + "&".join(params)
    success, result = await alertmanager_request(url, endpoint, token=token)

    if not success:
        return [TextContent(type="text", text=f"❌ Failed to get alerts: {result}")]

    if not isinstance(result, list):
        return [TextContent(type="text", text=f"⚠️ Unexpected response: {str(result)[:500]}")]

    alerts = result

    # Filter by name if specified
    if filter_name:
        filter_lower = filter_name.lower()
        filtered = []
        for a in alerts:
            labels = a.get("labels", {})
            annotations = a.get("annotations", {})

            # Check alertname, namespace, and common labels/annotations
            searchable = " ".join(
                [
                    str(labels.get("alertname", "")),
                    str(labels.get("namespace", "")),
                    str(labels.get("service", "")),
                    str(annotations.get("summary", "")),
                    str(annotations.get("description", "")),
                ]
            ).lower()

            if filter_lower in searchable:
                filtered.append(a)
        alerts = filtered

    if not alerts:
        return [
            TextContent(
                type="text",
                text=f"✅ No active alerts in {environment}" + (f" matching '{filter_name}'" if filter_name else ""),
            )
        ]

    lines = [f"## 🚨 Active Alerts in {environment}", f"**Count:** {len(alerts)}", ""]

    for a in alerts[:20]:
        labels = a.get("labels", {})
        annotations = a.get("annotations", {})

        alertname = labels.get("alertname", "Unknown")
        severity = labels.get("severity", "unknown")
        namespace = labels.get("namespace", "")

        severity_icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(severity, "⚪")

        summary = annotations.get("summary", "")[:80]

        starts_at = a.get("startsAt", "")[:19]

        lines.append(f"{severity_icon} **{alertname}** ({severity})")
        if namespace:
            lines.append(f"   Namespace: `{namespace}`")
        if summary:
            lines.append(f"   {summary}")
        lines.append(f"   Started: {starts_at}")

        # Add runbook link if available
        runbook = annotations.get("runbook_url", "")
        if runbook:
            lines.append(f"   [Runbook]({runbook})")

        lines.append("")

    return [TextContent(type="text", text="\n".join(lines))]


async def _alertmanager_create_silence_impl(
    matchers: str, duration: str, comment: str, environment: str
) -> list[TextContent]:
    """Implementation of alertmanager_create_silence tool."""
    url, token = await get_alertmanager_config(environment)

    # Parse duration using shared utility
    minutes = parse_duration_to_minutes(duration)

    now = datetime.utcnow()
    ends = now + timedelta(minutes=minutes)

    # Parse matchers
    parsed_matchers = []
    for m in matchers.split(","):
        if "=~" in m:
            name, value = m.split("=~", 1)
            parsed_matchers.append(
                {
                    "name": name.strip(),
                    "value": value.strip(),
                    "isRegex": True,
                    "isEqual": True,
                }
            )
        elif "=" in m:
            name, value = m.split("=", 1)
            parsed_matchers.append(
                {
                    "name": name.strip(),
                    "value": value.strip(),
                    "isRegex": False,
                    "isEqual": True,
                }
            )

    if not parsed_matchers:
        return [
            TextContent(
                type="text",
                text="❌ Invalid matchers format. Use: alertname=MyAlert,namespace=myns",
            )
        ]

    data = {
        "matchers": parsed_matchers,
        "startsAt": now.isoformat() + "Z",
        "endsAt": ends.isoformat() + "Z",
        "createdBy": "mcp-workflow",
        "comment": comment,
    }

    success, result = await alertmanager_request(url, "/silences", method="POST", data=data, token=token)

    if not success:
        return [TextContent(type="text", text=f"❌ Failed to create silence: {result}")]

    silence_id = result.get("silenceID", "unknown") if isinstance(result, dict) else str(result)

    lines = [
        "## ✅ Silence Created",
        f"**ID:** `{silence_id}`",
        f"**Environment:** {environment}",
        f"**Duration:** {duration} (until {ends.isoformat()}Z)",
        f"**Matchers:** {matchers}",
        f"**Comment:** {comment}",
    ]

    return [TextContent(type="text", text="\n".join(lines))]


async def _alertmanager_delete_silence_impl(silence_id: str, environment: str) -> list[TextContent]:
    """Implementation of alertmanager_delete_silence tool."""
    url, token = await get_alertmanager_config(environment)

    success, result = await alertmanager_request(url, f"/silence/{silence_id}", method="DELETE", token=token)

    if not success:
        return [TextContent(type="text", text=f"❌ Failed to delete silence: {result}")]

    return [TextContent(type="text", text=f"✅ Silence `{silence_id}` deleted")]


async def _prometheus_grafana_link_impl(dashboard: str, namespace: str, environment: str) -> list[TextContent]:
    """Implementation of prometheus_grafana_link tool."""
    # Get Prometheus URL from config.json or env
    prom_url = ""
    try:
        config_path = Path(__file__).parent.parent.parent.parent / "config.json"
        if config_path.exists():
            import json

            with open(config_path) as f:
                config = json.load(f)
            env_key = "production" if environment.lower() == "prod" else environment.lower()
            prom_url = config.get("prometheus", {}).get("environments", {}).get(env_key, {}).get("url", "")
    except Exception:
        pass
    if not prom_url:
        prom_url = os.getenv(f"PROMETHEUS_{environment.upper()}_URL", "")
    if not prom_url:
        return [TextContent(type="text", text=f"❌ Prometheus URL not configured for {environment}")]
    grafana_url = prom_url.replace("prometheus", "grafana")

    params = []
    if namespace:
        params.append(f"var-namespace={namespace}")

    url = f"{grafana_url}/d/{dashboard}"
    if params:
        url += "?" + "&".join(params)

    return [
        TextContent(
            type="text",
            text=f"## Grafana Dashboard\n\n**URL:** {url}\n\n[Open Dashboard]({url})",
        )
    ]


def register_tools(server: "FastMCP") -> int:
    """Register tools with the MCP server."""
    registry = ToolRegistry(server)

    # ==================== TOOLS USED IN SKILLS ====================
    @auto_heal_stage()
    @registry.tool()
    async def alertmanager_alerts(
        environment: str = "stage",
        filter_name: str = "",
        silenced: bool = False,
        inhibited: bool = False,
    ) -> list[TextContent]:
        """
        List active alerts in Alertmanager.

        Args:
            environment: Target environment (stage, production)
            filter_name: Filter alerts by name containing this string (e.g., "Automation Analytics")
            silenced: Include silenced alerts (default: False)
            inhibited: Include inhibited alerts (default: False)

        Returns:
            List of active alerts with their details.
        """
        return await _alertmanager_alerts_impl(environment, filter_name, silenced, inhibited)

    @auto_heal_stage()
    @registry.tool()
    async def alertmanager_create_silence(
        matchers: str,
        duration: str = "2h",
        comment: str = "Silenced via MCP",
        environment: str = "stage",
    ) -> list[TextContent]:
        """
        Create a new silence in Alertmanager.

        Args:
            matchers: Label matchers as "name=value,name2=value2" or "alertname=MyAlert"
            duration: How long to silence (e.g., "2h", "1d", "30m")
            comment: Reason for silencing
            environment: Target environment (stage, production)

        Returns:
            Created silence ID.
        """
        return await _alertmanager_create_silence_impl(matchers, duration, comment, environment)

    @auto_heal_stage()
    @registry.tool()
    async def alertmanager_delete_silence(
        silence_id: str,
        environment: str = "stage",
    ) -> list[TextContent]:
        """
        Delete (expire) a silence.

        Args:
            silence_id: ID of the silence to delete
            environment: Target environment (stage, production)

        Returns:
            Confirmation of deletion.
        """
        return await _alertmanager_delete_silence_impl(silence_id, environment)

    @auto_heal_stage()
    @registry.tool()
    async def prometheus_grafana_link(
        dashboard: str = "overview",
        namespace: str = "",
        environment: str = "stage",
    ) -> list[TextContent]:
        """
        Generate a link to Grafana dashboard.

        Args:
            dashboard: Dashboard name/uid
            namespace: Namespace to filter on
            environment: Target environment (stage, production)

        Returns:
            Grafana dashboard URL.
        """
        return await _prometheus_grafana_link_impl(dashboard, namespace, environment)

    return registry.count
