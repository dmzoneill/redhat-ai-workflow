---
name: monitor-jira-comments
description: Daily monitoring of Jira comments on sprint issues
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: monitor_jira_comments.yaml
  executable: "true"
---

# monitor_jira_comments

Daily monitoring of Jira comments on sprint issues.

Detects questions from team members and responds appropriately.
All responses are written in natural language - never mentions "bot" or "automated".

Scheduled to run at 9 AM on weekdays via cron.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("monitor_jira_comments", '{
  "jira_project": "AAP",
  "hours_lookback": 24,
  "notify_user": true,
  "slack_channel": "example-slack_channel",
  "dry_run": false
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Ensure developer persona is loaded**
2. **Find all sprint issues assigned to current user**
3. **Parse the search results into a list**
4. **Check each issue for recent comments**
5. **Compile summary of all checks**
6. **Log this monitoring run to session**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `jira_project` | string | No | `AAP` | Jira project key (e.g., AAP) |
| `hours_lookback` | string | No | `24` | How many hours back to check for new comments |
| `notify_user` | string | No | `true` | Whether to notify user via Slack |
| `slack_channel` | string | No | `-` | Slack channel for notifications |
| `dry_run` | string | No | `false` | If true, don't post responses, just report what would be done |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the monitor_jira_comments skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("monitor_jira_comments", '{
  "jira_project": "AAP",
  "hours_lookback": 24,
  "notify_user": true,
  "slack_channel": "example-slack_channel",
  "dry_run": false
}')
```

### Via Command (if configured)

```
/monitor-jira-comments
```

## MCP Tools Used

- `jira_search`
- `memory_session_log`
- `persona_load`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/monitor_jira_comments.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/monitor_jira_comments.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
