# Check Integration Tests

Review Konflux integration test status.

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
