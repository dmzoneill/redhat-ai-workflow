"""Meta Tools - Dynamic tool discovery and execution.

Provides tools for:
- tool_list: List all available tools across modules
- tool_exec: Execute any tool from any module dynamically
- context_filter: Get context-aware tool recommendations for a message
"""

import importlib.util
import json
import logging

import yaml
from fastmcp import Context, FastMCP
from fastmcp.exceptions import NotFoundError, ToolError
from mcp.types import TextContent

from server.tool_discovery import build_full_manifest, get_module_for_tool
from server.tool_registry import ToolRegistry
from tool_modules.aa_workflow.src.meta_tool_handlers import (
    apply_tool_filter_impl,
    context_filter_impl,
    session_info_impl,
    session_list_impl,
    session_rename_impl,
    session_switch_impl,
    session_sync_impl,
    tool_gap_update_impl,
    tool_gaps_list_impl,
    workspace_state_export_impl,
    workspace_state_list_impl,
)
from tool_modules.aa_workflow.src.skill_engine import _format_known_issues

# Setup project path for server imports
from tool_modules.common import PROJECT_ROOT

TOOL_MODULES_DIR = PROJECT_ROOT / "tool_modules"

logger = logging.getLogger(__name__)

# Failures loading a tool module or running one of its tools (fastmcp wraps
# errors raised inside a tool in ToolError; unknown tools raise NotFoundError).
_TOOL_EXEC_ERRORS = (
    ToolError,
    NotFoundError,
    ImportError,
    SyntaxError,
    OSError,
    AttributeError,
    TypeError,
    ValueError,
    LookupError,
    RuntimeError,
)


# Known issues checking - loads patterns from memory
def _learned_matches(document: dict, error_lower: str, tool_lower: str) -> list:
    """Collect learned error patterns that mention this tool or error."""
    matches = []
    categories = (
        "error_patterns",
        "auth_patterns",
        "bonfire_patterns",
        "pipeline_patterns",
    )
    for category in categories:
        for pattern in document.get(category, []):
            pattern_text = pattern.get("pattern", "").lower()
            if pattern_text and (pattern_text in error_lower or pattern_text in tool_lower):
                matches.append(
                    {
                        "source": category,
                        "pattern": pattern.get("pattern"),
                        "meaning": pattern.get("meaning", ""),
                        "fix": pattern.get("fix", ""),
                        "commands": pattern.get("commands", []),
                    }
                )
    return matches


def _fix_matches(document: dict, tool_name: str, error_lower: str) -> list:
    """Collect tool-fix records that match this tool or error text."""
    matches = []
    tool_lower = tool_name.lower() if tool_name else ""
    for fix in document.get("tool_fixes", []):
        same_tool = tool_name and fix.get("tool_name", "").lower() == tool_lower
        fix_pattern = fix.get("error_pattern", "").lower()
        same_error = bool(error_lower) and fix_pattern and fix_pattern in error_lower
        if same_tool or same_error:
            matches.append(
                {
                    "source": "tool_fixes",
                    "tool_name": fix.get("tool_name"),
                    "pattern": fix.get("error_pattern", ""),
                    "fix": fix.get("fix_applied", ""),
                }
            )
    return matches


