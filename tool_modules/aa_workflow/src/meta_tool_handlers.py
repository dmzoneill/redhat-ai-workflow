# pylint: disable=duplicate-code,cyclic-import
"""Implementations for meta MCP tools.

Registered in meta_tools.register_meta_tools. Bodies live here so the
registration module stays under the line and statement limits.
"""

import logging
from typing import Any

from fastmcp import Context
from mcp.types import TextContent

logger = logging.getLogger(__name__)

try:
    from tool_modules.aa_ollama.src.skill_discovery import detect_skill
    from tool_modules.aa_ollama.src.tool_filter import filter_tools_detailed

    TOOL_FILTER_AVAILABLE = True
except ImportError:
    TOOL_FILTER_AVAILABLE = False
    filter_tools_detailed = None  # type: ignore[assignment]
    detect_skill = None  # type: ignore[assignment]


async def context_filter_impl(  # pylint: disable=too-many-branches,too-many-locals,too-many-statements
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
                text="⚠️ Tool filtering not available. Install: uv add sentence-transformers lancedb",  # pylint: disable=line-too-long
            )
        ]

    try:
        # Detect skill first
        detected_skill = detect_skill(message) if detect_skill is not None else None

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
        persona_icon = {
            "developer": "👨‍💻",
            "devops": "🔧",
            "incident": "🚨",
            "release": "📦",
        }.get(result["persona"], "👤")
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
        lines.append(
            f"Reduction: {result.get('reduction_pct', 0):.1f}% | Latency: {result.get('latency_ms', 0)}ms"  # pylint: disable=line-too-long
        )
        lines.append("")

        # Group tools by category
        tool_groups: dict[str, list[str]] = {}
        for t in tools:
            prefix = t.split("_")[0] if "_" in t else "other"
            if prefix not in tool_groups:
                tool_groups[prefix] = []
            tool_groups[prefix].append(t)

        for group, group_tools in sorted(tool_groups.items()):
            lines.append(
                f"**{group}**: {', '.join(group_tools[:5])}"
                + (f" +{len(group_tools) - 5} more" if len(group_tools) > 5 else "")
            )

        return [TextContent(type="text", text="\n".join(lines))]

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Context filter error: %s", e)
        return [TextContent(type="text", text=f"❌ Error running context filter: {e}")]


