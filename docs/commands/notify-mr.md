# /notify-mr

> Post a review request to the team Slack channel for an existing MR.

## Overview

Post a review request to the team Slack channel for an existing MR.

**Underlying Skill:** `notify_mr`

This command is a wrapper that calls the `notify_mr` skill. For detailed process information, see [skills/notify_mr.md](../skills/notify_mr.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `mr_id` | No | - |

## Usage

### Examples

```bash
skill_run("notify_mr", '{"mr_id": "$MR_ID"}')
```

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
```

```bash
🔀 *MR Ready for Review*

📋 *Jira:* AAP-61661 - Fix billing calculation
🔗 *MR:* !1459 - AAP-61661 - Fix billing calculation
📁 *Repo:* automation-analytics-backend

Please review when you have a moment 🙏
```

## Process Flow

This command invokes the `notify_mr` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /notify-mr]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call notify_mr skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [notify_mr skill documentation](../skills/notify_mr.md).

## Details

## Instructions

```
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


## Related Commands

_(To be determined based on command relationships)_
