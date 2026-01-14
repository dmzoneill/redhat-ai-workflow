# /test-ephemeral

> Deploy and test a merge request in ephemeral environment.

## Overview

Deploy and test a merge request in ephemeral environment.

**Underlying Skill:** `test_mr_ephemeral`

This command is a wrapper that calls the `test_mr_ephemeral` skill. For detailed process information, see [skills/test_mr_ephemeral.md](../skills/test_mr_ephemeral.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `mr_id` | No | - |

## Usage

### Examples

```bash
skill_run("test_mr_ephemeral", '{"mr_id": $MR_ID}')
```

```bash
# Test an MR
skill_run("test_mr_ephemeral", '{"mr_id": 1234}')

# Test billing ClowdApp
skill_run("test_mr_ephemeral", '{"mr_id": 1234, "billing": true}')

# Keep namespace for manual testing
skill_run("test_mr_ephemeral", '{"mr_id": 1234, "keep_namespace": true}')
```

## Process Flow

This command invokes the `test_mr_ephemeral` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /test-ephemeral]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call test_mr_ephemeral skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [test_mr_ephemeral skill documentation](../skills/test_mr_ephemeral.md).

## Details

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


## Related Commands

_(To be determined based on command relationships)_
