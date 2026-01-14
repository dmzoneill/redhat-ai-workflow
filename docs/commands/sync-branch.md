# /sync-branch

> Quickly rebase your current branch onto main.

## Overview

Quickly rebase your current branch onto main.

**Underlying Skill:** `sync_branch`

This command is a wrapper that calls the `sync_branch` skill. For detailed process information, see [skills/sync_branch.md](../skills/sync_branch.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `force_push` | No | - |

## Usage

### Examples

```bash
skill_run("sync_branch")
```

```bash
# Simple sync - stashes changes, rebases, restores
skill_run("sync_branch")

# Sync and force push
skill_run("sync_branch", '{"force_push": true}')

# Sync onto a different branch
skill_run("sync_branch", '{"base_branch": "release-1.0"}')

# Sync a specific repo
skill_run("sync_branch", '{"repo_name": "backend"}')
```

## Process Flow

This command invokes the `sync_branch` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /sync-branch]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call sync_branch skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [sync_branch skill documentation](../skills/sync_branch.md).

## Details

## Instructions

```
skill_run("sync_branch")
```

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `repo` | Repository path | Current directory |
| `repo_name` | Repository name (resolves via config) | - |
| `issue_key` | Jira issue (resolves repo) | - |
| `base_branch` | Branch to rebase onto | `main` |
| `stash_changes` | Stash uncommitted changes first | `true` |
| `force_push` | Force push after rebase | `false` |

## Examples

```bash
# Simple sync - stashes changes, rebases, restores
skill_run("sync_branch")

# Sync and force push
skill_run("sync_branch", '{"force_push": true}')

# Sync onto a different branch
skill_run("sync_branch", '{"base_branch": "release-1.0"}')

# Sync a specific repo
skill_run("sync_branch", '{"repo_name": "backend"}')
```

## What It Does

1. Fetches latest from remote
2. Stashes any uncommitted changes (optional)
3. Rebases current branch onto main
4. Auto-resolves simple conflicts
5. Restores stashed changes
6. Reports status

## vs /rebase-pr

| `/sync-branch` | `/rebase-pr` |
|----------------|--------------|
| Quick daily sync | Full PR cleanup |
| Stashes changes | Expects clean state |
| Interactive | More automated |
| Ongoing work | Ready for merge |


## Related Commands

_(To be determined based on command relationships)_
