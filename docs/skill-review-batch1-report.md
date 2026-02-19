# Skill File Review Report - Batch 1 of 4

**Review Date:** 2026-02-18
**Files Reviewed:** 32 skill files
**Scope:** YAML syntax, typos, missing fields, wrong references, logic errors, undefined variables

---

## Summary

| Severity | Count |
|----------|-------|
| Logic Error | 6 |
| Wrong Reference / Undefined Variable | 5 |
| Typo / Wrong Variable Name | 3 |
| Missing Field / Config | 2 |
| Potential Issue | 2 |

---

## Issues Found

### 1. skills/test_mr_ephemeral.yaml

| Line | Issue Type | Description | Suggested Fix |
|------|------------|-------------|---------------|
| 1236 | Wrong Reference | Output template references `{{ cfg.jira.url }}` but `cfg` from `load_config` does not include a `jira` key. The load_config step outputs: gitlab_project, konflux_namespace, quay_pr_repo, quay_pr_namespace, quay_release_namespace, ephemeral_kubeconfig, repo_path. | Add `jira_url` to the load_config step output: `jira_url: config.get("jira", {}).get("url", "https://issues.redhat.com")`, then use `{{ cfg.jira_url }}` in the template. |
| 259-262 | Missing Argument | `gitlab_ci_status` is called with only `project` but not `branch`. This returns the default branch's pipeline, not the MR's pipeline. | Add `branch: "{{ mr_info.branch }}"` to get the pipeline for the MR's branch. Note: `mr_info` may not exist yet when this step runs (it runs conditionally on `inputs.mr_id`). Consider passing branch from mr_info when available. |

---

### 2. skills/mark_mr_ready.yaml

| Line | Issue Type | Description | Suggested Fix |
|------|------------|-------------|---------------|
| 518 | Wrong Variable Name | `detect_ready_failures` references `mr_details_raw` but the step that fetches MR details (`get_mr_details`) outputs to `mr_details`. | Change `mr_details_raw` to `mr_details` in the detect_ready_failures compute block. |

---

### 3. skills/notify_mr.yaml

| Line | Issue Type | Description | Suggested Fix |
|------|------------|-------------|---------------|
| 422 | Wrong Variable Name | `detect_notify_failures` references `mr_details_raw` but the step that fetches MR details (`get_mr_details`) outputs to `mr_result`. | Change `mr_details_raw` to `mr_result`. |
| 439 | Wrong Variable Name | `detect_notify_failures` references `slack_result_raw` but the step that posts to Slack (`post_to_team`) outputs to `slack_result`. | Change `slack_result_raw` to `slack_result`. |

---

### 4. skills/review_all_prs.yaml

| Line | Issue Type | Description | Suggested Fix |
|------|------------|-------------|---------------|
| 502 | Logic Error | `is_slack = inputs.get('slack_format', True)` - The input `slack_format` has `default: false` per the inputs definition. Using `True` as the fallback contradicts the declared default. | Change to `inputs.get('slack_format', False)` to match the input default. |

---

### 5. skills/slack_daemon_control.yaml

| Line | Issue Type | Description | Suggested Fix |
|------|------------|-------------|---------------|
| 156-161 | Logic Error | When daemon is already running, the code sets `result` and then `raise SystemExit`. `SystemExit` terminates the entire Python process, not just the compute step. The intent appears to be "return early with this result." | Restructure the code: wrap the daemon start logic in an `else` block so that when the daemon is already running, we set `result` and do not fall through to the start logic. Remove the `raise SystemExit`. |

---

### 6. skills/submit_expense.yaml

| Line | Issue Type | Description | Suggested Fix |
|------|------------|-------------|---------------|
| 363-366 | Logic Error | In `parse_receipt_status`, the code mutates `expense_info["amount"]` as a side effect. The step's `result` dict does not include `amount`. Skill engines typically pass step outputs to subsequent steps; mutating a previous step's output may not persist. | Include `amount` in the `receipt_check` output: `result = {"receipt_ready": ..., "need_download": ..., "status_text": ..., "amount": expense_info.get("amount") or (amount_match.group(1) if amount_match else None)}`. Or add a separate step to merge amount into expense_info. |
| 334-336 | Logic Error | Same pattern in `parse_download_result` - mutates `expense_info["amount"]` and `receipt_check["receipt_ready"]`, `receipt_check["need_download"]`. These mutations may not persist. | Include the updated values in the step's result and have downstream steps use them. |

