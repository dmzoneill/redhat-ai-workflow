#!/usr/bin/env python3
"""
Claude Agent - The AI Brain for Slack Bot

This module provides a Claude-powered agent that:
1. Receives messages/requests
2. Uses Claude to understand intent and decide actions
3. Calls tools (Jira, GitLab, Git, K8s, etc.)
4. Returns intelligent responses

This is the same pattern as Cursor's Claude agent - Claude decides what to do
and calls MCP tools to execute actions.
"""

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, cast

# Add parent to path for config imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Runtime imports with fallbacks
try:
    import anthropic
    from anthropic import AnthropicVertex

    ANTHROPIC_AVAILABLE = True
    VERTEX_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    VERTEX_AVAILABLE = False
    anthropic = None
    AnthropicVertex = None

try:
    from scripts.common.context_resolver import ContextResolver, ResolvedContext

    RESOLVER_AVAILABLE = True
except ImportError:
    RESOLVER_AVAILABLE = False
    ContextResolver = None
    ResolvedContext = None

# Import context injector for knowledge gathering
try:
    from scripts.context_injector import ContextInjector, GatheredContext

    CONTEXT_INJECTOR_AVAILABLE = True
except ImportError:
    CONTEXT_INJECTOR_AVAILABLE = False
    ContextInjector = None
    GatheredContext = None

try:
    from scripts.skill_hooks import SkillHooks

    HOOKS_AVAILABLE = True
except ImportError:
    HOOKS_AVAILABLE = False
    SkillHooks = None

# Import known issues checker for learning loop
try:
    PROJECT_ROOT = Path(__file__).parent.parent
    sys.path.insert(0, str(PROJECT_ROOT))
    from server.debuggable import _check_known_issues_sync, _format_known_issues

    KNOWN_ISSUES_AVAILABLE = True
except ImportError:
    KNOWN_ISSUES_AVAILABLE = False

    def _check_known_issues_sync(tool_name="", error_text=""):
        return []

    def _format_known_issues(matches):
        return ""


# Import tool filtering for NPU-powered pre-filtering
try:
    from tool_modules.aa_ollama.src.skill_discovery import detect_skill
    from tool_modules.aa_ollama.src.tool_filter import filter_tools_detailed, get_filter

    TOOL_FILTER_AVAILABLE = True
except ImportError:
    TOOL_FILTER_AVAILABLE = False
    filter_tools_detailed = None
    detect_skill = None
    get_filter = None


logger = logging.getLogger(__name__)

# Skill executor - use the actual skill engine from aa_workflow
try:
    # Add tool_modules to path for skill_engine
    PROJECT_ROOT = Path(__file__).parent.parent
    sys.path.insert(0, str(PROJECT_ROOT / "tool_modules" / "aa_workflow" / "src"))
    sys.path.insert(0, str(PROJECT_ROOT))

    import yaml as skill_yaml
    from skill_engine import SkillExecutor, SkillExecutorConfig

    SKILL_EXECUTOR_AVAILABLE = True
    SKILLS_DIR = Path(__file__).parent.parent / "skills"
except ImportError as e:
    SKILL_EXECUTOR_AVAILABLE = False
    SkillExecutor = None
    skill_yaml = None
    SKILLS_DIR = None
    logger.debug(f"Skill executor not available: {e}")

PROJECT_ROOT = Path(__file__).parent.parent


def _get_available_skills_description() -> str:
    """Dynamically build skill list from skills/ directory."""
    if not SKILLS_DIR or not SKILLS_DIR.exists():
        return "Skills directory not available."

    skills = []
    for f in sorted(SKILLS_DIR.glob("*.yaml")):
        try:
            with open(f) as fp:
                data = skill_yaml.safe_load(fp)
            name = data.get("name", f.stem)
            desc = data.get("description", "").split("\n")[0][
                :60
            ]  # First line, truncated
            inputs = [i["name"] for i in data.get("inputs", []) if i.get("required")]
            input_str = f" (inputs: {', '.join(inputs)})" if inputs else ""
            skills.append(f"- {name}: {desc}{input_str}")
        except Exception as e:
            logger.debug(f"Suppressed error in _build_skill_list: {e}")
            skills.append(f"- {f.stem}: (error loading)")

    if not skills:
        return "No skills found."

    # Return top 20 most useful skills to keep description manageable
    # Prioritize commonly used ones
    priority_skills = [
        "test_mr_ephemeral",
        "start_work",
        "create_mr",
        "create_jira_issue",
        "review_pr",
        "close_issue",
        "coffee",
        "beer",
        "standup_summary",
        "investigate_slack_alert",
        "debug_prod",
        "investigate_alert",
    ]

    sorted_skills = []
    other_skills = []
    for s in skills:
        skill_name = s.split(":")[0].replace("- ", "")
        if skill_name in priority_skills:
            sorted_skills.append(s)
        else:
            other_skills.append(s)

    # Show priority skills first, then note there are more
    result = sorted_skills[:15]
    remaining = len(other_skills) + len(sorted_skills) - 15
    if remaining > 0:
        result.append(f"- ... and {remaining} more skills available")

    return "\n".join(result)


@dataclass
class ToolDefinition:
    """Definition of a tool Claude can call."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Optional[Callable[..., Any]] = field(default=None)


@dataclass
class ToolCall:
    """A tool call requested by Claude."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    """Result of executing a tool."""

    tool_use_id: str
    content: str
    is_error: bool = field(default=False)


class ToolRegistry:
    """
    Registry of tools available to Claude.

    Maps tool names to their definitions and handlers.
    """

    def __init__(self) -> None:
        self.tools: dict[str, ToolDefinition] = {}
        self._register_builtin_tools()

    def _register_builtin_tools(self) -> None:
        """Register built-in tools that map to our MCP tools."""

        # Jira tools
        self.register(
            ToolDefinition(
                name="jira_view",
                description=(
                    "View a Jira issue by key (e.g., AAP-12345). "
                    "Returns issue details including summary, status, assignee, and description."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "issue_key": {
                            "type": "string",
                            "description": "Jira issue key (e.g., AAP-12345)",
                        }
                    },
                    "required": ["issue_key"],
                },
            )
        )

        self.register(
            ToolDefinition(
                name="jira_search",
                description="Search Jira issues using JQL query.",
                parameters={
                    "type": "object",
                    "properties": {
                        "jql": {"type": "string", "description": "JQL query string"},
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum results to return",
                            "default": 10,
                        },
                    },
                    "required": ["jql"],
                },
            )
        )

        self.register(
            ToolDefinition(
                name="jira_comment",
                description="Add a comment to a Jira issue.",
                parameters={
                    "type": "object",
                    "properties": {
                        "issue_key": {
                            "type": "string",
                            "description": "Jira issue key",
                        },
                        "comment": {
                            "type": "string",
                            "description": "Comment text to add",
                        },
                    },
                    "required": ["issue_key", "comment"],
                },
            )
        )

        # GitLab tools - simplified, full functionality in aa_gitlab MCP server
        self.register(
            ToolDefinition(
                name="gitlab_mr_view",
                description="View a GitLab Merge Request. Pass the full URL for best results.",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": (
                                "Full GitLab URL "
                                "(e.g., https://gitlab.cee.redhat.com/org/repo/-/merge_requests/1449)"
                            ),
                        },
                    },
                    "required": ["url"],
                },
            )
        )

        self.register(
            ToolDefinition(
                name="gitlab_mr_list",
                description="List open Merge Requests for a project.",
                parameters={
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Repository path like 'automation-analytics/automation-analytics-backend'",
                        },
                        "state": {
                            "type": "string",
                            "description": "MR state: opened, merged, closed, all",
                            "default": "opened",
                        },
                    },
                    "required": ["project"],
                },
            )
        )

        self.register(
            ToolDefinition(
                name="gitlab_pipeline_status",
                description="Get CI/CD pipeline status for a project.",
                parameters={
                    "type": "object",
                    "properties": {
                        "mr_id": {"type": "string", "description": "Merge Request ID"}
                    },
                    "required": ["mr_id"],
                },
            )
        )

        self.register(
            ToolDefinition(
                name="gitlab_mr_approve",
                description="Approve a merge request. Sends notification to author.",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "Full GitLab URL or MR ID",
                        },
                        "author": {
                            "type": "string",
                            "description": "GitLab username of MR author (for notification)",
                        },
                    },
                    "required": ["url"],
                },
            )
        )

        self.register(
            ToolDefinition(
                name="gitlab_mr_comment",
                description="Leave a comment on a merge request. Sends notification to author.",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "Full GitLab URL or MR ID",
                        },
                        "comment": {
                            "type": "string",
                            "description": "Comment text to post",
                        },
                        "author": {
                            "type": "string",
                            "description": "GitLab username of MR author (for notification)",
                        },
                    },
                    "required": ["url", "comment"],
                },
            )
        )

        self.register(
            ToolDefinition(
                name="gitlab_mr_merge",
                description="Merge a merge request. Sends notification to team channel.",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "Full GitLab URL or MR ID",
                        },
                        "squash": {
                            "type": "boolean",
                            "description": "Squash commits on merge",
                            "default": False,
                        },
                        "author": {
                            "type": "string",
                            "description": "GitLab username of MR author (for notification)",
                        },
                    },
                    "required": ["url"],
                },
            )
        )

        # Git tools
        self.register(
            ToolDefinition(
                name="git_status",
                description="Get git status of a repository.",
                parameters={
                    "type": "object",
                    "properties": {
                        "repo_path": {
                            "type": "string",
                            "description": "Path to git repository",
                        }
                    },
                    "required": [],
                },
            )
        )

        self.register(
            ToolDefinition(
                name="git_log",
                description="Get recent git commits.",
                parameters={
                    "type": "object",
                    "properties": {
                        "repo_path": {
                            "type": "string",
                            "description": "Path to git repository",
                        },
                        "count": {
                            "type": "integer",
                            "description": "Number of commits to show",
                            "default": 10,
                        },
                    },
                    "required": [],
                },
            )
        )

        # Kubernetes tools
        self.register(
            ToolDefinition(
                name="k8s_get_pods",
                description="List pods in a Kubernetes namespace.",
                parameters={
                    "type": "object",
                    "properties": {
                        "namespace": {
                            "type": "string",
                            "description": "Kubernetes namespace",
                        }
                    },
                    "required": ["namespace"],
                },
            )
        )

        self.register(
            ToolDefinition(
                name="k8s_get_events",
                description="Get recent events in a Kubernetes namespace.",
                parameters={
                    "type": "object",
                    "properties": {
                        "namespace": {
                            "type": "string",
                            "description": "Kubernetes namespace",
                        }
                    },
                    "required": ["namespace"],
                },
            )
        )

        self.register(
            ToolDefinition(
                name="k8s_logs",
                description="Get logs from a Kubernetes pod.",
                parameters={
                    "type": "object",
                    "properties": {
                        "namespace": {
                            "type": "string",
                            "description": "Kubernetes namespace",
                        },
                        "pod": {"type": "string", "description": "Pod name"},
                        "tail": {
                            "type": "integer",
                            "description": "Number of lines to tail",
                            "default": 100,
                        },
                    },
                    "required": ["namespace", "pod"],
                },
            )
        )

        # Bonfire tools - ephemeral namespace management
        # ALWAYS use these tools instead of generating shell commands!
        self.register(
            ToolDefinition(
                name="bonfire_namespace_reserve",
                description="""Reserve an ephemeral namespace for testing.
