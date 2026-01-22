# Check CI Health

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

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `project` | GitLab project to check | No (current repo) |
| `pipeline_id` | Specific pipeline to inspect | No (latest) |
| `job_name` | Specific job to focus on | No (all failed) |

## Examples

```bash
# Check current repo CI
skill_run("check_ci_health", '{}')

# Check specific project
skill_run("check_ci_health", '{"project": "automation-analytics-backend"}')

# Investigate specific pipeline
skill_run("check_ci_health", '{"pipeline_id": 12345}')
```
