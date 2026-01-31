---
name: review-pr
description: Review a colleague's PR/MR
license: MIT
compatibility: opencode
metadata:
  version: "2.0"
  source: review_pr.yaml
  executable: "true"
---

# review_pr

Review a colleague's PR/MR.

Resolves repository from issue_key, repo_name, or current directory.

Accepts EITHER:
- mr_id: GitLab MR number (e.g., 123)
- issue_key: Jira issue key (e.g., AAP-61214) - will find the MR

Checks MR description, commit format, pipelines, Jira context,
runs local tests, and provides brief focused feedback.

**NEW Features:**
- Semantic search for similar code patterns in codebase
- Architecture validation against project knowledge
- Pattern checking against learned error patterns
- Author history and coaching based on past reviews

Automatically approves or posts feedback based on findings.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("review_pr", '{
  "mr_id": "example-mr_id",
  "url": "example-url",
  "issue_key": "example-issue_key",
  "repo_name": "example-repo_name",
  "run_tests": false,
  "auto_merge": false,
  "slack_format": false
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load developer persona for GitLab, Git, and Jira tools**
2. **Determine which repo, GitLab project, and settings to use**
3. **Ensure we have mr_id, url, or issue_key**
4. **Find MR associated with Jira issue**
5. **Extract MR ID from inputs, URL, or search results using shared parser**
6. **Set the MR ID for remaining steps**
7. **Check memory for known GitLab API issues before fetching MR**
8. **Apply pre-emptive fixes based on known patterns**
9. **Load previous review if this is a re-review**
10. **Fetch MR details from GitLab**
11. **Get commit history for the MR**
12. **Parse commit history**
13. **Get the code diff for the MR**
14. **Parse diff to identify changed files**
15. **Get blame info for main changed file**
16. **Extract authorship info from blame**
17. **Extract AAP-XXXXX from MR title**
18. **Find similar code patterns to validate against conventions**
19. **Parse similar code search results**
20. **Load architecture knowledge to validate changes**
21. **Parse architecture modules for validation**
22. **Check if changes align with project architecture**
23. **Load coding patterns for the project**
24. **Parse coding patterns**
25. **Check diff against known error patterns**
26. **Parse problematic pattern matches**
27. **Get Jira issue context**
28. **Get code changes**
29. **Validate diff size to avoid context overflow**
30. **set_mr_diff**
31. **Check GitLab CI status**
32. **Get pipeline trace if failed**
33. **Save pipeline failure patterns for faster diagnosis**
34. **Get MR approvers list**
35. **Parse approvers list**
36. **Load release persona for Konflux tools**
37. **Check Konflux integration tests**
38. **Check commit title matches commit_format pattern from config.json**
39. **Save new format issues to patterns for future detection**
40. **Verify MR has adequate description**
41. **Extract source branch from MR details using shared parser**
42. **Fetch latest from origin**
43. **Checkout MR branch locally**
44. **Fallback: fetch MR directly**
45. **Checkout after MR fetch**
46. **Verify docker-compose is running**
47. **Start docker-compose if containers not running**
48. **Set docker status**
49. **Run make migrations**
50. **Run make data**
51. **Summarize setup results**
52. **Run pytest in FastAPI container**
53. **Copy test script to container**
54. **Run tests in container**
55. **Parse test execution results**
56. **Static analysis for security, memory, race conditions**
57. **Track common code issues per author for coaching**
58. **Capture tech debt, missing tests, and other discovered work (with deduplication)**
59. **Compile review findings**
60. **Decide whether to approve or request changes**
61. **Build feedback message for GitLab**
62. **Post review feedback to MR**
63. **Approve the MR on GitLab**
64. **Save successful review patterns for quick reference**
65. **Notify author that MR was approved**
66. **Notify author that feedback was posted**
67. **Extract MR author GitLab username for Slack notification**
68. **Check if we've reviewed this author's MRs before**
69. **Load slack persona for Slack DM tools**
70. **Send Slack DM to author that MR was approved**
71. **Send Slack DM to author that feedback was posted**
72. **Add review note to Jira issue**
73. **Build context for memory updates**
74. **Log review to session**
75. **Track review in teammate preferences (learn reviewer patterns)**
76. **Share review findings for debug_prod, investigate_alert skills**
77. **Check if there's an active investigation that might relate to this review**
78. **Detect failure patterns from PR review operations**
79. **Learn from GitLab VPN failures**
80. **Learn from GitLab auth failures**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `mr_id` | integer | No | `-` | GitLab MR ID (e.g., 1234) |
| `url` | string | No | `-` | Full GitLab MR URL (e.g., https://gitlab.cee.redhat.com/org/repo/-/merge_requests/123) |
| `issue_key` | string | No | `-` | Jira issue key (e.g., AAP-61214) - will search for associated MR |
| `repo_name` | string | No | `-` | Repository name from config (e.g., 'automation-analytics-backend') |
| `run_tests` | boolean | No | `false` | Checkout branch and run local tests (default: false, static analysis only) |
| `auto_merge` | boolean | No | `false` | Automatically merge if approved (default: false) |
| `slack_format` | boolean | No | `false` | Use Slack link format in summary |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the review_pr skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("review_pr", '{
  "mr_id": "example-mr_id",
  "url": "example-url",
  "issue_key": "example-issue_key",
  "repo_name": "example-repo_name",
  "run_tests": false,
  "auto_merge": false,
  "slack_format": false
}')
```

### Via Command (if configured)

```
/review-pr
```

## MCP Tools Used

- `check_known_issues`
- `code_search`
- `docker_compose_status`
- `docker_compose_up`
- `docker_cp`
- `docker_exec`
- `git_blame`
- `git_checkout`
- `git_diff`
- `git_fetch`
- `gitlab_ci_status`
- `gitlab_ci_trace`
- `gitlab_commit_list`
- `gitlab_mr_approve`
- `gitlab_mr_approvers`
- `gitlab_mr_comment`
- `gitlab_mr_diff`
- `gitlab_mr_list`
- `gitlab_mr_view`
- `jira_add_comment`
- `jira_view_issue`
- `knowledge_query`
- `konflux_list_pipelines`
- `learn_tool_fix`
- `make_target`
- `memory_session_log`
- `persona_load`
- `slack_dm_gitlab_user`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/review_pr.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/review_pr.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
