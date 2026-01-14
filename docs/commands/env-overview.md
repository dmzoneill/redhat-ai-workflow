# /env-overview

> Full health check of a Kubernetes environment.

## Overview

Full health check of a Kubernetes environment.

**Underlying Skill:** `environment_overview`

This command is a wrapper that calls the `environment_overview` skill. For detailed process information, see [skills/environment_overview.md](../skills/environment_overview.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `environment` | No | - |

## Usage

### Examples

```bash
skill_run("environment_overview", '{"environment": "stage"}')
```

```bash
# Stage environment overview
skill_run("environment_overview", '{"environment": "stage"}')

# Production overview
skill_run("environment_overview", '{"environment": "prod"}')

# Specific namespace
skill_run("environment_overview", '{"environment": "stage", "namespace": "tower-analytics-stage"}')
```

## Process Flow

This command invokes the `environment_overview` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /env-overview]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call environment_overview skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [environment_overview skill documentation](../skills/environment_overview.md).

## Details

## Instructions

```
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


## Related Commands

_(To be determined based on command relationships)_
