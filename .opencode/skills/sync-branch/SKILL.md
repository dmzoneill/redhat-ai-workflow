---
name: sync-branch
description: Quickly sync current branch with main using rebase
license: MIT
compatibility: opencode
metadata:
  version: "1.3"
  source: sync_branch.yaml
  executable: "true"
---

# sync_branch

Quickly sync current branch with main using rebase.

Less aggressive than rebase_pr - good for ongoing work:
- Fetches latest main
- Rebases current branch onto main
- Auto-resolves simple conflicts
- Reports status

Uses MCP tools: git_status, git_fetch, git_stash, git_push

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("sync_branch", '{
  "repo": "example-repo",
  "repo_name": "example-repo_name",
  "issue_key": "example-issue_key",
  "base_branch": "example-base_branch",
  "stash_changes": true,
  "force_push": false,
  "run_linting": true
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load developer persona for Git tools**
2. **Initialize failure tracking**
3. **Get git/branching patterns from knowledge base**
4. **Parse git knowledge for rebase context**
5. **Check for known git rebase issues**
6. **Determine which repo to use**
7. **Get current branch and check for uncommitted changes**
8. **Parse git status output using shared parser**
9. **Stash uncommitted changes**
10. **Fetch latest from remote**
11. **Check how many commits behind**
12. **Check how many commits ahead**
13. **Parse commit counts**
14. **Rebase onto base branch**
15. **Check for conflicts after rebase**
16. **Parse rebase result**
17. **Branch is already up to date**
18. **Restore stashed changes**
19. **Check code formatting before push**
20. **Run flake8 linting before push**
21. **Parse lint results and warn if issues**
22. **Block push if lint fails**
23. **Force push rebased branch**
24. **Search for code related to this branch**
25. **Parse branch code search results**
26. **Log branch sync to session**
27. **Learn from branch sync for future reference**
28. **Track branches that frequently fall behind**
29. **Save sync context for other skills**
30. **Detect failure patterns from sync operations**
31. **Learn from rebase conflict failures**
32. **Learn from push rejected failures**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `repo` | string | No | `-` | Repository path - if not provided, resolved from issue_key or repo_name |
| `repo_name` | string | No | `-` | Repository name from config (e.g., 'automation-analytics-backend') |
| `issue_key` | string | No | `-` | Jira issue key - used to resolve repo if repo not specified |
| `base_branch` | string | No | `-` | Branch to sync with (default: repo's default_branch from config) |
| `stash_changes` | boolean | No | `true` | Stash uncommitted changes before rebase |
| `force_push` | boolean | No | `false` | Force push after successful rebase |
| `run_linting` | boolean | No | `true` | Run linting before force push (if force_push is true) |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the sync_branch skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("sync_branch", '{
  "repo": "example-repo",
  "repo_name": "example-repo_name",
  "issue_key": "example-issue_key",
  "base_branch": "example-base_branch",
  "stash_changes": true,
  "force_push": false,
  "run_linting": true
}')
```

### Via Command (if configured)

```
/sync-branch
```

## MCP Tools Used

- `code_search`
- `git_fetch`
- `git_format`
- `git_lint`
- `git_log`
- `git_push`
- `git_rebase`
- `git_stash`
- `git_status`
- `knowledge_query`
- `learn_tool_fix`
- `memory_session_log`
- `persona_load`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/sync_branch.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/sync_branch.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
