# /extend-ephemeral

> Extend the lifetime of an ephemeral namespace.

## Overview

Extend the lifetime of an ephemeral namespace.

**Underlying Skill:** `extend_ephemeral`

This command is a wrapper that calls the `extend_ephemeral` skill. For detailed process information, see [skills/extend_ephemeral.md](../skills/extend_ephemeral.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `namespace` | No | - |

## Usage

### Examples

```bash
skill_run("extend_ephemeral", '{"namespace": "$NAMESPACE"}')
```

```bash
# Extend your namespace
skill_run("extend_ephemeral", '{}')

# Extend specific namespace
skill_run("extend_ephemeral", '{"namespace": "ephemeral-abc123"}')

# Extend by 8 hours
skill_run("extend_ephemeral", '{"namespace": "ephemeral-abc123", "hours": 8}')
```

## Process Flow

This command invokes the `extend_ephemeral` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /extend-ephemeral]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call extend_ephemeral skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [extend_ephemeral skill documentation](../skills/extend_ephemeral.md).

## Details

## Instructions

```
skill_run("extend_ephemeral", '{"namespace": "$NAMESPACE"}')
```

## What It Does

1. Lists your ephemeral namespaces
2. Shows current expiration time
3. Extends the namespace lifetime

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `namespace` | Namespace to extend | Auto-detect (if only one) |
| `hours` | Hours to extend | `4` |

## Examples

```bash
# Extend your namespace
skill_run("extend_ephemeral", '{}')

# Extend specific namespace
skill_run("extend_ephemeral", '{"namespace": "ephemeral-abc123"}')

# Extend by 8 hours
skill_run("extend_ephemeral", '{"namespace": "ephemeral-abc123", "hours": 8}')
```

## Finding Your Namespace

Use `/check-namespaces` to see your ephemeral namespaces.


## Related Commands

_(To be determined based on command relationships)_
