"""Session Tools - Bootstrap and manage work sessions.

Provides tools for:
- session_start: Initialize a new work session with context
- Prompts for guided workflows (debug, review)

This module is workspace-aware and uses WorkspaceRegistry to maintain
per-workspace state (project, persona, issue, branch).
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from mcp.types import TextContent

from server.tool_registry import ToolRegistry
from server.utils import load_config

# Support both package import and direct loading
try:
    from .constants import KNOWLEDGE_DIR, MEMORY_DIR, PERSONAS_DIR
except ImportError:
    TOOL_MODULES_DIR = Path(__file__).parent.parent.parent
    PROJECT_DIR = TOOL_MODULES_DIR.parent
    PERSONAS_DIR = PROJECT_DIR / "personas"
    MEMORY_DIR = PROJECT_DIR / "memory"
    KNOWLEDGE_DIR = MEMORY_DIR / "knowledge" / "personas"

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context, FastMCP

logger = logging.getLogger(__name__)


# ==================== TOOL IMPLEMENTATIONS ====================


def _load_current_work(lines: list[str], project: str | None = None) -> None:
    """Load and append current work status for the specified project.

    Args:
        lines: List to append output lines to
        project: Project name. If None, uses current chat project.
    """
    # Import here to avoid circular imports
    try:
        from tool_modules.aa_workflow.src.chat_context import get_project_work_state_path
    except ImportError:
        try:
            from .chat_context import get_project_work_state_path
        except ImportError:
            from chat_context import get_project_work_state_path

    current_work_file = get_project_work_state_path(project)
    if not current_work_file.exists():
        lines.append("*No active work tracked for this project. Use `start_work` skill to begin.*\n")
        return

    try:
        with open(current_work_file) as f:
            work = yaml.safe_load(f) or {}

        active = work.get("active_issues", [])
        mrs = work.get("open_mrs", [])
        followups = work.get("follow_ups", [])

        if active or mrs or followups:
            lines.append("## 📋 Current Work\n")

            if active:
                lines.append("### Active Issues")
                for issue in active:
                    lines.append(f"- **{issue.get('key', '?')}**: {issue.get('summary', 'No summary')}")
                    lines.append(f"  Status: {issue.get('status', '?')} | Branch: `{issue.get('branch', '?')}`")
                lines.append("")

            if mrs:
                lines.append("### Open MRs")
                for mr in mrs:
                    lines.append(f"- **!{mr.get('id', '?')}**: {mr.get('title', 'No title')}")
                    lines.append(f"  Pipeline: {mr.get('pipeline_status', '?')}")
                lines.append("")

            if followups:
                lines.append("### Follow-ups")
                for fu in followups[:5]:
                    priority = fu.get("priority", "normal")
                    emoji = "🔴" if priority == "high" else "🟡" if priority == "medium" else "⚪"
                    lines.append(f"- {emoji} {fu.get('task', '?')}")
                if len(followups) > 5:
                    lines.append(f"*...and {len(followups) - 5} more*")
                lines.append("")
        else:
            lines.append("*No active work tracked for this project. Use `start_work` skill to begin.*\n")

    except Exception as e:
        lines.append(f"*Could not load work state: {e}*\n")


def _load_environment_status(lines: list[str]) -> None:
    """Load and append environment status."""
    env_file = MEMORY_DIR / "state" / "environments.yaml"
    if not env_file.exists():
        return

    try:
        with open(env_file) as f:
            env_data = yaml.safe_load(f) or {}

        envs = env_data.get("environments", {})
        if not envs:
            return

        env_summary = []
        for env_name, env_info in envs.items():
            if env_name == "ephemeral":
                active_ns = env_info.get("active_namespaces", [])
                if active_ns:
                    env_summary.append(f"🧪 {len(active_ns)} ephemeral namespace(s)")
            else:
                status = env_info.get("status", "unknown")
                if status == "issues":
                    alerts = env_info.get("alerts", [])
                    alert_count = len(alerts)
                    env_summary.append(f"⚠️ {env_name}: {alert_count} alert(s)")
                elif status == "healthy":
                    env_summary.append(f"✅ {env_name}")

        if env_summary:
            lines.append("## 🌐 Environments\n")
            for item in env_summary[:5]:
                lines.append(f"- {item}")
            lines.append("")

    except Exception:
        pass


def _load_session_history(lines: list[str]) -> None:
    """Load and append today's session history."""
    today = datetime.now().strftime("%Y-%m-%d")
    session_file = MEMORY_DIR / "sessions" / f"{today}.yaml"
    if not session_file.exists():
        return

    try:
        with open(session_file) as f:
            session = yaml.safe_load(f) or {}
        entries = session.get("entries", [])
        if entries:
            lines.append("## 📝 Today's Session History\n")
            for entry in entries[-5:]:
                lines.append(f"- [{entry.get('time', '?')}] {entry.get('action', '?')}")
            lines.append("")
    except Exception:
        pass


