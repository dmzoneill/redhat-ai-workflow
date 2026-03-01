"""Tool registry and definitions for Claude Agent."""

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

PROJECT_ROOT = Path(__file__).parent.parent

try:
    sys.path.insert(0, str(PROJECT_ROOT / "tool_modules" / "aa_workflow" / "src"))
    sys.path.insert(0, str(PROJECT_ROOT))
    import yaml as skill_yaml

    SKILL_EXECUTOR_AVAILABLE = True
    SKILLS_DIR = Path(__file__).parent.parent / "skills"
except ImportError:
    SKILL_EXECUTOR_AVAILABLE = False
    skill_yaml = None
    SKILLS_DIR = None

logger = logging.getLogger(__name__)


def _get_available_skills_description() -> str:
    """Dynamically build skill list from skills/ directory."""
    if not SKILLS_DIR or not SKILLS_DIR.exists():
        return "Skills directory not available."

    skills = []
    for f in sorted(SKILLS_DIR.glob("*.yaml")):
        try:
            with open(f, encoding="utf-8") as fp:
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


__all__ = [
    "ToolDefinition",
    "ToolCall",
    "ToolResult",
    "ToolRegistry",
    "PROJECT_ROOT",
]
