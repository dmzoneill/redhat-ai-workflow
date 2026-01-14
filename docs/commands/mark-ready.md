# /mark-ready

> Remove draft status from an MR and notify the team.

## Overview

Remove draft status from an MR and notify the team.

**Underlying Skill:** `mark_mr_ready`

This command is a wrapper that calls the `mark_mr_ready` skill. For detailed process information, see [skills/mark_mr_ready.md](../skills/mark_mr_ready.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `mr_id` | No | - |

## Usage

### Examples

```bash
skill_run("mark_mr_ready", '{"mr_id": 1234}')
```

```bash
# Mark MR ready
skill_run("mark_mr_ready", '{"mr_id": 1459}')

# Mark ready and update Jira
skill_run("mark_mr_ready", '{"mr_id": 1459, "issue_key": "AAP-12345"}')

# Mark ready without Jira update
skill_run("mark_mr_ready", '{"mr_id": 1459, "update_jira": false}')
```

```bash
/create-mr          # Creates as draft by default
... self-review ...
... fix issues ...
/mark-ready         # Remove draft, notify team
```

## Process Flow

This command invokes the `mark_mr_ready` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /mark-ready]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call mark_mr_ready skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [mark_mr_ready skill documentation](../skills/mark_mr_ready.md).

## Details

## Instructions

```
skill_run("mark_mr_ready", '{"mr_id": 1234}')
```

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `mr_id` | GitLab MR ID (required) | - |
| `project` | GitLab project path | Auto-detected |
| `issue_key` | Jira issue to update | - |
| `update_jira` | Update Jira status to "In Review" | `true` |

## Examples

```bash
# Mark MR ready
skill_run("mark_mr_ready", '{"mr_id": 1459}')

# Mark ready and update Jira
skill_run("mark_mr_ready", '{"mr_id": 1459, "issue_key": "AAP-12345"}')

# Mark ready without Jira update
skill_run("mark_mr_ready", '{"mr_id": 1459, "update_jira": false}')
```text

## What It Does

1. Removes "Draft:" prefix from MR title
2. Sets MR status to ready for review
3. Posts to team Slack channel asking for review
4. Updates Jira status to "In Review" (optional)

## Workflow

```
/create-mr          # Creates as draft by default
... self-review ...
... fix issues ...
/mark-ready         # Remove draft, notify team
```

## Why Draft First?

Creating MRs as drafts lets you:
- Run pipelines before review
- Self-review your changes
- Fix linting/test issues
- Polish before asking for review time


## Related Commands

_(To be determined based on command relationships)_
