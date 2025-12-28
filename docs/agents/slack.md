# 💬 Slack Agent

> Autonomous Slack responder and team assistant

## Overview

The Slack agent is designed for autonomous Slack integration. It monitors channels, detects intent, and responds to requests using available skills and tools.

## Quick Load

```
Load the slack agent
```

## Tools Loaded

| Module | Tools | Description |
|--------|-------|-------------|
| [slack](../mcp-servers/slack.md) | 13 | Slack messaging |
| [jira](../mcp-servers/jira.md) | 24 | Issue tracking |
| [gitlab](../mcp-servers/gitlab.md) | 35 | MRs and pipelines |

**Total:** ~74 tools

## Skills Available

| Skill | Description |
|-------|-------------|
| [⚡ start_work](../skills/start_work.md) | Start working on issue |
| [🚀 create_mr](../skills/create_mr.md) | Create merge request |
| [👀 review_pr](../skills/review_pr.md) | Review a PR |
| [📝 check_my_prs](../skills/check_my_prs.md) | Check your PRs |
| [✅ close_issue](../skills/close_issue.md) | Close an issue |
| [📊 standup_summary](../skills/standup_summary.md) | Generate standup |
| [📋 jira_hygiene](../skills/jira_hygiene.md) | Check issue quality |
| [🔁 sync_branch](../skills/sync_branch.md) | Sync branch |
| [🔄 rebase_pr](../skills/rebase_pr.md) | Rebase a PR |

## Communication Style

The Slack agent uses concise, Slack-appropriate formatting:

**Good Response:**
```
📋 *AAP-12345*: Add REST endpoint for user preferences
Status: In Progress | Assignee: @david
[View in Jira](link)
```

**Not Like This:**
```
I found the Jira issue you requested. Here are the details...
The issue titled "Add REST endpoint for user preferences"...
(too verbose for Slack)
```

## Intent Detection

| Trigger | Intent | Action |
|---------|--------|--------|
| "AAP-12345" | jira_query | Show issue details |
| "!123", "MR 123" | pr_status | Show MR status |
| "my PRs", "my MRs" | check_my_prs | Run skill |
| "prod down", "alert" | prod_debug | Offer debug_prod |
| "start AAP-12345" | start_work | Offer start_work |
| "standup", "status" | standup | Run standup_summary |

## Example Interactions

### Jira Query

```
User: What's the status of AAP-12345?

Bot: 📋 *AAP-12345*: Implement caching layer
     Status: In Progress 🔄
     Assignee: @jsmith
     [View in Jira](https://issues.redhat.com/browse/AAP-12345)
```

### MR Status

```
User: Check MR 456

Bot: 🦊 *!456*: AAP-12345 - feat: Add caching
     Author: jsmith | Target: main
     Pipeline: Passed ✅
     [View MR](https://gitlab.../456)
```

### Help

```
User: @bot help

Bot: 👋 Here's what I can help with:

     📋 *Jira* - "AAP-12345" or "what's AAP-12345"
     🦊 *MRs* - "MR 123" or "check my PRs"
     🚀 *Actions* - "start AAP-12345" or "create MR"
     📊 *Status* - "standup" or "my work"
```

## User Classification

The agent adjusts its response style based on who's asking:

| Category | Style | Auto-respond? |
|----------|-------|---------------|
| **Teammates** | Casual, emojis ✅ | Yes |
| **Managers** | Formal, no emojis | Review first |
| **Unknown** | Professional | Yes |

## Running the Daemon

```bash
# Foreground
make slack-daemon

# With Claude integration
make slack-daemon-llm

# Background
make slack-daemon-bg
```

## Safety Guidelines

- Never execute destructive operations without confirmation
- Production actions require explicit user approval
- Always show what you're about to do before doing it
- Log all actions for audit trail

## Related

- [investigate_slack_alert Skill](../skills/investigate_slack_alert.md)
- [slack_daemon_control Skill](../skills/slack_daemon_control.md)