def _load_persona_info(lines: list[str], agent: str) -> None:
    """Load and append persona information."""
    current_persona = None
    loaded_modules = []
    try:
        from server.persona_loader import get_loader

        loader = get_loader()
        if loader:
            current_persona = loader.current_persona
            loaded_modules = list(loader.loaded_modules)
    except Exception:
        pass

    if agent:
        agent_file = PERSONAS_DIR / f"{agent}.md"
        if agent_file.exists():
            lines.append(f"## 🤖 Agent: {agent}\n")
            lines.append("*Loading agent persona...*\n")
            lines.append("---\n")
            lines.append(agent_file.read_text())
        else:
            lines.append(f"*Agent '{agent}' not found. Available: devops, developer, incident, release*\n")
    elif current_persona:
        lines.append(f"## 🤖 Active Persona: {current_persona}\n")
        if loaded_modules:
            lines.append(f"**Loaded modules:** {', '.join(sorted(loaded_modules))}\n")
        lines.append("Use `persona_load(name)` to switch personas.\n")
    else:
        if loaded_modules and any(m in loaded_modules for m in ["git", "gitlab", "jira"]):
            lines.append("## 🤖 Active Persona: developer (default)\n")
            lines.append(f"**Loaded modules:** {', '.join(sorted(loaded_modules))}\n")
        else:
            lines.append("## 💡 Available Personas\n")
            lines.append("Load one with `persona_load(name)` or `session_start(agent='name')`:\n")
            lines.append("- **devops** - Infrastructure, monitoring, deployments")
            lines.append("- **developer** - Coding, PRs, code review")
            lines.append("- **incident** - Production issues, triage")
            lines.append("- **release** - Shipping, coordination")
        lines.append("")


def _load_learned_patterns(lines: list[str]) -> None:
    """Load and append learned patterns summary."""
    patterns_file = MEMORY_DIR / "learned" / "patterns.yaml"
    if not patterns_file.exists():
        return

    try:
        with open(patterns_file) as f:
            patterns = yaml.safe_load(f) or {}

        jira_patterns = patterns.get("jira_cli_patterns", [])
        error_patterns = patterns.get("error_patterns", [])
        auth_patterns = patterns.get("auth_patterns", [])
        bonfire_patterns = patterns.get("bonfire_patterns", [])
        pipeline_patterns = patterns.get("pipeline_patterns", [])

        total = (
            len(jira_patterns)
            + len(error_patterns)
            + len(auth_patterns)
            + len(bonfire_patterns)
            + len(pipeline_patterns)
        )

        if total > 0:
            lines.append("## 🧠 Learned Patterns\n")
            lines.append(f"*{total} patterns loaded from memory*\n")
            if jira_patterns:
                lines.append(f"- **Jira CLI**: {len(jira_patterns)} patterns")
            if error_patterns:
                lines.append(f"- **Error handling**: {len(error_patterns)} patterns")
            if auth_patterns:
                lines.append(f"- **Authentication**: {len(auth_patterns)} patterns")
            if bonfire_patterns:
                lines.append(f"- **Bonfire/Ephemeral**: {len(bonfire_patterns)} patterns")
            if pipeline_patterns:
                lines.append(f"- **Pipelines**: {len(pipeline_patterns)} patterns")
            lines.append("")
            lines.append("*Use `memory_read('learned/patterns')` for details*")
            lines.append("")

    except Exception:
        pass


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


def _get_current_persona() -> str | None:
    """Get the currently loaded persona."""
    try:
        from server.persona_loader import get_loader

        loader = get_loader()
        if loader:
            return loader.current_persona
    except Exception:
        pass
    return None


