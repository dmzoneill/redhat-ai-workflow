# Skill Auto-Heal Implementation Plan

## Overview

This document outlines the changes required to enable **auto-heal** capabilities across all skills. When a tool fails, the skill should:

1. **Detect** the failure
2. **Analyze** using `debug_tool`
3. **Fix** the tool implementation if possible
4. **Learn** by saving the pattern to memory

## Current State

| Metric | Count |
|--------|-------|
| Skills with auto-heal | 42 |
| Skills that should have auto-heal | 0 remaining |
| Skills that are utility/internal (no auto-heal needed) | 8 |

### Skills with Auto-Heal Implemented (42 total)

#### High Priority (Infrastructure/K8s/Cluster)
1. ✅ `test_mr_ephemeral.yaml` - bonfire_namespace_reserve
2. ✅ `deploy_to_ephemeral.yaml` - bonfire_namespace_reserve
3. ✅ `debug_prod.yaml` - kubectl_get_pods
4. ✅ `investigate_alert.yaml` - kubectl_get_pods
5. ✅ `rollout_restart.yaml` - kubectl_rollout_restart
6. ✅ `release_to_prod.yaml` - konflux_get_component
7. ✅ `konflux_status.yaml` - konflux_status
8. ✅ `silence_alert.yaml` - alertmanager_alerts
9. ✅ `extend_ephemeral.yaml` - bonfire_namespace_list
10. ✅ `cancel_pipeline.yaml` - tkn_pipelinerun_list
11. ✅ `check_integration_tests.yaml` - konflux_list_integration_tests
12. ✅ `check_secrets.yaml` - kubectl_get_secrets
13. ✅ `environment_overview.yaml` - k8s_environment_summary
14. ✅ `scale_deployment.yaml` - kubectl_get_deployments
15. ✅ `scan_vulnerabilities.yaml` - quay_check_image_exists

#### Medium Priority (GitLab/Git)
16. ✅ `review_pr.yaml` - gitlab_mr_view
17. ✅ `check_ci_health.yaml` - gitlab_ci_list
18. ✅ `ci_retry.yaml` - gitlab init
19. ✅ `create_mr.yaml` - git_push
20. ✅ `check_mr_feedback.yaml` - gitlab_mr_list
21. ✅ `check_my_prs.yaml` - gitlab init
22. ✅ `cleanup_branches.yaml` - git init
23. ✅ `close_mr.yaml` - gitlab_mr_view
24. ✅ `hotfix.yaml` - git init
25. ✅ `notify_mr.yaml` - failure tracking
26. ✅ `mark_mr_ready.yaml` - failure tracking
27. ✅ `rebase_pr.yaml` - git init
28. ✅ `review_all_prs.yaml` - gitlab init
29. ✅ `sync_branch.yaml` - git init

#### Medium Priority (Jira)
30. ✅ `start_work.yaml` - jira_view_issue
31. ✅ `appinterface_check.yaml` - appinterface_validate
32. ✅ `sprint_planning.yaml` - jira_list_issues
33. ✅ `clone_jira_issue.yaml` - jira_view_issue
34. ✅ `close_issue.yaml` - jira init
35. ✅ `create_jira_issue.yaml` - jira_create_issue
36. ✅ `jira_hygiene.yaml` - jira init

#### Lower Priority (Slack/Calendar/Reporting)
37. ✅ `weekly_summary.yaml` - git_log
38. ✅ `standup_summary.yaml` - failure tracking
39. ✅ `notify_team.yaml` - slack_list_channels
40. ✅ `investigate_slack_alert.yaml` - failure tracking
41. ✅ `schedule_meeting.yaml` - google_calendar_status
42. ✅ `release_aa_backend_prod.yaml` - failure tracking

### Skills NOT Needing Auto-Heal (8 utility/internal)
- `beer.yaml` - fun skill
- `coffee.yaml` - fun skill
- `learn_pattern.yaml` - internal memory
- `memory_cleanup.yaml` - internal memory
- `memory_edit.yaml` - internal memory
- `memory_init.yaml` - internal memory
- `memory_view.yaml` - internal memory
- `slack_daemon_control.yaml` - daemon control

---

## Auto-Heal Pattern

### Standard Implementation

Add this pattern after any tool call that might fail:

