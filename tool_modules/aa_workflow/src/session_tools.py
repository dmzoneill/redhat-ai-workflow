"""Session Tools - Bootstrap and manage work sessions.

Provides tools for:
- session_start: Initialize a new work session with context
- Prompts for guided workflows (debug, review)
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
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


# ==================== TOOL IMPLEMENTATIONS ====================


def _load_current_work(lines: list[str]) -> None:
    """Load and append current work status."""
    current_work_file = MEMORY_DIR / "state" / "current_work.yaml"
    if not current_work_file.exists():
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
            lines.append("*No active work tracked. Use `start_work` skill to begin.*\n")

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


async def _session_start_impl(agent: str = "", memory_session_log_fn=None) -> list[TextContent]:
    """Implementation of session_start tool."""
    # Track session start in stats
    from tool_modules.aa_workflow.src.agent_stats import start_session

    start_session()

    lines = ["# 🚀 Session Started\n"]

    # Load all context sections using helper functions
    _load_current_work(lines)
    _load_environment_status(lines)
    _load_session_history(lines)
    _load_persona_info(lines, agent)
    _load_learned_patterns(lines)

    # Load project-specific knowledge (auto-scans if needed)
    detected_project = _load_project_knowledge(lines, agent)

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

    return [TextContent(type="text", text="\n".join(lines))]


def register_session_tools(server: "FastMCP", memory_session_log_fn=None) -> int:
    """Register session tools with the MCP server.

    Args:
        server: The FastMCP server instance
        memory_session_log_fn: Optional function to log session actions
    """
    registry = ToolRegistry(server)

    @registry.tool()
    async def session_start(agent: str = "") -> list[TextContent]:
        """
        Initialize a new session with full context.

        This is the FIRST tool to call when starting work. It loads:
        - Current work state (active issues, branches, MRs)
        - Today's session history (if resuming)
        - Optionally loads an agent persona

        Args:
            agent: Optional agent to load ("devops", "developer", "incident", "release")

        Returns:
            Complete session context to get started.
        """
        return await _session_start_impl(agent, memory_session_log_fn)

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
