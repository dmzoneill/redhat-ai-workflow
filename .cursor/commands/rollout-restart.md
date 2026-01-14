# Rollout Restart

Restart a deployment and monitor the rollout.

## Instructions

```text
skill_run("rollout_restart", '{"deployment": "$DEPLOYMENT", "namespace": "$NAMESPACE"}')
```

## What It Does

1. Describes current deployment state
2. Triggers rollout restart
3. Monitors rollout progress
4. Verifies new pods are healthy

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `deployment` | Deployment name | Required |
| `namespace` | Kubernetes namespace | Required |
| `environment` | Cluster (stage/prod/ephemeral) | `stage` |

## Examples

```bash
# Restart in stage
skill_run("rollout_restart", '{"deployment": "tower-analytics-api", "namespace": "tower-analytics-stage"}')

# Restart in production
skill_run("rollout_restart", '{"deployment": "tower-analytics-api", "namespace": "tower-analytics-prod", "environment": "prod"}')
```

## ⚠️ Caution

Use carefully in production. Consider silencing alerts first with `/silence-alert`.
