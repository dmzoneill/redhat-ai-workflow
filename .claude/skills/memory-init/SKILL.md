---
name: memory-init
description: Initialize or reset memory files to a clean state
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: memory_init.yaml
  executable: "true"
---

# memory_init

Initialize or reset memory files to a clean state.

Use this for:
- Fresh start on a new project/sprint
- Clearing stale data after extended absence
- Setting up memory on a new machine

By default, preserves learned patterns and runbooks.
Use reset_learned=true to also reset those.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("memory_init", '{
  "confirm": true,
  "reset_learned": false,
  "preserve_patterns": true
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Search for code related to memory initialization**
2. **Parse init code search results**
3. **Verify user confirmed the action**
4. **Create timestamped backup of all memory files before wiping**
5. **Backup patterns if preserving them**
6. **Reset current work state**
7. **Reset environment state**
8. **Reset learned memory (patterns, runbooks, etc)**
9. **Restore patterns from backup if preserved**
10. **Log initialization to session**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `confirm` | boolean | Yes | `-` | Must be true to proceed (safety check) |
| `reset_learned` | boolean | No | `false` | Also reset learned patterns and runbooks (default: false) |
| `preserve_patterns` | boolean | No | `true` | Keep learned patterns even if reset_learned is true |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the memory_init skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("memory_init", '{
  "confirm": true,
  "reset_learned": false,
  "preserve_patterns": true
}')
```

### Via Command (if configured)

```
/memory-init
```

## MCP Tools Used

- `code_search`
- `memory_session_log`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/memory_init.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/memory_init.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