```yaml
# Original tool call
- name: call_some_tool
  tool: gitlab_mr_list
  args:
    project: "{{ project }}"
  output: tool_result
  on_error: continue

# ==================== AUTO-HEAL ====================

- name: detect_failure_some_tool
  description: "Detect if tool failed"
  condition: "tool_result and ('❌' in str(tool_result) or 'error' in str(tool_result).lower())"
  compute: |
    error_text = str(tool_result)[:300]

    # Common error patterns
    needs_auth = any(x in error_text.lower() for x in ['unauthorized', 'forbidden', '401', '403', 'token expired'])
    needs_vpn = any(x in error_text.lower() for x in ['no route', 'connection refused', 'timeout', 'network'])

    result = {
      "failed": True,
      "tool_name": "gitlab_mr_list",
      "error": error_text,
      "needs_auth": needs_auth,
      "needs_vpn": needs_vpn,
    }
  output: failure_some_tool

# Quick fix for common issues
- name: quick_fix_auth
  description: "Auto-fix auth issues"
  condition: "failure_some_tool and failure_some_tool.needs_auth"
  tool: kube_login
  args:
    cluster: "stage"
  output: auth_fix_result
  on_error: continue

- name: quick_fix_vpn
  description: "Auto-fix VPN issues"
  condition: "failure_some_tool and failure_some_tool.needs_vpn"
  tool: vpn_connect
  args: {}
  output: vpn_fix_result
  on_error: continue

# Deep analysis for unknown errors
- name: analyze_tool_failure
  description: "Use debug_tool to analyze unknown failure"
  condition: "failure_some_tool and not failure_some_tool.needs_auth and not failure_some_tool.needs_vpn"
  tool: debug_tool
  args:
    tool_name: "{{ failure_some_tool.tool_name }}"
    error_message: "{{ failure_some_tool.error }}"
  output: debug_analysis

# Learn from the failure
- name: learn_from_failure
  description: "Save pattern to memory for future"
  condition: "failure_some_tool"
  tool: memory_append
  args:
    key: "learned/tool_failures"
    list_path: "failures"
    item: |
      tool: {{ failure_some_tool.tool_name }}
      error: {{ failure_some_tool.error[:100] }}
      timestamp: {{ now() }}
      context: {{ skill_name }}
  on_error: continue

# Retry the tool after fix
- name: retry_some_tool
  description: "Retry tool after auto-fix"
  condition: "(auth_fix_result or vpn_fix_result) and failure_some_tool"
  tool: gitlab_mr_list
  args:
    project: "{{ project }}"
  output: retry_result
  on_error: continue
```

---

## Skills Requiring Auto-Heal

### 🔴 HIGH PRIORITY (Operational)

These skills interact with external systems that frequently have auth/network issues.

#### 1. `test_mr_ephemeral.yaml`

**Tools that fail:**
- `bonfire_namespace_reserve` - auth issues
- `bonfire_deploy` - timeout/auth
- `kubectl_get_pods` - kubeconfig issues
- `quay_check_image_exists` - registry auth

**Changes needed:**
- [ ] Add failure detection after `bonfire_namespace_reserve`
- [ ] Add `kube_login("ephemeral")` auto-fix
- [ ] Add failure detection after `quay_check_image_exists`
- [ ] Add retry logic with backoff
- [ ] Save failures to `learned/tool_failures`

#### 2. `debug_prod.yaml`

**Tools that fail:**
- `kubectl_get_pods` - auth
- `prometheus_query` - auth
- `kibana_search_logs` - browser auth needed
- `kubectl_logs` - auth

**Changes needed:**
- [ ] Add failure detection after each kubectl/prometheus call
- [ ] Add `kube_login("production")` auto-fix
- [ ] Detect kibana auth issues and suggest manual login
- [ ] Save failures to memory

#### 3. `investigate_alert.yaml`

**Tools that fail:**
- `alertmanager_list_alerts` - auth
- `prometheus_query` - auth
- `kubectl_get_pods` - auth

**Changes needed:**
- [ ] Add failure detection for alertmanager tools
- [ ] Add `kube_login("stage")` auto-fix
- [ ] Pattern matching for common alert types
- [ ] Save learned patterns

#### 4. `release_to_prod.yaml`

**Tools that fail:**
- `quay_check_image_exists` - registry auth
- `quay_get_vulnerabilities` - registry auth
- `konflux_create_release` - auth
- `appinterface_validate` - local path issues

**Changes needed:**
- [ ] Add failure detection after quay tools
- [ ] Add `podman login quay.io` suggestion
- [ ] Detect konflux auth issues
- [ ] Block release on tool failures (safety)

#### 5. `deploy_to_ephemeral.yaml`

