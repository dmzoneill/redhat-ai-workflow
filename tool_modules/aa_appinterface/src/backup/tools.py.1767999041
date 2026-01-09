"""App-Interface MCP Server - Qontract operations tools.

Provides 6 tools for working with app-interface GitOps configuration.
"""

import logging
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import load_config
from server.utils import run_cmd_full as run_cmd
from server.utils import truncate_output

# Setup project path for server imports
from tool_modules.common import PROJECT_ROOT  # noqa: F401 - side effect: adds to sys.path

logger = logging.getLogger(__name__)


# ==================== Configuration ====================


def find_app_interface_path() -> str:
    """Find app-interface repository path."""
    config = load_config()

    # Try app_interface section first
    app_interface = config.get("app_interface", {})
    if app_interface.get("path"):
        path = os.path.expanduser(app_interface["path"])
        if Path(path).exists():
            return path

    # Try repositories section
    repos = config.get("repositories", {})
    if "app-interface" in repos:
        path = repos["app-interface"].get("path", "")
        if path and Path(os.path.expanduser(path)).exists():
            return os.path.expanduser(path)

    # Try workspace_roots from paths section
    paths_cfg = config.get("paths", {})
    workspace_roots = paths_cfg.get("workspace_roots", [])
    for root in workspace_roots:
        candidate = Path(os.path.expanduser(root)) / "app-interface"
        if candidate.exists():
            return str(candidate)

    # Fallback to env var and common paths
    candidates = [
        Path(os.getenv("APP_INTERFACE_PATH", "")),
        Path("/opt/app-interface"),
    ]
    for c in candidates:
        if c and c.exists():
            return str(c)
    return ""


APP_INTERFACE_PATH = find_app_interface_path()


# ==================== TOOLS ====================


