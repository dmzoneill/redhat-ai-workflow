"""Meta Tools - Dynamic tool discovery and execution.

Provides tools for:
- tool_list: List all available tools across modules
- tool_exec: Execute any tool from any module dynamically
- context_filter: Get context-aware tool recommendations for a message
"""

import importlib.util
import json
import logging
from typing import TYPE_CHECKING

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import TextContent

from server.tool_discovery import build_full_manifest, get_module_for_tool
from server.tool_registry import ToolRegistry

# Setup project path for server imports
from tool_modules.common import PROJECT_ROOT

# Import tool filtering for context-aware recommendations
try:
    from tool_modules.aa_ollama.src.skill_discovery import detect_skill
    from tool_modules.aa_ollama.src.tool_filter import filter_tools_detailed

    TOOL_FILTER_AVAILABLE = True
except ImportError:
    TOOL_FILTER_AVAILABLE = False
    filter_tools_detailed = None
    detect_skill = None

TOOL_MODULES_DIR = PROJECT_ROOT / "tool_modules"

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# Known issues checking - loads patterns from memory
def _check_known_issues_sync(tool_name: str = "", error_text: str = "") -> list:
    """Check memory for known issues matching this tool/error."""
    import yaml

    matches = []
    error_lower = error_text.lower() if error_text else ""
    tool_lower = tool_name.lower() if tool_name else ""

    try:
        memory_dir = PROJECT_ROOT / "memory" / "learned"

        patterns_file = memory_dir / "patterns.yaml"
        if patterns_file.exists():
            with open(patterns_file) as f:
                patterns = yaml.safe_load(f) or {}

            # Check all pattern categories
            for category in [
                "error_patterns",
                "auth_patterns",
                "bonfire_patterns",
                "pipeline_patterns",
            ]:
                for pattern in patterns.get(category, []):
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

        # Check tool_fixes.yaml
        fixes_file = memory_dir / "tool_fixes.yaml"
        if fixes_file.exists():
            with open(fixes_file) as f:
                fixes = yaml.safe_load(f) or {}

            for fix in fixes.get("tool_fixes", []):
                if tool_name and fix.get("tool_name", "").lower() == tool_lower:
                    matches.append(
                        {
                            "source": "tool_fixes",
                            "tool_name": fix.get("tool_name"),
                            "pattern": fix.get("error_pattern", ""),
                            "fix": fix.get("fix_applied", ""),
                        }
                    )
                elif error_text:
                    fix_pattern = fix.get("error_pattern", "").lower()
                    if fix_pattern and fix_pattern in error_lower:
                        matches.append(
                            {
                                "source": "tool_fixes",
                                "tool_name": fix.get("tool_name"),
                                "pattern": fix.get("error_pattern", ""),
                                "fix": fix.get("fix_applied", ""),
                            }
                        )

    except Exception:
        pass

    return matches


def _format_known_issues(matches: list) -> str:
    """Format known issues for display."""
    if not matches:
        return ""

    lines = ["\n## 💡 Known Issues Found!\n"]
    for match in matches[:3]:  # Limit to 3
        lines.append(f"**Pattern:** `{match.get('pattern', '?')}`")
        if match.get("meaning"):
            lines.append(f"*{match.get('meaning')}*")
        if match.get("fix"):
            lines.append(f"**Fix:** {match.get('fix')}")
        if match.get("commands"):
            lines.append("**Try:**")
            for cmd in match.get("commands", [])[:2]:
                lines.append(f"- `{cmd}`")
        lines.append("")

    return "\n".join(lines)


# ============== Dynamic Tool Discovery ==============
# Tools are discovered by scanning module files at runtime.
# No more hardcoded lists to maintain!


def _get_tool_registry() -> dict[str, list[str]]:
    """Get the tool registry by discovering tools from modules.

    This replaces the old hardcoded TOOL_REGISTRY dict.
    Tools are discovered by parsing @registry.tool() decorators in module files.
    """
    return build_full_manifest()


def _get_module_for_tool(tool_name: str) -> str | None:
    """Get the module a tool belongs to.

    This replaces the old MODULE_PREFIXES dict.
    Uses the discovery system with prefix-based fallback.
    """
    return get_module_for_tool(tool_name)


