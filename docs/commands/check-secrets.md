# /check-secrets

> Verify Kubernetes secrets and configmaps.

## Overview

Verify Kubernetes secrets and configmaps.

**Underlying Skill:** `check_secrets`

This command is a wrapper that calls the `check_secrets` skill. For detailed process information, see [skills/check_secrets.md](../skills/check_secrets.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `namespace` | No | - |

## Usage

### Examples

```bash
skill_run("check_secrets", '{"namespace": "$NAMESPACE"}')
```

```bash
# Check stage secrets
skill_run("check_secrets", '{"namespace": "tower-analytics-stage"}')

# Check specific deployment
skill_run("check_secrets", '{"namespace": "tower-analytics-stage", "deployment": "tower-analytics-api"}')
```

## Process Flow

This command invokes the `check_secrets` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /check-secrets]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call check_secrets skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [check_secrets skill documentation](../skills/check_secrets.md).

## Details

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


## Related Commands

_(To be determined based on command relationships)_
