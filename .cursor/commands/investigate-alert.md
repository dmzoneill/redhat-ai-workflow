# 🚨 Investigate Alert

Quick triage of a firing Prometheus alert.

## Instructions

```
skill_run("investigate_alert", '{"environment": "stage"}')
```

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `environment` | Target environment (`stage` or `prod`) | `stage` |
| `namespace` | Specific namespace to check | Auto-detected |
| `alert_name` | Specific alert to investigate | All firing |
| `auto_escalate` | Auto-escalate to debug_prod if serious | `false` |

## Examples

```bash
# Check stage alerts
skill_run("investigate_alert", '{"environment": "stage"}')

# Check production alerts
skill_run("investigate_alert", '{"environment": "prod"}')

# Investigate specific alert
skill_run("investigate_alert", '{"environment": "prod", "alert_name": "HighErrorRate"}')

# Auto-escalate serious alerts
skill_run("investigate_alert", '{"environment": "stage", "auto_escalate": true}')
```

## What It Does

1. Gets current firing alerts from Prometheus/Alertmanager
2. Quick health check (pods, deployments)
3. Checks recent Kubernetes events
4. Looks for known error patterns
5. Escalates to `debug_prod` if serious

## When to Use

- Slack alert notification
- Quick triage before diving deep
- Checking if an alert is real or flapping

For deep investigation, use `/debug-prod` directly.

