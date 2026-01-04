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

# Support both package import and direct loading
try:
    from .constants import AGENTS_DIR, MEMORY_DIR
except ImportError:
    SERVERS_DIR = Path(__file__).parent.parent.parent
    PROJECT_DIR = SERVERS_DIR.parent
    AGENTS_DIR = PROJECT_DIR / "agents"
    MEMORY_DIR = PROJECT_DIR / "memory"

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register_session_tools(server: "FastMCP", memory_session_log_fn=None) -> int:
    """Register session tools with the MCP server.

    Args:
        server: The FastMCP server instance
        memory_session_log_fn: Optional function to log session actions
    """
    tool_count = 0

    @server.tool()
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

        # Load agent if specified
        if agent:
            agent_file = AGENTS_DIR / f"{agent}.md"
            if agent_file.exists():
                lines.append(f"## 🤖 Agent: {agent}\n")
                lines.append("*Loading agent persona...*\n")
                lines.append("---\n")
                lines.append(agent_file.read_text())
            else:
                lines.append(f"*Agent '{agent}' not found. " "Available: devops, developer, incident, release*\n")
        else:
            lines.append("## 💡 Available Agents\n")
            lines.append("Load one with `agent_load(name)` or `session_start(agent='name')`:\n")
            lines.append("- **devops** - Infrastructure, monitoring, deployments")
            lines.append("- **developer** - Coding, PRs, code review")
            lines.append("- **incident** - Production issues, triage")
            lines.append("- **release** - Shipping, coordination")
            lines.append("")

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

        # Log session start (if function provided)
        if memory_session_log_fn:
            await memory_session_log_fn("Session started", f"Agent: {agent or 'none'}")

        return [TextContent(type="text", text="\n".join(lines))]

    tool_count += 1

    return tool_count


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
