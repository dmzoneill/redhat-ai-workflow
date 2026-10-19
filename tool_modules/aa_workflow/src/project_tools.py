# pylint: disable=duplicate-code,cyclic-import
"""Project Tools - Manage projects in config.json.

Provides tools for:
- project_list: List all configured projects
- project_add: Add a new project to config.json
- project_remove: Remove a project from config.json
- project_detect: Auto-detect project settings from a directory
"""

import json
import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from mcp.types import TextContent

from server.config_manager import config as config_manager
from server.tool_registry import ToolRegistry

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = logging.getLogger(__name__)

# Required fields for a repository entry
REQUIRED_FIELDS = ["path", "gitlab", "jira_project", "default_branch"]

# Optional fields with defaults
OPTIONAL_FIELDS = {
    "jira_component": "",
    "lint_command": "",
    "test_command": "",
    "test_setup": "",
    "konflux_namespace": "",
    "scopes": [],
    "docs": None,
}


# ==================== HELPER FUNCTIONS ====================


def _load_config() -> dict:
    """Load config.json using ConfigManager."""
    return config_manager.get_all()


def _save_config(config: dict) -> bool:
    """Save config.json using ConfigManager.

    Note: This replaces the entire config. For partial updates,
    use config_manager.update_section() instead.
    """
    try:
        # Update each section
        for section, data in config.items():
            config_manager.update_section(section, data, merge=False)
        config_manager.flush()
        return True
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        logger.error("Failed to save config: %s", exc)
        return False


def _detect_language(project_path: Path) -> str:
    """Detect project language from config files."""
    if (project_path / "pyproject.toml").exists() or (
        project_path / "setup.py"
    ).exists():
        return "python"
    if (project_path / "package.json").exists():
        return "javascript"
    if (project_path / "go.mod").exists():
        return "go"
    if (project_path / "Cargo.toml").exists():
        return "rust"
    if (project_path / "pom.xml").exists():
        return "java"
    return "unknown"


