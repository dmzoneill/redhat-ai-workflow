# /memory

> View and manage the persistent memory system.

## Overview

View and manage the persistent memory system.

**Underlying Skill:** `memory_view`

This command is a wrapper that calls the `memory_view` skill. For detailed process information, see [skills/memory_view.md](../skills/memory_view.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `section` | No | - |

## Usage

### Examples

```bash
## Options

View specific sections:
```

```bash
## Actions

Clear completed items:
```

```bash
Add a follow-up task:
```

## Process Flow

This command invokes the `memory_view` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /memory]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call memory_view skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```

For detailed step-by-step process, see the [memory_view skill documentation](../skills/memory_view.md).

## Details

## Instructions

```python
skill_run("memory_view")
```

## Options

View specific sections:
```python
# Just current work
skill_run("memory_view", '{"section": "work"}')

# Just follow-ups
skill_run("memory_view", '{"section": "followups"}')

# Just environments
skill_run("memory_view", '{"section": "environments"}')

# Just patterns
skill_run("memory_view", '{"section": "patterns"}')
```

## Actions

Clear completed items:
```python
skill_run("memory_view", '{"action": "clear_completed"}')
```

Add a follow-up task:
```python
skill_run("memory_view", '{"action": "add_followup", "followup_text": "Review MR !1234", "followup_priority": "high"}')
```

Clean old session logs:
```python
skill_run("memory_view", '{"action": "clear_old_sessions"}')
```


## Related Commands

*(To be determined based on command relationships)*
