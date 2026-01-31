---
name: notify-mr
description: Notify the team Slack channel about an existing MR that's ready for review
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: notify_mr.yaml
  executable: "true"
---

# notify_mr

Notify the team Slack channel about an existing MR that's ready for review.

Use this when:
- You created a draft MR and it's now ready
- You want to remind the team about a pending review
- You marked an MR as ready after initial work

Uses MCP tools: gitlab_mr_view, jira_view_issue, slack_post_team

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("notify_mr", '{
  "mr_id": "example-mr_id",
  "project": "example-project",
  "issue_key": "example-issue_key",
  "message": "example-message",
  "reminder": false,
  "slack_format": false
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load developer persona for GitLab and Jira tools**
2. **Initialize failure tracking**
3. **Get notification patterns from knowledge base**
4. **Parse notification knowledge for context**
5. **Check for known Slack/notification issues**
6. **Load configuration and resolve inputs**
7. **Get MR details from GitLab**
8. **Parse MR details from glab output**
9. **Get Jira issue details for context**
10. **Parse Jira issue summary**
11. **Build Slack message and post to team channel**
12. **Load slack persona for Slack notification tools**
13. **Post notification to team channel**
14. **Search for code related to the MR being notified**
15. **Parse MR code search results**
16. **Log notification to session**
17. **Track MR notifications for patterns**
18. **Track MRs that need frequent reminders**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `mr_id` | string | No | `-` | GitLab MR IID (e.g., 1459). If not provided, will try to find from current branch. |
| `project` | string | No | `-` | GitLab project path (e.g., 'automation-analytics/automation-analytics-backend') |
| `issue_key` | string | No | `-` | Jira issue key for additional context |
| `message` | string | No | `-` | Custom message to include (optional) |
| `reminder` | boolean | No | `false` | If true, formats as a reminder rather than new MR notification |
| `slack_format` | boolean | No | `false` | Use Slack link format in summary |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the notify_mr skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("notify_mr", '{
  "mr_id": "example-mr_id",
  "project": "example-project",
  "issue_key": "example-issue_key",
  "message": "example-message",
  "reminder": false,
  "slack_format": false
}')
```

### Via Command (if configured)

```
/notify-mr
```

## MCP Tools Used

- `code_search`
- `gitlab_mr_view`
- `jira_view_issue`
- `knowledge_query`
- `memory_session_log`
- `persona_load`
- `slack_post_team`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/notify_mr.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/notify_mr.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
