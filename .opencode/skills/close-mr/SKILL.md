---
name: close-mr
description: Close a GitLab merge request
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: close_mr.yaml
  executable: "true"
---

# close_mr

Close a GitLab merge request.

Use when:
- MR is abandoned
- MR is replaced by another
- Work is no longer needed

Uses: gitlab_mr_view, gitlab_mr_close, jira_transition, jira_add_comment

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("close_mr", '{
  "mr_id": "example-mr_id",
  "project": "automation-analytics/automation-analytics-backend",
  "reason": "Closing - no longer needed",
  "update_jira": true
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load developer persona for GitLab and Jira tools**
2. **Check for known GitLab issues before starting**
3. **Get MR details before closing**
4. **Extract Jira key from MR**
5. **Close the merge request**
6. **Parse close result**
7. **Add comment to Jira issue**
8. **Log MR closure**
9. **Track MR closures for patterns**
10. **Remove closed MR from open_mrs in memory**
11. **Search for code related to the closed MR**
12. **Parse MR code search results**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `mr_id` | integer | Yes | `-` | GitLab MR ID |
| `project` | string | No | `automation-analytics/automation-analytics-backend` | GitLab project path |
| `reason` | string | No | `Closing - no longer needed` | Reason for closing |
| `update_jira` | boolean | No | `true` | Update linked Jira issue |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the close_mr skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("close_mr", '{
  "mr_id": "example-mr_id",
  "project": "automation-analytics/automation-analytics-backend",
  "reason": "Closing - no longer needed",
  "update_jira": true
}')
```

### Via Command (if configured)

```
/close-mr
```

## MCP Tools Used

- `check_known_issues`
- `code_search`
- `gitlab_mr_close`
- `gitlab_mr_view`
- `jira_add_comment`
- `memory_session_log`
- `persona_load`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/close_mr.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/close_mr.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
