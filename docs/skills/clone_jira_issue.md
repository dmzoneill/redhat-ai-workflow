# ⚡ clone_jira_issue

> Clone a Jira issue for similar work

## Overview

Clone a Jira issue for similar work.

This skill:
- Clones an existing issue
- Links to the original
- Assigns to current user

Uses: jira_view_issue, jira_clone_issue, jira_add_link, jira_assign

**Version:** 1.0

## Quick Start

```bash
skill_run("clone_jira_issue", '{"issue_key": "AAP-12345"}')
```

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `issue_key` | string | ✅ Yes | `-` | Source issue key to clone (e.g., AAP-12345) |
| `new_summary` | string | No | `""` | New summary (optional, defaults to 'Clone of <original>') |
| `link_type` | string | No | `relates to` | Link type to original (relates to, blocks, is blocked by) |
| `assign_to_me` | boolean | No | `True` | Assign cloned issue to current user |

## Process Flow

```mermaid
flowchart TD
    START([Start])
    STEP1[Step 1: Get Source]
    START --> STEP1
    STEP2[Step 2: Parse Source]
    STEP1 --> STEP2
    STEP3[Step 3: Clone Issue]
    STEP2 --> STEP3
    STEP4[Step 4: Parse Clone]
    STEP3 --> STEP4
    STEP5[Step 5: Link Issues]
    STEP4 --> STEP5
    STEP6[Step 6: Assign Issue]
    STEP5 --> STEP6
    STEP7[Step 7: Log Clone]
    STEP6 --> STEP7
    STEP7 --> DONE([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style DONE fill:#10b981,stroke:#059669,color:#fff
```

## Detailed Steps

### Step 1: Get Source

**Description:** Get source issue details

**Tool:** `jira_view_issue`

### Step 2: Parse Source

**Description:** Parse source issue

**Tool:** `compute`

### Step 3: Clone Issue

**Description:** Clone the issue

**Tool:** `jira_clone_issue`

**Condition:** `source_info.exists`

### Step 4: Parse Clone

**Description:** Parse clone result

**Tool:** `compute`

### Step 5: Link Issues

**Description:** Link clone to original

**Tool:** `jira_add_link`

**Condition:** `clone_result.success`

### Step 6: Assign Issue

**Description:** Assign to current user

**Tool:** `jira_assign`

**Condition:** `clone_result.success and inputs.assign_to_me`

### Step 7: Log Clone

**Description:** Log clone action

**Tool:** `memory_session_log`


## MCP Tools Used (5 total)

- `jira_add_link`
- `jira_assign`
- `jira_clone_issue`
- `jira_view_issue`
- `memory_session_log`

## Related Skills

_(To be determined based on skill relationships)_
