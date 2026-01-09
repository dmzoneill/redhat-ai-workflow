# ⚡ sprint_planning

> Help with sprint planning by analyzing the backlog

## Overview

Help with sprint planning by analyzing the backlog.

This skill:
- Lists unassigned issues in the backlog
- Identifies blocked items
- Shows issues ready for sprint
- Can add issues to a sprint

Uses: jira_list_issues, jira_list_blocked, jira_add_to_sprint, jira_add_flag

**Version:** 1.0

## Quick Start

```bash
skill_run("sprint_planning", '{"issue_key": "AAP-12345"}')
```

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `project` | string | No | `AAP` | Jira project key |
| `sprint` | string | No | `""` | Sprint name to add issues to (optional) |
| `limit` | integer | No | `20` | Max issues to show |

## Process Flow

```mermaid
flowchart TD
    START([Start])
    STEP1[Step 1: Get Backlog]
    START --> STEP1
    STEP2[Step 2: Parse Backlog]
    STEP1 --> STEP2
    STEP3[Step 3: Get Blocked]
    STEP2 --> STEP3
    STEP4[Step 4: Parse Blocked]
    STEP3 --> STEP4
    STEP5[Step 5: Get Ready Issues]
    STEP4 --> STEP5
    STEP6[Step 6: Parse Ready]
    STEP5 --> STEP6
    STEP7[Step 7: Analyze Sprint Candidates]
    STEP6 --> STEP7
    STEP7 --> DONE([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style DONE fill:#10b981,stroke:#059669,color:#fff
```

## Detailed Steps

### Step 1: Get Backlog

**Description:** Get backlog issues

**Tool:** `jira_list_issues`

### Step 2: Parse Backlog

**Description:** Parse backlog issues

**Tool:** `compute`

### Step 3: Get Blocked

**Description:** Get blocked issues

**Tool:** `jira_list_blocked`

### Step 4: Parse Blocked

**Description:** Parse blocked issues

**Tool:** `compute`

### Step 5: Get Ready Issues

**Description:** Get issues ready for development

**Tool:** `jira_list_issues`

### Step 6: Parse Ready

**Description:** Parse ready issues

**Tool:** `compute`

### Step 7: Analyze Sprint Candidates

**Description:** Identify best candidates for sprint

**Tool:** `compute`


## MCP Tools Used (2 total)

- `jira_list_blocked`
- `jira_list_issues`

## Related Skills

_(To be determined based on skill relationships)_
