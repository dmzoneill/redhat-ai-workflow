# /jira-hygiene

> Check and fix Jira issue quality before you start coding.

## Overview

Check and fix Jira issue quality before you start coding.

**Underlying Skill:** `jira_hygiene`

This command is a wrapper that calls the `jira_hygiene` skill. For detailed process information, see [skills/jira_hygiene.md](../skills/jira_hygiene.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `issue_key` | No | - |

## Usage

### Examples

```bash
skill_run("jira_hygiene", '{"issue_key": "AAP-XXXXX"}')
```

```bash
# Check issue hygiene
skill_run("jira_hygiene", '{"issue_key": "AAP-12345"}')

# Check and auto-fix issues
skill_run("jira_hygiene", '{"issue_key": "AAP-12345", "auto_fix": true}')

# Full auto: fix and transition
skill_run("jira_hygiene", '{"issue_key": "AAP-12345", "auto_fix": true, "auto_transition": true}')
```

## Process Flow

This command invokes the `jira_hygiene` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /jira-hygiene]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call jira_hygiene skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [jira_hygiene skill documentation](../skills/jira_hygiene.md).

## Details

## Instructions

```
skill_run("jira_hygiene", '{"issue_key": "AAP-XXXXX"}')
```

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `issue_key` | Jira issue key (required) | - |
| `repo_name` | Repository name (for component) | - |
| `auto_fix` | Automatically fix issues | `false` |
| `auto_transition` | Move New → Refinement when complete | `false` |

## Examples

```bash
# Check issue hygiene
skill_run("jira_hygiene", '{"issue_key": "AAP-12345"}')

# Check and auto-fix issues
skill_run("jira_hygiene", '{"issue_key": "AAP-12345", "auto_fix": true}')

# Full auto: fix and transition
skill_run("jira_hygiene", '{"issue_key": "AAP-12345", "auto_fix": true, "auto_transition": true}')
```

## What It Checks

| Check | Description |
|-------|-------------|
| 📝 Description | Has meaningful content |
| ✅ Acceptance Criteria | Defined and clear |
| 🏷️ Labels | Has appropriate labels |
| 📊 Priority | Set appropriately |
| 🎯 Epic Link | Connected to an epic |
| 📐 Story Points | Estimated |
| 🎨 Formatting | Proper Jira markup |

## When to Use

- Before starting work on an issue (`/start-work`)
- During backlog refinement
- Before creating an MR
- Sprint planning prep


## Related Commands

_(To be determined based on command relationships)_
