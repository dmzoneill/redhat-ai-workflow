---
name: test-error-recovery
description: Test skill to demonstrate interactive error recovery
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: test_error_recovery.yaml
  executable: "true"
---

# test_error_recovery

Test skill to demonstrate interactive error recovery

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("test_error_recovery", '{
  "test_value": "hello"
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Deliberately trigger dict attribute error**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `test_value` | string | No | `hello` |  |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the test_error_recovery skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("test_error_recovery", '{
  "test_value": "hello"
}')
```

### Via Command (if configured)

```
/test-error-recovery
```

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/test_error_recovery.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/test_error_recovery.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
