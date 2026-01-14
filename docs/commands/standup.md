# /standup

> **Description:** Generate your daily standup summary from recent activity.

## Overview

**Description:** Generate your daily standup summary from recent activity.

**Underlying Skill:** `standup_summary`

This command is a wrapper that calls the `standup_summary` skill. For detailed process information, see [skills/standup_summary.md](../skills/standup_summary.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `days` | No | - |

## Usage

### Examples

```bash
skill_run("standup_summary")
```

```bash
skill_run("standup_summary", '{"days": 2}')
  ```text
- `repo`: Specific repository path
```
  skill_run("standup_summary", '{"repo_name": "automation-analytics-backend"}')
  ```text
- `issue_key`: Focus on a specific Jira issue
```
  skill_run("standup_summary", '{"issue_key": "AAP-12345"}')
  ```text

**What it generates:**

### ✅ What I Did
- Recent commits with links to Jira issues
- Issues closed (moved to Done)
- PRs reviewed

### 🔄 What I'm Working On
- Issues in "In Progress" or "In Review" status
- Open MRs

### 🚧 Blockers
- (Manual input - skill prompts if needed)

**Example Output:**
```

## Process Flow

This command invokes the `standup_summary` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /standup]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call standup_summary skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```bash

For detailed step-by-step process, see the [standup_summary skill documentation](../skills/standup_summary.md).

## Details

## ✅ What I Did
- Recent commits with links to Jira issues
- Issues closed (moved to Done)
- PRs reviewed

#

## 🔄 What I'm Working On
- Issues in "In Progress" or "In Review" status
- Open MRs

#

## 🚧 Blockers
- (Manual input - skill prompts if needed)

**Example Output:**
```

## 📋 Standup Summary
**Date:** 2025-12-24
**Author:** Dave O'Neill

#

## ✅ What I Did
**Commits:** 5
- `a1b2c3d` AAP-12345 - feat: Add billing integration
- `e4f5g6h` AAP-12346 - fix: Handle null response
...

#

## 🔄 What I'm Working On
- [AAP-12345] Billing integration feature
- [AAP-12347] Performance optimization

#

## 🚧 Blockers
- None
```

**Quick aliases:**
- `/standup` - Yesterday's summary (default)
- `/standup 3` - Last 3 days (for Monday standups)


## Related Commands

_(To be determined based on command relationships)_
