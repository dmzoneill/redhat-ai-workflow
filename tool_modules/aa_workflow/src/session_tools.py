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
from fastmcp import Context
from mcp.types import TextContent

from server.auto_heal_decorator import auto_heal
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
    from fastmcp import FastMCP

logger = logging.getLogger(__name__)


# ==================== BOOTSTRAP CONTEXT ====================


async def _get_bootstrap_context(
    project: str | None, session_name: str | None
) -> dict | None:
    """Get bootstrap context using the memory abstraction layer.

    Queries memory to get:
    - Intent classification based on project/session context
    - Suggested persona based on current work
    - Active issues and recommended actions
    - Related Slack discussions
    - Related code context

    Args:
        project: Current project name
        session_name: Optional session name (may contain intent hints)

    Returns:
        Bootstrap context dict or None if unavailable
    """
    try:
        from services.memory_abstraction import get_memory_interface
    except ImportError:
        logger.debug("Memory abstraction not available for bootstrap")
        return None

    try:
        memory = get_memory_interface()

        # Build query based on available context
        query_parts = []
        if project:
            query_parts.append(f"project {project}")
        if session_name:
            query_parts.append(session_name)
        query_parts.append("current work status")

        query = " ".join(query_parts)

        # Query only FAST sources for bootstrap (local operations only)
        # Slow sources (external APIs like inscope, jira, gitlab, gmail, gdrive, calendar)
        # are available via memory_query but not included in bootstrap to keep startup fast
        # Fast sources: yaml (local files), code (local vector), slack (local vector)
        fast_sources = ["yaml", "code", "slack"]

        result = await memory.query(
            question=query,
            sources=fast_sources,  # Only fast local sources
        )

        # Extract bootstrap context from result
        # Note: slow_sources_available tells the AI what additional sources can be queried
        bootstrap = {
            "intent": result.intent.to_dict(),
            "current_work": {},
            "suggested_persona": None,
            "persona_confidence": 0.0,
            "recommended_actions": [],
            "related_slack": [],  # Recent relevant Slack discussions
            "related_code": [],  # Related code snippets
            "sources_queried": result.sources_queried,
            "slow_sources_available": [
                "inscope",  # InScope AI documentation (2-120s)
                "jira",  # Jira issue details
                "gitlab",  # GitLab MRs/pipelines
                "github",  # GitHub PRs/issues
                "calendar",  # Google Calendar events
                "gmail",  # Gmail messages
                "gdrive",  # Google Drive files
            ],
        }

        # Extract context from each source type
        for item in result.items:
            source = item.source

            if source == "yaml":
                # Extract current work from yaml results
                if "current_work" in item.metadata.get("key", ""):
                    if "Active Issues:" in item.content:
                        issues = []
                        for line in item.content.split("\n"):
                            if line.startswith("- ") and ":" in line:
                                issue_key = line.split(":")[0].replace("- ", "").strip()
                                if issue_key.startswith("AAP-") or issue_key.startswith(
                                    "APPSRE-"
                                ):
                                    issues.append(issue_key)
                        bootstrap["current_work"]["active_issues"] = issues

            elif source == "slack":
                # Extract relevant Slack discussions (limit to top 3)
                if len(bootstrap["related_slack"]) < 3:
                    slack_item = {
                        "summary": item.summary,
                        "channel": item.metadata.get("channel", "unknown"),
                        "timestamp": item.metadata.get("timestamp", ""),
                        "relevance": item.relevance,
                    }
                    bootstrap["related_slack"].append(slack_item)

            elif source == "code":
                # Extract related code snippets (limit to top 3)
                if len(bootstrap["related_code"]) < 3:
                    code_item = {
                        "summary": item.summary,
                        "file": item.metadata.get(
                            "file_path", item.metadata.get("path", "unknown")
                        ),
                        "relevance": item.relevance,
                    }
                    bootstrap["related_code"].append(code_item)

        # Determine suggested persona based on intent
        intent = result.intent.intent
        persona_map = {
            "code_lookup": ("developer", 0.85),
            "troubleshooting": ("incident", 0.9),
            "status_check": ("developer", 0.7),
            "documentation": ("researcher", 0.8),
            "issue_context": ("developer", 0.85),
        }

        if intent in persona_map:
            persona, confidence = persona_map[intent]
            bootstrap["suggested_persona"] = persona
            bootstrap["persona_confidence"] = confidence

        # Generate recommended actions based on intent
        # Note: Actions that require slow sources should use memory_query explicitly
        action_map = {
            "code_lookup": [
                "Use code_search to find relevant code",
                "Check memory for similar patterns",
            ],
            "troubleshooting": [
                "Check learned/patterns for known fixes",
                "Load incident persona for debugging tools",
                "Use memory_query(sources=['jira']) for issue details",
            ],
            "status_check": [
                "Review active issues in current_work",
                "Use memory_query(sources=['gitlab']) for MR status",
            ],
            "issue_context": [
                "Use memory_query(sources=['jira']) for issue details",
                "Use memory_query(sources=['gitlab']) for related MRs",
            ],
            "documentation": [
                "Use memory_query(sources=['inscope']) for documentation",
                "Check knowledge base in memory/knowledge/",
            ],
        }

        # Map intents to suggested skills for direct execution
        skill_map = {
            "code_lookup": [
                "explain_code",
                "find_similar_code",
                "gather_context",
            ],
            "troubleshooting": [
                "debug_prod",
                "investigate_alert",
                "check_ci_health",
            ],
            "status_check": [
                "environment_overview",
                "check_my_prs",
                "konflux_status",
            ],
            "issue_context": [
                "start_work",
                "jira_hygiene",
                "close_issue",
            ],
            "documentation": [
                "learn_architecture",
                "explain_code",
                "update_docs",
            ],
            "deployment": [
                "deploy_to_ephemeral",
                "test_mr_ephemeral",
                "environment_overview",
            ],
            "gitlab": [
                "check_ci_health",
                "review_pr",
                "check_my_prs",
                "create_mr",
            ],
            "calendar": [
                "schedule_meeting",
                "sync_pto_calendar",
            ],
            "planning": [
                "sprint_planning",
                "plan_implementation",
                "work_analysis",
            ],
            "review": [
                "review_pr",
                "review_local_changes",
                "check_mr_feedback",
            ],
            "release": [
                "release_to_prod",
                "release_aa_backend_prod",
                "konflux_status",
            ],
            "alert": [
                "investigate_alert",
                "investigate_slack_alert",
                "silence_alert",
            ],
        }

        bootstrap["recommended_actions"] = action_map.get(
            intent,
            [
                "Use memory_query for more context",
                "Slow sources available: inscope, jira, gitlab, github, calendar, gmail, gdrive",
            ],
        )

        # Add suggested skills to bootstrap context
        if intent in skill_map:
            bootstrap["suggested_skills"] = skill_map[intent]

        return bootstrap

    except Exception as e:
        logger.warning(f"Failed to get bootstrap context: {e}")
        return None


