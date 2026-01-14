# /scale-deployment

> Scale a deployment up or down.

## Overview

Scale a deployment up or down.

**Underlying Skill:** `scale_deployment`

This command is a wrapper that calls the `scale_deployment` skill. For detailed process information, see [skills/scale_deployment.md](../skills/scale_deployment.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `deployment` | No | - |
| `namespace` | No | - |
| `replicas` | No | - |

## Usage

### Examples

```bash
skill_run("scale_deployment", '{"deployment": "$DEPLOYMENT", "namespace": "$NAMESPACE", "replicas": $COUNT}')
```

```bash
# Scale up
skill_run("scale_deployment", '{"deployment": "tower-analytics-api", "namespace": "tower-analytics-stage", "replicas": 3}')

# Scale down
skill_run("scale_deployment", '{"deployment": "tower-analytics-worker", "namespace": "tower-analytics-stage", "replicas": 1}')
```

## Process Flow

This command invokes the `scale_deployment` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /scale-deployment]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call scale_deployment skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [scale_deployment skill documentation](../skills/scale_deployment.md).

## Details

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


## Related Commands

_(To be determined based on command relationships)_
