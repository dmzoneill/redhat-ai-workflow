# Universal Persona

Combined developer and devops capabilities for full workflow support.

## Overview

| Metric | Value |
|--------|-------|
| **Approximate Tools** | ~92 |
| **Purpose** | All-in-one toolset |
| **Use Case** | Full workflow without persona switching |

## Tool Modules

| Module | Tools | Description |
|--------|-------|-------------|
| workflow | 18 | Core: memory, persona, session, skill, infra, meta |
| git_basic | 27 | Essential git operations |
| gitlab_basic | 16 | MRs, CI/CD basics |
| jira_basic | 17 | Issue viewing, search, status updates |
| k8s_basic | 22 | Essential k8s (pods, logs, deployments) |

## Capabilities

This persona combines developer and devops capabilities:

### Development

- Git operations (status, branch, commit, push)
- GitLab MRs and CI/CD
- Jira issue management
- Code review workflows

### DevOps

- Kubernetes operations
- Ephemeral deployments (via skills)
- Alert investigation
- Production debugging

## Available Skills

### Daily Workflow

- `coffee` - Morning briefing
- `beer` - End of day wrap-up
- `standup_summary` - Generate standup summary
- `weekly_summary` - Weekly work summary

### Development

- `start_work` - Start working on a Jira issue
- `create_mr` - Create MR
- `mark_mr_ready` - Mark draft MR ready
- `review_pr` - PR review workflow
- `check_my_prs` - Check your PRs for feedback
- `sync_branch` - Quick sync with main
- `cleanup_branches` - Delete merged branches

### DevOps

- `test_mr_ephemeral` - Deploy MR to ephemeral
- `deploy_to_ephemeral` - Deploy apps to ephemeral
- `extend_ephemeral` - Extend namespace reservation

### Incident

- `investigate_alert` - Investigate Prometheus alerts
- `investigate_slack_alert` - Investigate Slack alerts
- `debug_prod` - Debug production issues

### Communication

- `notify_team` - Send Slack notifications
- `schedule_meeting` - Schedule meetings

## Usage

```python
persona_load("universal")
```

## When to Use

- You need both development and devops capabilities
- You don't want to switch personas frequently
- You're doing end-to-end feature work (code to deploy)

## Persona Switching

Even with universal tools, you can adopt specialized personas:

```python
# Tools stay the same, but adopt devops expertise
persona_load("devops")
```

This changes Claude's focus/expertise while keeping access to all universal tools.
