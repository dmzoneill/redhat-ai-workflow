# 🔄 Sync Branch

Quickly rebase your current branch onto main.

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

