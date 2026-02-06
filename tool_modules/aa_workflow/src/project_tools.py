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
from typing import TYPE_CHECKING, Any

from mcp.types import TextContent

from server.config_manager import config as config_manager
from server.tool_registry import ToolRegistry

# Support both package import and direct loading
try:
    from .constants import PROJECT_DIR
except ImportError:
    TOOL_MODULES_DIR = Path(__file__).parent.parent.parent
    PROJECT_DIR = TOOL_MODULES_DIR.parent

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
    except Exception as e:
        logger.error(f"Failed to save config: {e}")
        return False


def _detect_language(project_path: Path) -> str:
    """Detect project language from config files."""
    if (project_path / "pyproject.toml").exists() or (project_path / "setup.py").exists():
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
            ["git", "symbolic-re", "refs/remotes/origin/HEAD"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            # refs/remotes/origin/main -> main
            return result.stdout.strip().split("/")[-1]
    except Exception:
        pass

    # Fallback: check if main or master exists
    try:
        result = subprocess.run(
            ["git", "branch", "-r"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            branches = result.stdout
            if "origin/main" in branches:
                return "main"
            if "origin/master" in branches:
                return "master"
    except Exception:
        pass

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
    except Exception:
        pass
    return None


def _detect_lint_command(project_path: Path, language: str) -> str:
    """Detect lint command based on project type."""
    if language == "python":
        # Check for common Python linters
        if (project_path / "pyproject.toml").exists():
            content = (project_path / "pyproject.toml").read_text()
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

    if language == "javascript":
        if (project_path / "package.json").exists():
            try:
                with open(project_path / "package.json") as f:
                    pkg = json.load(f)
                scripts = pkg.get("scripts", {})
                if "lint" in scripts:
                    return "npm run lint"
                if "eslint" in scripts:
                    return "npm run eslint"
            except Exception:
                pass
        return "npm run lint"

    if language == "go":
        return "go fmt ./... && go vet ./..."

    return ""


def _detect_test_command(project_path: Path, language: str) -> str:
    """Detect test command based on project type."""
    if language == "python":
        if (project_path / "pytest.ini").exists() or (project_path / "pyproject.toml").exists():
            return "pytest tests/ -v"
        return "python -m pytest"

    if language == "javascript":
        if (project_path / "package.json").exists():
            try:
                with open(project_path / "package.json") as f:
                    pkg = json.load(f)
                scripts = pkg.get("scripts", {})
                if "test" in scripts:
                    return "npm test"
            except Exception:
                pass
        return "npm test"

    if language == "go":
        return "go test ./..."

    return ""


def _detect_scopes(project_path: Path) -> list[str]:
    """Detect commit scopes from directory structure."""
    scopes = []
    important_dirs = ["api", "core", "models", "services", "utils", "tests", "docs", "config"]

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
        if (project_path / "docker-compose.yml").exists() or (project_path / "docker-compose.yaml").exists():
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

    # Build detected config
    detected = {
        "name": project_path.name,
        "path": str(project_path),
        "language": language,
        "default_branch": default_branch,
        "gitlab": gitlab or "<NEEDS_INPUT>",
        "jira_project": "<NEEDS_INPUT>",
        "lint_command": lint_command,
        "test_command": test_command,
        "scopes": scopes,
        "test_setup": test_setup,
    }

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


async def _project_add_impl(
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
    """Add a new project to config.json."""
    config = _load_config()

    if "repositories" not in config:
        config["repositories"] = {}

    # Check if project already exists
    if name in config["repositories"]:
        return [
            TextContent(
                type="text",
                text=f"❌ Project '{name}' already exists in config.json.\n\n"
                f"Use `project_remove('{name}')` first if you want to replace it.",
            )
        ]

    # Expand and validate path
    project_path = Path(path).expanduser().resolve()

    # Auto-detect settings if enabled and path exists
    if auto_detect and project_path.exists():
        language = _detect_language(project_path)

        if not default_branch or default_branch == "main":
            detected_branch = _detect_default_branch(project_path)
            if detected_branch:
                default_branch = detected_branch

        if not lint_command:
            lint_command = _detect_lint_command(project_path, language)

        if not test_command:
            test_command = _detect_test_command(project_path, language)

        if not scopes:
            detected_scopes = _detect_scopes(project_path)
            scopes = ",".join(detected_scopes)

        if not test_setup:
            test_setup = _generate_test_setup(project_path, language)

    # Build entry
    entry: dict[str, Any] = {
        "path": str(project_path),
        "gitlab": gitlab,
        "jira_project": jira_project,
        "default_branch": default_branch,
    }

    # Add optional fields if provided
    if jira_component:
        entry["jira_component"] = jira_component
    if lint_command:
        entry["lint_command"] = lint_command
    if test_command:
        entry["test_command"] = test_command
    if test_setup:
        entry["test_setup"] = test_setup
    if konflux_namespace:
        entry["konflux_namespace"] = konflux_namespace
    if scopes:
        entry["scopes"] = [s.strip() for s in scopes.split(",") if s.strip()]

    # Validate
    errors = _validate_project_entry(entry)
    if errors:
        return [
            TextContent(
                type="text",
                text="❌ Validation errors:\n\n" + "\n".join(f"- {e}" for e in errors),
            )
        ]

    # Add to config
    config["repositories"][name] = entry

    # Save
    if not _save_config(config):
        return [TextContent(type="text", text="❌ Failed to save config.json")]

    lines = [f"✅ **Project '{name}' added to config.json**\n"]
    lines.append("### Configuration\n")
    lines.append("```json")
    lines.append(json.dumps({name: entry}, indent=2))
    lines.append("```")

    lines.append("\n### Next Steps\n")
    lines.append(f"1. Run `knowledge_scan(project='{name}')` to generate project knowledge")
    lines.append(f"2. Verify GitLab access: `gitlab_mr_list(project='{gitlab}')`")
    lines.append(f"3. Verify Jira access: `jira_list_issues(project='{jira_project}')`")

    return [TextContent(type="text", text="\n".join(lines))]


async def _project_remove_impl(name: str, confirm: bool = False) -> list[TextContent]:
    """Remove a project from config.json."""
    config = _load_config()

    if "repositories" not in config or name not in config["repositories"]:
        available = list(config.get("repositories", {}).keys())
        return [
            TextContent(
                type="text",
                text=f"❌ Project '{name}' not found in config.json.\n\n"
                f"Available projects: {', '.join(available) if available else 'none'}",
            )
        ]

    if not confirm:
        entry = config["repositories"][name]
        lines = [f"⚠️ **Confirm removal of project '{name}'**\n"]
        lines.append("### Current Configuration\n")
        lines.append("```json")
        lines.append(json.dumps({name: entry}, indent=2))
        lines.append("```")
        lines.append(f"\n*Run `project_remove('{name}', confirm=True)` to confirm removal.*")
        return [TextContent(type="text", text="\n".join(lines))]

    # Remove from config
    removed = config["repositories"].pop(name)

    # Also check and remove from related sections
    removed_from = []

    # Check quay.repositories
    if "quay" in config and "repositories" in config["quay"]:
        if name in config["quay"]["repositories"]:
            del config["quay"]["repositories"][name]
            removed_from.append("quay.repositories")

    # Check saas_pipelines.namespaces
    if "saas_pipelines" in config and "namespaces" in config["saas_pipelines"]:
        if name in config["saas_pipelines"]["namespaces"]:
            del config["saas_pipelines"]["namespaces"][name]
            removed_from.append("saas_pipelines.namespaces")

    # Save
    if not _save_config(config):
        return [TextContent(type="text", text="❌ Failed to save config.json")]

    lines = [f"✅ **Project '{name}' removed from config.json**\n"]

    if removed_from:
        lines.append("Also removed from:")
        for section in removed_from:
            lines.append(f"- `{section}`")

    lines.append("\n### Removed Configuration\n")
    lines.append("```json")
    lines.append(json.dumps({name: removed}, indent=2))
    lines.append("```")

    return [TextContent(type="text", text="\n".join(lines))]


async def _project_update_impl(
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
    """Update an existing project in config.json."""
    config = _load_config()

    if "repositories" not in config or name not in config["repositories"]:
        available = list(config.get("repositories", {}).keys())
        return [
            TextContent(
                type="text",
                text=f"❌ Project '{name}' not found.\n\n"
                f"Available: {', '.join(available) if available else 'none'}",
            )
        ]

    entry = config["repositories"][name]
    updated_fields = []

    # Update provided fields
    if path:
        entry["path"] = str(Path(path).expanduser().resolve())
        updated_fields.append("path")
    if gitlab:
        entry["gitlab"] = gitlab
        updated_fields.append("gitlab")
    if jira_project:
        entry["jira_project"] = jira_project
        updated_fields.append("jira_project")
    if jira_component:
        entry["jira_component"] = jira_component
        updated_fields.append("jira_component")
    if lint_command:
        entry["lint_command"] = lint_command
        updated_fields.append("lint_command")
    if test_command:
        entry["test_command"] = test_command
        updated_fields.append("test_command")
    if default_branch:
        entry["default_branch"] = default_branch
        updated_fields.append("default_branch")
    if konflux_namespace:
        entry["konflux_namespace"] = konflux_namespace
        updated_fields.append("konflux_namespace")
    if scopes:
        entry["scopes"] = [s.strip() for s in scopes.split(",") if s.strip()]
        updated_fields.append("scopes")

    if not updated_fields:
        return [
            TextContent(
                type="text",
                text="❌ No fields provided to update.\n\n"
                "Provide at least one field to update (path, gitlab, jira_project, etc.)",
            )
        ]

    # Validate
    errors = _validate_project_entry(entry)
    if errors:
        return [
            TextContent(
                type="text",
                text="❌ Validation errors:\n\n" + "\n".join(f"- {e}" for e in errors),
            )
        ]

    # Save
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


def register_project_tools(server: "FastMCP") -> int:
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
    async def project_add(
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
    async def project_update(
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
