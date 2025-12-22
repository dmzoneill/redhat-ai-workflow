"""Alertmanager MCP Server - Silence and alert management tools.

Provides 5 tools for Alertmanager silences and status.
"""

import asyncio
import logging
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

logger = logging.getLogger(__name__)



# ==================== Configuration ====================

def get_kubeconfig(environment: str) -> str:
    """Get kubeconfig path for environment."""
    kube_base = Path.home() / ".kube"
    env_map = {"production": "p", "prod": "p", "stage": "s"}
    cluster = env_map.get(environment.lower(), "s")
    return str(kube_base / f"config.{cluster}")


def get_alertmanager_url(environment: str) -> str:
    """Get Alertmanager URL for environment from config.json or env vars."""
    # Try to load from config.json first
    try:
        config_path = Path(__file__).parent.parent.parent.parent.parent / "config.json"
        if config_path.exists():
            import json
            with open(config_path) as f:
                config = json.load(f)
            env_key = "production" if environment.lower() == "prod" else environment.lower()
            url = config.get("alertmanager", {}).get("environments", {}).get(env_key, {}).get("url")
            if url:
                return url
    except Exception:
        pass
    # Fallback to environment variables
    urls = {
        "stage": os.getenv("ALERTMANAGER_STAGE_URL", ""),
        "production": os.getenv("ALERTMANAGER_PROD_URL", ""),
        "prod": os.getenv("ALERTMANAGER_PROD_URL", ""),
    }
    url = urls.get(environment.lower(), urls.get("stage", ""))
    if not url:
        raise ValueError(f"Alertmanager URL not configured. Set ALERTMANAGER_{environment.upper()}_URL or configure in config.json")
    return url


def get_alertmanager_token(kubeconfig: str) -> str:
    """Get OpenShift token from kubeconfig."""
    try:
        result = subprocess.run(
            ["kubectl", "config", "view", "--minify", "-o", 
             "jsonpath={.users[0].user.token}"],
            capture_output=True,
            text=True,
            env={"KUBECONFIG": kubeconfig},
            timeout=10,
        )
        return result.stdout.strip()
    except Exception as e:
        logger.warning(f"Failed to get token from {kubeconfig}: {e}")
        return ""


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


async def get_env_config(environment: str) -> tuple[str, str | None]:
    """Get URL and token for environment."""
    url = get_alertmanager_url(environment)
    kubeconfig = get_kubeconfig(environment)
    token = get_alertmanager_token(kubeconfig)
    return url, token


# ==================== TOOLS ====================

def register_tools(server: "FastMCP") -> int:
    """Register tools with the MCP server."""
    
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
        url, token = await get_env_config(environment)

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
        url, token = await get_env_config(environment)

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
                parsed_matchers.append({
                    "name": name.strip(),
                    "value": value.strip(),
                    "isRegex": True,
                    "isEqual": True,
                })
            elif "=" in m:
                name, value = m.split("=", 1)
                parsed_matchers.append({
                    "name": name.strip(),
                    "value": value.strip(),
                    "isRegex": False,
                    "isEqual": True,
                })

        if not parsed_matchers:
            return [TextContent(type="text", text="❌ Invalid matchers format. Use: alertname=MyAlert,namespace=myns")]

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
        url, token = await get_env_config(environment)

        success, result = await alertmanager_request(url, f"/silence/{silence_id}", method="DELETE", token=token)

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
        url, token = await get_env_config(environment)

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
        url, token = await get_env_config(environment)

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
            config_path = Path(__file__).parent.parent.parent.parent.parent / "config.json"
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

        return [TextContent(type="text", text=f"## Grafana Dashboard\n\n**URL:** {url}\n\n[Open Dashboard]({url})")]


    # ==================== ENTRY POINT ====================
    
    return len([m for m in dir() if not m.startswith('_')])  # Approximate count
