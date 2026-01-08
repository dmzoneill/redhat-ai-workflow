"""Session Tools - Bootstrap and manage work sessions.

Provides tools for:
- session_start: Initialize a new work session with context
- Prompts for guided workflows (debug, review)
"""

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from mcp.types import TextContent

from server.tool_registry import ToolRegistry

# Support both package import and direct loading
try:
    from .constants import MEMORY_DIR, PERSONAS_DIR
except ImportError:
    TOOL_MODULES_DIR = Path(__file__).parent.parent.parent
    PROJECT_DIR = TOOL_MODULES_DIR.parent
    PERSONAS_DIR = PROJECT_DIR / "personas"
    MEMORY_DIR = PROJECT_DIR / "memory"

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


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
        lines = ["# 🚀 Session Started\n"]

        # Load current work
        current_work_file = MEMORY_DIR / "state" / "current_work.yaml"
        if current_work_file.exists():
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
                            lines.append(f"- **{issue.get('key', '?')}**: " f"{issue.get('summary', 'No summary')}")
                            lines.append(
                                f"  Status: {issue.get('status', '?')} | " f"Branch: `{issue.get('branch', '?')}`"
                            )
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

        # Load environment status
        env_file = MEMORY_DIR / "state" / "environments.yaml"
        if env_file.exists():
            try:
                with open(env_file) as f:
                    env_data = yaml.safe_load(f) or {}

                envs = env_data.get("environments", {})
                if envs:
                    # Check if any environment has issues
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

        # Load today's session history
        today = datetime.now().strftime("%Y-%m-%d")
        session_file = MEMORY_DIR / "sessions" / f"{today}.yaml"
        if session_file.exists():
            try:
                with open(session_file) as f:
                    session = yaml.safe_load(f) or {}
                entries = session.get("entries", [])
                if entries:
                    lines.append("## 📝 Today's Session History\n")
                    for entry in entries[-5:]:  # Last 5 entries
                        lines.append(f"- [{entry.get('time', '?')}] {entry.get('action', '?')}")
                    lines.append("")
            except Exception:
                pass

        # Detect currently loaded persona from persona_loader if available
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

        # Load agent if specified
        if agent:
            agent_file = PERSONAS_DIR / f"{agent}.md"
            if agent_file.exists():
                lines.append(f"## 🤖 Agent: {agent}\n")
                lines.append("*Loading agent persona...*\n")
                lines.append("---\n")
                lines.append(agent_file.read_text())
            else:
                lines.append(f"*Agent '{agent}' not found. " "Available: devops, developer, incident, release*\n")
        elif current_persona:
            # Show currently active persona
            lines.append(f"## 🤖 Active Persona: {current_persona}\n")
            if loaded_modules:
                lines.append(f"**Loaded modules:** {', '.join(sorted(loaded_modules))}\n")
            lines.append("Use `persona_load(name)` to switch personas.\n")
        else:
            # Check if developer tools are loaded (default)
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

        # Load learned patterns summary (for context)
        patterns_file = MEMORY_DIR / "learned" / "patterns.yaml"
        if patterns_file.exists():
            try:
                with open(patterns_file) as f:
                    patterns = yaml.safe_load(f) or {}

                # Count patterns by category
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
            await memory_session_log_fn("Session started", f"Agent: {agent or 'none'}")

        return [TextContent(type="text", text="\n".join(lines))]

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
