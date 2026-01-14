# /memory-init

> Initialize or reset memory files to a clean state.

## Overview

Initialize or reset memory files to a clean state.

**Underlying Skill:** `memory_init`

This command is a wrapper that calls the `memory_init` skill. For detailed process information, see [skills/memory_init.md](../skills/memory_init.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `confirm` | No | - |

## Usage

### Examples

```bash
skill_run("memory_init", '{"confirm": true}')
```

```bash
skill_run("memory_init", '{"confirm": true, "reset_learned": true}')
```

```bash
skill_run("memory_init", '{"confirm": true, "reset_learned": true, "preserve_patterns": true}')
```

## Process Flow

This command invokes the `memory_init` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /memory-init]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call memory_init skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [memory_init skill documentation](../skills/memory_init.md).

## Details

## Usage

**Reset state files only (preserves learned patterns):**
```
skill_run("memory_init", '{"confirm": true}')
```text

**Full reset (including learned memory):**
```
skill_run("memory_init", '{"confirm": true, "reset_learned": true}')
```text

**Full reset but keep patterns:**
```
skill_run("memory_init", '{"confirm": true, "reset_learned": true, "preserve_patterns": true}')
```

## What Gets Reset

#

## State Files (always reset)
- `state/current_work.yaml` - Active issues, open MRs, follow-ups
- `state/environments.yaml` - Environment status, ephemeral namespaces

#

## Learned Files (only with reset_learned=true)
- `learned/runbooks.yaml` - Operational procedures
- `learned/teammate_preferences.yaml` - Review preferences
- `learned/service_quirks.yaml` - Service behaviors
- `learned/patterns.yaml` - Error patterns (preserved by default)

## When to Use

- Starting a new sprint or project
- After extended time away from the codebase
- Setting up on a new machine
- Clearing test data after experimentation


## Related Commands

_(To be determined based on command relationships)_
