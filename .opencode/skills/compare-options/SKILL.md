---
name: compare-options
description: Compare multiple options for implementing something
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: compare_options.yaml
  executable: "true"
---

# compare_options

Compare multiple options for implementing something.

This skill:
1. Takes a list of options to compare
2. Searches codebase for existing usage of each
3. Checks memory for past experiences
4. Creates a comparison matrix with pros/cons

Use this when deciding between approaches before implementation.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("compare_options", '{
  "question": "example-question",
  "options": "example-options",
  "criteria": "example-criteria",
  "project": "example-project"
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **parse_options**
2. **detect_project**
3. **set_project**
4. **Search for first option**
5. **Search for second option**
6. **Search for third option**
7. **Check memory for related patterns**
8. **analyze_options**
9. **build_comparison**
10. **Log comparison to session**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `question` | string | Yes | `-` | What decision are you trying to make? (e.g., 'Which caching solution to use?') |
| `options` | string | Yes | `-` | Comma-separated options to compare (e.g., 'Redis, Memcached, Django cache') |
| `criteria` | string | No | `-` | Comma-separated criteria to evaluate (e.g., 'performance, complexity, cost') |
| `project` | string | No | `-` | Project context (auto-detected if empty) |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the compare_options skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("compare_options", '{
  "question": "example-question",
  "options": "example-options",
  "criteria": "example-criteria",
  "project": "example-project"
}')
```

### Via Command (if configured)

```
/compare-options
```

## MCP Tools Used

- `code_search`
- `memory_read`
- `memory_session_log`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/compare_options.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/compare_options.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
