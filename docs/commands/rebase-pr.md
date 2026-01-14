# /rebase-pr

> Rebase a merge request onto latest main.

## Overview

Rebase a merge request onto latest main.

**Underlying Skill:** `rebase_pr`

This command is a wrapper that calls the `rebase_pr` skill. For detailed process information, see [skills/rebase_pr.md](../skills/rebase_pr.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `mr_id` | No | - |

## Usage

### Examples

```bash
skill_run("rebase_pr", '{"mr_id": $MR_ID}')
```

```bash
# Rebase an MR
skill_run("rebase_pr", '{"mr_id": 1234}')

# Rebase onto different branch
skill_run("rebase_pr", '{"mr_id": 1234, "target_branch": "release-1.0"}')
```

## Process Flow

This command invokes the `rebase_pr` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /rebase-pr]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call rebase_pr skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [rebase_pr skill documentation](../skills/rebase_pr.md).

## Details

## Instructions

```
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


## Related Commands

_(To be determined based on command relationships)_
