# /debug-prod

> Deep investigation of production issues.

## Overview

Deep investigation of production issues.

**Underlying Skill:** `debug_prod`

This command is a wrapper that calls the `debug_prod` skill. For detailed process information, see [skills/debug_prod.md](../skills/debug_prod.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `pod_filter` | No | - |

## Usage

### Examples

```bash
skill_run("debug_prod")
```

```bash
# General production health check
skill_run("debug_prod")

# Investigate specific pod type
skill_run("debug_prod", '{"pod_filter": "processor"}')

# Look at longer time range
skill_run("debug_prod", '{"time_range": "6h"}')

# Investigate specific alert
skill_run("debug_prod", '{"alert_name": "HighErrorRate"}')

# Check stage instead
skill_run("debug_prod", '{"namespace": "tower-analytics-stage"}')
```

## Process Flow

This command invokes the `debug_prod` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /debug-prod]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call debug_prod skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [debug_prod skill documentation](../skills/debug_prod.md).

## Details

## Instructions

```
skill_run("debug_prod")
```

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `namespace` | Kubernetes namespace | `tower-analytics-prod` |
| `alert_name` | Specific alert to investigate | All |
| `pod_filter` | Filter pods by name pattern | All pods |
| `time_range` | Log time range | `1h` |

## Examples

```bash
# General production health check
skill_run("debug_prod")

# Investigate specific pod type
skill_run("debug_prod", '{"pod_filter": "processor"}')

# Look at longer time range
skill_run("debug_prod", '{"time_range": "6h"}')

# Investigate specific alert
skill_run("debug_prod", '{"alert_name": "HighErrorRate"}')

# Check stage instead
skill_run("debug_prod", '{"namespace": "tower-analytics-stage"}')
```

## What It Gathers

| Data | Source |
|------|--------|
| 🔴 Pod Status | Kubernetes |
| 📜 Recent Logs | Kibana |
| 📊 Metrics | Prometheus |
| 🚨 Alerts | Alertmanager |
| 🚀 Recent Deployments | GitLab/Konflux |
| 📅 Events | Kubernetes |

## Output

- Current state summary
- Error patterns identified
- Likely root causes
- Suggested actions
- Links to dashboards

## When to Use

- Production incident investigation
- After `/investigate-alert` needs more detail
- Proactive health checks
- Post-incident analysis

## vs /investigate-alert

| `/investigate-alert` | `/debug-prod` |
|---------------------|---------------|
| Quick triage | Deep investigation |
| ~30 seconds | ~2-5 minutes |
| Firing alerts focus | Full system view |
| Surface level | Logs, metrics, events |


## Related Commands

_(To be determined based on command relationships)_