# ==================== TOOL IMPLEMENTATIONS ====================


def _load_current_work(lines: list[str], project: str | None = None) -> None:
    """Load and append current work status for the specified project.

    Args:
        lines: List to append output lines to
        project: Project name. If None, uses current chat project.
    """
    # Import here to avoid circular imports
    try:
        from tool_modules.aa_workflow.src.chat_context import (
            get_project_work_state_path,
        )
    except ImportError:
        try:
            from .chat_context import get_project_work_state_path
        except ImportError:
            from chat_context import get_project_work_state_path

    current_work_file = get_project_work_state_path(project)
    if not current_work_file.exists():
        lines.append(
            "*No active work tracked for this project. Use `start_work` skill to begin.*\n"
        )
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
                    lines.append(
                        f"- **{issue.get('key', '?')}**: {issue.get('summary', 'No summary')}"
                    )
                    lines.append(
                        f"  Status: {issue.get('status', '?')} | Branch: `{issue.get('branch', '?')}`"
                    )
                lines.append("")

            if mrs:
                lines.append("### Open MRs")
                for mr in mrs:
                    lines.append(
                        f"- **!{mr.get('id', '?')}**: {mr.get('title', 'No title')}"
                    )
                    lines.append(f"  Pipeline: {mr.get('pipeline_status', '?')}")
                lines.append("")

            if followups:
                lines.append("### Follow-ups")
                for fu in followups[:5]:
                    priority = fu.get("priority", "normal")
                    emoji = (
                        "🔴"
                        if priority == "high"
                        else "🟡" if priority == "medium" else "⚪"
                    )
                    lines.append(f"- {emoji} {fu.get('task', '?')}")
                if len(followups) > 5:
                    lines.append(f"*...and {len(followups) - 5} more*")
                lines.append("")
        else:
            lines.append(
                "*No active work tracked for this project. Use `start_work` skill to begin.*\n"
            )

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

    except Exception as e:
        logger.debug(f"Suppressed error in _load_environment_status: {e}")


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
    except Exception as e:
        logger.debug(f"Suppressed error in _load_session_history: {e}")


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
    except Exception as e:
        logger.debug(f"Suppressed error in _load_persona_info: {e}")

    if agent:
        agent_file = PERSONAS_DIR / f"{agent}.md"
        if agent_file.exists():
            lines.append(f"## 🤖 Agent: {agent}\n")
            lines.append("*Loading agent persona...*\n")
            lines.append("---\n")
            lines.append(agent_file.read_text())
        else:
            lines.append(
                f"*Agent '{agent}' not found. Available: devops, developer, incident, release*\n"
            )
    elif current_persona:
        lines.append(f"## 🤖 Active Persona: {current_persona}\n")
        if loaded_modules:
            lines.append(f"**Loaded modules:** {', '.join(sorted(loaded_modules))}\n")
        lines.append("Use `persona_load(name)` to switch personas.\n")
    else:
        if loaded_modules and any(
            m in loaded_modules for m in ["git", "gitlab", "jira"]
        ):
            lines.append("## 🤖 Active Persona: developer (default)\n")
            lines.append(f"**Loaded modules:** {', '.join(sorted(loaded_modules))}\n")
        else:
            lines.append("## 💡 Available Personas\n")
            lines.append(
                "Load one with `persona_load(name)` or `session_start(agent='name')`:\n"
            )
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
                lines.append(
                    f"- **Bonfire/Ephemeral**: {len(bonfire_patterns)} patterns"
                )
            if pipeline_patterns:
                lines.append(f"- **Pipelines**: {len(pipeline_patterns)} patterns")
            lines.append("")
            lines.append("*Use `memory_read('learned/patterns')` for details*")
            lines.append("")

    except Exception as e:
        logger.debug(f"Suppressed error in _load_learned_patterns: {e}")


