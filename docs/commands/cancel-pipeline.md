# /cancel-pipeline

> Cancel a running Tekton pipeline.

## Overview

Cancel a running Tekton pipeline.

**Underlying Skill:** `cancel_pipeline`

This command is a wrapper that calls the `cancel_pipeline` skill. For detailed process information, see [skills/cancel_pipeline.md](../skills/cancel_pipeline.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `pipeline_run` | No | - |

## Usage

### Examples

```bash
skill_run("cancel_pipeline", '{"pipeline_run": "$PIPELINERUN"}')
```

```bash
# Cancel a pipeline
skill_run("cancel_pipeline", '{"pipeline_run": "backend-build-abc123"}')

# Cancel and delete
skill_run("cancel_pipeline", '{"pipeline_run": "backend-build-abc123", "delete": true}')
```

## Process Flow

This command invokes the `cancel_pipeline` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /cancel-pipeline]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call cancel_pipeline skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [cancel_pipeline skill documentation](../skills/cancel_pipeline.md).

## Details

## Instructions

```
skill_run("cancel_pipeline", '{"pipeline_run": "$PIPELINERUN"}')
```

## What It Does

1. Lists running pipelines
2. Shows pipeline details
3. Cancels the specified run
4. Optionally cleans up resources

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `pipeline_run` | PipelineRun name | Required |
| `namespace` | Konflux namespace | `aap-aa-tenant` |
| `delete` | Delete after cancel | `false` |

## Examples

```bash
# Cancel a pipeline
skill_run("cancel_pipeline", '{"pipeline_run": "backend-build-abc123"}')

# Cancel and delete
skill_run("cancel_pipeline", '{"pipeline_run": "backend-build-abc123", "delete": true}')
```

## Finding Pipelines

Use `/konflux-status` to see running pipelines.


## Related Commands

_(To be determined based on command relationships)_
