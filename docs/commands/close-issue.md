# /close-issue

> Close a Jira issue and add a summary comment from commits.

## Overview

Close a Jira issue and add a summary comment from commits.

**Underlying Skill:** `close_issue`

This command is a wrapper that calls the `close_issue` skill. For detailed process information, see [skills/close_issue.md](../skills/close_issue.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `issue_key` | No | - |

## Usage

### Examples

```bash
skill_run("close_issue", '{"issue_key": "AAP-XXXXX"}')
```

```bash
# Close issue with commit summary
skill_run("close_issue", '{"issue_key": "AAP-12345"}')

# Close without adding comment
skill_run("close_issue", '{"issue_key": "AAP-12345", "add_comment": false}')
```

```bash
/start-work AAP-12345     # Begin work
... code ...
/create-mr                # Create merge request
... review/merge ...
/close-issue AAP-12345    # Wrap up
```

## Process Flow

This command invokes the `close_issue` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /close-issue]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call close_issue skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [close_issue skill documentation](../skills/close_issue.md).

## Details

## Instructions

```
skill_run("close_issue", '{"issue_key": "AAP-XXXXX"}')
```

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `issue_key` | Jira issue key (required) | - |
| `repo` | Repository path | Resolved from issue |
| `add_comment` | Add commit summary comment | `true` |

## Examples

```bash
# Close issue with commit summary
skill_run("close_issue", '{"issue_key": "AAP-12345"}')

# Close without adding comment
skill_run("close_issue", '{"issue_key": "AAP-12345", "add_comment": false}')
```text

## What It Does

1. Gets the Jira issue details
2. Finds commits referencing the issue
3. Generates a summary comment from commits
4. Adds the comment to Jira
5. Transitions issue to Done

## Workflow Integration

```
/start-work AAP-12345     # Begin work
... code ...
/create-mr                # Create merge request
... review/merge ...
/close-issue AAP-12345    # Wrap up
```

## Comment Format

The auto-generated comment includes:
- MR link (if found)
- List of commits
- Files changed summary
- Merge date


## Related Commands

_(To be determined based on command relationships)_
