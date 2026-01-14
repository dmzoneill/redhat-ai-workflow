# /investigate-alert

> Quick triage of a firing Prometheus alert.

## Overview

Quick triage of a firing Prometheus alert.

**Underlying Skill:** `investigate_alert`

This command is a wrapper that calls the `investigate_alert` skill. For detailed process information, see [skills/investigate_alert.md](../skills/investigate_alert.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `environment` | No | - |

## Usage

### Examples

```bash
skill_run("investigate_alert", '{"environment": "stage"}')
```

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

## Process Flow

This command invokes the `investigate_alert` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /investigate-alert]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call investigate_alert skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [investigate_alert skill documentation](../skills/investigate_alert.md).

## Details

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


## Related Commands

_(To be determined based on command relationships)_
