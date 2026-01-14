# 👨‍💻 Developer Persona

> Daily coding, PRs, and code review

## Overview

The Developer persona is your primary tool configuration for day-to-day development work. It provides tools for Git operations, GitLab MRs, Jira issues, and Google Calendar integration.

## Quick Load

```text
Load the developer agent
```

## Tools Loaded

| Module | Tools | Description |
|--------|-------|-------------|
| [git](../tool_modules/git.md) | 15 | Git operations |
| [gitlab](../tool_modules/gitlab.md) | 35 | MRs, pipelines, code review |
| [jira](../tool_modules/jira.md) | 24 | Issue tracking |
| [google_calendar](../tool_modules/google_calendar.md) | 6 | Calendar & meetings |

**Total:** ~78 tools (4 modules)

## Skills Available

### Daily Rituals

| Skill | Description |
|-------|-------------|
| [☕ coffee](../skills/coffee.md) | Morning briefing - email, PRs, Jira, calendar |
| [🍺 beer](../skills/beer.md) | End-of-day wrap-up and standup prep |
| [📊 standup_summary](../skills/standup_summary.md) | Generate standup notes |

### Development Workflow

| Skill | Description |
|-------|-------------|
| [⚡ start_work](../skills/start_work.md) | Begin working on a Jira issue |
| [🚀 create_mr](../skills/create_mr.md) | Create MR with validation |
| [✅ close_issue](../skills/close_issue.md) | Close issue with summary |
| [🔁 sync_branch](../skills/sync_branch.md) | Quick sync with main |

### Code Review

| Skill | Description |
|-------|-------------|
| [👀 review_pr](../skills/review_pr.md) | Review a specific MR |
| [📋 review_all_prs](../skills/review_all_prs.md) | Batch review open PRs |
| [📝 check_my_prs](../skills/check_my_prs.md) | Check your PRs for feedback |
| [💬 check_mr_feedback](../skills/check_mr_feedback.md) | Find comments needing response |
| [🔄 rebase_pr](../skills/rebase_pr.md) | Rebase with conflict resolution |

### Jira Management

| Skill | Description |
|-------|-------------|
| [📋 jira_hygiene](../skills/jira_hygiene.md) | Validate issue quality |
| [📋 create_jira_issue](../skills/create_jira_issue.md) | Create issue with Markdown |

## Use Cases

### Starting Your Day

```yaml
You: /coffee

Claude: ☕ Good Morning, Dave!

        📅 3 meetings today
        📧 5 unread emails
        🔀 2 open PRs (!456, !458)
        💬 1 PR needs response
        🚨 No alerts
```

### Working on an Issue

```yaml
You: Start work on AAP-12345

Claude: [Runs start_work skill]
        ✅ Created branch: aap-12345-implement-api
        ✅ Jira status: In Progress
```

### Creating a Merge Request

```yaml
You: Create MR for my changes

Claude: [Runs create_mr skill]
        ✅ Linting passed
        ✅ No conflicts
        ✅ Created MR !460
```

## When to Switch Agents

Switch to **DevOps** agent when you need to:
- Deploy to ephemeral environment
- Debug Kubernetes pods
- Check Quay images

Switch to **Incident** agent when you need to:
- Investigate production alerts
- Search logs in Kibana
- Check Prometheus metrics

## Related

- [🔧 DevOps Persona](./devops.md)
- [🚨 Incident Persona](./incident.md)
