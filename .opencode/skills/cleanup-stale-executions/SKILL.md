---
name: cleanup-stale-executions
description: Cleans up stale skill executions from the skill_execution.json file
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: cleanup_stale_executions.yaml
  executable: "true"
---

# cleanup_stale_executions

Cleans up stale skill executions from the skill_execution.json file.

A skill execution is considered stale if:
- It's been "running" for more than 30 minutes, OR
- It's been "running" for more than 10 minutes with no recent events

Completed executions older than 5 minutes are also removed to keep the file small.

This skill is designed to run periodically via cron to prevent the execution
tracking file from growing unbounded and to clear stuck executions.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("cleanup_stale_executions", '{}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Clean up stale and old skill executions**
2. **Log the cleanup to session memory**

## Inputs

This skill has no inputs.


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the cleanup_stale_executions skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("cleanup_stale_executions", '{}')
```

### Via Command (if configured)

```
/cleanup-stale-executions
```

## MCP Tools Used

- `memory_session_log`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/cleanup_stale_executions.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/cleanup_stale_executions.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
