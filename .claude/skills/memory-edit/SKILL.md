---
name: memory-edit
description: Modify or remove entries from memory
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: memory_edit.yaml
  executable: "true"
---

# memory_edit

Modify or remove entries from memory.

Actions:
- remove: Remove an item from a list (e.g., remove closed issue from active_issues)
- update: Update a field value

Use memory_view to inspect memory before editing.
Use memory_cleanup for automatic cleanup of stale entries.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("memory_edit", '{
  "file": "example-file",
  "action": "example-action",
  "list_path": "example-list_path",
  "match_key": "example-match_key",
  "match_value": "example-match_value",
  "field_path": "example-field_path",
  "new_value": "example-new_value"
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Search for code related to memory editing**
2. **Parse edit code search results**
3. **Validate inputs based on action**
4. **Remove item from list in memory**
5. **Update field in memory**
6. **Log memory edit to session**
7. **Track memory edits for patterns**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `file` | string | Yes | `-` | Memory file to edit (e.g., 'state/current_work', 'learned/patterns') |
| `action` | string | Yes | `-` | Action: 'remove' or 'update' |
| `list_path` | string | No | `-` | Path to list for remove action (e.g., 'active_issues', 'open_mrs') |
| `match_key` | string | No | `-` | Key to match for remove action (e.g., 'key' for issues, 'id' for MRs) |
| `match_value` | string | No | `-` | Value to match for remove action (e.g., 'AAP-12345', '123') |
| `field_path` | string | No | `-` | Dot-separated path for update action (e.g., 'environments.stage.status') |
| `new_value` | string | No | `-` | New value for update action |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the memory_edit skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("memory_edit", '{
  "file": "example-file",
  "action": "example-action",
  "list_path": "example-list_path",
  "match_key": "example-match_key",
  "match_value": "example-match_value",
  "field_path": "example-field_path",
  "new_value": "example-new_value"
}')
```

### Via Command (if configured)

```
/memory-edit
```

## MCP Tools Used

- `code_search`
- `memory_session_log`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/memory_edit.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/memory_edit.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
