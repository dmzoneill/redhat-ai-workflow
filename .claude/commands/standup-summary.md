---
name: standup-summary
description: "Generate a standup summary from recent activity."
arguments:
  - name: days
---
# Standup Summary

Generate a standup summary from recent activity.

## Instructions

```text
skill_run("standup_summary", '{}')
```

## What It Does

1. Checks recent git commits
2. Reviews Jira issue updates
3. Checks MR status and feedback
4. Summarizes what was done and what's next

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `days` | Number of days to look back | No (default: 1) |
| `project` | Project to summarize | No (auto-detected) |

## Examples

```bash
# Today's standup
skill_run("standup_summary", '{}')

# Last 3 days
skill_run("standup_summary", '{"days": 3}')
```

## Output Format

- **Yesterday**: What was completed
- **Today**: What's planned
- **Blockers**: Any issues blocking progress
