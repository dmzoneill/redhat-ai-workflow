---
name: test-error-recovery
description: "Test skill for error recovery functionality."
arguments:
  - name: fail_step
---
# Test Error Recovery

Test skill for error recovery functionality.

## Instructions

```text
skill_run("test_error_recovery", '{}')
```

## What It Does

Tests the skill engine's error recovery and auto-heal capabilities.

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `fail_step` | Which step to simulate failure | No |
| `recovery_type` | Type of recovery to test | No |

## Examples

```bash
# Run error recovery test
skill_run("test_error_recovery", '{}')

# Test specific failure
skill_run("test_error_recovery", '{"fail_step": "api_call"}')
```
