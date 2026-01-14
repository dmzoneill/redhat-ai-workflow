---
name: jira-hygiene
description: "Check and fix Jira issue quality before you start coding."
arguments:
  - name: issue_key
---
# 🧹 Jira Hygiene

Check and fix Jira issue quality before you start coding.

## Instructions

```text
skill_run("jira_hygiene", '{"issue_key": "AAP-XXXXX"}')
```

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `issue_key` | Jira issue key (required) | - |
| `repo_name` | Repository name (for component) | - |
| `auto_fix` | Automatically fix issues | `false` |
| `auto_transition` | Move New → Refinement when complete | `false` |

## Examples

```bash
# Check issue hygiene
skill_run("jira_hygiene", '{"issue_key": "AAP-12345"}')

# Check and auto-fix issues
skill_run("jira_hygiene", '{"issue_key": "AAP-12345", "auto_fix": true}')

# Full auto: fix and transition
skill_run("jira_hygiene", '{"issue_key": "AAP-12345", "auto_fix": true, "auto_transition": true}')
```

## What It Checks

| Check | Description |
|-------|-------------|
| 📝 Description | Has meaningful content |
| ✅ Acceptance Criteria | Defined and clear |
| 🏷️ Labels | Has appropriate labels |
| 📊 Priority | Set appropriately |
| 🎯 Epic Link | Connected to an epic |
| 📐 Story Points | Estimated |
| 🎨 Formatting | Proper Jira markup |

## When to Use

- Before starting work on an issue (`/start-work`)
- During backlog refinement
- Before creating an MR
- Sprint planning prep
