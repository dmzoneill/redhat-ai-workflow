# 🔍 Debug Production

Deep investigation of production issues.

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

