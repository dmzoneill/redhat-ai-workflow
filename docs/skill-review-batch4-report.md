# Skill File Review Report - Batch 4 of 4

## Summary

Reviewed 31 skill files for YAML syntax errors, typos, logic errors, missing fields, broken references, and inconsistencies.

---

## Issues Found

### 1. skills/edit_slide_deck.yaml

**Issue type:** Logic error / Missing output
**Line:** 152-179 (build_summary step)
**Description:** The `build_summary` compute step references `view_result`, `add_result`, etc. but uses `'view_result' in dir()` which may not work correctly in the skill execution context. The step also doesn't assign `result` in all code paths - the variable `summary` is built but the compute block should set `result = summary` before the `output: summary` line.
**Suggested fix:** Ensure the compute block ends with `result = summary` (or equivalent) so the output is properly captured. The current code builds `summary` but the last line is `lines.append(...)` - verify the `result` assignment.

---

### 2. skills/slop_fix.yaml

**Issue type:** Logic error / Self-referential tool call
**Line:** 94-111
**Description:** The skill calls `tool: slop_fix` in step `apply_fixes`, but the skill itself is named `slop_fix`. This creates a circular reference - the skill is calling itself as a tool. The tool should likely be something like `slop_apply_fixes` or a different MCP tool.
**Suggested fix:** Verify the correct tool name. If the intent is to apply fixes via a separate tool, use that tool (e.g., `slop_apply` or similar). If the skill is meant to orchestrate the slop fix workflow, the step should call a different tool, not the skill name.

---

### 4. skills/test_error_recovery.yaml

**Issue type:** Logic error (intentional for testing)
**Line:** 24
**Description:** The comment says `# ❌ Should be inputs.get("test_value")` - the code uses `inputs.test_value` which will raise AttributeError if `test_value` is missing. This appears intentional for testing error recovery.
**Suggested fix:** If this is a test skill for error recovery, consider adding a note in the description that it deliberately triggers errors. Otherwise, fix to use `inputs.get("test_value", "hello")`.

---

### 5. skills/memory_cleanup.yaml

**Issue type:** Logic error / Wrong attribute access
**Line:** 288-294 (track_cleanup_history step)
**Description:** The compute block uses `analysis.total`, `analysis.counts.active_issues`, etc. but `analysis` is a dict - it should use bracket notation: `analysis["total"]`, `analysis["counts"]["active_issues"]`.
**Suggested fix:** Change to dict access:
```python
"total_stale": analysis.get("total", 0) if analysis else 0,
"active_issues_cleaned": analysis.get("counts", {}).get("active_issues", 0) if analysis else 0,
"open_mrs_cleaned": analysis.get("counts", {}).get("open_mrs", 0) if analysis else 0,
"ephemeral_cleaned": analysis.get("counts", {}).get("ephemeral_namespaces", 0) if analysis else 0,
"archived_sessions": archive_result.get("archived", 0) if archive_result else 0,
```

---

### 6. skills/investigate_slack_alert.yaml

**Issue type:** Wrong variable reference
**Line:** 481-483 (detect_slack_alert_failures step)
**Description:** References `pods_raw` and `logs_raw` but the actual output variables from earlier steps are `pod_status` and `recent_logs`. Similarly `jira_search_raw` - the step that gets Jira data outputs to `existing_issues` and `billing_issues`.
**Suggested fix:** Change variable references:
```python
pods_text = str(pod_status) if 'pod_status' in dir() and pod_status else ""
logs_text = str(recent_logs) if 'recent_logs' in dir() and recent_logs else ""
jira_text = str(existing_issues) if 'existing_issues' in dir() and existing_issues else ""
# Also need to include billing_issues if checking Jira
```

---

### 7. skills/add_project.yaml

**Issue type:** Wrong tool/args / Invalid YAML structure
**Line:** 89-94, 98-104, 117-123
**Description:** Uses `outputs:` (plural) instead of `output:` (singular) for tool steps. Uses `tool: shell` which may be blocked by CLI-to-MCP rules. The `project_detect` tool returns a single result - the `outputs:` with list format may not match the skill engine's expected structure.
**Suggested fix:** Change `outputs:` to `output:` and use single output variable names. Replace `shell` with appropriate MCP tools if available.

