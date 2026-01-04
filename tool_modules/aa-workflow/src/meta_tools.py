"""Meta Tools - Dynamic tool discovery and execution.

Provides tools for:
- tool_list: List all available tools across modules
- tool_exec: Execute any tool from any module dynamically
"""

import importlib.util
import json
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Add aa-common to path for shared utilities
SERVERS_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(SERVERS_DIR / "aa-common"))

# Tool counts per module - for discovery
TOOL_REGISTRY = {
    "git": [
        "git_status",
        "git_branch_list",
        "git_branch_create",
        "git_checkout",
        "git_log",
        "git_diff",
        "git_add",
        "git_commit",
        "git_push",
        "git_pull",
        "git_stash",
        "git_fetch",
        "git_merge",
        "git_rebase",
        "git_remote",
    ],
    "jira": [
        "jira_view_issue",
        "jira_view_issue_json",
        "jira_search",
        "jira_list_issues",
        "jira_my_issues",
        "jira_list_blocked",
        "jira_lint",
        "jira_set_status",
        "jira_assign",
        "jira_unassign",
        "jira_add_comment",
        "jira_block",
        "jira_unblock",
        "jira_add_to_sprint",
        "jira_remove_sprint",
        "jira_create_issue",
        "jira_clone_issue",
        "jira_add_link",
        "jira_add_flag",
        "jira_remove_flag",
        "jira_open_browser",
    ],
    "gitlab": [
        "gitlab_mr_list",
        "gitlab_mr_view",
        "gitlab_mr_create",
        "gitlab_mr_update",
        "gitlab_mr_approve",
        "gitlab_mr_revoke",
        "gitlab_mr_merge",
        "gitlab_mr_close",
        "gitlab_mr_reopen",
        "gitlab_mr_comment",
        "gitlab_mr_diff",
        "gitlab_mr_rebase",
        "gitlab_mr_checkout",
        "gitlab_mr_approvers",
        "gitlab_ci_list",
        "gitlab_ci_status",
        "gitlab_ci_view",
        "gitlab_ci_run",
        "gitlab_ci_retry",
        "gitlab_ci_cancel",
        "gitlab_ci_trace",
        "gitlab_ci_lint",
        "gitlab_repo_view",
        "gitlab_repo_clone",
        "gitlab_issue_list",
        "gitlab_issue_view",
        "gitlab_issue_create",
        "gitlab_label_list",
        "gitlab_release_list",
        "gitlab_user_info",
    ],
    "k8s": [
        "kubectl_get_pods",
        "kubectl_describe_pod",
        "kubectl_logs",
        "kubectl_delete_pod",
        "kubectl_get_deployments",
        "kubectl_describe_deployment",
        "kubectl_rollout_status",
        "kubectl_rollout_restart",
        "kubectl_scale",
        "kubectl_get_services",
        "kubectl_get_events",
        "kubectl_get",
        "kubectl_exec",
        "kubectl_top_pods",
    ],
    "prometheus": [
        "prometheus_query",
        "prometheus_query_range",
        "prometheus_alerts",
        "prometheus_rules",
        "prometheus_targets",
        "prometheus_labels",
        "prometheus_series",
        "prometheus_namespace_metrics",
        "prometheus_error_rate",
        "prometheus_pod_health",
        "prometheus_grafana_link",
    ],
    "alertmanager": [
        "alertmanager_silences",
        "alertmanager_create_silence",
        "alertmanager_delete_silence",
        "alertmanager_status",
        "alertmanager_alerts",
    ],
    "kibana": [
        "kibana_search_logs",
        "kibana_get_errors",
        "kibana_get_pod_logs",
        "kibana_trace_request",
        "kibana_get_link",
        "kibana_error_link",
        "kibana_status",
        "kibana_index_patterns",
        "kibana_list_dashboards",
    ],
    "konflux": [
        "konflux_list_applications",
        "konflux_get_application",
        "konflux_list_components",
        "konflux_get_component",
        "konflux_list_snapshots",
        "konflux_get_snapshot",
        "konflux_list_integration_tests",
        "konflux_get_test_results",
        "konflux_list_releases",
        "konflux_get_release",
        "konflux_list_release_plans",
        "konflux_list_builds",
        "konflux_get_build_logs",
        "konflux_list_environments",
        "konflux_namespace_summary",
    ],
    "bonfire": [
        "bonfire_version",
        "bonfire_namespace_reserve",
        "bonfire_namespace_list",
        "bonfire_namespace_describe",
        "bonfire_namespace_release",
        "bonfire_namespace_extend",
        "bonfire_namespace_wait",
        "bonfire_apps_list",
        "bonfire_apps_dependencies",
        "bonfire_deploy",
        "bonfire_deploy_with_reserve",
        "bonfire_process",
        "bonfire_deploy_env",
        "bonfire_process_env",
        "bonfire_deploy_iqe_cji",
        "bonfire_pool_list",
        "bonfire_deploy_aa",
    ],
    "quay": [
        "quay_get_repository",
        "quay_list_tags",
        "quay_get_tag",
        "quay_check_image_exists",
        "quay_get_vulnerabilities",
        "quay_get_manifest",
        "quay_check_aa_image",
        "quay_list_aa_tags",
    ],
    "appinterface": [
        "appinterface_validate",
        "appinterface_get_saas",
        "appinterface_diff",
        "appinterface_resources",
        "appinterface_search",
        "appinterface_clusters",
    ],
}

