---
name: rebase-pr
description: Rebase a PR branch onto main to clean up merge commits
license: MIT
compatibility: opencode
metadata:
  version: "1.2"
  source: rebase_pr.yaml
  executable: "true"
---

# rebase_pr

Rebase a PR branch onto main to clean up merge commits.

If 'repo_path' is not provided, resolves from issue_key or repo_name via config.

Steps:
1. Check for merge commits on the PR
2. Checkout the branch locally
3. Pull latest from remote
4. Rebase onto main
5. If conflicts: guide user through resolution
6. Force push rebased branch

Handles merge conflicts by pausing and showing what needs to be fixed.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("rebase_pr", '{
  "mr_id": "example-mr_id",
  "issue_key": "example-issue_key",
  "branch": "example-branch",
  "repo_path": "example-repo_path",
  "repo_name": "example-repo_name",
  "base_branch": "example-base_branch",
  "force_push": false,
  "run_linting": true
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load developer persona for Git and GitLab tools**
2. **Initialize failure tracking**
3. **Check for known rebase issues**
4. **Load previous rebase history for this branch**
5. **Get coding patterns from knowledge for conflict resolution**
6. **Parse coding patterns**
7. **Determine which repo and GitLab project to use**
8. **Ensure we have a way to identify the branch**
9. **Get branch name from MR**
10. **List all branches for issue key lookup**
11. **Extract branch name from MR or issue key using shared parsers**
12. **Fetch latest from all remotes**
13. **Get merge commits on the branch**
14. **Get total commit count**
15. **Parse merge commit info using shared parser**
16. **Check for uncommitted changes**
17. **Stash any local changes**
18. **Checkout the target branch**
19. **Fallback: force checkout from remote if local failed**
20. **Pull latest from remote**
21. **Reset to remote if pull failed**
22. **Record sync status**
23. **Fetch base branch from remote**
24. **Start the rebase onto base branch**
25. **Parse rebase output into structured result using shared parser**
26. **Find similar code patterns to help resolve conflicts**
27. **Parse conflict context search results**
28. **Analyze conflicts and auto-resolve obvious ones**
29. **Stage auto-resolved conflict files**
30. **Continue rebase if all conflicts auto-resolved**
31. **Check if new conflicts emerged after continue**
32. **Parse the rebase continue result**
33. **Update rebase result after auto-resolution**
34. **Run flake8 linting on changed files**
35. **Run black formatting check on changed files**
36. **Check if linting passed**
37. **Dry-run to check if force push is allowed**
38. **Check dry-run result for protection issues**
39. **Force push rebased branch**
40. **Build result summary**
41. **Notify author about rebase result**
42. **Log rebase to session**
43. **Log rebase to session**
44. **Learn from this rebase for future reference**
45. **Track files that frequently have conflicts during rebases**
46. **Update MR state in memory after rebase**
47. **Detect failure patterns from rebase operations**
48. **Learn from rebase conflict failures**
49. **Learn from GitLab VPN failures**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `mr_id` | integer | No | `-` | GitLab MR ID - will find the branch |
| `issue_key` | string | No | `-` | Jira issue key - will find the branch and resolve repo |
| `branch` | string | No | `-` | Branch name directly (if known) |
| `repo_path` | string | No | `-` | Path to repository - if not provided, resolved from issue_key or repo_name |
| `repo_name` | string | No | `-` | Repository name from config (e.g., 'automation-analytics-backend') |
| `base_branch` | string | No | `-` | Branch to rebase onto (default: repo's default_branch from config) |
| `force_push` | boolean | No | `false` | Auto force-push after successful rebase (asks if false) |
| `run_linting` | boolean | No | `true` | Run linting (black/flake8) before pushing (default: true) |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the rebase_pr skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("rebase_pr", '{
  "mr_id": "example-mr_id",
  "issue_key": "example-issue_key",
  "branch": "example-branch",
  "repo_path": "example-repo_path",
  "repo_name": "example-repo_name",
  "base_branch": "example-base_branch",
  "force_push": false,
  "run_linting": true
}')
```

### Via Command (if configured)

```
/rebase-pr
```

## MCP Tools Used

- `code_search`
- `git_add`
- `git_branch_list`
- `git_checkout`
- `git_fetch`
- `git_log`
- `git_pull`
- `git_push`
- `git_rebase`
- `git_reset`
- `git_stash`
- `git_status`
- `gitlab_mr_view`
- `knowledge_query`
- `learn_tool_fix`
- `lint_python`
- `memory_session_log`
- `persona_load`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/rebase_pr.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/rebase_pr.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