**Issue type:** Wrong config key
**Line:** 302 (track_project_additions)
**Description:** References `name`, `path`, `gitlab`, `jira_project` as if they are direct variables, but they come from `inputs`. The `path` variable might not exist - should use `inputs.get("path", "unknown")`.
**Suggested fix:** Use `inputs.get("path", "unknown")` consistently.

**Issue type:** Invalid outputs structure
**Line:** 333-337
**Description:** Outputs use object format `project_name: "{{ ... }}"` instead of list format `- name: project_name` / `value: "{{ ... }}"` used by other skills.
**Suggested fix:** Use standard outputs format:
```yaml
outputs:
  - name: project_name
    value: "{{ name | default(detected_name) }}"
  - name: config_updated
    value: true
  ...
```

---

### 8. skills/slack_persona_sync.yaml

**Issue type:** Invalid YAML structure
**Line:** 70-74
**Description:** Uses `report:` as a top-level key with a multi-line string. The standard skill structure uses `outputs:` with `- name: report` and `value: |`.
**Suggested fix:** Move report into outputs:
```yaml
outputs:
  - name: result
    value: "{{ sync_result }}"
  - name: report
    value: |
      ## Slack Persona Sync Complete
      {{ sync_result }}
```

**Issue type:** Self-referential tool call
**Line:** 52-58
**Description:** The skill calls `tool: slack_persona_sync` - the same name as the skill. The tool exists in aa_slack_persona module. This is valid - the skill wraps the tool. No fix needed.

---

### 9. skills/performance/export_report.yaml

**Issue type:** Potential KeyError
**Line:** 48-51 (get_quarter)
**Description:** When parsing `inputs.quarter` like "Q1 2026", the code does `parts[0][1]` to get quarter number. If user passes "Q10 2026" or malformed input, this could fail. Also `parts[1]` could raise IndexError if format is wrong.
**Suggested fix:** Add validation:
```python
if len(parts) < 2:
    raise ValueError("Quarter must be in format 'Q1 2026'")
quarter = int(parts[0][1])  # 'Q1' -> 1
if quarter not in (1, 2, 3, 4):
    raise ValueError("Quarter must be 1-4")
year = int(parts[1])
```

---

### 10. skills/performance/evaluate_questions.yaml

**Issue type:** Invalid function reference
**Line:** 207
**Description:** Uses `run_skill("ollama_generate_wrapper", {...})` - this function may not exist in the skill execution context.
**Suggested fix:** Use the appropriate MCP tool for LLM generation (e.g., a tool that calls Ollama/Claude). Check what tools are available for text generation.

---

### 11. skills/performance/backfill_missing.yaml

**Issue type:** Wrong skill path
**Line:** 106
**Description:** Calls `run_skill("performance/collect_daily", {"date": date_str})` - the skill path format may be wrong. Skills are typically referenced by name like `collect_daily` not `performance/collect_daily`.
**Suggested fix:** Use `run_skill("collect_daily", {"date": date_str})` or verify the correct skill invocation format.

**Issue type:** Wrong tool
**Line:** 125-128
**Description:** Uses `tool: performance_status` - verify this tool exists. The args use `quarter: "Q{{ missing_info.quarter }} {{ missing_info.year }}"` which may need to be a string like "Q1 2026".
**Suggested fix:** Verify `performance_status` tool exists and accepts the quarter format.

---

### 12. skills/check_mr_feedback.yaml

**Issue type:** Wrong default / Logic error
**Line:** 357
**Description:** `is_slack = inputs.get('slack_format', True)` - the input default is `false` (line 54), so using `True` as the fallback in the compute block overrides the input. Should be `inputs.get('slack_format', False)` to match the input default.
**Suggested fix:** Change to `is_slack = inputs.get('slack_format', False)` for consistency with the input definition.

---

### 13. skills/memory_view.yaml

