---
name: test-mr-ephemeral
description: "Deploy and test a merge request in an ephemeral environment."
arguments:
  - name: mr_id
    required: true
---
# Test MR in Ephemeral

Deploy and test a merge request in an ephemeral environment.

## Instructions

```text
skill_run("test_mr_ephemeral", '{"mr_id": $MR_ID}')
```

## What It Does

1. Validates MR exists and gets commit SHA
2. Checks Konflux image exists in Quay
3. Reserves ephemeral namespace (4h default)
4. Deploys using bonfire with correct ClowdApp
5. Waits for pods to be ready
6. Runs smoke tests in the namespace
7. Reports deployment URL and test results

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `mr_id` | GitLab MR number | Yes |
| `billing` | Deploy billing ClowdApp | No (default: false) |
| `run_tests` | Run pytest after deployment | No (default: true) |

## Examples

```bash
# Deploy and test MR
skill_run("test_mr_ephemeral", '{"mr_id": 1450}')

# Deploy billing changes
skill_run("test_mr_ephemeral", '{"mr_id": 1450, "billing": true}')

# Deploy without running tests
skill_run("test_mr_ephemeral", '{"mr_id": 1450, "run_tests": false}')
```

## Prerequisites

- VPN connected
- Logged into ephemeral cluster
- Konflux build completed

## Cleanup

After testing, release the namespace:
```text
bonfire_namespace_release("ephemeral-xxxxx")
```
