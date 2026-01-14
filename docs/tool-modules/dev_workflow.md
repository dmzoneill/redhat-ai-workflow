# aa_dev_workflow - Development Workflow Tools

High-level workflow coordination tools for common development tasks.

## Overview

| Metric | Value |
|--------|-------|
| **Total Tools** | 9 |
| **Basic Tools** | 9 |
| **Extra Tools** | 0 |
| **Auto-Heal** | Yes |

## Tools

### Basic Tools (9)

| Tool | Description |
|------|-------------|
| `workflow_start_work` | Get context to start working on a Jira issue |
| `workflow_check_deploy_readiness` | Check if MR is ready to deploy |
| `workflow_review_feedback` | Get guidance on addressing review feedback |
| `workflow_create_branch` | Create a feature branch from a Jira issue |
| `workflow_prepare_mr` | Prepare a Merge Request |
| `workflow_run_local_checks` | Run local linting and validation |
| `workflow_monitor_pipelines` | Monitor GitLab + Konflux pipelines |
| `workflow_handle_review` | Prepare to handle MR review feedback |
| `workflow_daily_standup` | Generate a summary of recent work |

## Usage Examples

### Start Working on an Issue

```python
workflow_start_work(issue_key="AAP-12345")
```

### Check Deploy Readiness

```python
workflow_check_deploy_readiness(project="backend", mr_id=1459, environment="stage")
```

### Run Local Checks

```python
workflow_run_local_checks(repo="backend")
```

## Auto-Heal Support

All tools in this module are decorated with `@auto_heal()` for automatic VPN and authentication recovery.

## Related Modules

- [workflow](workflow.md) - Core workflow tools (memory, personas, skills)
- [git](git.md) - Git operations
- [gitlab](gitlab.md) - GitLab MR and CI operations
- [jira](jira.md) - Jira issue tracking
