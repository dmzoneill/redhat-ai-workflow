# /check-prs

> Review status of your open merge requests.

## Overview

Review status of your open merge requests.

**Underlying Skill:** `check_my_prs`

This command is a wrapper that calls the `check_my_prs` skill. For detailed process information, see [skills/check_my_prs.md](../skills/check_my_prs.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `project` | No | - |

## Usage

### Examples

```bash
skill_run("check_my_prs", '{}')
```

```bash
# Check all your MRs
skill_run("check_my_prs", '{}')

# Check specific project
skill_run("check_my_prs", '{"project": "automation-analytics-backend"}')
```

## Process Flow

This command invokes the `check_my_prs` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /check-prs]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call check_my_prs skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [check_my_prs skill documentation](../skills/check_my_prs.md).

## Details

## Instructions

```
skill_run("check_my_prs", '{}')
```

## What It Does

1. Lists all your open MRs across projects
2. Shows CI/pipeline status for each
3. Checks for new comments or review feedback
4. Identifies MRs ready to merge
5. Flags stale MRs needing attention

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `project` | Specific project to check | All projects |
| `include_drafts` | Include draft MRs | `true` |

## Examples

```bash
# Check all your MRs
skill_run("check_my_prs", '{}')

# Check specific project
skill_run("check_my_prs", '{"project": "automation-analytics-backend"}')
```


## Related Commands

_(To be determined based on command relationships)_
