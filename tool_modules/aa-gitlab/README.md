# AA GitLab MCP Server

MCP server for GitLab operations via the `glab` CLI.

## Tools (32)

### Merge Requests
- `gitlab_mr_list` - List MRs
- `gitlab_mr_view` - View MR details
- `gitlab_mr_create` - Create MR
- `gitlab_mr_update` - Update MR
- `gitlab_mr_approve` - Approve MR
- `gitlab_mr_revoke` - Revoke approval
- `gitlab_mr_merge` - Merge MR
- `gitlab_mr_close` - Close MR
- `gitlab_mr_reopen` - Reopen MR
- `gitlab_mr_comment` - Add comment
- `gitlab_mr_diff` - View diff
- `gitlab_mr_rebase` - Rebase MR
- `gitlab_mr_checkout` - Checkout locally
- `gitlab_mr_approvers` - List approvers

### CI/CD
- `gitlab_ci_list` - List pipelines
- `gitlab_ci_status` - Pipeline status
- `gitlab_ci_view` - View pipeline
- `gitlab_ci_run` - Trigger pipeline
- `gitlab_ci_retry` - Retry job
- `gitlab_ci_cancel` - Cancel pipeline
- `gitlab_ci_trace` - Get job logs
- `gitlab_ci_lint` - Validate CI config

### Repository & Issues
- `gitlab_repo_view` - View project
- `gitlab_repo_clone` - Get clone command
- `gitlab_issue_list` - List issues
- `gitlab_issue_view` - View issue
- `gitlab_issue_create` - Create issue
- `gitlab_label_list` - List labels
- `gitlab_release_list` - List releases
- `gitlab_user_info` - Current user

## Installation

```bash
cd tool_modules/aa-gitlab
pip install -e .
```

## Prerequisites

- `glab` CLI installed: `brew install glab` or https://gitlab.com/gitlab-org/cli
- Authenticated: `glab auth login`

## Usage

```json
{
  "mcpServers": {
    "gitlab": {
      "command": "aa-gitlab",
      "env": {
        "GITLAB_HOST": "gitlab.com"
      }
    }
  }
}
```
