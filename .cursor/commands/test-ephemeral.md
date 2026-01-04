# Test MR in Ephemeral

Deploy and test a merge request in ephemeral environment.

## Instructions

```
skill_run("test_mr_ephemeral", '{"mr_id": $MR_ID}')
```

## What It Does

1. Gets MR details and commit SHA
2. Waits for Konflux build to complete
3. Reserves an ephemeral namespace
4. Deploys the MR's image
5. Verifies deployment health
6. Runs basic smoke tests
7. Optionally releases namespace when done

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `mr_id` | MR ID to test | Required |
| `project` | GitLab project | Current repo |
| `billing` | Deploy billing ClowdApp | `false` |
| `keep_namespace` | Don't release on completion | `false` |

## Examples

```bash
# Test an MR
skill_run("test_mr_ephemeral", '{"mr_id": 1234}')

# Test billing ClowdApp
skill_run("test_mr_ephemeral", '{"mr_id": 1234, "billing": true}')

# Keep namespace for manual testing
skill_run("test_mr_ephemeral", '{"mr_id": 1234, "keep_namespace": true}')
```

## Prerequisites

- VPN connected (`/vpn`)
- Ephemeral cluster login (`kube_login("ephemeral")`)







