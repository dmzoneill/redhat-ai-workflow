# Skill YAML Review Report

Review of 30 skill files for typos, logic errors, missing fields, broken references, and YAML syntax issues.

---

## 1. investigate_service_issues.yaml

**Issue type:** Wrong tool parameter
**Line/section:** Lines 87-91, step `list_failed_units`
**Description:** Uses `pattern: "--failed"` but `systemctl_list_units` expects `state: "failed"`. The tool signature is `systemctl_list_units(type_filter, state, user)` - there is no `pattern` parameter.
**Suggested fix:**
```yaml
args:
  state: "failed"
```

---

## 2. manage_local_services.yaml

**Issue type:** Wrong tool parameter
**Line/section:** Lines 88-92, step `list_workflow_units`
**Description:** Uses `pattern: "aa-workflow-*"` but `systemctl_list_units` only accepts `type_filter`, `state`, and `user`. The `pattern` parameter is ignored, so all units are listed instead of filtering to aa-workflow units.
**Suggested fix:** The `systemctl_list_units` tool does not support unit name pattern matching. Either extend the tool to support a pattern/glob parameter, or filter the output in a compute step. For now, document that this lists all units; filtering could be done in a parse step.

---

## 3. api_smoke_test.yaml

**Issue type:** Wrong argument format
**Line/section:** Lines 89-94, step `check_tls`
**Description:** Passes `host: "{{ inputs.base_url }}"` to `openssl_s_client`. The `base_url` input is typically a full URL like `https://api.example.com`. The openssl tool expects hostname only (e.g., `api.example.com`) and uses `-connect host:port`. Passing `https://api.example.com` would produce invalid hostname.
**Suggested fix:** Parse the URL to extract hostname and port before passing to openssl_s_client:
```yaml
# Add a compute step to parse base_url, or use:
# host: "{{ inputs.base_url | replace('https://', '') | replace('http://', '') | split(':')[0] }}"
# port: "{{ inputs.base_url.split(':')[-1] if ':' in inputs.base_url.replace('https://', '').replace('http://', '') else '443' }}"
```

---

## 4. cert_check.yaml

**Issue type:** Wrong argument format
**Line/section:** Lines 86-98, 114-122, etc.
**Description:** The `host` parameter is set to `inputs.endpoints.split(',')[0].strip()` which can be `host:port` (e.g., `api.example.com:443`). The openssl tool then builds `-connect "{host}:{port}"` with default port 443, producing `api.example.com:443:443` when the endpoint includes a port.
**Suggested fix:** Parse host and port from the endpoint string:
```yaml
# Use a compute step to parse endpoints into host and port, then pass to the tool
```

---

## 5. gke_cluster_ops.yaml

**Issue type:** Logic error / parameter misuse
**Line/section:** Lines 131-157, steps `start_instance`, `stop_instance`, `describe_instance`
**Description:** The input `cluster` is described as "GKE cluster name" but is passed to `gcloud_compute_instances_start` and `gcloud_compute_instances_stop` as the `instance` parameter. GKE clusters and GCP compute instances are different resources. Starting/stopping a "cluster" name as an instance would fail or behave unexpectedly.
**Suggested fix:** Add a separate `instance` input for compute operations, or rename `cluster` to `target` and document that for start/stop it must be a VM instance name, not a GKE cluster name.

---

## 6. data_migration_verify.yaml

**Issue type:** Logic error
**Line/section:** Lines 276-284, step `podman_db_check`
**Description:** Uses `inputs.source_db` as the Podman container name. The `source_db` input is described as "Source database connection string or path" - for PostgreSQL it could be `postgresql://user:pass@host:5432/db`, for SQLite a file path. Using a connection string or path as a container name will fail.
**Suggested fix:** Use a fixed container name like `postgres` when the db_type is postgres and we're checking a container, or make the container name a separate optional input. Alternatively, skip this step when source_db is a connection string rather than a container reference.

---

## 7. sprint_planning.yaml

**Issue type:** Potential Python/Jinja compatibility
**Line/section:** Lines 246, 272
**Description:** Uses `inputs.get('check_quality', true)` and `inputs.get('auto_add', false)`. In Jinja2, `true` and `false` are valid. If the eval fallback is used (when Jinja is unavailable), Python's `eval()` would raise NameError because Python uses `True`/`False`.
**Suggested fix:** Use `True` and `False` for broader compatibility, or ensure Jinja is always used for condition evaluation.

---

## 8. weekly_summary.yaml

**Issue type:** Hardcoded path
**Line/section:** Line 222, step `get_session_logs`
**Description:** Hardcodes `Path.home() / "src/redhat-ai-workflow/memory/logs"`. This path may not exist on all systems or workspaces.
**Suggested fix:** Use config.json or workspace-relative path (e.g., from SKILLS_DIR or workspace root).

---

## 9. weekly_summary.yaml / standup_summary.yaml

**Issue type:** Inconsistent default
**Line/section:** weekly_summary line 361, standup_summary line 323
**Description:** `is_slack = inputs.get('slack_format', True)` defaults to True, but the input definition has `default: false` for slack_format. When the user doesn't pass slack_format, the input will be false, but the compute block defaults to True when the key is missing - creating inconsistency.
**Suggested fix:** Use `inputs.get('slack_format', False)` to match the input default, or `inputs.get('slack_format', inputs.get('format') == 'slack')` to derive from format.

---

## 10. scan_vulnerabilities.yaml

**Issue type:** Incorrect skill_run syntax in template
**Line/section:** Line 575
**Description:** The template shows `skill_run(skill_name="cve_fix", inputs='...')` - the skill_run MCP tool expects positional args: `skill_run("cve_fix", '{"downstream_component": "..."}')`. The keyword form may work depending on tool binding but could confuse users.
**Suggested fix:** Use the standard form: `skill_run("cve_fix", '{"downstream_component": "automation-analytics-backend"}')`

---

## 11. api_smoke_test.yaml

**Issue type:** Incorrect skill_run syntax in template
**Line/section:** Line 344
**Description:** Template shows `skill_run(skill_name="debug_prod", inputs='{"namespace": "main"}')` - should use positional form for consistency.
**Suggested fix:** `skill_run("debug_prod", '{"namespace": "main"}')`

---

## Files with no issues found

The following files were reviewed and no issues were identified:
- meeting_notes_review.yaml
- manage_secrets.yaml
- local_dev_environment.yaml
- local_build_test.yaml
- inscope_research.yaml
- cloud_inventory.yaml
- dev_workflow_orchestrator.yaml
- debug_local_db.yaml
- email_digest.yaml
- aws_rds_debug.yaml
- gdrive_research.yaml
- ansible_configure_vm.yaml
- standup_summary.yaml (except item 9)
- scan_vulnerabilities.yaml (except item 11)
- review_local_changes.yaml
- release_to_prod.yaml (except item 10)
- rebase_pr.yaml
- jira_hygiene.yaml
- konflux_status.yaml
- investigate_alert.yaml (except item 1)
- environment_overview.yaml
- debug_prod.yaml
- coffee.yaml
- ci_retry.yaml

---

## Summary

| Severity | Count |
|----------|-------|
| Wrong tool parameter (will fail) | 2 |
| Logic error | 2 |
| Wrong argument format | 2 |
| Hardcoded value | 1 |
| Inconsistent default | 1 |
| Documentation/template | 2 |

**Priority fixes:** Items 1, 2, 3, 4, 5, 6 will cause incorrect behavior or failures. Items 7-11 are lower priority or documentation-only.

**Note:** `today` in release_to_prod is correctly provided by the skill engine context.
