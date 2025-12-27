"""Alertmanager MCP Server - Silence and alert management tools.

Provides 5 tools for Alertmanager silences and status.
"""

import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

# Add aa-common to path for shared utilities
SERVERS_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(SERVERS_DIR / "aa-common"))

from src.utils import get_bearer_token, get_env_config, get_kubeconfig, get_service_url

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
    """Make a request to Alertmanager API."""
    import httpx

    base_url = url.rstrip("/")
    full_url = f"{base_url}/api/v2{endpoint}"

    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            if method == "GET":
                response = await client.get(full_url, headers=headers)
            elif method == "POST":
                response = await client.post(full_url, headers=headers, json=data)
            elif method == "DELETE":
                response = await client.delete(full_url, headers=headers)
            else:
                return False, f"Unsupported method: {method}"

            if response.status_code == 401:
                return False, "Authentication required"

            if response.status_code >= 400:
                return False, f"HTTP {response.status_code}: {response.text[:200]}"

            try:
                return True, response.json()
            except:
                return True, response.text
    except Exception as e:
        return False, str(e)


async def get_alertmanager_config(environment: str) -> tuple[str, str | None]:
    """Get URL and token for Alertmanager environment.

    Uses shared utilities from aa-common for config loading.
    """
    url = get_service_url("alertmanager", environment)
    env_config = get_env_config(environment, "alertmanager")
    kubeconfig = env_config.get("kubeconfig", get_kubeconfig(environment))
    token = await get_bearer_token(kubeconfig)
    return url, token


# ==================== TOOLS ====================


