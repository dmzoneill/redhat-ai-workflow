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
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import anthropic
    from anthropic import AnthropicVertex

    ANTHROPIC_AVAILABLE = True
    VERTEX_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    VERTEX_AVAILABLE = False
    AnthropicVertex = None

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
                description="View a Jira issue by key (e.g., AAP-12345). Returns issue details including summary, status, assignee, and description.",
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

        # GitLab tools
        self.register(
            ToolDefinition(
                name="gitlab_mr_view",
                description="View a GitLab Merge Request by ID. Returns MR details including title, status, author, and changes.",
                parameters={
                    "type": "object",
                    "properties": {
                        "mr_id": {
                            "type": "string",
                            "description": "Merge Request ID (e.g., 123 or !123)",
                        }
                    },
                    "required": ["mr_id"],
                },
            )
        )

        self.register(
            ToolDefinition(
                name="gitlab_mr_list",
                description="List open Merge Requests, optionally filtered by author.",
                parameters={
                    "type": "object",
                    "properties": {
                        "author": {
                            "type": "string",
                            "description": "Filter by author username (optional)",
                        },
                        "state": {
                            "type": "string",
                            "description": "MR state: opened, merged, closed, all",
                            "default": "opened",
                        },
                    },
                    "required": [],
                },
            )
        )

        self.register(
            ToolDefinition(
                name="gitlab_pipeline_status",
                description="Get the CI/CD pipeline status for a Merge Request.",
                parameters={
                    "type": "object",
                    "properties": {"mr_id": {"type": "string", "description": "Merge Request ID"}},
                    "required": ["mr_id"],
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

        # Skill tools
        self.register(
            ToolDefinition(
                name="skill_run",
                description="Run a workflow skill. Available skills: start_work, create_mr, review_pr, jira_hygiene, debug_prod, close_issue, sync_branch, rebase_pr, standup_summary",
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
    """

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.rh_issue = os.getenv("RH_ISSUE_CLI", "rh-issue")

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
            elif tool_name == "skill_run":
                return await self._execute_skill(arguments)
            else:
                return f"Unknown tool: {tool_name}"
        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            return f"Error executing {tool_name}: {str(e)}"

    async def _run_command(self, cmd: list[str], cwd: str | None = None) -> str:
        """Run a shell command and return output."""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=cwd or str(self.project_root),
            )
            output = result.stdout
            if result.returncode != 0 and result.stderr:
                output += f"\nError: {result.stderr}"
            return output.strip() or "(no output)"
        except subprocess.TimeoutExpired:
            return "Command timed out after 60 seconds"
        except Exception as e:
            return f"Command failed: {e}"

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
        """Execute GitLab tools via glab CLI."""
        if tool_name == "gitlab_mr_view":
            mr_id = args.get("mr_id", "").lstrip("!")
            return await self._run_command(["glab", "mr", "view", mr_id])
        elif tool_name == "gitlab_mr_list":
            cmd = ["glab", "mr", "list"]
            if args.get("author"):
                cmd.extend(["--author", args["author"]])
            state = args.get("state", "opened")
            cmd.extend(["--state", state])
            return await self._run_command(cmd)
        elif tool_name == "gitlab_pipeline_status":
            mr_id = args.get("mr_id", "").lstrip("!")
            return await self._run_command(["glab", "mr", "view", mr_id, "--web"])
        return f"Unknown GitLab tool: {tool_name}"

    async def _execute_git(self, tool_name: str, args: dict) -> str:
        """Execute Git tools."""
        repo_path = args.get("repo_path", str(self.project_root))

        if tool_name == "git_status":
            return await self._run_command(["git", "status", "-sb"], cwd=repo_path)
        elif tool_name == "git_log":
            count = args.get("count", 10)
            return await self._run_command(["git", "log", f"-{count}", "--oneline"], cwd=repo_path)
        return f"Unknown Git tool: {tool_name}"

    async def _execute_k8s(self, tool_name: str, args: dict) -> str:
        """Execute Kubernetes tools via kubectl."""
        namespace = args.get("namespace", "")

        if tool_name == "k8s_get_pods":
            return await self._run_command(["kubectl", "get", "pods", "-n", namespace])
        elif tool_name == "k8s_get_events":
            return await self._run_command(
                ["kubectl", "get", "events", "-n", namespace, "--sort-by=.lastTimestamp"]
            )
        elif tool_name == "k8s_logs":
            pod = args.get("pod", "")
            tail = args.get("tail", 100)
            return await self._run_command(
                ["kubectl", "logs", "-n", namespace, pod, f"--tail={tail}"]
            )
        return f"Unknown K8s tool: {tool_name}"

    async def _execute_skill(self, args: dict) -> str:
        """Execute a workflow skill."""
        skill_name = args.get("skill_name", "")
        inputs = args.get("inputs", {})

        # For now, return info about the skill
        # In full implementation, this would load and run the skill YAML
        return f"Skill '{skill_name}' would be executed with inputs: {json.dumps(inputs)}"


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
        max_tokens: int = 4096,
        system_prompt: str | None = None,
    ):
        if not ANTHROPIC_AVAILABLE:
            raise ImportError(
                "anthropic package not installed. Install with: pip install anthropic"
            )

        self.model = model
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
            logger.info(f"Using Vertex AI: project={vertex_project}, region={vertex_region}")
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
            logger.info("Using direct Anthropic API")

        self.tool_registry = ToolRegistry()
        self.tool_executor = ToolExecutor(PROJECT_ROOT)

    def _default_system_prompt(self) -> str:
        return """You are an AI assistant helping with software development workflows. 
You have access to tools for:
- Jira: View issues, search, add comments
- GitLab: View MRs, list MRs, check pipelines
- Git: Check status, view logs
- Kubernetes: Get pods, events, logs
- Skills: Run workflow automations

When users ask questions, use the appropriate tools to gather information and help them.
Be concise and format responses for Slack (use *bold*, `code`, and bullet points).

Always call tools when you can provide real data instead of generic advice.
For Jira issues like AAP-12345, use jira_view to get real details.
For MRs like !123, use gitlab_mr_view to get real status."""

    async def process_message(
        self,
        message: str,
        context: dict | None = None,
    ) -> str:
        """
        Process a message using Claude.

        1. Send message to Claude with available tools
        2. Claude decides what to do (maybe call tools)
        3. Execute any tool calls
        4. Return final response
        """
        messages = [{"role": "user", "content": message}]

        # Add context if provided
        if context:
            context_text = f"Context: User is {context.get('user_name', 'unknown')} in #{context.get('channel_name', 'unknown')}"
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
    # Test the agent
    import asyncio

    async def test():
        agent = ClaudeAgent()

        # Test with a simple query
        response = await agent.process_message(
            "What's the status of AAP-12345?",
            context={"user_name": "testuser", "channel_name": "test"},
        )
        print(response)

    asyncio.run(test())
