# Smoke Test ALL MCP Tools

Comprehensive smoke test of ALL 203 MCP tools across 16 modules.

**Instructions:** Execute ALL the `tool_exec()` calls below that are NOT marked as SKIP.
Report results in the summary table format at the bottom.

## Pre-requisites

```python
# Authenticate to clusters FIRST
kube_login("s")  # stage
kube_login("k")  # konflux
```

## Test Execution

Test ALL tools in each module. Report results in a summary table.

---

## Module: git (15 tools)

```python
tool_exec("git_status", '{"repo": "redhat-ai-workflow"}')
tool_exec("git_branch_list", '{"repo": "redhat-ai-workflow"}')
tool_exec("git_branch_create", '{"repo": "redhat-ai-workflow", "branch_name": "test-smoke-delete-me", "checkout": false}')  # SKIP - creates branch
tool_exec("git_checkout", '{"repo": "redhat-ai-workflow", "target": "main"}')
tool_exec("git_log", '{"repo": "redhat-ai-workflow", "limit": 3}')
tool_exec("git_diff", '{"repo": "redhat-ai-workflow"}')
tool_exec("git_add", '{"repo": "redhat-ai-workflow", "files": "."}')  # SKIP - modifies state
tool_exec("git_commit", '{"repo": "redhat-ai-workflow", "message": "test"}')  # SKIP - modifies state
tool_exec("git_push", '{"repo": "redhat-ai-workflow"}')  # SKIP - modifies remote
tool_exec("git_pull", '{"repo": "redhat-ai-workflow"}')  # SKIP - modifies state
tool_exec("git_stash", '{"repo": "redhat-ai-workflow", "action": "list"}')
tool_exec("git_fetch", '{"repo": "redhat-ai-workflow"}')
tool_exec("git_merge", '{"repo": "redhat-ai-workflow", "target": "main"}')  # SKIP - modifies state
tool_exec("git_rebase", '{"repo": "redhat-ai-workflow", "onto": "main"}')  # SKIP - modifies state
tool_exec("git_remote", '{"repo": "redhat-ai-workflow"}')
```

**Safe to test:** git_status, git_branch_list, git_checkout, git_log, git_diff, git_stash (list), git_fetch, git_remote (8 tools)
**Skip (modifies state):** git_branch_create, git_add, git_commit, git_push, git_pull, git_merge, git_rebase (7 tools)

---

## Module: jira (25 tools)

```python
tool_exec("jira_view_issue", '{"issue_key": "AAP-61661"}')
tool_exec("jira_view_issue_json", '{"issue_key": "AAP-61661"}')
tool_exec("jira_search", '{"jql": "project=AAP ORDER BY created DESC", "max_results": 2}')
tool_exec("jira_list_issues", '{"project": "AAP", "status": "In Progress"}')
tool_exec("jira_my_issues", '{}')
tool_exec("jira_list_blocked", '{}')
tool_exec("jira_lint", '{"issue_key": "AAP-61661"}')
tool_exec("jira_set_status", '{"issue_key": "AAP-61661", "status": "In Progress"}')  # SKIP - modifies
tool_exec("jira_set_summary", '{"issue_key": "AAP-61661", "summary": "test"}')  # SKIP - modifies
tool_exec("jira_set_priority", '{"issue_key": "AAP-61661", "priority": "Normal"}')  # SKIP - modifies
tool_exec("jira_set_story_points", '{"issue_key": "AAP-61661", "points": 5}')  # SKIP - modifies
tool_exec("jira_set_epic", '{"issue_key": "AAP-61661", "epic_key": "AAP-62501"}')  # SKIP - modifies
tool_exec("jira_assign", '{"issue_key": "AAP-61661", "assignee": "daoneill"}')  # SKIP - modifies
tool_exec("jira_unassign", '{"issue_key": "AAP-61661"}')  # SKIP - modifies
tool_exec("jira_add_comment", '{"issue_key": "AAP-61661", "comment": "test"}')  # SKIP - modifies
tool_exec("jira_block", '{"issue_key": "AAP-61661", "blocker_key": "AAP-12345"}')  # SKIP - modifies
tool_exec("jira_unblock", '{"issue_key": "AAP-61661", "blocker_key": "AAP-12345"}')  # SKIP - modifies
tool_exec("jira_add_to_sprint", '{"issue_key": "AAP-61661", "sprint_id": "123"}')  # SKIP - modifies
tool_exec("jira_remove_sprint", '{"issue_key": "AAP-61661"}')  # SKIP - modifies
tool_exec("jira_create_issue", '{"issue_type": "task", "summary": "test"}')  # SKIP - creates
tool_exec("jira_clone_issue", '{"issue_key": "AAP-61661"}')  # SKIP - creates
tool_exec("jira_add_link", '{"from_issue": "AAP-61661", "to_issue": "AAP-12345"}')  # SKIP - modifies
tool_exec("jira_add_flag", '{"issue_key": "AAP-61661"}')  # SKIP - modifies
tool_exec("jira_remove_flag", '{"issue_key": "AAP-61661"}')  # SKIP - modifies
tool_exec("jira_open_browser", '{"issue_key": "AAP-61661"}')
```

