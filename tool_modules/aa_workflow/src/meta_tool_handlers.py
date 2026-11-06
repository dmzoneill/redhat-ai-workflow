"""Implementations for meta MCP tools.

Registered in meta_tools.register_meta_tools. Bodies live here so the
registration module stays under the line and statement limits.
"""

import logging
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Any

import anyio
import yaml
from fastmcp import Context
from mcp.types import TextContent

from server import persona_loader, workspace_state
from tool_modules.aa_workflow.src import tool_gap_detector, workspace_exporter

logger = logging.getLogger(__name__)

detect_skill: Callable[..., Any] | None = None
filter_tools_detailed: Callable[..., dict[str, Any]] | None = None
try:
    from tool_modules.aa_ollama.src import skill_discovery, tool_filter
except ImportError:
    TOOL_FILTER_AVAILABLE = False
else:
    TOOL_FILTER_AVAILABLE = True
    detect_skill = skill_discovery.detect_skill
    filter_tools_detailed = tool_filter.filter_tools_detailed

_FILTER_UNAVAILABLE = "⚠️ Tool filtering not available. Install: uv add sentence-transformers lancedb"

# Failures of the optional filter stack (embeddings, NPU, malformed results).
_FILTER_ERRORS = (OSError, RuntimeError, ValueError, KeyError, TypeError, AttributeError, ImportError)
# Failures while exporting workspace state for the VS Code extension.
_EXPORT_ERRORS = (OSError, RuntimeError, ValueError, KeyError, TypeError, AttributeError)
# Failures reading or writing the tool gap YAML file.
_GAP_ERRORS = (OSError, yaml.YAMLError, ValueError, KeyError, TypeError, AttributeError)
# Failures removing a tool from the server.
_REMOVE_TOOL_ERRORS = (AttributeError, KeyError, ValueError)
# Failures notifying a client whose session has gone away.
_NOTIFY_ERRORS = (RuntimeError, OSError, anyio.ClosedResourceError, anyio.BrokenResourceError)