def _detect_project_from_cwd() -> str | None:
    """Detect project from current working directory."""
    config = load_config()
    if not config:
        return None

    try:
        cwd = Path.cwd().resolve()
    except Exception as e:
        logger.debug(f"Suppressed error in _detect_project_from_cwd: {e}")
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
    except Exception as e:
        logger.debug(f"Suppressed error in _get_current_persona: {e}")
    return None


def _load_project_knowledge(lines: list[str], agent: str) -> str | None:
    """Load and append project knowledge if available.

    Returns the detected project name, or None.
    """
    # Detect project from cwd
    project = _detect_project_from_cwd()
    if not project:
        return None

    # Determine persona - use config default as fallback
    if not agent and not _get_current_persona():
        from server.utils import load_config

        cfg = load_config()
        persona = cfg.get("agent", {}).get("default_persona", "researcher")
    else:
        persona = agent or _get_current_persona()

    # Check if knowledge exists
    knowledge_path = KNOWLEDGE_DIR / persona / f"{project}.yaml"

    if knowledge_path.exists():
        try:
            with open(knowledge_path) as f:
                knowledge = yaml.safe_load(f) or {}

            metadata = knowledge.get("metadata", {})
            confidence = metadata.get("confidence", 0)
            confidence_emoji = (
                "🟢" if confidence > 0.7 else "🟡" if confidence > 0.4 else "🔴"
            )

            lines.append(f"## 📚 Project Knowledge: {project}\n")
            lines.append(
                f"*Persona: {persona} | Confidence: {confidence_emoji} {confidence:.0%}*\n"
            )

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
                    lines.append(
                        f"- `{module.get('path', '?')}`: {module.get('purpose', '')}"
                    )
                lines.append("")

            # Show gotchas count
            gotchas = knowledge.get("gotchas", [])
            learned = knowledge.get("learned_from_tasks", [])
            if gotchas or learned:
                lines.append(
                    f"*{len(gotchas)} gotchas, {len(learned)} learnings recorded*"
                )
                lines.append("")

            lines.append(
                "*Use `knowledge_query()` for details or `knowledge_learn()` to add insights*"
            )
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
                    lines.append(
                        f"**Dependencies:** {', '.join(f'`{d}`' for d in deps)}"
                    )
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
        from .chat_context import get_chat_state
    except ImportError:
        from chat_context import get_chat_state

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
                    logger.info(
                        f"Detected project '{project_name}' from MCP root: {root_path}"
                    )
                    return project_name

        logger.debug("No matching project found for any root")
        return None
    except Exception as e:
        # MCP roots not available or error - fall back to other detection
        logger.debug(f"MCP roots detection failed: {e}")
        return None


async def _resume_session(
    workspace, resume_session_id: str, agent: str, project: str, name: str
):
    """Handle the session resume path.

    Finds the existing session, updates its fields, and returns session state.

    Args:
        workspace: WorkspaceState for the current workspace.
        resume_session_id: ID of the session to resume.
        agent: Optional agent/persona to set on the resumed session.
        project: Optional project to set on the resumed session.
        name: Optional name to set on the resumed session.

    Returns:
        Tuple of (lines, session_id, chat_session, is_resumed).
        If the session is not found, is_resumed is False and a fallback
        to new-session creation is expected.
    """
    from server.workspace_state import WorkspaceRegistry

    existing_session = workspace.get_session(resume_session_id)
    if existing_session:
        # Resume the existing session
        workspace.set_active_session(resume_session_id)
        chat_session = existing_session
        session_id = resume_session_id

        # Update persona if provided
        if agent:
            chat_session.persona = agent

        # Update name if provided
        if name:
            chat_session.name = name

        chat_session.touch()
        logger.info(f"Resumed session {session_id}")

        # Emit notification for session resume
        try:
            from .notification_emitter import notify_session_resumed

            notify_session_resumed(session_id, name or chat_session.name)
        except Exception as e:
            logger.debug(f"Suppressed error in notify_session_resumed: {e}")

        # For resumed sessions, update project if explicitly provided
        if project:
            chat_session.project = project
            chat_session.is_project_auto_detected = False
            # Persist the project change to disk
            WorkspaceRegistry.save_to_disk()
            logger.info(
                f"Updated and persisted project '{project}' for resumed session {session_id}"
            )

        lines: list[str] = []  # Will be rebuilt in _build_session_output
        return lines, session_id, chat_session, True
    else:
        # Session not found - list available sessions
        available = list(workspace.sessions.keys())
        lines = [
            "# \u26a0\ufe0f Session Not Found\n",
            f"Session `{resume_session_id}` does not exist.\n",
            f"**Available sessions:** {', '.join(f'`{s}`' for s in available) or 'none'}\n",
            "Creating a new session instead...\n",
            "---\n",
        ]
        return lines, None, None, False


