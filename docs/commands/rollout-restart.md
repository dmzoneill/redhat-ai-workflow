# /rollout-restart

> Restart a deployment and monitor the rollout.

## Overview

Restart a deployment and monitor the rollout.

**Underlying Skill:** `rollout_restart`

This command is a wrapper that calls the `rollout_restart` skill. For detailed process information, see [skills/rollout_restart.md](../skills/rollout_restart.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `deployment` | No | - |
| `namespace` | No | - |

## Usage

### Examples

```bash
skill_run("rollout_restart", '{"deployment": "$DEPLOYMENT", "namespace": "$NAMESPACE"}')
```

```bash
# Restart in stage
skill_run("rollout_restart", '{"deployment": "tower-analytics-api", "namespace": "tower-analytics-stage"}')

# Restart in production
skill_run("rollout_restart", '{"deployment": "tower-analytics-api", "namespace": "tower-analytics-prod", "environment": "prod"}')
```

## Process Flow

This command invokes the `rollout_restart` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /rollout-restart]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call rollout_restart skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [rollout_restart skill documentation](../skills/rollout_restart.md).

## Details

## Instructions

```
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


## Related Commands

_(To be determined based on command relationships)_