# Module prefix mapping
MODULE_PREFIXES = {
    "git_": "git",
    "jira_": "jira",
    "gitlab_": "gitlab",
    "kubectl_": "k8s",
    "k8s_": "k8s",
    "prometheus_": "prometheus",
    "alertmanager_": "alertmanager",
    "kibana_": "kibana",
    "konflux_": "konflux",
    "tkn_": "konflux",
    "bonfire_": "bonfire",
    "quay_": "quay",
    "appinterface_": "appinterface",
    "workflow_": "workflow",
    "lint_": "workflow",
    "test_": "workflow",
    "security_": "workflow",
    "precommit_": "workflow",
    "memory_": "workflow",
    "agent_": "workflow",
    "skill_": "workflow",
    "session_": "workflow",
    "tool_": "workflow",
}


def register_meta_tools(server: "FastMCP", create_issue_fn=None) -> int:
    """Register meta tools with the MCP server."""
    tool_count = 0

    @server.tool()
    async def tool_list(module: str = "") -> list[TextContent]:
        """
        List all available tools across all modules.

        Use this to discover tools that aren't directly loaded.
        Then use tool_exec() to run them.

        Args:
            module: Filter by module (git, jira, gitlab, k8s, etc.)
                   Leave empty to list all modules.

        Returns:
            List of available tools and their descriptions.
        """
        if module:
            if module not in TOOL_REGISTRY:
                return [
                    TextContent(
                        type="text",
                        text=f"❌ Unknown module: {module}\n\n" f"Available: {', '.join(TOOL_REGISTRY.keys())}",
                    )
                ]

            tools = TOOL_REGISTRY[module]
            lines = [f"## Module: {module}\n", f"**{len(tools)} tools available:**\n"]
            for t in tools:
                lines.append(f"- `{t}`")
            lines.append(f"\n*Use `tool_exec('{tools[0]}', '{{}}')` to run*")
            return [TextContent(type="text", text="\n".join(lines))]

        # List all modules
        lines = ["## Available Tool Modules\n"]
        total = 0
        for mod, tools in TOOL_REGISTRY.items():
            lines.append(f"- **{mod}**: {len(tools)} tools")
            total += len(tools)
        lines.append(f"\n**Total: {total} tools**")
        lines.append("\nUse `tool_list(module='git')` to see tools in a module")
        lines.append("\n**💡 TIP:** After loading an agent, call tools DIRECTLY by name:")
        lines.append("   `bonfire_namespace_list(mine_only=True)`  ← Cursor shows actual name")
        lines.append("   NOT: `tool_exec('bonfire_namespace_list', ...)`  ← Shows as 'tool_exec'")
        lines.append("\nUse `tool_exec()` only for tools from non-loaded agents.")

        return [TextContent(type="text", text="\n".join(lines))]

    tool_count += 1

    @server.tool()
    async def tool_exec(tool_name: str, args: str = "{}") -> list[TextContent]:
        """
        Execute ANY tool from ANY module dynamically.

        This is a meta-tool that can run tools not directly loaded.
        First use tool_list() to see available tools.

        Args:
            tool_name: Full tool name (e.g., "gitlab_mr_list", "kibana_search_logs")
            args: JSON string of arguments (e.g., '{"project": "backend", "state": "opened"}')

        Returns:
            Tool execution result.

        Example:
            tool_exec("gitlab_mr_list", '{"project": "your-backend"}')
        """
        # Determine which module the tool belongs to
        module = None
        for prefix, mod in MODULE_PREFIXES.items():
            if tool_name.startswith(prefix):
                module = mod
                break

        if not module:
            return [
                TextContent(
                    type="text",
                    text=f"❌ Unknown tool: {tool_name}\n\nUse tool_list() to see available tools.",
                )
            ]

        # Parse arguments
        try:
            tool_args = json.loads(args) if args else {}
        except json.JSONDecodeError as e:
            return [TextContent(type="text", text=f"❌ Invalid JSON args: {e}")]

        # Load and execute the tool module
        tools_file = SERVERS_DIR / f"aa-{module}" / "src" / "tools.py"

        if not tools_file.exists():
            return [TextContent(type="text", text=f"❌ Module not found: {module}")]

        try:
            # Create a temporary server to register tools
            temp_server = FastMCP(f"temp-{module}")

            # Load the module
            spec = importlib.util.spec_from_file_location(f"aa_{module}_tools_exec", tools_file)
            if spec is None or spec.loader is None:
                return [TextContent(type="text", text=f"❌ Could not load module: {module}")]

            loaded_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(loaded_module)

            # Register tools with temp server
            if hasattr(loaded_module, "register_tools"):
                loaded_module.register_tools(temp_server)

            # Execute the tool
            result = await temp_server.call_tool(tool_name, tool_args)

            # Extract text from result
            if isinstance(result, tuple):
                result = result[0]
            if isinstance(result, list) and len(result) > 0:
                if hasattr(result[0], "text"):
                    return [TextContent(type="text", text=result[0].text)]
                return [TextContent(type="text", text=str(result[0]))]

            return [TextContent(type="text", text=str(result))]

        except Exception as e:
            error_msg = str(e)
            lines = [f"❌ Error executing {tool_name}: {error_msg}"]

            # Auto-create GitHub issue for all tool failures
            if create_issue_fn:
                try:
                    issue_result = await create_issue_fn(tool=tool_name, error=error_msg, context=f"Args: {args}")

                    if issue_result["success"]:
                        lines.append("")
                        lines.append(f"🐛 **Issue created:** {issue_result['issue_url']}")
                    elif issue_result["issue_url"]:
                        lines.append("")
                        lines.append("💡 **Report this error:**")
                        lines.append(f"📝 [Create GitHub Issue]({issue_result['issue_url']})")
                except Exception as issue_err:
                    logger.debug(f"Failed to create GitHub issue: {issue_err}")

            return [TextContent(type="text", text="\n".join(lines))]

    tool_count += 1

    return tool_count
