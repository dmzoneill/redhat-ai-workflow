# GitHub Tools

> aa_github module for GitHub CLI (gh) operations

## Diagram

```mermaid
classDiagram
    class RepositoryTools {
        +gh_repo_list(): str
        +gh_repo_view(repo): str
        +gh_repo_clone(repo): str
        +gh_repo_create(name): str
        +gh_repo_fork(repo): str
        +gh_repo_delete(repo): str
    }

    class PullRequestTools {
        +gh_pr_list(repo): str
        +gh_pr_view(pr_num): str
        +gh_pr_create(title, body): str
        +gh_pr_checkout(pr_num): str
        +gh_pr_merge(pr_num): str
        +gh_pr_close(pr_num): str
        +gh_pr_reopen(pr_num): str
        +gh_pr_review(pr_num): str
        +gh_pr_diff(pr_num): str
        +gh_pr_checks(pr_num): str
    }

    class IssueTools {
        +gh_issue_list(repo): str
        +gh_issue_view(issue_num): str
        +gh_issue_create(title, body): str
        +gh_issue_close(issue_num): str
        +gh_issue_reopen(issue_num): str
        +gh_issue_comment(issue_num, body): str
        +gh_issue_edit(issue_num): str
    }

    class WorkflowTools {
        +gh_workflow_list(repo): str
        +gh_workflow_view(workflow): str
        +gh_run_list(repo): str
        +gh_run_view(run_id): str
        +gh_run_watch(run_id): str
        +gh_run_rerun(run_id): str
        +gh_run_cancel(run_id): str
    }
```

## Tool Categories

```mermaid
graph TB
    subgraph Repository[Repository Management]
        LIST[gh_repo_list]
        VIEW[gh_repo_view]
        CLONE[gh_repo_clone]
        CREATE[gh_repo_create]
        FORK[gh_repo_fork]
    end

    subgraph PR[Pull Requests]
        PR_LIST[gh_pr_list]
        PR_CREATE[gh_pr_create]
        PR_MERGE[gh_pr_merge]
        PR_REVIEW[gh_pr_review]
        PR_CHECKS[gh_pr_checks]
    end

    subgraph Issues[Issues]
        ISSUE_LIST[gh_issue_list]
        ISSUE_CREATE[gh_issue_create]
        ISSUE_COMMENT[gh_issue_comment]
    end

    subgraph Actions[GitHub Actions]
        WORKFLOW_LIST[gh_workflow_list]
        RUN_LIST[gh_run_list]
        RUN_WATCH[gh_run_watch]
    end
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| tools_basic.py | `tool_modules/aa_github/src/` | All GitHub CLI tools |

## Tool Summary

### Repository Tools

| Tool | Description |
|------|-------------|
| `gh_repo_list` | List repositories |
| `gh_repo_view` | View repository details |
| `gh_repo_clone` | Clone a repository |
| `gh_repo_create` | Create a new repository |
| `gh_repo_fork` | Fork a repository |
| `gh_repo_delete` | Delete a repository |

### Pull Request Tools

| Tool | Description |
|------|-------------|
| `gh_pr_list` | List pull requests |
| `gh_pr_view` | View pull request details |
| `gh_pr_create` | Create a pull request |
| `gh_pr_checkout` | Checkout a pull request locally |
| `gh_pr_merge` | Merge a pull request |
| `gh_pr_close` | Close a pull request |
| `gh_pr_review` | Review a pull request |
| `gh_pr_diff` | View pull request diff |
| `gh_pr_checks` | View PR check status |

### Issue Tools

| Tool | Description |
|------|-------------|
| `gh_issue_list` | List issues |
| `gh_issue_view` | View issue details |
| `gh_issue_create` | Create an issue |
| `gh_issue_close` | Close an issue |
| `gh_issue_comment` | Add comment to an issue |

### Workflow/Actions Tools

| Tool | Description |
|------|-------------|
| `gh_workflow_list` | List workflows |
| `gh_workflow_view` | View workflow details |
| `gh_run_list` | List workflow runs |
| `gh_run_view` | View workflow run details |
| `gh_run_watch` | Watch a workflow run |
| `gh_run_rerun` | Re-run a workflow |
| `gh_run_cancel` | Cancel a workflow run |

## Prerequisites

Requires GitHub CLI (`gh`) to be installed and authenticated:

```bash
# Install
brew install gh  # macOS
dnf install gh   # Fedora

# Authenticate
gh auth login
```

## Usage Examples

```python
# List repositories
result = await gh_repo_list()

# View a pull request
result = await gh_pr_view("owner/repo", 123)

# Create a pull request
result = await gh_pr_create("Fix bug", "This PR fixes...")

# Watch a workflow run
result = await gh_run_watch("12345")
```

## Related Diagrams

- [Git Tools](./git-tools.md)
- [GitLab Tools](./gitlab-tools.md)
- [Tool Module Structure](./tool-module-structure.md)
