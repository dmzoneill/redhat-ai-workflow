# 🕐 Cron Scheduler

Schedule skills to run automatically at specific times or based on events.

## Overview

The cron scheduler allows you to automate recurring tasks like:
- Morning briefings (`/coffee`) at 8:30 AM
- End of day wrap-ups (`/beer`) at 5:30 PM
- Stale PR reminders every few hours
- Custom workflows on any schedule

## Quick Start

### Enable the Scheduler

The scheduler is disabled by default. Enable it in `config.json`:

```json
{
  "schedules": {
    "enabled": true,
    "timezone": "Europe/Dublin"
  }
}
```

### Add a Scheduled Job

Use the `cron_add` tool:

```text
cron_add("morning_coffee", "coffee", cron="30 8 * * 1-5", notify="slack,desktop")
```

Or edit `config.json` directly:

```json
{
  "schedules": {
    "jobs": [
      {
        "name": "morning_coffee",
        "skill": "coffee",
        "cron": "30 8 * * 1-5",
        "notify": ["slack", "desktop"],
        "enabled": true
      }
    ]
  }
}
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `cron_list` | List all scheduled jobs with next run time |
| `cron_add` | Add a new scheduled job |
| `cron_remove` | Remove a scheduled job |
| `cron_enable` | Enable or disable a job |
| `cron_run_now` | Manually trigger a job immediately |
| `cron_status` | Show scheduler status and recent executions |
| `cron_notifications` | View recent notification history |

## Cron Syntax

Standard 5-field cron format:

```
┌───────────── minute (0-59)
│ ┌───────────── hour (0-23)
│ │ ┌───────────── day of month (1-31)
│ │ │ ┌───────────── month (1-12)
│ │ │ │ ┌───────────── day of week (0-6, Sun=0)
│ │ │ │ │
* * * * *
```

### Examples

| Expression | Description |
|------------|-------------|
| `30 8 * * 1-5` | 8:30 AM on weekdays |
| `0 17 * * 1-5` | 5:00 PM on weekdays |
| `0 9 * * 1` | 9:00 AM every Monday |
| `*/30 * * * *` | Every 30 minutes |
| `0 */4 * * *` | Every 4 hours |
| `0 0 1 * *` | Midnight on the 1st of each month |

## Job Types

### Cron Jobs (Time-Based)

Run at specific times:

```json
{
  "name": "evening_beer",
  "skill": "beer",
  "cron": "30 17 * * 1-5",
  "inputs": {
    "generate_standup": true
  },
  "notify": ["slack"],
  "enabled": true
}
```

### Poll Jobs (Event-Based)

Check conditions periodically and trigger when met:

```json
{
  "name": "stale_pr_reminder",
  "trigger": "poll",
  "poll_interval": "4h",
  "condition": "gitlab_stale_prs",
  "skill": "pr_reminder",
  "notify": ["slack"],
  "enabled": true
}
```

## Poll Sources

Define conditions to check in `poll_sources`:

```json
{
  "poll_sources": {
    "gitlab_stale_prs": {
      "type": "gitlab_mr_list",
      "args": {
        "project": "automation-analytics/automation-analytics-backend",
        "state": "opened",
        "author": "@me"
      },
      "condition": "age > 3d"
    },
    "jira_in_progress": {
      "type": "jira_search",
      "args": {
        "jql": "assignee = currentUser() AND status = 'In Progress'"
      },
      "condition": "count > 0"
    }
  }
}
```

### Condition Syntax

| Condition | Description |
|-----------|-------------|
| `any` | Trigger if any results |
| `count > N` | Trigger if more than N results |
| `count = N` | Trigger if exactly N results |
| `age > Xd` | Trigger for items older than X days |
| `age > Xh` | Trigger for items older than X hours |

### Duration Format

| Format | Description |
|--------|-------------|
| `30m` | 30 minutes |
| `4h` | 4 hours |
| `1d` | 1 day |
| `1w` | 1 week |

## Notifications

Configure how you're notified when jobs complete:

| Channel | Description |
|---------|-------------|
| `slack` | Send to Slack (self DM or configured channel) |
| `desktop` | Desktop notification (notify-send on Linux) |
| `memory` | Log to memory (always enabled) |

### Example

```json
{
  "notify": ["slack", "desktop", "memory"]
}
```

## Configuration Reference

Full `schedules` section in `config.json`:

```json
{
  "schedules": {
    "enabled": true,
    "timezone": "Europe/Dublin",
    "jobs": [
      {
        "name": "morning_coffee",
        "description": "Morning briefing",
        "skill": "coffee",
        "cron": "30 8 * * 1-5",
        "inputs": {},
        "notify": ["slack", "desktop"],
        "enabled": true
      },
      {
        "name": "evening_beer",
        "description": "End of day wrap-up",
        "skill": "beer",
        "cron": "30 17 * * 1-5",
        "inputs": {
          "generate_standup": true,
          "cleanup_prompts": true
        },
        "notify": ["slack"],
        "enabled": true
      },
      {
        "name": "stale_pr_reminder",
        "description": "Check for stale PRs",
        "trigger": "poll",
        "poll_interval": "4h",
        "condition": "gitlab_stale_prs",
        "skill": "pr_reminder",
        "notify": ["slack"],
        "enabled": true
      }
    ],
    "poll_sources": {
      "gitlab_stale_prs": {
        "type": "gitlab_mr_list",
        "args": {
          "project": "automation-analytics/automation-analytics-backend",
          "state": "opened",
          "author": "@me"
        },
        "condition": "age > 3d"
      }
    }
  }
}
```

## Server Options

### Disable Scheduler

Run the MCP server without the scheduler:

```bash
python -m server --agent developer --no-scheduler
```

### Check Status

```text
cron_status()
```

Output:
```
## 🕐 Scheduler Status

