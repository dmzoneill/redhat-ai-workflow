#!/usr/bin/env python3
"""Update specific tool calls in a skill to use auto_heal.

This script is more surgical than a blanket sed replacement.
It only converts specific tools that benefit from auto-heal.
"""

import re
from pathlib import Path

# Tools that should use auto_heal (infrastructure/API tools that may need auth)
AUTO_HEAL_TOOLS = {
    # Jira tools
    "jira_view_issue",
    "jira_get_issue",
    "jira_set_status",
    "jira_transition",
    "jira_assign",
    "jira_add_comment",
    "jira_search",
    "jira_list_issues",
    "jira_my_issues",
    # GitLab tools
    "gitlab_mr_list",
    "gitlab_mr_view",
    "gitlab_mr_comments",
    "gitlab_mr_create",
    "gitlab_mr_diff",
    "gitlab_mr_sha",
    "gitlab_ci_status",
    "gitlab_ci_list",
    "gitlab_ci_view",
    "gitlab_ci_trace",
    # Git remote tools
    "git_fetch",
    "git_push",
    "git_pull",
    # K8s tools
    "kubectl_get_pods",
    "kubectl_get_deployments",
    "kubectl_get_events",
    "kubectl_get_secret_value",
    "kubectl_describe_pod",
    "kubectl_logs",
    "kubectl_rollout_restart",
    "kubectl_scale",
    "kubectl_get",
    # Bonfire tools
    "bonfire_namespace_reserve",
    "bonfire_namespace_wait",
    "bonfire_namespace_list",
    "bonfire_deploy",
    "bonfire_deploy_aa",
    # Konflux tools
    "konflux_list_snapshots",
    "konflux_get_snapshot",
    "konflux_get_build_logs",
    "konflux_list_integration_tests",
    "konflux_get_test_results",
    # Tekton tools
    "tkn_pipelinerun_list",
    "tkn_pipelinerun_describe",
    "tkn_pipelinerun_logs",
    "tkn_taskrun_list",
    # Monitoring tools
    "prometheus_query",
    "alertmanager_alerts",
    "alertmanager_silence",
    "kibana_search_logs",
    # Quay tools
    "quay_check_image_exists",
    "skopeo_get_digest",
    # Slack tools
    "slack_post_message",
    "slack_list_channels",
    # App interface
    "appinterface_get_saas",
    "appinterface_diff",
    "appinterface_resources",
    "appinterface_validate",
}

# Comment hints for each tool category
TOOL_HINTS = {
    "jira_": "Jira API - may need auth refresh",
    "gitlab_": "GitLab API - may need auth refresh",
    "git_fetch": "Git remote - may need auth/network",
    "git_push": "Git remote - may need auth/network",
    "git_pull": "Git remote - may need auth/network",
    "kubectl_": "K8s cluster - may need kube_login",
    "bonfire_": "Ephemeral cluster - may need kube_login",
    "konflux_": "Konflux cluster - may need kube_login",
    "tkn_": "Tekton/Konflux - may need kube_login",
    "prometheus_": "Prometheus - may need auth",
    "alertmanager_": "Alertmanager - may need auth",
    "kibana_": "Kibana - may need auth",
    "quay_": "Quay API - may need auth",
    "skopeo_": "Quay API - may need auth",
    "slack_": "Slack API - may need auth",
    "appinterface_": "App Interface - may need auth",
}


def get_hint(tool_name: str) -> str:
    """Get the appropriate hint for a tool."""
    for prefix, hint in TOOL_HINTS.items():
        if tool_name.startswith(prefix):
            return hint
    return "API call - may need auth"


def update_skill_file(filepath: Path, dry_run: bool = True) -> dict:
    """Update a skill file to use auto_heal for appropriate tools.

    Returns:
        dict with counts of changes made
    """
    content = filepath.read_text()
    lines = content.split("\n")

    changes = {
        "file": filepath.name,
        "converted": 0,
        "kept": 0,
        "tools_converted": [],
        "tools_kept": [],
    }

    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # Look for tool: lines
        tool_match = re.match(r"(\s*)tool:\s*(\w+)", line)
        if tool_match:
            tool_name = tool_match.group(2)

            # Look ahead for on_error: continue
            j = i + 1
            found_on_error = False
            on_error_line_idx = -1

            while j < len(lines) and j < i + 10:  # Look within next 10 lines
                next_line = lines[j]

                # Stop if we hit another step (- name:)
                if re.match(r"\s*-\s*name:", next_line):
                    break

                # Check for on_error: continue
                if re.match(r"\s*on_error:\s*continue\s*$", next_line):
                    found_on_error = True
                    on_error_line_idx = j
                    break

                j += 1

            if found_on_error and tool_name in AUTO_HEAL_TOOLS:
                # Convert this one
                hint = get_hint(tool_name)
                new_lines.append(line)

                # Copy lines until on_error
                for k in range(i + 1, on_error_line_idx):
                    new_lines.append(lines[k])

                # Replace on_error line
                on_error_indent = re.match(r"(\s*)", lines[on_error_line_idx]).group(1)
                new_lines.append(f"{on_error_indent}on_error: auto_heal  # {hint}")

                changes["converted"] += 1
                changes["tools_converted"].append(tool_name)

                i = on_error_line_idx + 1
                continue
            elif found_on_error:
                changes["kept"] += 1
                changes["tools_kept"].append(tool_name)

        new_lines.append(line)
        i += 1

    if not dry_run and changes["converted"] > 0:
        filepath.write_text("\n".join(new_lines))

    return changes


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Update skill error handling")
    parser.add_argument("--apply", action="store_true", help="Actually apply changes")
    parser.add_argument("--file", type=str, help="Process single file")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show details")
    args = parser.parse_args()

    skills_dir = Path(__file__).parent.parent / "skills"

    if args.file:
        files = [Path(args.file)]
    else:
        files = sorted(skills_dir.glob("*.yaml"))

    total_converted = 0
    total_kept = 0

    print(f"{'DRY RUN - ' if not args.apply else ''}Processing {len(files)} skill files...\n")

    for filepath in files:
        if filepath.name.startswith("_"):
            continue

        changes = update_skill_file(filepath, dry_run=not args.apply)

        if changes["converted"] > 0 or args.verbose:
            print(f"📄 {changes['file']}")
            if changes["converted"] > 0:
                print(f"   ✅ Converted to auto_heal: {changes['converted']}")
                if args.verbose:
                    for tool in set(changes["tools_converted"]):
                        count = changes["tools_converted"].count(tool)
                        print(f"      - {tool} ({count}x)")
            if changes["kept"] > 0 and args.verbose:
                print(f"   ⏭️  Kept as continue: {changes['kept']}")

        total_converted += changes["converted"]
        total_kept += changes["kept"]

    print(f"\n{'=' * 50}")
    print(f"Total converted to auto_heal: {total_converted}")
    print(f"Total kept as continue: {total_kept}")

    if not args.apply and total_converted > 0:
        print("\n💡 Run with --apply to make changes")


if __name__ == "__main__":
    main()