# Core tools that should NEVER be removed by apply_tool_filter.
CORE_TOOLS = frozenset(
    {
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
)

_PERSONA_ICONS = {
    "developer": "👨‍💻",
    "devops": "🔧",
    "incident": "🚨",
    "release": "📦",
}


def _text(text: str) -> list[TextContent]:
    """A single text content block."""
    return [TextContent(type="text", text=text)]


def _as_aware(moment: datetime) -> datetime:
    """``moment`` with a timezone; naive values are taken as local time."""
    return moment if moment.tzinfo else moment.astimezone()


def seconds_since(moment: datetime) -> float:
    """Seconds elapsed since ``moment``, which may be timezone-aware or naive (local)."""
    return (datetime.now(tz=timezone.utc) - _as_aware(moment)).total_seconds()


def _activity_sort_key(moment: datetime | None) -> datetime:
    """Sort key for an optional activity time; missing times sort oldest."""
    return _as_aware(moment) if moment else datetime.min.replace(tzinfo=timezone.utc)


def _loaded_tool_count() -> int:
    """Number of tools currently loaded by the persona loader."""
    loader = persona_loader.get_loader()
    return len(loader.get_status()["tools"]) if loader else 0


def _group_by_prefix(tools: Iterable[str]) -> dict[str, list[str]]:
    """Tool names grouped by the text before their first underscore."""
    groups: dict[str, list[str]] = {}
    for tool in tools:
        prefix = tool.split("_")[0] if "_" in tool else "other"
        groups.setdefault(prefix, []).append(tool)
    return groups


def _run_filter(message: str, persona: str) -> tuple[Any, dict[str, Any]]:
    """Detected skill and the 4-layer filter result for ``message``."""
    if filter_tools_detailed is None:
        raise RuntimeError("tool filter not loaded")
    detected_skill = detect_skill(message) if detect_skill is not None else None
    result = filter_tools_detailed(message=message, persona=persona, detected_skill=detected_skill)
    return detected_skill, result


def _persona_line(result: dict[str, Any]) -> str:
    """Persona line of the context analysis."""
    icon = _PERSONA_ICONS.get(result["persona"], "👤")
    if result.get("persona_auto_detected"):
        reason = result.get("persona_detection_reason", "keyword")
        return f"**Persona**: {icon} {result['persona']} (auto-detected via {reason})"
    return f"**Persona**: {icon} {result['persona']}"


def _skill_lines(skill: dict[str, Any]) -> list[str]:
    """Detected skill section of the context analysis."""
    if not skill.get("name"):
        return ["**Detected Skill**: None (will use general tools)"]
    lines = [f"**Detected Skill**: 🎯 {skill['name']}"]
    if skill.get("description"):
        lines.append(f"  - {skill['description'][:100]}")
    if skill.get("tools"):
        lines.append(f"  - Tools: {', '.join(skill['tools'][:10])}")
    mem_ops = skill.get("memory_ops") or {}
    if mem_ops.get("reads"):
        lines.append(f"  - Memory reads: {len(mem_ops['reads'])}")
    if mem_ops.get("writes"):
        lines.append(f"  - Memory writes: {len(mem_ops['writes'])}")
    return lines


def _memory_lines(mem: dict[str, Any]) -> list[str]:
    """Memory state section of the context analysis."""
    lines = ["### 🧠 Memory State"]
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
    return lines


def _knowledge_lines(ctx: dict[str, Any]) -> list[str]:
    """Learned patterns and semantic search sections of the context analysis."""
    lines = []
    patterns = ctx.get("learned_patterns", [])
    if patterns:
        lines.append("### 💡 Relevant Learned Patterns")
        for p in patterns[:3]:
            lines.append(f"- **{p.get('pattern', 'Unknown')[:40]}**")
            if p.get("fix"):
                lines.append(f"  Fix: {p['fix'][:60]}")
    semantic = ctx.get("semantic_knowledge", [])
    if semantic:
        lines.append("")
        lines.append("### 🔍 Relevant Code (Semantic Search)")
        for s in semantic[:3]:
            lines.append(f"- `{s.get('file', 'unknown')}`")
            if s.get("content"):
                lines.append(f"  ```\n  {s['content'][:100]}...\n  ```")
    return lines


def _recommended_tool_lines(result: dict[str, Any]) -> list[str]:
    """Recommended tools section of the context analysis."""
    tools = result.get("tools", [])
    lines = [
        f"### 📋 Recommended Tools ({len(tools)} tools)",
        f"Reduction: {result.get('reduction_pct', 0):.1f}% | Latency: {result.get('latency_ms', 0)}ms",
        "",
    ]
    for group, group_tools in sorted(_group_by_prefix(tools).items()):
        more = f" +{len(group_tools) - 5} more" if len(group_tools) > 5 else ""
        lines.append(f"**{group}**: {', '.join(group_tools[:5])}{more}")
    return lines


def _context_report(message: str, result: dict[str, Any]) -> str:
    """Markdown context analysis for a filter result."""
    ctx = result.get("context", {})
    lines = [f'## 🎯 Context Analysis for: "{message[:50]}..."', "", _persona_line(result)]
    lines.extend(_skill_lines(ctx.get("skill", {})))
    lines.append("")
    lines.extend(_memory_lines(ctx.get("memory_state", {})))
    lines.append("")
    lines.extend(_knowledge_lines(ctx))
    lines.append("")
    lines.extend(_recommended_tool_lines(result))
    return "\n".join(lines)


async def context_filter_impl(
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
        return _text(_FILTER_UNAVAILABLE)

    try:
        _, result = _run_filter(message, persona)
        return _text(_context_report(message, result))
    except _FILTER_ERRORS as e:
        logger.error("Context filter error: %s", e)
        return _text(f"❌ Error running context filter: {e}")


def _server_from_ctx(ctx: Context) -> Any:
    """The FastMCP server behind ``ctx``, or None when it is gone."""
    try:
        return ctx.fastmcp
    except RuntimeError:
        return None


async def _hide_tools(server: Any, tools_to_keep: set[str]) -> tuple[list[str], list[str]]:
    """Remove every server tool not in ``tools_to_keep``; returns (hidden, kept)."""
    hidden_tools: list[str] = []
    kept_tools: list[str] = []
    for tool_name in list({t.name for t in await server.list_tools()}):
        if tool_name in tools_to_keep:
            kept_tools.append(tool_name)
            continue
        try:
            server.remove_tool(tool_name)
            hidden_tools.append(tool_name)
        except _REMOVE_TOOL_ERRORS as e:
            logger.warning("Could not remove tool %s: %s", tool_name, e)
    return hidden_tools, kept_tools


async def _notify_tools_changed(ctx: Context) -> None:
    """Tell the client its tool list changed (no-op without a session)."""
    try:
        session = getattr(ctx, "session", None)
        if session and hasattr(session, "send_tool_list_changed"):
            await session.send_tool_list_changed()
            logger.info("Sent tools/list_changed notification to client")
    except ValueError as e:
        logger.debug("Could not send notification (expected in test mode): %s", e)
    except _NOTIFY_ERRORS as e:
        logger.warning("Could not send tool list changed: %s", e)


def _filter_applied_report(
    message: str, persona: str, filtered: tuple[Any, dict[str, Any]], tools: tuple[list[str], list[str]]
) -> str:
    """Markdown summary of an applied tool filter."""
    detected_skill, result = filtered
    hidden_tools, kept_tools = tools
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
    if kept_tools:
        lines.append("### 🔧 Available Tools")
        for group, group_tools in sorted(_group_by_prefix(sorted(kept_tools)).items()):
            more = f" +{len(group_tools) - 5} more" if len(group_tools) > 5 else ""
            lines.append(f"- **{group}**: {', '.join(group_tools[:5])}{more}")
    lines.extend(
        [
            "",
            "---",
            "💡 **Tip**: Call `apply_tool_filter` again with a different message to re-filter,",
            "or use `persona_load` to restore all tools for a persona.",
        ]
    )
    return "\n".join(lines)


async def apply_tool_filter_impl(
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
        return _text(_FILTER_UNAVAILABLE)

    if not ctx:
        return _text(
            "⚠️ Context not available - cannot apply filter dynamically.\n\n"
            "Use `context_filter` instead to see recommendations."
        )

    try:
        server = _server_from_ctx(ctx)
        if not server:
            return _text(
                "⚠️ Server not available in context - cannot apply filter.\n\n"
                "Use `context_filter` instead to see recommendations."
            )

        filtered = _run_filter(message, persona)
        tools = await _hide_tools(server, set(filtered[1].get("tools", [])) | CORE_TOOLS)
        if tools[0]:
            await _notify_tools_changed(ctx)
        return _text(_filter_applied_report(message, persona, filtered, tools))

    except _FILTER_ERRORS as e:
        logger.exception("Apply tool filter error")
        return _text(f"❌ Error applying tool filter: {e}")


async def _export_quietly(ctx: Context) -> None:
    """Refresh the VS Code export; failures are logged and ignored."""
    try:
        await workspace_exporter.export_workspace_state_async(ctx)
    except _EXPORT_ERRORS as exc:
        logger.debug("Suppressed error: %s", exc)


async def workspace_state_export_impl(ctx: Context) -> list[TextContent]:
    """
    Export workspace state for VS Code extension.

    Exports all active workspace states to a JSON file that the
    VS Code extension watches for real-time UI updates.

    Returns:
        Export status and file path.
    """
    try:
        result = await workspace_exporter.export_workspace_state_async(ctx)
    except _EXPORT_ERRORS as e:
        return _text(f"❌ Export error: {e}")

    if result.get("success"):
        return _text(
            f"✅ Exported {result['workspace_count']} workspace(s) to:\n"
            f"`{result['file']}`\n\n"
            "The VS Code extension will pick up changes automatically."
        )
    return _text(f"❌ Export failed: {result.get('error', 'Unknown error')}")


def _workspace_session_lines(state: Any, current_session_id: str | None, loaded_tools: int) -> list[str]:
    """Session bullet points of one workspace in workspace_state_list."""
    lines = []
    for sid, session in state.sessions.items():
        active_marker = " ✓ *active*" if sid == state.active_session_id else ""
        this_chat_marker = " ← *this chat*" if current_session_id and sid == current_session_id else ""
        lines.append(f"  - `{sid[:8]}`{active_marker}{this_chat_marker}: {session.persona}")
        if session.issue_key:
            lines.append(f"    - Issue: {session.issue_key}")
        if session.branch:
            lines.append(f"    - Branch: {session.branch}")
        tools = session.tool_count or loaded_tools
        if tools:
            lines.append(f"    - Tools: {tools} loaded")
    return lines


async def workspace_state_list_impl(
    ctx: Context,
) -> list[TextContent]:
    """
    List all active workspace states.

    Shows all workspaces tracked by the MCP server, including their
    project, persona, active issue, branch, and sessions.

    Returns:
        List of workspace states with session details.
    """
    registry = workspace_state.WorkspaceRegistry

    # Ensure current workspace is included
    current_state = await registry.get_for_ctx(ctx)
    current_session = current_state.get_active_session()
    current_session_id = current_session.session_id if current_session else None

    all_states = registry.get_all()
    if not all_states:
        return _text("No active workspaces.")

    lines = ["## 🖥️ Active Workspaces & Sessions\n"]
    total_sessions = 0
    for uri, state in all_states.items():
        marker = " ← *current*" if uri == current_state.workspace_uri else ""
        lines.append(f"### `{uri}`{marker}")
        lines.append(f"- **Project:** {state.project or 'default'}")
        session_count = state.session_count()
        total_sessions += session_count
        lines.append(f"- **Sessions:** {session_count}")
        if state.sessions:
            lines.extend(_workspace_session_lines(state, current_session_id, _loaded_tool_count()))
        lines.append("")

    lines.append(f"*Total: {len(all_states)} workspace(s), {total_sessions} session(s)*")

    # Auto-export to update VS Code extension
    await _export_quietly(ctx)
    return _text("\n".join(lines))


def _last_tool_lines(session: Any) -> list[str]:
    """Last-tool footer of session_info."""
    if not session.last_tool:
        return []
    time_ago = ""
    if session.last_tool_time:
        elapsed = seconds_since(session.last_tool_time)
        if elapsed < 60:
            time_ago = "just now"
        elif elapsed < 3600:
            time_ago = f"{int(elapsed / 60)} min ago"
        else:
            time_ago = f"{int(elapsed / 3600)} hours ago"
    return [
        f"*Last tool: `{session.last_tool}` ({time_ago})*",
        f"*Total tool calls: {session.tool_call_count}*",
    ]


def _session_info_lines(workspace: Any, session: Any) -> list[str]:
    """Property table of session_info."""
    session_project = session.project or workspace.project or "default"
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
    lines.append(f"| **Tools** | {session.tool_count or _loaded_tool_count()} loaded |")
    if session.started_at:
        lines.append(f"| **Started** | {session.started_at.isoformat()} |")
    if session.last_activity:
        lines.append(f"| **Last Active** | {session.last_activity.isoformat()} |")
    lines.append(f"\n*Session name: {session.name or 'unnamed'}*")
    lines.extend(_last_tool_lines(session))
    return lines


async def session_info_impl(ctx: Context, session_id: str = "") -> list[TextContent]:
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
    workspace = await workspace_state.WorkspaceRegistry.get_for_ctx(ctx)

    # If session_id provided, look up that specific session
    if session_id:
        session = workspace.get_session(session_id)
        if not session:
            available = [f"`{sid}`" for sid in workspace.sessions]
            return _text(
                f"❌ Session `{session_id}` not found.\n\n"
                f"Available sessions: {', '.join(available) or 'none'}\n\n"
                "Use `session_start()` to create a new session."
            )
        workspace.set_active_session(session_id)
    else:
        session = workspace.get_active_session()

    if not session:
        return _text("❌ No active session. Call `session_start()` first.")

    lines = _session_info_lines(workspace, session)

    # Auto-export
    await _export_quietly(ctx)
    return _text("\n".join(lines))


async def session_rename_impl(ctx: Context, name: str, session_id: str = "") -> list[TextContent]:
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
    registry = workspace_state.WorkspaceRegistry
    workspace = await registry.get_for_ctx(ctx)

    if session_id:
        session = workspace.get_session(session_id)
        if not session:
            return _text(f"❌ Session `{session_id}` not found.")
    else:
        session = workspace.get_active_session()

    if not session:
        return _text("❌ No active session to rename.")

    old_name = session.name or "(unnamed)"
    session.name = name

    # Save to disk, then export for VS Code extension
    registry.save_to_disk()
    await _export_quietly(ctx)

    return _text(f"✅ Session renamed: `{old_name}` → `{name}`")


def _time_ago(moment: datetime | None) -> str:
    """Human-readable age of ``moment`` for session_list."""
    if not moment:
        return "unknown"
    elapsed = seconds_since(moment)
    if elapsed < 60:
        return "just now"
    if elapsed < 3600:
        return f"{int(elapsed / 60)} min ago"
    if elapsed < 86400:
        return f"{int(elapsed / 3600)} hours ago"
    return f"{int(elapsed / 86400)} days ago"


async def session_list_impl(ctx: Context) -> list[TextContent]:
    """
    List all sessions in the current workspace.

    Shows session IDs, names, personas, and recent activity for each session.
    Useful for identifying which chat is which.

    Returns:
        List of all sessions with their details.
    """
    workspace = await workspace_state.WorkspaceRegistry.get_for_ctx(ctx)
    current_session = workspace.get_active_session()

    if not workspace.sessions:
        return _text("No sessions in this workspace.")

    lines = ["## 📋 Sessions in this Workspace\n"]

    # Sort by last activity (most recent first)
    sorted_sessions = sorted(
        workspace.sessions.values(),
        key=lambda s: _activity_sort_key(s.last_activity),
        reverse=True,
    )

    for session in sorted_sessions:
        is_current = current_session and session.session_id == current_session.session_id
        marker = "→ " if is_current else "  "
        name_display = f"**{session.name}**" if session.name else "*unnamed*"
        lines.append(f"{marker}`{session.session_id}` - {name_display}")
        lines.append(f"   Persona: {session.persona} | Active: {_time_ago(session.last_activity)}")
        if session.last_tool:
            lines.append(f"   Last: `{session.last_tool}` ({session.tool_call_count} calls)")
        if session.issue_key:
            lines.append(f"   Issue: {session.issue_key}")
        lines.append("")

    lines.append(f"*Total: {len(workspace.sessions)} session(s)*")
    lines.append("\n*Tip: Use `session_rename(name='...')` to name your sessions*")
    lines.append("*Tip: Use `session_switch(session_id='...')` to switch to a different session*")

    return _text("\n".join(lines))


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
    registry = workspace_state.WorkspaceRegistry
    workspace = await registry.get_for_ctx(ctx)

    # Perform sync, save changes, export for UI
    result = workspace.sync_with_cursor_db()
    registry.save_to_disk()
    await workspace_exporter.export_workspace_state_async(ctx)

    total = sum(result.values())
    if total == 0:
        return _text("✅ Sessions already in sync with Cursor.")

    lines = ["## 🔄 Session Sync Complete\n"]
    if result["added"] > 0:
        lines.append(f"- **Added:** {result['added']} session(s)")
    if result["removed"] > 0:
        lines.append(f"- **Removed:** {result['removed']} session(s)")
    if result["renamed"] > 0:
        lines.append(f"- **Renamed:** {result['renamed']} session(s)")

    lines.append(f"\n*Total sessions: {len(workspace.sessions)}*")

    return _text("\n".join(lines))


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
    registry = workspace_state.WorkspaceRegistry
    workspace = await registry.get_for_ctx(ctx)

    # Check if session exists
    session = workspace.get_session(session_id)
    if not session:
        available = [f"`{sid}`" for sid in workspace.sessions]
        return _text(f"❌ Session `{session_id}` not found.\n\nAvailable sessions: {', '.join(available) or 'none'}")

    # Switch to the session and save to disk
    workspace.set_active_session(session_id)
    session.touch()
    registry.save_to_disk()

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

    return _text("\n".join(lines))


def _gap_lines(gap: dict[str, Any]) -> list[str]:
    """Markdown block for one tool gap request."""
    lines = [
        f"### `{gap.get('suggested_tool_name', 'unknown')}`",
        f"**Votes:** {gap.get('vote_count', 1)} | **Status:** {gap.get('status', 'open')}",
        f"**Action:** {gap.get('desired_action', 'N/A')}",
    ]
    skills = gap.get("requesting_skills", [])
    if skills:
        lines.append(f"**Requested by:** {', '.join(skills)}")
    if gap.get("context"):
        lines.append(f"**Context:** {str(gap.get('context'))[:100]}")
    if gap.get("workaround_used"):
        lines.append(f"**Workaround:** {gap.get('workaround_used')}")
    if gap.get("suggested_args"):
        lines.append(f"**Suggested args:** `{gap.get('suggested_args')}`")
    lines.append("")
    return lines


async def tool_gaps_list_impl(status: str = "open", limit: int = 10) -> list[TextContent]:
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
        gaps = tool_gap_detector.tool_gap.get_gaps(status=status, limit=limit)
    except _GAP_ERRORS as e:
        return _text(f"❌ Error loading tool gaps: {e}")

    if not gaps:
        return _text(f"No tool gaps with status '{status}'.")

    lines = [f"## 🔧 Tool Gap Requests (status: {status})\n"]
    for gap in gaps:
        lines.extend(_gap_lines(gap))
    lines.append(f"*Total: {len(gaps)} gap(s) shown*")
    lines.append("\n*Use `tool_gap_update(gap_id, status)` to update status*")
    return _text("\n".join(lines))


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
    valid_statuses = ["open", "in_progress", "implemented", "rejected"]
    if status not in valid_statuses:
        return _text(f"❌ Invalid status '{status}'. Must be one of: {', '.join(valid_statuses)}")

    try:
        updated = tool_gap_detector.tool_gap.update_status(gap_id, status)
    except _GAP_ERRORS as e:
        return _text(f"❌ Error updating tool gap: {e}")

    if updated:
        return _text(f"✅ Updated gap `{gap_id}` status to `{status}`")
    return _text(f"❌ Gap `{gap_id}` not found")
