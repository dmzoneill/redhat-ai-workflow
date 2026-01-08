#!/usr/bin/env python3
"""Script to split large tool modules into basic and extra variants.

This script reads the existing tools.py files and splits them based on
predefined categorizations of which tools are "basic" (everyday use) vs
"extra" (advanced/specialized use).
"""

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
TOOL_MODULES_DIR = PROJECT_ROOT / "tool_modules"

# Define which tools go into basic vs extra for each module
# Format: module_name -> (basic_tools, extra_tools)
SPLITS = {
    "gitlab": {
        "basic": [
            "gitlab_mr_list",
            "gitlab_mr_view",
            "gitlab_mr_create",
            "gitlab_mr_update",
            "gitlab_mr_comment",
            "gitlab_mr_diff",
            "gitlab_ci_list",
            "gitlab_ci_status",
            "gitlab_ci_view",
            "gitlab_ci_run",
            "gitlab_ci_retry",
            "gitlab_ci_trace",
            "gitlab_repo_view",
            "gitlab_issue_list",
            "gitlab_issue_view",
            "gitlab_user_info",
        ],
        "extra": [
            "gitlab_mr_approve",
            "gitlab_mr_revoke",
            "gitlab_mr_merge",
            "gitlab_mr_close",
            "gitlab_mr_reopen",
            "gitlab_mr_rebase",
            "gitlab_mr_approvers",
            "gitlab_ci_cancel",
            "gitlab_ci_lint",
            "gitlab_issue_create",
            "gitlab_label_list",
            "gitlab_release_list",
            "gitlab_list_mrs",
            "gitlab_mr_comments",
        ],
    },
    "jira": {
        "basic": [
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
            "jira_get_issue",
            "jira_transition",
            "jira_ai_helper",
            "jira_show_template",
        ],
        "extra": [
            "jira_block",
            "jira_unblock",
            "jira_add_to_sprint",
            "jira_remove_sprint",
            "jira_create_issue",
            "jira_clone_issue",
            "jira_add_link",
            "jira_add_flag",
            "jira_remove_flag",
            "jira_set_summary",
            "jira_set_priority",
            "jira_set_story_points",
            "jira_set_epic",
        ],
    },
    "k8s": {
        "basic": [
            "kubectl_get_pods",
            "kubectl_describe_pod",
            "kubectl_logs",
            "kubectl_delete_pod",
            "kubectl_get_deployments",
            "kubectl_describe_deployment",
            "kubectl_rollout_status",
            "kubectl_get_services",
            "kubectl_get_events",
            "kubectl_top_pods",
            "kubectl_get",
            "k8s_namespace_health",
            "k8s_list_pods",
            "k8s_environment_summary",
        ],
        "extra": [
            "kubectl_rollout_restart",
            "kubectl_scale",
            "kubectl_get_ingress",
            "kubectl_get_configmaps",
            "kubectl_get_secrets",
            "kubectl_exec",
            "kubectl_cp",
            "kubectl_get_secret_value",
            "kubectl_saas_pipelines",
            "kubectl_saas_deployments",
            "kubectl_saas_pods",
            "kubectl_saas_logs",
            "k8s_list_deployments",
            "k8s_list_ephemeral_namespaces",
        ],
    },
    "konflux": {
        "basic": [
            "konflux_list_pipelines",
            "konflux_get_pipeline",
            "konflux_running_pipelines",
            "konflux_failed_pipelines",
            "tkn_describe_pipelinerun",
            "tkn_logs",
            "konflux_list_components",
            "konflux_list_snapshots",
            "konflux_get_snapshot",
            "konflux_list_applications",
            "konflux_status",
            "konflux_get_application",
            "konflux_get_component",
            "konflux_namespace_summary",
            "tkn_pipelinerun_list",
            "tkn_pipelinerun_describe",
            "tkn_pipelinerun_logs",
            "tkn_pipelinerun_cancel",
        ],
        "extra": [
            "konflux_list_integration_tests",
            "konflux_get_test_results",
            "konflux_list_releases",
            "konflux_get_release",
            "konflux_list_release_plans",
            "konflux_list_builds",
            "konflux_get_build_logs",
            "konflux_list_environments",
            "tkn_pipelinerun_delete",
            "tkn_taskrun_list",
            "tkn_taskrun_describe",
            "tkn_taskrun_logs",
            "tkn_pipeline_list",
            "tkn_pipeline_describe",
            "tkn_pipeline_start",
            "tkn_task_list",
            "tkn_task_describe",
        ],
    },
    "bonfire": {
        "basic": [
            "bonfire_namespace_reserve",
            "bonfire_namespace_list",
            "bonfire_namespace_describe",
            "bonfire_namespace_release",
            "bonfire_namespace_extend",
            "bonfire_namespace_wait",
            "bonfire_apps_list",
            "bonfire_apps_dependencies",
            "bonfire_pool_list",
            "bonfire_deploy",
        ],
        "extra": [
            "bonfire_deploy_with_reserve",
            "bonfire_process",
            "bonfire_deploy_env",
            "bonfire_process_env",
            "bonfire_deploy_iqe_cji",
            "bonfire_process_iqe_cji",
            "bonfire_deploy_aa",
            "bonfire_deploy_aa_local",
            "bonfire_full_test_workflow",
            "bonfire_deploy_aa_from_snapshot",
        ],
    },
    "prometheus": {
        "basic": [
            "prometheus_query",
            "prometheus_alerts",
            "prometheus_get_alerts",
            "prometheus_check_health",
            "prometheus_targets",
            "prometheus_namespace_metrics",
            "prometheus_error_rate",
            "prometheus_pod_health",
        ],
        "extra": [
            "prometheus_query_range",
            "prometheus_pre_deploy_check",
            "prometheus_rules",
            "prometheus_labels",
            "prometheus_series",
        ],
    },
}


