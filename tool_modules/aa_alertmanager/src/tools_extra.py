"""Alertmanager MCP Server - Silence and alert management tools.

Provides 5 tools for Alertmanager silences and status,
plus 3 Grafana dashboard and annotation tools.
"""

import logging
import os
from datetime import datetime, timezone

from fastmcp import FastMCP

# Setup project path for server imports (must be before server imports)
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization

from mcp.types import TextContent

from server.auto_heal_decorator import auto_heal_stage
from server.http_client import grafana_client
from server.tool_registry import ToolRegistry
from server.utils import (
    get_bearer_token,
    get_env_config,
    get_kubeconfig,
    get_service_url,
)

from .common import alertmanager_request, get_alertmanager_config

logger = logging.getLogger(__name__)


async def get_grafana_config(environment: str) -> tuple[str, str | None]:
    """Get URL and token for Grafana environment.

    Resolution order:
    1. config.json grafana.environments.<env>.url
    2. Derive from Prometheus URL (replace 'prometheus' with 'grafana')
    3. GRAFANA_<ENV>_URL environment variable

    Uses the same Bearer token as Prometheus/Alertmanager (shared cluster auth).
    """
    env_key = "production" if environment.lower() == "prod" else environment.lower()

    # 1. Try config.json grafana section
    grafana_url = ""
    try:
        from server.config_manager import config as config_manager

        grafana_url = (
            (config_manager.get("grafana") or {})
            .get("environments", {})
            .get(env_key, {})
            .get("url", "")
        )
    except Exception as exc:
        logger.debug("Suppressed error: %s", exc)

    # 2. Fall back to deriving from Prometheus URL
    if not grafana_url:
        try:
            prom_url = get_service_url("prometheus", environment)
            grafana_url = prom_url.replace("prometheus", "grafana")
        except ValueError as exc:
            logger.debug("Invalid value encountered: %s", exc)

    # 3. Fall back to environment variable
    if not grafana_url:
        grafana_url = os.getenv(f"GRAFANA_{environment.upper()}_URL", "")

    if not grafana_url:
        raise ValueError(
            f"Grafana URL not configured for {environment}. "
            f"Set GRAFANA_{environment.upper()}_URL, configure grafana in config.json, "
            "or ensure Prometheus URL is configured (Grafana URL is derived from it)."
        )

    # Get token - try grafana-specific config first, fall back to prometheus config
    env_config = get_env_config(environment, "grafana")
    if not env_config.get("kubeconfig"):
        env_config = get_env_config(environment, "prometheus")
    kubeconfig = env_config.get("kubeconfig", get_kubeconfig(environment))
    token = await get_bearer_token(kubeconfig, environment=environment, auto_auth=True)

    return grafana_url, token


async def grafana_request(
    url: str,
    endpoint: str,
    method: str = "GET",
    data: dict | None = None,
    params: dict | None = None,
    token: str | None = None,
    timeout: int = 30,
) -> tuple[bool, dict | str]:
    """Make a request to Grafana API using shared HTTP client."""
    client = grafana_client(url, token, timeout)
    try:
        if method == "GET":
            return await client.get(endpoint, params=params)
        elif method == "POST":
            return await client.post(endpoint, json=data, params=params)
        else:
            return False, f"Unsupported method: {method}"
    finally:
        await client.close()


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


async def _alertmanager_silences_impl(
    environment: str, state: str
) -> list[TextContent]:
    """Implementation of alertmanager_silences tool."""
    url, token = await get_alertmanager_config(environment)
    success, result = await alertmanager_request(url, "/silences", token=token)

    if not success:
        return [TextContent(type="text", text=f"❌ Failed to get silences: {result}")]

    if not isinstance(result, list):
        return [
            TextContent(type="text", text=f"⚠️ Unexpected response: {str(result)[:500]}")
        ]

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


async def _grafana_dashboard_list_impl(
    environment: str, search: str, folder: str
) -> list[TextContent]:
    """Implementation of grafana_dashboard_list tool."""
    try:
        url, token = await get_grafana_config(environment)
    except ValueError as e:
        return [TextContent(type="text", text=f"Failed to get Grafana config: {e}")]

    params: dict[str, str] = {"type": "dash-db"}
    if search:
        params["query"] = search
    if folder:
        params["folderIds"] = folder

    success, result = await grafana_request(
        url, "/api/search", params=params, token=token
    )

    if not success:
        return [TextContent(type="text", text=f"Failed to list dashboards: {result}")]

    if not isinstance(result, list):
        return [
            TextContent(type="text", text=f"Unexpected response: {str(result)[:500]}")
        ]

    if not result:
        msg = f"No dashboards found in {environment}"
        if search:
            msg += f" matching '{search}'"
        return [TextContent(type="text", text=msg)]

    lines = [f"## Grafana Dashboards in {environment}", f"**Count:** {len(result)}", ""]

    for d in result[:30]:
        title = d.get("title", "Untitled")
        uid = d.get("uid", "N/A")
        folder_title = d.get("folderTitle", "General")
        dash_url = d.get("url", "")

        lines.append(f"- **{title}**")
        lines.append(f"  UID: `{uid}` | Folder: {folder_title}")
        if dash_url:
            full_url = (
                f"{url.rstrip('/')}{dash_url}" if dash_url.startswith("/") else dash_url
            )
            lines.append(f"  [Open]({full_url})")
        lines.append("")

    return [TextContent(type="text", text="\n".join(lines))]


