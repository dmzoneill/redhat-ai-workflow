# /silence-alert

> Create or manage Alertmanager silences.

## Overview

Create or manage Alertmanager silences.

**Underlying Skill:** `silence_alert`

This command is a wrapper that calls the `silence_alert` skill. For detailed process information, see [skills/silence_alert.md](../skills/silence_alert.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `alert_name` | No | - |
| `duration` | No | - |

## Usage

### Examples

```bash
skill_run("silence_alert", '{"alert_name": "$ALERT", "duration": "$DURATION"}')
```

```bash
# Silence for 1 hour
skill_run("silence_alert", '{"alert_name": "HighErrorRate", "duration": "1h"}')

# Silence with comment
skill_run("silence_alert", '{"alert_name": "HighMemory", "duration": "2h", "comment": "Investigating AAP-61214"}')

# Delete a silence
skill_run("silence_alert", '{"delete_id": "abc-123-silence-id"}')
```

## Process Flow

This command invokes the `silence_alert` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /silence-alert]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call silence_alert skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [silence_alert skill documentation](../skills/silence_alert.md).

## Details

## Instructions

```
skill_run("silence_alert", '{"alert_name": "$ALERT", "duration": "$DURATION"}')
```

## What It Does

1. Lists current alerts and silences
2. Creates silence for specified alert
3. Can also delete existing silences

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `alert_name` | Alert name pattern to silence | Required |
| `duration` | Silence duration (e.g., "2h", "30m") | `1h` |
| `environment` | Target environment | `stage` |
| `comment` | Reason for silence | Optional |
| `delete_id` | Silence ID to delete | Optional |

## Examples

```bash
# Silence for 1 hour
skill_run("silence_alert", '{"alert_name": "HighErrorRate", "duration": "1h"}')

# Silence with comment
skill_run("silence_alert", '{"alert_name": "HighMemory", "duration": "2h", "comment": "Investigating AAP-61214"}')

# Delete a silence
skill_run("silence_alert", '{"delete_id": "abc-123-silence-id"}')
```

## When to Use

- During planned maintenance
- While investigating known issues
- To reduce noise during deployments


## Related Commands

_(To be determined based on command relationships)_
