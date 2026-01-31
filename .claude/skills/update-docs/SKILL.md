---
name: update-docs
description: Check and update repository documentation before creating a PR/MR
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: update_docs.yaml
  executable: "true"
---

# update_docs

Check and update repository documentation before creating a PR/MR.
- Scans for outdated docs based on code changes
- Updates mermaid diagrams if architecture changed
- Checks README.md for accuracy
- Updates API docs if endpoints changed
- Only runs for repos with docs.enabled=true in config.json

Uses MCP tools: git_log, git_diff, git_status, git_add, git_commit

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("update_docs", '{
  "repo": "example-repo",
  "repo_name": "example-repo_name",
  "issue_key": "example-issue_key",
  "auto_commit": false,
  "check_only": false
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Search for code related to the documentation update**
2. **Parse doc code search results**
3. **Get documentation patterns from knowledge**
4. **Parse documentation patterns**
5. **Check for known documentation issues**
6. **Determine which repo to check**
7. **Skip if docs not enabled for this repo**
8. **Get list of files changed in this branch**
9. **Check if README needs updating based on changes**
10. **Check if API docs need updating**
11. **Check mermaid diagrams for staleness**
12. **Compile all documentation suggestions**
13. **Log documentation check to session**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `repo` | string | No | `-` | Repository path - if not provided, uses current directory |
| `repo_name` | string | No | `-` | Repository name from config (e.g., 'automation-analytics-backend') |
| `issue_key` | string | No | `-` | Jira issue key for commit message |
| `auto_commit` | boolean | No | `false` | Automatically commit doc updates |
| `check_only` | boolean | No | `false` | Only check, don't suggest updates |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the update_docs skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("update_docs", '{
  "repo": "example-repo",
  "repo_name": "example-repo_name",
  "issue_key": "example-issue_key",
  "auto_commit": false,
  "check_only": false
}')
```

### Via Command (if configured)

```
/update-docs
```

## MCP Tools Used

- `code_search`
- `knowledge_query`
- `memory_session_log`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/update_docs.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/update_docs.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
