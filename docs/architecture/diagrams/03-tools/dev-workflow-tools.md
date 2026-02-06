# Development Workflow Tools

> aa_dev_workflow module for high-level development workflow coordination

## Diagram

```mermaid
classDiagram
    class DevWorkflowBasic {
        +workflow_start_work(issue_key): str
        +workflow_create_branch(issue_key): str
        +workflow_prepare_mr(): str
        +workflow_run_local_checks(): str
        +workflow_check_deploy_readiness(): str
        +workflow_review_feedback(mr_id): str
        +workflow_monitor_pipelines(): str
        +workflow_handle_review(): str
        +workflow_daily_standup(): str
    }
```

## Workflow Stages

```mermaid
flowchart LR
    subgraph Start[Start Work]
        START_WORK[workflow_start_work]
        CREATE_BRANCH[workflow_create_branch]
    end

    subgraph Develop[Development]
        LOCAL_CHECKS[workflow_run_local_checks]
        PREPARE_MR[workflow_prepare_mr]
    end

    subgraph Review[Review & Deploy]
        CHECK_READY[workflow_check_deploy_readiness]
        MONITOR[workflow_monitor_pipelines]
        HANDLE_REVIEW[workflow_handle_review]
    end

    subgraph Daily[Daily]
        STANDUP[workflow_daily_standup]
    end

    Start --> Develop --> Review
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| tools_basic.py | `tool_modules/aa_dev_workflow/src/` | All workflow coordination tools |

## Tool Summary

| Tool | Description |
|------|-------------|
| `workflow_start_work` | Get context to start working on a Jira issue |
| `workflow_create_branch` | Create a feature branch from a Jira issue |
| `workflow_prepare_mr` | Prepare a Merge Request with proper format |
| `workflow_run_local_checks` | Run local linting and validation |
| `workflow_check_deploy_readiness` | Check if MR is ready to deploy |
| `workflow_review_feedback` | Get guidance on addressing review feedback |
| `workflow_monitor_pipelines` | Monitor GitLab + Konflux pipelines |
| `workflow_handle_review` | Prepare to handle MR review feedback |
| `workflow_daily_standup` | Generate a summary of recent work |

## Workflow Integration

```mermaid
graph TB
    subgraph Jira[Jira Integration]
        ISSUE[Get Issue Details]
        UPDATE[Update Status]
    end

    subgraph Git[Git Integration]
        BRANCH[Create Branch]
        COMMIT[Commit Changes]
    end

    subgraph GitLab[GitLab Integration]
        MR[Create MR]
        PIPELINE[Check Pipeline]
    end

    subgraph Konflux[Konflux Integration]
        TEKTON[Monitor Tekton]
        DEPLOY[Check Deployment]
    end

    ISSUE --> BRANCH
    BRANCH --> COMMIT
    COMMIT --> MR
    MR --> PIPELINE
    PIPELINE --> TEKTON
    TEKTON --> DEPLOY
    DEPLOY --> UPDATE
```

## Usage Examples

```python
# Start work on a Jira issue
result = await workflow_start_work("AAP-12345")

# Create a feature branch
result = await workflow_create_branch("AAP-12345")

# Run local checks before committing
result = await workflow_run_local_checks()

# Check if MR is ready to deploy
result = await workflow_check_deploy_readiness()
```

## Related Diagrams

- [Git Tools](./git-tools.md)
- [GitLab Tools](./gitlab-tools.md)
- [Jira Tools](./jira-tools.md)
- [Common Skills](../04-skills/common-skills.md)