def register_tools(server: "FastMCP") -> int:
    """Register tools with the MCP server."""

    @server.tool()
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
                    text=f"✅ No active alerts in {environment}"
                    + (f" matching '{filter_name}'" if filter_name else ""),
                )
            ]

        lines = [f"## 🚨 Active Alerts in {environment}", f"**Count:** {len(alerts)}", ""]

        for a in alerts[:20]:
            labels = a.get("labels", {})
            annotations = a.get("annotations", {})
            _status = a.get("status", {})  # noqa: F841

            alertname = labels.get("alertname", "Unknown")
            severity = labels.get("severity", "unknown")
            namespace = labels.get("namespace", "")

            severity_icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(severity, "⚪")

            summary = annotations.get("summary", "")[:80]
            _description = annotations.get("description", "")[:100]  # noqa: F841

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

    @server.tool()
    async def alertmanager_silences(
        environment: str = "stage",
        state: str = "",
    ) -> list[TextContent]:
        """
        List active silences in Alertmanager.

        Args:
            environment: Target environment (stage, production)
            state: Filter by state (active, expired, pending, or empty for all)

        Returns:
            List of silences with their details.
        """
        url, token = await get_alertmanager_config(environment)

        success, result = await alertmanager_request(url, "/silences", token=token)

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to get silences: {result}")]

        if not isinstance(result, list):
            return [TextContent(type="text", text=f"⚠️ Unexpected response: {str(result)[:500]}")]

        silences = result
        if state:
            silences = [s for s in silences if s.get("status", {}).get("state") == state]

        if not silences:
            return [TextContent(type="text", text=f"No silences found in {environment}")]

        lines = [f"## Silences in {environment}", f"**Count:** {len(silences)}", ""]

        for s in silences[:20]:
            status = s.get("status", {})
            sil_state = status.get("state", "unknown")

            icon = {"active": "🔇", "expired": "⏰", "pending": "⏳"}.get(sil_state, "❓")

            created_by = s.get("createdBy", "unknown")
            comment = s.get("comment", "")
            starts = s.get("startsAt", "")[:19]
            ends = s.get("endsAt", "")[:19]

            matchers = s.get("matchers", [])
            matcher_strs = []
            for m in matchers:
                name = m.get("name", "")
                value = m.get("value", "")
                is_regex = m.get("isRegex", False)
                op = "=~" if is_regex else "="
                matcher_strs.append(f"{name}{op}{value}")

            lines.append(f"{icon} **{', '.join(matcher_strs[:3])}**")
            lines.append(f"   State: {sil_state} | By: {created_by}")
            lines.append(f"   From: {starts} To: {ends}")
            if comment:
                lines.append(f"   Comment: {comment[:100]}")
            lines.append(f"   ID: `{s.get('id', 'N/A')}`")
            lines.append("")

        return [TextContent(type="text", text="\n".join(lines))]

    @server.tool()
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
        url, token = await get_alertmanager_config(environment)

        # Parse duration
        duration_map = {"m": 1, "h": 60, "d": 1440}
        try:
            unit = duration[-1]
            amount = int(duration[:-1])
            minutes = amount * duration_map.get(unit, 60)
        except:
            minutes = 120

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

        success, result = await alertmanager_request(
            url, "/silences", method="POST", data=data, token=token
        )

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

    @server.tool()
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
        url, token = await get_alertmanager_config(environment)

        success, result = await alertmanager_request(
            url, f"/silence/{silence_id}", method="DELETE", token=token
        )

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to delete silence: {result}")]

        return [TextContent(type="text", text=f"✅ Silence `{silence_id}` deleted")]

    @server.tool()
    async def alertmanager_status(
        environment: str = "stage",
    ) -> list[TextContent]:
        """
        Get Alertmanager cluster status.

        Args:
            environment: Target environment (stage, production)

        Returns:
            Alertmanager status and cluster info.
        """
        url, token = await get_alertmanager_config(environment)

        success, result = await alertmanager_request(url, "/status", token=token)

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to get status: {result}")]

        lines = [f"## Alertmanager Status: {environment}", ""]

        if isinstance(result, dict):
            cluster = result.get("cluster", {})
            if cluster:
                lines.append("### Cluster")
                lines.append(f"- **Name:** {cluster.get('name', 'N/A')}")
                lines.append(f"- **Status:** {cluster.get('status', 'N/A')}")

                peers = cluster.get("peers", [])
                if peers:
                    lines.append(f"- **Peers:** {len(peers)}")

            version = result.get("versionInfo", {})
            if version:
                lines.append("\n### Version")
                lines.append(f"- **Version:** {version.get('version', 'N/A')}")

            uptime = result.get("uptime", "")
            if uptime:
                lines.append(f"\n**Uptime:** {uptime}")
        else:
            lines.append(f"```\n{result}\n```")

        return [TextContent(type="text", text="\n".join(lines))]

    @server.tool()
    async def alertmanager_receivers(
        environment: str = "stage",
    ) -> list[TextContent]:
        """
        List configured notification receivers.

        Args:
            environment: Target environment (stage, production)

        Returns:
            List of receivers.
        """
        url, token = await get_alertmanager_config(environment)

        success, result = await alertmanager_request(url, "/receivers", token=token)

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to get receivers: {result}")]

        lines = [f"## Receivers in {environment}", ""]

        if isinstance(result, list):
            for r in result:
                name = r.get("name", "unknown") if isinstance(r, dict) else str(r)
                lines.append(f"- `{name}`")
        else:
            lines.append(f"```\n{result}\n```")

        return [TextContent(type="text", text="\n".join(lines))]

    @server.tool()
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
        # Get Prometheus URL from config.json or env
        prom_url = ""
        try:
            config_path = Path(__file__).parent.parent.parent.parent / "config.json"
            if config_path.exists():
                import json

                with open(config_path) as f:
                    config = json.load(f)
                env_key = "production" if environment.lower() == "prod" else environment.lower()
                prom_url = (
                    config.get("prometheus", {})
                    .get("environments", {})
                    .get(env_key, {})
                    .get("url", "")
                )
        except Exception:
            pass
        if not prom_url:
            prom_url = os.getenv(f"PROMETHEUS_{environment.upper()}_URL", "")
        if not prom_url:
            return [
                TextContent(type="text", text=f"❌ Prometheus URL not configured for {environment}")
            ]
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

    # ==================== ENTRY POINT ====================

    return len([m for m in dir() if not m.startswith("_")])  # Approximate count
