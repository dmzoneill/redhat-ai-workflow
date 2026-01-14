# /notify-team

> Send a message to a Slack channel.

## Overview

Send a message to a Slack channel.

**Underlying Skill:** `notify_team`

This command is a wrapper that calls the `notify_team` skill. For detailed process information, see [skills/notify_team.md](../skills/notify_team.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `channel` | No | - |
| `message` | No | - |

## Usage

### Examples

```bash
skill_run("notify_team", '{"channel": "$CHANNEL", "message": "$MESSAGE"}')
```

```bash
# Simple notification
skill_run("notify_team", '{"channel": "analytics-dev", "message": "Deploying v1.2.3 to stage"}')

# With mentions
skill_run("notify_team", '{"channel": "analytics-dev", "message": "Need review on AAP-61214", "mentions": ["daoneill"]}')
```

## Process Flow

This command invokes the `notify_team` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /notify-team]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call notify_team skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [notify_team skill documentation](../skills/notify_team.md).

## Details

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


## Related Commands

_(To be determined based on command relationships)_
