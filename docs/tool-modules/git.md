# 📂 git

> Git repository operations

## Overview

The `aa_git` module provides tools for Git operations including status, branches, commits, and more.

## Tool Count

**30 tools**

## Tools

| Tool | Description |
|------|-------------|
| `git_status` | Show working tree status |
| `git_branch_list` | List branches |
| `git_branch_create` | Create a new branch |
| `git_checkout` | Switch branches or restore files |
| `git_commit` | Record changes (auto-formats with config.json) |
| `git_push` | Push commits to remote |
| `git_pull` | Fetch and integrate with remote |
| `git_fetch` | Download objects and refs |
| `git_log` | Show commit history |
| `git_diff` | Show changes between commits |
| `git_show` | Show commit details |
| `git_diff_tree` | Get files changed in commit |
| `git_stash` | Stash changes temporarily |
| `git_merge` | Join branches together |
| `git_merge_abort` | Abort in-progress merge |
| `git_rebase` | Reapply commits on top of another base |
| `git_reset` | Reset HEAD to specified state |
| `git_clean` | Remove untracked files |
| `git_add` | Stage files for commit |
| `git_config_get` | Get config values |
| `git_rev_parse` | Parse and resolve git references |
| `git_remote_info` | Get remote repository info |
| `code_format` | Format code with black/isort/ruff |
| `code_lint` | Run linting with flake8/ruff/pylint |
| `make_target` | Run make targets |
| `docker_compose_status` | Check container status |
| `docker_compose_up` | Start services |
| `docker_compose_down` | Stop services |
| `docker_cp` | Copy files to/from container |
| `docker_exec` | Execute command in container |

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

The `git_commit` tool auto-formats messages using `config.json`:

```python
git_commit(
    repo="/path/to/repo",
    message="Add new feature",
    issue_key="AAP-12345",
    commit_type="feat"
)
# → Creates: "AAP-12345 - feat: Add new feature"
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

- [👨‍💻 Developer Persona](../personas/developer.md)
- [📦 Release Persona](../personas/release.md)

## Related Skills

- [start_work](../skills/start_work.md) - Creates branches
- [sync_branch](../skills/sync_branch.md) - Syncs with main
- [rebase_pr](../skills/rebase_pr.md) - Rebases branches
