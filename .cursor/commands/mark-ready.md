# 📢 Mark MR Ready

Remove draft status from an MR and notify the team.

## Instructions

```
skill_run("mark_mr_ready", '{"mr_id": 1234}')
```

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `mr_id` | GitLab MR ID (required) | - |
| `project` | GitLab project path | Auto-detected |
| `issue_key` | Jira issue to update | - |
| `update_jira` | Update Jira status to "In Review" | `true` |

## Examples

```bash
# Mark MR ready
skill_run("mark_mr_ready", '{"mr_id": 1459}')

# Mark ready and update Jira
skill_run("mark_mr_ready", '{"mr_id": 1459, "issue_key": "AAP-12345"}')

# Mark ready without Jira update
skill_run("mark_mr_ready", '{"mr_id": 1459, "update_jira": false}')
```

## What It Does

1. Removes "Draft:" prefix from MR title
2. Sets MR status to ready for review
3. Posts to team Slack channel asking for review
4. Updates Jira status to "In Review" (optional)

## Workflow

```
/create-mr          # Creates as draft by default
... self-review ...
... fix issues ...
/mark-ready         # Remove draft, notify team
```

## Why Draft First?

Creating MRs as drafts lets you:
- Run pipelines before review
- Self-review your changes
- Fix linting/test issues
- Polish before asking for review time