**Safe to test:** jira_view_issue, jira_view_issue_json, jira_search, jira_list_issues, jira_my_issues, jira_list_blocked, jira_lint, jira_open_browser (8 tools)
**Skip (modifies state):** 17 tools

---

## Module: gitlab (30 tools)

```python
tool_exec("gitlab_mr_list", '{"project": "automation-analytics/automation-analytics-backend", "state": "opened"}')
tool_exec("gitlab_mr_view", '{"project": "automation-analytics/automation-analytics-backend", "mr_id": 1462}')
tool_exec("gitlab_mr_create", '{"project": "...", "title": "test"}')  # SKIP - creates
tool_exec("gitlab_mr_update", '{"project": "...", "mr_id": 1462, "title": "test"}')  # SKIP - modifies
tool_exec("gitlab_mr_approve", '{"project": "...", "mr_id": 1462}')  # SKIP - modifies
tool_exec("gitlab_mr_revoke", '{"project": "...", "mr_id": 1462}')  # SKIP - modifies
tool_exec("gitlab_mr_merge", '{"project": "...", "mr_id": 1462}')  # SKIP - modifies
tool_exec("gitlab_mr_close", '{"project": "...", "mr_id": 1462}')  # SKIP - modifies
tool_exec("gitlab_mr_reopen", '{"project": "...", "mr_id": 1462}')  # SKIP - modifies
tool_exec("gitlab_mr_comment", '{"project": "...", "mr_id": 1462, "message": "test"}')  # SKIP - modifies
tool_exec("gitlab_mr_diff", '{"project": "automation-analytics/automation-analytics-backend", "mr_id": 1462}')
tool_exec("gitlab_mr_rebase", '{"project": "...", "mr_id": 1462}')  # SKIP - modifies
tool_exec("gitlab_mr_checkout", '{"project": "...", "mr_id": 1462}')  # SKIP - modifies local
tool_exec("gitlab_mr_approvers", '{"project": "automation-analytics/automation-analytics-backend", "mr_id": 1462}')
tool_exec("gitlab_ci_list", '{"project": "automation-analytics/automation-analytics-backend"}')
tool_exec("gitlab_ci_status", '{"project": "automation-analytics/automation-analytics-backend"}')
tool_exec("gitlab_ci_view", '{"project": "automation-analytics/automation-analytics-backend"}')
tool_exec("gitlab_ci_run", '{"project": "..."}')  # SKIP - triggers pipeline
tool_exec("gitlab_ci_retry", '{"project": "...", "pipeline_id": 123}')  # SKIP - triggers pipeline
tool_exec("gitlab_ci_cancel", '{"project": "...", "pipeline_id": 123}')  # SKIP - modifies
tool_exec("gitlab_ci_trace", '{"project": "automation-analytics/automation-analytics-backend", "job_id": 12345}')
tool_exec("gitlab_ci_lint", '{"project": "automation-analytics/automation-analytics-backend"}')
tool_exec("gitlab_repo_view", '{"project": "automation-analytics/automation-analytics-backend"}')  # SKIP - in tools_extra
tool_exec("gitlab_repo_clone", '{"project": "..."}')  # SKIP - clones repo
tool_exec("gitlab_issue_list", '{"project": "automation-analytics/automation-analytics-backend"}')  # SKIP - in tools_extra
tool_exec("gitlab_issue_view", '{"project": "automation-analytics/automation-analytics-backend", "issue_id": 1}')  # SKIP - in tools_extra
tool_exec("gitlab_issue_create", '{"project": "...", "title": "test"}')  # SKIP - creates
tool_exec("gitlab_label_list", '{"project": "automation-analytics/automation-analytics-backend"}')  # SKIP - in tools_extra
tool_exec("gitlab_release_list", '{"project": "automation-analytics/automation-analytics-backend"}')  # SKIP - in tools_extra
tool_exec("gitlab_user_info", '{}')  # SKIP - in tools_extra
```

