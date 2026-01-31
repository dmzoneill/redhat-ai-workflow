---
name: sprint-planning
description: Help with sprint planning by analyzing the backlog
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: sprint_planning.yaml
  executable: "true"
---

# sprint_planning

Help with sprint planning by analyzing the backlog.

This skill:
- Lists unassigned issues in the backlog
- Identifies blocked items
- Shows issues ready for sprint
- Can add issues to a sprint

Uses: jira_list_issues, jira_list_blocked, jira_add_to_sprint, jira_add_flag

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("sprint_planning", '{
  "project": "AAP",
  "sprint": "example-sprint",
  "limit": 20
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load developer persona for Jira tools**
2. **Check for known Jira issues before starting**
3. **Get sprint planning patterns from knowledge**
4. **Parse sprint planning patterns**
5. **Get project gotchas that might affect sprint planning**
6. **Parse planning-relevant gotchas**
7. **Get backlog issues**
8. **Parse backlog issues**
9. **Get blocked issues**
10. **Parse blocked issues**
11. **Get issues ready for development**
12. **Parse ready issues**
13. **Identify best candidates for sprint**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `project` | string | No | `AAP` | Jira project key |
| `sprint` | string | No | `-` | Sprint name to add issues to (optional) |
| `limit` | integer | No | `20` | Max issues to show |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the sprint_planning skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("sprint_planning", '{
  "project": "AAP",
  "sprint": "example-sprint",
  "limit": 20
}')
```

### Via Command (if configured)

```
/sprint-planning
```

## MCP Tools Used

- `check_known_issues`
- `jira_list_blocked`
- `jira_list_issues`
- `knowledge_query`
- `persona_load`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/sprint_planning.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/sprint_planning.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