def _read_yaml(path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def check_known_issues_sync(tool_name: str = "", error_text: str = "") -> list:
    """Check memory for known issues matching this tool/error."""
    error_lower = error_text.lower() if error_text else ""
    tool_lower = tool_name.lower() if tool_name else ""
    try:
        memory_dir = PROJECT_ROOT / "memory" / "learned"
        patterns = _read_yaml(memory_dir / "patterns.yaml")
        fixes = _read_yaml(memory_dir / "tool_fixes.yaml")
    except (yaml.YAMLError, OSError) as exc:
        logger.debug("Suppressed error: %s", exc)
        return []
    matches = _learned_matches(patterns, error_lower, tool_lower)
    matches.extend(_fix_matches(fixes, tool_name, error_lower))
    return matches


# ============== Dynamic Tool Discovery ==============
# Tools are discovered by scanning module files at runtime.
# No more hardcoded lists to maintain!


def get_tool_registry() -> dict[str, list[str]]:
    """Get the tool registry by discovering tools from modules.

    This replaces the old hardcoded TOOL_REGISTRY dict.
    Tools are discovered by parsing @registry.tool() decorators in module files.
    """
    return build_full_manifest()


def module_for_tool(tool_name: str) -> str | None:
    """Get the module a tool belongs to.

    This replaces the old MODULE_PREFIXES dict.
    Uses the discovery system with prefix-based fallback.
    """
    return get_module_for_tool(tool_name)


async def tool_list_impl(module: str) -> list[TextContent]:
    """Implementation of tool_list tool."""
    # Get tools dynamically from discovery system
    tool_registry = get_tool_registry()

    if module:
        if module not in tool_registry:
            return [
                TextContent(
                    type="text",
                    text=(f"❌ Unknown module: {module}\n\nAvailable: {', '.join(tool_registry.keys())}"),
                )
            ]

        tools = tool_registry[module]
        lines = [f"## Module: {module}\n", f"**{len(tools)} tools available:**\n"]
        for t in tools:
            lines.append(f"- `{t}`")
        if tools:
            lines.append(f"\n*Use `tool_exec('{tools[0]}', '{{}}')` to run*")
        return [TextContent(type="text", text="\n".join(lines))]

    # List all modules
    lines = ["## Available Tool Modules\n"]
    total = 0
    for mod, tools in tool_registry.items():
        lines.append(f"- **{mod}**: {len(tools)} tools")
        total += len(tools)
    lines.append(f"\n**Total: {total} tools**")
    lines.append("\nUse `tool_list(module='git')` to see tools in a module")
    lines.append("\n**💡 TIP:** After loading an agent, call tools DIRECTLY by name:")
    lines.append("   `bonfire_namespace_list(mine_only=True)`  ← Cursor shows actual name")
    lines.append("   NOT: `tool_exec('bonfire_namespace_list', ...)`  ← Shows as 'tool_exec'")
    lines.append("\nUse `tool_exec()` only for tools from non-loaded agents.")

    return [TextContent(type="text", text="\n".join(lines))]


def extract_tool_result(result) -> list[TextContent]:
    """Extract text content from tool execution result.

    Args:
        result: Tool execution result (various types)

    Returns:
        TextContent list
    """
    if isinstance(result, tuple):
        result = result[0]
    if isinstance(result, list) and len(result) > 0:
        if hasattr(result[0], "text"):
            return [TextContent(type="text", text=result[0].text)]
        return [TextContent(type="text", text=str(result[0]))]

    return [TextContent(type="text", text=str(result))]


async def handle_tool_exec_error(tool_name: str, error_msg: str, args: str, create_issue_fn) -> list[TextContent]:
    """Handle tool execution error with known issues check and GitHub issue creation.

    Args:
        tool_name: Name of the tool that failed
        error_msg: Error message
        args: Tool arguments (JSON string)
        create_issue_fn: Function to create GitHub issues

    Returns:
        Error message with hints and issue link
    """
    lines = [f"❌ Error executing {tool_name}: {error_msg}"]

    # Check for known issues from memory
    matches = check_known_issues_sync(tool_name=tool_name, error_text=error_msg)
    known_text = _format_known_issues(matches)
    if known_text:
        lines.append(known_text)
    else:
        lines.append("")
        lines.append(f"💡 **Auto-fix:** `debug_tool('{tool_name}')`")
        lines.append(f"📚 **After fixing:** `learn_tool_fix('{tool_name}', '<pattern>', '<cause>', '<fix>')`")

    # Auto-create GitHub issue for all tool failures
    if create_issue_fn:
        try:
            issue_result = await create_issue_fn(tool=tool_name, error=error_msg, context=f"Args: {args}")

            if issue_result["success"]:
                lines.append("")
                lines.append(f"🐛 **Issue created:** {issue_result['issue_url']}")
            elif issue_result["issue_url"]:
                lines.append("")
                lines.append("💡 **Report this error:**")
                lines.append(f"📝 [Create GitHub Issue]({issue_result['issue_url']})")
        except (OSError, RuntimeError, ValueError, TypeError, KeyError) as issue_err:
            logger.debug("Failed to create GitHub issue: %s", issue_err)

    return [TextContent(type="text", text="\n".join(lines))]


async def tool_exec_impl(tool_name: str, args: str, create_issue_fn) -> list[TextContent]:
    """Implementation of tool_exec tool."""
    # Determine which module the tool belongs to using discovery system
    module = module_for_tool(tool_name)

    if not module:
        return [
            TextContent(
                type="text",
                text=f"❌ Unknown tool: {tool_name}\n\nUse tool_list() to see available tools.",
            )
        ]

    # Parse arguments
    try:
        tool_args = json.loads(args) if args else {}
    except json.JSONDecodeError as e:
        return [TextContent(type="text", text=f"❌ Invalid JSON args: {e}")]

    # Load and execute the tool module (try tools_basic.py first, then tools.py)
    tools_file = TOOL_MODULES_DIR / f"aa_{module}" / "src" / "tools_basic.py"
    if not tools_file.exists():
        tools_file = TOOL_MODULES_DIR / f"aa_{module}" / "src" / "tools.py"

    if not tools_file.exists():
        return [TextContent(type="text", text=f"❌ Module not found: {module}")]

    try:
        # Create a temporary server to register tools
        temp_server = FastMCP(f"temp-{module}")

        # Load the module
        spec = importlib.util.spec_from_file_location(f"aa_{module}_tools_exec", tools_file)
        if spec is None or spec.loader is None:
            return [TextContent(type="text", text=f"❌ Could not load module: {module}")]

        loaded_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(loaded_module)

        # Register tools with temp server
        if hasattr(loaded_module, "register_tools"):
            loaded_module.register_tools(temp_server)

        # Execute the tool
        result = await temp_server.call_tool(tool_name, tool_args)

        # Extract text from result
        return extract_tool_result(result)

    except _TOOL_EXEC_ERRORS as exc:
        # Report loading or execution failures instead of killing the server.
        return await handle_tool_exec_error(tool_name, str(exc), args, create_issue_fn)


def register_meta_tools(server: "FastMCP", create_issue_fn=None) -> int:
    """Register meta tools with the MCP server."""
    registry = ToolRegistry(server)
    _register_lookup_tools(registry, create_issue_fn)
    _register_session_tools(registry)
    return registry.count


def _register_lookup_tools(registry, create_issue_fn) -> None:
    """Register discovery and workspace meta tools."""

    @registry.tool()
    async def tool_list(module: str = "") -> list[TextContent]:
        """
        List all available tools across all modules.

        Use this to discover tools that aren't directly loaded.
        Then use tool_exec() to run them.

        Args:
            module: Filter by module (git, jira, gitlab, k8s, etc.)
                   Leave empty to list all modules.

        Returns:
            List of available tools and their descriptions.
        """
        return await tool_list_impl(module)

    @registry.tool()
    async def tool_exec(tool_name: str, args: str = "{}") -> list[TextContent]:
        """
        Execute ANY tool from ANY module dynamically.

        This is a meta-tool that can run tools not directly loaded.
        First use tool_list() to see available tools.

        Args:
            tool_name: Full tool name (e.g., "gitlab_mr_list", "kibana_search_logs")
            args: JSON string of arguments (e.g., '{"project": "backend", "state": "opened"}')

        Returns:
            Tool execution result.

        Example:
            tool_exec("gitlab_mr_list", '{"project": "your-backend"}')
        """
        return await tool_exec_impl(tool_name, args, create_issue_fn)

    @registry.tool()
    async def context_filter(
        message: str,
        persona: str = "developer",
    ) -> list[TextContent]:
        """
        Get context-aware tool recommendations for a message.

        Uses the 4-layer HybridToolFilter to analyze your message and return:
        - Recommended tools for this task
        - Detected skill (if any)
        - Memory context (active issues, repo, branch)
        - Learned patterns (known fixes)
        - Semantic knowledge (relevant code)

        Call this FIRST when starting a complex task to understand what tools
        and context are available.

        Args:
            message: The task or question you want to accomplish
            persona: Current persona (developer, devops, incident, release)

        Returns:
            Context-aware recommendations including tools, skill, and enriched context.

        Example:
            context_filter("deploy MR 1459 to ephemeral")
            # Returns: detected skill, recommended tools, memory state, etc.
        """
        return await context_filter_impl(message, persona)

    @registry.tool()
    async def apply_tool_filter(
        ctx: Context,
        message: str,
        persona: str = "developer",
    ) -> list[TextContent]:
        """
        Apply tool filtering to reduce the tools Claude sees at runtime.

        This tool analyzes your message and dynamically hides irrelevant tools,
        reducing Claude's context window usage and improving response quality.

        Call this at the START of complex tasks to focus Claude on relevant tools.

        The filter uses 4 layers:
        1. Core tools (always kept: memory, persona, session)
        2. Persona baseline (developer, devops, incident, release)
        3. Skill tools (auto-detected from message)
        4. NPU classification (semantic understanding if available)

        Args:
            message: The task you want to accomplish (e.g., "deploy MR 1459 to ephemeral")
            persona: Current persona hint (auto-detected if not specified)

        Returns:
            Summary of filtering applied and tools now available.

        Example:
            apply_tool_filter("deploy MR 1459 to ephemeral")
            # Hides git, jira, lint tools; keeps k8s, bonfire, gitlab, quay
        """
        return await apply_tool_filter_impl(ctx, message, persona)

    @registry.tool()
    async def workspace_state_export(ctx: Context) -> list[TextContent]:
        """
        Export workspace state for VS Code extension.

        Exports all active workspace states to a JSON file that the
        VS Code extension watches for real-time UI updates.

        Returns:
            Export status and file path.
        """
        return await workspace_state_export_impl(ctx)

    @registry.tool()
    async def workspace_state_list(ctx: Context) -> list[TextContent]:
        """
        List all active workspace states.

        Shows all workspaces tracked by the MCP server, including their
        project, persona, active issue, branch, and sessions.

        Returns:
            List of workspace states with session details.
        """
        return await workspace_state_list_impl(ctx)


def _register_session_tools(registry) -> None:
    """Register session and tool-gap meta tools."""

    @registry.tool()
    async def session_info(ctx: Context, session_id: str = "") -> list[TextContent]:
        """
        Show session info for a specific session or the active session.

        IMPORTANT: Each Cursor chat should track its own session_id. When you call
        session_start(), save the returned session_id and pass it to this tool
        to get YOUR session's info (not another chat's session).

        Args:
            session_id: Your session ID from session_start(). If not provided,
                        shows the workspace's most recent active session (which
                        may belong to a different chat).

        Returns:
            Session information including ID, persona, project, and activity.

        Examples:
            session_info(session_id="abc123")  # Get YOUR session info
            session_info()                      # Get workspace's active session (shared)
        """
        return await session_info_impl(ctx, session_id)

    @registry.tool()
    async def session_rename(ctx: Context, name: str, session_id: str = "") -> list[TextContent]:
        """
        Rename a session.

        Give your session a friendly name to help identify it in the UI.

        Args:
            name: New name for the session (e.g., "Working on AAP-12345", "Debugging billing")
            session_id: Optional session ID to rename. If not provided, renames the active session.

        Returns:
            Confirmation of the rename.

        Examples:
            session_rename(name="Fixing billing calculation bug")
            session_rename(name="AAP-61214 - API refactor", session_id="abc123")
        """
        return await session_rename_impl(ctx, name, session_id)

    @registry.tool()
    async def session_list(ctx: Context) -> list[TextContent]:
        """
        List all sessions in the current workspace.

        Shows session IDs, names, personas, and recent activity for each session.
        Useful for identifying which chat is which.

        Returns:
            List of all sessions with their details.
        """
        return await session_list_impl(ctx)

    @registry.tool()
    async def session_sync(ctx: Context) -> list[TextContent]:
        """
        Sync sessions with Cursor's database.

        This synchronizes the MCP server's session list with Cursor's internal
        database. It will:
        - Add sessions for Cursor chats that don't have MCP sessions
        - Remove sessions for chats that were deleted/archived in Cursor
        - Update session names to match Cursor's chat names

        This is called automatically when exporting workspace state, but can
        be called manually to force a sync.

        Returns:
            Summary of sync operations performed.
        """
        return await session_sync_impl(ctx)

    @registry.tool()
    async def session_switch(ctx: Context, session_id: str) -> list[TextContent]:
        """
        Switch to a different session.

        Use this to switch the active session to a specific session ID.
        This is useful when you have multiple chats and want to ensure
        you're working with the correct session context.

        Args:
            session_id: The session ID to switch to (from session_list or session_start).

        Returns:
            Confirmation of the switch with session details.

        Examples:
            session_switch(session_id="abc123")
        """
        return await session_switch_impl(ctx, session_id)

    @registry.tool()
    async def tool_gaps_list(status: str = "open", limit: int = 10) -> list[TextContent]:
        """
        List requested tools that don't exist yet.

        When skills need tools that don't exist, they log the gap using the
        ToolGapDetector. This tool shows those requests, sorted by vote count.

        Use this to see what tools users/skills have requested.
        Most-voted tools should be prioritized for development.

        Args:
            status: Filter by status (open, in_progress, implemented, rejected)
            limit: Maximum number of results (default 10)

        Returns:
            List of tool gap requests with vote counts and context.
        """
        return await tool_gaps_list_impl(status, limit)

    @registry.tool()
    async def tool_gap_update(gap_id: str, status: str) -> list[TextContent]:
        """
        Update the status of a tool gap request.

        Use this after implementing a requested tool or to reject a request.

        Args:
            gap_id: The gap ID to update
            status: New status (open, in_progress, implemented, rejected)

        Returns:
            Confirmation of the update.
        """
        return await tool_gap_update_impl(gap_id, status)
