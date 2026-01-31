---
name: learn-pattern
description: Save a new error pattern to memory
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: learn_pattern.yaml
  executable: "true"
---

# learn_pattern

Save a new error pattern to memory.

When you discover a new error pattern and its fix, use this skill
to remember it for future debugging sessions.

The pattern is saved to memory/learned/patterns.yaml and will be
automatically matched during investigate_alert and debug_prod skills.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("learn_pattern", '{
  "pattern": "example-pattern",
  "meaning": "example-meaning",
  "fix": "example-fix",
  "commands": "example-commands",
  "category": "general"
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Validate inputs**
2. **Parse comma-separated commands**
3. **Check if tools in commands actually exist**
4. **Save pattern to memory**
5. **Log pattern learning to session**
6. **Track pattern learning history**
7. **Search for similar patterns in codebase**
8. **Parse similar patterns search results**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `pattern` | string | Yes | `-` | Short name for the pattern (e.g., 'OOMKilled', 'ImagePullBackOff') |
| `meaning` | string | Yes | `-` | What this error means (e.g., 'Container exceeded memory limit') |
| `fix` | string | Yes | `-` | How to fix this error (e.g., 'Increase memory limits in deployment') |
| `commands` | string | No | `-` | Comma-separated commands to run for diagnosis (e.g., 'kubectl describe pod X,kubectl logs X') |
| `category` | string | No | `general` | Category: pod_errors, log_patterns, network, general |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the learn_pattern skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("learn_pattern", '{
  "pattern": "example-pattern",
  "meaning": "example-meaning",
  "fix": "example-fix",
  "commands": "example-commands",
  "category": "general"
}')
```

### Via Command (if configured)

```
/learn-pattern
```

## MCP Tools Used

- `code_search`
- `memory_session_log`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/learn_pattern.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/learn_pattern.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
