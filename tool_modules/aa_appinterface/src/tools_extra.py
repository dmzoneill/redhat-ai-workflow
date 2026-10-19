"""App-Interface MCP Server - Qontract operations tools.

Provides 6 tools for working with app-interface GitOps configuration.
"""

import logging
import urllib.error
import urllib.request
from pathlib import Path

import yaml
from fastmcp import FastMCP
from mcp.types import TextContent
from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import load_config
from tool_modules.aa_appinterface.src.tools_basic import (
    _missing_repo,
    run_cmd,
    truncate_output,
)

logger = logging.getLogger(__name__)


# ==================== TOOLS ====================


async def _appinterface_clusters_impl(path: str) -> list[TextContent]:
    """Implementation of appinterface_clusters tool."""
    repo_path, missing = _missing_repo(path)
    if missing:
        return missing

    lines = ["## Clusters in app-interface", ""]

    clusters_dir = Path(repo_path) / "data/clusters"
    if clusters_dir.exists():
        clusters = list(clusters_dir.glob("*.yml"))
        lines.append(f"Found {len(clusters)} cluster(s):")
        lines.append("")

        for c in sorted(clusters)[:30]:
            lines.append(f"- `{c.stem}`")

        if len(clusters) > 30:
            lines.append(f"... and {len(clusters) - 30} more")
    else:
        success, stdout, _stderr = await run_cmd(
            ["grep", "-rl", "$schema.*cluster", repo_path, "--include=*.yml"],
            cwd=repo_path,
        )

        if success and stdout:
            files = stdout.strip().split("\n")
            lines.append(f"Found {len(files)} cluster file(s)")
            for f in files[:20]:
                lines.append(f"- `{Path(f).name}`")

    return [TextContent(type="text", text="\n".join(lines))]


def _user_profile_url(team: str, username: str) -> str:
    """Build the app-interface user YAML URL."""
    config = load_config()
    slack_config = config.get("slack", {})
    user_mapping_config = slack_config.get("user_mapping", {})
    default_url = (
        "https://gitlab.cee.redhat.com/service/app-interface/-/raw/master/"
        "data/teams/{team}/users/{user}.yml"
    )
    url_template = user_mapping_config.get("app_interface_url", default_url)
    return url_template.format(team=team, user=username)


def _append_user_profile(lines: list[str], data: dict, username: str) -> None:
    """Append profile fields parsed from a user document."""
    lines.append("### Profile")
    lines.append(f"- **Name:** {data.get('name', username)}")
    if "org_username" in data:
        lines.append(f"- **Kerberos:** {data['org_username']}")
    if "slack_username" in data:
        lines.append(f"- **Slack:** @{data['slack_username']}")
    if "github_username" in data:
        lines.append(f"- **GitHub:** @{data['github_username']}")
    if "redhat_email" in data or "mail" in data:
        email = data.get("redhat_email") or data.get("mail")
        lines.append(f"- **Email:** {email}")
    if "manager" in data:
        manager_ref = data["manager"]
        if isinstance(manager_ref, dict) and "$ref" in manager_ref:
            manager_name = manager_ref["$ref"].split("/")[-1].replace(".yml", "")
            lines.append(f"- **Manager:** {manager_name}")
    lines.append("")
    lines.append("### Raw YAML")
    lines.append("```yaml")
    lines.append(
        truncate_output(yaml.dump(data, default_flow_style=False), max_length=1500)
    )
    lines.append("```")


def _fetch_user_document(url: str) -> str:
    """Download a user YAML document."""
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.read().decode("utf-8")


async def _appinterface_get_user_impl(username: str, team: str) -> list[TextContent]:
    """Implementation of appinterface_get_user tool."""
    url = _user_profile_url(team, username)
    lines = [f"## User: `{username}`", ""]
    try:
        content = _fetch_user_document(url)
        data = yaml.safe_load(content)
        if isinstance(data, dict):
            _append_user_profile(lines, data, username)
        else:
            lines.append(f"```yaml\n{truncate_output(content, max_length=2000)}\n```")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            lines.append(f"⚠️ User `{username}` not found in team `{team}`")
            lines.append(f"URL tried: {url}")
            lines.append("")
            lines.append(
                "Try a different team directory or check the username spelling."
            )
        else:
            lines.append(f"❌ HTTP Error: {exc.code} {exc.reason}")
    except (
        urllib.error.URLError,
        yaml.YAMLError,
        OSError,
        UnicodeError,
        ValueError,
    ) as exc:
        lines.append(f"❌ Error fetching user info: {exc}")
    return [TextContent(type="text", text="\n".join(lines))]


async def _appinterface_search_impl(
    query: str, file_type: str, path: str
) -> list[TextContent]:
    """Search app-interface files for a term."""
    located = _missing_repo(path)
    if located[1] is not None:
        return located[1]
    repo_path = located[0]
    lines = [f"## Search: `{query}`", ""]

    success, stdout, _stderr = await run_cmd(
        ["grep", "-rn", query, repo_path, f"--include=*.{file_type}", "-l"],
        cwd=repo_path,
    )

    if not success or not stdout.strip():
        return [TextContent(type="text", text=f"No results for `{query}`")]

    files = stdout.strip().split("\n")
    lines.append(f"Found in {len(files)} file(s):")
    lines.append("")

    for f in files[:15]:
        try:
            rel_path = Path(f).relative_to(repo_path)
            lines.append(f"- `{rel_path}`")
        except ValueError:
            lines.append(f"- `{f}`")

    if len(files) > 15:
        lines.append(f"... and {len(files) - 15} more")

    lines.append("\n### Sample Matches")

    success, stdout, _stderr = await run_cmd(
        ["grep", "-rn", query, repo_path, f"--include=*.{file_type}", "-m", "3"],
        cwd=repo_path,
    )

    if success and stdout:
        lines.append("```")
        lines.append(truncate_output(stdout, max_length=2000))
        lines.append("```")

    return [TextContent(type="text", text="\n".join(lines))]


def register_tools(server: "FastMCP") -> int:
    """Register tools with the MCP server."""
    registry = ToolRegistry(server)

    # ==================== TOOLS NOT USED IN SKILLS ====================
    @auto_heal()
    @registry.tool()
    async def appinterface_clusters(path: str = "") -> list[TextContent]:
        """
        List clusters defined in app-interface.

        Args:
            path: Path to app-interface repo (optional)

        Returns:
            List of clusters.
        """
        return await _appinterface_clusters_impl(path)

    @auto_heal()
    @registry.tool()
    async def appinterface_get_user(
        username: str,
        team: str = "insights",
    ) -> list[TextContent]:
        """
        Get user information from app-interface.

        Fetches user YAML from app-interface GitLab which contains:
        - Slack username
        - GitLab username
        - Red Hat email
        - Manager info
        - Roles and permissions

        Args:
            username: GitLab/Kerberos username (e.g., 'bthomass', 'akarve')
            team: Team directory in app-interface (default: 'insights')

        Returns:
            User information from app-interface.
        """
        return await _appinterface_get_user_impl(username, team)

    @auto_heal()
    @registry.tool()
    async def appinterface_search(
        query: str,
        file_type: str = "yml",
        path: str = "",
    ) -> list[TextContent]:
        """
        Search app-interface for a term.

        Args:
            query: Search term
            file_type: File extension to search (yml, yaml, json)
            path: Path to app-interface repo (optional)

        Returns:
            Matching files and lines.
        """
        return await _appinterface_search_impl(query, file_type, path)

    return registry.count
