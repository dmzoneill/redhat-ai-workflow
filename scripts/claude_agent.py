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
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Add parent to path for config imports
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import anthropic
    from anthropic import AnthropicVertex

    ANTHROPIC_AVAILABLE = True
    VERTEX_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    VERTEX_AVAILABLE = False
    AnthropicVertex = None

try:
    from config.context_resolver import ContextResolver, ResolvedContext

    RESOLVER_AVAILABLE = True
except ImportError:
    RESOLVER_AVAILABLE = False
    ContextResolver = None
    ResolvedContext = None

try:
    from scripts.skill_hooks import SkillHooks

    HOOKS_AVAILABLE = True
except ImportError:
    HOOKS_AVAILABLE = False
    SkillHooks = None

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent


@dataclass
class ToolDefinition:
    """Definition of a tool Claude can call."""

    name: str
    description: str
    parameters: dict
    handler: callable | None = None


@dataclass
class ToolCall:
    """A tool call requested by Claude."""

    id: str
    name: str
    arguments: dict


@dataclass
class ToolResult:
    """Result of executing a tool."""

    tool_use_id: str
    content: str
    is_error: bool = False


class ToolRegistry:
    """
    Registry of tools available to Claude.

    Maps tool names to their definitions and handlers.
    """

    def __init__(self):
        self.tools: dict[str, ToolDefinition] = {}
        self._register_builtin_tools()

    def _register_builtin_tools(self):
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
                        "issue_key": {"type": "string", "description": "Jira issue key"},
                        "comment": {"type": "string", "description": "Comment text to add"},
                    },
                    "required": ["issue_key", "comment"],
                },
            )
        )

        # GitLab tools - simplified, full functionality in aa-gitlab MCP server
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
                    "properties": {"mr_id": {"type": "string", "description": "Merge Request ID"}},
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
                        "repo_path": {"type": "string", "description": "Path to git repository"}
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
                        "repo_path": {"type": "string", "description": "Path to git repository"},
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
                        "namespace": {"type": "string", "description": "Kubernetes namespace"}
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
                        "namespace": {"type": "string", "description": "Kubernetes namespace"}
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
                        "namespace": {"type": "string", "description": "Kubernetes namespace"},
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
        self.register(
            ToolDefinition(
                name="skill_run",
                description="""Run a workflow skill.

For ephemeral deployments, USE THIS:
  skill_run("test_mr_ephemeral", {"mr_id": 1459})
  skill_run("test_mr_ephemeral", {"mr_id": 1459, "billing": true})
  skill_run("test_mr_ephemeral", {"commit_sha": "abc123..."})

This handles everything: gets SHA, checks image, reserves namespace, deploys.
Works for both open and merged MRs.""",
                parameters={
                    "type": "object",
                    "properties": {
                        "skill_name": {"type": "string", "description": "Name of the skill to run"},
                        "inputs": {"type": "object", "description": "Inputs for the skill"},
                    },
                    "required": ["skill_name"],
                },
            )
        )

    def register(self, tool: ToolDefinition):
        """Register a tool."""
        self.tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition | None:
        """Get a tool by name."""
        return self.tools.get(name)

    def list_tools(self) -> list[dict]:
        """Get all tools in Anthropic API format."""
        return [
            {"name": tool.name, "description": tool.description, "input_schema": tool.parameters}
            for tool in self.tools.values()
        ]


