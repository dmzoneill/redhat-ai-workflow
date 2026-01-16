---
name: cleanup-branches
description: "Delete merged and stale feature branches."
arguments:
  - name: dry_run
---
# Cleanup Branches

Delete merged and stale feature branches.

## Instructions

```text
skill_run("cleanup_branches", '{}')
```

## What It Does

1. Fetches latest from remote
2. Lists all local and remote branches
3. Identifies merged branches
4. Deletes merged branches (with confirmation)
5. Optionally cleans up tracking refs

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `repo` | Repository path | Current directory |
| `dry_run` | Just show what would be deleted | `true` (safe) |
| `include_remote` | Also delete remote branches | `false` |
| `older_than_days` | Consider branches stale if no commits | `30` |
| `protected_branches` | Branches to never delete | `main,master,develop,release` |

## Examples

```bash
# Preview what would be deleted (safe)
skill_run("cleanup_branches", '{}')

# Actually delete branches
skill_run("cleanup_branches", '{"dry_run": false}')

# Include remote branches
skill_run("cleanup_branches", '{"dry_run": false, "include_remote": true}')

# More aggressive cleanup (14 days)
skill_run("cleanup_branches", '{"older_than_days": 14}')
```

## Safety

- **Default is dry_run=true** - shows what would be deleted without deleting
- Protected branches are never deleted
- Main/master/develop/release branches are protected by default
