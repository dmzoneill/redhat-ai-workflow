---
name: start-work
description: Begin or resume working on a Jira issue
license: MIT
compatibility: opencode
metadata:
  version: "2.0"
  source: start_work.yaml
  executable: "true"
---

# start_work

Begin or resume working on a Jira issue.

If 'repo' is not provided, automatically resolves the repository from the
issue key prefix (e.g., AAP → automation-analytics-backend) using config.json.

Features:
- Gets issue context from Jira
- Creates or checks out feature branch
- Shows MR feedback if exists
- Updates Jira status
- **NEW:** Searches codebase for related code using semantic vector search
- **NEW:** Loads project-specific gotchas and patterns from knowledge base
- **NEW:** Shows relevant error patterns from learned memory

Uses MCP tools: jira_view_issue, git_fetch, git_branch_list, git_checkout,
                git_branch_create, git_pull, gitlab_mr_list, gitlab_mr_view,
                gitlab_mr_comments, gitlab_ci_status, jira_set_status,
                code_search, knowledge_query, check_known_issues

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("start_work", '{
  "issue_key": "example-issue_key",
  "repo": "example-repo",
  "repo_name": "example-repo_name",
  "auto_stash": true,
  "slack_format": false
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load developer persona for Git, GitLab, and Jira tools**
2. **Determine which repo to use based on issue key or explicit input**
3. **Ensure we're in a valid git repository**
4. **Check if git status indicates any issues**
5. **Validate issue key format using shared parser**
6. **get_issue**
7. **Verify issue was found**
8. **Find code related to this issue using semantic search**
9. **Parse semantic search results**
10. **Load relevant gotchas for this project**
11. **Parse gotchas into actionable list**
12. **Load architecture overview for context**
13. **Parse architecture context**
14. **Check memory for patterns related to this issue**
15. **Parse related error patterns**
16. **Fetch all remotes**
17. **List all branches**
18. **Find branch matching this issue key using shared parser**
19. **Search for open MRs matching this issue**
20. **Find MR matching our issue key or branch using shared parser**
21. **Get MR details**
22. **Get MR review comments**
23. **Get CI pipeline status**
24. **Analyze MR feedback for actionable items using shared parser**
25. **Check for recent Jira comments or status changes**
26. **Parse Jira details for updates using shared parser**
27. **create_branch_name**
28. **Stash any uncommitted changes before checkout**
29. **Parse stash result**
30. **Checkout existing branch for this issue**
31. **Pull latest changes**
32. **Checkout main branch**
33. **Pull latest main**
34. **Create new feature branch**
35. **update_status**
36. **Transition issue to In Progress via workflow**
37. **Assign issue to current user**
38. **get_final_branch**
39. **Ensure Jira issue has proper details (uses jira_hygiene skill)**
40. **Log work start to session log**
41. **Notify team channel that work started (uses notify_team skill)**
42. **Extract issue summary and generate timestamp**
43. **Add issue to active_issues in memory**
44. **Update last_updated in current_work**
45. **Detect failure patterns from start work operations**
46. **Learn from Jira failures**
47. **Learn from GitLab VPN failures**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `issue_key` | string | Yes | `-` | Jira issue key (e.g., AAP-12345) |
| `repo` | string | No | `-` | Repository path - if not provided, resolved from issue key via config |
| `repo_name` | string | No | `-` | Repository name from config (e.g., 'automation-analytics-backend') - alternative to repo path |
| `auto_stash` | boolean | No | `true` | Automatically stash uncommitted changes before checkout (default: true) |
| `slack_format` | boolean | No | `false` | Use Slack link format |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the start_work skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("start_work", '{
  "issue_key": "example-issue_key",
  "repo": "example-repo",
  "repo_name": "example-repo_name",
  "auto_stash": true,
  "slack_format": false
}')
```

### Via Command (if configured)

```
/start-work
```

## MCP Tools Used

- `check_known_issues`
- `code_search`
- `git_branch_create`
- `git_branch_list`
- `git_checkout`
- `git_fetch`
- `git_pull`
- `git_stash`
- `git_status`
- `gitlab_ci_status`
- `gitlab_mr_comments`
- `gitlab_mr_list`
- `gitlab_mr_view`
- `jira_assign`
- `jira_set_status`
- `jira_transition`
- `jira_view_issue`
- `knowledge_query`
- `learn_tool_fix`
- `memory_append`
- `memory_session_log`
- `memory_update`
- `persona_load`
- `skill_run`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/start_work.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/start_work.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