def extract_function_code(content: str, func_name: str) -> str | None:
    """Extract a function definition from the content."""
    # Find the decorator + function pattern - handles various @auto_heal variants
    # Also handles functions that may span to another decorator or end of file
    pattern = rf"(\s*@auto_heal[^\n]*\n\s*@registry\.tool\(\).*?\n\s*async def {func_name}\(.*?(?=\n\s*@auto_heal|\n\s*return registry\.count|\Z))"
    match = re.search(pattern, content, re.DOTALL)
    if match:
        return match.group(1).rstrip()
    return None


def get_module_header(module_name: str, variant: str, tool_count: int, tool_list: list[str]) -> str:
    """Generate the header for a tools file."""
    if variant == "basic":
        desc = f"{module_name.capitalize()} Basic Tools - Essential {module_name} operations."
        detail = f"For advanced operations, see tools_extra.py."
    else:
        desc = f"{module_name.capitalize()} Extra Tools - Advanced {module_name} operations."
        detail = f"For basic operations, see tools_basic.py."

    tools_str = ", ".join(tool_list[:5]) + (", ..." if len(tool_list) > 5 else "")

    return f'''"""{desc}

{detail}

Tools included (~{tool_count}):
- {tools_str}
"""
'''


def split_module(module_name: str):
    """Split a module into basic and extra variants."""
    if module_name not in SPLITS:
        print(f"No split definition for {module_name}")
        return

    module_dir = TOOL_MODULES_DIR / f"aa_{module_name}"
    tools_file = module_dir / "src" / "tools.py"

    if not tools_file.exists():
        print(f"Tools file not found: {tools_file}")
        return

    content = tools_file.read_text()
    split_config = SPLITS[module_name]

    for variant in ["basic", "extra"]:
        tools = split_config[variant]
        output_file = module_dir / "src" / f"tools_{variant}.py"

        # Extract the imports and helper functions (everything before register_tools)
        # Skip the first docstring to avoid duplication
        header_match = re.search(r"^(.*?)(def register_tools)", content, re.DOTALL)
        if not header_match:
            print(f"Could not find register_tools in {module_name}")
            continue

        imports_section = header_match.group(1)
        # Remove the original module docstring (first triple-quoted string)
        imports_section = re.sub(r'^""".*?"""', "", imports_section, count=1, flags=re.DOTALL).strip()

        # Build the new file
        new_content = get_module_header(module_name, variant, len(tools), tools)
        new_content += imports_section.strip() + "\n\n\n"
        new_content += f'def register_tools(server: FastMCP) -> int:\n    """Register {variant} {module_name} tools with the MCP server."""\n    registry = ToolRegistry(server)\n\n'

        # Extract each function
        for func_name in tools:
            func_code = extract_function_code(content, func_name)
            if func_code:
                new_content += func_code + "\n\n"
            else:
                print(f"  Warning: Could not extract {func_name} from {module_name}")

        new_content += "    return registry.count\n"

        # Write the file
        output_file.write_text(new_content)
        print(f"Created {output_file.relative_to(PROJECT_ROOT)}")


def main():
    """Split all configured modules."""
    for module_name in SPLITS:
        print(f"\nSplitting {module_name}...")
        split_module(module_name)

    print("\n✅ Done! Remember to update personas to use _basic/_extra variants.")


if __name__ == "__main__":
    main()
