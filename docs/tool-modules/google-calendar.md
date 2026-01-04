# 📅 google-calendar

> Calendar and meeting management

## Overview

The `aa-google-calendar` module provides tools for Google Calendar integration including event creation, availability checking, and meeting scheduling.

## Tool Count

**6 tools**

## Tools

| Tool | Description |
|------|-------------|
| `google_calendar_list_events` | List upcoming events |
| `google_calendar_create_event` | Create calendar event |
| `google_calendar_check_availability` | Check free/busy |
| `google_calendar_check_mutual_availability` | Find mutual free time |
| `google_calendar_schedule_meeting` | Smart meeting scheduler |
| `google_calendar_find_meeting` | Find existing meeting |

## Features

### Meeting Window

All meetings are scheduled within the configured window:
- **Time:** 15:00-19:00 Irish time
- **Days:** Monday-Friday only
- **Timezone:** Europe/Dublin

### Duplicate Prevention

Before creating meetings, checks for existing:
- Same MR ID or Jira key
- Same attendee
- Within last 7 days

### Google Meet Integration

Automatically creates Google Meet link for virtual meetings.

## Usage Examples

### List Today's Events

```python
google_calendar_list_events(
    start_date="today",
    end_date="today"
)
```

### Schedule Meeting

```python
google_calendar_schedule_meeting(
    attendee_email="bthomas@redhat.com",
    subject="MR !456 Review Discussion",
    duration_minutes=30,
    mr_id=456  # For duplicate check
)
```

### Check Availability

```python
google_calendar_check_mutual_availability(
    attendee_email="jsmith@redhat.com",
    date="2025-01-20"
)
```

## OAuth Setup

1. Create Google Cloud project
2. Enable Calendar API
3. Create OAuth credentials
4. Run `/google-reauth` command
5. Token saved to `~/.aa-google-token.json`

## Loaded By

- [👨‍💻 Developer Persona](../personas/developer.md)

## Related Skills

- [coffee](../skills/coffee.md) - Shows today's calendar
- [beer](../skills/beer.md) - Shows tomorrow's schedule
- [check_mr_feedback](../skills/check_mr_feedback.md) - Schedules review meetings