**Tools that fail:**
- `bonfire_pool_list` - auth
- `bonfire_namespace_reserve` - timeout
- `bonfire_deploy` - various
- `kubectl_get_pods` - auth

**Changes needed:**
- [ ] Add failure detection for bonfire tools
- [ ] Add `kube_login("ephemeral")` auto-fix
- [ ] Add retry with exponential backoff
- [ ] Clean up namespace on failure

#### 6. `rollout_restart.yaml`

**Tools that fail:**
- `kubectl_rollout_restart` - auth
- `kubectl_rollout_status` - timeout
- `kubectl_describe_deployment` - auth

**Changes needed:**
- [ ] Add failure detection for kubectl tools
- [ ] Add auth auto-fix
- [ ] Add rollback on stuck rollout
- [ ] Save failure patterns

---

### 🟡 MEDIUM PRIORITY (Development)

#### 7. `review_pr.yaml`

**Tools that fail:**
- `gitlab_mr_view` - auth
- `gitlab_ci_status` - auth
- `git_diff` - repo path issues

**Changes needed:**
- [ ] Add failure detection for gitlab tools
- [ ] Detect glab auth issues
- [ ] Suggest `glab auth login`

#### 8. `create_mr.yaml`

**Tools that fail:**
- `git_push` - auth/remote issues
- `gitlab_mr_create` - auth
- `gitlab_ci_lint` - auth

**Changes needed:**
- [ ] Add failure detection for git tools
- [ ] Detect SSH key issues
- [ ] Suggest git credential fix

#### 9. `start_work.yaml`

**Tools that fail:**
- `git_checkout` - uncommitted changes
- `git_pull` - conflicts
- `jira_view_issue` - auth

**Changes needed:**
- [ ] Already has git_stash - good!
- [ ] Add conflict detection and resolution
- [ ] Add jira auth detection

#### 10. `check_ci_health.yaml`

**Tools that fail:**
- `gitlab_ci_list` - auth
- `gitlab_ci_trace` - auth
- `gitlab_ci_lint` - auth

**Changes needed:**
- [ ] Add failure detection for all gitlab tools
- [ ] Suggest glab auth refresh

#### 11. `konflux_status.yaml`

**Tools that fail:**
- `konflux_status` - auth
- `konflux_list_applications` - auth
- `konflux_running_pipelines` - auth

**Changes needed:**
- [ ] Add failure detection for konflux tools
- [ ] Add `kube_login("konflux")` auto-fix

#### 12. `appinterface_check.yaml`

**Tools that fail:**
- `appinterface_validate` - path issues
- `appinterface_get_saas` - not found
- `appinterface_diff` - git issues

**Changes needed:**
- [ ] Add failure detection
- [ ] Check if app-interface repo exists
- [ ] Suggest git clone if missing

---

### 🟢 LOW PRIORITY (Already Handles Errors Well)

#### 13. `silence_alert.yaml`
- [ ] Add retry for alertmanager auth

#### 14. `extend_ephemeral.yaml`
- [ ] Add retry for bonfire auth

#### 15. `cancel_pipeline.yaml`
- [ ] Already has retry logic - verify it works

---

## Memory Structure for Learned Failures

Create `memory/learned/tool_failures.yaml`:

```yaml
# Learned tool failure patterns
failures:
  - tool: bonfire_namespace_reserve
    error: "Unauthorized"
    fix: "kube_login('ephemeral')"
    success_rate: 0.95
    last_seen: "2026-01-04T10:30:00"

  - tool: kibana_search_logs
    error: "403 Forbidden"
    fix: "Manual browser login required"
    success_rate: 0.0  # Can't auto-fix
    last_seen: "2026-01-04T11:00:00"

auto_fixes:
  unauthorized:
    pattern: ["unauthorized", "401", "forbidden", "403"]
    action: "kube_login"

  network:
    pattern: ["no route", "connection refused", "timeout"]
    action: "vpn_connect"

  registry:
    pattern: ["manifest unknown", "unauthorized", "podman login"]
    action: "suggest_podman_login"
```

---

## Implementation Order

### Phase 1: Core Infrastructure (Week 1)

1. [ ] Create `learned/tool_failures.yaml` memory structure
2. [ ] Create shared auto-heal compute blocks as templates
3. [ ] Add to `test_mr_ephemeral.yaml` (most used skill)
4. [ ] Add to `debug_prod.yaml` (most tool failures)
5. [ ] Test and iterate

### Phase 2: Operational Skills (Week 2)

