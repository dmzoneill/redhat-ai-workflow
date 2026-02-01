"""Chat Context - Track project context per chat session.

This module provides workspace-aware context management. Each Cursor workspace
maintains its own state (project, issue, branch) via the WorkspaceRegistry.

For tools that have access to MCP Context (ctx), use the async functions:
- get_chat_project_async(ctx) - Get project for workspace
- set_chat_project_async(ctx, project) - Set project for workspace

For backward compatibility, synchronous functions are still available:
- get_chat_project() - Uses default workspace
- set_chat_project(project) - Sets on default workspace

The workspace is identified by ctx.session.list_roots() which returns
the workspace path(s) open in Cursor.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from fastmcp import Context
from mcp.types import TextContent

from server.tool_registry import ToolRegistry
from server.utils import load_config

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = logging.getLogger(__name__)

# Default project when none specified
DEFAULT_PROJECT = "redhat-ai-workflow"


# ==================== WORKSPACE-AWARE FUNCTIONS (ASYNC) ====================


async def get_chat_project_async(ctx: "Context") -> str:
    """Get the current project for this workspace (async).

    Uses WorkspaceRegistry to get workspace-specific project.

    Args:
        ctx: MCP Context from tool call

    Returns:
        Project name for the current workspace
    """
    from server.workspace_utils import get_workspace_project

    return await get_workspace_project(ctx)


async def set_chat_project_async(ctx: "Context", project: str) -> bool:
    """Set the active project for this workspace (async).

    Args:
        ctx: MCP Context from tool call
        project: Project name to set

    Returns:
        True if project is valid, False otherwise
    """
    from server.workspace_utils import set_workspace_project

    return await set_workspace_project(ctx, project)


async def get_chat_issue_async(ctx: "Context") -> str | None:
    """Get the active Jira issue for this workspace (async).

    Args:
        ctx: MCP Context from tool call

    Returns:
        Issue key or None
    """
    from server.workspace_utils import get_workspace_issue

    return await get_workspace_issue(ctx)


async def set_chat_issue_async(ctx: "Context", issue_key: str | None) -> None:
    """Set the active Jira issue for this workspace (async).

    Args:
        ctx: MCP Context from tool call
        issue_key: Issue key to set
    """
    from server.workspace_utils import set_workspace_issue

    await set_workspace_issue(ctx, issue_key)


async def get_chat_branch_async(ctx: "Context") -> str | None:
    """Get the active git branch for this workspace (async).

    Args:
        ctx: MCP Context from tool call

    Returns:
        Branch name or None
    """
    from server.workspace_utils import get_workspace_branch

    return await get_workspace_branch(ctx)


async def set_chat_branch_async(ctx: "Context", branch: str | None) -> None:
    """Set the active git branch for this workspace (async).

    Args:
        ctx: MCP Context from tool call
        branch: Branch name to set
    """
    from server.workspace_utils import set_workspace_branch

    await set_workspace_branch(ctx, branch)


async def get_chat_state_async(ctx: "Context") -> dict:
    """Get full chat state for this workspace (async).

    Args:
        ctx: MCP Context from tool call

    Returns:
        Dictionary with workspace state
    """
    from server.workspace_utils import get_workspace_from_ctx

    state = await get_workspace_from_ctx(ctx)
    return {
        "project": state.project or DEFAULT_PROJECT,
        "issue_key": state.issue_key,
        "branch": state.branch,
        "started_at": state.started_at.isoformat() if state.started_at else None,
        "is_default": state.project is None and not state.is_auto_detected,
        "is_auto_detected": state.is_auto_detected,
        "workspace_uri": state.workspace_uri,
        "persona": state.persona,
    }


async def get_project_work_state_path_async(ctx: "Context", project: str | None = None) -> Path:
    """Get the path to the project-specific work state file (async).

    Args:
        ctx: MCP Context from tool call
        project: Project name. If None, uses workspace project.

    Returns:
        Path to the project's current_work.yaml file.
    """
    from server.workspace_utils import get_workspace_project

    from .constants import MEMORY_DIR

    if project is None:
        project = await get_workspace_project(ctx)

    return MEMORY_DIR / "state" / "projects" / project / "current_work.yaml"


# ==================== BACKWARD COMPATIBILITY (SYNC) ====================
# These functions use the default workspace when ctx is not available.
# Prefer the async versions when ctx is available.

# Process-level state for backward compatibility
_chat_state: dict = {
    "project": None,
    "started_at": None,
    "issue_key": None,
    "branch": None,
}


def _detect_project_from_cwd() -> str | None:
    """Detect project from current working directory."""
    config = load_config()
    if not config:
        return None

    try:
        cwd = Path.cwd().resolve()
    except Exception:
        return None

    repositories = config.get("repositories", {})
    for project_name, project_config in repositories.items():
        project_path = Path(project_config.get("path", "")).expanduser().resolve()
        try:
            cwd.relative_to(project_path)
            return project_name
        except ValueError:
            continue

    return None


def _get_project_info(project_name: str) -> dict | None:
    """Get project configuration from config.json."""
    config = load_config()
    if not config:
        return None

    repos = config.get("repositories", {})
    if project_name in repos:
        return repos[project_name]

    if project_name == DEFAULT_PROJECT:
        return {
            "path": str(Path(__file__).parent.parent.parent.parent),
            "description": "AI Workflow MCP Server project",
            "jira_project": "AAP",
        }

    return None


def get_chat_project() -> str:
    """Get the current project (sync, uses default workspace).

    For workspace-aware code, use get_chat_project_async(ctx) instead.

    Returns:
        Project name
    """
    global _chat_state

    # First try WorkspaceRegistry default workspace
    try:
        from server.workspace_utils import get_project_sync

        project = get_project_sync()
        if project and project != DEFAULT_PROJECT:
            return project
    except Exception:
        pass

    # Fall back to legacy global state
    if _chat_state["project"]:
        return _chat_state["project"]

    detected = _detect_project_from_cwd()
    if detected:
        return detected

    return DEFAULT_PROJECT


def set_chat_project(project: str) -> bool:
    """Set the active project (sync, uses default workspace).

    For workspace-aware code, use set_chat_project_async(ctx, project) instead.

    Args:
        project: Project name to set

    Returns:
        True if project is valid, False otherwise
    """
    global _chat_state

    info = _get_project_info(project)
    if not info:
        return False

    _chat_state["project"] = project
    _chat_state["started_at"] = datetime.now().isoformat()

    # Also update default workspace in registry
    try:
        from server.workspace_state import WorkspaceRegistry

        state = WorkspaceRegistry.get_or_create("default")
        state.project = project
        state.is_auto_detected = False
    except Exception:
        pass

    return True


def set_chat_issue(issue_key: str) -> None:
    """Set the active Jira issue (sync)."""
    global _chat_state
    _chat_state["issue_key"] = issue_key

    try:
        from server.workspace_state import WorkspaceRegistry

        state = WorkspaceRegistry.get_or_create("default")
        state.issue_key = issue_key
    except Exception:
        pass


def get_chat_issue() -> str | None:
    """Get the active Jira issue (sync)."""
    try:
        from server.workspace_state import WorkspaceRegistry

        state = WorkspaceRegistry.get("default")
        if state and state.issue_key:
            return state.issue_key
    except Exception:
        pass

    return _chat_state.get("issue_key")


def set_chat_branch(branch: str) -> None:
    """Set the active git branch (sync)."""
    global _chat_state
    _chat_state["branch"] = branch

    try:
        from server.workspace_state import WorkspaceRegistry

        state = WorkspaceRegistry.get_or_create("default")
        state.branch = branch
    except Exception:
        pass


def get_chat_branch() -> str | None:
    """Get the active git branch (sync)."""
    try:
        from server.workspace_state import WorkspaceRegistry

        state = WorkspaceRegistry.get("default")
        if state and state.branch:
            return state.branch
    except Exception:
        pass

    return _chat_state.get("branch")


def get_chat_state() -> dict:
    """Get full chat state (sync, uses default workspace)."""
    explicit_project = _chat_state["project"]
    detected_project = _detect_project_from_cwd() if not explicit_project else None

    # Try to get from workspace registry
    try:
        from server.workspace_state import WorkspaceRegistry

        state = WorkspaceRegistry.get("default")
        if state:
            return {
                "project": state.project or get_chat_project(),
                "issue_key": state.issue_key or _chat_state.get("issue_key"),
                "branch": state.branch or _chat_state.get("branch"),
                "started_at": state.started_at.isoformat() if state.started_at else _chat_state.get("started_at"),
                "is_default": state.project is None and not state.is_auto_detected,
                "is_auto_detected": state.is_auto_detected,
            }
    except Exception:
        pass

    return {
        "project": get_chat_project(),
        "issue_key": _chat_state.get("issue_key"),
        "branch": _chat_state.get("branch"),
        "started_at": _chat_state.get("started_at"),
        "is_default": explicit_project is None and detected_project is None,
        "is_auto_detected": explicit_project is None and detected_project is not None,
    }


def get_project_work_state_path(project: str | None = None) -> Path:
    """Get the path to the project-specific work state file (sync).

    Args:
        project: Project name. If None, uses current chat project.

    Returns:
        Path to the project's current_work.yaml file.
    """
    from .constants import MEMORY_DIR

    if project is None:
        project = get_chat_project()

    return MEMORY_DIR / "state" / "projects" / project / "current_work.yaml"


def get_project_state_dir(project: str | None = None) -> Path:
    """Get the directory for project-specific state files.

    Args:
        project: Project name. If None, uses current chat project.

    Returns:
        Path to the project's state directory.
    """
    from .constants import MEMORY_DIR

    if project is None:
        project = get_chat_project()

    return MEMORY_DIR / "state" / "projects" / project


# ==================== TOOL IMPLEMENTATIONS ====================


async def _project_context_impl(
    ctx: "Context",
    project: str = "",
    issue_key: str = "",
    branch: str = "",
) -> list[TextContent]:
    """
    Get or set the project context for this workspace.

    Uses WorkspaceRegistry for per-workspace state management.
    """
    from server.workspace_utils import (
        get_workspace_from_ctx,
        set_workspace_branch,
        set_workspace_issue,
        set_workspace_project,
    )

    lines = []

    # Set project if provided
    if project:
        if await set_workspace_project(ctx, project):
            lines.append(f"✅ Project set to: **{project}**\n")
        else:
            config = load_config()
            repos = list(config.get("repositories", {}).keys()) if config else []
            repos.append(DEFAULT_PROJECT)
            lines.append(f"❌ Unknown project: `{project}`\n")
            lines.append("**Available projects:**")
            for repo in repos:
                lines.append(f"- `{repo}`")
            return [TextContent(type="text", text="\n".join(lines))]

    # Set issue if provided
    if issue_key:
        await set_workspace_issue(ctx, issue_key)
        lines.append(f"✅ Active issue: **{issue_key}**\n")

    # Set branch if provided
    if branch:
        await set_workspace_branch(ctx, branch)
        lines.append(f"✅ Active branch: `{branch}`\n")

    # Get current workspace state
    state = await get_workspace_from_ctx(ctx)
    current_project = state.project or DEFAULT_PROJECT
    project_info = _get_project_info(current_project)

    lines.append("## 📁 Workspace Context\n")
    lines.append(f"**Project:** `{current_project}`")

    if state.is_auto_detected:
        lines.append("  *(auto-detected from workspace)*")
    elif state.project is None:
        lines.append("  *(default - use `project_context(project='...')` to change)*")

    if project_info:
        if project_info.get("path"):
            lines.append(f"**Path:** `{project_info['path']}`")
        if project_info.get("gitlab"):
            lines.append(f"**GitLab:** `{project_info['gitlab']}`")
        if project_info.get("jira_project"):
            lines.append(f"**Jira Project:** `{project_info['jira_project']}`")

    if state.issue_key:
        lines.append(f"\n**Active Issue:** `{state.issue_key}`")

    if state.branch:
        lines.append(f"**Active Branch:** `{state.branch}`")

    if state.persona:
        lines.append(f"**Persona:** `{state.persona}`")

    if state.started_at:
        lines.append(f"\n*Context set at: {state.started_at.isoformat()}*")

    # Show workspace URI for debugging
    if state.workspace_uri != "default":
        lines.append(f"\n*Workspace: {state.workspace_uri}*")

    lines.append("\n---")
    lines.append("**Switch project:** `project_context(project='automation-analytics-backend')`")

    return [TextContent(type="text", text="\n".join(lines))]


def register_chat_context_tools(server: "FastMCP") -> int:
    """Register chat context tools with the MCP server."""
    from fastmcp import Context

    registry = ToolRegistry(server)

    @registry.tool()
    async def project_context(
        ctx: Context,
        project: str = "",
        issue_key: str = "",
        branch: str = "",
    ) -> list[TextContent]:
        """
        Get or set the project context for this chat.

        When multiple Cursor chats are open, each chat tracks its own project context.
        This helps the AI understand which codebase you're working on.

        Args:
            project: Project name to set (from config.json repositories).
                     Leave empty to see current context.
            issue_key: Optional Jira issue key to associate with this chat.
            branch: Optional git branch to associate with this chat.

        Returns:
            Current project context information.

        Examples:
            project_context()  # Show current context
            project_context(project="automation-analytics-backend")  # Switch project
            project_context(issue_key="AAP-12345")  # Set active issue
        """
        return await _project_context_impl(ctx, project, issue_key, branch)

    return registry.count
