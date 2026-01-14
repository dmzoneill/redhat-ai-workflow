---
name: ci-health
description: "Diagnose CI/CD pipeline issues."
arguments:
  - name: project
    required: true
---
# CI Health Check

Diagnose CI/CD pipeline issues.

## Instructions

```text
skill_run("check_ci_health", '{"project": "$PROJECT"}')
```

## What It Does

1. Lists recent pipeline runs
2. Shows failed jobs with error details
3. Validates `.gitlab-ci.yml` configuration
4. Identifies flaky tests or infrastructure issues

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `project` | GitLab project to check | Current repo |
| `pipeline_id` | Specific pipeline to inspect | Latest |
| `job_name` | Specific job to focus on | All failed |

## Examples

```bash
# Check current repo CI
skill_run("check_ci_health", '{}')

# Check specific project
skill_run("check_ci_health", '{"project": "automation-analytics-backend"}')

# Investigate specific pipeline
skill_run("check_ci_health", '{"pipeline_id": 12345}')
```