def _load_project_knowledge(lines: list[str], agent: str) -> str | None:
    """Load and append project knowledge if available.

    Returns the detected project name, or None.
    """
    # Detect project from cwd
    project = _detect_project_from_cwd()
    if not project:
        return None

    # Determine persona
    persona = agent or _get_current_persona() or "developer"

    # Check if knowledge exists
    knowledge_path = KNOWLEDGE_DIR / persona / f"{project}.yaml"

    if knowledge_path.exists():
        try:
            with open(knowledge_path) as f:
                knowledge = yaml.safe_load(f) or {}

            metadata = knowledge.get("metadata", {})
            confidence = metadata.get("confidence", 0)
            confidence_emoji = "🟢" if confidence > 0.7 else "🟡" if confidence > 0.4 else "🔴"

            lines.append(f"## 📚 Project Knowledge: {project}\n")
            lines.append(f"*Persona: {persona} | Confidence: {confidence_emoji} {confidence:.0%}*\n")

            # Show architecture overview if available
            arch = knowledge.get("architecture", {})
            if arch.get("overview"):
                overview = arch["overview"][:200]
                if len(arch["overview"]) > 200:
                    overview += "..."
                lines.append(f"**Overview:** {overview}\n")

            # Show key modules
            key_modules = arch.get("key_modules", [])[:3]
            if key_modules:
                lines.append("**Key Modules:**")
                for module in key_modules:
                    lines.append(f"- `{module.get('path', '?')}`: {module.get('purpose', '')}")
                lines.append("")

            # Show gotchas count
            gotchas = knowledge.get("gotchas", [])
            learned = knowledge.get("learned_from_tasks", [])
            if gotchas or learned:
                lines.append(f"*{len(gotchas)} gotchas, {len(learned)} learnings recorded*")
                lines.append("")

            lines.append("*Use `knowledge_query()` for details or `knowledge_learn()` to add insights*")
            lines.append("")

            return project

        except Exception as e:
            logger.warning(f"Failed to load knowledge: {e}")
            return project

    else:
        # Knowledge doesn't exist - will be auto-scanned
        lines.append(f"## 📚 Project Detected: {project}\n")
        lines.append(f"*No knowledge yet for {persona} persona. Auto-scanning...*\n")

        # Trigger auto-scan
        try:
            from .knowledge_tools import _generate_initial_knowledge, _save_knowledge

            config = load_config()
            project_config = config.get("repositories", {}).get(project, {})
            project_path = Path(project_config.get("path", "")).expanduser()

            if project_path.exists():
                knowledge = _generate_initial_knowledge(project, persona, project_path)
                _save_knowledge(persona, project, knowledge)

                lines.append("✅ **Initial knowledge generated!**\n")

                # Show brief summary
                arch = knowledge.get("architecture", {})
                deps = arch.get("dependencies", [])[:5]
                if deps:
                    lines.append(f"**Dependencies:** {', '.join(f'`{d}`' for d in deps)}")
                    lines.append("")

                lines.append("*Knowledge will improve as you complete tasks.*")
                lines.append("")

        except Exception as e:
            logger.warning(f"Failed to auto-scan project: {e}")
            lines.append(f"*Auto-scan failed: {e}. Run `knowledge_scan()` manually.*")
            lines.append("")

        return project


def _load_chat_context(lines: list[str]) -> str:
    """Load and display chat context (project, issue, branch) - sync version."""
    try:
        from .chat_context import get_chat_state, get_chat_project
    except ImportError:
        from chat_context import get_chat_state, get_chat_project

    state = get_chat_state()
    project = state["project"]

    lines.append("## 📁 Workspace Context\n")
    lines.append(f"**Project:** `{project}`")

    if state.get("is_auto_detected"):
        lines.append("  *(auto-detected from workspace)*")
    elif state["is_default"]:
        lines.append("  *(default - use `project_context(project='...')` to change)*")

    if state.get("persona"):
        lines.append(f"**Persona:** `{state['persona']}`")

    if state["issue_key"]:
        lines.append(f"**Active Issue:** `{state['issue_key']}`")

    if state["branch"]:
        lines.append(f"**Active Branch:** `{state['branch']}`")

    lines.append("")

    return project


