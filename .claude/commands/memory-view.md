---
name: memory-view
description: "View and manage persistent memory."
arguments:
  - name: section
---
# Memory View

View and manage persistent memory.

## Instructions

```text
skill_run("memory_view", '{}')
```

## What It Shows

- **Active issues** you're working on
- **Open MRs** and their status
- **Follow-up tasks** pending
- **Environment health** summary
- **Recent session** activity

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `section` | Which section to view | `all` |
| `action` | Action to perform | None |
| `followup_text` | Text for new follow-up | - |

### Sections

- `all` - Everything
- `work` - Active issues and MRs
- `followups` - Follow-up tasks
- `environments` - Environment health
- `patterns` - Learned error patterns
- `sessions` - Recent session logs

### Actions

- `clear_completed` - Remove completed items
- `add_followup` - Add a follow-up task
- `clear_old_sessions` - Remove sessions older than 7 days

## Examples

```bash
# View everything
skill_run("memory_view", '{}')

# View just active work
skill_run("memory_view", '{"section": "work"}')

# View learned patterns
skill_run("memory_view", '{"section": "patterns"}')

# Add a follow-up
skill_run("memory_view", '{"action": "add_followup", "followup_text": "Review MR 1450 feedback"}')

# Clear completed items
skill_run("memory_view", '{"action": "clear_completed"}')
```

## See Also

- `/memory` - Quick memory access
- `/memory-edit` - Edit memory directly
- `/memory-cleanup` - Clean up memory files