async def _create_new_session(workspace, agent: str, project: str, name: str):
    """Handle creating a new session.

    Args:
        workspace: WorkspaceState for the current workspace.
        agent: Optional agent/persona for the new session.
        project: Optional explicit project for the new session.
        name: Optional friendly name for the new session.

    Returns:
        Tuple of (lines, session_id, chat_session).
    """
    lines = ["# \U0001f680 Session Started\n"]

    # Determine project for this session
    # If explicitly provided, use that; otherwise auto-detect from workspace
    session_project = project if project else workspace.project
    is_auto_detected = not bool(project) and workspace.is_auto_detected

    # Create a new chat session with its own project
    # Get default persona from config
    from server.utils import load_config

    cfg = load_config()
    default_persona = cfg.get("agent", {}).get("default_persona", "researcher")
    persona = agent or default_persona
    chat_session = workspace.create_session(
        persona=persona,
        name=name or None,
        project=session_project,
        is_project_auto_detected=is_auto_detected,
    )
    session_id = chat_session.session_id

    # Set persona on the session if agent provided
    if agent:
        chat_session.persona = agent

    # Emit notification for session creation
    try:
        from .notification_emitter import notify_session_created

        notify_session_created(session_id, name or None)
    except Exception as e:
        logger.debug(f"Suppressed error in notify_session_created: {e}")

    return lines, session_id, chat_session


def _build_session_output(
    lines: list[str],
    session_id: str | None,
    chat_session,
    workspace,
    is_resumed: bool,
    project: str,
    name: str,
) -> list[str]:
    """Build the session header output lines with session ID and project info.

    Args:
        lines: Existing output lines (may already have content).
        session_id: The session ID to display.
        chat_session: The ChatSession object (may be None for no-ctx path).
        workspace: The WorkspaceState (may be None for no-ctx path).
        is_resumed: Whether this is a resumed session.
        project: The project name for display.
        name: Optional session name.

    Returns:
        The lines list (modified in place and returned for convenience).
    """
    if workspace is None or chat_session is None:
        # No-ctx fallback path: lines already populated, nothing more to add
        return lines

    # Add session ID and total session count to output
    total_sessions = workspace.session_count()
    session_name_info = (
        f" - *{name or chat_session.name}*" if (name or chat_session.name) else ""
    )

    # Get project info for display
    session_project = chat_session.project or workspace.project or "default"
    project_source = (
        "(auto-detected)" if chat_session.is_project_auto_detected else "(explicit)"
    )

    if is_resumed:
        session_line = (
            f"**Session ID:** `{session_id}`{session_name_info}"
            f" *(1 of {total_sessions} sessions in this workspace)*\n"
        )
        lines[:] = [
            "# \U0001f504 Session Resumed\n",
            session_line,
            f"**Project:** {session_project} {project_source}\n",
            f"**Persona:** {chat_session.persona}\n",
        ]
        if chat_session.issue_key:
            lines.append(f"**Active Issue:** {chat_session.issue_key}\n")
        if chat_session.branch:
            lines.append(f"**Branch:** {chat_session.branch}\n")
        lines.append("")
    else:
        session_line = (
            f"**Session ID:** `{session_id}`{session_name_info}"
            f" *(1 of {total_sessions} sessions in this workspace)*\n"
        )
        lines.insert(1, session_line)
        lines.insert(2, f"**Project:** {session_project} {project_source}\n")
        lines.insert(
            3,
            "\u26a0\ufe0f **SAVE THIS SESSION ID**"
            ' - Pass it to `session_info(session_id="...")`'
            " to track YOUR session.\n",
        )

    return lines


