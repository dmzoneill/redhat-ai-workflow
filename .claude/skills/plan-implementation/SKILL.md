---
name: plan-implementation
description: Create a structured implementation plan for a feature or change
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: plan_implementation.yaml
  executable: "true"
---

# plan_implementation

Create a structured implementation plan for a feature or change.

This skill:
1. Analyzes the goal and breaks it into steps
2. Identifies files that need to be modified
3. Checks for existing patterns to follow
4. Identifies risks and unknowns
5. Creates a checklist-style plan

Use this after researching to create an actionable plan before coding.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("plan_implementation", '{
  "goal": "example-goal",
  "project": "example-project",
  "issue_key": "example-issue_key",
  "constraints": "example-constraints"
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load developer persona for Jira tools**
2. **detect_project**
3. **set_project**
4. **Get Jira issue details**
5. **Find code related to the goal**
6. **parse_related_code**
7. **Get coding patterns to follow**
8. **Get architecture context**
9. **Get relevant gotchas**
10. **build_plan**
11. **Log plan creation to session**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `goal` | string | Yes | `-` | What you want to implement (e.g., 'Add Redis caching to billing API') |
| `project` | string | No | `-` | Project to plan for (auto-detected if empty) |
| `issue_key` | string | No | `-` | Jira issue key if this is for a specific ticket |
| `constraints` | string | No | `-` | Any constraints or requirements (e.g., 'must be backwards compatible') |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the plan_implementation skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("plan_implementation", '{
  "goal": "example-goal",
  "project": "example-project",
  "issue_key": "example-issue_key",
  "constraints": "example-constraints"
}')
```

### Via Command (if configured)

```
/plan-implementation
```

## MCP Tools Used

- `code_search`
- `jira_view_issue`
- `knowledge_query`
- `memory_session_log`
- `persona_load`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/plan_implementation.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/plan_implementation.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
