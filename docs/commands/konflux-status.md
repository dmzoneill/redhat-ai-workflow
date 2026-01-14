# /konflux-status

> Get overall Konflux platform health.

## Overview

Get overall Konflux platform health.

**Underlying Skill:** `konflux_status`

This command is a wrapper that calls the `konflux_status` skill. For detailed process information, see [skills/konflux_status.md](../skills/konflux_status.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `namespace` | No | - |

## Usage

### Examples

```bash
skill_run("konflux_status", '{}')
```

```bash
# Overall Konflux status
skill_run("konflux_status", '{}')

# Specific namespace
skill_run("konflux_status", '{"namespace": "aap-aa-tenant"}')
```

## Process Flow

This command invokes the `konflux_status` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /konflux-status]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call konflux_status skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [konflux_status skill documentation](../skills/konflux_status.md).

## Details

## Instructions

```
skill_run("konflux_status", '{}')
```

## What It Does

1. Shows running and failed pipelines
2. Lists recent builds and their status
3. Checks application health
4. Summarizes namespace activity

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `namespace` | Specific namespace | `aap-aa-tenant` |
| `application` | Filter by application | All |

## Examples

```bash
# Overall Konflux status
skill_run("konflux_status", '{}')

# Specific namespace
skill_run("konflux_status", '{"namespace": "aap-aa-tenant"}')
```


## Related Commands

_(To be determined based on command relationships)_
