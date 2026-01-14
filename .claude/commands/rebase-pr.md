---
name: rebase-pr
description: "Rebase a merge request onto latest main."
arguments:
  - name: mr_id
    required: true
---
# Rebase PR

Rebase a merge request onto latest main.

## Instructions

```text
skill_run("rebase_pr", '{"mr_id": $MR_ID}')
```

## What It Does

1. Gets MR details and source branch
2. Fetches latest from origin
3. Checks out the branch
4. Rebases onto main
5. Force pushes the rebased branch

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `mr_id` | MR ID to rebase | Required |
| `project` | GitLab project | Current repo |
| `target_branch` | Branch to rebase onto | `main` |

## Examples

```bash
# Rebase an MR
skill_run("rebase_pr", '{"mr_id": 1234}')

# Rebase onto different branch
skill_run("rebase_pr", '{"mr_id": 1234, "target_branch": "release-1.0"}')
```

## Conflict Resolution

If conflicts occur, the skill will:
1. Show conflicting files
2. Wait for manual resolution
3. Continue rebase after you fix conflicts
