---
name: memory-cleanup
description: Clean up stale entries from memory
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: memory_cleanup.yaml
  executable: "true"
---

# memory_cleanup

Clean up stale entries from memory.

Removes:
- Closed issues that are still in active_issues
- Merged MRs that are still in open_mrs
- Expired ephemeral namespaces
- Old session logs (older than 7 days)

Use with --dry-run to preview what would be removed.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("memory_cleanup", '{
  "dry_run": true,
  "days": 7
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Search for code related to memory cleanup**
2. **Parse cleanup code search results**
3. **Load current work state from memory**
4. **Load environment state from memory**
5. **Find stale entries that should be removed**
6. **Remove stale entries from memory**
7. **Archive session logs older than 90 days**
8. **Log cleanup to session**
9. **Track cleanup history for patterns**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `dry_run` | boolean | No | `true` | Preview changes without applying them (default: true) |
| `days` | integer | No | `7` | Remove session logs older than this many days (default: 7) |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the memory_cleanup skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("memory_cleanup", '{
  "dry_run": true,
  "days": 7
}')
```

### Via Command (if configured)

```
/memory-cleanup
```

## MCP Tools Used

- `code_search`
- `memory_read`
- `memory_session_log`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/memory_cleanup.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/memory_cleanup.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
