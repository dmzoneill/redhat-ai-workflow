# /sprint-planning

> Analyze backlog for sprint planning.

## Overview

Analyze backlog for sprint planning.

**Underlying Skill:** `sprint_planning`

This command is a wrapper that calls the `sprint_planning` skill. For detailed process information, see [skills/sprint_planning.md](../skills/sprint_planning.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `project` | No | - |

## Usage

### Examples

```bash
skill_run("sprint_planning", '{"project": "AAP"}')
```

```bash
# Analyze backlog
skill_run("sprint_planning", '{"project": "AAP"}')

# Plan specific sprint
skill_run("sprint_planning", '{"project": "AAP", "sprint": "Sprint 42"}')
```

## Process Flow

This command invokes the `sprint_planning` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /sprint-planning]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call sprint_planning skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [sprint_planning skill documentation](../skills/sprint_planning.md).

## Details

## Instructions

```
skill_run("sprint_planning", '{"project": "AAP"}')
```

## What It Does

1. Lists backlog issues by priority
2. Identifies blocked items
3. Shows story point estimates
4. Suggests sprint candidates
5. Flags issues needing refinement

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `project` | Jira project | `AAP` |
| `sprint` | Target sprint name | Next sprint |
| `capacity` | Team capacity (points) | Auto |

## Examples

```bash
# Analyze backlog
skill_run("sprint_planning", '{"project": "AAP"}')

# Plan specific sprint
skill_run("sprint_planning", '{"project": "AAP", "sprint": "Sprint 42"}')
```


## Related Commands

_(To be determined based on command relationships)_