**Safe to test:** gitlab_mr_list, gitlab_mr_view, gitlab_mr_diff, gitlab_mr_approvers, gitlab_ci_list, gitlab_ci_status, gitlab_ci_view, gitlab_ci_trace, gitlab_ci_lint (9 tools)
**Skip (modifies state):** 15 tools
**Skip (in tools_extra):** gitlab_repo_view, gitlab_issue_list, gitlab_issue_view, gitlab_label_list, gitlab_release_list, gitlab_user_info (6 tools)

---

## Module: k8s (14 tools)

```python
tool_exec("kubectl_get_pods", '{"namespace": "tower-analytics-stage", "environment": "stage"}')
tool_exec("kubectl_describe_pod", '{"namespace": "tower-analytics-stage", "environment": "stage", "pod": "automation-analytics-api-fastapi-v2-657ff8dff4-5ph6m"}')
tool_exec("kubectl_logs", '{"namespace": "tower-analytics-stage", "environment": "stage", "pod": "automation-analytics-api-fastapi-v2-657ff8dff4-5ph6m", "tail": 10}')
tool_exec("kubectl_delete_pod", '{"namespace": "...", "pod": "..."}')  # SKIP - deletes
tool_exec("kubectl_get_deployments", '{"namespace": "tower-analytics-stage", "environment": "stage"}')
tool_exec("kubectl_describe_deployment", '{"namespace": "tower-analytics-stage", "environment": "stage", "deployment": "automation-analytics-api-fastapi-v2"}')
tool_exec("kubectl_rollout_status", '{"namespace": "tower-analytics-stage", "environment": "stage", "deployment": "automation-analytics-api-fastapi-v2"}')
tool_exec("kubectl_rollout_restart", '{"namespace": "...", "deployment": "..."}')  # SKIP - restarts
tool_exec("kubectl_scale", '{"namespace": "...", "deployment": "...", "replicas": 1}')  # SKIP - scales
tool_exec("kubectl_get_services", '{"namespace": "tower-analytics-stage", "environment": "stage"}')
tool_exec("kubectl_get_events", '{"namespace": "tower-analytics-stage", "environment": "stage"}')
tool_exec("kubectl_get", '{"namespace": "tower-analytics-stage", "environment": "stage", "resource": "configmaps"}')
tool_exec("kubectl_exec", '{"namespace": "...", "pod": "...", "command": "ls"}')  # SKIP - executes
tool_exec("kubectl_top_pods", '{"namespace": "tower-analytics-stage", "environment": "stage"}')
```

**Safe to test:** kubectl_get_pods, kubectl_describe_pod, kubectl_logs, kubectl_get_deployments, kubectl_describe_deployment, kubectl_rollout_status, kubectl_get_services, kubectl_get_events, kubectl_get, kubectl_top_pods (10 tools)
**Skip (modifies state):** kubectl_delete_pod, kubectl_rollout_restart, kubectl_scale, kubectl_exec (4 tools)

---

## Module: prometheus (11 tools)

```python
tool_exec("prometheus_query", '{"query": "up", "environment": "stage"}')
tool_exec("prometheus_query_range", '{"query": "up", "environment": "stage", "start": "1h"}')
tool_exec("prometheus_alerts", '{"environment": "stage"}')
tool_exec("prometheus_rules", '{"environment": "stage"}')
tool_exec("prometheus_targets", '{"environment": "stage"}')  # SKIP - in tools_extra
tool_exec("prometheus_labels", '{"environment": "stage"}')  # SKIP - in tools_extra
tool_exec("prometheus_series", '{"environment": "stage", "match": "up"}')  # SKIP - in tools_extra
tool_exec("prometheus_namespace_metrics", '{"namespace": "tower-analytics-stage", "environment": "stage"}')  # SKIP - in tools_extra
tool_exec("prometheus_error_rate", '{"namespace": "tower-analytics-stage", "environment": "stage"}')  # SKIP - in tools_extra
tool_exec("prometheus_pod_health", '{"namespace": "tower-analytics-stage", "environment": "stage"}')
tool_exec("prometheus_grafana_link", '{"environment": "stage"}')
```

