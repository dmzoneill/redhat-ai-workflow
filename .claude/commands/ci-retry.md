---
name: ci-retry
description: "Retry failed GitLab CI or Konflux/Tekton pipelines."
arguments:
  - name: mr_id
    required: true
---
# CI Retry

Retry failed GitLab CI or Konflux/Tekton pipelines.

## Instructions

```text
skill_run("ci_retry", '{"mr_id": $MR_ID}')
```

## What It Does

1. Detects CI system (GitLab CI or Konflux/Tekton)
2. Gets current pipeline status
3. Retries failed jobs/pipeline
4. Monitors retry status

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `mr_id` | GitLab MR ID - will retry its pipeline | - |
| `pipeline_id` | GitLab CI pipeline ID to retry | - |
| `tekton_run` | Tekton PipelineRun name to re-trigger | - |
| `project` | GitLab project path | `automation-analytics/automation-analytics-backend` |
| `namespace` | Konflux/Tekton namespace | `aap-aa-tenant` |
| `wait` | Wait for pipeline to complete | `false` |

## Examples

```bash
# Retry MR's failed pipeline
skill_run("ci_retry", '{"mr_id": 1450}')

# Retry specific GitLab pipeline
skill_run("ci_retry", '{"pipeline_id": 12345}')

# Retry Tekton pipeline
skill_run("ci_retry", '{"tekton_run": "backend-build-abc123"}')

# Retry and wait for result
skill_run("ci_retry", '{"mr_id": 1450, "wait": true}')
```

## See Also

- `/ci-health` - Diagnose CI issues
- `/check-prs` - Check your PRs for pipeline status
