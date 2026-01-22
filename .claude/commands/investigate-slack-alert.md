---
name: investigate-slack-alert
description: "Investigate an alert received via Slack."
arguments:
  - name: alert_text
    required: true
---
# Investigate Slack Alert

Investigate an alert received via Slack.

## Instructions

```text
skill_run("investigate_slack_alert", '{"alert_text": "$ALERT_TEXT"}')
```

## What It Does

1. Parses the Slack alert message
2. Identifies the alert type and severity
3. Queries relevant metrics and logs
4. Checks for known patterns in memory
5. Provides investigation steps

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `alert_text` | The alert message from Slack | Yes |
| `environment` | Environment to check: 'stage', 'prod' | No |

## Examples

```bash
# Investigate an alert
skill_run("investigate_slack_alert", '{"alert_text": "High CPU usage on billing-worker"}')

# With specific environment
skill_run("investigate_slack_alert", '{"alert_text": "Pod restart loop detected", "environment": "prod"}')
```

## Related Commands

- `/investigate-alert` - For Prometheus/Alertmanager alerts
- `/debug-prod` - For production debugging
