# Deploy to Ephemeral

Deploy code to an ephemeral environment for testing.

## Instructions

```text
skill_run("deploy_to_ephemeral", '{"mr_id": $MR_ID}')
```

## What It Does

1. Validates the MR exists
2. Gets the commit SHA
3. Checks for Konflux image in Quay
4. Reserves an ephemeral namespace
5. Deploys using bonfire
6. Waits for pods to be ready

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `mr_id` | GitLab MR number | Yes |
| `billing` | Deploy billing ClowdApp | No (default: false) |
| `duration` | Namespace duration in hours | No (default: 4) |

## Examples

```bash
# Deploy MR to ephemeral
skill_run("deploy_to_ephemeral", '{"mr_id": 1450}')

# Deploy billing changes
skill_run("deploy_to_ephemeral", '{"mr_id": 1450, "billing": true}')
```

## Prerequisites

- VPN connected
- Logged into ephemeral cluster
- Konflux build completed

## See Also

- `/test-ephemeral` - Full test workflow
- `/extend-ephemeral` - Extend namespace duration
