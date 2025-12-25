# 🦊 gitlab

> GitLab MRs, pipelines, and code review

## Overview

The `aa-gitlab` module provides tools for GitLab operations including merge requests, pipelines, comments, and project management.

## Tool Count

**36 tools**

## Tools

### Merge Requests

| Tool | Description |
|------|-------------|
| `gitlab_mr_list` | List merge requests |
| `gitlab_mr_view` | View MR details |
| `gitlab_mr_create` | Create a new MR |
| `gitlab_mr_approve` | Approve an MR |
| `gitlab_mr_merge` | Merge an MR |
| `gitlab_mr_close` | Close an MR |
| `gitlab_mr_reopen` | Reopen an MR |
| `gitlab_mr_diff` | Get MR diff |
| `gitlab_mr_comments` | Get MR comments |
| `gitlab_mr_add_comment` | Add comment to MR |

### Pipelines

| Tool | Description |
|------|-------------|
| `gitlab_pipeline_list` | List pipelines |
| `gitlab_pipeline_status` | Get pipeline status |
| `gitlab_pipeline_retry` | Retry a pipeline |
| `gitlab_pipeline_cancel` | Cancel a pipeline |
| `gitlab_job_logs` | Get job logs |

### Projects

| Tool | Description |
|------|-------------|
| `gitlab_project_info` | Get project info |
| `gitlab_project_branches` | List branches |
| `gitlab_ci_status` | Get CI status |
| `gitlab_search_mrs_by_issue` | Find MRs by Jira key |

## Usage Examples

### List Open MRs

```python
gitlab_mr_list(
    project="automation-analytics/automation-analytics-backend",
    state="opened",
    author="@me"
)
```

### View MR Details

```python
gitlab_mr_view(
    project="automation-analytics/automation-analytics-backend",
    mr_id=456
)
```

### Create MR

```python
gitlab_mr_create(
    project="automation-analytics/automation-analytics-backend",
    source_branch="aap-12345-feature",
    target_branch="main",
    title="AAP-12345 - feat: Add new feature",
    description="...",
    draft=True
)
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GITLAB_TOKEN` | Yes | GitLab API token |

> Uses `glab` CLI under the hood for most operations.

## Loaded By

- [👨‍💻 Developer Agent](../agents/developer.md)
- [🔧 DevOps Agent](../agents/devops.md)
- [💬 Slack Agent](../agents/slack.md)

## Related Skills

- [create_mr](../skills/create_mr.md) - Creates merge requests
- [review_pr](../skills/review_pr.md) - Reviews MRs
- [check_my_prs](../skills/check_my_prs.md) - Checks PR status