async def _load_chat_context_async(ctx: "Context", lines: list[str]) -> str:
    """Load and display chat context (project, issue, branch) - async version.

    Uses WorkspaceRegistry for per-workspace state.
    """
    from server.workspace_utils import get_workspace_from_ctx

    state = await get_workspace_from_ctx(ctx)
    project = state.project or "redhat-ai-workflow"

    lines.append("## 📁 Workspace Context\n")
    lines.append(f"**Project:** `{project}`")

    if state.is_auto_detected:
        lines.append("  *(auto-detected from workspace)*")
    elif state.project is None:
        lines.append("  *(default - use `project_context(project='...')` to change)*")

    if state.persona:
        lines.append(f"**Persona:** `{state.persona}`")

    if state.issue_key:
        lines.append(f"**Active Issue:** `{state.issue_key}`")

    if state.branch:
        lines.append(f"**Active Branch:** `{state.branch}`")

    # Show workspace URI for debugging (only if not default)
    if state.workspace_uri and state.workspace_uri != "default":
        lines.append(f"\n*Workspace: {state.workspace_uri}*")

    lines.append("")

    return project


async def _detect_project_from_mcp_roots(ctx) -> str | None:
    """Try to detect project from MCP workspace roots.

    Cursor may provide workspace roots via the MCP protocol.
    This is more reliable than cwd detection since it reflects
    the actual workspace open in the editor.
    """
    import logging

    logger = logging.getLogger(__name__)

    if ctx is None:
        logger.debug("No context provided for MCP roots detection")
        return None

    try:
        session = ctx.session
        logger.debug("Requesting workspace roots from client...")
        roots_result = await session.list_roots()

        if not roots_result or not roots_result.roots:
            logger.debug("No roots returned by client")
            return None

        logger.info(f"Client returned {len(roots_result.roots)} workspace root(s)")
        for root in roots_result.roots:
            logger.debug(f"  Root: {root.name or '(unnamed)'} -> {root.uri}")

        # Load config to match roots against known projects
        from server.utils import load_config

        config = load_config()
        if not config:
            return None

        repositories = config.get("repositories", {})

        # Check each root against known project paths
        for root in roots_result.roots:
            # Convert file:// URI to path
            root_uri = str(root.uri)
            if root_uri.startswith("file://"):
                root_path = root_uri[7:]  # Remove file://
            else:
                root_path = root_uri

            # Match against configured repositories
            for project_name, project_config in repositories.items():
                project_path = project_config.get("path", "")
                if project_path and root_path.rstrip("/") == project_path.rstrip("/"):
                    logger.info(f"Detected project '{project_name}' from MCP root: {root_path}")
                    return project_name

        logger.debug("No matching project found for any root")
        return None
    except Exception as e:
        # MCP roots not available or error - fall back to other detection
        logger.debug(f"MCP roots detection failed: {e}")
        return None


