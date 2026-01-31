---
name: gather-context
description: Gather relevant context for a task using semantic search and knowledge base
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: gather_context.yaml
  executable: "true"
---

# gather_context

Gather relevant context for a task using semantic search and knowledge base.

This skill consolidates the common pattern of:
1. Searching codebase for related code (code_search)
2. Loading project knowledge/gotchas (knowledge_query)
3. Checking for known issues/patterns (check_known_issues)

Use this at the start of any skill that needs context about:
- A Jira issue being worked on
- A feature being implemented
- A bug being investigated
- Code being reviewed

Returns structured context that can be used by other skills.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("gather_context", '{
  "query": "example-query",
  "project": "automation-analytics-backend",
  "tool_name": "example-tool_name",
  "code_limit": 5,
  "include_architecture": true,
  "include_gotchas": true,
  "include_patterns": true
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Search codebase for related code using semantic search**
2. **Parse code search results into structured format**
3. **Load project gotchas from knowledge base**
4. **Parse gotchas into actionable list**
5. **Load coding patterns from knowledge base**
6. **Parse coding patterns**
7. **Load architecture overview from knowledge base**
8. **Parse architecture context**
9. **Check memory for known issues related to query**
10. **Parse known issues into structured format**
11. **Combine all context into single output**
12. **Log context gathering to session**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `query` | string | Yes | `-` | What to search for (issue description, feature name, error message, etc.) |
| `project` | string | No | `automation-analytics-backend` | Project name from config for knowledge lookup |
| `tool_name` | string | No | `-` | Tool name to check for known issues (optional) |
| `code_limit` | integer | No | `5` | Max code search results |
| `include_architecture` | boolean | No | `true` | Include architecture overview in context |
| `include_gotchas` | boolean | No | `true` | Include project gotchas in context |
| `include_patterns` | boolean | No | `true` | Include coding patterns in context |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the gather_context skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("gather_context", '{
  "query": "example-query",
  "project": "automation-analytics-backend",
  "tool_name": "example-tool_name",
  "code_limit": 5,
  "include_architecture": true,
  "include_gotchas": true,
  "include_patterns": true
}')
```

### Via Command (if configured)

```
/gather-context
```

## MCP Tools Used

- `check_known_issues`
- `code_search`
- `knowledge_query`
- `memory_session_log`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/gather_context.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/gather_context.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
