# /coffee

> Your daily standup assistant - everything you need at the start of your work day.

## Overview

Your daily standup assistant - everything you need at the start of your work day.

**Underlying Skill:** `coffee`

This command is a wrapper that calls the `coffee` skill. For detailed process information, see [skills/coffee.md](../skills/coffee.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `days_back` | No | - |

## Usage

### Examples

```bash
skill_run("coffee")
```

```bash
# Look back further in history
skill_run("coffee", '{"days_back": 7}')

# Full email processing (mark read & archive)
skill_run("coffee", '{"full_email_scan": true, "auto_archive_email": true}')
```

```bash
/setup-gmail
```

## Process Flow

This command invokes the `coffee` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /coffee]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call coffee skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [coffee skill documentation](../skills/coffee.md).

## Details

## Instructions

Get your morning briefing:

```
skill_run("coffee")
```

## What You'll Get

| Section | Description |
|---------|-------------|
| 📅 Calendar | Today's meetings with Meet links |
| 📧 Email | Unread count, categorized (people vs newsletters) |
| 🔀 PRs | Your open PRs, feedback waiting, failed pipelines |
| 👀 Reviews | PRs assigned to you for review |
| 🧪 Ephemeral | Your active test environments with expiry times |
| 📝 Yesterday | Your commits from yesterday (for standup) |
| 📋 Jira | Sprint activity for the day/week |
| 🚀 Merges | Recently merged code in aa-backend |
| 🚨 Alerts | Any firing Prometheus alerts |
| 🎯 Actions | Smart suggestions based on all the above |

## Options

```bash
# Look back further in history
skill_run("coffee", '{"days_back": 7}')

# Full email processing (mark read & archive)
skill_run("coffee", '{"full_email_scan": true, "auto_archive_email": true}')
```text

## First Time Setup

If email isn't working, you need to enable Gmail API:

```
/setup-gmail
```text

This adds Gmail scopes to your existing Google OAuth.

## Quick Summary

Just want the highlights without the full briefing?

```
skill_run("coffee", '{"days_back": 1}')
```


## Related Commands

_(To be determined based on command relationships)_
