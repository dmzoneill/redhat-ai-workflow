---
name: check-mr-feedback
description: Check your open Merge Requests for feedback that needs your attention
license: MIT
compatibility: opencode
metadata:
  version: "1.2"
  source: check_mr_feedback.yaml
  executable: "true"
---

# check_mr_feedback

Check your open Merge Requests for feedback that needs your attention.

Scans for:
- Human reviewer comments (filters out bot/CI comments)
- Meeting requests (can trigger Google Calendar invite)
- Code change requests
- Questions requiring answers
- Approval status

Optionally creates Google Meet invitations when meetings are requested.

Uses MCP tools: gitlab_mr_list, gitlab_mr_comments

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("check_mr_feedback", '{
  "project": "automation-analytics/automation-analytics-backend",
  "create_meetings": false,
  "mr_ids": "example-mr_ids",
  "slack_format": false
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load developer persona for GitLab MR tools**
2. **Get code review patterns from knowledge base**
3. **Parse review knowledge for feedback context**
4. **Check for known GitLab issues before starting**
5. **Fetch all open MRs authored by the current user**
6. **Parse MR list output**
7. **Prepare MR IDs for individual tool calls**
8. **Get comments for first MR**
9. **Get comments for second MR**
10. **Get comments for third MR**
11. **Get comments for fourth MR**
12. **Get comments for fifth MR**
13. **Analyze comments from all MRs using shared parsers**
14. **Check if meetings already exist for meeting requests**
15. **Create Google Meet invitations for meeting requests**
16. **Create human-readable summary**
17. **Build context for memory updates**
18. **Log feedback check to session**
19. **Search for code related to MRs with feedback**
20. **Parse MR code search results**
21. **Create follow-up tasks for MRs needing response**
22. **Detect failure patterns from MR feedback checks**
23. **Learn from GitLab VPN failures**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `project` | string | No | `automation-analytics/automation-analytics-backend` | GitLab project path |
| `create_meetings` | boolean | No | `false` | Automatically create Google Meet invites for meeting requests |
| `mr_ids` | array | No | `-` | Specific MR IDs to check (optional - defaults to all open MRs) |
| `slack_format` | boolean | No | `false` | Use Slack link format in summary |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the check_mr_feedback skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("check_mr_feedback", '{
  "project": "automation-analytics/automation-analytics-backend",
  "create_meetings": false,
  "mr_ids": "example-mr_ids",
  "slack_format": false
}')
```

### Via Command (if configured)

```
/check-mr-feedback
```

## MCP Tools Used

- `check_known_issues`
- `code_search`
- `gitlab_mr_comments`
- `gitlab_mr_list`
- `knowledge_query`
- `learn_tool_fix`
- `memory_session_log`
- `persona_load`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/check_mr_feedback.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/check_mr_feedback.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
