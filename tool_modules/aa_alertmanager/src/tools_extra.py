"""Alertmanager MCP Server - Silence and alert management tools.

Provides 5 tools for Alertmanager silences and status.
"""

import logging

from fastmcp import FastMCP

# Setup project path for server imports (must be before server imports)
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization

from mcp.types import TextContent

from server.auto_heal_decorator import auto_heal_stage
from server.http_client import alertmanager_client
from server.tool_registry import ToolRegistry
from server.utils import get_bearer_token, get_env_config, get_kubeconfig, get_service_url

# Setup project path for server imports


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


async def _alertmanager_receivers_impl(environment: str) -> list[TextContent]:
    """Implementation of alertmanager_receivers tool."""
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


async def _alertmanager_silences_impl(environment: str, state: str) -> list[TextContent]:
    """Implementation of alertmanager_silences tool."""
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


async def _alertmanager_status_impl(environment: str) -> list[TextContent]:
    """Implementation of alertmanager_status tool."""
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


def register_tools(server: "FastMCP") -> int:
    """Register tools with the MCP server."""
    registry = ToolRegistry(server)

    # ==================== TOOLS NOT USED IN SKILLS ====================
    @auto_heal_stage()
    @registry.tool()
    async def alertmanager_receivers(environment: str = "stage") -> list[TextContent]:
        """
        List configured notification receivers.

        Args:
            environment: Target environment (stage, production)

        Returns:
            List of receivers.
        """
        return await _alertmanager_receivers_impl(environment)

    @auto_heal_stage()
    @registry.tool()
    async def alertmanager_silences(environment: str = "stage", state: str = "") -> list[TextContent]:
        """
        List active silences in Alertmanager.

        Args:
            environment: Target environment (stage, production)
            state: Filter by state (active, expired, pending, or empty for all)

        Returns:
            List of silences with their details.
        """
        return await _alertmanager_silences_impl(environment, state)

    @auto_heal_stage()
    @registry.tool()
    async def alertmanager_status(environment: str = "stage") -> list[TextContent]:
        """
        Get Alertmanager cluster status.

        Args:
            environment: Target environment (stage, production)

        Returns:
            Alertmanager status and cluster info.
        """
        return await _alertmanager_status_impl(environment)

    return registry.count
