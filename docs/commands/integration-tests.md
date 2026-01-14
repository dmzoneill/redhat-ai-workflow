# /integration-tests

> Review Konflux integration test status.

## Overview

Review Konflux integration test status.

**Underlying Skill:** `check_integration_tests`

This command is a wrapper that calls the `check_integration_tests` skill. For detailed process information, see [skills/check_integration_tests.md](../skills/check_integration_tests.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `application` | No | - |

## Usage

### Examples

```bash
skill_run("check_integration_tests", '{}')
```

```bash
# Check all integration tests
skill_run("check_integration_tests", '{}')

# Check specific application
skill_run("check_integration_tests", '{"application": "backend"}')
```

## Process Flow

This command invokes the `check_integration_tests` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /integration-tests]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call check_integration_tests skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [check_integration_tests skill documentation](../skills/check_integration_tests.md).

## Details

## Instructions

```
skill_run("check_integration_tests", '{}')
```

## What It Does

1. Lists integration test scenarios
2. Shows recent test results
3. Identifies failing tests
4. Links to snapshot and pipeline details

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `namespace` | Konflux namespace | `aap-aa-tenant` |
| `application` | Application to check | All |
| `snapshot` | Specific snapshot to review | Latest |

## Examples

```bash
# Check all integration tests
skill_run("check_integration_tests", '{}')

# Check specific application
skill_run("check_integration_tests", '{"application": "backend"}')
```


## Related Commands

_(To be determined based on command relationships)_
