# Dev Workflow Orchestrator

High-level entry point for development workflows.

## Instructions

```text
skill_run("dev_workflow_orchestrator", '{"action": "$ACTION", "issue_key": "", "repo": ""}')
```

## What It Does

High-level entry point for development workflows.

Orchestrates common developer tasks:
- Start work on an issue (branch, Jira, context)
- Check deploy readiness (lint, tests, CI)
- Prepare merge request
- Monitor CI/CD pipelines
- Generate standup summary
- Handle code review feedback

Uses: workflow_check_deploy_readiness, workflow_run_local_checks,
workflow_daily_standup, workflow_start_work, workflow_create_branch,
workflow_prepare_mr, workflow_monitor_pipelines,
workflow_handle_review, workflow_review_feedback

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `action` | Workflow action to perform | Yes |
| `issue_key` | Jira issue key (required for start, check, prepare_mr) | No |
| `repo` | Repository path | No |
