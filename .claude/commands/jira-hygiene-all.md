---
name: jira-hygiene-all
description: "Run hygiene checks on all your assigned Jira issues."
arguments:
  - name: dry_run
---
# 🧹 Jira Hygiene All

Run hygiene checks on all your assigned Jira issues.

## Instructions

```text
skill_run("jira_hygiene_all", '{}')
```

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `status` | Filter by status (e.g., "In Progress", "New") | All statuses |
| `limit` | Maximum number of issues to process | `200` |
| `auto_fix` | Automatically fix issues where possible | `true` |
| `auto_transition` | Auto-transition New → Refinement when ready | `true` |
| `dry_run` | Show what would be fixed without making changes | `false` |

## Examples

```bash
# Run hygiene on all your issues
skill_run("jira_hygiene_all", '{}')

# Dry run - see what would be fixed
skill_run("jira_hygiene_all", '{"dry_run": true}')

# Only check "In Progress" issues
skill_run("jira_hygiene_all", '{"status": "In Progress"}')

# Check first 10 issues without auto-fixing
skill_run("jira_hygiene_all", '{"limit": 10, "auto_fix": false}')
```

## What It Does

1. Fetches all Jira issues assigned to you
2. Runs `jira_hygiene` on each issue
3. Reports summary with healthy/fixed/needs-attention counts
4. Lists issues that need manual attention

## When to Use

- Nightly cleanup of your issue backlog
- Before sprint planning
- Weekly hygiene check
- Before vacation (clean up your queue)
