# /deploy

> **Description:** Deploy a Merge Request to an ephemeral environment for testing.

## Overview

**Description:** Deploy a Merge Request to an ephemeral environment for testing.

**Underlying Skill:** `test_mr_ephemeral`

This command is a wrapper that calls the `test_mr_ephemeral` skill. For detailed process information, see [skills/test_mr_ephemeral.md](../skills/test_mr_ephemeral.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `mr_id` | No | - |

## Usage

### Examples

```bash
skill_run("test_mr_ephemeral", '{"mr_id": 1450}')
```

```bash
skill_run("test_mr_ephemeral", '{"mr_id": 1450, "billing": true}')
  ```text
- `run_tests`: Run pytest after deployment (default: true)

**What it does:**

1. **Validates MR** - Checks MR exists and gets commit SHA
2. **Checks image** - Verifies Konflux build exists in Quay
3. **Reserves namespace** - Gets ephemeral namespace (4h default)
4. **Deploys** - Runs bonfire deploy with correct ClowdApp
5. **Waits for pods** - Monitors pod readiness
6. **Runs tests** - Executes smoke tests in the namespace
7. **Reports** - Shows deployment URL and test results

**ClowdApp auto-detection:**
The skill automatically determines whether to deploy the main or billing ClowdApp based on:
- Commit message content
- Jira issue summary
- Files changed (billing controller paths)

**Example:**
```

```bash
**Prerequisites:**
- Logged into ephemeral OpenShift cluster
- bonfire_venv activated
- Konflux build completed

**Cleanup:**
After testing, release the namespace:
```

## Process Flow

This command invokes the `test_mr_ephemeral` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /deploy]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call test_mr_ephemeral skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```

For detailed step-by-step process, see the [test_mr_ephemeral skill documentation](../skills/test_mr_ephemeral.md).

## Details


## Related Commands

_(To be determined based on command relationships)_
