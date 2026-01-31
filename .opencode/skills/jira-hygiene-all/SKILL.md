---
name: jira-hygiene-all
description: Run hygiene checks on all your assigned Jira issues
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: jira_hygiene_all.yaml
  executable: "true"
---

# jira_hygiene_all

Run hygiene checks on all your assigned Jira issues.

Fetches all issues assigned to you and runs jira_hygiene on each.
Useful for scheduled nightly cleanup of your issue backlog.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("jira_hygiene_all", '{
  "status": "example-status",
  "limit": 200,
  "auto_fix": true,
  "auto_transition": true,
  "dry_run": false
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load developer persona for Jira tools**
2. **Fetch all issues assigned to me**
3. **Parse issue list**
4. **Run hygiene check on each issue**
5. **Build batch hygiene summary**
6. **Log batch hygiene to session**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `status` | string | No | `-` | Filter by status (e.g., 'In Progress', 'New'). Empty = all statuses. |
| `limit` | integer | No | `200` | Maximum number of issues to process |
| `auto_fix` | boolean | No | `true` | Automatically fix issues where possible |
| `auto_transition` | boolean | No | `true` | Auto-transition New → Refinement when ready |
| `dry_run` | boolean | No | `false` | Show what would be fixed without making changes |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the jira_hygiene_all skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("jira_hygiene_all", '{
  "status": "example-status",
  "limit": 200,
  "auto_fix": true,
  "auto_transition": true,
  "dry_run": false
}')
```

### Via Command (if configured)

```
/jira-hygiene-all
```

## MCP Tools Used

- `jira_my_issues`
- `memory_session_log`
- `persona_load`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/jira_hygiene_all.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/jira_hygiene_all.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