6. [ ] Add to `investigate_alert.yaml`
7. [ ] Add to `release_to_prod.yaml`
8. [ ] Add to `deploy_to_ephemeral.yaml`
9. [ ] Add to `rollout_restart.yaml`

### Phase 3: Development Skills (Week 3)

10. [ ] Add to `review_pr.yaml`
11. [ ] Add to `create_mr.yaml`
12. [ ] Add to `start_work.yaml`
13. [ ] Add to `check_ci_health.yaml`
14. [ ] Add to `konflux_status.yaml`
15. [ ] Add to `appinterface_check.yaml`

### Phase 4: Polish (Week 4)

16. [ ] Add to remaining skills
17. [ ] Create dashboard for failure patterns
18. [ ] Add success rate tracking
19. [ ] Document patterns in README

---

## Success Metrics

| Metric | Target |
|--------|--------|
| Skills with auto-heal | 15+ |
| Auto-fix success rate | >80% |
| Learned patterns in memory | 20+ |
| Mean time to fix | <30 seconds |

---

## Todo Checklist

### Infrastructure
- [x] Create `memory/learned/tool_failures.yaml`
- [x] Create shared auto-heal module `scripts/common/auto_heal.py`
- [ ] Update skill engine to track failure/success rates

### High Priority Skills (K8s/Cluster) ✅ Complete
- [x] `test_mr_ephemeral.yaml` - bonfire namespace reserve
- [x] `debug_prod.yaml` - kubectl get pods
- [x] `investigate_alert.yaml` - kubectl get pods
- [x] `release_to_prod.yaml` - konflux get component
- [x] `deploy_to_ephemeral.yaml` - bonfire namespace reserve
- [x] `rollout_restart.yaml` - kubectl rollout restart
- [x] `konflux_status.yaml` - konflux status
- [x] `silence_alert.yaml` - alertmanager alerts
- [x] `extend_ephemeral.yaml` - bonfire namespace list
- [x] `cancel_pipeline.yaml` - tkn pipelinerun list
- [x] `check_integration_tests.yaml` - konflux list integration tests
- [x] `check_secrets.yaml` - kubectl get secrets
- [x] `environment_overview.yaml` - k8s environment summary
- [x] `scale_deployment.yaml` - kubectl get deployments
- [x] `scan_vulnerabilities.yaml` - quay check image exists

### Medium Priority Skills (GitLab/Git) ✅ Complete
- [x] `review_pr.yaml` - gitlab_mr_view
- [x] `check_ci_health.yaml` - gitlab_ci_list
- [x] `ci_retry.yaml` - gitlab init
- [x] `create_mr.yaml` - git_push
- [x] `check_mr_feedback.yaml` - gitlab_mr_list
- [x] `check_my_prs.yaml` - gitlab init
- [x] `cleanup_branches.yaml` - git init
- [x] `close_mr.yaml` - gitlab_mr_view
- [x] `hotfix.yaml` - git init
- [x] `notify_mr.yaml` - failure tracking
- [x] `mark_mr_ready.yaml` - failure tracking
- [x] `rebase_pr.yaml` - git init
- [x] `review_all_prs.yaml` - gitlab init
- [x] `sync_branch.yaml` - git init

### Medium Priority Skills (Jira) ✅ Complete
- [x] `start_work.yaml` - jira view issue
- [x] `appinterface_check.yaml` - appinterface validate
- [x] `sprint_planning.yaml` - jira list issues
- [x] `clone_jira_issue.yaml` - jira view issue
- [x] `close_issue.yaml` - jira init
- [x] `create_jira_issue.yaml` - jira create issue
- [x] `jira_hygiene.yaml` - jira init

### Lower Priority Skills (Slack/Calendar/Reporting) ✅ Complete
- [x] `weekly_summary.yaml` - git log
- [x] `standup_summary.yaml` - failure tracking
- [x] `notify_team.yaml` - slack list channels
- [x] `investigate_slack_alert.yaml` - failure tracking
- [x] `schedule_meeting.yaml` - google calendar status
- [x] `release_aa_backend_prod.yaml` - failure tracking

### Testing & Documentation
- [ ] Test auto-heal with simulated failures
- [ ] Create runbook for common failures
- [x] Update CLAUDE.md with auto-heal expectations
- [ ] Add metrics dashboard

---

## Related Files

- `server/debuggable.py` - debug_tool implementation
- `tool_modules/aa-workflow/src/memory_tools.py` - memory tools
- `tool_modules/aa-workflow/src/infra_tools.py` - kube_login, vpn_connect
- `memory/learned/patterns.yaml` - existing pattern storage
