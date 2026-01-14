# Environment Overview

Full health check of a Kubernetes environment.

## Instructions

```text
skill_run("environment_overview", '{"environment": "stage"}')
```

## What It Does

1. Gets cluster-wide health summary
2. Checks namespace resource status
3. Lists services and ingresses
4. Shows pod health across deployments

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `environment` | Target environment | `stage` |
| `namespace` | Specific namespace | Auto-detect |

## Examples

```bash
# Stage environment overview
skill_run("environment_overview", '{"environment": "stage"}')

# Production overview
skill_run("environment_overview", '{"environment": "prod"}')

# Specific namespace
skill_run("environment_overview", '{"environment": "stage", "namespace": "tower-analytics-stage"}')
```