def register_tools(server: "FastMCP") -> int:
    """Register tools with the MCP server."""
    registry = ToolRegistry(server)

    @auto_heal()
    @registry.tool()
    async def appinterface_validate(path: str = "") -> list[TextContent]:
        """
        Run qontract validation on app-interface.

        Args:
            path: Path to app-interface repo (optional, uses default)

        Returns:
            Validation results.
        """
        repo_path = path or APP_INTERFACE_PATH
        if not repo_path or not os.path.isdir(repo_path):
            return [TextContent(type="text", text=f"❌ app-interface not found at {repo_path}")]

        lines = ["## App-Interface Validation", ""]

        if (Path(repo_path) / "Makefile").exists():
            success, stdout, stderr = await run_cmd(["make", "bundle", "validate"], cwd=repo_path, timeout=600)

            output = stdout + stderr

            if success:
                lines.append("✅ Validation passed")
            else:
                lines.append("❌ Validation failed")

            lines.append("```")
            lines.append(truncate_output(output, max_length=3000, mode="tail"))
            lines.append("```")
        else:
            lines.append("⚠️ No Makefile found, trying qontract-validator directly...")

            success, stdout, stderr = await run_cmd(["qontract-validator", "--only-errors"], cwd=repo_path)

            if success:
                lines.append("✅ Valid")
            else:
                lines.append("❌ Invalid")
                lines.append(f"```\n{stderr or stdout}\n```")

        return [TextContent(type="text", text="\n".join(lines))]

    @auto_heal()
    @registry.tool()
    async def appinterface_get_saas(
        service_name: str,
        path: str = "",
    ) -> list[TextContent]:
        """
        Get SaasFile for a service from app-interface.

        Args:
            service_name: Name of the service (e.g., "your-app")
            path: Path to app-interface repo (optional)

        Returns:
            SaasFile configuration.
        """
        repo_path = path or APP_INTERFACE_PATH
        if not repo_path or not os.path.isdir(repo_path):
            return [TextContent(type="text", text="❌ app-interface not found")]

        lines = [f"## SaasFile: `{service_name}`", ""]

        saas_dir = Path(repo_path) / "data/services"
        if not saas_dir.exists():
            saas_dir = Path(repo_path) / "data"

        matches = []
        for f in saas_dir.rglob("*.yml"):
            if service_name.lower() in f.name.lower() or service_name.lower() in str(f).lower():
                if "saas" in f.name.lower() or "saas" in str(f.parent).lower():
                    matches.append(f)

        if not matches:
            success, stdout, stderr = await run_cmd(
                ["grep", "-rl", service_name, str(saas_dir), "--include=*.yml"], cwd=repo_path
            )
            if success and stdout:
                for line in stdout.strip().split("\n")[:5]:
                    if line:
                        matches.append(Path(line))

        if not matches:
            return [TextContent(type="text", text=f"⚠️ No SaasFile found for `{service_name}`")]

        lines.append(f"Found {len(matches)} matching file(s):")
        lines.append("")

        for match in matches[:3]:
            try:
                rel_path = match.relative_to(repo_path)
            except ValueError:
                rel_path = match
            lines.append(f"### `{rel_path}`")

            try:
                content = match.read_text()
                lines.append("```yaml")
                lines.append(truncate_output(content, max_length=2000))
                lines.append("```")
            except Exception as e:
                lines.append(f"❌ Could not read: {e}")
            lines.append("")

        return [TextContent(type="text", text="\n".join(lines))]

    @auto_heal()
    @registry.tool()
    async def appinterface_diff(path: str = "") -> list[TextContent]:
        """
        Show what changes would be applied by qontract-reconcile.

        Args:
            path: Path to app-interface repo (optional)

        Returns:
            Diff of pending changes.
        """
        repo_path = path or APP_INTERFACE_PATH
        if not repo_path or not os.path.isdir(repo_path):
            return [TextContent(type="text", text="❌ app-interface not found")]

        lines = ["## App-Interface Changes", ""]

        success, stdout, stderr = await run_cmd(["git", "diff", "--stat"], cwd=repo_path)

        if success and stdout.strip():
            lines.append("### Modified Files")
            lines.append("```")
            lines.append(stdout)
            lines.append("```")
        else:
            lines.append("No uncommitted changes")
            return [TextContent(type="text", text="\n".join(lines))]

        success, stdout, stderr = await run_cmd(["git", "diff", "--", "*.yml", "*.yaml"], cwd=repo_path)

        if stdout.strip():
            lines.append("\n### YAML Changes")
            lines.append("```diff")
            lines.append(truncate_output(stdout, max_length=5000))
            lines.append("```")

        return [TextContent(type="text", text="\n".join(lines))]

    @auto_heal()
    @registry.tool()
    async def appinterface_resources(
        namespace: str,
        path: str = "",
    ) -> list[TextContent]:
        """
        List resources configured for a namespace in app-interface.

        Args:
            namespace: Kubernetes namespace name
            path: Path to app-interface repo (optional)

        Returns:
            Resources defined for the namespace.
        """
        repo_path = path or APP_INTERFACE_PATH
        if not repo_path or not os.path.isdir(repo_path):
            return [TextContent(type="text", text="❌ app-interface not found")]

        lines = [f"## Resources for `{namespace}`", ""]

        success, stdout, stderr = await run_cmd(
            ["grep", "-rl", f"name: {namespace}", repo_path, "--include=*.yml"], cwd=repo_path
        )

        if not success or not stdout.strip():
            success, stdout, stderr = await run_cmd(
                ["grep", "-rl", namespace, repo_path, "--include=*.yml"], cwd=repo_path
            )

        if success and stdout.strip():
            files = stdout.strip().split("\n")[:10]
            lines.append(f"Found in {len(files)} file(s):")
            lines.append("")

            for f in files:
                try:
                    rel_path = Path(f).relative_to(repo_path) if Path(f).is_absolute() else f
                except ValueError:
                    rel_path = f
                lines.append(f"- `{rel_path}`")

            for f in files:
                if "namespace" in f.lower():
                    try:
                        content = Path(f).read_text()

                        if "resourceTemplates" in content or "resources" in content:
                            lines.append(f"\n### Resources from `{Path(f).name}`")

                            import yaml

                            try:
                                docs = list(yaml.safe_load_all(content))
                                for doc in docs:
                                    if isinstance(doc, dict):
                                        resources = doc.get("resourceTemplates", []) or doc.get("resources", [])
                                        for r in resources[:10]:
                                            if isinstance(r, dict):
                                                name = r.get("name", "unnamed")
                                                lines.append(f"  - `{name}`")
                            except (yaml.YAMLError, KeyError, TypeError):
                                pass
                    except OSError:
                        pass
        else:
            lines.append(f"No files found mentioning `{namespace}`")

        return [TextContent(type="text", text="\n".join(lines))]

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
        repo_path = path or APP_INTERFACE_PATH
        if not repo_path or not os.path.isdir(repo_path):
            return [TextContent(type="text", text="❌ app-interface not found")]

        lines = [f"## Search: `{query}`", ""]

        success, stdout, stderr = await run_cmd(
            ["grep", "-rn", query, repo_path, f"--include=*.{file_type}", "-l"], cwd=repo_path
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

        success, stdout, stderr = await run_cmd(
            ["grep", "-rn", query, repo_path, f"--include=*.{file_type}", "-m", "3"], cwd=repo_path
        )

        if success and stdout:
            lines.append("```")
            lines.append(truncate_output(stdout, max_length=2000))
            lines.append("```")

        return [TextContent(type="text", text="\n".join(lines))]

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
        import urllib.error
        import urllib.request

        import yaml

        config = load_config()

        # Get URL template from config or use default
        slack_config = config.get("slack", {})
        user_mapping_config = slack_config.get("user_mapping", {})
        default_url = (
            "https://gitlab.cee.redhat.com/service/app-interface/" "-/raw/master/data/teams/{team}/users/{user}.yml"
        )
        url_template = user_mapping_config.get("app_interface_url", default_url)

        url = url_template.format(team=team, user=username)

        lines = [f"## User: `{username}`", ""]

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as response:
                content = response.read().decode("utf-8")

            data = yaml.safe_load(content)

            if isinstance(data, dict):
                lines.append("### Profile")

                name = data.get("name", username)
                lines.append(f"- **Name:** {name}")

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
                lines.append(truncate_output(yaml.dump(data, default_flow_style=False), max_length=1500))
                lines.append("```")
            else:
                lines.append(f"```yaml\n{truncate_output(content, max_length=2000)}\n```")

        except urllib.error.HTTPError as e:
            if e.code == 404:
                lines.append(f"⚠️ User `{username}` not found in team `{team}`")
                lines.append(f"URL tried: {url}")
                lines.append("")
                lines.append("Try a different team directory or check the username spelling.")
            else:
                lines.append(f"❌ HTTP Error: {e.code} {e.reason}")
        except Exception as e:
            lines.append(f"❌ Error fetching user info: {e}")

        return [TextContent(type="text", text="\n".join(lines))]

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
        repo_path = path or APP_INTERFACE_PATH
        if not repo_path or not os.path.isdir(repo_path):
            return [TextContent(type="text", text="❌ app-interface not found")]

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
            success, stdout, stderr = await run_cmd(
                ["grep", "-rl", "$schema.*cluster", repo_path, "--include=*.yml"], cwd=repo_path
            )

            if success and stdout:
                files = stdout.strip().split("\n")
                lines.append(f"Found {len(files)} cluster file(s)")
                for f in files[:20]:
                    lines.append(f"- `{Path(f).name}`")

        return [TextContent(type="text", text="\n".join(lines))]

    # ==================== ENTRY POINT ====================

    return registry.count
