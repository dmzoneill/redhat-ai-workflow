"""Workspace Utilities - Helper functions for workspace-aware tools.

Provides convenience functions for accessing workspace state from tool
implementations. These functions wrap the WorkspaceRegistry to provide
a cleaner API.

Usage:
    from server.workspace_utils import (
        get_workspace_from_ctx,
        get_workspace_project,
        get_workspace_persona,
    )

    async def my_tool(ctx: Context, ...) -> ...:
        project = await get_workspace_project(ctx)
        persona = await get_workspace_persona(ctx)
        # ... use workspace-specific values
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context

from .workspace_state import (
    DEFAULT_PROJECT,
    ChatSession,
    WorkspaceRegistry,
    WorkspaceState,
)

logger = logging.getLogger(__name__)


async def get_workspace_from_ctx(ctx: "Context") -> WorkspaceState:
    """Get workspace state from MCP context.

    This is the primary function for tools to access workspace state.

    Args:
        ctx: MCP Context from tool call

    Returns:
        WorkspaceState for the current workspace

    Example:
        async def my_tool(ctx: Context) -> str:
            state = await get_workspace_from_ctx(ctx)
            return f"Working on {state.project} as {state.persona}"
    """
    return await WorkspaceRegistry.get_for_ctx(ctx)


async def get_workspace_project(ctx: "Context") -> str:
    """Get the project for the current session (per-session, not per-workspace).

    Returns the session's project, falling back to workspace project,
    or the default project.

    Args:
        ctx: MCP Context

    Returns:
        Project name (never None)

    Example:
        project = await get_workspace_project(ctx)
        # Use project for memory paths, knowledge lookup, etc.
    """
    state = await get_workspace_from_ctx(ctx)
    session = state.get_active_session()
    if session and session.project:
        return session.project
    return state.project or DEFAULT_PROJECT


async def get_workspace_persona(ctx: "Context") -> str:
    """Get the persona for the current workspace.

    Args:
        ctx: MCP Context

    Returns:
        Persona name (defaults to "developer")

    Example:
        persona = await get_workspace_persona(ctx)
        # Use persona for tool filtering, knowledge lookup, etc.
    """
    state = await get_workspace_from_ctx(ctx)
    return state.persona


async def get_workspace_issue(ctx: "Context") -> str | None:
    """Get the active Jira issue for the current workspace.

    Args:
        ctx: MCP Context

    Returns:
        Issue key (e.g., "AAP-12345") or None
    """
    state = await get_workspace_from_ctx(ctx)
    return state.issue_key


async def get_workspace_branch(ctx: "Context") -> str | None:
    """Get the active git branch for the current workspace.

    Args:
        ctx: MCP Context

    Returns:
        Branch name or None
    """
    state = await get_workspace_from_ctx(ctx)
    return state.branch


async def get_workspace_uri(ctx: "Context") -> str:
    """Get the workspace URI for the current context.

    Args:
        ctx: MCP Context

    Returns:
        Workspace URI string
    """
    state = await get_workspace_from_ctx(ctx)
    return state.workspace_uri


async def set_workspace_project(ctx: "Context", project: str) -> bool:
    """Set the project for the current session (per-session, not per-workspace).

    Args:
        ctx: MCP Context
        project: Project name to set

    Returns:
        True if project is valid, False otherwise
    """
    from .utils import load_config

    # Validate project exists in config
    config = load_config()
    if config:
        repos = config.get("repositories", {})
        if project not in repos and project != DEFAULT_PROJECT:
            return False

    state = await get_workspace_from_ctx(ctx)
    session = state.get_active_session()
    if session:
        session.project = project
        session.is_project_auto_detected = False
        session.clear_filter_cache()  # Clear cache when project changes
        logger.info(f"Set project to '{project}' for session {session.session_id}")
    else:
        # Fallback to workspace level if no active session
        state.project = project
        state.is_auto_detected = False
        state.clear_filter_cache()
        logger.info(f"Set project to '{project}' for workspace {state.workspace_uri} (no active session)")
    return True


async def set_workspace_persona(ctx: "Context", persona: str) -> None:
    """Set the persona for the current workspace.

    Args:
        ctx: MCP Context
        persona: Persona name to set
    """
    state = await get_workspace_from_ctx(ctx)
    state.persona = persona
    state.clear_filter_cache()  # Clear cache when persona changes
    logger.info(f"Set persona to '{persona}' for workspace {state.workspace_uri}")


async def set_workspace_issue(ctx: "Context", issue_key: str | None) -> None:
    """Set the active Jira issue for the current workspace.

    Args:
        ctx: MCP Context
        issue_key: Issue key (e.g., "AAP-12345") or None to clear
    """
    state = await get_workspace_from_ctx(ctx)
    state.issue_key = issue_key
    logger.debug(f"Set issue to '{issue_key}' for workspace {state.workspace_uri}")


async def set_workspace_branch(ctx: "Context", branch: str | None) -> None:
    """Set the active git branch for the current workspace.

    Args:
        ctx: MCP Context
        branch: Branch name or None to clear
    """
    state = await get_workspace_from_ctx(ctx)
    state.branch = branch
    logger.debug(f"Set branch to '{branch}' for workspace {state.workspace_uri}")


async def set_workspace_tool_count(ctx: "Context", count: int) -> None:
    """Set the tool count for the current workspace's active session.

    Args:
        ctx: MCP Context
        count: Number of tools loaded
    """
    state = await get_workspace_from_ctx(ctx)
    session = state.get_active_session()
    if session:
        session.tool_count = count
    logger.debug(f"Set tool count to {count} for workspace {state.workspace_uri}")


async def get_workspace_state_dict(ctx: "Context") -> dict:
    """Get workspace state as a dictionary.

    Useful for debugging and display.

    Args:
        ctx: MCP Context

    Returns:
        Dictionary with all workspace state
    """
    state = await get_workspace_from_ctx(ctx)
    return state.to_dict()


async def is_tool_active_for_workspace(ctx: "Context", tool_module: str) -> bool:
    """Check if a tool module is active for the current workspace.
    
    Note: This now always returns True since we no longer track individual tools.
    Tool availability is determined by the loaded persona's modules.

    Args:
        ctx: MCP Context
        tool_module: Tool module name (e.g., "k8s", "gitlab")

    Returns:
        True (tool availability is now managed by persona loader)
    """
    # We no longer track individual active tools - persona determines available tools
    return True


async def ensure_session_exists(ctx: "Context", export: bool = True) -> ChatSession:
    """Ensure a session exists for the current workspace.

    If no active session exists, creates one automatically.
    Optionally exports the workspace state for VS Code extension.

    This is useful for tools that need session context but don't want
    to require explicit session_start() calls.

    Args:
        ctx: MCP Context
        export: If True, export workspace state after creating session

    Returns:
        The active (or newly created) ChatSession
    """
    state = await get_workspace_from_ctx(ctx)
    session = state.get_active_session()

    if not session:
        logger.info(f"No active session, auto-creating for workspace {state.workspace_uri}")
        session = state.create_session(persona="developer", name="Auto-created")

        # Export state so VS Code extension can see the new session
        if export:
            try:
                from tool_modules.aa_workflow.src.workspace_exporter import (
                    export_workspace_state,
                )

                export_workspace_state()
                logger.debug("Exported workspace state after auto-creating session")
            except Exception as e:
                logger.warning(f"Failed to export workspace state: {e}")

    return session


async def get_active_session(ctx: "Context") -> ChatSession | None:
    """Get the active session for the current workspace.

    Args:
        ctx: MCP Context

    Returns:
        Active ChatSession or None if no session exists
    """
    state = await get_workspace_from_ctx(ctx)
    return state.get_active_session()


async def get_session_id(ctx: "Context") -> str | None:
    """Get the active session ID for the current workspace.

    Args:
        ctx: MCP Context

    Returns:
        Session ID string or None if no session exists
    """
    state = await get_workspace_from_ctx(ctx)
    return state.active_session_id


# Synchronous helpers for backward compatibility
# These use the default workspace when ctx is not available


def get_default_workspace() -> WorkspaceState:
    """Get the default workspace state (synchronous).

    Use this only when ctx is not available (e.g., in non-tool code).

    Returns:
        WorkspaceState for the default workspace
    """
    return WorkspaceRegistry.get_or_create("default")


def get_project_sync() -> str:
    """Get project from default workspace (synchronous).

    Use this only when ctx is not available.

    Returns:
        Project name
    """
    state = get_default_workspace()
    return state.project or DEFAULT_PROJECT


def get_persona_sync() -> str:
    """Get persona from default workspace (synchronous).

    Use this only when ctx is not available.

    Returns:
        Persona name
    """
    state = get_default_workspace()
    return state.persona