async def apply_tool_filter_impl(  # pylint: disable=too-many-branches,too-many-locals,too-many-statements
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
                text="⚠️ Tool filtering not available. Install: uv add sentence-transformers lancedb",  # pylint: disable=line-too-long
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
        server: Any = (
            ctx._fastmcp  # pylint: disable=protected-access
            if hasattr(ctx, "_fastmcp")
            else None  # pylint: disable=protected-access
        )  # pylint: disable=protected-access
        if not server:
            return [
                TextContent(
                    type="text",
                    text="⚠️ Server not available in context - cannot apply filter.\n\n"
                    "Use `context_filter` instead to see recommendations.",
                )
            ]

        # Detect skill first
        detected_skill = detect_skill(message) if detect_skill is not None else None

        # Run the 4-layer filter
        result = filter_tools_detailed(
            message=message,
            persona=persona,
            detected_skill=detected_skill,
        )

        relevant_tools = set(result.get("tools", []))

        # Core tools that should NEVER be removed
        CORE_TOOLS = {  # pylint: disable=invalid-name
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
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.warning("Could not remove tool %s: %s", tool_name, e)
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
                logger.debug(
                    "Could not send notification (expected in test mode): %s", e
                )
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("Could not send tool list changed: %s", e)

        # Format response
        lines = [
            "## ✅ Tool Filter Applied",
            "",
            f"**Task**: {message[:60]}{'...' if len(message) > 60 else ''}",
            f"**Persona**: {result.get('persona', persona)}",
        ]

        if result.get("persona_auto_detected"):
            lines.append(
                f"  _(auto-detected via {result.get('persona_detection_reason', 'keyword')})_"
            )

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
            tool_groups: dict[str, list[str]] = {}
            for t in sorted(kept_tools):
                prefix = t.split("_")[0] if "_" in t else "other"
                if prefix not in tool_groups:
                    tool_groups[prefix] = []
                tool_groups[prefix].append(t)

            for group, group_tools in sorted(tool_groups.items()):
                if len(group_tools) <= 5:
                    lines.append(f"- **{group}**: {', '.join(group_tools)}")
                else:
                    lines.append(
                        f"- **{group}**: {', '.join(group_tools[:5])} +{len(group_tools) - 5} more"
                    )

        lines.extend(
            [
                "",
                "---",
                "💡 **Tip**: Call `apply_tool_filter` again with a different message to re-filter,",
                "or use `persona_load` to restore all tools for a persona.",
            ]
        )

        return [TextContent(type="text", text="\n".join(lines))]

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Apply tool filter error: %s", e)
        import traceback  # pylint: disable=import-outside-toplevel

        logger.error(traceback.format_exc())
        return [TextContent(type="text", text=f"❌ Error applying tool filter: {e}")]


async def workspace_state_export_impl(ctx: Context) -> list[TextContent]:
    """
    Export workspace state for VS Code extension.

    Exports all active workspace states to a JSON file that the
    VS Code extension watches for real-time UI updates.

    Returns:
        Export status and file path.
    """
    try:
        from tool_modules.aa_workflow.src.workspace_exporter import (  # pylint: disable=import-outside-toplevel
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
        return [
            TextContent(
                type="text",
                text=f"❌ Export failed: {result.get('error', 'Unknown error')}",
            )
        ]
    except Exception as e:  # pylint: disable=broad-exception-caught
        return [TextContent(type="text", text=f"❌ Export error: {e}")]


async def workspace_state_list_impl(  # pylint: disable=too-many-locals
    ctx: Context,
) -> list[TextContent]:  # pylint: disable=too-many-locals
    """
    List all active workspace states.

    Shows all workspaces tracked by the MCP server, including their
    project, persona, active issue, branch, and sessions.

    Returns:
        List of workspace states with session details.
    """
    from server.workspace_state import (  # pylint: disable=import-outside-toplevel
        WorkspaceRegistry,
    )  # pylint: disable=import-outside-toplevel

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
            current_tools = (
                state._get_loaded_tools()  # pylint: disable=protected-access
            )  # pylint: disable=protected-access

            for sid, session in state.sessions.items():
                is_active = sid == state.active_session_id
                is_this_chat = current_session and sid == current_session.session_id
                active_marker = " ✓ *active*" if is_active else ""
                this_chat_marker = " ← *this chat*" if is_this_chat else ""
                lines.append(
                    f"  - `{sid[:8]}`{active_marker}{this_chat_marker}: {session.persona}"
                )
                if session.issue_key:
                    lines.append(f"    - Issue: {session.issue_key}")
                if session.branch:
                    lines.append(f"    - Branch: {session.branch}")
                tools = session.tool_count or len(current_tools)
                if tools:
                    lines.append(f"    - Tools: {tools} loaded")

        lines.append("")

    lines.append(
        f"*Total: {len(all_states)} workspace(s), {total_sessions} session(s)*"
    )

    # Auto-export to update VS Code extension
    try:
        from tool_modules.aa_workflow.src.workspace_exporter import (  # pylint: disable=import-outside-toplevel
            export_workspace_state_async,
        )

        await export_workspace_state_async(ctx)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.debug("Suppressed error: %s", exc)

    return [TextContent(type="text", text="\n".join(lines))]


async def session_info_impl(  # pylint: disable=too-many-branches
    ctx: Context, session_id: str = ""
) -> list[TextContent]:  # pylint: disable=too-many-branches
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
    from datetime import datetime  # pylint: disable=import-outside-toplevel

    from server.workspace_state import (  # pylint: disable=import-outside-toplevel
        WorkspaceRegistry,
    )  # pylint: disable=import-outside-toplevel

    workspace = await WorkspaceRegistry.get_for_ctx(ctx)

    # If session_id provided, look up that specific session
    if session_id:
        session = workspace.get_session(session_id)
        if not session:
            available = [f"`{sid}`" for sid in workspace.sessions.keys()]
            return [
                TextContent(
                    type="text",
                    text=f"❌ Session `{session_id}` not found.\n\n"
                    f"Available sessions: {', '.join(available) or 'none'}\n\n"
                    "Use `session_start()` to create a new session.",
                )
            ]
        workspace.set_active_session(session_id)
    else:
        session = workspace.get_active_session()

    if not session:
        return [
            TextContent(
                type="text",
                text="❌ No active session. Call `session_start()` first.",
            )
        ]

    session_project = session.project or workspace.project or "default"
    project_source = (
        "(auto-detected)" if session.is_project_auto_detected else "(explicit)"
    )

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

    tools = session.tool_count or len(
        workspace._get_loaded_tools()  # pylint: disable=protected-access
    )  # pylint: disable=protected-access
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
        from tool_modules.aa_workflow.src.workspace_exporter import (  # pylint: disable=import-outside-toplevel
            export_workspace_state_async,
        )

        await export_workspace_state_async(ctx)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.debug("Suppressed error: %s", exc)

    return [TextContent(type="text", text="\n".join(lines))]


async def session_rename_impl(
    ctx: Context, name: str, session_id: str = ""
) -> list[TextContent]:
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
    from server.workspace_state import (  # pylint: disable=import-outside-toplevel
        WorkspaceRegistry,
    )  # pylint: disable=import-outside-toplevel

    workspace = await WorkspaceRegistry.get_for_ctx(ctx)

    if session_id:
        session = workspace.get_session(session_id)
        if not session:
            return [
                TextContent(type="text", text=f"❌ Session `{session_id}` not found.")
            ]
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
        from tool_modules.aa_workflow.src.workspace_exporter import (  # pylint: disable=import-outside-toplevel
            export_workspace_state_async,
        )

        await export_workspace_state_async(ctx)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.debug("Suppressed error: %s", exc)

    return [
        TextContent(type="text", text=f"✅ Session renamed: `{old_name}` → `{name}`")
    ]


async def session_list_impl(ctx: Context) -> list[TextContent]:
    """
    List all sessions in the current workspace.

    Shows session IDs, names, personas, and recent activity for each session.
    Useful for identifying which chat is which.

    Returns:
        List of all sessions with their details.
    """
    from datetime import datetime  # pylint: disable=import-outside-toplevel

    from server.workspace_state import (  # pylint: disable=import-outside-toplevel
        WorkspaceRegistry,
    )  # pylint: disable=import-outside-toplevel

    workspace = await WorkspaceRegistry.get_for_ctx(ctx)
    current_session = workspace.get_active_session()

    if not workspace.sessions:
        return [TextContent(type="text", text="No sessions in this workspace.")]

    lines = ["## 📋 Sessions in this Workspace\n"]

    # Sort by last activity (most recent first)
    sorted_sessions = sorted(
        workspace.sessions.values(),
        key=lambda s: s.last_activity or datetime.min,
        reverse=True,
    )

    for session in sorted_sessions:
        is_current = (
            current_session and session.session_id == current_session.session_id
        )
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
            lines.append(
                f"   Last: `{session.last_tool}` ({session.tool_call_count} calls)"
            )

        if session.issue_key:
            lines.append(f"   Issue: {session.issue_key}")

        lines.append("")

    lines.append(f"*Total: {len(workspace.sessions)} session(s)*")
    lines.append("\n*Tip: Use `session_rename(name='...')` to name your sessions*")
    lines.append(
        "*Tip: Use `session_switch(session_id='...')` to switch to a different session*"
    )

    return [TextContent(type="text", text="\n".join(lines))]


async def session_sync_impl(ctx: Context) -> list[TextContent]:
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
    from server.workspace_state import (  # pylint: disable=import-outside-toplevel
        WorkspaceRegistry,
    )  # pylint: disable=import-outside-toplevel
    from tool_modules.aa_workflow.src.workspace_exporter import (  # pylint: disable=import-outside-toplevel
        export_workspace_state_async,
    )

    workspace = await WorkspaceRegistry.get_for_ctx(ctx)

    # Perform sync
    result = workspace.sync_with_cursor_db()

    # Save changes
    WorkspaceRegistry.save_to_disk()

    # Export for UI
    await export_workspace_state_async(ctx)

    total = sum(result.values())
    if total == 0:
        return [
            TextContent(type="text", text="✅ Sessions already in sync with Cursor.")
        ]

    lines = ["## 🔄 Session Sync Complete\n"]
    if result["added"] > 0:
        lines.append(f"- **Added:** {result['added']} session(s)")
    if result["removed"] > 0:
        lines.append(f"- **Removed:** {result['removed']} session(s)")
    if result["renamed"] > 0:
        lines.append(f"- **Renamed:** {result['renamed']} session(s)")

    lines.append(f"\n*Total sessions: {len(workspace.sessions)}*")

    return [TextContent(type="text", text="\n".join(lines))]


async def session_switch_impl(ctx: Context, session_id: str) -> list[TextContent]:
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
    from server.workspace_state import (  # pylint: disable=import-outside-toplevel
        WorkspaceRegistry,
    )  # pylint: disable=import-outside-toplevel

    workspace = await WorkspaceRegistry.get_for_ctx(ctx)

    # Check if session exists
    session = workspace.get_session(session_id)
    if not session:
        available = [f"`{sid}`" for sid in workspace.sessions.keys()]
        return [
            TextContent(
                type="text",
                text=f"❌ Session `{session_id}` not found.\n\nAvailable sessions: {', '.join(available) or 'none'}",  # pylint: disable=line-too-long
            )
        ]

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


async def tool_gaps_list_impl(
    status: str = "open", limit: int = 10
) -> list[TextContent]:
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
    try:
        from tool_modules.aa_workflow.src.tool_gap_detector import (  # pylint: disable=import-outside-toplevel
            tool_gap,
        )  # pylint: disable=import-outside-toplevel

        gaps = tool_gap.get_gaps(status=status, limit=limit)

        if not gaps:
            return [
                TextContent(type="text", text=f"No tool gaps with status '{status}'.")
            ]

        lines = [f"## 🔧 Tool Gap Requests (status: {status})\n"]

        for g in gaps:
            lines.append(f"### `{g.get('suggested_tool_name', 'unknown')}`")
            lines.append(
                f"**Votes:** {g.get('vote_count', 1)} | **Status:** {g.get('status', 'open')}"
            )
            lines.append(f"**Action:** {g.get('desired_action', 'N/A')}")

            skills = g.get("requesting_skills", [])
            if skills:
                lines.append(f"**Requested by:** {', '.join(skills)}")

            if g.get("context"):
                lines.append(f"**Context:** {str(g.get('context'))[:100]}")

            if g.get("workaround_used"):
                lines.append(f"**Workaround:** {g.get('workaround_used')}")

            if g.get("suggested_args"):
                lines.append(f"**Suggested args:** `{g.get('suggested_args')}`")

            lines.append("")

        lines.append(f"*Total: {len(gaps)} gap(s) shown*")
        lines.append("\n*Use `tool_gap_update(gap_id, status)` to update status*")

        return [TextContent(type="text", text="\n".join(lines))]

    except Exception as e:  # pylint: disable=broad-exception-caught
        return [TextContent(type="text", text=f"❌ Error loading tool gaps: {e}")]


async def tool_gap_update_impl(gap_id: str, status: str) -> list[TextContent]:
    """
    Update the status of a tool gap request.

    Use this after implementing a requested tool or to reject a request.

    Args:
        gap_id: The gap ID to update
        status: New status (open, in_progress, implemented, rejected)

    Returns:
        Confirmation of the update.
    """
    try:
        from tool_modules.aa_workflow.src.tool_gap_detector import (  # pylint: disable=import-outside-toplevel
            tool_gap,
        )  # pylint: disable=import-outside-toplevel

        valid_statuses = ["open", "in_progress", "implemented", "rejected"]
        if status not in valid_statuses:
            return [
                TextContent(
                    type="text",
                    text=f"❌ Invalid status '{status}'. Must be one of: {', '.join(valid_statuses)}",  # pylint: disable=line-too-long
                )
            ]

        if tool_gap.update_status(gap_id, status):
            return [
                TextContent(
                    type="text",
                    text=f"✅ Updated gap `{gap_id}` status to `{status}`",
                )
            ]
        return [TextContent(type="text", text=f"❌ Gap `{gap_id}` not found")]

    except Exception as e:  # pylint: disable=broad-exception-caught
        return [TextContent(type="text", text=f"❌ Error updating tool gap: {e}")]