**Safe to test:** prometheus_query, prometheus_query_range, prometheus_alerts, prometheus_rules, prometheus_pod_health, prometheus_grafana_link (6 tools)
**Skip (in tools_extra):** prometheus_targets, prometheus_labels, prometheus_series, prometheus_namespace_metrics, prometheus_error_rate (5 tools)

---

## Module: alertmanager (5 tools)

```python
tool_exec("alertmanager_silences", '{"environment": "stage"}')  # SKIP - in tools_extra
tool_exec("alertmanager_create_silence", '{"environment": "stage", "matchers": "alertname=test", "duration": "1h", "comment": "test"}')  # SKIP - creates
tool_exec("alertmanager_delete_silence", '{"environment": "stage", "silence_id": "xxx"}')  # SKIP - deletes
tool_exec("alertmanager_status", '{"environment": "stage"}')  # SKIP - in tools_extra
tool_exec("alertmanager_alerts", '{"environment": "stage"}')
```

**Safe to test:** alertmanager_alerts (1 tool)
**Skip (modifies state):** alertmanager_create_silence, alertmanager_delete_silence (2 tools)
**Skip (in tools_extra):** alertmanager_silences, alertmanager_status (2 tools)

---

## Module: kibana (9 tools)

```python
tool_exec("kibana_search_logs", '{"query": "error", "environment": "stage", "limit": 2}')
tool_exec("kibana_get_errors", '{"namespace": "tower-analytics-stage", "environment": "stage", "limit": 2}')  # SKIP - in tools_extra
tool_exec("kibana_get_pod_logs", '{"namespace": "tower-analytics-stage", "environment": "stage", "pod": "automation-analytics-api-fastapi-v2", "limit": 2}')  # SKIP - in tools_extra
tool_exec("kibana_trace_request", '{"request_id": "xxx", "environment": "stage"}')  # SKIP - in tools_extra
tool_exec("kibana_get_link", '{"namespace": "tower-analytics-stage", "environment": "stage"}')  # SKIP - in tools_extra
tool_exec("kibana_error_link", '{"namespace": "tower-analytics-stage", "environment": "stage"}')  # SKIP - in tools_extra
tool_exec("kibana_status", '{"environment": "stage"}')  # SKIP - in tools_extra
tool_exec("kibana_index_patterns", '{"environment": "stage"}')  # SKIP - in tools_extra
tool_exec("kibana_list_dashboards", '{"environment": "stage"}')  # SKIP - in tools_extra
```

**Safe to test:** kibana_search_logs (1 tool)
**Skip (in tools_extra):** kibana_get_errors, kibana_get_pod_logs, kibana_trace_request, kibana_get_link, kibana_error_link, kibana_status, kibana_index_patterns, kibana_list_dashboards (8 tools)

---

## Module: konflux (15 tools)

```python
tool_exec("konflux_list_applications", '{"namespace": "aap-aa-tenant"}')
tool_exec("konflux_get_application", '{"application": "aap-aa-main", "namespace": "aap-aa-tenant"}')  # SKIP - in tools_extra
tool_exec("konflux_list_components", '{"application": "aap-aa-main", "namespace": "aap-aa-tenant"}')
tool_exec("konflux_get_component", '{"component": "automation-analytics-backend-main", "namespace": "aap-aa-tenant"}')
tool_exec("konflux_list_snapshots", '{"application": "aap-aa-main", "namespace": "aap-aa-tenant"}')
tool_exec("konflux_get_snapshot", '{"snapshot": "xxx", "namespace": "aap-aa-tenant"}')
tool_exec("konflux_list_integration_tests", '{"application": "aap-aa-main", "namespace": "aap-aa-tenant"}')
tool_exec("konflux_get_test_results", '{"test_name": "xxx", "namespace": "aap-aa-tenant"}')
tool_exec("konflux_list_releases", '{"application": "aap-aa-main", "namespace": "aap-aa-tenant"}')
tool_exec("konflux_get_release", '{"release": "xxx", "namespace": "aap-aa-tenant"}')
tool_exec("konflux_list_release_plans", '{"application": "aap-aa-main", "namespace": "aap-aa-tenant"}')  # SKIP - in tools_extra
tool_exec("konflux_list_builds", '{"component": "automation-analytics-backend-main", "namespace": "aap-aa-tenant"}')
tool_exec("konflux_get_build_logs", '{"build": "xxx", "namespace": "aap-aa-tenant"}')
tool_exec("konflux_list_environments", '{"namespace": "aap-aa-tenant"}')  # SKIP - in tools_extra
tool_exec("konflux_namespace_summary", '{"namespace": "aap-aa-tenant"}')
```

