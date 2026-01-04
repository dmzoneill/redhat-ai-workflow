# Notify Team

Send a message to a Slack channel.

## Instructions

```
skill_run("notify_team", '{"channel": "$CHANNEL", "message": "$MESSAGE"}')
```

## What It Does

1. Finds the Slack channel
2. Posts the message
3. Optionally mentions users

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `channel` | Channel name (without #) | Required |
| `message` | Message to send | Required |
| `mentions` | List of usernames to @mention | Optional |

## Examples

```bash
# Simple notification
skill_run("notify_team", '{"channel": "analytics-dev", "message": "Deploying v1.2.3 to stage"}')

# With mentions
skill_run("notify_team", '{"channel": "analytics-dev", "message": "Need review on AAP-61214", "mentions": ["daoneill"]}')
```

## Common Channels

- `analytics-dev` - Development team
- `analytics-alerts` - Alert notifications
- `analytics-releases` - Release announcements
