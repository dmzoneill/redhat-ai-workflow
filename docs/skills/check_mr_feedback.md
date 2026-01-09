# ⚡ check_mr_feedback

> Check your open Merge Requests for feedback that needs your attention

## Overview

Check your open Merge Requests for feedback that needs your attention.

Scans for:
- Human reviewer comments (filters out bot/CI comments)
- Meeting requests (can trigger Google Calendar invite)
- Code change requests
- Questions requiring answers
- Approval status

Optionally creates Google Meet invitations when meetings are requested.

Uses MCP tools: gitlab_mr_list, gitlab_mr_comments

**Version:** 1.2

## Quick Start

```bash
skill_run("check_mr_feedback", '{"issue_key": "AAP-12345"}')
```

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `project` | string | No | `automation-analytics/automation-analytics-backend` | GitLab project path |
| `create_meetings` | boolean | No | `False` | Automatically create Google Meet invites for meeting requests |
| `mr_ids` | array | No | `-` | Specific MR IDs to check (optional - defaults to all open MRs) |
| `slack_format` | boolean | No | `False` | Use Slack link format in summary |

## Process Flow

```mermaid
flowchart TD
    START([Start])
    STEP1[Step 1: Get My Mrs]
    START --> STEP1
    STEP2[Step 2: Parse Open Mrs]
    STEP1 --> STEP2
    STEP3[Step 3: Prepare Mr Ids]
    STEP2 --> STEP3
    STEP4[Step 4: Get Mr1 Comments]
    STEP3 --> STEP4
    STEP5[Step 5: Get Mr2 Comments]
    STEP4 --> STEP5
    STEP6[Step 6: Get Mr3 Comments]
    STEP5 --> STEP6
    STEP7[Step 7: Get Mr4 Comments]
    STEP6 --> STEP7
    STEP8[Step 8: Get Mr5 Comments]
    STEP7 --> STEP8
    STEP9[Step 9: Check Comments]
    STEP8 --> STEP9
    STEP10[Step 10: Check Existing Meetings]
    STEP9 --> STEP10
    STEP11[Step 11: Create Meeting Invites]
    STEP10 --> STEP11
    STEP12[Step 12: Format Summary]
    STEP11 --> STEP12
    STEP13[Step 13: Build Memory Context]
    STEP12 --> STEP13
    STEP14[Step 14: Log Session Feedback Check]
    STEP13 --> STEP14
    STEP15[Step 15: Create Followups For Feedback]
    STEP14 --> STEP15
    STEP15 --> DONE([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style DONE fill:#10b981,stroke:#059669,color:#fff
```

## Detailed Steps

### Step 1: Get My Mrs

**Description:** Fetch all open MRs authored by the current user

**Tool:** `gitlab_mr_list`

### Step 2: Parse Open Mrs

**Description:** Parse MR list output

**Tool:** `compute`

### Step 3: Prepare Mr Ids

**Description:** Prepare MR IDs for individual tool calls

**Tool:** `compute`

### Step 4: Get Mr1 Comments

**Description:** Get comments for first MR

**Tool:** `gitlab_mr_comments`

**Condition:** `{{ mr_data.ids|length > 0 }}`

### Step 5: Get Mr2 Comments

**Description:** Get comments for second MR

**Tool:** `gitlab_mr_comments`

**Condition:** `{{ mr_data.ids|length > 1 }}`

### Step 6: Get Mr3 Comments

**Description:** Get comments for third MR

**Tool:** `gitlab_mr_comments`

**Condition:** `{{ mr_data.ids|length > 2 }}`

### Step 7: Get Mr4 Comments

**Description:** Get comments for fourth MR

**Tool:** `gitlab_mr_comments`

**Condition:** `{{ mr_data.ids|length > 3 }}`

### Step 8: Get Mr5 Comments

**Description:** Get comments for fifth MR

**Tool:** `gitlab_mr_comments`

**Condition:** `{{ mr_data.ids|length > 4 }}`

### Step 9: Check Comments

**Description:** Analyze comments from all MRs using shared parsers

**Tool:** `compute`

### Step 10: Check Existing Meetings

**Description:** Check if meetings already exist for meeting requests

**Tool:** `compute`

**Condition:** `{{ feedback_analysis }}`

### Step 11: Create Meeting Invites

**Description:** Create Google Meet invitations for meeting requests

**Tool:** `compute`

**Condition:** `{{ inputs.create_meetings and feedback_with_calendar_check }}`

### Step 12: Format Summary

**Description:** Create human-readable summary

**Tool:** `compute`

### Step 13: Build Memory Context

**Description:** Build context for memory updates

**Tool:** `compute`

### Step 14: Log Session Feedback Check

**Description:** Log feedback check to session

**Tool:** `memory_session_log`

### Step 15: Create Followups For Feedback

**Description:** Create follow-up tasks for MRs needing response

**Tool:** `compute`

**Condition:** `feedback_analysis`


## MCP Tools Used (3 total)

- `gitlab_mr_comments`
- `gitlab_mr_list`
- `memory_session_log`

## Related Skills

_(To be determined based on skill relationships)_
