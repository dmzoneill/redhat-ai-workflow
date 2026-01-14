# /memory-edit

> Modify or remove entries from memory.

## Overview

Modify or remove entries from memory.

**Underlying Skill:** `memory_edit`

This command is a wrapper that calls the `memory_edit` skill. For detailed process information, see [skills/memory_edit.md](../skills/memory_edit.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `file` | No | - |
| `action` | No | - |
| `list_path` | No | - |
| `match_key` | No | - |
| `match_value` | No | - |

## Usage

### Examples

```bash
skill_run("memory_edit", '{
  "file": "state/current_work",
  "action": "remove",
  "list_path": "active_issues",
  "match_key": "key",
  "match_value": "AAP-12345"
}')
```

```bash
skill_run("memory_edit", '{
  "file": "state/current_work",
  "action": "remove",
  "list_path": "open_mrs",
  "match_key": "id",
  "match_value": "123"
}')
```

```bash
skill_run("memory_edit", '{
  "file": "state/environments",
  "action": "update",
  "field_path": "environments.stage.status",
  "new_value": "healthy"
}')
```

## Process Flow

This command invokes the `memory_edit` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /memory-edit]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call memory_edit skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```bash

For detailed step-by-step process, see the [memory_edit skill documentation](../skills/memory_edit.md).

## Details

## Usage

#

## Remove an Item

Remove a closed issue from active_issues:
```
skill_run("memory_edit", '{
  "file": "state/current_work",
  "action": "remove",
  "list_path": "active_issues",
  "match_key": "key",
  "match_value": "AAP-12345"
}')
```text

Remove a merged MR from open_mrs:
```
skill_run("memory_edit", '{
  "file": "state/current_work",
  "action": "remove",
  "list_path": "open_mrs",
  "match_key": "id",
  "match_value": "123"
}')
```bash

#

## Update a Field

Update environment status:
```
skill_run("memory_edit", '{
  "file": "state/environments",
  "action": "update",
  "field_path": "environments.stage.status",
  "new_value": "healthy"
}')
```

## Tips

- Use `/memory --file <file>` first to see current content
- Use `/memory-cleanup` for automatic cleanup of stale entries
- Match keys: `key` for issues, `id` for MRs, `name` for namespaces


## Related Commands

_(To be determined based on command relationships)_
