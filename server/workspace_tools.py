"""Workspace Tools - Decorators and utilities for workspace-aware tools.

Provides decorators to enforce workspace-specific tool access control
and utilities for building workspace-aware tools.

Usage:
    from server.workspace_tools import workspace_tool

    @registry.tool()
    @workspace_tool(required_modules=["k8s"])
    async def kubectl_get_pods(ctx: Context, namespace: str) -> str:
        # Only runs if k8s is in workspace's active_tools
        ...
"""

import functools
import logging
from typing import TYPE_CHECKING, Callable, TypeVar

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context

logger = logging.getLogger(__name__)

# Type variable for decorated functions
F = TypeVar("F", bound=Callable)

# Mapping of tool modules to suggested personas
MODULE_TO_PERSONA = {
    "k8s": "devops",
    "k8s_basic": "devops",
    "k8s_extra": "devops",
    "bonfire": "devops",
    "bonfire_basic": "devops",
    "prometheus": "incident",
    "prometheus_basic": "incident",
    "alertmanager": "incident",
    "kibana": "incident",
    "konflux": "release",
    "konflux_basic": "release",
    "quay": "release",
    "git": "developer",
    "git_basic": "developer",
    "gitlab": "developer",
    "gitlab_basic": "developer",
    "jira": "developer",
    "jira_basic": "developer",
}


def _suggest_persona(module: str) -> str:
    """Suggest a persona for a given module."""
    return MODULE_TO_PERSONA.get(module, "developer")


def workspace_tool(required_modules: list[str] | None = None):
    """Decorator to enforce workspace-specific tool access.

    When a tool is decorated with this, it will check if the required
    modules are active for the current workspace before executing.

    Args:
        required_modules: List of module names that must be active.
                         If None, no module check is performed.

    Returns:
        Decorated function that checks workspace access.

    Example:
        @registry.tool()
        @workspace_tool(required_modules=["k8s"])
        async def kubectl_get_pods(ctx: Context, namespace: str) -> str:
            ...

    Note:
        The decorated function MUST have `ctx: Context` as its first parameter.
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(ctx: "Context", *args, **kwargs):
            # Import here to avoid circular imports
            from .workspace_state import WorkspaceRegistry

            # Get workspace state
            try:
                state = await WorkspaceRegistry.get_for_ctx(ctx)
            except Exception as e:
                logger.warning(f"Failed to get workspace state: {e}")
                # Allow execution if we can't get workspace state
                return await func(ctx, *args, **kwargs)

            # Check if required modules are active
            if required_modules:
                # If no active tools set, all tools are available (backward compat)
                if state.active_tools:
                    missing = []
                    for module in required_modules:
                        if module not in state.active_tools:
                            missing.append(module)

                    if missing:
                        # Suggest persona to load
                        suggested = _suggest_persona(missing[0])
                        return (
                            f"❌ Required module(s) not loaded: {', '.join(missing)}\n\n"
                            f"This tool requires the following modules to be active:\n"
                            f"- {', '.join(required_modules)}\n\n"
                            f"**To enable:** Run `persona_load('{suggested}')` to load the {suggested} persona.\n\n"
                            f"Current workspace persona: `{state.persona}`\n"
                            f"Active modules: {', '.join(sorted(state.active_tools)) or 'none'}"
                        )

            # Execute the tool
            return await func(ctx, *args, **kwargs)

        return wrapper  # type: ignore

    return decorator


def workspace_aware(func: F) -> F:
    """Decorator to mark a tool as workspace-aware.

    This is a lighter decorator that doesn't enforce module access,
    but ensures the tool has access to workspace state.

    The decorated function can access workspace state via:
        state = await WorkspaceRegistry.get_for_ctx(ctx)

    Args:
        func: The tool function to decorate

    Returns:
        Decorated function

    Example:
        @registry.tool()
        @workspace_aware
        async def my_tool(ctx: Context, ...) -> str:
            from server.workspace_state import WorkspaceRegistry
            state = await WorkspaceRegistry.get_for_ctx(ctx)
            project = state.project
            ...
    """

    @functools.wraps(func)
    async def wrapper(ctx: "Context", *args, **kwargs):
        return await func(ctx, *args, **kwargs)

    return wrapper  # type: ignore


async def check_workspace_access(
    ctx: "Context",
    required_modules: list[str],
) -> tuple[bool, str | None]:
    """Check if required modules are active for the workspace.

    Use this for manual access checking when the decorator isn't suitable.

    Args:
        ctx: MCP Context
        required_modules: List of required module names

    Returns:
        Tuple of (allowed, error_message).
        If allowed is True, error_message is None.
        If allowed is False, error_message contains the reason.

    Example:
        allowed, error = await check_workspace_access(ctx, ["k8s"])
        if not allowed:
            return error
        # ... proceed with tool execution
    """
    from .workspace_state import WorkspaceRegistry

    try:
        state = await WorkspaceRegistry.get_for_ctx(ctx)
    except Exception as e:
        logger.warning(f"Failed to get workspace state: {e}")
        return True, None  # Allow if we can't check

    if not state.active_tools:
        return True, None  # All tools available if none specified

    missing = [m for m in required_modules if m not in state.active_tools]
    if not missing:
        return True, None

    suggested = _suggest_persona(missing[0])
    error = (
        f"❌ Required module(s) not loaded: {', '.join(missing)}\n\n"
        f"Run `persona_load('{suggested}')` to enable."
    )
    return False, error


async def get_workspace_context(ctx: "Context") -> dict:
    """Get workspace context as a dictionary.

    Convenience function for tools that need workspace context
    but don't want to import WorkspaceRegistry directly.

    Args:
        ctx: MCP Context

    Returns:
        Dictionary with workspace context:
        - workspace_uri: str
        - project: str | None
        - persona: str
        - issue_key: str | None
        - branch: str | None
        - active_tools: list[str]
    """
    from .workspace_state import WorkspaceRegistry

    try:
        state = await WorkspaceRegistry.get_for_ctx(ctx)
        return {
            "workspace_uri": state.workspace_uri,
            "project": state.project,
            "persona": state.persona,
            "issue_key": state.issue_key,
            "branch": state.branch,
            "active_tools": list(state.active_tools),
        }
    except Exception as e:
        logger.warning(f"Failed to get workspace context: {e}")
        return {
            "workspace_uri": "default",
            "project": None,
            "persona": "developer",
            "issue_key": None,
            "branch": None,
            "active_tools": [],
        }


