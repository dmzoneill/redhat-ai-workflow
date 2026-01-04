# Silence Alert

Create or manage Alertmanager silences.

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







