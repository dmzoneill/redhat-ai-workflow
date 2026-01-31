---
name: summarize-findings
description: Create a summary of research findings from the current session
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: summarize_findings.yaml
  executable: "true"
---

# summarize_findings

Create a summary of research findings from the current session.

This skill:
1. Reviews session logs for research activities
2. Compiles findings into a structured summary
3. Optionally saves to memory for future reference

Use this at the end of a research session to capture learnings.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("summarize_findings", '{
  "topic": "example-topic",
  "conclusion": "example-conclusion",
  "save_to_memory": true
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Get today's session logs**
2. **filter_research_entries**
3. **build_summary**
4. **Save summary to memory**
5. **Log summary creation to session**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `topic` | string | Yes | `-` | Topic of the research (e.g., 'caching strategies') |
| `conclusion` | string | No | `-` | Your conclusion or recommendation |
| `save_to_memory` | boolean | No | `true` | Save summary to memory for future reference |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the summarize_findings skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("summarize_findings", '{
  "topic": "example-topic",
  "conclusion": "example-conclusion",
  "save_to_memory": true
}')
```

### Via Command (if configured)

```
/summarize-findings
```

## MCP Tools Used

- `memory_session_log`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/summarize_findings.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/summarize_findings.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