async def _session_start_impl(
    ctx: "Context | None" = None,
    agent: str = "",
    project: str = "",
    name: str = "",
    memory_session_log_fn=None,
    resume_session_id: str = "",
) -> list[TextContent]:
    """Implementation of session_start tool.

    Uses WorkspaceRegistry for per-workspace state management.
    Creates a new ChatSession or resumes an existing one.
    """
    # #region agent log
    import json as _json; open('/home/daoneill/src/redhat-ai-workflow/.cursor/debug.log', 'a').write(_json.dumps({"location": "session_tools.py:_session_start_impl:entry", "message": "session_start called", "data": {"agent": agent, "project": project, "name": name, "resume_session_id": resume_session_id}, "timestamp": __import__('time').time() * 1000, "sessionId": "debug-session", "hypothesisId": "C"}) + '\n')
    # #endregion
    # Track session start in stats
    from tool_modules.aa_workflow.src.agent_stats import start_session

    start_session()

    is_resumed = False
    session_id = None

    # Use workspace-aware context if ctx is available
    if ctx:
        from server.workspace_state import WorkspaceRegistry

        # Get workspace state
        workspace = await WorkspaceRegistry.get_for_ctx(ctx)
        # #region agent log
        import json as _json; open('/home/daoneill/src/redhat-ai-workflow/.cursor/debug.log', 'a').write(_json.dumps({"location": "session_tools.py:_session_start_impl:workspace", "message": "Got workspace from ctx", "data": {"workspace_uri": workspace.workspace_uri, "workspace_project": workspace.project, "is_auto_detected": workspace.is_auto_detected, "session_count": len(workspace.sessions)}, "timestamp": __import__('time').time() * 1000, "sessionId": "debug-session", "hypothesisId": "A,C"}) + '\n')
        # #endregion

        # Check if we're resuming an existing session
        if resume_session_id:
            existing_session = workspace.get_session(resume_session_id)
            if existing_session:
                # Resume the existing session
                workspace.set_active_session(resume_session_id)
                chat_session = existing_session
                session_id = resume_session_id
                is_resumed = True
                
                # Update persona if provided
                if agent:
                    chat_session.persona = agent
                
                # Update name if provided
                if name:
                    chat_session.name = name
                
                chat_session.touch()
                logger.info(f"Resumed session {session_id}")
            else:
                # Session not found - list available sessions
                available = list(workspace.sessions.keys())
                lines = [
                    f"# ⚠️ Session Not Found\n",
                    f"Session `{resume_session_id}` does not exist.\n",
                    f"**Available sessions:** {', '.join(f'`{s}`' for s in available) or 'none'}\n",
                    f"Creating a new session instead...\n",
                    "---\n",
                ]
                # Fall through to create new session
                resume_session_id = ""

        if not is_resumed:
            lines = ["# 🚀 Session Started\n"]
            
            # Determine project for this session
            # If explicitly provided, use that; otherwise auto-detect from workspace
            session_project = project if project else workspace.project
            is_auto_detected = not bool(project) and workspace.is_auto_detected
            
            # Create a new chat session with its own project
            persona = agent or "developer"
            chat_session = workspace.create_session(
                persona=persona, 
                name=name or None,
                project=session_project,
                is_project_auto_detected=is_auto_detected,
            )
            session_id = chat_session.session_id
            
            # #region agent log
            import json as _json; open('/home/daoneill/src/redhat-ai-workflow/.cursor/debug.log', 'a').write(_json.dumps({"location": "session_tools.py:_session_start_impl:new_session", "message": "Created new session with project", "data": {"session_id": session_id, "project": session_project, "is_auto_detected": is_auto_detected, "explicit_project": project}, "timestamp": __import__('time').time() * 1000, "sessionId": "debug-session", "hypothesisId": "per-session"}) + '\n')
            # #endregion
        else:
            # For resumed sessions, update project if explicitly provided
            if project:
                chat_session.project = project
                chat_session.is_project_auto_detected = False
                # #region agent log
                import json as _json; open('/home/daoneill/src/redhat-ai-workflow/.cursor/debug.log', 'a').write(_json.dumps({"location": "session_tools.py:_session_start_impl:resume_update_project", "message": "Updated resumed session project", "data": {"session_id": session_id, "project": project}, "timestamp": __import__('time').time() * 1000, "sessionId": "debug-session", "hypothesisId": "per-session"}) + '\n')
                # #endregion
        
        # Use the session's project (not workspace's) for the rest of the function
        project = chat_session.project

        # Set persona on the session if agent provided (for new sessions)
        if agent and not is_resumed:
            chat_session.persona = agent

        # Load chat context using async version
        chat_project = await _load_chat_context_async(ctx, lines)

        # Add session ID and total session count to output
        total_sessions = workspace.session_count()
        session_name_info = f" - *{name or chat_session.name}*" if (name or chat_session.name) else ""
        
        # Get project info for display
        session_project = chat_session.project or workspace.project or 'default'
        project_source = "(auto-detected)" if chat_session.is_project_auto_detected else "(explicit)"
        
        if is_resumed:
            lines = [
                "# 🔄 Session Resumed\n",
                f"**Session ID:** `{session_id}`{session_name_info} *(1 of {total_sessions} sessions in this workspace)*\n",
                f"**Project:** {session_project} {project_source}\n",
                f"**Persona:** {chat_session.persona}\n",
            ]
            if chat_session.issue_key:
                lines.append(f"**Active Issue:** {chat_session.issue_key}\n")
            if chat_session.branch:
                lines.append(f"**Branch:** {chat_session.branch}\n")
            lines.append("")
        else:
            lines.insert(
                1,
                f"**Session ID:** `{session_id}`{session_name_info} *(1 of {total_sessions} sessions in this workspace)*\n"
            )
            lines.insert(2, f"**Project:** {session_project} {project_source}\n")
            lines.insert(3, "⚠️ **SAVE THIS SESSION ID** - Pass it to `session_info(session_id=\"...\")` to track YOUR session.\n")
    else:
        # Fallback to sync version for backward compatibility (no ctx available)
        lines = ["# 🚀 Session Started\n"]
        
        # Detect project from MCP roots if not explicitly provided
        detected_from_roots = None
        if not project:
            detected_from_roots = await _detect_project_from_mcp_roots(ctx) if ctx else None
            if detected_from_roots:
                project = detected_from_roots

        # Set project context if provided (explicitly or from roots)
        if project:
            try:
                from .chat_context import set_chat_project
            except ImportError:
                from chat_context import set_chat_project
            set_chat_project(project)

        # Load chat context using sync version
        chat_project = _load_chat_context(lines)

    # Load all context sections using helper functions
    # Pass the chat project to load project-specific work state
    _load_current_work(lines, chat_project)
    _load_environment_status(lines)
    _load_session_history(lines)
    _load_persona_info(lines, agent)
    _load_learned_patterns(lines)

    # Load project-specific knowledge (auto-scans if needed)
    # Use chat project if no project detected from cwd
    detected_project = _load_project_knowledge(lines, agent) or chat_project

    # Show available skills
    lines.append("## ⚡ Quick Skills\n")
    lines.append("Run with `skill_run(name, inputs)`:\n")
    lines.append("- **start_work** - Begin Jira issue (creates branch, updates status)")
    lines.append("- **create_mr** - Create MR with proper formatting")
    lines.append("- **investigate_alert** - Systematic alert investigation")
    lines.append("- **memory_view** - View/manage persistent memory")
    lines.append("- **coffee** - Morning briefing (calendar, email, PRs)")
    lines.append("- **beer** - End of day wrap-up")
    lines.append("")

    # Show tool usage guidance
    lines.append("## 🛠️ Tool Usage\n")
    lines.append("**ALWAYS prefer MCP tools over CLI commands!**\n")
    lines.append("| Instead of CLI | Use MCP Tool |")
    lines.append("|---------------|--------------|")
    lines.append("| `rh-issue set-status ...` | `jira_set_status()` |")
    lines.append("| `git checkout -b ...` | `git_branch_create()` |")
    lines.append("| `glab mr create ...` | `gitlab_mr_create()` |")
    lines.append("| `kubectl get pods ...` | `kubectl_get_pods()` |")
    lines.append("")
    lines.append("Use `tool_list()` to see all available tools.")
    lines.append("Use `check_known_issues(tool, error)` when tools fail.")
    lines.append("")

    # Log session start (if function provided)
    if memory_session_log_fn:
        project_info = f", Project: {detected_project}" if detected_project else ""
        await memory_session_log_fn("Session started", f"Agent: {agent or 'none'}{project_info}")

    # Export workspace state for VS Code extension
    try:
        from tool_modules.aa_workflow.src.workspace_exporter import export_workspace_state_async

        logger.info("session_start: About to export workspace state")
        result = await export_workspace_state_async(ctx)
        logger.info(f"session_start: Export result: {result}")
    except Exception as e:
        logger.warning(f"Failed to export workspace state: {e}")
        import traceback
        logger.warning(f"Traceback: {traceback.format_exc()}")

    return [TextContent(type="text", text="\n".join(lines))]


