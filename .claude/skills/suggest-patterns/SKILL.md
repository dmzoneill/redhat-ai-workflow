---
name: suggest-patterns
description: Auto-discover error patterns from tool failure history
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: suggest_patterns.yaml
  executable: "true"
---

# suggest_patterns

Auto-discover error patterns from tool failure history.

Analyzes memory/learned/tool_failures.yaml to find frequently occurring
errors that aren't already captured in patterns.yaml.

Groups similar errors together and suggests new patterns when an error
occurs 5+ times.

Use this periodically to discover new patterns worth adding to memory.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("suggest_patterns", '{}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Search for code related to error patterns**
2. **Parse pattern code search results**
3. **Load existing patterns for comparison**
4. **Analyze tool failures to discover new patterns**
5. **Log pattern discovery to session**
6. **Track pattern discovery history**

## Inputs

This skill has no inputs.


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the suggest_patterns skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("suggest_patterns", '{}')
```

### Via Command (if configured)

```
/suggest-patterns
```

## MCP Tools Used

- `code_search`
- `memory_session_log`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/suggest_patterns.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/suggest_patterns.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
