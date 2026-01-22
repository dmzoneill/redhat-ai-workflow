---
name: check-integration-tests
description: "Run or check status of integration tests."
arguments:
  - name: branch
---
# Check Integration Tests

Run or check status of integration tests.

## Instructions

```text
skill_run("check_integration_tests", '{}')
```

## What It Does

1. Checks integration test pipeline status
2. Shows recent test failures
3. Identifies flaky tests
4. Provides test coverage info

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `project` | Project to check | No (auto-detected) |
| `branch` | Branch to check tests for | No (current) |

## Examples

```bash
# Check integration tests
skill_run("check_integration_tests", '{}')

# Check specific branch
skill_run("check_integration_tests", '{"branch": "feature-branch"}')
```
