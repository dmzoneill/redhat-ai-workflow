---
name: cleanup-branches
description: Clean up old feature branches that have been merged or are stale
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: cleanup_branches.yaml
  executable: "true"
---

# cleanup_branches

Clean up old feature branches that have been merged or are stale.

The skill will:
1. Fetch latest from remote
2. List all local and remote branches
3. Identify merged branches
4. Delete merged branches (with confirmation)
5. Optionally clean up tracking refs

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("cleanup_branches", '{
  "repo": "example-repo",
  "dry_run": true,
  "include_remote": false,
  "older_than_days": 30,
  "protected_branches": "main,master,develop,release"
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load developer persona for Git tools**
2. **Initialize failure tracking**
3. **Get branch naming conventions from knowledge**
4. **Parse branch naming patterns**
5. **Check for known git branch issues**
6. **Determine repository path**
7. **Fetch latest from all remotes**
8. **List all local branches**
9. **List all remote branches**
10. **List all branches including remote**
11. **Search for Jira issues related to candidate branches**
12. **Parse branch code search results**
13. **Identify branches to delete**
14. **Delete first candidate branch**
15. **Delete second candidate branch**
16. **Delete third candidate branch**
17. **Count deleted branches**
18. **Log cleanup action**
19. **Learn from branch cleanup for future reference**
20. **Track frequently stale branches by pattern**
21. **Detect failure patterns from branch cleanup**
22. **Learn from git permission failures**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `repo` | string | No | `-` | Repository path (defaults to cwd) |
| `dry_run` | boolean | No | `true` | Just show what would be deleted (default: true for safety) |
| `include_remote` | boolean | No | `false` | Also delete remote branches (requires push access) |
| `older_than_days` | integer | No | `30` | Consider branches stale if no commits in this many days |
| `protected_branches` | string | No | `main,master,develop,release` | Comma-separated list of branches to never delete |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the cleanup_branches skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("cleanup_branches", '{
  "repo": "example-repo",
  "dry_run": true,
  "include_remote": false,
  "older_than_days": 30,
  "protected_branches": "main,master,develop,release"
}')
```

### Via Command (if configured)

```
/cleanup-branches
```

## MCP Tools Used

- `code_search`
- `git_branch_delete`
- `git_branch_list`
- `git_fetch`
- `git_remote`
- `knowledge_query`
- `learn_tool_fix`
- `memory_session_log`
- `persona_load`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/cleanup_branches.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/cleanup_branches.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
