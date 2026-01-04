---
name: cancel-pipeline
description: "Cancel a running Tekton pipeline."
arguments:
  - name: pipeline_run
    required: true
---
# Cancel Pipeline

Cancel a running Tekton pipeline.

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