**Issue type:** Wrong key / Logic error
**Line:** 140, 375
**Description:** Session log files use `entries` as the key (per memory/sessions/*.yaml and example.yaml), but memory_view uses `session_data.get("actions", [])`. This will always return empty list.
**Suggested fix:** Change to `session_data.get("entries", [])` or `session_data.get("entries", session_data.get("actions", []))` for backward compatibility. Each entry has `action`, `details`, `time` keys.

---

### 14. skills/compare_options.yaml

**Issue type:** Wrong variable reference in condition
**Line:** 103-104, 114-115, 124-125
**Description:** Conditions use `len(parsed.options)` - in Jinja/expression context, `parsed` might need to be accessed differently. Also `parsed` is the output of `parse_options` step - ensure the variable is in scope.
**Suggested fix:** Verify the condition syntax. Some skill engines use `parsed.options|length` or `parsed['options']|length` for Jinja.

**Issue type:** Wrong variable in build_comparison
**Line:** 176
**Description:** References `project` but when `detect_project` runs (condition: not inputs.project), it outputs to `project`. When `set_project` runs, it also outputs to `project`. The variable `project` might not be defined if both conditions have different execution paths. In `build_comparison`, `project` could be undefined if `inputs.project` was provided (set_project runs) - need to ensure project is always set.
**Suggested fix:** Use `project or inputs.project or 'automation-analytics-backend'` for safety.

---

### 15. skills/review_pr_multiagent_test.yaml

**Issue type:** Wrong variable check
**Line:** 127-128, 133-134
**Description:** Uses `'architecture_review' in globals()` - in skill compute blocks, variables from previous steps may not be in `globals()`. Should use the standard pattern `'architecture_review' in dir()` or check if the output exists.
**Suggested fix:** Use `'architecture_review' in dir() and architecture_review` or similar pattern used in other skills.

---

### 16. skills/summarize_findings.yaml

**Issue type:** Wrong Jinja syntax
**Line:** 191
**Description:** `details: "{% if inputs.conclusion %}Conclusion: {{ inputs.conclusion[:100] }}{% endif %}"` - the `[:100]` slice may not work in Jinja if `inputs.conclusion` is None. Also `inputs.conclusion` could be undefined.
**Suggested fix:** Use `(inputs.conclusion or '')[:100]` or add a default.

---

### 17. skills/learn_pattern.yaml

**Issue type:** Potential structure mismatch
**Line:** 172-174
**Description:** Uses `data[category]` where category can be "general", "pod_errors", etc. But memory_view and other skills expect `patterns.error_patterns` as a list. The learn_pattern skill uses a different structure (category-based). This could cause memory_view to show no patterns if learn_pattern stores in `data["general"]` but memory_view reads `patterns.get("error_patterns", [])`.
**Suggested fix:** Verify the patterns.yaml schema. If memory_view expects `error_patterns`, learn_pattern may need to also add to that list, or memory_view should read from category-based structure.

---

### 18. skills/reindex_all_vectors.yaml

**Issue type:** Wrong import / Missing output
**Line:** 64
**Description:** Uses `from server.utils import load_config` - the project may use `scripts.common.config_loader` for config. Verify the correct import path.
**Suggested fix:** Check other skills - bootstrap_knowledge uses `from server.utils import load_config`, add_project and investigate_slack_alert use `from scripts.common.config_loader import load_config`. There may be two different config loaders. Use the one that matches the project structure.

---

### 19. skills/add_project.yaml - path variable

**Issue type:** Wrong variable reference
**Line:** 79-80 (validate_path)
**Description:** Uses `command: "test -d '{{ path }}'"` - the `path` comes from `inputs.path`. In skill template context, use `{{ inputs.path }}` to be explicit.
**Suggested fix:** Use `{{ inputs.path }}` in the command.

---

## Files with No Issues Found

The following files were reviewed and appear correct:
- gather_context.yaml
- hello_world.yaml
- bootstrap_knowledge.yaml
- build_persona_style.yaml
- memory_edit.yaml
- memory_init.yaml
- knowledge_refresh.yaml
- list_presentations.yaml
- sync_discovered_work.yaml
- export_presentation.yaml
- bootstrap_all_knowledge.yaml
- research_topic.yaml
- clone_jira_issue.yaml

---

## Recommendations

1. **Session log format:** Session files use `entries` but memory_view reads `actions`. Update memory_view to use `session_data.get("entries", [])`.
2. **Replace run_skill() in compute blocks:** Skills that use `run_skill()` in compute blocks may need to use `tool: skill_run` as a separate step instead.
3. **Add project path validation:** For add_project, ensure `inputs.path` is used consistently.
4. **Fix slop_fix circular reference:** The skill should not call itself as a tool.