**Safe to test:** konflux_list_applications, konflux_list_components, konflux_get_component, konflux_list_snapshots, konflux_get_snapshot, konflux_list_integration_tests, konflux_get_test_results, konflux_list_releases, konflux_get_release, konflux_list_builds, konflux_get_build_logs, konflux_namespace_summary (12 tools)
**Skip (in tools_extra):** konflux_get_application, konflux_list_release_plans, konflux_list_environments (3 tools)

---

## Module: bonfire (17 tools)

```python
tool_exec("bonfire_version", '{}')  # SKIP - tool removed
tool_exec("bonfire_namespace_reserve", '{"duration": "1h"}')  # SKIP - reserves
tool_exec("bonfire_namespace_list", '{"mine_only": true}')
tool_exec("bonfire_namespace_describe", '{"namespace": "ephemeral-xxx"}')
tool_exec("bonfire_namespace_release", '{"namespace": "ephemeral-xxx"}')  # SKIP - releases
tool_exec("bonfire_namespace_extend", '{"namespace": "ephemeral-xxx", "duration": "1h"}')  # SKIP - modifies
tool_exec("bonfire_namespace_wait", '{"namespace": "ephemeral-xxx"}')
tool_exec("bonfire_apps_list", '{}')  # SKIP - in tools_extra
tool_exec("bonfire_apps_dependencies", '{"app": "tower-analytics"}')
tool_exec("bonfire_deploy", '{"namespace": "ephemeral-xxx", "app": "tower-analytics"}')  # SKIP - deploys
tool_exec("bonfire_deploy_with_reserve", '{"app": "tower-analytics"}')  # SKIP - in tools_extra
tool_exec("bonfire_process", '{"app": "tower-analytics"}')  # SKIP - in tools_extra
tool_exec("bonfire_deploy_env", '{"namespace": "ephemeral-xxx"}')  # SKIP - in tools_extra
tool_exec("bonfire_process_env", '{}')  # SKIP - in tools_extra
tool_exec("bonfire_deploy_iqe_cji", '{"namespace": "ephemeral-xxx"}')  # SKIP - in tools_extra
tool_exec("bonfire_pool_list", '{}')
tool_exec("bonfire_deploy_aa", '{"namespace": "ephemeral-xxx"}')  # SKIP - deploys
```

**Safe to test:** bonfire_namespace_list, bonfire_namespace_describe, bonfire_namespace_wait, bonfire_apps_dependencies, bonfire_pool_list (5 tools)
**Skip (modifies state):** bonfire_namespace_reserve, bonfire_namespace_release, bonfire_namespace_extend, bonfire_deploy, bonfire_deploy_aa (5 tools)
**Skip (in tools_extra):** bonfire_apps_list, bonfire_deploy_with_reserve, bonfire_process, bonfire_deploy_env, bonfire_process_env, bonfire_deploy_iqe_cji (6 tools)
**Skip (removed):** bonfire_version (1 tool)

---

## Module: quay (8 tools)

```python
tool_exec("quay_get_repository", '{"repository": "redhat-user-workloads/aap-aa-tenant/aap-aa-main/automation-analytics-backend-main"}')  # SKIP - in tools_extra
tool_exec("quay_list_tags", '{"repository": "redhat-user-workloads/aap-aa-tenant/aap-aa-main/automation-analytics-backend-main", "limit": 5}')  # SKIP - in tools_extra
tool_exec("quay_get_tag", '{"repository": "redhat-user-workloads/aap-aa-tenant/aap-aa-main/automation-analytics-backend-main", "tag": "latest"}')
tool_exec("quay_check_image_exists", '{"repository": "redhat-user-workloads/aap-aa-tenant/aap-aa-main/automation-analytics-backend-main", "tag_or_digest": "latest"}')
tool_exec("quay_get_vulnerabilities", '{"repository": "redhat-user-workloads/aap-aa-tenant/aap-aa-main/automation-analytics-backend-main", "tag": "latest"}')
tool_exec("quay_get_manifest", '{"repository": "redhat-user-workloads/aap-aa-tenant/aap-aa-main/automation-analytics-backend-main", "tag": "latest"}')
tool_exec("quay_check_aa_image", '{"sha": "abc123"}')
tool_exec("quay_list_aa_tags", '{"limit": 5}')
```

