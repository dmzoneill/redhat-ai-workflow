---
name: extend-ephemeral
description: Extend the duration of an ephemeral namespace reservation
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: extend_ephemeral.yaml
  executable: "true"
---

# extend_ephemeral

Extend the duration of an ephemeral namespace reservation.

Use when:
- Tests are taking longer than expected
- You need more time to debug
- Demo/testing session running long

The skill will:
1. List your current namespaces
2. Get details on the target namespace
3. Extend the reservation
4. Confirm new expiry time

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("extend_ephemeral", '{
  "namespace": "example-namespace",
  "duration": "1h",
  "list_only": false
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load devops persona for Bonfire tools**
2. **Check for known bonfire/ephemeral issues**
3. **Get ephemeral-related gotchas from knowledge**
4. **Parse ephemeral-related gotchas**
5. **List my ephemeral namespaces**
6. **Parse namespace list**
7. **Select namespace to extend**
8. **Get namespace details**
9. **Parse namespace details**
10. **Extend the namespace reservation**
11. **Parse extend result**
12. **Search for code related to ephemeral namespace management**
13. **Parse ephemeral code search results**
14. **Log extension to session**
15. **Track namespace extension history for patterns**
16. **Update ephemeral deployment state**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `namespace` | string | No | `-` | Namespace to extend (will list yours if not specified) |
| `duration` | string | No | `1h` | How much time to add (e.g., '1h', '2h', '4h') |
| `list_only` | boolean | No | `false` | Just list namespaces without extending |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the extend_ephemeral skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("extend_ephemeral", '{
  "namespace": "example-namespace",
  "duration": "1h",
  "list_only": false
}')
```

### Via Command (if configured)

```
/extend-ephemeral
```

## MCP Tools Used

- `bonfire_namespace_describe`
- `bonfire_namespace_extend`
- `bonfire_namespace_list`
- `code_search`
- `knowledge_query`
- `memory_append`
- `memory_session_log`
- `persona_load`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/extend_ephemeral.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/extend_ephemeral.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