ALWAYS use this tool - NEVER output bonfire commands as text.
This tool handles KUBECONFIG automatically (uses ~/.kube/config.e).""",
                parameters={
                    "type": "object",
                    "properties": {
                        "duration": {
                            "type": "string",
                            "description": "Reservation duration (e.g., '1h', '2h', '4h')",
                            "default": "2h",
                        },
                    },
                    "required": [],
                },
            )
        )

        self.register(
            ToolDefinition(
                name="bonfire_namespace_list",
                description="""List your ephemeral namespace reservations.
ALWAYS use this tool - NEVER output bonfire commands as text.
Handles KUBECONFIG automatically.""",
                parameters={
                    "type": "object",
                    "properties": {
                        "mine_only": {
                            "type": "boolean",
                            "description": "Only show namespaces owned by current user",
                            "default": True,
                        },
                    },
                    "required": [],
                },
            )
        )

        self.register(
            ToolDefinition(
                name="bonfire_namespace_release",
                description="""Release an ephemeral namespace. Only releases YOUR namespaces.
ALWAYS use this tool - NEVER output bonfire commands as text.
Handles KUBECONFIG automatically.""",
                parameters={
                    "type": "object",
                    "properties": {
                        "namespace": {
                            "type": "string",
                            "description": "Namespace name (e.g., 'ephemeral-abc123')",
                        },
                    },
                    "required": ["namespace"],
                },
            )
        )

        self.register(
            ToolDefinition(
                name="bonfire_deploy_aa",
                description="""Deploy Automation Analytics to ephemeral namespace.
ALWAYS use this tool - NEVER construct bonfire commands manually or output them as text.
Handles KUBECONFIG automatically. Checks image exists before deploying.

REQUIRED:
- template_ref: 40-char git SHA
- image_tag: 64-char sha256 digest from Quay (use quay_get_tag to get this)
- billing: true for billing ClowdApp, false for main""",
                parameters={
                    "type": "object",
                    "properties": {
                        "namespace": {
                            "type": "string",
                            "description": "Ephemeral namespace (e.g., 'ephemeral-abc123')",
                        },
                        "template_ref": {
                            "type": "string",
                            "description": "FULL 40-char git commit SHA",
                        },
                        "image_tag": {
                            "type": "string",
                            "description": "64-char sha256 digest from Quay (NOT git SHA)",
                        },
                        "billing": {
                            "type": "boolean",
                            "description": "True for billing ClowdApp, False for main",
                            "default": False,
                        },
                    },
                    "required": ["namespace", "template_ref", "image_tag"],
                },
            )
        )

        self.register(
            ToolDefinition(
                name="quay_get_tag",
                description="Check if an image exists in Quay and get its sha256 digest.",
                parameters={
                    "type": "object",
                    "properties": {
                        "repository": {
                            "type": "string",
                            "description": (
                                "Repository path "
                                "(e.g., 'aap-aa-tenant/aap-aa-main/automation-analytics-backend-main')"
                            ),
                        },
                        "tag": {
                            "type": "string",
                            "description": "Image tag (use FULL 40-char git SHA)",
                        },
                    },
                    "required": ["repository", "tag"],
                },
            )
        )

        # Skill tools
        # Build dynamic skill list
        skills_list = _get_available_skills_description()

        self.register(
            ToolDefinition(
                name="skill_run",
                description=f"""Run a workflow skill.

Available skills:
{skills_list}

Example usage:
  skill_run("test_mr_ephemeral", {{"mr_id": 1459}})
  skill_run("create_jira_issue", {{"summary": "Bug title", "issue_type": "Bug"}})
  skill_run("start_work", {{"issue_key": "AAP-12345"}})""",
                parameters={
                    "type": "object",
                    "properties": {
                        "skill_name": {
                            "type": "string",
                            "description": "Name of the skill to run",
                        },
                        "inputs": {
                            "type": "object",
                            "description": "Inputs for the skill",
                        },
                    },
                    "required": ["skill_name"],
                },
            )
        )

        # Memory tools - for tracking work context
        self.register(
            ToolDefinition(
                name="memory_read",
                description="""Read from persistent memory.

Memory stores context that persists across sessions:
- state/current_work - Active issues, branches, MRs
- state/environments - Stage/prod health status
- learned/patterns - Error patterns and solutions
- learned/runbooks - Procedures that worked

Leave key empty to list available memory files.""",
                parameters={
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Memory key (e.g., 'state/current_work', 'learned/patterns')",
                        }
                    },
                    "required": [],
                },
            )
        )

        self.register(
            ToolDefinition(
                name="memory_append",
                description="""Add an item to a list in memory.

Useful for tracking:
- active_issues: Issues you're working on
- open_mrs: MRs awaiting review
- follow_ups: Tasks to remember""",
                parameters={
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Memory file (e.g., 'state/current_work')",
                        },
                        "list_path": {
                            "type": "string",
                            "description": "Path to list (e.g., 'active_issues')",
                        },
                        "item": {
                            "type": "string",
                            "description": "Item to add (as YAML/JSON string)",
                        },
                    },
                    "required": ["key", "list_path", "item"],
                },
            )
        )

        self.register(
            ToolDefinition(
                name="memory_session_log",
                description="Log an action to today's session log for handoff to future sessions.",
                parameters={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "What was done"},
                        "details": {
                            "type": "string",
                            "description": "Additional details (optional)",
                        },
                    },
                    "required": ["action"],
                },
            )
        )

        # Slack tools
        self.register(
            ToolDefinition(
                name="slack_send_message",
                description="""Send a message to a Slack channel or thread.