---

### 7. skills/performance/collect_daily.yaml

| Line | Issue Type | Description | Suggested Fix |
|------|------------|-------------|---------------|
| 115 | Wrong Reference | Uses `config.get("projects", {})` but the config structure (per config.json.example) uses `repositories`, not `projects`. | Change to `config.get("repositories", {})`. |

---

### 8. skills/deploy_to_ephemeral.yaml

| Line | Issue Type | Description | Suggested Fix |
|------|------------|-------------|---------------|
| 229-244 | Potential Dead Code | The `determine_image_param` step builds `image_config` with `param` and `clowdapp` logic for billing vs main, but `deploy_app` uses `set_image_tag` from inputs directly and does not use `image_config.param`. When `inputs.component == "billing"`, the deploy may not use the correct ClowdApp. | Verify whether `bonfire_deploy` handles component internally. If not, pass the appropriate set-parameter from `image_config` to the deploy step. If the tool auto-detects, document this and consider removing the unused `image_config` step. |

---

### 9. skills/create_jira_issue.yaml

| Line | Issue Type | Description | Suggested Fix |
|------|------------|-------------|---------------|
| 408-412 | Potential API Mismatch | `jira_update_issue` is called with `fields: "labels"` and `values: "{{ inputs.labels }}"`. The Jira API typically expects a JSON object for field updates (e.g., `{"labels": ["label1", "label2"]}`). | Verify the `jira_update_issue` tool's expected signature. If it expects a field map, use `fields: {"labels": [inputs.labels.split(",")]}` or equivalent structure. |

---

### 10. skills/close_issue.yaml

| Line | Issue Type | Description | Suggested Fix |
|------|------------|-------------|---------------|
| 317 | Non-Standard Parameter | `skill_run` is called with `execute: true`. The skill_run tool may support this for "plan vs execute" mode, but it's worth verifying. | Confirm that `execute` is a supported parameter for `skill_run`. If not, remove it. |

---

## Files With No Issues Found

The following files were reviewed and no issues were found:

- skills/create_jira_issue.yaml (aside from potential jira_update_issue API)
- skills/close_issue.yaml (aside from execute param)
- skills/check_my_prs.yaml
- skills/pr_jira_audit.yaml
- skills/notify_mr.yaml (aside from wrong variable names in detect_notify_failures)
- skills/create_mr.yaml
- skills/reward_zone.yaml
- skills/reward_zone_send.yaml
- skills/jira_hygiene_all.yaml
- skills/work_analysis.yaml
- skills/workflow_health_check.yaml
- skills/vm_snapshot_workflow.yaml
- skills/vm_network_setup.yaml
- skills/vm_lab_setup.yaml
- skills/security_audit.yaml
- skills/schedule_cron_jobs.yaml
- skills/s3_data_ops.yaml
- skills/remote_host_diagnostics.yaml
- skills/ollama_inference_test.yaml
- skills/network_connectivity_check.yaml
- skills/mysql_debug.yaml
- skills/meeting_scheduler_manage.yaml
- skills/cve_fix.yaml
- skills/notify_team.yaml

---

## Recommendations

1. **Add jira_url to test_mr_ephemeral load_config** - High priority; the output template will fail when ClowdApp selection includes a Jira key.
2. **Fix wrong variable names** - Medium priority; failure detection steps will not work correctly.
3. **Fix collect_daily config key** - Medium priority; the skill will not find any repositories.
4. **Fix slack_daemon_control SystemExit** - Medium priority; prevents graceful handling when daemon is already running.
5. **Fix submit_expense mutation logic** - Medium priority; amount and receipt status may not propagate correctly.
