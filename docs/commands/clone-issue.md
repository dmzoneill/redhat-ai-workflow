# /clone-issue

> Clone an existing Jira issue.

## Overview

Clone an existing Jira issue.

**Underlying Skill:** `clone_jira_issue`

This command is a wrapper that calls the `clone_jira_issue` skill. For detailed process information, see [skills/clone_jira_issue.md](../skills/clone_jira_issue.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `issue_key` | No | - |

## Usage

### Examples

```bash
skill_run("clone_jira_issue", '{"issue_key": "$JIRA_KEY"}')
```

```bash
# Clone an issue
skill_run("clone_jira_issue", '{"issue_key": "AAP-61214"}')

# Clone to different project
skill_run("clone_jira_issue", '{"issue_key": "AAP-61214", "project": "RHCLOUD"}')
```

## Process Flow

This command invokes the `clone_jira_issue` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /clone-issue]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call clone_jira_issue skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [clone_jira_issue skill documentation](../skills/clone_jira_issue.md).

## Details

## Instructions

```
skill_run("clone_jira_issue", '{"issue_key": "$JIRA_KEY"}')
```

## What It Does

1. Reads source issue details
2. Creates clone with linked reference
3. Adds "clones" link to original
4. Optionally assigns to you

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `issue_key` | Source issue to clone | Required |
| `project` | Target project | Same as source |
| `assign_to_me` | Auto-assign clone | `true` |

## Examples

```bash
# Clone an issue
skill_run("clone_jira_issue", '{"issue_key": "AAP-61214"}')

# Clone to different project
skill_run("clone_jira_issue", '{"issue_key": "AAP-61214", "project": "RHCLOUD"}')
```


## Related Commands

_(To be determined based on command relationships)_