def register_session_tools(server: "FastMCP", memory_session_log_fn=None) -> int:
    """Register session tools with the MCP server.

    Args:
        server: The FastMCP server instance
        memory_session_log_fn: Optional function to log session actions
    """
    from mcp.server.fastmcp import Context

    registry = ToolRegistry(server)

    @registry.tool()
    async def debug_mcp_roots(ctx: Context) -> list[TextContent]:
        """Debug tool to inspect MCP workspace roots and session info from Cursor.

        Use this to see what workspace and session information Cursor provides.
        This helps diagnose project detection and chat identification.
        """
        lines = ["# MCP Context Debug\n"]

        try:
            # Inspect the context object itself
            lines.append("## Context Object\n")
            lines.append(f"**Type:** `{type(ctx).__name__}`")
            ctx_attrs = [a for a in dir(ctx) if not a.startswith("_")]
            lines.append(f"**Attributes:** `{', '.join(ctx_attrs)}`")

            # Check for request_id or other identifiers on ctx
            for attr in ["request_id", "id", "session_id", "chat_id", "conversation_id"]:
                if hasattr(ctx, attr):
                    lines.append(f"**ctx.{attr}:** `{getattr(ctx, attr)}`")

            session = ctx.session
            lines.append("\n## Session Object\n")
            lines.append(f"**Type:** `{type(session).__name__}`")
            session_attrs = [a for a in dir(session) if not a.startswith("_")]
            lines.append(f"**Attributes:** `{', '.join(session_attrs)}`")

            # Check for any ID-like attributes on session
            for attr in ["id", "session_id", "request_id", "client_id", "conversation_id", "chat_id"]:
                if hasattr(session, attr):
                    val = getattr(session, attr)
                    lines.append(f"**session.{attr}:** `{val}`")

            # Check client info
            if hasattr(session, "client_params") and session.client_params:
                params = session.client_params
                lines.append("\n## Client Parameters\n")
                params_attrs = [a for a in dir(params) if not a.startswith("_")]
                lines.append(f"**Attributes:** `{', '.join(params_attrs)}`")

                if params.clientInfo:
                    lines.append(f"**Client:** `{params.clientInfo.name}` v`{params.clientInfo.version}`")
                    # Check for any ID on clientInfo
                    client_attrs = [a for a in dir(params.clientInfo) if not a.startswith("_")]
                    lines.append(f"**ClientInfo attrs:** `{', '.join(client_attrs)}`")

                # Check roots capability
                if params.capabilities and params.capabilities.roots:
                    lines.append(f"**Roots Capability:** `{params.capabilities.roots}`")
                else:
                    lines.append("**Roots Capability:** *Not advertised*")

            # Try to list roots
            lines.append("\n## Workspace Roots\n")
            try:
                roots_result = await session.list_roots()
                if roots_result and roots_result.roots:
                    for root in roots_result.roots:
                        name = root.name or "(unnamed)"
                        lines.append(f"- **{name}**: `{root.uri}`")
                        # Check for any additional attributes on root
                        root_attrs = [a for a in dir(root) if not a.startswith("_")]
                        lines.append(f"  Root attrs: `{', '.join(root_attrs)}`")

                    # Try to match against projects
                    lines.append("\n## Project Detection\n")
                    detected = await _detect_project_from_mcp_roots(ctx)
                    if detected:
                        lines.append(f"✅ Detected project: **{detected}**")
                    else:
                        lines.append("❌ No matching project found in config.json")
                else:
                    lines.append("*No roots returned by client*")
            except Exception as e:
                lines.append(f"*Error listing roots: {e}*")

            # Check for any other interesting session methods
            lines.append("\n## Session Methods\n")
            methods = [m for m in dir(session) if callable(getattr(session, m, None)) and not m.startswith("_")]
            lines.append(f"**Methods:** `{', '.join(methods)}`")

            # Check request_context for more details
            lines.append("\n## Request Context\n")
            if hasattr(ctx, "request_context") and ctx.request_context:
                rc = ctx.request_context
                lines.append(f"**request_id:** `{rc.request_id}`")
                if rc.meta:
                    lines.append(f"**meta:** `{rc.meta}`")
                    meta_attrs = [a for a in dir(rc.meta) if not a.startswith("_")]
                    lines.append(f"**meta attrs:** `{', '.join(meta_attrs)}`")
                    # Dump all meta attributes
                    for attr in meta_attrs:
                        try:
                            val = getattr(rc.meta, attr)
                            if not callable(val):
                                lines.append(f"**meta.{attr}:** `{val}`")
                        except Exception:
                            pass
                if hasattr(rc, "request") and rc.request:
                    lines.append(f"**request type:** `{type(rc.request).__name__}`")
                    req_attrs = [a for a in dir(rc.request) if not a.startswith("_")]
                    lines.append(f"**request attrs:** `{', '.join(req_attrs)}`")

            # Check ctx.client_id
            lines.append("\n## Client Identification\n")
            lines.append(f"**ctx.request_id:** `{ctx.request_id}`")
            lines.append(f"**ctx.client_id:** `{ctx.client_id}`")

        except Exception as e:
            import traceback
            lines.append(f"**Error:** {e}")
            lines.append(f"```\n{traceback.format_exc()}\n```")

        return [TextContent(type="text", text="\n".join(lines))]

    @registry.tool()
    async def session_start(
        ctx: Context, agent: str = "", project: str = "", name: str = "", session_id: str = ""
    ) -> list[TextContent]:
        """
        Initialize a new session or resume an existing one.

        IMPORTANT FOR MULTI-CHAT SUPPORT:
        - Each Cursor chat should have its OWN session_id
        - When you call session_start() without session_id, a NEW session is created
        - SAVE the returned session_id and pass it to session_info() to track YOUR session
        - To resume a previous session, pass its session_id

        This is the FIRST tool to call when starting work. It loads:
        - Chat context (project, issue, branch for THIS chat)
        - Current work state (active issues, branches, MRs)
        - Today's session history (if resuming)
        - Optionally loads an agent persona

        Args:
            agent: Optional agent to load ("devops", "developer", "incident", "release")
            project: Optional project to work on (e.g., "automation-analytics-backend").
                     Defaults to "redhat-ai-workflow" if not specified.
            name: Optional friendly name for this session (e.g., "Working on AAP-12345").
                  Helps identify sessions in the UI.
            session_id: Optional session ID to resume. If provided and valid, resumes
                        that session instead of creating a new one.

        Returns:
            Complete session context including YOUR session_id (save this!).

        Examples:
            session_start()  # Create new session, returns session_id
            session_start(session_id="abc123")  # Resume existing session
            session_start(project="automation-analytics-backend")  # New session for backend
            session_start(agent="devops", project="app-interface")  # DevOps on app-interface
            session_start(name="Fixing billing bug")  # Named session for easy identification
        """
        return await _session_start_impl(ctx, agent, project, name, memory_session_log_fn, session_id)

    return registry.count


