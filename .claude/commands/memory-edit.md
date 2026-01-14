---
name: memory-edit
description: "Modify or remove entries from memory."
arguments:
  - name: file
  - name: action
  - name: list_path
  - name: match_key
  - name: match_value
---
# ✏️ Memory Edit

Modify or remove entries from memory.

## Usage

### Remove an Item

Remove a closed issue from active_issues:
```text
skill_run("memory_edit", '{
  "file": "state/current_work",
  "action": "remove",
  "list_path": "active_issues",
  "match_key": "key",
  "match_value": "AAP-12345"
}')
```

Remove a merged MR from open_mrs:
```text
skill_run("memory_edit", '{
  "file": "state/current_work",
  "action": "remove",
  "list_path": "open_mrs",
  "match_key": "id",
  "match_value": "123"
}')
```

### Update a Field

Update environment status:
```text
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