async def _grafana_dashboard_get_impl(uid: str, environment: str) -> list[TextContent]:
    """Implementation of grafana_dashboard_get tool."""
    try:
        url, token = await get_grafana_config(environment)
    except ValueError as e:
        return [TextContent(type="text", text=f"Failed to get Grafana config: {e}")]

    success, result = await grafana_request(
        url, f"/api/dashboards/uid/{uid}", token=token
    )

    if not success:
        return [
            TextContent(type="text", text=f"Failed to get dashboard '{uid}': {result}")
        ]

    if not isinstance(result, dict):
        return [
            TextContent(type="text", text=f"Unexpected response: {str(result)[:500]}")
        ]

    meta = result.get("meta", {})
    dashboard = result.get("dashboard", {})

    title = dashboard.get("title", "Untitled")
    description = dashboard.get("description", "")
    dash_url = meta.get("url", "")
    folder_title = meta.get("folderTitle", "General")
    created = meta.get("created", "")[:19]
    updated = meta.get("updated", "")[:19]

    panels = dashboard.get("panels", [])

    lines = [
        f"## {title}",
        f"**UID:** `{uid}`",
        f"**Folder:** {folder_title}",
        f"**Created:** {created}",
        f"**Updated:** {updated}",
    ]

    if description:
        lines.append(f"**Description:** {description}")

    if dash_url:
        full_url = (
            f"{url.rstrip('/')}{dash_url}" if dash_url.startswith("/") else dash_url
        )
        lines.append(f"**URL:** [Open Dashboard]({full_url})")

    if panels:
        lines.append("")
        lines.append(f"### Panels ({len(panels)})")
        for p in panels[:25]:
            panel_title = p.get("title", "Untitled")
            panel_type = p.get("type", "unknown")
            panel_id = p.get("id", "N/A")
            lines.append(f"- **{panel_title}** (type: {panel_type}, id: {panel_id})")

    return [TextContent(type="text", text="\n".join(lines))]


async def _grafana_annotation_create_impl(
    text: str, tags: str, dashboard_uid: str, environment: str
) -> list[TextContent]:
    """Implementation of grafana_annotation_create tool."""
    try:
        url, token = await get_grafana_config(environment)
    except ValueError as e:
        return [TextContent(type="text", text=f"Failed to get Grafana config: {e}")]

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    data: dict = {
        "text": text,
        "time": now_ms,
        "timeEnd": now_ms,
    }

    if tags:
        data["tags"] = [t.strip() for t in tags.split(",") if t.strip()]

    if dashboard_uid:
        # Resolve dashboard ID from UID (annotations API needs the numeric ID)
        success, dash_result = await grafana_request(
            url, f"/api/dashboards/uid/{dashboard_uid}", token=token
        )
        if success and isinstance(dash_result, dict):
            dash_id = dash_result.get("dashboard", {}).get("id")
            if dash_id:
                data["dashboardId"] = dash_id

    success, result = await grafana_request(
        url, "/api/annotations", method="POST", data=data, token=token
    )

    if not success:
        return [TextContent(type="text", text=f"Failed to create annotation: {result}")]

    annotation_id = (
        result.get("id", "unknown") if isinstance(result, dict) else str(result)
    )
    message = (
        result.get("message", "Annotation created")
        if isinstance(result, dict)
        else "Annotation created"
    )

    lines = [
        "## Annotation Created",
        f"**ID:** `{annotation_id}`",
        f"**Environment:** {environment}",
        f"**Text:** {text}",
    ]
    if tags:
        lines.append(f"**Tags:** {tags}")
    if dashboard_uid:
        lines.append(f"**Dashboard:** `{dashboard_uid}`")
    lines.append(f"**Status:** {message}")

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
    async def alertmanager_silences(
        environment: str = "stage", state: str = ""
    ) -> list[TextContent]:
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

    # ==================== GRAFANA TOOLS ====================
    @auto_heal_stage()
    @registry.tool()
    async def grafana_dashboard_list(
        environment: str = "stage",
        search: str = "",
        folder: str = "",
    ) -> list[TextContent]:
        """
        List Grafana dashboards.

        Args:
            environment: Target environment (stage, production)
            search: Search query to filter dashboards
            folder: Filter by folder name

        Returns:
            List of dashboards with titles and UIDs.
        """
        return await _grafana_dashboard_list_impl(environment, search, folder)

    @auto_heal_stage()
    @registry.tool()
    async def grafana_dashboard_get(
        uid: str,
        environment: str = "stage",
    ) -> list[TextContent]:
        """
        Get a Grafana dashboard by UID.

        Args:
            uid: Dashboard UID
            environment: Target environment (stage, production)

        Returns:
            Dashboard details including title, panels, and URL.
        """
        return await _grafana_dashboard_get_impl(uid, environment)

    @auto_heal_stage()
    @registry.tool()
    async def grafana_annotation_create(
        text: str,
        tags: str = "",
        dashboard_uid: str = "",
        environment: str = "stage",
    ) -> list[TextContent]:
        """
        Create a Grafana annotation (e.g., for deployments).

        Args:
            text: Annotation text
            tags: Comma-separated tags (e.g., "deployment,release")
            dashboard_uid: Optional dashboard UID to scope the annotation
            environment: Target environment (stage, production)

        Returns:
            Confirmation of annotation creation.
        """
        return await _grafana_annotation_create_impl(
            text, tags, dashboard_uid, environment
        )

    return registry.count