def _detect_default_branch(project_path: Path) -> str:
    """Detect default branch from git."""
    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            # refs/remotes/origin/main -> main
            return result.stdout.strip().split("/")[-1]
    except (subprocess.SubprocessError, OSError) as e:
        logger.debug("Suppressed error in _detect_default_branch (symbolic-ref): %s", e)

    # Fallback: check if main or master exists
    try:
        result = subprocess.run(
            ["git", "branch", "-r"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            branches = result.stdout
            if "origin/main" in branches:
                return "main"
            if "origin/master" in branches:
                return "master"
    except (subprocess.SubprocessError, OSError) as e:
        logger.debug("Suppressed error in _detect_default_branch (branch list): %s", e)

    return "main"  # Default


def _detect_gitlab_remote(project_path: Path) -> str | None:
    """Detect GitLab project path from git remote."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            # Parse various URL formats
            # git@gitlab.cee.redhat.com:org/repo.git
            # https://gitlab.cee.redhat.com/org/repo.git
            if "gitlab" in url:
                if url.startswith("git@"):
                    # git@gitlab.cee.redhat.com:org/repo.git
                    path = url.split(":")[-1]
                else:
                    # https://gitlab.cee.redhat.com/org/repo.git
                    path = "/".join(url.split("/")[-2:])
                # Remove .git suffix
                if path.endswith(".git"):
                    path = path[:-4]
                return path
    except (subprocess.SubprocessError, OSError) as e:
        logger.debug("Suppressed error in _detect_gitlab_remote: %s", e)
    return None


def _python_lint_command(project_path: Path) -> str:
    """Detect a Python lint command from project config."""
    pyproject = project_path / "pyproject.toml"
    if not pyproject.exists():
        return "black --check . && flake8 ."
    content = pyproject.read_text()
    commands = []
    if "black" in content or (project_path / ".black").exists():
        commands.append("black --check .")
    if "flake8" in content or (project_path / ".flake8").exists():
        commands.append("flake8 .")
    if "ruf" in content or (project_path / "ruff.toml").exists():
        commands.append("ruff check .")
    if commands:
        return " && ".join(commands)
    return "black --check . && flake8 ."


def _package_script(project_path: Path, *script_names: str, default: str) -> str:
    """Return an npm script command when package.json defines one of the names."""
    package_json = project_path / "package.json"
    if not package_json.exists():
        return default
    try:
        with open(package_json, encoding="utf-8") as handle:
            scripts = json.load(handle).get("scripts", {})
    except (json.JSONDecodeError, OSError) as exc:
        logger.debug("Suppressed error reading package.json: %s", exc)
        return default
    for name in script_names:
        if name in scripts:
            return f"npm run {name}" if name != "test" else "npm test"
    return default


def _detect_lint_command(project_path: Path, language: str) -> str:
    """Detect lint command based on project type."""
    if language == "python":
        return _python_lint_command(project_path)
    if language == "javascript":
        return _package_script(project_path, "lint", "eslint", default="npm run lint")
    if language == "go":
        return "go fmt ./... && go vet ./..."
    return ""


def _detect_test_command(project_path: Path, language: str) -> str:
    """Detect test command based on project type."""
    if language == "python":
        if (project_path / "pytest.ini").exists() or (
            project_path / "pyproject.toml"
        ).exists():
            return "pytest tests/ -v"
        return "python -m pytest"

    if language == "javascript":
        return _package_script(project_path, "test", default="npm test")

    if language == "go":
        return "go test ./..."

    return ""


def _detect_scopes(project_path: Path) -> list[str]:
    """Detect commit scopes from directory structure."""
    scopes = []
    important_dirs = [
        "api",
        "core",
        "models",
        "services",
        "utils",
        "tests",
        "docs",
        "config",
    ]

    for dir_name in important_dirs:
        if (project_path / dir_name).exists():
            scopes.append(dir_name)

    # Also check src/ subdirectories
    src_path = project_path / "src"
    if src_path.exists():
        for item in src_path.iterdir():
            if item.is_dir() and not item.name.startswith("_"):
                scopes.append(item.name)

    return scopes[:10]  # Limit to 10


def _generate_test_setup(project_path: Path, language: str) -> str:
    """Generate test setup instructions."""
    project_name = project_path.name
    lines = [f"# Test Environment Setup for {project_name}"]

    if language == "python":
        lines.extend(
            [
                "# 1. Create virtual environment:",
                "#    python -m venv venv && source venv/bin/activate",
                "# 2. Install dependencies:",
                "#    uv pip install -e '.[dev]'",
            ]
        )

        # Check for docker-compose
        if (project_path / "docker-compose.yml").exists() or (
            project_path / "docker-compose.yaml"
        ).exists():
            lines.extend(
                [
                    "# 3. Start services:",
                    "#    docker-compose up -d",
                ]
            )

        lines.extend(
            [
                "# 4. Run tests:",
                "#    pytest tests/ -v",
            ]
        )

    elif language == "javascript":
        lines.extend(
            [
                "# 1. Install dependencies:",
                "#    npm install",
                "# 2. Run tests:",
                "#    npm test",
            ]
        )

    elif language == "go":
        lines.extend(
            [
                "# 1. Download dependencies:",
                "#    go mod download",
                "# 2. Run tests:",
                "#    go test ./...",
            ]
        )

    return "\n".join(lines)


def _validate_project_entry(entry: dict) -> list[str]:
    """Validate a project entry and return list of errors."""
    errors = []

    for field in REQUIRED_FIELDS:
        if field not in entry or not entry[field]:
            errors.append(f"Missing required field: {field}")

    # Validate path exists
    if "path" in entry:
        path = Path(entry["path"]).expanduser()
        if not path.exists():
            errors.append(f"Path does not exist: {entry['path']}")
        elif not path.is_dir():
            errors.append(f"Path is not a directory: {entry['path']}")

    return errors


# ==================== TOOL IMPLEMENTATIONS ====================


async def _project_list_impl() -> list[TextContent]:
    """List all configured projects."""
    config = _load_config()
    repositories = config.get("repositories", {})

    if not repositories:
        return [TextContent(type="text", text="No projects configured in config.json")]

    lines = ["## 📁 Configured Projects\n"]

    for name, info in sorted(repositories.items()):
        path = info.get("path", "?")
        gitlab = info.get("gitlab", "?")
        jira = info.get("jira_project", "?")
        branch = info.get("default_branch", "?")

        # Check if path exists
        path_exists = Path(path).expanduser().exists() if path != "?" else False
        status = "✅" if path_exists else "❌"

        lines.append(f"### {status} {name}")
        lines.append(f"- **Path:** `{path}`")
        lines.append(f"- **GitLab:** `{gitlab}`")
        lines.append(f"- **Jira:** `{jira}`")
        lines.append(f"- **Branch:** `{branch}`")

        # Show optional fields if present
        if info.get("konflux_namespace"):
            lines.append(f"- **Konflux:** `{info['konflux_namespace']}`")
        if info.get("scopes"):
            lines.append(f"- **Scopes:** {', '.join(info['scopes'])}")

        lines.append("")

    lines.append(f"*Total: {len(repositories)} projects*")

    return [TextContent(type="text", text="\n".join(lines))]


async def _project_detect_impl(path: str) -> list[TextContent]:
    """Auto-detect project settings from a directory."""
    project_path = Path(path).expanduser().resolve()

    if not project_path.exists():
        return [TextContent(type="text", text=f"❌ Path does not exist: {path}")]

    if not project_path.is_dir():
        return [TextContent(type="text", text=f"❌ Path is not a directory: {path}")]

    # Detect settings
    language = _detect_language(project_path)
    default_branch = _detect_default_branch(project_path)
    gitlab = _detect_gitlab_remote(project_path)
    lint_command = _detect_lint_command(project_path, language)
    test_command = _detect_test_command(project_path, language)
    scopes = _detect_scopes(project_path)
    test_setup = _generate_test_setup(project_path, language)

    lines = [f"## 🔍 Detected Project Settings: {project_path.name}\n"]
    lines.append(f"**Language:** {language}")
    lines.append(f"**Path:** `{project_path}`")
    lines.append(f"**Default Branch:** `{default_branch}`")
    lines.append(f"**GitLab:** `{gitlab or 'Not detected - needs input'}`")
    lines.append(f"**Lint Command:** `{lint_command or 'Not detected'}`")
    lines.append(f"**Test Command:** `{test_command or 'Not detected'}`")
    lines.append(f"**Scopes:** {', '.join(scopes) if scopes else 'None detected'}")

    lines.append("\n### Suggested Config Entry\n")
    lines.append("```json")
    lines.append(
        json.dumps(
            {
                project_path.name: {
                    "path": str(project_path),
                    "gitlab": gitlab or "<org/repo>",
                    "jira_project": "<PROJECT_KEY>",
                    "jira_component": "",
                    "lint_command": lint_command,
                    "test_command": test_command,
                    "test_setup": test_setup,
                    "default_branch": default_branch,
                    "scopes": scopes,
                }
            },
            indent=2,
        )
    )
    lines.append("```")

    lines.append("\n*Use `project_add()` to add this project to config.json*")

    return [TextContent(type="text", text="\n".join(lines))]


def _with_detected_settings(
    project_path: Path, settings: dict, auto_detect: bool
) -> dict:
    """Fill empty project settings from the filesystem when auto-detect is on."""
    updated = dict(settings)
    if not auto_detect or not project_path.exists():
        return updated
    language = _detect_language(project_path)
    branch = updated.get("default_branch") or ""
    if not branch or branch == "main":
        detected_branch = _detect_default_branch(project_path)
        if detected_branch:
            updated["default_branch"] = detected_branch
    if not updated.get("lint_command"):
        updated["lint_command"] = _detect_lint_command(project_path, language)
    if not updated.get("test_command"):
        updated["test_command"] = _detect_test_command(project_path, language)
    if not updated.get("scopes"):
        updated["scopes"] = ",".join(_detect_scopes(project_path))
    if not updated.get("test_setup"):
        updated["test_setup"] = _generate_test_setup(project_path, language)
    return updated


def _project_entry(project_path: Path, settings: dict) -> dict:
    """Build a config.json repository entry from project settings."""
    entry = {
        "path": str(project_path),
        "gitlab": settings["gitlab"],
        "jira_project": settings["jira_project"],
        "default_branch": settings["default_branch"],
    }
    optional = (
        "jira_component",
        "lint_command",
        "test_command",
        "test_setup",
        "konflux_namespace",
        "scopes",
    )
    for key in optional:
        value = settings.get(key) or ""
        if not value:
            continue
        if key == "scopes":
            entry[key] = [part.strip() for part in value.split(",") if part.strip()]
        else:
            entry[key] = value
    return entry


def _added_project_message(
    name: str, gitlab: str, jira_project: str, entry: dict
) -> str:
    """Format the project_add success message."""
    lines = [f"✅ **Project '{name}' added to config.json**\n"]
    lines.append("### Configuration\n")
    lines.append("```json")
    lines.append(json.dumps({name: entry}, indent=2))
    lines.append("```")
    lines.append("\n### Next Steps\n")
    lines.append(
        f"1. Run `knowledge_scan(project='{name}')` to generate project knowledge"
    )
    lines.append(f"2. Verify GitLab access: `gitlab_mr_list(project='{gitlab}')`")
    lines.append(f"3. Verify Jira access: `jira_list_issues(project='{jira_project}')`")
    return "\n".join(lines)


async def _project_add_impl(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    name: str,
    path: str,
    gitlab: str,
    jira_project: str,
    jira_component: str = "",
    lint_command: str = "",
    test_command: str = "",
    test_setup: str = "",
    default_branch: str = "main",
    konflux_namespace: str = "",
    scopes: str = "",
    auto_detect: bool = True,
) -> list[TextContent]:
    """Add a new project to config.json.

    The parameter list matches the project_add MCP tool.
    """
    config = _load_config()
    config.setdefault("repositories", {})
    if name in config["repositories"]:
        return [
            TextContent(
                type="text",
                text=(
                    f"❌ Project '{name}' already exists in config.json.\n\n"
                    f"Use `project_remove('{name}')` first if you want to replace it."
                ),
            )
        ]

    project_path = Path(path).expanduser().resolve()
    settings = _with_detected_settings(
        project_path,
        {
            "gitlab": gitlab,
            "jira_project": jira_project,
            "jira_component": jira_component,
            "lint_command": lint_command,
            "test_command": test_command,
            "test_setup": test_setup,
            "default_branch": default_branch,
            "konflux_namespace": konflux_namespace,
            "scopes": scopes,
        },
        auto_detect,
    )
    entry = _project_entry(project_path, settings)
    errors = _validate_project_entry(entry)
    if errors:
        detail = "\n".join(f"- {err}" for err in errors)
        return [TextContent(type="text", text=f"❌ Validation errors:\n\n{detail}")]
    config["repositories"][name] = entry
    if not _save_config(config):
        return [TextContent(type="text", text="❌ Failed to save config.json")]
    message = _added_project_message(name, gitlab, jira_project, entry)
    return [TextContent(type="text", text=message)]


async def _project_remove_impl(name: str, confirm: bool = False) -> list[TextContent]:
    """Remove a project from config.json."""
    config = _load_config()
    repos = config.get("repositories", {})
    if name not in repos:
        available = ", ".join(repos) if repos else "none"
        return [
            TextContent(
                type="text",
                text=(
                    f"❌ Project '{name}' not found in config.json.\n\n"
                    f"Available projects: {available}"
                ),
            )
        ]
    if not confirm:
        return [_project_removal_preview(name, repos[name])]
    removed = repos.pop(name)
    removed_from = _drop_related_project(config, name)
    if not _save_config(config):
        return [TextContent(type="text", text="❌ Failed to save config.json")]
    return [_project_removed_message(name, removed, removed_from)]


def _project_removal_preview(name: str, entry: dict) -> TextContent:
    lines = [f"⚠️ **Confirm removal of project '{name}'**\n"]
    lines.append("### Current Configuration\n")
    lines.append("```json")
    lines.append(json.dumps({name: entry}, indent=2))
    lines.append("```")
    lines.append(
        f"\n*Run `project_remove('{name}', confirm=True)` to confirm removal.*"
    )
    return TextContent(type="text", text="\n".join(lines))


def _drop_related_project(config: dict, name: str) -> list[str]:
    removed_from = []
    quay_repos = config.get("quay", {}).get("repositories", {})
    if name in quay_repos:
        del quay_repos[name]
        removed_from.append("quay.repositories")
    namespaces = config.get("saas_pipelines", {}).get("namespaces", {})
    if name in namespaces:
        del namespaces[name]
        removed_from.append("saas_pipelines.namespaces")
    return removed_from


def _project_removed_message(
    name: str, removed: dict, removed_from: list[str]
) -> TextContent:
    lines = [f"✅ **Project '{name}' removed from config.json**\n"]
    if removed_from:
        lines.append("Also removed from:")
        lines.extend(f"- `{section}`" for section in removed_from)
    lines.append("\n### Removed Configuration\n")
    lines.append("```json")
    lines.append(json.dumps({name: removed}, indent=2))
    lines.append("```")
    return TextContent(type="text", text="\n".join(lines))


def _collect_project_updates(entry: dict, values: dict) -> list[str]:
    """Apply non-empty project fields and return the keys that changed."""
    updated = []
    for key, value in values.items():
        if not value:
            continue
        if key == "path":
            entry["path"] = str(Path(value).expanduser().resolve())
        elif key == "scopes":
            entry["scopes"] = [
                part.strip() for part in value.split(",") if part.strip()
            ]
        else:
            entry[key] = value
        updated.append(key)
    return updated


def _missing_project_message(name: str, available: list[str]) -> str:
    shown = ", ".join(available) if available else "none"
    return f"❌ Project '{name}' not found.\n\nAvailable: {shown}"


async def _project_update_impl(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    name: str,
    path: str = "",
    gitlab: str = "",
    jira_project: str = "",
    jira_component: str = "",
    lint_command: str = "",
    test_command: str = "",
    default_branch: str = "",
    konflux_namespace: str = "",
    scopes: str = "",
) -> list[TextContent]:
    """Update an existing project in config.json.

    The parameter list matches the project_update MCP tool.
    """
    config = _load_config()
    repos = config.get("repositories", {})
    if name not in repos:
        text = _missing_project_message(name, list(repos))
        return [TextContent(type="text", text=text)]

    entry = repos[name]
    updated_fields = _collect_project_updates(
        entry,
        {
            "path": path,
            "gitlab": gitlab,
            "jira_project": jira_project,
            "jira_component": jira_component,
            "lint_command": lint_command,
            "test_command": test_command,
            "default_branch": default_branch,
            "konflux_namespace": konflux_namespace,
            "scopes": scopes,
        },
    )
    if not updated_fields:
        return [
            TextContent(
                type="text",
                text=(
                    "❌ No fields provided to update.\n\n"
                    "Provide at least one field to update "
                    "(path, gitlab, jira_project, etc.)"
                ),
            )
        ]
    errors = _validate_project_entry(entry)
    if errors:
        detail = "\n".join(f"- {err}" for err in errors)
        return [TextContent(type="text", text=f"❌ Validation errors:\n\n{detail}")]
    if not _save_config(config):
        return [TextContent(type="text", text="❌ Failed to save config.json")]
    lines = [f"✅ **Project '{name}' updated**\n"]
    lines.append(f"**Updated fields:** {', '.join(updated_fields)}\n")
    lines.append("### Current Configuration\n")
    lines.append("```json")
    lines.append(json.dumps({name: entry}, indent=2))
    lines.append("```")
    return [TextContent(type="text", text="\n".join(lines))]


# ==================== TOOL REGISTRATION ====================


def _shared_register_project_tools(server: "FastMCP") -> int:
    """Register project management tools with the MCP server."""
    registry = ToolRegistry(server)

    @registry.tool()
    async def project_list() -> list[TextContent]:
        """
        List all configured projects in config.json.

        Shows project name, path, GitLab, Jira, and other settings.
        Indicates if the local path exists.

        Returns:
            List of configured projects with their settings.
        """
        return await _project_list_impl()

    @registry.tool()
    async def project_detect(path: str) -> list[TextContent]:
        """
        Auto-detect project settings from a directory.

        Scans the directory to detect:
        - Language (Python, JavaScript, Go, etc.)
        - Default branch from git
        - GitLab remote URL
        - Lint and test commands
        - Commit scopes from directory structure

        Args:
            path: Path to the project directory

        Returns:
            Detected settings and suggested config entry.
        """
        return await _project_detect_impl(path)

    @registry.tool()
    async def project_add(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        name: str,
        path: str,
        gitlab: str,
        jira_project: str,
        jira_component: str = "",
        lint_command: str = "",
        test_command: str = "",
        test_setup: str = "",
        default_branch: str = "main",
        konflux_namespace: str = "",
        scopes: str = "",
        auto_detect: bool = True,
    ) -> list[TextContent]:
        """
        Add a new project to config.json.

        If auto_detect is True and the path exists, will auto-detect
        settings like lint_command, test_command, scopes, etc.

        Args:
            name: Project name (used as key in config)
            path: Local filesystem path to the project
            gitlab: GitLab project path (e.g., "org/repo")
            jira_project: Jira project key (e.g., "AAP")
            jira_component: Optional Jira component name
            lint_command: Command to run linting
            test_command: Command to run tests
            test_setup: Test setup instructions
            default_branch: Default branch (main/master)
            konflux_namespace: Konflux tenant namespace
            scopes: Comma-separated list of commit scopes
            auto_detect: Auto-detect settings from project directory

        Returns:
            Confirmation of project addition.
        """
        return await _project_add_impl(
            name,
            path,
            gitlab,
            jira_project,
            jira_component,
            lint_command,
            test_command,
            test_setup,
            default_branch,
            konflux_namespace,
            scopes,
            auto_detect,
        )

    @registry.tool()
    async def project_remove(name: str, confirm: bool = False) -> list[TextContent]:
        """
        Remove a project from config.json.

        Also removes the project from related sections like
        quay.repositories and saas_pipelines.namespaces.

        Args:
            name: Project name to remove
            confirm: Must be True to actually remove

        Returns:
            Confirmation of removal or prompt to confirm.
        """
        return await _project_remove_impl(name, confirm)

    @registry.tool()
    async def project_update(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        name: str,
        path: str = "",
        gitlab: str = "",
        jira_project: str = "",
        jira_component: str = "",
        lint_command: str = "",
        test_command: str = "",
        default_branch: str = "",
        konflux_namespace: str = "",
        scopes: str = "",
    ) -> list[TextContent]:
        """
        Update an existing project in config.json.

        Only updates fields that are provided (non-empty).

        Args:
            name: Project name to update
            path: New local filesystem path
            gitlab: New GitLab project path
            jira_project: New Jira project key
            jira_component: New Jira component name
            lint_command: New lint command
            test_command: New test command
            default_branch: New default branch
            konflux_namespace: New Konflux namespace
            scopes: New comma-separated scopes

        Returns:
            Confirmation of update.
        """
        return await _project_update_impl(
            name,
            path,
            gitlab,
            jira_project,
            jira_component,
            lint_command,
            test_command,
            default_branch,
            konflux_namespace,
            scopes,
        )

    return registry.count


def register_project_tools(server: "FastMCP") -> int:
    "Register project tools."
    return _shared_register_project_tools(server)


register_project_tools.__doc__ = _shared_register_project_tools.__doc__
