# Skill Review Batch 3 Report

Review of 42 YAML skill files for bugs, errors, and issues.

## Confirmed Issues

### 1. Missing `result` assignment in compute blocks

| File | Line | Issue | Fix |
|------|------|-------|-----|
| `skills/list_presentations.yaml` | 52-67 | `build_summary` compute block sets `result = list_result or "No presentations found"` then builds `summary = "\n".join(lines)` but never assigns `result = summary`. The `output: summary` captures `result`, so output would be wrong. | Add `result = summary` before the block ends. |
| `skills/export_presentation.yaml` | 51-66 | Same pattern: sets `result = export_result or "Export failed"` then builds `summary` but never assigns `result = summary`. | Add `result = summary` before the block ends. |

### 2. Dict access in Python compute blocks (dot notation instead of bracket notation)

| File | Line | Issue | Fix |
|------|------|-------|-----|
| `skills/clone_jira_issue.yaml` | 203-204 | In `track_clones` compute block: `clone_result.new_key` and `source_info.type` - step outputs are dicts. Dot notation fails in Python. | Use `clone_result.get("new_key")` and `source_info.get("type", "unknown")`. |
| `skills/scale_deployment.yaml` | 324, 358 | In compute blocks: `final_state.running_count` and `final_state.all_running` - final_state is a dict. | Use `final_state.get("running_count", 0)` and `final_state.get("all_running", False)`. |
| `skills/check_my_prs.yaml` | 158-162 | In `resolve_project` compute: `inputs.project`, `inputs.repo_name` - inputs is typically a dict. | Use `inputs.get("project")`, `inputs.get("repo_name")`. |
| `skills/summarize_findings.yaml` | 120 | In compute block: `inputs.conclusion` - inputs is a dict. | Use `inputs.get("conclusion", "")`. |
| `skills/compare_options.yaml` | 58 | In compute block: `inputs.criteria.split(',')` - when inputs.get('criteria') is truthy, uses `inputs.criteria` which may fail if inputs is a dict. | Use `inputs.get("criteria", "").split(",")`. |
| `skills/performance/collect_daily.yaml` | 55 | In compute block: `inputs.date` - inputs is a dict. | Use `inputs.get("date")` or `inputs["date"]`. |

### 3. Undefined Jinja variables

| File | Line | Issue | Fix |
|------|------|-------|-----|
| `skills/extend_ephemeral.yaml` | 319 | `timestamp: {{ now().isoformat() }}` - `now()` is not a standard Jinja builtin. | Use `{{ '' \| default('') }}` with a datetime from a prior step, or inject `now` via the skill engine, or use a compute step to generate the timestamp. |

### 4. Jinja `len()` not available

| File | Line | Issue | Fix |
|------|------|-------|-----|
| `skills/review_all_prs.yaml` | 533 | `total_mrs: "{{ len(mr_analysis) }}"` - Jinja2 does not have `len()` builtin. | Use `{{ mr_analysis \| length }}`. |
| `skills/check_my_prs.yaml` | 412 | `total_mrs: "{{ len(my_mrs) }}"` - same issue. | Use `{{ my_mrs \| length }}`. |

### 5. Jinja default with wrong type

| File | Line | Issue | Fix |
|------|------|-------|-----|
| `skills/memory_init.yaml` | 302-306 | `(backup_info \| default('')).backup_location` - when backup_info is missing, default('') gives empty string. Accessing `.backup_location` on '' would fail. | Use `(backup_info \| default({})).get('backup_location', 'N/A')` or ensure default is `{}` not `''`. |

### 6. Step output variable reference

| File | Line | Issue | Fix |
|------|------|-------|-----|
| `skills/monitor_jira_comments.yaml` | 76-81 | Step `search_sprint_issues` has no `output:` - the parse_issues step references `search_sprint_issues` directly. If the engine stores tool output under step name, this may work. If not, parse_issues would get undefined. | Add `output: search_results` to search_sprint_issues step and reference `search_results` in parse_issues. |

### 7. `outputs:` structure (non-standard)

| File | Line | Issue | Fix |
|------|------|-------|-----|
| `skills/slack_persona_sync.yaml` | 67-73 | Uses `outputs: result: "..."` and `report: \|` (keys) instead of standard list format `outputs: - name: X, value: Y`. May cause parsing or runtime issues. | Convert to standard format: `outputs: - name: result, value: "{{ sync_result }}"` and `- name: report, value: \| ...` |

### 8. `outputs` section before `steps`

| File | Line | Issue | Fix |
|------|------|-------|-----|
| `skills/knowledge_refresh.yaml` | 48-51 | `outputs:` section appears before `steps:` - unusual ordering. YAML allows any order, but some parsers may expect steps before outputs. | Move outputs section after steps for consistency with other skills. |

### 9. Missing `output:` on compute step

| File | Line | Issue | Fix |
|------|------|-------|-----|
| `skills/sprint_autopilot.yaml` | 94-137 | Step `evaluate_safety` has compute block that sets `result = {...}` but no `output:` line. Downstream steps (`abort_if_unsafe`, `stash_if_needed`) reference `evaluate_safety.can_proceed` and `evaluate_safety.needs_stash`. | Add `output: evaluate_safety` to the step to explicitly capture the result. |

---

## Summary by Category

| Category | Count |
|----------|-------|
| Missing result assignment | 2 |
| Dict dot notation (Python) | 6 |
| Undefined Jinja variables | 1 |
| Jinja len() vs length filter | 2 |
| Jinja default wrong type | 1 |
| Step output reference | 1 |
| outputs structure | 1 |
| Section ordering | 1 |
| Missing output | 1 |

**Total confirmed issues: 16**

---

## Files with No Issues Found

The following files were reviewed and no confirmed runtime-impacting issues were found:

- skills/learn_pattern.yaml
- skills/memory_init.yaml (except the backup_info default noted above)
- skills/research_topic.yaml
- skills/knowledge_refresh.yaml (except outputs ordering)
- skills/sync_discovered_work.yaml
- skills/performance/export_report.yaml
- skills/performance/evaluate_questions.yaml
- skills/performance/backfill_missing.yaml
- skills/review_pr_multiagent_test.yaml
- skills/summarize_findings.yaml (except inputs.conclusion)
- skills/review_pr.yaml
- skills/slop_fix.yaml
- skills/review_all_prs.yaml (except len())
- skills/check_my_prs.yaml (except inputs and len)
- skills/pr_jira_audit.yaml
- skills/check_mr_feedback.yaml
- skills/scale_deployment.yaml (except final_state dot notation)
- skills/standup_summary.yaml
- skills/extend_ephemeral.yaml (except now())
- skills/monitor_jira_comments.yaml
- skills/memory_cleanup.yaml
- skills/coffee.yaml
- skills/check_integration_tests.yaml
- skills/notify_mr.yaml
- skills/mark_mr_ready.yaml
- skills/add_project.yaml
- skills/investigate_slack_alert.yaml
- skills/sprint_autopilot.yaml (except evaluate_safety output)
- skills/beer.yaml
- skills/create_slide_deck.yaml
- skills/test_mr_ephemeral.yaml
- skills/update_docs.yaml
- skills/memory_view.yaml
- skills/investigate_service_issues.yaml
- skills/slack_daemon_control.yaml
- skills/performance/collect_daily.yaml
- skills/deploy_to_ephemeral.yaml
