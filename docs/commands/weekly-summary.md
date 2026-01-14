# /weekly-summary

> Generate a summary of work from session logs.

## Overview

Generate a summary of work from session logs.

**Underlying Skill:** `weekly_summary`

This command is a wrapper that calls the `weekly_summary` skill. For detailed process information, see [skills/weekly_summary.md](../skills/weekly_summary.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `days` | No | - |

## Usage

### Examples

```bash
skill_run("weekly_summary", '{}')
```

```bash
skill_run("weekly_summary", '{"days": 14}')
```

```bash
skill_run("weekly_summary", '{"format": "slack"}')
```

## Process Flow

This command invokes the `weekly_summary` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /weekly-summary]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call weekly_summary skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [weekly_summary skill documentation](../skills/weekly_summary.md).

## Details

## Usage

**Default (past 7 days):**
```
skill_run("weekly_summary", '{}')
```text

**Custom period:**
```
skill_run("weekly_summary", '{"days": 14}')
```text

**Slack format:**
```
skill_run("weekly_summary", '{"format": "slack"}')
```text

## What It Includes

- **Issues worked**: Jira issues mentioned in session logs
- **MRs created/reviewed**: Merge requests tracked
- **Deployments**: Ephemeral and other deployments
- **Debug sessions**: Investigation and debugging work
- **Patterns learned**: New error patterns saved
- **Currently active**: Active issues and open MRs from memory

## Example

```
/weekly-summary
```

This generates a comprehensive summary useful for:
- Weekly team standups
- Sprint reviews
- Personal progress tracking


## Related Commands

_(To be determined based on command relationships)_
