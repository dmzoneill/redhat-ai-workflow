---
name: hello-world
description: A simple test skill that prints "Hello World" with a timestamp
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: hello_world.yaml
  executable: "true"
---

# hello_world

A simple test skill that prints "Hello World" with a timestamp.
Used for testing the cron scheduler functionality.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("hello_world", '{}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Print hello world with timestamp**
2. **Log the execution to session**

## Inputs

This skill has no inputs.


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the hello_world skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("hello_world", '{}')
```

### Via Command (if configured)

```
/hello-world
```

## MCP Tools Used

- `memory_session_log`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/hello_world.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/hello_world.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
