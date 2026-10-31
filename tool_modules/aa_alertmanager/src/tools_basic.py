"""Alertmanager MCP Server - Silence and alert management tools.

Provides 5 tools for Alertmanager silences and status.
"""

import logging
import os
from datetime import datetime, timedelta, timezone

from fastmcp import FastMCP
from mcp.types import TextContent

# Setup project path for server imports (must be before server imports)
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization

from server.auto_heal_decorator import auto_heal_stage
from server.config_manager import config as config_manager
from server.timeouts import parse_duration_to_minutes
from server.tool_registry import ToolRegistry

from .common import alertmanager_request, get_alertmanager_config

logger = logging.getLogger(__name__)


# ==================== TOOLS ====================


_SEVERITY_ICONS = {"critical": "🔴", "warning": "🟡", "info": "🔵"}


def _alerts_endpoint(silenced: bool, inhibited: bool) -> str:
    """The /alerts query for active alerts, with silenced/inhibited filters."""
    params = [
        f"silenced={'true' if silenced else 'false'}",
        f"inhibited={'true' if inhibited else 'false'}",
        "active=true",
    ]
    return "/alerts?" + "&".join(params)


def _alert_matches(alert: dict, filter_lower: str) -> bool:
    """Whether the alert's name, namespace, service, summary or description contains the filter."""
    labels = alert.get("labels", {})
    annotations = alert.get("annotations", {})
    searchable = " ".join(
        [
            str(labels.get("alertname", "")),
            str(labels.get("namespace", "")),
            str(labels.get("service", "")),
            str(annotations.get("summary", "")),
            str(annotations.get("description", "")),
        ]
    ).lower()
    return filter_lower in searchable


def _alert_lines(alert: dict) -> list[str]:
    """Markdown lines describing one alert."""
    labels = alert.get("labels", {})
    annotations = alert.get("annotations", {})
    severity = labels.get("severity", "unknown")
    namespace = labels.get("namespace", "")
    summary = annotations.get("summary", "")[:80]
    runbook = annotations.get("runbook_url", "")

    lines = [f"{_SEVERITY_ICONS.get(severity, '⚪')} **{labels.get('alertname', 'Unknown')}** ({severity})"]
    if namespace:
        lines.append(f"   Namespace: `{namespace}`")
    if summary:
        lines.append(f"   {summary}")
    lines.append(f"   Started: {alert.get('startsAt', '')[:19]}")
    if runbook:
        lines.append(f"   [Runbook]({runbook})")
    lines.append("")
    return lines


async def _alertmanager_alerts_impl(
    environment: str, filter_name: str, silenced: bool, inhibited: bool
) -> list[TextContent]:
    """Implementation of alertmanager_alerts tool."""
    url, token = await get_alertmanager_config(environment)

    success, result = await alertmanager_request(url, _alerts_endpoint(silenced, inhibited), token=token)

    if not success:
        return [TextContent(type="text", text=f"❌ Failed to get alerts: {result}")]

    if not isinstance(result, list):
        return [TextContent(type="text", text=f"⚠️ Unexpected response: {str(result)[:500]}")]

    alerts = result
    if filter_name:
        filter_lower = filter_name.lower()
        alerts = [a for a in alerts if _alert_matches(a, filter_lower)]

    if not alerts:
        return [
            TextContent(
                type="text",
                text=f"✅ No active alerts in {environment}" + (f" matching '{filter_name}'" if filter_name else ""),
            )
        ]

    lines = [f"## 🚨 Active Alerts in {environment}", f"**Count:** {len(alerts)}", ""]
    for a in alerts[:20]:
        lines.extend(_alert_lines(a))

    return [TextContent(type="text", text="\n".join(lines))]


def _utc_iso(moment: datetime) -> str:
    """Alertmanager timestamp: UTC ISO 8601 with a Z suffix."""
    return moment.astimezone(timezone.utc).replace(tzinfo=None).isoformat() + "Z"


def _parse_matchers(matchers: str) -> list[dict]:
    """Parse "name=value,name=~regex" into Alertmanager matcher dicts."""
    parsed = []
    for m in matchers.split(","):
        is_regex = "=~" in m
        if not is_regex and "=" not in m:
            continue
        name, value = m.split("=~" if is_regex else "=", 1)
        parsed.append({"name": name.strip(), "value": value.strip(), "isRegex": is_regex, "isEqual": True})
    return parsed


async def _alertmanager_create_silence_impl(
    matchers: str, duration: str, comment: str, environment: str
) -> list[TextContent]:
    """Implementation of alertmanager_create_silence tool."""
    url, token = await get_alertmanager_config(environment)

    # Parse duration using shared utility
    minutes = parse_duration_to_minutes(duration)

    now = datetime.now(timezone.utc)
    ends = now + timedelta(minutes=minutes)

    parsed_matchers = _parse_matchers(matchers)

    if not parsed_matchers:
        return [
            TextContent(
                type="text",
                text="❌ Invalid matchers format. Use: alertname=MyAlert,namespace=myns",
            )
        ]

    data = {
        "matchers": parsed_matchers,
        "startsAt": _utc_iso(now),
        "endsAt": _utc_iso(ends),
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
        f"**Duration:** {duration} (until {_utc_iso(ends)})",
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
        env_key = "production" if environment.lower() == "prod" else environment.lower()
        prom_url = (config_manager.get("prometheus") or {}).get("environments", {}).get(env_key, {}).get("url", "")
    except (AttributeError, TypeError, ValueError, OSError) as exc:
        logger.debug("Suppressed error: %s", exc)
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
