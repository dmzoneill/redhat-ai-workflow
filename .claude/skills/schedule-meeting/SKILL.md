---
name: schedule-meeting
description: Schedule a meeting by finding mutual availability and creating calendar event
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: schedule_meeting.yaml
  executable: "true"
---

# schedule_meeting

Schedule a meeting by finding mutual availability and creating calendar event.

Uses Google Calendar API to:
1. Check your calendar status
2. Find free time slots
3. Check attendee availability (optional)
4. Create the meeting

Prerequisites:
- Google Calendar API credentials configured
- OAuth token for calendar access

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("schedule_meeting", '{
  "title": "example-title",
  "duration_minutes": 30,
  "attendees": "example-attendees",
  "preferred_time": "example-preferred_time",
  "days_ahead": 5,
  "description": "example-description"
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load meetings persona for Google Calendar tools**
2. **Search for code related to meeting scheduling**
3. **Parse meeting code search results**
4. **Initialize failure tracking**
5. **Get meeting/scheduling patterns from knowledge base**
6. **Parse meeting knowledge for scheduling context**
7. **Check for known calendar/meeting issues**
8. **Verify calendar API is accessible**
9. **Check if calendar is accessible**
10. **Get upcoming calendar events**
11. **Parse existing events to find busy times**
12. **Find available time slots**
13. **Parse available time slots**
14. **Check if attendees are free**
15. **Parse attendee availability**
16. **Select best meeting time**
17. **Create the calendar event**
18. **Try quick meeting if schedule_meeting failed**
19. **Log meeting scheduling**
20. **Track meeting scheduling for patterns**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `title` | string | Yes | `-` | Meeting title |
| `duration_minutes` | integer | No | `30` | Meeting duration in minutes |
| `attendees` | string | No | `-` | Comma-separated email addresses of attendees |
| `preferred_time` | string | No | `-` | Preferred time like 'tomorrow 2pm' or 'next Monday morning' |
| `days_ahead` | integer | No | `5` | How many days ahead to search for free slots |
| `description` | string | No | `-` | Meeting description/agenda |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the schedule_meeting skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("schedule_meeting", '{
  "title": "example-title",
  "duration_minutes": 30,
  "attendees": "example-attendees",
  "preferred_time": "example-preferred_time",
  "days_ahead": 5,
  "description": "example-description"
}')
```

### Via Command (if configured)

```
/schedule-meeting
```

## MCP Tools Used

- `code_search`
- `google_calendar_check_mutual_availability`
- `google_calendar_find_meeting`
- `google_calendar_list_events`
- `google_calendar_quick_meeting`
- `google_calendar_schedule_meeting`
- `google_calendar_status`
- `knowledge_query`
- `memory_session_log`
- `persona_load`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/schedule_meeting.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/schedule_meeting.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
