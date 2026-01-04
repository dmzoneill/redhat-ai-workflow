# Scale Deployment

Scale a deployment up or down.

## Instructions

```
skill_run("scale_deployment", '{"deployment": "$DEPLOYMENT", "namespace": "$NAMESPACE", "replicas": $COUNT}')
```

## What It Does

1. Shows current deployment state
2. Scales to target replicas
3. Monitors rollout
4. Verifies pod health

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `deployment` | Deployment name | Required |
| `namespace` | Kubernetes namespace | Required |
| `replicas` | Target replica count | Required |
| `environment` | Cluster (stage/prod) | `stage` |

## Examples

```bash
# Scale up
skill_run("scale_deployment", '{"deployment": "tower-analytics-api", "namespace": "tower-analytics-stage", "replicas": 3}')

# Scale down
skill_run("scale_deployment", '{"deployment": "tower-analytics-worker", "namespace": "tower-analytics-stage", "replicas": 1}')
```

## Caution

In production, scaling changes may be reverted by GitOps.
Consider updating app-interface for permanent changes.