**Safe to test:** quay_get_tag, quay_check_image_exists, quay_get_vulnerabilities, quay_get_manifest, quay_check_aa_image, quay_list_aa_tags (6 tools)
**Skip (in tools_extra):** quay_get_repository, quay_list_tags (2 tools)

---

## Module: appinterface (6 tools)

```python
tool_exec("appinterface_validate", '{}')
tool_exec("appinterface_get_saas", '{"service_name": "tower-analytics"}')
tool_exec("appinterface_diff", '{}')
tool_exec("appinterface_resources", '{"service_name": "tower-analytics"}')
tool_exec("appinterface_search", '{"query": "tower-analytics"}')
tool_exec("appinterface_clusters", '{}')
```

**Safe to test:** ALL 6 tools (read-only)

---

## Module: slack (9 tools)

```python
tool_exec("slack_list_messages", '{"channel": "automation-analytics-dev", "limit": 3}')  # SKIP - in tools_extra
tool_exec("slack_send_message", '{"channel": "...", "message": "test"}')  # SKIP - sends
tool_exec("slack_get_channels", '{}')  # SKIP - in tools_extra
tool_exec("slack_post_team", '{"message": "test"}')  # SKIP - sends
tool_exec("slack_dm_gitlab_user", '{"username": "...", "message": "test"}')  # SKIP - sends
tool_exec("slack_get_user", '{"username": "daoneill"}')
tool_exec("slack_search_messages", '{"query": "automation analytics", "limit": 3}')
tool_exec("slack_add_reaction", '{"channel": "...", "timestamp": "...", "emoji": "thumbsup"}')  # SKIP - in tools_extra
tool_exec("slack_list_channels", '{}')
```

**Safe to test:** slack_get_user, slack_search_messages, slack_list_channels (3 tools)
**Skip (modifies state):** slack_send_message, slack_post_team, slack_dm_gitlab_user (3 tools)
**Skip (in tools_extra):** slack_list_messages, slack_get_channels, slack_add_reaction (3 tools)

---

## Module: google_calendar (6 tools)

```python
tool_exec("google_calendar_find_meeting", '{"attendees": "test@redhat.com", "duration_minutes": 30}')
tool_exec("google_calendar_check_mutual_availability", '{"attendees": "test@redhat.com"}')
tool_exec("google_calendar_schedule_meeting", '{"title": "test", "attendees": "test@redhat.com"}')  # SKIP - creates
tool_exec("google_calendar_quick_meeting", '{"title": "test", "attendees": "test@redhat.com"}')  # SKIP - creates
tool_exec("google_calendar_list_events", '{"days": 7, "max_results": 5}')
tool_exec("google_calendar_status", '{}')
```

**Safe to test:** google_calendar_find_meeting, google_calendar_check_mutual_availability, google_calendar_list_events, google_calendar_status (4 tools)
**Skip (modifies state):** 2 tools

---

## Module: lint (7 tools)

```python
tool_exec("lint_python", '{"repo": "redhat-ai-workflow", "paths": "server/utils.py"}')
tool_exec("lint_yaml", '{"repo": "redhat-ai-workflow", "paths": "config.json"}')
tool_exec("lint_dockerfile", '{"repo": "redhat-ai-workflow"}')
tool_exec("test_run", '{"repo": "redhat-ai-workflow", "test_path": "tests/test_server_config.py"}')
tool_exec("test_coverage", '{"repo": "redhat-ai-workflow"}')
tool_exec("security_scan", '{"repo": "redhat-ai-workflow"}')
tool_exec("precommit_run", '{"repo": "redhat-ai-workflow"}')
```

**Safe to test:** ALL 7 tools (read-only checks)

---

## Module: dev_workflow (9 tools)

```python
tool_exec("workflow_start_work", '{"issue_key": "AAP-61661"}')  # SKIP - modifies
tool_exec("workflow_check_deploy_readiness", '{"repo": "automation-analytics-backend"}')
tool_exec("workflow_review_feedback", '{"mr_id": 1462}')
tool_exec("workflow_create_branch", '{"issue_key": "AAP-61661"}')  # SKIP - creates
tool_exec("workflow_prepare_mr", '{"issue_key": "AAP-61661"}')  # SKIP - creates
tool_exec("workflow_run_local_checks", '{"repo": "redhat-ai-workflow"}')
tool_exec("workflow_monitor_pipelines", '{"mr_id": 1462}')
tool_exec("workflow_handle_review", '{"mr_id": 1462}')
tool_exec("workflow_daily_standup", '{}')
```

