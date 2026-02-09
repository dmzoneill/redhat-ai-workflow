"""Project Tools - Manage projects in config.json.

This module delegates to the canonical implementations in
tool_modules.aa_workflow.src.project_tools to avoid code duplication.

Provides tools for:
- project_list: List all configured projects
- project_add: Add a new project to config.json
- project_remove: Remove a project from config.json
- project_detect: Auto-detect project settings from a directory
- project_update: Update an existing project in config.json
"""

from typing import TYPE_CHECKING

from mcp.types import TextContent

from server.tool_registry import ToolRegistry

# Import all shared helpers and implementations from the canonical module.
from tool_modules.aa_workflow.src.project_tools import (
    OPTIONAL_FIELDS,
    REQUIRED_FIELDS,
    _detect_default_branch,
    _detect_gitlab_remote,
    _detect_language,
    _detect_lint_command,
    _detect_scopes,
    _detect_test_command,
    _generate_test_setup,
    _load_config,
    _project_add_impl,
    _project_detect_impl,
    _project_list_impl,
    _project_remove_impl,
    _project_update_impl,
    _save_config,
    _validate_project_entry,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP

# Re-export for backwards compatibility
__all__ = [
    "REQUIRED_FIELDS",
    "OPTIONAL_FIELDS",
    "_load_config",
    "_save_config",
    "_detect_language",
    "_detect_default_branch",
    "_detect_gitlab_remote",
    "_detect_lint_command",
    "_detect_test_command",
    "_detect_scopes",
    "_generate_test_setup",
    "_validate_project_entry",
    "_project_list_impl",
    "_project_detect_impl",
    "_project_add_impl",
    "_project_remove_impl",
    "_project_update_impl",
    "register_tools",
]


# ==================== TOOL REGISTRATION ====================


def register_tools(server: "FastMCP") -> int:
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
