---
name: research-topic
description: Research a topic thoroughly using multiple sources
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: research_topic.yaml
  executable: "true"
---

# research_topic

Research a topic thoroughly using multiple sources.

This skill:
1. Searches internal codebase for relevant implementations
2. Checks memory for past learnings and patterns
3. Queries project knowledge for architecture context
4. Optionally searches the web for external documentation

Use this when you need to understand something before taking action.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("research_topic", '{
  "topic": "example-topic",
  "project": "example-project",
  "depth": "normal",
  "focus": "example-focus"
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **detect_project**
2. **set_project**
3. **Search codebase for topic-related code**
4. **Parse code search results**
5. **Check memory for related patterns**
6. **Find relevant patterns**
7. **Get architecture context**
8. **Get coding patterns**
9. **Get relevant gotchas**
10. **Parse knowledge results**
11. **build_summary**
12. **Log research to session**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `topic` | string | Yes | `-` | The topic to research (e.g., 'pytest fixtures', 'Redis caching', 'authentication flow') |
| `project` | string | No | `-` | Project to search in (auto-detected if empty) |
| `depth` | string | No | `normal` | Research depth: 'quick' (code only), 'normal' (code + memory), 'deep' (all sources) |
| `focus` | string | No | `-` | Specific aspect to focus on (e.g., 'performance', 'security', 'testing') |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the research_topic skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("research_topic", '{
  "topic": "example-topic",
  "project": "example-project",
  "depth": "normal",
  "focus": "example-focus"
}')
```

### Via Command (if configured)

```
/research-topic
```

## MCP Tools Used

- `code_search`
- `knowledge_query`
- `memory_read`
- `memory_session_log`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/research_topic.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/research_topic.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