**Safe to test:** workflow_check_deploy_readiness, workflow_review_feedback, workflow_run_local_checks, workflow_monitor_pipelines, workflow_handle_review, workflow_daily_standup (6 tools)
**Skip (modifies state):** 3 tools

---

## Module: workflow (17 tools)

```python
tool_exec("vpn_connect", '{}')  # SKIP - connects VPN
tool_exec("kube_login", '{"cluster": "s"}')  # Already done in pre-req
tool_exec("memory_read", '{"key": "state/current_work"}')
tool_exec("memory_write", '{"key": "test", "content": "test"}')  # SKIP - modifies
tool_exec("memory_update", '{"key": "state/current_work", "path": "test", "value": "test"}')  # SKIP - modifies
tool_exec("memory_append", '{"key": "state/current_work", "list_path": "test", "item": "test"}')  # SKIP - modifies
tool_exec("memory_session_log", '{"action": "smoke test"}')
tool_exec("check_known_issues", '{"tool_name": "bonfire_deploy"}')
tool_exec("learn_tool_fix", '{"tool_name": "test", "error_pattern": "test", "root_cause": "test", "fix_description": "test"}')  # SKIP - modifies
tool_exec("tool_list", '{}')
tool_exec("tool_exec", '{"tool_name": "git_status", "args": "{\"repo\": \"redhat-ai-workflow\"}"}')
tool_exec("persona_list", '{}')
tool_exec("persona_load", '{"persona_name": "developer"}')  # SKIP - changes state
tool_exec("session_start", '{}')
tool_exec("skill_list", '{}')
tool_exec("skill_run", '{"skill_name": "memory_view"}')
tool_exec("debug_tool", '{"tool_name": "git_status"}')  # SKIP - server-level tool, not in module
```text

**Safe to test:** memory_read, memory_session_log, check_known_issues, tool_list, tool_exec, persona_list, session_start, skill_list, skill_run (9 tools)
**Skip (modifies state):** memory_write, memory_update, memory_append, learn_tool_fix, persona_load, vpn_connect, kube_login (7 tools)
**Skip (server-level):** debug_tool (1 tool)

---

## Summary

| Module | Total | Safe to Test | Skip (Modifies) | Skip (tools_extra) | Skip (Other) |
|--------|-------|--------------|-----------------|-------------------|--------------|
| git | 15 | 8 | 7 | 0 | 0 |
| jira | 25 | 8 | 17 | 0 | 0 |
| gitlab | 30 | 9 | 15 | 6 | 0 |
| k8s | 14 | 10 | 4 | 0 | 0 |
| prometheus | 11 | 6 | 0 | 5 | 0 |
| alertmanager | 5 | 1 | 2 | 2 | 0 |
| kibana | 9 | 1 | 0 | 8 | 0 |
| konflux | 15 | 12 | 0 | 3 | 0 |
| bonfire | 17 | 5 | 5 | 6 | 1 (removed) |
| quay | 8 | 6 | 0 | 2 | 0 |
| appinterface | 6 | 6 | 0 | 0 | 0 |
| slack | 9 | 3 | 3 | 3 | 0 |
| google_calendar | 6 | 4 | 2 | 0 | 0 |
| lint | 7 | 7 | 0 | 0 | 0 |
| dev_workflow | 9 | 6 | 3 | 0 | 0 |
| workflow | 17 | 9 | 7 | 0 | 1 (server-level) |
| **TOTAL** | **203** | **101** | **65** | **35** | **2** |

## Expected Output Format

```
## 🧪 MCP Tool Smoke Test Results

### Module: git (8/15 tested)
| Tool | Status | Notes |
|------|--------|-------|
| git_status | ✅ | Shows branch main |
| git_branch_list | ✅ | Lists branches |
| ... | ... | ... |

### Module: jira (8/25 tested)
...

## Summary
- **Total tools:** 203
- **Tested:** 134
- **Passed:** X
- **Failed:** Y
- **Skipped (modifies state):** 69
```