async def _session_start_impl(  # noqa: C901
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

    Orchestrates three helpers:
    - _resume_session: handles resuming an existing session
    - _create_new_session: handles creating a new session
    - _build_session_output: builds the header output lines
    """
    # Track session start in stats
    from tool_modules.aa_workflow.src.agent_stats import start_session

    start_session()

    is_resumed = False
    session_id = None
    chat_session = None
    workspace = None

    # Use workspace-aware context if ctx is available
    if ctx:
        from server.workspace_state import WorkspaceRegistry

        # Get workspace state
        workspace = await WorkspaceRegistry.get_for_ctx(ctx)

        # Check if we're resuming an existing session
        if resume_session_id:
            lines, session_id, chat_session, is_resumed = await _resume_session(
                workspace, resume_session_id, agent, project, name
            )

        if not is_resumed:
            new_lines, session_id, chat_session = await _create_new_session(
                workspace, agent, project, name
            )
            # If resume failed (session not found), prepend the warning lines
            if resume_session_id and not is_resumed:
                # lines already has the "Session Not Found" warning
                lines.extend(new_lines)
            else:
                lines = new_lines

        # Use the session's project (not workspace's) for the rest of the function
        project = chat_session.project

        # Load chat context using async version
        chat_project = await _load_chat_context_async(ctx, lines)

        # Build session header output
        _build_session_output(
            lines, session_id, chat_session, workspace, is_resumed, project, name
        )
    else:
        # Fallback to sync version for backward compatibility (no ctx available)
        lines = ["# \U0001f680 Session Started\n"]

        # Detect project from MCP roots if not explicitly provided
        detected_from_roots = None
        if not project:
            detected_from_roots = (
                await _detect_project_from_mcp_roots(ctx) if ctx else None
            )
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
    lines.append("## \u26a1 Quick Skills\n")
    lines.append("Run with `skill_run(name, inputs)`:\n")
    lines.append("- **start_work** - Begin Jira issue (creates branch, updates status)")
    lines.append("- **create_mr** - Create MR with proper formatting")
    lines.append("- **investigate_alert** - Systematic alert investigation")
    lines.append("- **memory_view** - View/manage persistent memory")
    lines.append("- **coffee** - Morning briefing (calendar, email, PRs)")
    lines.append("- **beer** - End of day wrap-up")
    lines.append("")

    # Show tool usage guidance
    lines.append("## \U0001f6e0\ufe0f Tool Usage\n")
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

    # Bootstrap context: Query memory abstraction for intent classification and suggested persona
    bootstrap_context = await _get_bootstrap_context(detected_project, name)
    if bootstrap_context:
        lines.append("## \U0001f3af Bootstrap Context\n")

        # Show intent classification
        intent = bootstrap_context.get("intent", {})
        if intent:
            intent_name = intent.get("intent", "general")
            confidence = intent.get("confidence", 0)
            confidence_pct = int(confidence * 100)
            lines.append(
                f"**Detected Intent:** {intent_name} ({confidence_pct}% confidence)"
            )

        # Show suggested persona with auto-load logic
        suggested_persona = bootstrap_context.get("suggested_persona")
        current_persona = (
            chat_session.persona if chat_session else (agent or "researcher")
        )

        if suggested_persona and suggested_persona != current_persona:
            confidence = bootstrap_context.get("persona_confidence", 0)
            if confidence >= 0.8:
                # Auto-load the suggested persona
                lines.append(
                    f"**Auto-loading Persona:** {suggested_persona} (confidence: {int(confidence * 100)}%)"
                )
                try:
                    from server.persona_loader import get_loader

                    loader = get_loader()
                    if loader:
                        await loader.switch_persona(suggested_persona)
                        if chat_session:
                            chat_session.persona = suggested_persona
                        lines.append(
                            f"  \u2705 Switched from {current_persona} to {suggested_persona}"
                        )
                except Exception as e:
                    lines.append(f"  \u26a0\ufe0f Failed to auto-load: {e}")
            else:
                conf_pct = int(confidence * 100)
                lines.append(
                    f"**Suggested Persona:** {suggested_persona}"
                    f" (confidence: {conf_pct}% - below auto-load threshold)"
                )

        # Show current work summary
        current_work = bootstrap_context.get("current_work", {})
        if current_work:
            active_issues = current_work.get("active_issues", [])
            if active_issues:
                lines.append(f"**Active Issues:** {', '.join(active_issues[:3])}")

        # Show recommended next actions
        actions = bootstrap_context.get("recommended_actions", [])
        if actions:
            lines.append("**Recommended Actions:**")
            for action in actions[:3]:
                lines.append(f"  - {action}")

        # Show suggested skills for direct execution
        suggested_skills = bootstrap_context.get("suggested_skills", [])
        if suggested_skills:
            skill_list_str = ", ".join(f"`{s}`" for s in suggested_skills)
            lines.append(f"**Suggested Skills:** {skill_list_str}")

        # Show related Slack discussions if any
        related_slack = bootstrap_context.get("related_slack", [])
        if related_slack:
            lines.append("")
            lines.append("**Related Slack Discussions:**")
            for slack_item in related_slack[:3]:
                channel = slack_item.get("channel", "unknown")
                summary = slack_item.get("summary", "")[:80]
                relevance = int(slack_item.get("relevance", 0) * 100)
                lines.append(f"  - #{channel}: {summary}... ({relevance}% relevant)")

        # Show related code context if any
        related_code = bootstrap_context.get("related_code", [])
        if related_code:
            lines.append("")
            lines.append("**Related Code:**")
            for code_item in related_code[:3]:
                file_path = code_item.get("file", "unknown")
                # Shorten path for display
                if "/" in file_path:
                    file_path = "/".join(file_path.split("/")[-3:])
                summary = code_item.get("summary", "")[:60]
                relevance = int(code_item.get("relevance", 0) * 100)
                lines.append(f"  - `{file_path}`: {summary}... ({relevance}%)")

        # Show which sources were queried
        sources_queried = bootstrap_context.get("sources_queried", [])
        if sources_queried:
            lines.append("")
            lines.append(f"*Sources queried: {', '.join(sources_queried)}*")

        lines.append("")

    # Log session start (if function provided)
    if memory_session_log_fn:
        project_info = f", Project: {detected_project}" if detected_project else ""
        await memory_session_log_fn(
            "Session started", f"Agent: {agent or 'none'}{project_info}"
        )

    # Export workspace state for VS Code extension
    try:
        from tool_modules.aa_workflow.src.workspace_exporter import (
            export_workspace_state_async,
        )

        logger.info("session_start: About to export workspace state")
        result = await export_workspace_state_async(ctx)
        logger.info(f"session_start: Export result: {result}")
    except Exception as e:
        logger.warning(f"Failed to export workspace state: {e}")
        import traceback

        logger.warning(f"Traceback: {traceback.format_exc()}")

    return [TextContent(type="text", text="\n".join(lines))]


def register_session_tools(  # noqa: C901
    server: "FastMCP", memory_session_log_fn=None
) -> int:
    """Register session tools with the MCP server.

    Args:
        server: The FastMCP server instance
        memory_session_log_fn: Optional function to log session actions
    """
    from fastmcp import Context

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
            for attr in [
                "request_id",
                "id",
                "session_id",
                "chat_id",
                "conversation_id",
            ]:
                if hasattr(ctx, attr):
                    lines.append(f"**ctx.{attr}:** `{getattr(ctx, attr)}`")

            session = ctx.session
            lines.append("\n## Session Object\n")
            lines.append(f"**Type:** `{type(session).__name__}`")
            session_attrs = [a for a in dir(session) if not a.startswith("_")]
            lines.append(f"**Attributes:** `{', '.join(session_attrs)}`")

            # Check for any ID-like attributes on session
            for attr in [
                "id",
                "session_id",
                "request_id",
                "client_id",
                "conversation_id",
                "chat_id",
            ]:
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
                    lines.append(
                        f"**Client:** `{params.clientInfo.name}` v`{params.clientInfo.version}`"
                    )
                    # Check for any ID on clientInfo
                    client_attrs = [
                        a for a in dir(params.clientInfo) if not a.startswith("_")
                    ]
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
            methods = [
                m
                for m in dir(session)
                if callable(getattr(session, m, None)) and not m.startswith("_")
            ]
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
                        except Exception as e:
                            logger.debug(
                                f"Suppressed error in debug_mcp_roots meta attr: {e}"
                            )
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
        ctx: Context,
        agent: str = "",
        project: str = "",
        name: str = "",
        session_id: str = "",
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
        return await _session_start_impl(
            ctx, agent, project, name, memory_session_log_fn, session_id
        )

    @auto_heal()
    @registry.tool()
    async def session_set_project(
        ctx: Context, project: str, session_id: str = ""
    ) -> list[TextContent]:
        """Set the project for the current or specified session.

        CRITICAL: Claude should call this when it determines which project the user is working on.
        The workspace may be redhat-ai-workflow, but the user might be working on a different project.

        Project detection signals (in priority order):
        1. Repository name mentioned (automation-analytics-backend, pdf-generator, app-interface)
        2. GitLab project mentioned (automation-analytics/automation-analytics-backend)
        3. File paths mentioned (/home/user/src/automation-analytics-backend/...)
        4. Issue key context - if discussing AAP issues, likely automation-analytics-backend

        Args:
            project: Project name from config.json (e.g., "automation-analytics-backend", "pdf-generator")
            session_id: Optional session ID. If empty, uses active session.

        Returns:
            Confirmation of project update with session details.

        Examples:
            session_set_project(project="automation-analytics-backend")
            session_set_project(project="pdf-generator", session_id="abc123")
        """
        from server.utils import load_config
        from server.workspace_state import WorkspaceRegistry

        lines = []

        try:
            # Validate project exists in config
            config = load_config()
            repos = config.get("repositories", {})

            if project not in repos:
                available = ", ".join(repos.keys())
                return [
                    TextContent(
                        type="text",
                        text="# Invalid Project\n\n"
                        f"Project `{project}` not found in config.json.\n\n"
                        f"**Available projects:** {available}",
                    )
                ]

            # Get workspace state
            workspace = await WorkspaceRegistry.get_for_ctx(ctx)

            # Find the target session
            target_session_id = (
                session_id if session_id else workspace.active_session_id
            )

            if not target_session_id:
                return [
                    TextContent(
                        type="text",
                        text="# No Active Session\n\n"
                        "No active session found. Call `session_start()` first or provide a session_id.",
                    )
                ]

            session = workspace.sessions.get(target_session_id)
            if not session:
                return [
                    TextContent(
                        type="text",
                        text="# Session Not Found\n\n"
                        f"Session `{target_session_id}` not found in workspace.",
                    )
                ]

            # Update the session's project
            old_project = session.project
            session.project = project
            session.is_project_auto_detected = (
                False  # Explicitly set, not auto-detected
            )
            session.touch()

            # Persist to disk
            WorkspaceRegistry.save_to_disk()

            # Build response
            lines.append("# Project Updated\n")
            lines.append(f"**Session:** `{target_session_id}`")
            if session.name:
                lines.append(f" ({session.name})")
            lines.append("\n")
            lines.append(f"**Project:** `{old_project}` -> `{project}`\n")

            # Show project details
            repo_config = repos[project]
            if repo_config.get("path"):
                lines.append(f"**Path:** `{repo_config['path']}`\n")
            if repo_config.get("gitlab"):
                lines.append(f"**GitLab:** `{repo_config['gitlab']}`\n")
            if repo_config.get("jira_project"):
                lines.append(f"**Jira Project:** `{repo_config['jira_project']}`\n")

            logger.info(
                f"Updated session {target_session_id} project: {old_project} -> {project}"
            )

            # Emit notification for toast
            try:
                from .notification_emitter import notify_session_updated

                notify_session_updated(
                    target_session_id, f"Project changed to {project}"
                )
            except Exception as e:
                logger.debug(f"Suppressed error in notify_session_updated: {e}")

            # Trigger session daemon to reload from disk so UI updates
            try:
                from services.base.dbus import get_client

                client = get_client("session")
                await client.connect()
                await client.call_method("refresh_now", [])
                await client.disconnect()
                logger.debug("Triggered session daemon refresh after project update")
            except Exception as e:
                logger.debug(f"Could not trigger session daemon refresh: {e}")

        except Exception as e:
            import traceback

            lines.append(f"# Error\n\n**Error:** {e}\n")
            lines.append(f"```\n{traceback.format_exc()}\n```")

        return [TextContent(type="text", text="\n".join(lines))]

    @registry.tool()
    async def jira_attach_session(
        ctx: Context,
        issue_key: str,
        session_id: str = "",
        include_transcript: bool = False,
    ) -> list[TextContent]:
        """Attach current session context to a Jira issue as a comment.

        Exports the AI session context (conversation summary, tool calls, code changes)
        and posts it as a formatted comment on the specified Jira issue. This allows
        team members to investigate what was discussed and done during the session.

        The comment includes:
        - Session metadata (ID, persona, project, duration)
        - Summary stats (message count, tool calls, code references)
        - Key actions taken (extracted from tool results)
        - Related issue keys mentioned in the conversation
        - Optionally: full conversation transcript (collapsible)

        Args:
            issue_key: The Jira issue key to attach context to (e.g., AAP-12345)
            session_id: Optional session ID. If empty, uses active session.
            include_transcript: Whether to include full conversation transcript (default: False).
                               The transcript is collapsible in Jira's UI.

        Returns:
            Confirmation of the comment being added with a preview.

        Examples:
            jira_attach_session(issue_key="AAP-12345")
            jira_attach_session(issue_key="AAP-12345", include_transcript=True)
            jira_attach_session(issue_key="AAP-12345", session_id="abc123")
        """
        from server.workspace_state import (
            WorkspaceRegistry,
            format_session_context_for_jira,
            get_cursor_chat_content,
        )

        lines = []

        try:
            # Validate issue key format
            import re

            if not re.match(r"^[A-Z]+-\d+$", issue_key.upper()):
                return [
                    TextContent(
                        type="text",
                        text="# Invalid Issue Key\n\n"
                        f"`{issue_key}` is not a valid Jira issue key.\n"
                        "Expected format: AAP-12345",
                    )
                ]

            issue_key = issue_key.upper()

            # Get workspace and session
            workspace = await WorkspaceRegistry.get_for_ctx(ctx)
            target_session_id = (
                session_id if session_id else workspace.active_session_id
            )

            if not target_session_id:
                return [
                    TextContent(
                        type="text",
                        text="# No Active Session\n\n"
                        "No active session found. Call `session_start()` first or provide a session_id.",
                    )
                ]

            session = workspace.sessions.get(target_session_id)
            if not session:
                return [
                    TextContent(
                        type="text",
                        text="# Session Not Found\n\n"
                        f"Session `{target_session_id}` not found.\n"
                        "Use `session_list()` to see available sessions.",
                    )
                ]

            # Extract chat content from Cursor DB
            lines.append("# Attaching Session Context to Jira\n")
            lines.append(
                f"**Issue:** [{issue_key}](https://issues.redhat.com/browse/{issue_key})"
            )
            lines.append(f"**Session:** `{target_session_id[:8]}...`\n")

            chat_content = get_cursor_chat_content(target_session_id, max_messages=100)

            if chat_content["message_count"] == 0:
                lines.append(
                    "⚠️ **Warning:** No conversation content found in Cursor DB for this session."
                )
                lines.append("The session may be new or the chat ID may not match.\n")

            # Format for Jira
            jira_comment = format_session_context_for_jira(
                chat_content=chat_content,
                session=session,
                include_transcript=include_transcript,
                max_transcript_chars=5000,
            )

            # Preview
            lines.append("## Comment Preview\n")
            lines.append("```")
            # Show truncated preview
            preview = jira_comment[:1500]
            if len(jira_comment) > 1500:
                preview += "\n... (truncated)"
            lines.append(preview)
            lines.append("```\n")

            # Post to Jira using the jira module
            try:
                # Import the jira add comment function
                from tool_modules.aa_jira.src.tools_basic import _jira_add_comment_impl

                result = await _jira_add_comment_impl(issue_key, jira_comment)

                if "❌" in result:
                    lines.append(f"## Result\n\n{result}")
                else:
                    lines.append(f"## ✅ Success\n\n{result}")
                    lines.append(
                        f"\n[View on Jira](https://issues.redhat.com/browse/{issue_key})"
                    )

                    # Log to session
                    try:
                        await memory_session_log_fn(
                            ctx,
                            f"Attached session context to {issue_key}",
                            f"Messages: {chat_content['message_count']}, "
                            f"Tool calls: {chat_content['summary']['tool_calls']}",
                        )
                    except Exception as e:
                        logger.debug(
                            f"Suppressed error in jira_attach_session logging: {e}"
                        )

            except ImportError as e:
                lines.append(f"## Error\n\n❌ Could not import Jira tools: {e}")
                lines.append(
                    "\nMake sure the `developer` or `devops` persona is loaded."
                )

        except Exception as e:
            import traceback

            lines.append(f"# Error\n\n**Error:** {e}\n")
            lines.append(f"```\n{traceback.format_exc()}\n```")

        return [TextContent(type="text", text="\n".join(lines))]

    @registry.tool()
    async def session_export_context(
        ctx: Context,
        session_id: str = "",
        format: str = "markdown",
    ) -> list[TextContent]:
        """Export session context as markdown or JSON.

        Extracts the full conversation context from the current session,
        including messages, tool calls, and metadata. Useful for:
        - Sharing session context with team members
        - Archiving session history
        - Debugging session issues

        Args:
            session_id: Optional session ID. If empty, uses active session.
            format: Output format - "markdown" (default) or "json"

        Returns:
            Formatted session context.

        Examples:
            session_export_context()
            session_export_context(format="json")
            session_export_context(session_id="abc123")
        """
        from server.workspace_state import WorkspaceRegistry, get_cursor_chat_content

        try:
            # Get workspace and session
            workspace = await WorkspaceRegistry.get_for_ctx(ctx)
            target_session_id = (
                session_id if session_id else workspace.active_session_id
            )

            if not target_session_id:
                return [
                    TextContent(
                        type="text",
                        text="# No Active Session\n\n"
                        "No active session found. Call `session_start()` first or provide a session_id.",
                    )
                ]

            session = workspace.sessions.get(target_session_id)
            if not session:
                return [
                    TextContent(
                        type="text",
                        text="# Session Not Found\n\n"
                        f"Session `{target_session_id}` not found.",
                    )
                ]

            # Extract chat content
            chat_content = get_cursor_chat_content(target_session_id, max_messages=200)

            if format.lower() == "json":
                # JSON format
                import json

                export_data = {
                    "session": {
                        "id": session.session_id,
                        "persona": session.persona,
                        "project": session.project,
                        "issue_key": session.issue_key,
                        "branch": session.branch,
                        "started_at": (
                            session.started_at.isoformat()
                            if session.started_at
                            else None
                        ),
                        "last_activity": (
                            session.last_activity.isoformat()
                            if session.last_activity
                            else None
                        ),
                        "tool_call_count": session.tool_call_count,
                    },
                    "chat": chat_content,
                }
                return [
                    TextContent(
                        type="text",
                        text=f"```json\n{json.dumps(export_data, indent=2, default=str)}\n```",
                    )
                ]

            # Markdown format
            lines = []
            lines.append("# Session Context Export\n")
            lines.append(f"**Session ID:** `{session.session_id}`")
            lines.append(f"**Persona:** {session.persona}")
            if session.project:
                lines.append(f"**Project:** {session.project}")
            if session.issue_key:
                lines.append(f"**Issue:** {session.issue_key}")
            if session.branch:
                lines.append(f"**Branch:** `{session.branch}`")
            if session.started_at:
                lines.append(
                    f"**Started:** {session.started_at.strftime('%Y-%m-%d %H:%M')}"
                )
            lines.append("")

            # Summary
            summary = chat_content.get("summary", {})
            lines.append("## Summary\n")
            lines.append(f"- **Total Messages:** {chat_content['message_count']}")
            lines.append(f"- **User Messages:** {summary.get('user_messages', 0)}")
            lines.append(
                f"- **Assistant Messages:** {summary.get('assistant_messages', 0)}"
            )
            lines.append(f"- **Tool Calls:** {summary.get('tool_calls', 0)}")
            lines.append(f"- **Code References:** {summary.get('code_changes', 0)}")

            issue_keys = summary.get("issue_keys", [])
            if issue_keys:
                lines.append(f"- **Related Issues:** {', '.join(issue_keys)}")
            lines.append("")

            # Conversation
            messages = chat_content.get("messages", [])
            if messages:
                lines.append("## Conversation\n")
                for msg in messages[:50]:  # Limit display
                    role = msg.get("type", "unknown")
                    text = msg.get("text", "")[:500]
                    timestamp = (
                        msg.get("timestamp", "")[:16] if msg.get("timestamp") else ""
                    )

                    role_emoji = (
                        "👤" if role == "user" else "🤖" if role == "assistant" else "⚙️"
                    )
                    lines.append(
                        f"### {role_emoji} {role.title()} {f'({timestamp})' if timestamp else ''}\n"
                    )
                    lines.append(text)
                    lines.append("")

                if len(messages) > 50:
                    lines.append(f"*... and {len(messages) - 50} more messages*")

            return [TextContent(type="text", text="\n".join(lines))]

        except Exception as e:
            import traceback

            return [
                TextContent(
                    type="text",
                    text=f"# Error\n\n**Error:** {e}\n```\n{traceback.format_exc()}\n```",
                )
            ]

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