class ToolExecutor:
    """
    Executes tools by calling the appropriate CLI commands or MCP tools.

    Uses ContextResolver to determine repo paths from URLs and issue keys.
    Uses SkillHooks to emit event notifications (DMs to PR authors, team updates).
    """

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.rh_issue = os.getenv("RH_ISSUE_CLI", "rh-issue")

        # Initialize context resolver for repo path lookups
        self.resolver: Optional[ContextResolver] = None
        if RESOLVER_AVAILABLE:
            try:
                self.resolver = ContextResolver()
                logger.info(f"Context resolver loaded with {len(self.resolver.repos)} repositories")
            except Exception as e:
                logger.warning(f"Failed to load context resolver: {e}")

        # Initialize skill hooks for event notifications
        self.hooks: Optional[SkillHooks] = None
        if HOOKS_AVAILABLE:
            try:
                self.hooks = SkillHooks.from_config()
                logger.info("Skill hooks initialized for event notifications")
            except Exception as e:
                logger.warning(f"Failed to load skill hooks: {e}")

    async def execute(self, tool_name: str, arguments: dict) -> str:
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
            elif tool_name == "skill_run":
                return await self._execute_skill(arguments)
            else:
                return f"Unknown tool: {tool_name}"
        except Exception as e:
            logger.error(f"Tool execution error for {tool_name}: {e}", exc_info=True)
            return (
                f"The {tool_name} tool is currently unavailable. Please try a different approach."
            )

    async def _run_command(
        self, cmd: list[str], cwd: str | None = None, env: dict | None = None
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

    async def _execute_jira(self, tool_name: str, args: dict) -> str:
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

    async def _execute_gitlab(self, tool_name: str, args: dict) -> str:
        """
        Execute GitLab tools.

        Uses ContextResolver to:
        - Parse GitLab URLs to extract project and MR ID
        - Resolve GitLab project paths to local directories
        - Run glab from the correct local repo directory

        This ensures glab has proper git remote context.
        """
        import re

        # Get URL or MR input
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
            url_match = re.match(r"https?://[^/]+/(.+?)/-/merge_requests/(\d+)", mr_input)
            if url_match:
                project = project or url_match.group(1)
                mr_id = mr_id or url_match.group(2)
            else:
                mr_id = mr_id or mr_input.lstrip("!").strip()

        # Try to resolve local path from project if we don't have it yet
        if not local_repo_path and project and self.resolver:
            local_repo_path = self.resolver.get_repo_path(project)

        if not project:
            return "Project/repo is required. Provide a full GitLab URL or specify the project."

        # Determine how to run glab
        if local_repo_path and Path(local_repo_path).exists():
            # Run from local repo directory (preferred - uses git remotes)
            run_cwd = local_repo_path
            use_repo_flag = False
            logger.info(f"Running glab from local repo: {run_cwd}")
        else:
            # Fall back to --repo flag
            run_cwd = None
            use_repo_flag = True
            logger.info(f"Running glab with --repo flag: {project}")

        if tool_name == "gitlab_mr_view":
            if not mr_id:
                return "MR ID is required for gitlab_mr_view"
            cmd = ["glab", "mr", "view", mr_id, "--web=false"]
            if use_repo_flag:
                cmd.extend(["--repo", project])
            return await self._run_command(cmd, cwd=run_cwd)

        elif tool_name == "gitlab_mr_list":
            cmd = ["glab", "mr", "list"]
            if args.get("author"):
                cmd.extend(["--author", args["author"]])
            cmd.extend(["--state", args.get("state", "opened")])
            if use_repo_flag:
                cmd.extend(["--repo", project])
            return await self._run_command(cmd, cwd=run_cwd)

        elif tool_name == "gitlab_pipeline_status":
            cmd = ["glab", "ci", "status"]
            if use_repo_flag:
                cmd.extend(["--repo", project])
            return await self._run_command(cmd, cwd=run_cwd)

        elif tool_name == "gitlab_mr_approve":
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

        elif tool_name == "gitlab_mr_comment":
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

        elif tool_name == "gitlab_mr_merge":
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

        return f"Unknown GitLab tool: {tool_name}"

    async def _execute_git(self, tool_name: str, args: dict) -> str:
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
            return await self._run_command(["git", "log", f"-{count}", "--oneline"], cwd=repo_path)
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

    async def _execute_k8s(self, tool_name: str, args: dict) -> str:
        """Execute Kubernetes tools via kubectl."""
        namespace = args.get("namespace", "")
        environment = args.get("environment", "stage")

        # Detect ephemeral namespace
        if namespace.startswith("ephemeral-") or namespace.startswith("tower-analytics-pr-"):
            environment = "ephemeral"

        kubeconfig = self._get_kubeconfig(environment)
        env = {"KUBECONFIG": kubeconfig}

        if tool_name == "k8s_get_pods":
            return await self._run_command(["kubectl", "get", "pods", "-n", namespace], env=env)
        elif tool_name == "k8s_get_events":
            return await self._run_command(
                ["kubectl", "get", "events", "-n", namespace, "--sort-by=.lastTimestamp"], env=env
            )
        elif tool_name == "k8s_logs":
            pod = args.get("pod", "")
            tail = args.get("tail", 100)
            return await self._run_command(
                ["kubectl", "logs", "-n", namespace, pod, f"--tail={tail}"], env=env
            )
        return f"Unknown K8s tool: {tool_name}"

    def _get_bonfire_env(self) -> dict:
        """Get environment for bonfire commands (ephemeral cluster)."""
        env = os.environ.copy()
        kubeconfig = Path.home() / ".kube" / "config.e"
        env["KUBECONFIG"] = str(kubeconfig)
        return env

    async def _execute_bonfire(self, tool_name: str, args: dict) -> str:
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
                "tower-analytics-billing-clowdapp" if billing else "tower-analytics-clowdapp"
            )
            image_base = "quay.io/redhat-user-workloads/aap-aa-tenant/aap-aa-main/automation-analytics-backend-main"
            repository = "aap-aa-tenant/aap-aa-main/automation-analytics-backend-main"

            # HARD STOP: Check if image exists in Quay before deploying
            logger.info(f"Checking if image exists: {image_base}:{template_ref}")
            image_ref = f"docker://quay.io/redhat-user-workloads/{repository}:{template_ref}"
            check_cmd = ["skopeo", "inspect", "--raw", image_ref]
            check_result = await self._run_command(check_cmd)

            if "manifest unknown" in check_result.lower() or "error" in check_result.lower():
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

            logger.info(f"Bonfire deploy command: KUBECONFIG={env['KUBECONFIG']} {' '.join(cmd)}")
            return await self._run_command(cmd, env=env)

        return f"Unknown bonfire tool: {tool_name}"

    async def _execute_quay(self, tool_name: str, args: dict) -> str:
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
            except Exception:
                pass

            return f"Image exists but could not parse digest:\n{result[:500]}"

        return f"Unknown Quay tool: {tool_name}"

    async def _execute_skill(self, args: dict) -> str:
        """
        Execute a workflow skill from YAML.

        This is a simplified executor - it handles common skills inline
        using the available tools. For full skill YAML execution with
        all steps, use the aa-workflow MCP server.
        """
        skill_name = args.get("skill_name", "")
        inputs = args.get("inputs", {})

        # Available skills and their descriptions
        available_skills = {
            "test_mr_ephemeral": "Deploy MR to ephemeral for testing",
            "start_work": "Begin work on Jira issue",
            "create_mr": "Create merge request",
            "review_pr": "Review a PR/MR",
            "close_issue": "Close a Jira issue",
            "debug_prod": "Debug production issues",
            "investigate_alert": "Investigate an alert",
            "jira_hygiene": "Clean up Jira issues",
            "rebase_pr": "Rebase a PR",
            "sync_branch": "Sync branch with main",
            "standup_summary": "Generate standup summary",
            "check_my_prs": "Check your PRs for feedback",
            "review_all_prs": "Review all open PRs",
            "release_aa_backend_prod": "Release AA backend to prod",
        }

        if skill_name not in available_skills:
            return f"Unknown skill: {skill_name}\n\nAvailable skills:\n" + "\n".join(
                f"- {name}: {desc}" for name, desc in available_skills.items()
            )

        # ===== test_mr_ephemeral =====
        if skill_name == "test_mr_ephemeral":
            return await self._skill_test_mr_ephemeral(inputs)

        # ===== For other skills, provide guidance on what they need =====
        # These skills exist as YAML but need the full skill runner
        skill_file = f"skills/{skill_name}.yaml"

        return f"""Skill `{skill_name}` exists but requires the full skill runner.

**What it does:** {available_skills.get(skill_name, 'Unknown')}

**Skill file:** `{skill_file}`

**For now, you can:**
1. Use the individual tools directly (jira_view, gitlab_mr_view, etc.)
2. Ask me to help with the specific task and I'll use the right tools

**Example inputs for {skill_name}:**
{json.dumps(inputs, indent=2) if inputs else "{}"}"""

    async def _skill_test_mr_ephemeral(self, inputs: dict) -> str:
        """Execute test_mr_ephemeral skill inline using bonfire tools."""
        mr_id = inputs.get("mr_id")
        commit_sha = inputs.get("commit_sha")
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
                        logger.info(f"MR {mr_id} is merged, using merge commit: {commit_sha[:12]}")

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
        system_prompt: str | None = None,
    ):
        if not ANTHROPIC_AVAILABLE:
            raise ImportError(
                "anthropic package not installed. Install with: pip install anthropic"
            )

        self.max_tokens = max_tokens
        self.system_prompt = system_prompt or self._default_system_prompt()
        self.use_vertex = False

        # Check if using Vertex AI
        use_vertex = os.getenv("CLAUDE_CODE_USE_VERTEX", "0") == "1"
        vertex_project = os.getenv("ANTHROPIC_VERTEX_PROJECT_ID")
        vertex_region = os.getenv("ANTHROPIC_VERTEX_REGION", "us-east5")

        if use_vertex and vertex_project:
            if not VERTEX_AVAILABLE:
                raise ImportError(
                    "AnthropicVertex not available. Update anthropic: pip install -U anthropic"
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

        self.tool_registry = ToolRegistry()
        self.tool_executor = ToolExecutor(PROJECT_ROOT)

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
- jira: view issues, search, add comments
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

use tools to get real data. dont guess. for jira issues like AAP-12345 use jira_view. for mr urls use gitlab_mr_view."""

    async def process_message(
        self,
        message: str,
        context: dict | None = None,
    ) -> str:
        """
        Process a message using Claude.

        1. Extract repository context from message (URLs, issue keys)
        2. Send message to Claude with available tools
        3. Claude decides what to do (maybe call tools)
        4. Execute any tool calls
        5. Return final response
        """
        messages = [{"role": "user", "content": message}]

        # Extract repository context from the message
        resolved_ctx = None
        if RESOLVER_AVAILABLE:
            try:
                resolver = ContextResolver()
                resolved_ctx = resolver.from_message(message)
            except Exception as e:
                logger.warning(f"Failed to resolve context: {e}")

        # Build context string for Claude
        context_parts = []
        if context:
            context_parts.append(
                f"User: {context.get('user_name', 'unknown')} in #{context.get('channel_name', 'unknown')}"
            )

            # Add user classification for tone adjustment
            user_category = context.get("user_category", "unknown")
            include_emojis = context.get("include_emojis", True)

            if user_category == "concerned":
                # Manager/stakeholder - be formal and careful
                context_parts.append(
                    "TONE: formal - this is a manager/stakeholder. "
                    "be professional, clear, no typos, no casual slang. skip emojis."
                )
            elif user_category == "safe":
                # Teammate - full casual mode
                context_parts.append(
                    "TONE: casual - teammate, full irish dev mode, typos ok, emojis ok"
                )
            else:
                # Unknown - balanced professional
                emoji_note = "emojis ok" if include_emojis else "skip emojis"
                context_parts.append(f"TONE: professional - clear and helpful, {emoji_note}")

        # Add resolved repo context so Claude knows what repo we're dealing with
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
            # Multiple repos match - tell Claude to ask
            repos = ", ".join(a["name"] for a in resolved_ctx.alternatives)
            context_parts.append(f"Ambiguous repo - matches: {repos}. Ask user which one.")

        if context_parts:
            context_text = "Context: " + " | ".join(context_parts)
            messages[0]["content"] = f"{context_text}\n\nMessage: {message}"

        # Get available tools
        tools = self.tool_registry.list_tools()

        # Call Claude
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=self.system_prompt,
            tools=tools,
            messages=messages,
        )

        # Process response - may need multiple rounds if Claude calls tools
        while response.stop_reason == "tool_use":
            # Extract tool calls
            tool_calls = [block for block in response.content if block.type == "tool_use"]

            # Execute tools
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

            # Continue conversation with tool results
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.system_prompt,
                tools=tools,
                messages=messages,
            )

        # Extract final text response
        final_response = ""
        for block in response.content:
            if hasattr(block, "text"):
                final_response += block.text

        return final_response or "I processed your request but have no response."


# Convenience function
async def ask_claude(message: str, context: dict | None = None) -> str:
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