async def _tool_list_impl(module: str) -> list[TextContent]:
    """Implementation of tool_list tool."""
    # Get tools dynamically from discovery system
    tool_registry = _get_tool_registry()

    if module:
        if module not in tool_registry:
            return [
                TextContent(
                    type="text",
                    text=f"❌ Unknown module: {module}\n\n" f"Available: {', '.join(tool_registry.keys())}",
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


def _extract_tool_result(result) -> list[TextContent]:
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


async def _handle_tool_exec_error(tool_name: str, error_msg: str, args: str, create_issue_fn) -> list[TextContent]:
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
    matches = _check_known_issues_sync(tool_name=tool_name, error_text=error_msg)
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
        except Exception as issue_err:
            logger.debug(f"Failed to create GitHub issue: {issue_err}")

    return [TextContent(type="text", text="\n".join(lines))]


async def _tool_exec_impl(tool_name: str, args: str, create_issue_fn) -> list[TextContent]:
    """Implementation of tool_exec tool."""
    # Determine which module the tool belongs to using discovery system
    module = _get_module_for_tool(tool_name)

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
        return _extract_tool_result(result)

    except Exception as e:
        return await _handle_tool_exec_error(tool_name, str(e), args, create_issue_fn)


def register_meta_tools(server: "FastMCP", create_issue_fn=None) -> int:
    """Register meta tools with the MCP server."""
    registry = ToolRegistry(server)

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
        return await _tool_list_impl(module)

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
        return await _tool_exec_impl(tool_name, args, create_issue_fn)

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
        if not TOOL_FILTER_AVAILABLE:
            return [
                TextContent(
                    type="text",
                    text="⚠️ Tool filtering not available. Install: pip install sentence-transformers lancedb",
                )
            ]

        try:
            # Detect skill first
            detected_skill = detect_skill(message) if detect_skill else None

            # Run the 4-layer filter
            result = filter_tools_detailed(
                message=message,
                persona=persona,
                detected_skill=detected_skill,
            )

            # Format the response
            ctx = result.get("context", {})
            lines = []

            # Header
            lines.append(f'## 🎯 Context Analysis for: "{message[:50]}..."')
            lines.append("")

            # Persona
            persona_icon = {"developer": "👨‍💻", "devops": "🔧", "incident": "🚨", "release": "📦"}.get(
                result["persona"], "👤"
            )
            if result.get("persona_auto_detected"):
                lines.append(
                    f"**Persona**: {persona_icon} {result['persona']} "
                    f"(auto-detected via {result.get('persona_detection_reason', 'keyword')})"
                )
            else:
                lines.append(f"**Persona**: {persona_icon} {result['persona']}")

            # Skill
            skill = ctx.get("skill", {})
            if skill.get("name"):
                lines.append(f"**Detected Skill**: 🎯 {skill['name']}")
                if skill.get("description"):
                    lines.append(f"  - {skill['description'][:100]}")
                if skill.get("tools"):
                    lines.append(f"  - Tools: {', '.join(skill['tools'][:10])}")
                if skill.get("memory_ops"):
                    mem_ops = skill["memory_ops"]
                    if mem_ops.get("reads"):
                        lines.append(f"  - Memory reads: {len(mem_ops['reads'])}")
                    if mem_ops.get("writes"):
                        lines.append(f"  - Memory writes: {len(mem_ops['writes'])}")
            else:
                lines.append("**Detected Skill**: None (will use general tools)")

            lines.append("")

            # Memory state
            mem = ctx.get("memory_state", {})
            lines.append("### 🧠 Memory State")
            if mem.get("current_repo"):
                lines.append(f"- Active repo: `{mem['current_repo']}`")
            if mem.get("current_branch"):
                lines.append(f"- Branch: `{mem['current_branch']}`")
            active_issues = mem.get("active_issues", [])
            if active_issues:
                issue_keys = [i.get("key", str(i)) for i in active_issues[:3]]
                lines.append(f"- Active issues: {', '.join(issue_keys)}")
            if not any([mem.get("current_repo"), mem.get("current_branch"), active_issues]):
                lines.append("- No active work context")

            lines.append("")

            # Learned patterns
            patterns = ctx.get("learned_patterns", [])
            if patterns:
                lines.append("### 💡 Relevant Learned Patterns")
                for p in patterns[:3]:
                    lines.append(f"- **{p.get('pattern', 'Unknown')[:40]}**")
                    if p.get("fix"):
                        lines.append(f"  Fix: {p['fix'][:60]}")

            # Semantic knowledge
            semantic = ctx.get("semantic_knowledge", [])
            if semantic:
                lines.append("")
                lines.append("### 🔍 Relevant Code (Semantic Search)")
                for s in semantic[:3]:
                    lines.append(f"- `{s.get('file', 'unknown')}`")
                    if s.get("content"):
                        lines.append(f"  ```\n  {s['content'][:100]}...\n  ```")

            lines.append("")

            # Recommended tools
            tools = result.get("tools", [])
            lines.append(f"### 📋 Recommended Tools ({len(tools)} tools)")
            lines.append(f"Reduction: {result.get('reduction_pct', 0):.1f}% | Latency: {result.get('latency_ms', 0)}ms")
            lines.append("")

            # Group tools by category
            tool_groups = {}
            for t in tools:
                prefix = t.split("_")[0] if "_" in t else "other"
                if prefix not in tool_groups:
                    tool_groups[prefix] = []
                tool_groups[prefix].append(t)

            for group, group_tools in sorted(tool_groups.items()):
                lines.append(
                    f"**{group}**: {', '.join(group_tools[:5])}"
                    + (f" +{len(group_tools)-5} more" if len(group_tools) > 5 else "")
                )

            return [TextContent(type="text", text="\n".join(lines))]

        except Exception as e:
            logger.error(f"Context filter error: {e}")
            return [TextContent(type="text", text=f"❌ Error running context filter: {e}")]

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
        if not TOOL_FILTER_AVAILABLE:
            return [
                TextContent(
                    type="text",
                    text="⚠️ Tool filtering not available. Install: pip install sentence-transformers lancedb",
                )
            ]

        if not ctx:
            return [
                TextContent(
                    type="text",
                    text="⚠️ Context not available - cannot apply filter dynamically.\n\n"
                    "Use `context_filter` instead to see recommendations.",
                )
            ]

        try:
            # Get the FastMCP server from context
            server = ctx._fastmcp if hasattr(ctx, "_fastmcp") else None
            if not server:
                return [
                    TextContent(
                        type="text",
                        text="⚠️ Server not available in context - cannot apply filter.\n\n"
                        "Use `context_filter` instead to see recommendations.",
                    )
                ]

            # Detect skill first
            detected_skill = detect_skill(message) if detect_skill else None

            # Run the 4-layer filter
            result = filter_tools_detailed(
                message=message,
                persona=persona,
                detected_skill=detected_skill,
            )

            relevant_tools = set(result.get("tools", []))

            # Core tools that should NEVER be removed
            CORE_TOOLS = {
                "persona_load",
                "persona_list",
                "session_start",
                "session_info",
                "session_list",
                "session_switch",
                "session_rename",
                "debug_tool",
                "memory_read",
                "memory_write",
                "memory_update",
                "memory_append",
                "memory_query",
                "memory_session_log",
                "memory_stats",
                "check_known_issues",
                "learn_tool_fix",
                "skill_list",
                "skill_run",
                "tool_list",
                "tool_exec",
                "context_filter",
                "apply_tool_filter",
                "vpn_connect",
                "kube_login",
                "workspace_state_export",
                "workspace_state_list",
            }

            # Get current tools
            current_tools = {t.name for t in await server.list_tools()}
            tools_to_keep = relevant_tools | CORE_TOOLS

            # Track what we're hiding
            hidden_tools = []
            kept_tools = []

            # Remove tools not in the filtered set
            for tool_name in list(current_tools):
                if tool_name not in tools_to_keep:
                    try:
                        server.remove_tool(tool_name)
                        hidden_tools.append(tool_name)
                    except Exception as e:
                        logger.warning(f"Could not remove tool {tool_name}: {e}")
                else:
                    kept_tools.append(tool_name)

            # Notify Cursor that tools changed
            if hidden_tools:
                try:
                    if hasattr(ctx, "session"):
                        session = ctx.session
                        if session and hasattr(session, "send_tool_list_changed"):
                            await session.send_tool_list_changed()
                            logger.info("Sent tools/list_changed notification to client")
                except ValueError as e:
                    logger.debug(f"Could not send notification (expected in test mode): {e}")
                except Exception as e:
                    logger.warning(f"Could not send tool list changed: {e}")

            # Format response
            lines = [
                "## ✅ Tool Filter Applied",
                "",
                f"**Task**: {message[:60]}{'...' if len(message) > 60 else ''}",
                f"**Persona**: {result.get('persona', persona)}",
            ]

            if result.get("persona_auto_detected"):
                lines.append(f"  _(auto-detected via {result.get('persona_detection_reason', 'keyword')})_")

            if detected_skill:
                lines.append(f"**Skill**: {detected_skill}")

            lines.extend(
                [
                    "",
                    "### 📊 Results",
                    f"- **Tools available**: {len(kept_tools)}",
                    f"- **Tools hidden**: {len(hidden_tools)}",
                    f"- **Reduction**: {result.get('reduction_pct', 0):.1f}%",
                    f"- **Latency**: {result.get('latency_ms', 0):.0f}ms",
                    "",
                ]
            )

            # Show kept tools by category
            if kept_tools:
                lines.append("### 🔧 Available Tools")
                tool_groups = {}
                for t in sorted(kept_tools):
                    prefix = t.split("_")[0] if "_" in t else "other"
                    if prefix not in tool_groups:
                        tool_groups[prefix] = []
                    tool_groups[prefix].append(t)

                for group, group_tools in sorted(tool_groups.items()):
                    if len(group_tools) <= 5:
                        lines.append(f"- **{group}**: {', '.join(group_tools)}")
                    else:
                        lines.append(f"- **{group}**: {', '.join(group_tools[:5])} +{len(group_tools)-5} more")

            lines.extend(
                [
                    "",
                    "---",
                    "💡 **Tip**: Call `apply_tool_filter` again with a different message to re-filter,",
                    "or use `persona_load` to restore all tools for a persona.",
                ]
            )

            return [TextContent(type="text", text="\n".join(lines))]

        except Exception as e:
            logger.error(f"Apply tool filter error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return [TextContent(type="text", text=f"❌ Error applying tool filter: {e}")]

    @registry.tool()
    async def workspace_state_export(ctx: Context) -> list[TextContent]:
        """
        Export workspace state for VS Code extension.

        Exports all active workspace states to a JSON file that the
        VS Code extension watches for real-time UI updates.

        Returns:
            Export status and file path.
        """
        try:
            from tool_modules.aa_workflow.src.workspace_exporter import (
                export_workspace_state_async,
            )

            result = await export_workspace_state_async(ctx)

            if result.get("success"):
                return [
                    TextContent(
                        type="text",
                        text=f"✅ Exported {result['workspace_count']} workspace(s) to:\n"
                        f"`{result['file']}`\n\n"
                        "The VS Code extension will pick up changes automatically.",
                    )
                ]
            else:
                return [
                    TextContent(
                        type="text",
                        text=f"❌ Export failed: {result.get('error', 'Unknown error')}",
                    )
                ]
        except Exception as e:
            return [TextContent(type="text", text=f"❌ Export error: {e}")]

    @registry.tool()
    async def workspace_state_list(ctx: Context) -> list[TextContent]:
        """
        List all active workspace states.

        Shows all workspaces tracked by the MCP server, including their
        project, persona, active issue, branch, and sessions.

        Returns:
            List of workspace states with session details.
        """
        from server.workspace_state import WorkspaceRegistry

        # Ensure current workspace is included
        current_state = await WorkspaceRegistry.get_for_ctx(ctx)
        current_session = current_state.get_active_session()

        all_states = WorkspaceRegistry.get_all()

        if not all_states:
            return [TextContent(type="text", text="No active workspaces.")]

        lines = ["## 🖥️ Active Workspaces & Sessions\n"]
        total_sessions = 0

        for uri, state in all_states.items():
            is_current = uri == current_state.workspace_uri
            marker = " ← *current*" if is_current else ""

            lines.append(f"### `{uri}`{marker}")
            lines.append(f"- **Project:** {state.project or 'default'}")

            # Show sessions
            session_count = state.session_count()
            total_sessions += session_count
            lines.append(f"- **Sessions:** {session_count}")

            if state.sessions:
                current_tools = state._get_loaded_tools()

                for sid, session in state.sessions.items():
                    is_active = sid == state.active_session_id
                    is_this_chat = current_session and sid == current_session.session_id
                    active_marker = " ✓ *active*" if is_active else ""
                    this_chat_marker = " ← *this chat*" if is_this_chat else ""
                    lines.append(f"  - `{sid[:8]}`{active_marker}{this_chat_marker}: {session.persona}")
                    if session.issue_key:
                        lines.append(f"    - Issue: {session.issue_key}")
                    if session.branch:
                        lines.append(f"    - Branch: {session.branch}")
                    tools = session.tool_count or len(current_tools)
                    if tools:
                        lines.append(f"    - Tools: {tools} loaded")

            lines.append("")

        lines.append(f"*Total: {len(all_states)} workspace(s), {total_sessions} session(s)*")

        # Auto-export to update VS Code extension
        try:
            from tool_modules.aa_workflow.src.workspace_exporter import (
                export_workspace_state_async,
            )
            await export_workspace_state_async(ctx)
        except Exception:
            pass

        return [TextContent(type="text", text="\n".join(lines))]

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
        from datetime import datetime
        from server.workspace_state import WorkspaceRegistry

        workspace = await WorkspaceRegistry.get_for_ctx(ctx)

        # If session_id provided, look up that specific session
        if session_id:
            session = workspace.get_session(session_id)
            if not session:
                available = [f"`{sid}`" for sid in workspace.sessions.keys()]
                return [TextContent(
                    type="text",
                    text=f"❌ Session `{session_id}` not found.\n\n"
                    f"Available sessions: {', '.join(available) or 'none'}\n\n"
                    "Use `session_start()` to create a new session."
                )]
            workspace.set_active_session(session_id)
        else:
            session = workspace.get_active_session()

        if not session:
            return [TextContent(type="text", text="❌ No active session. Call `session_start()` first.")]

        session_project = session.project or workspace.project or 'default'
        project_source = "(auto-detected)" if session.is_project_auto_detected else "(explicit)"

        lines = [
            "## 💬 Current Session Info\n",
            "| Property | Value |",
            "|----------|-------|",
            f"| **Session ID** | `{session.session_id}` |",
            f"| **Workspace** | `{workspace.workspace_uri}` |",
            f"| **Project** | {session_project} {project_source} |",
            f"| **Persona** | {session.persona} |",
        ]

        if session.issue_key:
            lines.append(f"| **Issue** | {session.issue_key} |")
        if session.branch:
            lines.append(f"| **Branch** | {session.branch} |")

        tools = session.tool_count or len(workspace._get_loaded_tools())
        lines.append(f"| **Tools** | {tools} loaded |")

        if session.started_at:
            lines.append(f"| **Started** | {session.started_at.isoformat()} |")
        if session.last_activity:
            lines.append(f"| **Last Active** | {session.last_activity.isoformat()} |")

        lines.append(f"\n*Session name: {session.name or 'unnamed'}*")

        if session.last_tool:
            time_ago = ""
            if session.last_tool_time:
                delta = datetime.now() - session.last_tool_time
                if delta.total_seconds() < 60:
                    time_ago = "just now"
                elif delta.total_seconds() < 3600:
                    time_ago = f"{int(delta.total_seconds() / 60)} min ago"
                else:
                    time_ago = f"{int(delta.total_seconds() / 3600)} hours ago"
            lines.append(f"*Last tool: `{session.last_tool}` ({time_ago})*")
            lines.append(f"*Total tool calls: {session.tool_call_count}*")

        # Auto-export
        try:
            from tool_modules.aa_workflow.src.workspace_exporter import (
                export_workspace_state_async,
            )
            await export_workspace_state_async(ctx)
        except Exception:
            pass

        return [TextContent(type="text", text="\n".join(lines))]

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
        from server.workspace_state import WorkspaceRegistry

        workspace = await WorkspaceRegistry.get_for_ctx(ctx)

        if session_id:
            session = workspace.get_session(session_id)
            if not session:
                return [TextContent(type="text", text=f"❌ Session `{session_id}` not found.")]
        else:
            session = workspace.get_active_session()

        if not session:
            return [TextContent(type="text", text="❌ No active session to rename.")]

        old_name = session.name or "(unnamed)"
        session.name = name

        # Save to disk
        WorkspaceRegistry.save_to_disk()

        # Export for VS Code extension
        try:
            from tool_modules.aa_workflow.src.workspace_exporter import export_workspace_state_async
            await export_workspace_state_async(ctx)
        except Exception:
            pass

        return [TextContent(type="text", text=f"✅ Session renamed: `{old_name}` → `{name}`")]

    @registry.tool()
    async def session_list(ctx: Context) -> list[TextContent]:
        """
        List all sessions in the current workspace.

        Shows session IDs, names, personas, and recent activity for each session.
        Useful for identifying which chat is which.

        Returns:
            List of all sessions with their details.
        """
        from datetime import datetime
        from server.workspace_state import WorkspaceRegistry

        workspace = await WorkspaceRegistry.get_for_ctx(ctx)
        current_session = workspace.get_active_session()

        if not workspace.sessions:
            return [TextContent(type="text", text="No sessions in this workspace.")]

        lines = ["## 📋 Sessions in this Workspace\n"]

        # Sort by last activity (most recent first)
        sorted_sessions = sorted(
            workspace.sessions.values(),
            key=lambda s: s.last_activity or datetime.min,
            reverse=True
        )

        for session in sorted_sessions:
            is_current = current_session and session.session_id == current_session.session_id
            marker = "→ " if is_current else "  "

            # Format time ago
            time_ago = "unknown"
            if session.last_activity:
                delta = datetime.now() - session.last_activity
                if delta.total_seconds() < 60:
                    time_ago = "just now"
                elif delta.total_seconds() < 3600:
                    time_ago = f"{int(delta.total_seconds() / 60)} min ago"
                elif delta.total_seconds() < 86400:
                    time_ago = f"{int(delta.total_seconds() / 3600)} hours ago"
                else:
                    time_ago = f"{int(delta.total_seconds() / 86400)} days ago"

            name_display = f"**{session.name}**" if session.name else "*unnamed*"
            lines.append(f"{marker}`{session.session_id}` - {name_display}")
            lines.append(f"   Persona: {session.persona} | Active: {time_ago}")

            if session.last_tool:
                lines.append(f"   Last: `{session.last_tool}` ({session.tool_call_count} calls)")

            if session.issue_key:
                lines.append(f"   Issue: {session.issue_key}")

            lines.append("")

        lines.append(f"*Total: {len(workspace.sessions)} session(s)*")
        lines.append("\n*Tip: Use `session_rename(name='...')` to name your sessions*")
        lines.append("*Tip: Use `session_switch(session_id='...')` to switch to a different session*")

        return [TextContent(type="text", text="\n".join(lines))]

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
        from server.workspace_state import WorkspaceRegistry
        from tool_modules.aa_workflow.src.workspace_exporter import export_workspace_state_async

        workspace = await WorkspaceRegistry.get_for_ctx(ctx)
        
        # Perform sync
        result = workspace.sync_with_cursor_db()
        
        # Save changes
        WorkspaceRegistry.save_to_disk()
        
        # Export for UI
        await export_workspace_state_async(ctx)

        total = sum(result.values())
        if total == 0:
            return [TextContent(type="text", text="✅ Sessions already in sync with Cursor.")]

        lines = ["## 🔄 Session Sync Complete\n"]
        if result["added"] > 0:
            lines.append(f"- **Added:** {result['added']} session(s)")
        if result["removed"] > 0:
            lines.append(f"- **Removed:** {result['removed']} session(s)")
        if result["renamed"] > 0:
            lines.append(f"- **Renamed:** {result['renamed']} session(s)")
        
        lines.append(f"\n*Total sessions: {len(workspace.sessions)}*")

        return [TextContent(type="text", text="\n".join(lines))]

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
        from server.workspace_state import WorkspaceRegistry

        workspace = await WorkspaceRegistry.get_for_ctx(ctx)

        # Check if session exists
        session = workspace.get_session(session_id)
        if not session:
            available = [f"`{sid}`" for sid in workspace.sessions.keys()]
            return [TextContent(
                type="text",
                text=f"❌ Session `{session_id}` not found.\n\nAvailable sessions: {', '.join(available) or 'none'}"
            )]

        # Switch to the session
        workspace.set_active_session(session_id)
        session.touch()

        # Save to disk
        WorkspaceRegistry.save_to_disk()

        # Build response
        lines = [
            f"✅ **Switched to session `{session_id}`**\n",
            "| Property | Value |",
            "|----------|-------|",
            f"| **Name** | {session.name or '(unnamed)'} |",
            f"| **Persona** | {session.persona} |",
        ]

        if session.issue_key:
            lines.append(f"| **Issue** | {session.issue_key} |")
        if session.branch:
            lines.append(f"| **Branch** | {session.branch} |")

        lines.append(f"| **Tool Calls** | {session.tool_call_count} |")

        if session.last_tool:
            lines.append(f"| **Last Tool** | `{session.last_tool}` |")

        lines.append("\n*This session is now active for this chat.*")

        return [TextContent(type="text", text="\n".join(lines))]

    return registry.count
