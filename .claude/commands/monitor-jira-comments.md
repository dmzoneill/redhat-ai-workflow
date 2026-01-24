---
name: monitor-jira-comments
description: "Daily monitoring of Jira comments on sprint issues - detects and responds to questions."
arguments:
  - name: jira_project
---
# Monitor Jira Comments

Daily monitoring of Jira comments on sprint issues - detects and responds to questions.

## Instructions

Check for new comments on your sprint issues:

```text
skill_run("monitor_jira_comments", '{}')
```

This will:
1. Find your active sprint issues
2. Check for recent comments (last 24 hours)
3. Detect questions that need responses
4. Respond naturally (no bot language)
5. Notify you via Slack

## Example

```bash
# Check comments on AAP project (default)
skill_run("monitor_jira_comments", '{}')

# Check specific project
skill_run("monitor_jira_comments", '{"jira_project": "AAP"}')

# Dry run - see what would happen without posting
skill_run("monitor_jira_comments", '{"dry_run": true}')

# Check last 48 hours
skill_run("monitor_jira_comments", '{"hours_lookback": 48}')

# Custom Slack channel for notifications
skill_run("monitor_jira_comments", '{"slack_channel": "my-notifications"}')
```

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `jira_project` | AAP | Jira project key |
| `hours_lookback` | 24 | Hours back to check for comments |
| `notify_user` | true | Send Slack notifications |
| `slack_channel` | "" | Custom Slack channel |
| `dry_run` | false | Preview without posting responses |

## Scheduled Execution

This skill is scheduled to run automatically at 9 AM on weekdays via cron.

## Output

- **issues_checked**: Number of issues checked
- **questions_found**: Number of questions detected
- **responses_sent**: Number of responses posted
- **notifications_sent**: Number of Slack notifications
