# Git Safety Rules

## ⛔ CRITICAL: Never Discard Work Without Permission

**NEVER run `git checkout` on files without explicit user permission!**

This has caused catastrophic loss of uncommitted work. Before ANY git operation that could discard changes:

1. **ASK the user first** - "Can I revert file X? This will discard uncommitted changes."
2. **Check `git status`** - See what's modified
3. **Check `git diff`** - See what would be lost
4. **Consider `git stash`** - Preserve changes before destructive operations

## Destructive Commands Requiring Permission

These commands require explicit user permission:

| Command | Effect |
|---------|--------|
| `git checkout -- <file>` | Discards changes to file |
| `git reset --hard` | Discards ALL changes |
| `git clean -fd` | Deletes untracked files |
| `git stash drop` | Deletes stashed changes |

## Safe Workflow

```bash
# ALWAYS check first
git status
git diff

# If you need to discard changes, ASK FIRST
# "Can I revert changes to src/app.py? This will discard uncommitted work."

# If user agrees, prefer stash over discard
git stash push -m "Before reverting src/app.py"
```

## Commit Conventions

- **Commit messages**: Use `git_commit` tool - format from `config.json`: `{issue_key} - {type}({scope}): {description}`
- **Branch names**: `aap-xxxxx-short-description`
- **Always link Jira issues** in MR descriptions
- **Check pipeline status** after pushing