**Enabled in config:** ✅ Yes
**Timezone:** Europe/Dublin
**Total jobs configured:** 3
**Scheduler running:** ✅ Yes
**Cron jobs active:** 2
**Poll jobs active:** 1

### 📜 Recent Executions

- ✅ `2025-01-15 08:30` **morning_coffee** (1234ms)
- ✅ `2025-01-14 17:30` **evening_beer** (2345ms)
```

## Troubleshooting

### Scheduler Not Starting

1. Check if enabled in config:
   ```json
   "schedules": { "enabled": true }
   ```

2. Check dependencies are installed:
   ```bash
   uv add apscheduler croniter
   ```

3. Check server logs for errors

### Jobs Not Running

1. Verify job is enabled:
   ```json
   "enabled": true
   ```

2. Check cron expression is valid:
   ```text
   cron_list()
   ```

3. Manually test the job:
   ```text
   cron_run_now("morning_coffee")
   ```

### Notifications Not Working

1. Check Slack is configured in `config.json`
2. Verify notification channels are valid
3. Check `cron_notifications()` for history

## Best Practices

1. **Start with `enabled: false`** - Test jobs manually before enabling
2. **Use descriptive names** - Makes logs easier to read
3. **Set appropriate intervals** - Don't poll too frequently
4. **Use multiple notification channels** - Slack + desktop for important jobs
5. **Review execution history** - Use `cron_status()` regularly

## Pair with /coffee and /beer

The scheduler works great with the built-in briefing skills:

| Job | Skill | Schedule | Purpose |
|-----|-------|----------|---------|
| Morning briefing | `coffee` | `30 8 * * 1-5` | Start your day |
| Evening wrap-up | `beer` | `30 17 * * 1-5` | End your day |

```json
{
  "jobs": [
    {
      "name": "morning_coffee",
      "skill": "coffee",
      "cron": "30 8 * * 1-5",
      "notify": ["slack", "desktop"]
    },
    {
      "name": "evening_beer",
      "skill": "beer",
      "cron": "30 17 * * 1-5",
      "notify": ["slack"]
    }
  ]
}
```
