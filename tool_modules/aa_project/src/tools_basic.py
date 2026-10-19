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
    _shared_register_project_tools,
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
    "Register tools."
    return _shared_register_project_tools(server)


register_tools.__doc__ = _shared_register_project_tools.__doc__
