# ⚡ extend_ephemeral

> Extend the duration of an ephemeral namespace reservation

## Overview

Extend the duration of an ephemeral namespace reservation.

Use when:
- Tests are taking longer than expected
- You need more time to debug
- Demo/testing session running long

The skill will:
1. List your current namespaces
2. Get details on the target namespace
3. Extend the reservation
4. Confirm new expiry time

**Version:** 1.0

## Quick Start

```bash
skill_run("extend_ephemeral", '{"issue_key": "AAP-12345"}')
```

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `namespace` | string | No | `-` | Namespace to extend (will list yours if not specified) |
| `duration` | string | No | `1h` | How much time to add (e.g., '1h', '2h', '4h') |
| `list_only` | boolean | No | `False` | Just list namespaces without extending |

## Process Flow

```mermaid
flowchart TD
    START([Start])
    STEP1[Step 1: List My Namespaces]
    START --> STEP1
    STEP2[Step 2: Parse Namespaces]
    STEP1 --> STEP2
    STEP3[Step 3: Select Namespace]
    STEP2 --> STEP3
    STEP4[Step 4: Describe Namespace]
    STEP3 --> STEP4
    STEP5[Step 5: Parse Describe]
    STEP4 --> STEP5
    STEP6[Step 6: Extend Namespace]
    STEP5 --> STEP6
    STEP7[Step 7: Parse Extend Result]
    STEP6 --> STEP7
    STEP8[Step 8: Log Extension]
    STEP7 --> STEP8
    STEP8 --> DONE([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style DONE fill:#10b981,stroke:#059669,color:#fff
```

## Detailed Steps

### Step 1: List My Namespaces

**Description:** List my ephemeral namespaces

**Tool:** `bonfire_namespace_list`

### Step 2: Parse Namespaces

**Description:** Parse namespace list

**Tool:** `compute`

### Step 3: Select Namespace

**Description:** Select namespace to extend

**Tool:** `compute`

### Step 4: Describe Namespace

**Description:** Get namespace details

**Tool:** `bonfire_namespace_describe`

**Condition:** `selected_ns.namespace and not inputs.list_only`

### Step 5: Parse Describe

**Description:** Parse namespace details

**Tool:** `compute`

**Condition:** `ns_describe_raw`

### Step 6: Extend Namespace

**Description:** Extend the namespace reservation

**Tool:** `bonfire_namespace_extend`

**Condition:** `selected_ns.namespace and not inputs.list_only`

### Step 7: Parse Extend Result

**Description:** Parse extend result

**Tool:** `compute`

**Condition:** `extend_result`

### Step 8: Log Extension

**Description:** Log extension to session

**Tool:** `memory_session_log`

**Condition:** `extension_status and extension_status.success`


## MCP Tools Used (4 total)

- `bonfire_namespace_describe`
- `bonfire_namespace_extend`
- `bonfire_namespace_list`
- `memory_session_log`

## Related Skills

_(To be determined based on skill relationships)_
