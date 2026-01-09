# ⚡ check_my_prs

> Check your open MRs for feedback from reviewers

## Overview

Check your open MRs for feedback from reviewers.

Shows:
- MRs with unaddressed feedback (need your response)
- MRs awaiting review (no feedback yet)
- MRs ready to merge (approved)

Helps you respond to reviewer comments.

Resolves project from repo_name or issue_key if not explicitly provided.

**Version:** 1.2

## Quick Start

```bash
skill_run("check_my_prs", '{"issue_key": "AAP-12345"}')
```

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `project` | string | No | `""` | GitLab project path (resolved from repo_name if not provided) |
| `repo_name` | string | No | `-` | Repository name from config (e.g., 'automation-analytics-backend') |
| `show_approved` | boolean | No | `True` | Include approved MRs in output |
| `auto_merge` | boolean | No | `False` | Automatically merge approved MRs (asks first if false) |
| `auto_rebase` | boolean | No | `False` | Automatically rebase MRs with merge conflicts |
| `slack_format` | boolean | No | `False` | Use Slack link format in summary |

## Process Flow

```mermaid
flowchart TD
    START([Start])
    STEP1[Step 1: Init Autoheal]
    START --> STEP1
    STEP2[Step 2: Resolve Project]
    STEP1 --> STEP2
    STEP3[Step 3: Get Username]
    STEP2 --> STEP3
    STEP4[Step 4: List My Mrs]
    STEP3 --> STEP4
    STEP5[Step 5: Parse My Mrs]
    STEP4 --> STEP5
    STEP6[Step 6: Check First Mr]
    STEP5 --> STEP6
    STEP7[Step 7: Analyze First Mr]
    STEP6 --> STEP7
    STEP8[Step 8: Get Feedback Details]
    STEP7 --> STEP8
    STEP9[Step 9: Auto Rebase Mr]
    STEP8 --> STEP9
    STEP10[Step 10: Build Summary]
    STEP9 --> STEP10
    STEP11[Step 11: Update Summary With Merge]
    STEP10 --> STEP11
    STEP12[Step 12: Update Mr Status In Memory]
    STEP11 --> STEP12
    STEP13[Step 13: Log Check Prs]
    STEP12 --> STEP13
    STEP13 --> DONE([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style DONE fill:#10b981,stroke:#059669,color:#fff
```

## Detailed Steps

### Step 1: Init Autoheal

**Description:** Initialize failure tracking

**Tool:** `compute`

### Step 2: Resolve Project

**Description:** Determine which GitLab project to check

**Tool:** `compute`

### Step 3: Get Username

**Description:** Get current system username

**Tool:** `compute`

### Step 4: List My Mrs

**Description:** Fetch my open MRs from GitLab

**Tool:** `gitlab_mr_list`

### Step 5: Parse My Mrs

**Description:** Parse MR list using shared parser

**Tool:** `compute`

### Step 6: Check First Mr

**Description:** Get details of first MR

**Tool:** `gitlab_mr_view`

**Condition:** `len(my_mrs) > 0`

### Step 7: Analyze First Mr

**Description:** Analyze feedback status of first MR using shared parser

**Tool:** `compute`

**Condition:** `len(my_mrs) > 0 and first_mr_details`

### Step 8: Get Feedback Details

**Description:** Get detailed comments if MR needs response

**Tool:** `gitlab_mr_view`

**Condition:** `first_mr_status and first_mr_status.get('status') == 'needs_response'`

### Step 9: Auto Rebase Mr

**Description:** Automatically rebase MR with conflicts

**Tool:** `skill_run`

**Condition:** `inputs.auto_rebase and first_mr_status and first_mr_status.get('needs_rebase')`

### Step 10: Build Summary

**Description:** Compile status of all my MRs

**Tool:** `compute`

### Step 11: Update Summary With Merge

**Description:** Update summary if MR was merged

**Tool:** `compute`

**Condition:** `merge_result`

### Step 12: Update Mr Status In Memory

**Description:** Update open MRs in memory with current status

**Tool:** `compute`

**Condition:** `mr_statuses`

### Step 13: Log Check Prs

**Description:** Log PR check to session

**Tool:** `memory_session_log`


## MCP Tools Used (4 total)

- `gitlab_mr_list`
- `gitlab_mr_view`
- `memory_session_log`
- `skill_run`

## Related Skills

_(To be determined based on skill relationships)_
