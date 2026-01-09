# ⚡ konflux_status

> Get overall Konflux build system status

## Overview

Get overall Konflux build system status.

This skill shows:
- Application status
- Running pipelines
- Failed pipelines
- Namespace summary

Uses: konflux_status, konflux_list_applications, konflux_namespace_summary,
      konflux_running_pipelines, konflux_failed_pipelines

**Version:** 1.0

## Quick Start

```bash
skill_run("konflux_status", '{"issue_key": "AAP-12345"}')
```

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `namespace` | string | No | `aap-aa-tenant` | Konflux namespace |
| `application` | string | No | `""` | Specific application to check (optional) |

## Process Flow

```mermaid
flowchart TD
    START([Start])
    STEP1[Step 1: Get Status]
    START --> STEP1
    STEP2[Step 2: Parse Status]
    STEP1 --> STEP2
    STEP3[Step 3: List Applications]
    STEP2 --> STEP3
    STEP4[Step 4: Parse Applications]
    STEP3 --> STEP4
    STEP5[Step 5: Get Running Pipelines]
    STEP4 --> STEP5
    STEP6[Step 6: Parse Running]
    STEP5 --> STEP6
    STEP7[Step 7: Get Failed Pipelines]
    STEP6 --> STEP7
    STEP8[Step 8: Parse Failed]
    STEP7 --> STEP8
    STEP9[Step 9: Get Namespace Summary]
    STEP8 --> STEP9
    STEP9 --> DONE([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style DONE fill:#10b981,stroke:#059669,color:#fff
```

## Detailed Steps

### Step 1: Get Status

**Description:** Get Konflux overall status

**Tool:** `konflux_status`

### Step 2: Parse Status

**Description:** Parse status

**Tool:** `compute`

### Step 3: List Applications

**Description:** List applications in namespace

**Tool:** `konflux_list_applications`

### Step 4: Parse Applications

**Description:** Parse application list

**Tool:** `compute`

### Step 5: Get Running Pipelines

**Description:** Get running pipelines

**Tool:** `konflux_running_pipelines`

### Step 6: Parse Running

**Description:** Parse running pipelines

**Tool:** `compute`

### Step 7: Get Failed Pipelines

**Description:** Get failed pipelines

**Tool:** `konflux_failed_pipelines`

### Step 8: Parse Failed

**Description:** Parse failed pipelines

**Tool:** `compute`

### Step 9: Get Namespace Summary

**Description:** Get namespace summary

**Tool:** `konflux_namespace_summary`


## MCP Tools Used (5 total)

- `konflux_failed_pipelines`
- `konflux_list_applications`
- `konflux_namespace_summary`
- `konflux_running_pipelines`
- `konflux_status`

## Related Skills

_(To be determined based on skill relationships)_
