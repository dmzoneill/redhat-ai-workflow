---
name: memory-cleanup
description: "Clean up stale entries from memory."
arguments:
  - name: dry_run
---
# 🧹 Memory Cleanup

Clean up stale entries from memory.

## Usage

**Preview what would be removed (dry run - default):**
```text
skill_run("memory_cleanup", '{}')
```

**Actually remove stale entries:**
```text
skill_run("memory_cleanup", '{"dry_run": false}')
```

## What Gets Cleaned

- **Active Issues**: Issues with status "Done", "Closed", or "Resolved"
- **Open MRs**: MRs with pipeline status "merged" or "closed"
- **Ephemeral Namespaces**: Namespaces older than 7 days (configurable)

## Options

- `dry_run`: Preview changes without applying (default: true)
- `days`: Remove ephemeral namespaces older than this (default: 7)

## Example

```text
/memory-cleanup
```

This shows what would be cleaned. Run with `dry_run: false` to apply.
