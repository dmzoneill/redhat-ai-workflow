# /start-work

> Begin work on a Jira issue - creates branch, sets up environment.

## Overview

Begin work on a Jira issue - creates branch, sets up environment.

**Underlying Skill:** `start_work`

This command is a wrapper that calls the `start_work` skill. For detailed process information, see [skills/start_work.md](../skills/start_work.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `issue_key` | No | - |

## Usage

### Examples

```bash
skill_run("start_work", '{"issue_key": "$JIRA_KEY"}')
```

```bash
# Start work on an issue
skill_run("start_work", '{"issue_key": "AAP-61214"}')

# With specific repository
skill_run("start_work", '{"issue_key": "AAP-61214", "repo": "automation-analytics-backend"}')
```

```bash
aap-61214-short-description-from-jira-title
```

## Process Flow

This command invokes the `start_work` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /start-work]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call start_work skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [start_work skill documentation](../skills/start_work.md).

## Details

## Instructions

Start working on a Jira issue:

```
skill_run("start_work", '{"issue_key": "$JIRA_KEY"}')
```

This will:
1. Fetch Jira issue details
2. Create a branch: `aap-XXXXX-short-description`
3. Switch to the branch
4. Show issue context and acceptance criteria
5. Suggest next steps

## Example

```bash
# Start work on an issue
skill_run("start_work", '{"issue_key": "AAP-61214"}')

# With specific repository
skill_run("start_work", '{"issue_key": "AAP-61214", "repo": "automation-analytics-backend"}')
```text

## Branch Naming

Branch will be created as:
```
aap-61214-short-description-from-jira-title
```

## What Happens Next

After starting work:
1. Make your code changes
2. Commit with: `AAP-61214 - type(scope): description`
3. Push and create MR: `/create-mr`


## Related Commands

_(To be determined based on command relationships)_
