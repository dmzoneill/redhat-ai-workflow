# 📢 Notify Team About MR

Post a review request to the team Slack channel for an existing MR.

## Instructions

```text
skill_run("notify_mr", '{"mr_id": "$MR_ID"}')
```

## When to Use

- After creating a draft MR that's now ready
- To remind the team about a pending review
- When you marked an MR as ready after initial work

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `mr_id` | GitLab MR IID (e.g., "1459") | Auto-detect from branch |
| `project` | GitLab project path | From config |
| `issue_key` | Jira issue key for context | Extracted from MR title |
| `message` | Custom message to include | None |
| `reminder` | Format as reminder vs new | false |

## Examples

```bash
# Notify about specific MR
skill_run("notify_mr", '{"mr_id": "1459"}')

# From current branch (auto-detect MR)
skill_run("notify_mr", '{}')

# With custom message
skill_run("notify_mr", '{"mr_id": "1459", "message": "Addressed all feedback, ready for final review"}')

# Send as reminder
skill_run("notify_mr", '{"mr_id": "1459", "reminder": true}')

# With specific project
skill_run("notify_mr", '{"mr_id": "1459", "project": "automation-analytics/automation-analytics-backend"}')
```text

## What Gets Posted

```
🔀 *MR Ready for Review*

📋 *Jira:* AAP-61661 - Fix billing calculation
🔗 *MR:* !1459 - AAP-61661 - Fix billing calculation
📁 *Repo:* automation-analytics-backend

Please review when you have a moment 🙏
```text

Or as a reminder:
```
⏰ *Friendly Reminder: MR Awaiting Review*
...
```
