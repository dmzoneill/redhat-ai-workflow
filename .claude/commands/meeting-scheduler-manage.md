---
name: meeting-scheduler-manage
description: "Manage the automated meeting recording and transcription bot."
arguments:
  - name: action
    required: true
  - name: meeting_url
---
# Meeting Scheduler Manage

Manage the automated meeting recording and transcription bot.

## Instructions

```text
skill_run("meeting_scheduler_manage", '{"action": "$ACTION", "meeting_url": ""}')
```

## What It Does

Manage the automated meeting recording and transcription bot.

This skill handles:
- Listing scheduled meeting recordings
- Adding and removing meeting schedules
- Enabling/disabling scheduled recordings
- Starting and stopping all scheduled recordings
- Cleaning up expired recordings
- Managing meeting approval workflows
- Archiving old meeting data

Uses: meet_notes_list_calendars, meet_notes_add_calendar, meet_notes_remove_calendar,
meet_notes_start_scheduler, meet_notes_stop_scheduler, meet_notes_cleanup,
meet_notes_scheduler_status, meet_bot_approve_meeting

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `action` | Action to perform (list|add|remove|enable|start_all|stop_all|cleanup|status) | Yes |
| `meeting_url` | Meeting URL to add/remove from schedule | No |