def register_prompts(server: "FastMCP") -> int:
    """Register prompts with the MCP server."""
    prompt_count = 0

    @server.prompt()
    async def session_init() -> str:
        """
        Initialize a new work session.

        Use this prompt to start a productive session with full context.
        """
        return """You are an AI assistant helping with software development.

Start by calling session_start() to load your current work context.

If you know the type of work:
- DevOps tasks: session_start(agent="devops")
- Development: session_start(agent="developer")
- Incidents: session_start(agent="incident")
- Releases: session_start(agent="release")

After loading context, ask what the user wants to work on today."""

    prompt_count += 1

    @server.prompt()
    async def debug_guide() -> str:
        """
        Guide for debugging production issues.

        Provides a systematic approach to production debugging.
        """
        return """# Production Debugging Guide

## 1. Gather Context
- Which namespace? (tower-analytics-prod or tower-analytics-prod-billing)
- Any specific alert that fired?
- When did the issue start?

## 2. Check Pod Health
```
kubectl_get_pods(namespace="tower-analytics-prod", environment="prod")
```
Look for: CrashLoopBackOff, OOMKilled, Pending, high restarts

## 3. Check Events
```
kubectl_get_events(namespace="tower-analytics-prod", environment="prod")
```
Look for: Warning, Error, FailedScheduling

## 4. Check Logs
```
kubectl_logs(pod="<pod-name>", namespace="tower-analytics-prod", environment="prod", tail=100)
```
Grep for: error, exception, fatal, timeout

## 5. Check Alerts
```
prometheus_alerts(environment="prod")
```

## 6. Check Recent Deployments
Was there a recent deployment? Check app-interface for recent changes.

## 7. Match Against Known Patterns
Use memory_read("learned/patterns") to check for known issues.

## 8. Document Findings
Use memory_session_log() to record what you find."""

    prompt_count += 1

    @server.prompt()
    async def review_guide() -> str:
        """
        Guide for reviewing merge requests.

        Provides a structured approach to code review.
        """
        return """# Code Review Guide

## 1. Get MR Context
```
gitlab_mr_view(project="<project>", mr_id=<id>)
```

## 2. Check Linked Jira
```
jira_view_issue("<ISSUE-KEY>")
```
- Does the MR address the issue requirements?
- Are acceptance criteria met?

## 3. Review Changes
```
gitlab_mr_diff(project="<project>", mr_id=<id>)
```

### What to Look For:
- **Security**: SQL injection, secrets in code, unsafe deserialization
- **Performance**: N+1 queries, missing indexes, large memory allocations
- **Correctness**: Edge cases, error handling, race conditions
- **Style**: Consistent with codebase, clear naming, appropriate comments

## 4. Check Pipeline
```
gitlab_ci_status(project="<project>")
```
- All tests passing?
- No linter failures?

## 5. Provide Feedback
Be constructive, specific, and kind. Suggest alternatives, don't just criticize."""

    prompt_count += 1

    return prompt_count
