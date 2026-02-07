"""Default mock response generator for skill testing.

Provides realistic mock responses for all tool families so that skills
can be executed end-to-end without hitting real services.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Specific tool overrides (exact tool name match takes priority)
# ---------------------------------------------------------------------------
SPECIFIC_TOOLS: dict[str, dict] = {
    # Jira
    "jira_view_issue": {
        "success": True,
        "result": (
            "AAP-12345: Improve billing calculation accuracy\n"
            "Status: In Progress | Priority: High | Type: Story\n"
            "Assignee: testuser@redhat.com\n"
            "Sprint: Sprint 42\n"
            "Description: Update the billing module to handle vCPU fractional hours."
        ),
        "duration": 0.45,
    },
    "jira_search": {
        "success": True,
        "result": (
            "Found 3 issues:\n"
            "1. AAP-12345 - Improve billing calculation accuracy [In Progress]\n"
            "2. AAP-12346 - Fix timezone handling in reports [Open]\n"
            "3. AAP-12347 - Add retry logic to API client [Code Review]"
        ),
        "duration": 0.62,
    },
    "jira_set_status": {
        "success": True,
        "result": "AAP-12345 status updated to In Progress",
        "duration": 0.38,
    },
    "jira_add_comment": {
        "success": True,
        "result": "Comment added to AAP-12345",
        "duration": 0.30,
    },
    "jira_create_issue": {
        "success": True,
        "result": "Created AAP-12348: New issue",
        "duration": 0.55,
    },
    # GitLab
    "gitlab_mr_list": {
        "success": True,
        "result": (
            "Open MRs for automation-analytics-backend:\n"
            "1. !789 - feat(billing): improve vCPU calculation [WIP]\n"
            "2. !790 - fix(api): handle timeout errors [Ready]\n"
            "3. !791 - chore(deps): bump dependencies [Ready]"
        ),
        "duration": 0.50,
    },
    "gitlab_mr_view": {
        "success": True,
        "result": (
            "MR !789: feat(billing): improve vCPU calculation\n"
            "Author: testuser | Status: open | Pipeline: passed\n"
            "Branch: AAP-12345-billing-calc -> main\n"
            "Changes: 5 files, +120 -45"
        ),
        "duration": 0.40,
    },
    "gitlab_mr_comments": {
        "success": True,
        "result": "No comments on MR !789",
        "duration": 0.35,
    },
    "gitlab_ci_status": {
        "success": True,
        "result": "Pipeline #456789: passed (4m 32s)\nAll 12 jobs succeeded.",
        "duration": 0.42,
    },
    "gitlab_project_info": {
        "success": True,
        "result": (
            "Project: automation-analytics/automation-analytics-backend\n"
            "Default branch: main\n"
            "Open MRs: 5 | Open Issues: 12"
        ),
        "duration": 0.38,
    },
    # Git
    "git_status": {
        "success": True,
        "result": (
            "On branch AAP-12345-billing-calc\n"
            "Your branch is up to date with 'origin/AAP-12345-billing-calc'.\n\n"
            "nothing to commit, working tree clean"
        ),
        "duration": 0.05,
    },
    "git_branch_list": {
        "success": True,
        "result": ("* AAP-12345-billing-calc\n" "  main\n" "  AAP-12300-old-feature"),
        "duration": 0.04,
    },
    "git_branch_create": {
        "success": True,
        "result": "Created branch AAP-12345-billing-calc from main",
        "duration": 0.08,
    },
    "git_checkout": {
        "success": True,
        "result": "Switched to branch 'AAP-12345-billing-calc'",
        "duration": 0.06,
    },
    "git_fetch": {
        "success": True,
        "result": "Fetched from origin",
        "duration": 0.15,
    },
    "git_pull": {
        "success": True,
        "result": "Already up to date.",
        "duration": 0.10,
    },
    "git_log": {
        "success": True,
        "result": (
            "abc1234 feat(billing): add fractional hour support\n"
            "def5678 fix(billing): correct rounding error\n"
            "ghi9012 chore: update test fixtures"
        ),
        "duration": 0.04,
    },
    "git_diff": {
        "success": True,
        "result": "No differences found.",
        "duration": 0.03,
    },
    "git_remote": {
        "success": True,
        "result": "origin\tgit@gitlab.cee.redhat.com:automation-analytics/automation-analytics-backend.git (fetch)",
        "duration": 0.02,
    },
    # Kubernetes
    "kubectl_get_pods": {
        "success": True,
        "result": (
            "NAME                              READY   STATUS    RESTARTS   AGE\n"
            "aa-backend-api-6f8b4d7c9-x2j4k   1/1     Running   0          2d\n"
            "aa-backend-api-6f8b4d7c9-m8n3p    1/1     Running   0          2d\n"
            "aa-backend-worker-5c9d8e7f1-q7w2  1/1     Running   0          2d"
        ),
        "duration": 0.80,
    },
    "kubectl_get_deployments": {
        "success": True,
        "result": (
            "NAME              READY   UP-TO-DATE   AVAILABLE   AGE\n"
            "aa-backend-api    2/2     2            2           30d\n"
            "aa-backend-worker 1/1     1            1           30d"
        ),
        "duration": 0.75,
    },
    "kubectl_logs": {
        "success": True,
        "result": "2024-01-15 10:30:00 INFO  Application started successfully",
        "duration": 0.60,
    },
    # Bonfire
    "bonfire_namespace_list": {
        "success": True,
        "result": "ephemeral-abc123 (reserved by testuser, expires in 2h)",
        "duration": 0.55,
    },
    "bonfire_namespace_reserve": {
        "success": True,
        "result": "Reserved namespace: ephemeral-xyz789 (duration: 4h)",
        "duration": 2.50,
    },
    "bonfire_deploy_aa": {
        "success": True,
        "result": "Deployed automation-analytics to ephemeral-xyz789",
        "duration": 5.00,
    },
    "bonfire_apps_list": {
        "success": True,
        "result": "automation-analytics\nautomation-hub\ninsights-dashboard",
        "duration": 0.45,
    },
    # Memory / workflow
    "memory_read": {
        "success": True,
        "result": "OK",
        "duration": 0.02,
    },
    "memory_write": {
        "success": True,
        "result": "OK",
        "duration": 0.03,
    },
    "memory_update": {
        "success": True,
        "result": "OK",
        "duration": 0.02,
    },
    "memory_append": {
        "success": True,
        "result": "OK",
        "duration": 0.02,
    },
    "memory_session_log": {
        "success": True,
        "result": "OK",
        "duration": 0.02,
    },
    "memory_ask": {
        "success": True,
        "result": "No relevant results found.",
        "duration": 0.15,
    },
    "memory_search": {
        "success": True,
        "result": "No results found.",
        "duration": 0.12,
    },
    "persona_load": {
        "success": True,
        "result": "Persona 'developer' loaded successfully.",
        "duration": 0.10,
    },
    "persona_list": {
        "success": True,
        "result": "Available personas: developer, devops, incident, release",
        "duration": 0.05,
    },
    "skill_list": {
        "success": True,
        "result": "126 skills available",
        "duration": 0.08,
    },
    "skill_run": {
        "success": True,
        "result": "Skill completed successfully.",
        "duration": 1.00,
    },
    "session_start": {
        "success": True,
        "result": "Session started: abc123",
        "duration": 0.15,
    },
    # Knowledge / code search
    "check_known_issues": {
        "success": True,
        "result": "No known issues found.",
        "duration": 0.05,
    },
    "learn_tool_fix": {
        "success": True,
        "result": "Fix learned and saved.",
        "duration": 0.04,
    },
    "code_search": {
        "success": True,
        "result": "No results found.",
        "duration": 0.30,
    },
    "code_index": {
        "success": True,
        "result": "Indexing complete: 150 files processed.",
        "duration": 2.00,
    },
    "knowledge_query": {
        "success": True,
        "result": "No project knowledge found.",
        "duration": 0.08,
    },
    "knowledge_load": {
        "success": True,
        "result": "Knowledge loaded for project.",
        "duration": 0.12,
    },
    "knowledge_scan": {
        "success": True,
        "result": "Scan complete: found 5 patterns.",
        "duration": 1.50,
    },
    "knowledge_learn": {
        "success": True,
        "result": "Learning recorded.",
        "duration": 0.05,
    },
    # Slack
    "slack_search_messages": {
        "success": True,
        "result": "No messages found.",
        "duration": 0.40,
    },
    "slack_send_message": {
        "success": True,
        "result": "Message sent to #general",
        "duration": 0.35,
    },
    "slack_get_channel_history": {
        "success": True,
        "result": "No recent messages.",
        "duration": 0.38,
    },
    # Gmail / calendar
    "gmail_check_inbox": {
        "success": True,
        "result": "0 unread emails.",
        "duration": 0.50,
    },
    "gmail_search": {
        "success": True,
        "result": "No matching emails found.",
        "duration": 0.55,
    },
    "calendar_list_events": {
        "success": True,
        "result": "No upcoming events.",
        "duration": 0.45,
    },
    # System
    "systemctl_status": {
        "success": True,
        "result": "active (running)",
        "duration": 0.10,
    },
    # InScope
    "inscope_ask": {
        "success": True,
        "result": "Based on the documentation, you should configure your ClowdApp manifest.",
        "duration": 3.00,
    },
    "inscope_query": {
        "success": True,
        "result": "The deployment process involves creating a saas-file entry.",
        "duration": 3.00,
    },
    # Quay
    "quay_list_tags": {
        "success": True,
        "result": "latest, v1.2.3, abc1234",
        "duration": 0.40,
    },
    # VPN / auth
    "vpn_connect": {
        "success": True,
        "result": "VPN connected.",
        "duration": 2.00,
    },
    "kube_login": {
        "success": True,
        "result": "Logged in to stage cluster.",
        "duration": 1.50,
    },
    "sso_authenticate": {
        "success": True,
        "result": "SSO authentication successful.",
        "duration": 5.00,
    },
    # Browser
    "browser_navigate": {
        "success": True,
        "result": "Page loaded: Example Page",
        "duration": 1.20,
    },
    "browser_click": {
        "success": True,
        "result": "Clicked element.",
        "duration": 0.30,
    },
    "browser_snapshot": {
        "success": True,
        "result": "/tmp/browser_snapshots/screenshot.png",
        "duration": 0.50,
    },
    # Project management
    "project_list": {
        "success": True,
        "result": "3 projects configured: automation-analytics-backend, pdf-generator, redhat-ai-workflow",
        "duration": 0.05,
    },
    "project_detect": {
        "success": True,
        "result": "Detected: Python project, default branch: main",
        "duration": 0.20,
    },
}

# ---------------------------------------------------------------------------
# Prefix-based fallback responses (tool_name prefix -> response)
# ---------------------------------------------------------------------------
_PREFIX_RESPONSES: dict[str, dict] = {
    "git_": {
        "success": True,
        "result": "On branch main\nnothing to commit, working tree clean",
        "duration": 0.05,
    },
    "jira_": {
        "success": True,
        "result": "AAP-12345: Sample issue\nStatus: Open | Priority: Medium",
        "duration": 0.45,
    },
    "gitlab_": {
        "success": True,
        "result": "MR !100: sample merge request\nStatus: open | Pipeline: passed",
        "duration": 0.40,
    },
    "kubectl_": {
        "success": True,
        "result": "NAME          READY   STATUS    RESTARTS   AGE\nsample-pod    1/1     Running   0          1d",
        "duration": 0.70,
    },
    "bonfire_": {
        "success": True,
        "result": "ephemeral-ns-test (reserved, expires in 3h)",
        "duration": 0.55,
    },
    "memory_": {
        "success": True,
        "result": "OK",
        "duration": 0.02,
    },
    "knowledge_": {
        "success": True,
        "result": "No results found.",
        "duration": 0.10,
    },
    "code_": {
        "success": True,
        "result": "No results found.",
        "duration": 0.25,
    },
    "slack_": {
        "success": True,
        "result": "No messages found.",
        "duration": 0.35,
    },
    "gmail_": {
        "success": True,
        "result": "0 unread emails.",
        "duration": 0.50,
    },
    "calendar_": {
        "success": True,
        "result": "No upcoming events.",
        "duration": 0.45,
    },
    "systemctl_": {
        "success": True,
        "result": "active (running)",
        "duration": 0.10,
    },
    "curl_": {
        "success": True,
        "result": '{"status": "ok"}',
        "duration": 0.30,
    },
    "inscope_": {
        "success": True,
        "result": "Based on the documentation, here is the relevant information.",
        "duration": 3.00,
    },
    "quay_": {
        "success": True,
        "result": "latest, v1.0.0",
        "duration": 0.40,
    },
    "browser_": {
        "success": True,
        "result": "Action completed.",
        "duration": 0.50,
    },
    "session_": {
        "success": True,
        "result": "Session operation completed.",
        "duration": 0.10,
    },
    "project_": {
        "success": True,
        "result": "Project operation completed.",
        "duration": 0.10,
    },
    "sso_": {
        "success": True,
        "result": "SSO operation completed.",
        "duration": 2.00,
    },
    "vpn_": {
        "success": True,
        "result": "VPN operation completed.",
        "duration": 2.00,
    },
    "kube_": {
        "success": True,
        "result": "Kubernetes operation completed.",
        "duration": 1.50,
    },
    "debug_": {
        "success": True,
        "result": "Debug info retrieved.",
        "duration": 0.20,
    },
}

# Standalone tools without prefix patterns
_STANDALONE_RESPONSES: dict[str, dict] = {
    "persona_load": {
        "success": True,
        "result": "Persona loaded successfully.",
        "duration": 0.10,
    },
    "persona_list": {
        "success": True,
        "result": "Available personas: developer, devops, incident, release",
        "duration": 0.05,
    },
    "skill_run": {
        "success": True,
        "result": "Skill completed successfully.",
        "duration": 1.00,
    },
    "skill_list": {
        "success": True,
        "result": "126 skills available.",
        "duration": 0.08,
    },
    "check_known_issues": {
        "success": True,
        "result": "No known issues found.",
        "duration": 0.05,
    },
    "learn_tool_fix": {
        "success": True,
        "result": "Fix learned and saved.",
        "duration": 0.04,
    },
}


def generate_default_response(tool_name: str, args: dict | None = None) -> dict:
    """Generate a plausible mock response for a given tool invocation.

    Resolution order:
    1. Exact match in SPECIFIC_TOOLS
    2. Exact match in _STANDALONE_RESPONSES
    3. Longest matching prefix in _PREFIX_RESPONSES
    4. Generic success fallback

    Args:
        tool_name: The MCP tool name (e.g. "jira_view_issue").
        args: The arguments dict passed to the tool (currently unused
              but available for future conditional responses).

    Returns:
        A dict with keys: success (bool), result (str), duration (float).
    """
    # 1. Exact specific tool match
    if tool_name in SPECIFIC_TOOLS:
        return dict(SPECIFIC_TOOLS[tool_name])

    # 2. Standalone tool match
    if tool_name in _STANDALONE_RESPONSES:
        return dict(_STANDALONE_RESPONSES[tool_name])

    # 3. Prefix match (longest prefix wins)
    best_prefix = ""
    for prefix in _PREFIX_RESPONSES:
        if tool_name.startswith(prefix) and len(prefix) > len(best_prefix):
            best_prefix = prefix

    if best_prefix:
        return dict(_PREFIX_RESPONSES[best_prefix])

    # 4. Generic fallback
    return {
        "success": True,
        "result": f"Tool '{tool_name}' executed successfully.",
        "duration": 0.10,
    }