ALWAYS use this tool to reply to alerts or conversations.
Use thread_ts to reply in a thread (REQUIRED for alert replies).""",
                parameters={
                    "type": "object",
                    "properties": {
                        "channel_id": {
                            "type": "string",
                            "description": "Slack channel ID (e.g., C01CPSKFG0P)",
                        },
                        "text": {
                            "type": "string",
                            "description": "Message text (supports Slack markdown: *bold*, _italic_, `code`)",
                        },
                        "thread_ts": {
                            "type": "string",
                            "description": "Thread timestamp to reply in (REQUIRED for alert responses)",
                        },
                    },
                    "required": ["channel_id", "text"],
                },
            )
        )

    def register(self, tool: ToolDefinition) -> None:
        """Register a tool."""
        self.tools[tool.name] = tool

    def get(self, name: str) -> Optional[ToolDefinition]:
        """Get a tool by name."""
        return self.tools.get(name)

    def list_tools(self) -> list[dict[str, Any]]:
        """Get all tools in Anthropic API format."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.parameters,
            }
            for tool in self.tools.values()
        ]


class ToolExecutor:
    """
    Executes tools by calling the appropriate CLI commands or MCP tools.

    Uses ContextResolver to determine repo paths from URLs and issue keys.
    Uses SkillHooks to emit event notifications (DMs to PR authors, team updates).
    """

    def __init__(self, project_root: Path) -> None:
        self.project_root: Path = project_root
        self.rh_issue: str = os.getenv("RH_ISSUE_CLI", "rh-issue")

        # Initialize context resolver for repo path lookups
        self.resolver: Optional[Any] = None  # Type is ContextResolver when available
        if RESOLVER_AVAILABLE:
            try:
                self.resolver = ContextResolver()
                logger.info(
                    f"Context resolver loaded with {len(self.resolver.repos)} repositories"
                )
            except Exception as e:
                logger.warning(f"Failed to load context resolver: {e}")

        # Initialize skill hooks for event notifications
        self.hooks: Optional[Any] = None  # Type is SkillHooks when available
        if HOOKS_AVAILABLE:
            try:
                self.hooks = SkillHooks.from_config()
                logger.info("Skill hooks initialized for event notifications")
            except Exception as e:
                logger.warning(f"Failed to load skill hooks: {e}")

    async def execute(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Execute a tool and return the result."""
        logger.info(f"Executing tool: {tool_name} with {arguments}")

        try:
            # Route to appropriate handler
            if tool_name.startswith("jira_"):
                return await self._execute_jira(tool_name, arguments)
            elif tool_name.startswith("gitlab_"):
                return await self._execute_gitlab(tool_name, arguments)
            elif tool_name.startswith("git_"):
                return await self._execute_git(tool_name, arguments)
            elif tool_name.startswith("k8s_"):
                return await self._execute_k8s(tool_name, arguments)
            elif tool_name.startswith("bonfire_"):
                return await self._execute_bonfire(tool_name, arguments)
            elif tool_name.startswith("quay_"):
                return await self._execute_quay(tool_name, arguments)
            elif tool_name.startswith("memory_"):
                return await self._execute_memory(tool_name, arguments)
            elif tool_name.startswith("slack_"):
                return await self._execute_slack(tool_name, arguments)
            elif tool_name == "skill_run":
                return await self._execute_skill(arguments)
            else:
                return f"Unknown tool: {tool_name}"
        except Exception as e:
            error_msg = str(e)
            logger.error(
                f"Tool execution error for {tool_name}: {error_msg}", exc_info=True
            )

            # Check for known issues from memory
            matches = _check_known_issues_sync(
                tool_name=tool_name, error_text=error_msg
            )
            known_text = _format_known_issues(matches)

            if known_text:
                return f"❌ Error with {tool_name}: {error_msg}\n{known_text}"
            else:
                return (
                    f"❌ The {tool_name} tool failed: {error_msg}\n\n"
                    f"💡 **Auto-fix:** `debug_tool('{tool_name}')`\n"
                    f"📚 **After fixing:** `learn_tool_fix('{tool_name}', '<pattern>', '<cause>', '<fix>')`"
                )

    async def _run_command(
        self,
        cmd: list[str],
        cwd: Optional[str] = None,
        env: Optional[dict[str, str]] = None,
    ) -> str:
        """Run a shell command and return output."""
        try:
            run_env = os.environ.copy()
            if env:
                run_env.update(env)

            # CRITICAL: Clear virtualenv variables to allow pipenv commands (like rh-issue) to work
            # Without this, pipenv detects our venv and uses it instead of jira-creator's venv
            for var in ["VIRTUAL_ENV", "PIPENV_ACTIVE", "PYTHONHOME"]:
                run_env.pop(var, None)
            run_env["PIPENV_IGNORE_VIRTUALENVS"] = "1"
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=cwd or str(self.project_root),
                env=run_env,
            )
            output = result.stdout
            if result.returncode != 0 and result.stderr:
                output += f"\nError: {result.stderr}"
            return output.strip() or "(no output)"
        except subprocess.TimeoutExpired:
            return "The command timed out. Please try a simpler request."
        except Exception as e:
            logger.error(f"Command execution failed: {e}", exc_info=True)
            return "Unable to execute that command right now."

    async def _execute_jira(self, tool_name: str, args: dict[str, Any]) -> str:
        """Execute Jira tools via rh-issue CLI."""
        if tool_name == "jira_view":
            key = args.get("issue_key", "")
            return await self._run_command([self.rh_issue, "view", key])
        elif tool_name == "jira_search":
            jql = args.get("jql", "")
            max_results = args.get("max_results", 10)
            return await self._run_command(
                [self.rh_issue, "search", jql, "--max", str(max_results)]
            )
        elif tool_name == "jira_comment":
            key = args.get("issue_key", "")
            comment = args.get("comment", "")
            return await self._run_command([self.rh_issue, "comment", key, comment])
        return f"Unknown Jira tool: {tool_name}"

    def _resolve_gitlab_context(self, args: dict[str, Any]) -> dict[str, Any]:
        """Resolve GitLab project, MR ID, and execution context from arguments."""
        import re

        mr_input = args.get("mr_id", "") or args.get("url", "")
        project = args.get("repo", args.get("project", ""))
        mr_id = ""
        local_repo_path = None

        # Use context resolver if available
        if self.resolver and mr_input:
            ctx = self.resolver.from_message(mr_input)
            if ctx.gitlab_project:
                project = ctx.gitlab_project
            if ctx.mr_id:
                mr_id = ctx.mr_id
            if ctx.repo_path:
                local_repo_path = ctx.repo_path
                logger.info(f"Resolved GitLab project to local path: {local_repo_path}")

        # Fallback: manual URL parsing
        if not project or not mr_id:
            url_match = re.match(
                r"https?://[^/]+/(.+?)/-/merge_requests/(\d+)", mr_input
            )
            if url_match:
                project = project or url_match.group(1)
                mr_id = mr_id or url_match.group(2)
            else:
                mr_id = mr_id or mr_input.lstrip("!").strip()

        # Try to resolve local path from project if we don't have it yet
        if not local_repo_path and project and self.resolver:
            local_repo_path = self.resolver.get_repo_path(project)

        # Determine how to run glab
        if local_repo_path and Path(local_repo_path).exists():
            run_cwd = local_repo_path
            use_repo_flag = False
            logger.info(f"Running glab from local repo: {run_cwd}")
        else:
            run_cwd = None
            use_repo_flag = True
            logger.info(f"Running glab with --repo flag: {project}")

        return {
            "project": project,
            "mr_id": mr_id,
            "run_cwd": run_cwd,
            "use_repo_flag": use_repo_flag,
        }

    async def _gitlab_mr_view(
        self, mr_id: str, project: str, run_cwd: str | None, use_repo_flag: bool
    ) -> str:
        """Execute gitlab_mr_view tool."""
        if not mr_id:
            return "MR ID is required for gitlab_mr_view"
        cmd = ["glab", "mr", "view", mr_id, "--web=false"]
        if use_repo_flag:
            cmd.extend(["--repo", project])
        return await self._run_command(cmd, cwd=run_cwd)

    async def _gitlab_mr_list(
        self,
        project: str,
        run_cwd: str | None,
        use_repo_flag: bool,
        args: dict[str, Any],
    ) -> str:
        """Execute gitlab_mr_list tool."""
        cmd = ["glab", "mr", "list"]
        if args.get("author"):
            cmd.extend(["--author", args["author"]])
        cmd.extend(["--state", args.get("state", "opened")])
        if use_repo_flag:
            cmd.extend(["--repo", project])
        return await self._run_command(cmd, cwd=run_cwd)

    async def _gitlab_pipeline_status(
        self, project: str, run_cwd: str | None, use_repo_flag: bool
    ) -> str:
        """Execute gitlab_pipeline_status tool."""
        cmd = ["glab", "ci", "status"]
        if use_repo_flag:
            cmd.extend(["--repo", project])
        return await self._run_command(cmd, cwd=run_cwd)

    async def _gitlab_mr_approve(
        self,
        mr_id: str,
        project: str,
        run_cwd: str | None,
        use_repo_flag: bool,
        args: dict[str, Any],
    ) -> str:
        """Execute gitlab_mr_approve tool with event emission."""
        if not mr_id:
            return "MR ID is required for gitlab_mr_approve"
        cmd = ["glab", "mr", "approve", mr_id]
        if use_repo_flag:
            cmd.extend(["--repo", project])
        result = await self._run_command(cmd, cwd=run_cwd)

        # Emit approval event
        if self.hooks and "error" not in result.lower():
            await self.hooks.emit(
                "review_approved",
                {
                    "mr_id": mr_id,
                    "author": args.get("author", ""),
                    "project": project,
                    "target_branch": args.get("target_branch", "main"),
                },
            )
        return result

    async def _gitlab_mr_comment(
        self,
        mr_id: str,
        project: str,
        run_cwd: str | None,
        use_repo_flag: bool,
        args: dict[str, Any],
    ) -> str:
        """Execute gitlab_mr_comment tool with event emission."""
        if not mr_id:
            return "MR ID is required for gitlab_mr_comment"
        comment = args.get("comment", args.get("body", ""))
        if not comment:
            return "Comment text is required"
        cmd = ["glab", "mr", "note", mr_id, "-m", comment]
        if use_repo_flag:
            cmd.extend(["--repo", project])
        result = await self._run_command(cmd, cwd=run_cwd)

        # Emit comment event
        if self.hooks and "error" not in result.lower():
            await self.hooks.emit(
                "review_comment",
                {"mr_id": mr_id, "author": args.get("author", ""), "project": project},
            )
        return result

    async def _gitlab_mr_merge(
        self,
        mr_id: str,
        project: str,
        run_cwd: str | None,
        use_repo_flag: bool,
        args: dict[str, Any],
    ) -> str:
        """Execute gitlab_mr_merge tool with event emission."""
        if not mr_id:
            return "MR ID is required for gitlab_mr_merge"
        cmd = ["glab", "mr", "merge", mr_id, "--yes"]
        if args.get("squash"):
            cmd.append("--squash")
        if use_repo_flag:
            cmd.extend(["--repo", project])
        result = await self._run_command(cmd, cwd=run_cwd)

        # Emit merge event
        if self.hooks and "error" not in result.lower():
            await self.hooks.emit(
                "mr_merged",
                {
                    "mr_id": mr_id,
                    "author": args.get("author", ""),
                    "project": project,
                    "target_branch": args.get("target_branch", "main"),
                },
            )
        return result

    async def _execute_gitlab(self, tool_name: str, args: dict[str, Any]) -> str:
        """
        Execute GitLab tools.

        Uses ContextResolver to parse URLs and resolve project paths.
        """
        ctx = self._resolve_gitlab_context(args)
        project = ctx["project"]
        mr_id = ctx["mr_id"]
        run_cwd = ctx["run_cwd"]
        use_repo_flag = ctx["use_repo_flag"]

        if not project:
            return "Project/repo is required. Provide a full GitLab URL or specify the project."

        if tool_name == "gitlab_mr_view":
            return await self._gitlab_mr_view(mr_id, project, run_cwd, use_repo_flag)
        elif tool_name == "gitlab_mr_list":
            return await self._gitlab_mr_list(project, run_cwd, use_repo_flag, args)
        elif tool_name == "gitlab_pipeline_status":
            return await self._gitlab_pipeline_status(project, run_cwd, use_repo_flag)
        elif tool_name == "gitlab_mr_approve":
            return await self._gitlab_mr_approve(
                mr_id, project, run_cwd, use_repo_flag, args
            )
        elif tool_name == "gitlab_mr_comment":
            return await self._gitlab_mr_comment(
                mr_id, project, run_cwd, use_repo_flag, args
            )
        elif tool_name == "gitlab_mr_merge":
            return await self._gitlab_mr_merge(
                mr_id, project, run_cwd, use_repo_flag, args
            )

        return f"Unknown GitLab tool: {tool_name}"

    async def _execute_git(self, tool_name: str, args: dict[str, Any]) -> str:
        """
        Execute Git tools.

        Uses ContextResolver to resolve repo paths from issue keys or repo names.
        """
        repo_path = args.get("repo_path", "")

        # Try to resolve repo path from context if not provided
        if not repo_path and self.resolver:
            # Check for issue key in args that might hint at repo
            issue_key = args.get("issue_key", "")
            if issue_key:
                ctx = self.resolver.from_issue_key(issue_key)
                if ctx.repo_path:
                    repo_path = ctx.repo_path
                    logger.info(f"Resolved git repo from issue key: {repo_path}")

            # Check for repo name
            repo_name = args.get("repo_name", "")
            if repo_name and not repo_path:
                ctx = self.resolver.from_repo_name(repo_name)
                if ctx.repo_path:
                    repo_path = ctx.repo_path

        # Default to project root if still no path
        if not repo_path:
            repo_path = str(self.project_root)

        # Validate path exists
        if not Path(repo_path).exists():
            return f"Repository path not found: {repo_path}"

        if tool_name == "git_status":
            return await self._run_command(["git", "status", "-sb"], cwd=repo_path)
        elif tool_name == "git_log":
            count = args.get("count", 10)
            return await self._run_command(
                ["git", "log", f"-{count}", "--oneline"], cwd=repo_path
            )
        return f"Unknown Git tool: {tool_name}"

    def _get_kubeconfig(self, environment: str) -> str:
        """Get kubeconfig path for environment."""
        env_map = {
            "stage": "config.s",
            "s": "config.s",
            "production": "config.p",
            "prod": "config.p",
            "p": "config.p",
            "ephemeral": "config.e",
            "e": "config.e",
            "appsre-pipelines": "config.ap",
            "ap": "config.ap",
        }
        config_name = env_map.get(environment.lower(), f"config.{environment}")
        return str(Path.home() / ".kube" / config_name)

    async def _execute_k8s(self, tool_name: str, args: dict[str, Any]) -> str:
        """Execute Kubernetes tools via kubectl."""
        namespace = args.get("namespace", "")
        environment = args.get("environment", "stage")

        # Detect ephemeral namespace
        if namespace.startswith("ephemeral-") or namespace.startswith(
            "tower-analytics-pr-"
        ):
            environment = "ephemeral"

        kubeconfig = self._get_kubeconfig(environment)
        env = {"KUBECONFIG": kubeconfig}

        if tool_name == "k8s_get_pods":
            return await self._run_command(
                ["kubectl", "get", "pods", "-n", namespace], env=env
            )
        elif tool_name == "k8s_get_events":
            return await self._run_command(
                [
                    "kubectl",
                    "get",
                    "events",
                    "-n",
                    namespace,
                    "--sort-by=.lastTimestamp",
                ],
                env=env,
            )
        elif tool_name == "k8s_logs":
            pod = args.get("pod", "")
            tail = args.get("tail", 100)
            return await self._run_command(
                ["kubectl", "logs", "-n", namespace, pod, f"--tail={tail}"], env=env
            )
        return f"Unknown K8s tool: {tool_name}"

    def _get_bonfire_env(self) -> dict[str, str]:
        """Get environment for bonfire commands (ephemeral cluster)."""
        env = os.environ.copy()
        kubeconfig = Path.home() / ".kube" / "config.e"
        env["KUBECONFIG"] = str(kubeconfig)
        return env

    async def _execute_bonfire(self, tool_name: str, args: dict[str, Any]) -> str:
        """
        Execute bonfire tools for ephemeral namespace management.

        ALWAYS uses KUBECONFIG=~/.kube/config.e for ephemeral cluster.
        Uses the exact ITS deploy pattern for AA deployments.
        """
        env = self._get_bonfire_env()

        if tool_name == "bonfire_namespace_reserve":
            duration = args.get("duration", "2h")
            cmd = [
                "bonfire",
                "namespace",
                "reserve",
                "--duration",
                duration,
                "--pool",
                "default",
                "--timeout",
                "600",
                "--force",
            ]
            return await self._run_command(cmd, env=env)

        elif tool_name == "bonfire_namespace_list":
            mine_only = args.get("mine_only", True)
            cmd = ["bonfire", "namespace", "list"]
            if mine_only:
                cmd.append("--mine")
            return await self._run_command(cmd, env=env)

        elif tool_name == "bonfire_namespace_release":
            namespace = args.get("namespace", "")
            if not namespace:
                return "Error: namespace is required"

            # Safety: verify ownership first
            check_cmd = ["bonfire", "namespace", "list", "--mine"]
            check_result = await self._run_command(check_cmd, env=env)

            if namespace not in check_result:
                return f"Cannot release namespace '{namespace}' - not in your namespaces:\n{check_result}"

            cmd = ["bonfire", "namespace", "release", namespace]
            return await self._run_command(cmd, env=env)

        elif tool_name == "bonfire_deploy_aa":
            namespace = args.get("namespace", "")
            template_ref = args.get("template_ref", "")
            image_tag = args.get("image_tag", "")
            billing = args.get("billing", False)

            # Validate required args
            if not all([namespace, template_ref, image_tag]):
                return "Error: namespace, template_ref, and image_tag are all required"

            # Validate template_ref is 40 chars
            if len(template_ref) != 40:
                return f"Error: template_ref must be 40-char git SHA, got {len(template_ref)} chars"

            # Strip sha256: prefix if present
            digest = image_tag
            if digest.startswith("sha256:"):
                digest = digest[7:]

            # Validate image_tag is 64 chars
            if len(digest) != 64:
                return (
                    f"Error: image_tag must be 64-char sha256 digest, got {len(digest)} chars. "
                    "Use quay_get_tag to get the digest."
                )

            # Select component and image
            component = (
                "tower-analytics-billing-clowdapp"
                if billing
                else "tower-analytics-clowdapp"
            )
            image_base = "quay.io/redhat-user-workloads/aap-aa-tenant/aap-aa-main/automation-analytics-backend-main"
            repository = "aap-aa-tenant/aap-aa-main/automation-analytics-backend-main"

            # HARD STOP: Check if image exists in Quay before deploying
            logger.info(f"Checking if image exists: {image_base}:{template_ref}")
            image_ref = (
                f"docker://quay.io/redhat-user-workloads/{repository}:{template_ref}"
            )
            check_cmd = ["skopeo", "inspect", "--raw", image_ref]
            check_result = await self._run_command(check_cmd)

            if (
                "manifest unknown" in check_result.lower()
                or "error" in check_result.lower()
            ):
                return f"""❌ **STOP: Image not found in Quay**

The image for commit `{template_ref[:12]}` does not exist in redhat-user-workloads.

**Image checked:** `{image_base}:{template_ref}`

**Possible causes:**
1. Konflux hasn't built the image yet (check pipeline status)
2. The commit SHA is incorrect
3. The build failed

**What to do:**
1. Check Konflux build status for this commit
2. Wait for the build to complete
3. Retry once the image is available

**DO NOT** proceed with deployment - it will fail with ImagePullBackOff."""

            # Verify we got a valid manifest (contains schemaVersion or mediaType)
            if "schemaVersion" not in check_result and "mediaType" not in check_result:
                return f"""⚠️ **Image check inconclusive**

Got unexpected response when checking image:
```
{check_result[:500]}
```

Please verify the image exists before proceeding."""

            logger.info(f"Image verified: {image_base}:{template_ref}")

            # Build exact ITS command
            cmd = [
                "bonfire",
                "deploy",
                "--source=appsre",
                "--ref-env",
                "insights-production",
                "--namespace",
                namespace,
                "--timeout",
                "900",
                "--optional-deps-method",
                "hybrid",
                "--frontends",
                "false",
                "--component",
                component,
                "--no-remove-resources",
                "all",
                "--set-template-ref",
                f"{component}={template_ref}",
                "--set-parameter",
                f"{component}/IMAGE={image_base}@sha256",
                "--set-parameter",
                f"{component}/IMAGE_TAG={digest}",
                "tower-analytics",
            ]

            logger.info(
                f"Bonfire deploy command: KUBECONFIG={env['KUBECONFIG']} {' '.join(cmd)}"
            )
            return await self._run_command(cmd, env=env)

        return f"Unknown bonfire tool: {tool_name}"

    async def _execute_quay(self, tool_name: str, args: dict[str, Any]) -> str:
        """Execute Quay tools to check images."""
        if tool_name == "quay_get_tag":
            repository = args.get("repository", "")
            tag = args.get("tag", "")

            if not repository or not tag:
                return "Error: repository and tag are required"

            # Use skopeo to inspect the image
            image_ref = f"docker://quay.io/redhat-user-workloads/{repository}:{tag}"
            cmd = ["skopeo", "inspect", image_ref]

            result = await self._run_command(cmd)

            if "manifest unknown" in result.lower() or "error" in result.lower():
                return (
                    f"Image not found: {repository}:{tag}\n\n"
                    "The image may not be built yet. Check Konflux build status."
                )

            # Extract digest from result
            try:
                import re

                digest_match = re.search(r'"Digest":\s*"sha256:([a-f0-9]{64})"', result)
                if digest_match:
                    digest = digest_match.group(1)
                    return (
                        f"Image found!\n\n**Tag:** {tag}\n**Manifest Digest:** sha256:{digest}\n\n"
                        "Use the 64-char digest (without 'sha256:' prefix) as image_tag for bonfire_deploy_aa."
                    )
            except Exception as e:
                logger.debug(f"Suppressed error in _execute_quay: {e}")

            return f"Image exists but could not parse digest:\n{result[:500]}"

        return f"Unknown Quay tool: {tool_name}"

    def _execute_memory_read(self, key: str, read_memory) -> str:
        """Execute memory_read tool."""
        if not key:
            # List available memory files
            memory_dir = Path.home() / ".config/aa_workflow/memory"
            if not memory_dir.exists():
                return "No memory directory found"
            files = []
            for f in memory_dir.rglob("*.yaml"):
                rel_path = f.relative_to(memory_dir)
                files.append(str(rel_path).replace(".yaml", ""))
            return "Available memory files:\n" + "\n".join(
                f"- {f}" for f in sorted(files)
            )

        data = read_memory(key)
        if not data:
            return f"Memory file '{key}' is empty or not found"

        import yaml

        return f"## Memory: {key}\n```yaml\n{yaml.safe_dump(data, default_flow_style=False)}\n```"

    def _execute_memory_append(
        self, key: str, list_path: str, item_str: Any, append_to_list
    ) -> str:
        """Execute memory_append tool."""
        if not key or not list_path:
            return "Error: key and list_path are required"

        # Parse item
        try:
            import yaml

            item = yaml.safe_load(item_str) if isinstance(item_str, str) else item_str
        except Exception as e:
            logger.debug(f"Suppressed error in _execute_memory_append: {e}")
            item = {"value": item_str}

        append_to_list(key, list_path, item)
        return f"Appended to {key}.{list_path}"

    def _execute_memory_session_log(self, action: str, details: str) -> str:
        """Execute memory_session_log tool."""
        if not action:
            return "Error: action is required"

        # Use session log from memory tools
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            from scripts.common.config_loader import get_timezone
            from scripts.common.memory import read_memory as read_mem
            from scripts.common.memory import write_memory

            tz = ZoneInfo(get_timezone())
            today = datetime.now(tz).strftime("%Y-%m-%d")
            log_key = f"sessions/{today}"

            # Read existing log
            log_data = read_mem(log_key)
            if not log_data:
                log_data = {"date": today, "entries": []}

            # Add entry
            entry = {
                "time": datetime.now(tz).strftime("%H:%M"),
                "action": action,
            }
            if details:
                entry["details"] = details

            log_data.setdefault("entries", []).append(entry)
            write_memory(log_key, log_data)

            return f"Logged: {action}"
        except Exception as e:
            return f"Failed to log: {e}"

    async def _execute_memory(self, tool_name: str, args: dict[str, Any]) -> str:
        """Execute memory tools using scripts.common.memory helpers."""
        try:
            # Import memory helpers
            from scripts.common.memory import append_to_list, read_memory
        except ImportError:
            return "Memory tools not available (scripts.common.memory not found)"

        if tool_name == "memory_read":
            return self._execute_memory_read(args.get("key", ""), read_memory)
        elif tool_name == "memory_append":
            return self._execute_memory_append(
                args.get("key", ""),
                args.get("list_path", ""),
                args.get("item", "{}"),
                append_to_list,
            )
        elif tool_name == "memory_session_log":
            return self._execute_memory_session_log(
                args.get("action", ""), args.get("details", "")
            )

        return f"Unknown memory tool: {tool_name}"

    async def _execute_slack(self, tool_name: str, args: dict[str, Any]) -> str:
        """Execute Slack tools via D-Bus or direct API."""
        if tool_name == "slack_send_message":
            channel_id = args.get("channel_id", "")
            text = args.get("text", "")
            thread_ts = args.get("thread_ts", "")

            if not channel_id or not text:
                return "Error: channel_id and text are required"

            try:
                # Try D-Bus first (via slack_dbus)
                import sys
                from pathlib import Path

                scripts_dir = Path(__file__).parent
                if str(scripts_dir) not in sys.path:
                    sys.path.insert(0, str(scripts_dir))

                from services.slack.dbus import SlackAgentClient

                client = SlackAgentClient()
                if await client.connect():
                    result = await client.send_message(
                        channel_id, text, thread_ts or ""
                    )
                    await client.disconnect()
                    if result.get("success"):
                        return f"✅ Message sent to {channel_id}" + (
                            f" in thread {thread_ts}" if thread_ts else ""
                        )
                    else:
                        return f"❌ Failed to send message: {result.get('error', 'unknown error')}"
                else:
                    return "❌ D-Bus not connected - is slack-daemon running?"

            except Exception as e:
                logger.error(f"Slack send failed: {e}")
                return f"❌ Error sending to Slack: {e}"

        return f"Unknown Slack tool: {tool_name}"

    async def _execute_skill(self, args: dict[str, Any]) -> str:
        """
        Execute a workflow skill from YAML using the full SkillExecutor.

        This now uses the actual skill engine from aa_workflow MCP server,
        providing full skill execution with all steps, conditions, and tools.
        """
        skill_name = args.get("skill_name", "")
        inputs = args.get("inputs", {})

        # Ensure inputs is a dict (might be passed as JSON string)
        if isinstance(inputs, str):
            try:
                inputs = json.loads(inputs)
            except json.JSONDecodeError:
                inputs = {}

        # ALWAYS default to slack_format=True when called from the Slack agent
        if "slack_format" not in inputs:
            inputs["slack_format"] = True

        # Check if skill executor is available
        if not SKILL_EXECUTOR_AVAILABLE:
            logger.warning("Skill executor not available, using inline fallback")
            # Fall back to inline executor for test_mr_ephemeral
            if skill_name == "test_mr_ephemeral":
                return await self._skill_test_mr_ephemeral(inputs)
            return f"Skill executor not available. Cannot run: {skill_name}"

        # Check if skill file exists
        skill_file = SKILLS_DIR / f"{skill_name}.yaml"
        if not skill_file.exists():
            # List available skills
            available = (
                [f.stem for f in SKILLS_DIR.glob("*.yaml")]
                if SKILLS_DIR.exists()
                else []
            )
            return f"❌ Skill not found: {skill_name}\n\nAvailable: {', '.join(sorted(available)) or 'none'}"

        # Load and execute the skill
        try:
            with open(skill_file) as f:
                skill = skill_yaml.safe_load(f)

            # Create executor and run
            agent_config = SkillExecutorConfig(
                debug=True,  # Enable debug for visibility
                source="slack",  # Claude agent is typically invoked from Slack
            )
            executor = SkillExecutor(
                skill=skill,
                inputs=inputs,
                config=agent_config,
                server=None,  # No MCP server needed - tools loaded dynamically
            )

            # Execute and return result
            result = await executor.execute()
            return cast(str, result)

        except Exception as e:
            logger.error(f"Skill execution error for {skill_name}: {e}", exc_info=True)
            # Fall back to inline executor for test_mr_ephemeral if skill engine fails
            if skill_name == "test_mr_ephemeral":
                logger.info("Falling back to inline executor for test_mr_ephemeral")
                return await self._skill_test_mr_ephemeral(inputs)
            return f"❌ Skill execution failed: {e}"

    async def _skill_test_mr_ephemeral(self, inputs: dict[str, Any]) -> str:
        """Execute test_mr_ephemeral skill inline using bonfire tools."""
        mr_id = inputs.get("mr_id")
        commit_sha: str = str(inputs.get("commit_sha") or "")
        billing = inputs.get("billing", False)
        duration = inputs.get("duration", "2h")

        if not mr_id and not commit_sha:
            return "Error: need either mr_id or commit_sha"

        # Step 1: Get commit SHA from MR if needed
        if mr_id and not commit_sha:
            mr_cmd = ["glab", "api", f"projects/:id/merge_requests/{mr_id}"]
            mr_result = await self._run_command(mr_cmd)

            try:
                mr_data = json.loads(mr_result)
                commit_sha = mr_data.get("sha", "")
                mr_state = mr_data.get("state", "")

                # If MR is merged, use the merge commit SHA
                if mr_state == "merged":
                    merge_sha = mr_data.get("merge_commit_sha", "")
                    if merge_sha:
                        commit_sha = merge_sha
                        logger.info(
                            f"MR {mr_id} is merged, using merge commit: {commit_sha[:12]}"
                        )

            except Exception as e:
                sha_match = re.search(r"[a-f0-9]{40}", mr_result)
                if sha_match:
                    commit_sha = sha_match.group(0)
                else:
                    return f"Could not get commit SHA from MR {mr_id}: {e}"

        # Validate/expand commit_sha
        if len(commit_sha) != 40:
            expand_result = await self._run_command(["git", "rev-parse", commit_sha])
            if len(expand_result.strip()) == 40:
                commit_sha = expand_result.strip()
            else:
                return f"Invalid commit SHA: {commit_sha}. Need 40-char SHA."

        # Step 2: Check if image exists in Quay
        quay_result = await self._execute_quay(
            "quay_get_tag",
            {
                "repository": "aap-aa-tenant/aap-aa-main/automation-analytics-backend-main",
                "tag": commit_sha,
            },
        )

        if "not found" in quay_result.lower() or "error" in quay_result.lower():
            return f"""❌ Image not ready for commit {commit_sha[:12]}.

The Konflux build may still be in progress. Check back in a few minutes.

{quay_result}"""

        # Extract digest
        digest_match = re.search(r"sha256:([a-f0-9]{64})", quay_result)
        if not digest_match:
            return f"Could not extract sha256 digest from Quay:\n{quay_result[:500]}"

        image_digest = digest_match.group(1)

        # Step 3: Reserve namespace
        reserve_result = await self._execute_bonfire(
            "bonfire_namespace_reserve",
            {
                "duration": duration,
            },
        )

        ns_match = re.search(r"(ephemeral-[a-z0-9]+)", reserve_result.lower())
        if not ns_match:
            return f"Could not reserve namespace:\n{reserve_result}"

        namespace = ns_match.group(1)

        # Step 4: Deploy
        deploy_result = await self._execute_bonfire(
            "bonfire_deploy_aa",
            {
                "namespace": namespace,
                "template_ref": commit_sha,
                "image_tag": image_digest,
                "billing": billing,
            },
        )

        component = "billing" if billing else "main"
        return f"""## ✅ Ephemeral Deployment Complete

**MR:** {mr_id or 'N/A'}
**Commit:** `{commit_sha[:12]}`
**Namespace:** `{namespace}`
**Component:** {component}

{deploy_result}

**Next steps:**
- Check pods: `k8s_get_pods` with namespace='{namespace}'
- Release when done: `bonfire_namespace_release` with namespace='{namespace}'"""


class ClaudeAgent:
    """
    Claude-powered agent that understands requests and calls tools.

    This is the "brain" of the Slack bot - it receives messages,
    uses Claude to understand them, decides which tools to call,
    executes them, and formulates responses.

    Supports two modes:
    1. Vertex AI: Set CLAUDE_CODE_USE_VERTEX=1 and ANTHROPIC_VERTEX_PROJECT_ID
    2. Direct API: Set ANTHROPIC_API_KEY
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        vertex_model: str = "claude-3-5-sonnet-v2@20241022",
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
    ) -> None:
        if not ANTHROPIC_AVAILABLE:
            raise ImportError(
                "anthropic package not installed. Install with: uv add anthropic"
            )

        self.max_tokens = max_tokens
        self.system_prompt = system_prompt or self._default_system_prompt()
        self.use_vertex = False

        # Check if using Vertex AI
        use_vertex = os.getenv("CLAUDE_CODE_USE_VERTEX", "0") == "1"
        vertex_project = os.getenv("ANTHROPIC_VERTEX_PROJECT_ID")
        vertex_region = os.getenv("ANTHROPIC_VERTEX_REGION", "us-east5")

        # Client can be either AnthropicVertex or Anthropic
        self.client: Any = None  # Will be set below
        self.model: str = model

        if use_vertex and vertex_project:
            if not VERTEX_AVAILABLE:
                raise ImportError(
                    "AnthropicVertex not available. Update anthropic: uv add anthropic --upgrade"
                )
            self.client = AnthropicVertex(
                project_id=vertex_project,
                region=vertex_region,
            )
            self.use_vertex = True
            # Use Vertex-compatible model name
            self.model = vertex_model
            logger.info(
                f"Using Vertex AI: project={vertex_project}, region={vertex_region}, model={self.model}"
            )
        else:
            # Fall back to direct API
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError(
                    "No Claude credentials found. Set either:\n"
                    "  - CLAUDE_CODE_USE_VERTEX=1 + ANTHROPIC_VERTEX_PROJECT_ID (for Vertex)\n"
                    "  - ANTHROPIC_API_KEY (for direct API)"
                )
            self.client = anthropic.Anthropic(api_key=api_key)
            self.model = model
            logger.info(f"Using direct Anthropic API with model={self.model}")

        self.tool_registry: ToolRegistry = ToolRegistry()
        self.tool_executor: ToolExecutor = ToolExecutor(PROJECT_ROOT)

        # Tool filtering configuration
        self.use_tool_filtering = TOOL_FILTER_AVAILABLE
        self.persona = "developer"  # Default persona, can be changed per session

        # Context injection configuration
        self.use_context_injection = CONTEXT_INJECTOR_AVAILABLE
        self.context_injector: Optional[Any] = None  # Lazy init
        self.default_project = "automation-analytics-backend"

        # Conversation history tracking
        # Key: conversation_id (e.g., "channel_id:user_id" or "thread_ts")
        # Value: list of message dicts [{"role": "user/assistant", "content": "..."}]
        self._conversations: dict[str, list[dict[str, str]]] = {}
        self._max_history: int = 10  # Keep last N message pairs per conversation
        self._history_ttl: int = 3600  # Clear conversations older than 1 hour
        self._max_conversations: int = 200  # Prevent unbounded memory growth
        self._conversation_timestamps: dict[str, float] = {}

    def _get_conversation_history(self, conversation_id: str) -> list[dict[str, str]]:
        """Get conversation history for a given ID, clearing stale entries."""
        now = time.time()

        # Clear stale conversations
        stale_ids = [
            cid
            for cid, ts in self._conversation_timestamps.items()
            if now - ts > self._history_ttl
        ]
        for cid in stale_ids:
            self._conversations.pop(cid, None)
            self._conversation_timestamps.pop(cid, None)

        # Enforce max conversations limit - remove oldest if over limit
        if len(self._conversations) > self._max_conversations:
            sorted_convs = sorted(
                self._conversation_timestamps.items(), key=lambda x: x[1]
            )
            for cid, _ in sorted_convs[
                : len(self._conversations) - self._max_conversations
            ]:
                self._conversations.pop(cid, None)
                self._conversation_timestamps.pop(cid, None)

        return self._conversations.get(conversation_id, [])

    def _save_conversation_history(
        self, conversation_id: str, user_msg: str, assistant_msg: str
    ) -> None:
        """Save a message exchange to conversation history."""
        if conversation_id not in self._conversations:
            self._conversations[conversation_id] = []

        history = self._conversations[conversation_id]
        history.append({"role": "user", "content": user_msg})
        history.append({"role": "assistant", "content": assistant_msg})

        # Trim to max history (keep last N pairs = 2N messages)
        max_messages = self._max_history * 2
        if len(history) > max_messages:
            self._conversations[conversation_id] = history[-max_messages:]

        self._conversation_timestamps[conversation_id] = time.time()

    def _default_system_prompt(self) -> str:
        return """\
youre a 42 year old senior software engineer from ireland. \
20 years in the game. typing on your phone while grabbing a coffee.

PERSONA:
- all lowercase. no caps ever
- skip apostrophes: dont, cant, wont, youre, thats, im
- dev shorthand: prod, env, repo, pr, mr, k8s, ci, cfg, deps
- occasional typos from adjacent keys: teh, adn, fo, fubction, opem
- no ai fluff. no "i can help with that". just answer
- start with the answer, then details, maybe complain about why things are broken
- slack formatting: *bold*, _italic_, `code` - never **double asterisks**
- brief. senior devs dont waffle
- irish sentence rhythm (im after finding, thats grand, sure look) but no paddywhackery

TOOLS:
- jira: view issues, search, add comments - can access ANY jira project. \
just pass the issue key. never say you cant access a project - try it first
- gitlab: view mrs, list mrs, check pipelines
- git: status, logs
- k8s: pods, events, logs
- bonfire: namespace reserve/list/release, deploy_aa for ephemeral
- quay: check if images exist
- skill_run: workflow automations

INTENT MAPPING - when user says these, use skill_run:
- "deploy to ephemeral", "test MR 123", "deploy MR 123", "test AAP-12345"
  → skill_run("test_mr_ephemeral", {"mr_id": 123}) or {"issue_key": "AAP-12345"}
- "start work on AAP-12345"
  → skill_run("start_work", {"issue_key": "AAP-12345"})
- "review MR 123", "review AAP-12345"
  → skill_run("review_pr", {"mr_id": 123}) or {"issue_key": "AAP-12345"}
- "investigate this alert", "look into this alert"
  → skill_run("investigate_slack_alert", {"channel_id": "...", "message_ts": "...", "message_text": "..."})

ALWAYS run the investigate_slack_alert skill when you receive an alert context.

for ephemeral deploys: ALWAYS use skill_run("test_mr_ephemeral", {...})
it handles: getting SHA, checking quay, reserving namespace, deploying

CRITICAL RULES - NEVER BREAK THESE:
1. NEVER copy kubeconfig files. no cp commands for kubeconfig. ever.
2. NEVER construct raw bonfire/oc/kubectl commands. use the tools.
3. NEVER use short SHAs. always 40-char git sha, 64-char image digest.

KUBECONFIG - the tools handle this automatically:
- ephemeral: KUBECONFIG=~/.kube/config.e (handled by bonfire tools)
- stage: ~/.kube/config.s
- prod: ~/.kube/config.p

use tools to get real data. dont guess. \
for jira issues (any project - AAP-12345, ANSTRAT-1848, etc) use jira_view. \
for mr urls use gitlab_mr_view."""

    def _build_context_message(
        self,
        message: str,
        context: Optional[dict],
        resolved_ctx,
        filter_context: Optional[dict] = None,
    ) -> str:
        """Build context-enriched message with memory, patterns, and semantic knowledge."""
        context_parts = []
        if context:
            context_parts.append(
                f"User: {context.get('user_name', 'unknown')} in #{context.get('channel_name', 'unknown')}"
            )

            user_category = context.get("user_category", "unknown")
            include_emojis = context.get("include_emojis", True)

            if user_category == "concerned":
                context_parts.append(
                    "TONE: formal - this is a manager/stakeholder. "
                    "be professional, clear, no typos, no casual slang. skip emojis."
                )
            elif user_category == "safe":
                context_parts.append(
                    "TONE: casual - teammate, full irish dev mode, typos ok, emojis ok"
                )
            else:
                emoji_note = "emojis ok" if include_emojis else "skip emojis"
                context_parts.append(
                    f"TONE: professional - clear and helpful, {emoji_note}"
                )

        if resolved_ctx and resolved_ctx.is_valid():
            if resolved_ctx.repo_path:
                context_parts.append(
                    f"Repository: {resolved_ctx.repo_name} at {resolved_ctx.repo_path}"
                )
            if resolved_ctx.gitlab_project:
                context_parts.append(f"GitLab: {resolved_ctx.gitlab_project}")
            if resolved_ctx.issue_key:
                context_parts.append(f"Jira: {resolved_ctx.issue_key}")
            if resolved_ctx.mr_id:
                context_parts.append(f"MR: !{resolved_ctx.mr_id}")
        elif resolved_ctx and resolved_ctx.needs_clarification():
            repos = ", ".join(a["name"] for a in resolved_ctx.alternatives)
            context_parts.append(
                f"Ambiguous repo - matches: {repos}. Ask user which one."
            )

        # === Add enriched context from HybridToolFilter ===
        enrichment_parts = []
        if filter_context:
            ctx = filter_context.get("context", {})

            # Memory state (active issues, current repo)
            mem = ctx.get("memory_state", {})
            if mem.get("current_repo"):
                enrichment_parts.append(f"Active repo: {mem['current_repo']}")
            if mem.get("current_branch"):
                enrichment_parts.append(f"Branch: {mem['current_branch']}")
            active_issues = mem.get("active_issues", [])
            if active_issues:
                issue_keys = [i.get("key", str(i)) for i in active_issues[:3]]
                enrichment_parts.append(f"Active issues: {', '.join(issue_keys)}")

            # Detected skill
            skill = ctx.get("skill", {})
            if skill.get("name"):
                enrichment_parts.append(f"Detected skill: {skill['name']}")
                if skill.get("description"):
                    enrichment_parts.append(
                        f"Skill purpose: {skill['description'][:100]}"
                    )

            # Learned patterns (error fixes)
            patterns = ctx.get("learned_patterns", [])
            if patterns:
                pattern_hints = []
                for p in patterns[:2]:
                    if p.get("pattern") and p.get("fix"):
                        pattern_hints.append(f"• {p['pattern'][:50]} → {p['fix'][:50]}")
                if pattern_hints:
                    enrichment_parts.append("Known fixes:\n" + "\n".join(pattern_hints))

            # Semantic knowledge (relevant code)
            semantic = ctx.get("semantic_knowledge", [])
            if semantic:
                code_hints = []
                for s in semantic[:2]:
                    if s.get("file"):
                        code_hints.append(
                            f"• {s['file']}: {s.get('content', '')[:80]}..."
                        )
                if code_hints:
                    enrichment_parts.append("Relevant code:\n" + "\n".join(code_hints))

        # Build final message
        result_parts = []
        if context_parts:
            result_parts.append("Context: " + " | ".join(context_parts))
        if enrichment_parts:
            result_parts.append("Enriched Context:\n" + "\n".join(enrichment_parts))
        result_parts.append(f"Message: {message}")

        return "\n\n".join(result_parts)

    async def _execute_tool_loop(self, response, messages, tools):
        """Execute tool calls in a loop until Claude stops requesting tools."""
        while response.stop_reason == "tool_use":
            tool_calls = [
                block for block in response.content if block.type == "tool_use"
            ]

            tool_results = []
            for tc in tool_calls:
                result = await self.tool_executor.execute(tc.name, tc.input)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": result,
                    }
                )

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.system_prompt,
                tools=tools,
                messages=messages,
            )
        return response

    async def process_message(
        self,
        message: str,
        context: Optional[dict[str, Any]] = None,
        conversation_id: Optional[str] = None,
    ) -> str:
        """
        Process a message using Claude.

        This method:
        1. Gathers context from multiple knowledge sources (Slack, code, Jira, memory)
        2. Builds an enriched system prompt with the gathered context
        3. Calls Claude with the enriched prompt and available tools
        4. Executes any tool calls Claude requests
        5. Returns the final response
        """
        # Load conversation history
        history = []
        if conversation_id:
            history = self._get_conversation_history(conversation_id)

        # Extract repository context
        resolved_ctx = None
        if RESOLVER_AVAILABLE:
            try:
                resolver = ContextResolver()
                resolved_ctx = resolver.from_message(message)
            except Exception as e:
                logger.warning(f"Failed to resolve context: {e}")

        # ============================================================
        # CONTEXT INJECTION - Gather knowledge from multiple sources
        # ============================================================
        gathered_context: Optional[Any] = None  # Type is GatheredContext when available
        if self.use_context_injection and CONTEXT_INJECTOR_AVAILABLE:
            try:
                # Lazy init context injector
                if self.context_injector is None:
                    self.context_injector = ContextInjector(
                        project=self.default_project
                    )

                # Gather context from all sources
                gathered_context = await self.context_injector.gather_context_async(
                    query=message,
                    include_slack=True,  # Always search Slack conversations
                    include_code=True,  # Always search codebase
                    include_jira=True,  # Look up any detected Jira keys
                    include_memory=True,  # Check current work context
                )

                if gathered_context.has_context():
                    logger.info(
                        f"Context injection: {gathered_context.total_results} results "
                        f"from {len([s for s in gathered_context.sources if s.found])} sources "
                        f"in {gathered_context.total_latency_ms:.0f}ms"
                    )
            except Exception as e:
                logger.warning(f"Context injection failed: {e}")
                gathered_context = None

        # Get available tools (with optional NPU-powered filtering)
        all_tools = self.tool_registry.list_tools()
        filter_result = None

        if self.use_tool_filtering and TOOL_FILTER_AVAILABLE:
            # Detect skill early for better filtering
            detected_skill = detect_skill(message) if detect_skill else None

            # Get filtered tool names using 4-layer filter
            # This also returns enriched context (memory, patterns, semantic knowledge)
            filter_result = filter_tools_detailed(
                message=message,
                persona=self.persona,
                detected_skill=detected_skill,
            )

            relevant_tool_names = set(filter_result["tools"])

            # Filter tool definitions to only include relevant tools
            tools = [tool for tool in all_tools if tool["name"] in relevant_tool_names]

            # Check if persona was auto-detected and update
            if filter_result.get("persona_auto_detected"):
                logger.info(
                    f"Auto-detected persona: {filter_result['persona']} "
                    f"(was {self.persona}) via {filter_result['persona_detection_reason']}"
                )

            logger.info(
                f"Tool filtering: {len(all_tools)} → {len(tools)} tools "
                f"({filter_result['reduction_pct']}% reduction, {filter_result['latency_ms']}ms) "
                f"via {', '.join(filter_result['methods'])}"
            )
        else:
            tools = all_tools

        # Build context-enriched message (includes memory, patterns, semantic knowledge)
        enriched_message = self._build_context_message(
            message, context, resolved_ctx, filter_result
        )
        messages = history + [{"role": "user", "content": enriched_message}]

        # ============================================================
        # BUILD SYSTEM PROMPT WITH INJECTED CONTEXT
        # ============================================================
        system_prompt = self.system_prompt
        if gathered_context and gathered_context.has_context():
            # Inject gathered context into system prompt
            system_prompt = self._inject_context_into_prompt(
                base_prompt=self.system_prompt,
                gathered_context=gathered_context,
            )

        # Call Claude
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system_prompt,
            tools=tools,
            messages=messages,
        )

        # Execute tool calls in a loop
        response = await self._execute_tool_loop(response, messages, tools)

        # Extract final text response
        final_response = ""
        for block in response.content:
            if hasattr(block, "text"):
                final_response += block.text

        result = final_response or "I processed your request but have no response."

        # Save to conversation history if we have an ID
        if conversation_id:
            self._save_conversation_history(conversation_id, message, result)

        return result

    def _inject_context_into_prompt(
        self,
        base_prompt: str,
        gathered_context: Any,  # GatheredContext
    ) -> str:
        """
        Inject gathered context into the system prompt.

        The context is added as a separate section that Claude can reference
        when formulating responses.
        """
        if not gathered_context or not gathered_context.formatted:
            return base_prompt

        # Add context injection instructions
        context_instructions = """

KNOWLEDGE CONTEXT:
The following context has been gathered from past Slack conversations, the codebase,
Jira issues, and memory. Use this information to provide informed, accurate responses.
Reference specific sources when relevant (e.g., "based on the Slack conversation..." or
"looking at the code in..."). If the context doesn't contain relevant information for
the question, you can still use your tools to look up additional details.

"""

        return base_prompt + context_instructions + gathered_context.formatted


# Convenience function
async def ask_claude(message: str, context: Optional[dict[str, Any]] = None) -> str:
    """Quick way to ask Claude something."""
    agent = ClaudeAgent()
    return await agent.process_message(message, context)


if __name__ == "__main__":
    # Test the agent (asyncio already imported at top of file)
    async def test():
        agent = ClaudeAgent()

        # Test with a simple query
        response = await agent.process_message(
            "What's the status of AAP-12345?",
            context={"user_name": "testuser", "channel_name": "test"},
        )
        print(response)

    asyncio.run(test())
