---
name: create-mr
description: Create a merge request with full validation:
license: MIT
compatibility: opencode
metadata:
  version: "3.0"
  source: create_mr.yaml
  executable: "true"
---

# create_mr

Create a merge request with full validation:
- Automatically resolves repo and GitLab project from issue key if not provided
- Checks for uncommitted changes
- Validates commit message format (AAP-XXXXX)
- Runs black/flake8 linting
- Checks if branch can merge cleanly
- Optionally runs jira_hygiene first
- Creates MR with proper description
- Links to Jira and updates status

**NEW Features:**
- Suggests reviewers based on code ownership (git blame + knowledge)
- Loads coding patterns to include in MR description
- Checks for related documentation that may need updating

Uses MCP tools: git_status, git_fetch, git_log, git_push, gitlab_mr_list,
                gitlab_mr_create, jira_view_issue, jira_add_comment, jira_set_status,
                code_search, knowledge_query, git_blame

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("create_mr", '{
  "issue_key": "example-issue_key",
  "repo": "example-repo",
  "repo_name": "example-repo_name",
  "draft": true,
  "target_branch": "example-target_branch",
  "run_linting": true,
  "check_jira": true,
  "auto_fix_lint": false,
  "slack_format": false,
  "check_docs": true,
  "skip_docs_warning": false
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load developer persona for Git, GitLab, and Jira tools**
2. **Check for known GitLab issues before starting**
3. **Check for known git issues before starting**
4. **Determine which repo and GitLab project to use**
5. **Check for uncommitted changes and git state**
6. **Parse git status for issues**
7. **Fetch latest from origin**
8. **Get commits ahead of target branch**
9. **Check commit messages follow config.json commit_format pattern**
10. **Test if branch can merge cleanly**
11. **Abort the test merge**
12. **Determine if branch is mergeable**
13. **Read GitLab CI configuration to understand pipeline**
14. **Parse CI config for key jobs**
15. **Check if MR already exists for this branch**
16. **Parse MRs to find duplicate using shared parser**
17. **Get list of changed files for reviewer suggestion**
18. **Get blame info to suggest reviewers**
19. **Suggest reviewers based on code ownership**
20. **Load coding patterns to reference in MR**
21. **Parse coding patterns**
22. **Search for related code to reference**
23. **Parse related code search**
24. **Check if black and flake8 are installed**
25. **Run black formatter check**
26. **Parse black result**
27. **Block MR creation if black formatting needed**
28. **Get list of Python files changed in this branch**
29. **Run flake8 linting on changed files only**
30. **Parse flake8 result and block if issues found**
31. **Block MR creation if there are lint errors**
32. **Check if docs should be checked for this repo**
33. **Run documentation check skill**
34. **Parse documentation check results**
35. **Warn about documentation issues (non-blocking)**
36. **Fetch Jira issue details**
37. **Check Jira issue quality**
38. **Validate .gitlab-ci.yml before creating MR**
39. **Parse CI lint result**
40. **Push branch to origin**
41. **Detect predominant commit type from commits**
42. **Build MR description with Jira link and knowledge context**
43. **Build MR title following commit format from config.json**
44. **Create GitLab merge request**
45. **Add MR link to Jira issue**
46. **Move Jira to In Review (if not draft)**
47. **Use notify_mr skill to post to team channel**
48. **Notify team channel about new MR**
49. **Build context for memory update**
50. **Log MR creation to session log**
51. **Add MR to open_mrs in memory**
52. **Update active issue status if MR is not draft**
53. **Detect failure patterns from MR creation**
54. **Learn from GitLab VPN failures**
55. **Learn from GitLab auth failures**
56. **Learn from merge conflict failures**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `issue_key` | string | Yes | `-` | Jira issue key for linking (e.g., AAP-12345) |
| `repo` | string | No | `-` | Repository path - if not provided, resolved from issue key via config |
| `repo_name` | string | No | `-` | Repository name from config (e.g., 'automation-analytics-backend') |
| `draft` | boolean | No | `true` | Create as draft MR |
| `target_branch` | string | No | `-` | Target branch for MR (defaults to repo's default_branch from config) |
| `run_linting` | boolean | No | `true` | Run black/flake8 before creating MR |
| `check_jira` | boolean | No | `true` | Run jira_hygiene check before creating MR |
| `auto_fix_lint` | boolean | No | `false` | Auto-fix linting issues with black |
| `slack_format` | boolean | No | `false` | Use Slack link format |
| `check_docs` | boolean | No | `true` | Check documentation for staleness (if docs.check_on_mr=true in config) |
| `skip_docs_warning` | boolean | No | `false` | Skip documentation warnings (proceed even if docs need updating) |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the create_mr skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("create_mr", '{
  "issue_key": "example-issue_key",
  "repo": "example-repo",
  "repo_name": "example-repo_name",
  "draft": true,
  "target_branch": "example-target_branch",
  "run_linting": true,
  "check_jira": true,
  "auto_fix_lint": false,
  "slack_format": false,
  "check_docs": true,
  "skip_docs_warning": false
}')
```

### Via Command (if configured)

```
/create-mr
```

## MCP Tools Used

- `check_known_issues`
- `code_search`
- `git_blame`
- `git_fetch`
- `git_format`
- `git_lint`
- `git_log`
- `git_merge`
- `git_merge_abort`
- `git_push`
- `git_status`
- `gitlab_ci_lint`
- `gitlab_file_read`
- `gitlab_mr_create`
- `gitlab_mr_list`
- `jira_add_comment`
- `jira_set_status`
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
- **Source**: `skills/create_mr.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/create_mr.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
