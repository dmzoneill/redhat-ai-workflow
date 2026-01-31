---
name: find-similar-code
description: Find code similar to a given snippet or description
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: find_similar_code.yaml
  executable: "true"
---

# find_similar_code

Find code similar to a given snippet or description.

Use this skill to:
- Find existing implementations of similar functionality
- Discover patterns used elsewhere in the codebase
- Find code to reference when implementing new features
- Identify potential code duplication

Uses semantic vector search for intelligent matching.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("find_similar_code", '{
  "query": "example-query",
  "project": "example-project",
  "limit": 10,
  "show_context": true
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Check for known vector search issues before starting**
2. **detect_project**
3. **set_project**
4. **Search for similar code using semantic vector search**
5. **Parse search results**
6. **Get related patterns from knowledge base**
7. **Parse related patterns**
8. **build_summary**
9. **Detect failure patterns from code search**
10. **Learn from vector index failures**
11. **Log search to session**
12. **Track code searches for patterns**
13. **Track popular search queries**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `query` | string | Yes | `-` | Description of what you're looking for, or a code snippet |
| `project` | string | No | `-` | Project name from config.json (auto-detected from cwd if empty) |
| `limit` | integer | No | `10` | Maximum number of results to return |
| `show_context` | boolean | No | `true` | Show surrounding code context for each result |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the find_similar_code skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("find_similar_code", '{
  "query": "example-query",
  "project": "example-project",
  "limit": 10,
  "show_context": true
}')
```

### Via Command (if configured)

```
/find-similar-code
```

## MCP Tools Used

- `check_known_issues`
- `code_search`
- `knowledge_query`
- `learn_tool_fix`
- `memory_session_log`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/find_similar_code.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/find_similar_code.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
