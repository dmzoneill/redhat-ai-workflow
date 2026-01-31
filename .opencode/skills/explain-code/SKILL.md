---
name: explain-code
description: Explain a piece of code using project knowledge and context
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: explain_code.yaml
  executable: "true"
---

# explain_code

Explain a piece of code using project knowledge and context.

Use this skill to:
- Understand unfamiliar code in the codebase
- Get context about how code fits into the architecture
- Learn about related patterns and gotchas
- Find similar implementations for reference

Combines semantic search with project knowledge for comprehensive explanations.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("explain_code", '{
  "file": "example-file",
  "lines": "example-lines",
  "project": "example-project",
  "depth": "normal"
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Check for known vector search issues before starting**
2. **detect_project**
3. **set_project**
4. **get_project_path**
5. **Read the file to explain**
6. **Find related code in the codebase**
7. **Parse related code results**
8. **Get architecture context for this file**
9. **Parse architecture context**
10. **Get relevant gotchas for this code**
11. **Parse relevant gotchas**
12. **Get coding patterns for this type of code**
13. **Parse coding patterns**
14. **build_explanation**
15. **Detect failure patterns from code explanation**
16. **Learn from vector index failures**
17. **Log explanation to session**
18. **Track code explanations for patterns**
19. **Track files that are frequently explained**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `file` | string | Yes | `-` | File path to explain (relative to project root) |
| `lines` | string | No | `-` | Line range to focus on (e.g., "10-50") |
| `project` | string | No | `-` | Project name from config.json (auto-detected from cwd if empty) |
| `depth` | string | No | `normal` | Explanation depth: 'brief', 'normal', or 'detailed' |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the explain_code skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("explain_code", '{
  "file": "example-file",
  "lines": "example-lines",
  "project": "example-project",
  "depth": "normal"
}')
```

### Via Command (if configured)

```
/explain-code
```

## MCP Tools Used

- `check_known_issues`
- `code_search`
- `knowledge_query`
- `learn_tool_fix`
- `memory_session_log`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/explain_code.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/explain_code.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
