# /check-feedback

> Check your open Merge Requests for comments awaiting your response.

## Overview

Check your open Merge Requests for comments awaiting your response.

**Underlying Skill:** `check_mr_feedback`

This command is a wrapper that calls the `check_mr_feedback` skill. For detailed process information, see [skills/check_mr_feedback.md](../skills/check_mr_feedback.md).

## Arguments

No arguments required.

## Usage

### Examples

```bash
skill_run("check_mr_feedback", '{}')
```

```bash
cd ~/src/automation-analytics-backend
for mr in $(glab mr list --author=@me -R automation-analytics/automation-analytics-backend | grep -oP '!\d+' | tr -d '!'); do
  echo "=== MR !$mr ==="
  glab mr view $mr --comments | grep -A5 -E "^[a-zA-Z].*commented" | grep -v "group_10571_bot\|Konflux\|Starting Pipelinerun"
done
```

```bash
google_calendar_quick_meeting(
  title="MR !1445 Race Condition Discussion",
  attendee_email="bthomass@redhat.com",
  when="tomorrow 10:00",
  duration_minutes=30
)
```

## Process Flow

This command invokes the `check_mr_feedback` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /check-feedback]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call check_mr_feedback skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [check_mr_feedback skill documentation](../skills/check_mr_feedback.md).

## Details

## Instructions

Run the check_mr_feedback skill to scan your open MRs for:
- Human reviewer comments (filters out bot/CI comments)
- Meeting requests
- Code change requests
- Questions requiring answers

```
skill_run("check_mr_feedback", '{}')
```

Or run manually with glab:

```bash
cd ~/src/automation-analytics-backend
for mr in $(glab mr list --author=@me -R automation-analytics/automation-analytics-backend | grep -oP '!\d+' | tr -d '!'); do
  echo "=== MR !$mr ==="
  glab mr view $mr --comments | grep -A5 -E "^[a-zA-Z].*commented" | grep -v "group_10571_bot\|Konflux\|Starting Pipelinerun"
done
```text

## Meeting Requests

If a reviewer requests a meeting, you can create a Google Calendar invite:

```
google_calendar_quick_meeting(
  title="MR !1445 Race Condition Discussion",
  attendee_email="bthomass@redhat.com",
  when="tomorrow 10:00",
  duration_minutes=30
)
```text

First, check Google Calendar setup:
```
google_calendar_status()
```


## Related Commands

_(To be determined based on command relationships)_
