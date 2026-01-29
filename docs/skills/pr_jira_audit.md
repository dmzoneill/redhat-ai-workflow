# 🔍 pr_jira_audit

> Audit open MRs for missing Jira issue references

## Overview

The `pr_jira_audit` skill audits open merge requests (MRs) for missing Jira issue references. It scans each open MR's title, description, and commit messages looking for Jira issue keys. For MRs without linked Jira issues, it reports the gap and can optionally create new issues automatically.

This skill is essential for sprint hygiene, ensuring all work is tracked in Jira, and meeting compliance/traceability requirements.

## Quick Start

```text
skill_run("pr_jira_audit", '{}')
```

Or create issues for missing MRs:

```text
skill_run("pr_jira_audit", '{"dry_run": false, "auto_create": true}')
```

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `project` | string | No | `""` | GitLab project path (resolved from repo_name if not provided) |
| `repo_name` | string | No | `"automation-analytics-backend"` | Repository name from config |
| `jira_project` | string | No | `"AAP"` | Jira project key for creating new issues |
| `limit` | integer | No | `20` | Maximum number of MRs to audit |
| `auto_create` | boolean | No | `false` | Automatically create Jira issues for MRs without one |
| `add_comment` | boolean | No | `false` | Add a comment to the MR with the created Jira issue key |
| `dry_run` | boolean | No | `true` | If true, report what would be done without taking action |
| `slack_format` | boolean | No | `false` | Use Slack link format in summary |

## What It Does

1. **Load Developer Persona** - Ensures GitLab and Jira tools are available
2. **Resolve Project** - Determines which GitLab project to audit:
   - Uses explicit `project` input if provided
   - Resolves from `repo_name` via config
   - Falls back to current directory
3. **List Open MRs** - Fetches all open MRs from GitLab
4. **Parse MRs** - Extracts MR IDs, titles, and authors
5. **Audit First MR (Detailed)** - For the first MR:
   - Gets full details including description
   - Gets commit messages
   - Searches all sources for Jira keys
6. **Audit All MRs (Quick)** - For remaining MRs:
   - Quick pattern match on titles only
7. **Create Jira Issues** (if `auto_create: true`):
   - Creates Task issue for each missing MR
   - Includes MR title, author, and link in description
8. **Comment on MR** (if `add_comment: true`):
   - Adds comment with created Jira issue link
9. **Build Summary** - Generates compliance report
10. **Track Results** - Saves audit to memory for trend analysis
11. **Learn from Failures** - Detects and remembers common errors

## Jira Key Detection

The skill searches for Jira keys (e.g., `AAP-12345`, `RHCLOUD-1234`) in:

| Location | Example |
|----------|---------|
| MR Title | `AAP-12345: Add billing endpoint` |
| MR Description | `Fixes AAP-12345` |
| Commit Messages | `fix(billing): resolve issue AAP-12345` |

## Compliance Levels

| Compliance % | Status | Emoji |
|--------------|--------|-------|
| >= 90% | Excellent | 🟢 |
| >= 70% | Good | 🟡 |
| >= 50% | Fair | 🟠 |
| < 50% | Poor | 🔴 |

## Example Usage

### Default Audit (Dry Run)

```python
skill_run("pr_jira_audit", '{}')
```

### Create Issues Automatically

```python
skill_run("pr_jira_audit", '{"dry_run": false, "auto_create": true}')
```

### Audit Specific Project

```python
skill_run("pr_jira_audit", '{"project": "automation-analytics/automation-hub"}')
```

### Audit More MRs

```python
skill_run("pr_jira_audit", '{"limit": 50}')
```

### Add Comments to MRs

```python
skill_run("pr_jira_audit", '{"dry_run": false, "auto_create": true, "add_comment": true}')
```

### Slack-Formatted Output

```python
skill_run("pr_jira_audit", '{"slack_format": true}')
```

## Example Output

```text
## 🔍 PR Jira Audit Results

**Project:** automation-analytics/automation-analytics-backend
**Total MRs Audited:** 15
**Dry Run:** Yes

### 🟡 Compliance: 73%
- ✅ **With Jira:** 11
- ❌ **Missing Jira:** 4

### ❌ MRs Missing Jira Reference

- !1502: Update dependencies for Q1 2026
  - Author: jsmith
- !1498: Fix flaky test in billing module
  - Author: djones
- !1495: Refactor API client error handling
  - Author: mwilson
- !1492: Add debug logging for auth flow
  - Author: abrown

### ✅ MRs With Jira Reference

- !1501: AAP-12345 - Add vCPU billing endpoint → [AAP-12345](https://issues.redhat.com/browse/AAP-12345)
- !1500: AAP-12340 - Fix subscription validation → [AAP-12340](https://issues.redhat.com/browse/AAP-12340)
- !1499: AAP-12338 - Update pricing tiers → [AAP-12338](https://issues.redhat.com/browse/AAP-12338)
- ... and 8 more

---

## Quick Actions

### Create Jira Issues for Missing MRs

**Dry run mode** - To actually create issues, run:
```python
skill_run("pr_jira_audit", '{"dry_run": false, "auto_create": true}')
```

Or create issues manually:
```python
skill_run("create_jira_issue", '{"summary": "Update dependencies for Q1 2026", "project": "AAP"}')
```
```

## Outputs

| Output | Description |
|--------|-------------|
| `summary` | Full markdown audit report |
| `context.project` | GitLab project audited |
| `context.total_audited` | Number of MRs audited |
| `context.missing_count` | Number missing Jira references |
| `context.compliant_count` | Number with Jira references |
| `context.dry_run` | Whether this was a dry run |

## Error Handling

The skill detects and learns from common errors:

| Error | Cause | Auto-Fix |
|-------|-------|----------|
| "no such host" | VPN not connected | Prompts to run `vpn_connect()` |
| "unauthorized" | Token expired | Prompts to check GitLab token |

## MCP Tools Used

- `persona_load` - Load developer persona
- `gitlab_mr_list` - Fetch open MRs
- `gitlab_mr_view` - Get MR details
- `gitlab_mr_commits` - Get MR commit messages
- `gitlab_mr_comment` - Add comment to MR
- `skill_run` - Invoke `create_jira_issue` skill
- `memory_session_log` - Log audit
- `learn_tool_fix` - Remember error patterns

## Related Skills

- [jira_hygiene_all](./jira_hygiene_all.md) - Batch Jira issue hygiene
- [create_jira_issue](./create_jira_issue.md) - Create individual Jira issues
- [review_pr](./review_pr.md) - Review a specific MR
- [check_prs](./check_prs.md) - Check status of your open MRs
