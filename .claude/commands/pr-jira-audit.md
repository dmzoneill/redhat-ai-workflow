---
name: pr-jira-audit
description: "Audit open MRs for missing Jira issue references."
arguments:
  - name: dry_run
  - name: auto_create
---
# 🔍 PR Jira Audit

Audit open MRs for missing Jira issue references.

## Instructions

```text
skill_run("pr_jira_audit", '{}')
```

## What It Does

1. Lists all open MRs in the project
2. Checks each MR for Jira issue references in:
   - MR title (e.g., `AAP-12345 - Fix bug`)
   - MR description/body
   - Git commit messages
3. Reports compliance percentage
4. Optionally creates Jira issues for MRs without one

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `project` | GitLab project path | Auto-resolved |
| `repo_name` | Repository name from config | `automation-analytics-backend` |
| `jira_project` | Jira project for new issues | `AAP` |
| `limit` | Max MRs to audit | `20` |
| `auto_create` | Create Jira issues for missing | `false` |
| `add_comment` | Comment on MR with issue key | `false` |
| `dry_run` | Report only, no actions | `true` |

## Examples

```bash
# Basic audit (report only)
skill_run("pr_jira_audit", '{}')

# Audit and create Jira issues
skill_run("pr_jira_audit", '{"dry_run": false, "auto_create": true}')

# Full auto: create issues and comment on MRs
skill_run("pr_jira_audit", '{"dry_run": false, "auto_create": true, "add_comment": true}')

# Audit specific project
skill_run("pr_jira_audit", '{"project": "automation-analytics/automation-analytics-frontend"}')

# Audit more MRs
skill_run("pr_jira_audit", '{"limit": 50}')
```

## Output

Summary showing:
- 🟢/🟡/🟠/🔴 Compliance percentage
- ✅ MRs with Jira references (with links)
- ❌ MRs missing Jira references
- 🎫 Created Jira issues (if auto_create enabled)

## When to Use

- Sprint hygiene audits
- Ensuring all work is tracked in Jira
- Compliance/traceability requirements
- Before sprint reviews
- Onboarding check for new contributors
