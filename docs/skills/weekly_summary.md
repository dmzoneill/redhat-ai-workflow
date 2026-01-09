# ⚡ weekly_summary

> Generate a summary of work from session logs

## Overview

Generate a summary of work from session logs.

Aggregates session logs from the past week (or specified period)
and provides a summary of:
- Issues worked on
- MRs created/reviewed
- Deployments and debugging sessions
- Patterns learned

Useful for weekly reports or sprint reviews.

**Version:** 1.1

## Quick Start

```bash
skill_run("weekly_summary", '{"issue_key": "AAP-12345"}')
```

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `days` | integer | No | `7` | Number of days to look back (default: 7) |
| `format` | string | No | `markdown` | Output format: 'markdown' or 'slack' |
| `repo` | string | No | `automation-analytics-backend` | Repository to get commit history from |
| `slack_format` | boolean | No | `False` | Use Slack link format |

## Process Flow

```mermaid
flowchart TD
    START([Start])
    STEP1[Step 1: Init Autoheal]
    START --> STEP1
    STEP2[Step 2: Get Recent Commits]
    STEP1 --> STEP2
    STEP3[Step 3: Get My Jira Issues]
    STEP2 --> STEP3
    STEP4[Step 4: Get My Mrs]
    STEP3 --> STEP4
    STEP5[Step 5: Get Recent Releases]
    STEP4 --> STEP5
    STEP6[Step 6: Get Recent Images]
    STEP5 --> STEP6
    STEP7[Step 7: Search Slack Discussions]
    STEP6 --> STEP7
    STEP8[Step 8: Parse Slack Discussions]
    STEP7 --> STEP8
    STEP9[Step 9: Get Session Logs]
    STEP8 --> STEP9
    STEP10[Step 10: Load Current Work]
    STEP9 --> STEP10
    STEP11[Step 11: Parse External Data]
    STEP10 --> STEP11
    STEP12[Step 12: Analyze Logs]
    STEP11 --> STEP12
    STEP13[Step 13: Format Summary]
    STEP12 --> STEP13
    STEP13 --> DONE([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style DONE fill:#10b981,stroke:#059669,color:#fff
```

## Detailed Steps

### Step 1: Init Autoheal

**Description:** Initialize failure tracking

**Tool:** `compute`

### Step 2: Get Recent Commits

**Description:** Get commits from the past week

**Tool:** `git_log`

### Step 3: Get My Jira Issues

**Description:** Get my recently updated Jira issues

**Tool:** `jira_my_issues`

### Step 4: Get My Mrs

**Description:** Get my recent merge requests

**Tool:** `gitlab_mr_list`

### Step 5: Get Recent Releases

**Description:** Get recent Konflux releases

**Tool:** `konflux_list_releases`

### Step 6: Get Recent Images

**Description:** Get recent image tags from Quay

**Tool:** `quay_list_aa_tags`

### Step 7: Search Slack Discussions

**Description:** Search Slack for relevant team discussions

**Tool:** `slack_search_messages`

### Step 8: Parse Slack Discussions

**Description:** Parse Slack discussions

**Tool:** `compute`

### Step 9: Get Session Logs

**Description:** Read session logs from memory directory

**Tool:** `compute`

### Step 10: Load Current Work

**Description:** Load current work state

**Tool:** `memory_read`

### Step 11: Parse External Data

**Description:** Parse data from git, jira, gitlab, konflux

**Tool:** `compute`

### Step 12: Analyze Logs

**Description:** Analyze session logs for summary

**Tool:** `compute`

### Step 13: Format Summary

**Description:** Format summary for output

**Tool:** `compute`


## MCP Tools Used (7 total)

- `git_log`
- `gitlab_mr_list`
- `jira_my_issues`
- `konflux_list_releases`
- `memory_read`
- `quay_list_aa_tags`
- `slack_search_messages`

## Related Skills

_(To be determined based on skill relationships)_
