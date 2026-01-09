# ⚡ learn_pattern

> Save a new error pattern to memory

## Overview

Save a new error pattern to memory.

When you discover a new error pattern and its fix, use this skill
to remember it for future debugging sessions.

The pattern is saved to memory/learned/patterns.yaml and will be
automatically matched during investigate_alert and debug_prod skills.

**Version:** 1.0

## Quick Start

```bash
skill_run("learn_pattern", '{"issue_key": "AAP-12345"}')
```

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `pattern` | string | ✅ Yes | `-` | Short name for the pattern (e.g., 'OOMKilled', 'ImagePullBackOff') |
| `meaning` | string | ✅ Yes | `-` | What this error means (e.g., 'Container exceeded memory limit') |
| `fix` | string | ✅ Yes | `-` | How to fix this error (e.g., 'Increase memory limits in deployment') |
| `commands` | string | No | `-` | Comma-separated commands to run for diagnosis (e.g., 'kubectl describe pod X,kubectl logs X') |
| `category` | string | No | `general` | Category: pod_errors, log_patterns, network, general |

## Process Flow

```mermaid
flowchart TD
    START([Start])
    STEP1[Step 1: Validate Inputs]
    START --> STEP1
    STEP2[Step 2: Parse Commands]
    STEP1 --> STEP2
    STEP3[Step 3: Save Pattern]
    STEP2 --> STEP3
    STEP4[Step 4: Log Session]
    STEP3 --> STEP4
    STEP4 --> DONE([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style DONE fill:#10b981,stroke:#059669,color:#fff
```

## Detailed Steps

### Step 1: Validate Inputs

**Description:** Validate inputs

**Tool:** `compute`

### Step 2: Parse Commands

**Description:** Parse comma-separated commands

**Tool:** `compute`

**Condition:** `validation.valid`

### Step 3: Save Pattern

**Description:** Save pattern to memory

**Tool:** `compute`

**Condition:** `validation.valid`

### Step 4: Log Session

**Description:** Log pattern learning to session

**Tool:** `memory_session_log`

**Condition:** `save_result.success`


## MCP Tools Used (1 total)

- `memory_session_log`

## Related Skills

_(To be determined based on skill relationships)_
