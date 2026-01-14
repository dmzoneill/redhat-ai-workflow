# /ci-health

> Diagnose CI/CD pipeline issues.

## Overview

Diagnose CI/CD pipeline issues.

**Underlying Skill:** `check_ci_health`

This command is a wrapper that calls the `check_ci_health` skill. For detailed process information, see [skills/check_ci_health.md](../skills/check_ci_health.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `project` | No | - |

## Usage

### Examples

```bash
skill_run("check_ci_health", '{"project": "$PROJECT"}')
```

```bash
# Check current repo CI
skill_run("check_ci_health", '{}')

# Check specific project
skill_run("check_ci_health", '{"project": "automation-analytics-backend"}')

# Investigate specific pipeline
skill_run("check_ci_health", '{"pipeline_id": 12345}')
```

## Process Flow

This command invokes the `check_ci_health` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /ci-health]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call check_ci_health skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [check_ci_health skill documentation](../skills/check_ci_health.md).

## Details

## Instructions

```
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


## Related Commands

_(To be determined based on command relationships)_
