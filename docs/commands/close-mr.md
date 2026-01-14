# /close-mr

> Close a merge request and update linked Jira.

## Overview

Close a merge request and update linked Jira.

**Underlying Skill:** `close_mr`

This command is a wrapper that calls the `close_mr` skill. For detailed process information, see [skills/close_mr.md](../skills/close_mr.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `mr_id` | No | - |
| `project` | No | - |

## Usage

### Examples

```bash
skill_run("close_mr", '{"mr_id": $MR_ID, "project": "$PROJECT"}')
```

```bash
# Close an MR
skill_run("close_mr", '{"mr_id": 1234}')

# Close with reason
skill_run("close_mr", '{"mr_id": 1234, "reason": "Superseded by !1235"}')
```

## Process Flow

This command invokes the `close_mr` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /close-mr]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call close_mr skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [close_mr skill documentation](../skills/close_mr.md).

## Details

## Instructions

```
skill_run("close_mr", '{"mr_id": $MR_ID, "project": "$PROJECT"}')
```

## What It Does

1. Gets MR details and linked Jira
2. Closes the MR (not merge)
3. Transitions Jira issue appropriately
4. Adds closure comment with reason

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `mr_id` | MR ID to close | Required |
| `project` | GitLab project | Current repo |
| `reason` | Closure reason | Optional |

## Examples

```bash
# Close an MR
skill_run("close_mr", '{"mr_id": 1234}')

# Close with reason
skill_run("close_mr", '{"mr_id": 1234, "reason": "Superseded by !1235"}')
```

## Note

This **closes** (abandons) the MR, it does not merge it.
Use `/review-mr` and approve to merge.


## Related Commands

_(To be determined based on command relationships)_
