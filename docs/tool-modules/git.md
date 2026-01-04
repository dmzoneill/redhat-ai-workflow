# 📂 git

> Git repository operations

## Overview

The `aa-git` module provides tools for Git operations including status, branches, commits, and more.

## Tool Count

**15 tools**

## Tools

| Tool | Description |
|------|-------------|
| `git_status` | Show working tree status |
| `git_branch_list` | List branches |
| `git_branch_create` | Create a new branch |
| `git_checkout` | Switch branches or restore files |
| `git_commit` | Record changes to repository |
| `git_push` | Push commits to remote |
| `git_pull` | Fetch and integrate with remote |
| `git_fetch` | Download objects and refs |
| `git_log` | Show commit history |
| `git_diff` | Show changes between commits |
| `git_stash` | Stash changes temporarily |
| `git_merge` | Join branches together |
| `git_rebase` | Reapply commits on top of another base |
| `git_config_get` | Get config values |
| `git_rev_parse` | Parse and resolve git references |

## Usage Examples

### Check Status

```python
git_status(repo="/path/to/repo")
```

### Create Branch

```python
git_branch_create(
    repo="/path/to/repo",
    branch_name="aap-12345-feature",
    checkout=True
)
```

### Commit Changes

```python
git_commit(
    repo="/path/to/repo",
    message="AAP-12345 - feat: Add new feature"
)
```

### View Log

```python
git_log(
    repo="/path/to/repo",
    author="daoneill",
    since="2025-01-01",
    limit=10
)
```

## Loaded By

- [👨‍💻 Developer Agent](../agents/developer.md)
- [📦 Release Agent](../agents/release.md)

## Related Skills

- [start_work](../skills/start_work.md) - Creates branches
- [sync_branch](../skills/sync_branch.md) - Syncs with main
- [rebase_pr](../skills/rebase_pr.md) - Rebases branches
