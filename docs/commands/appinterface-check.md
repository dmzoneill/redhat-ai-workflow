# /appinterface-check

> Validate app-interface GitOps configuration.

## Overview

Validate app-interface GitOps configuration.

**Underlying Skill:** `appinterface_check`

This command is a wrapper that calls the `appinterface_check` skill. For detailed process information, see [skills/appinterface_check.md](../skills/appinterface_check.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `saas_file` | No | - |

## Usage

### Examples

```bash
skill_run("appinterface_check", '{"saas_file": "$SAAS_FILE"}')
```

```bash
# Check tower-analytics SaaS
skill_run("appinterface_check", '{"saas_file": "tower-analytics"}')

# Check specific environment
skill_run("appinterface_check", '{"saas_file": "tower-analytics", "environment": "stage"}')
```

## Process Flow

This command invokes the `appinterface_check` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /appinterface-check]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call appinterface_check skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [appinterface_check skill documentation](../skills/appinterface_check.md).

## Details

## Instructions

```
skill_run("appinterface_check", '{"saas_file": "$SAAS_FILE"}')
```

## What It Does

1. Validates app-interface configuration
2. Shows SaaS file contents and refs
3. Compares against live state
4. Lists resource quotas and limits

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `saas_file` | SaaS file to check | Auto-detect |
| `environment` | Environment to validate | All |

## Examples

```bash
# Check tower-analytics SaaS
skill_run("appinterface_check", '{"saas_file": "tower-analytics"}')

# Check specific environment
skill_run("appinterface_check", '{"saas_file": "tower-analytics", "environment": "stage"}')
```


## Related Commands

_(To be determined based on command relationships)_
