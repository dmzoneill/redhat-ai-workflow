---
name: check-secrets
description: "Verify Kubernetes secrets and configmaps."
arguments:
  - name: namespace
    required: true
---
# Check Secrets

Verify Kubernetes secrets and configmaps.

## Instructions

```
skill_run("check_secrets", '{"namespace": "$NAMESPACE"}')
```

## What It Does

1. Lists secrets in namespace
2. Lists configmaps
3. Checks deployment secret references
4. Identifies missing or mismatched secrets

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `namespace` | Kubernetes namespace | Required |
| `deployment` | Specific deployment to check | All |
| `environment` | Cluster (stage/prod) | `stage` |

## Examples

```bash
# Check stage secrets
skill_run("check_secrets", '{"namespace": "tower-analytics-stage"}')

# Check specific deployment
skill_run("check_secrets", '{"namespace": "tower-analytics-stage", "deployment": "tower-analytics-api"}')
```

## Note

This lists secret **names**, not values (for security).
Use `kubectl_get_secret_value` directly to view a specific secret.




