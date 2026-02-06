---
name: sync-pto-calendar
description: "Sync your Workday PTO with Google Calendar by declining meetings on PTO days."
arguments:
  - name: dry_run
  - name: days_ahead
  - name: decline_message
  - name: skip_all_day
  - name: skip_organizer_self
  - name: workday_url
---
# Sync Pto Calendar

Sync your Workday PTO with Google Calendar by declining meetings on PTO days.

## Instructions

```text
skill_run("sync_pto_calendar", '{"dry_run": "", "days_ahead": "", "decline_message": "", "skip_all_day": "", "skip_organizer_self": "", "workday_url": ""}')
```

## What It Does

Sync your Workday PTO with Google Calendar by declining meetings on PTO days.

This skill:
1. Opens Workday and navigates to your Time Off page
2. Extracts approved PTO dates
3. Finds meetings on those days in your Google Calendar
4. Declines meetings with an automatic "On PTO" message

**Prerequisites:**
- Google Calendar API configured (OAuth token)
- Workday SSO access (uses browser automation)

**Usage:**
- Run with `dry_run: true` first to preview what would be declined
- Use `days_ahead` to limit how far into the future to check
- Use `decline_message` to customize the decline response

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `dry_run` | Preview mode - show what would be declined without actually declining (default: True) | No |
| `days_ahead` | How many days ahead to check for PTO (default: 90) (default: 90) | No |
| `decline_message` | Message to include when declining meetings (default: I'll be out of office on PTO. Please reschedule if needed.) | No |
| `skip_all_day` | Skip all-day events (holidays, etc.) - only decline timed meetings | No |
| `skip_organizer_self` | Skip meetings you organized (you may want to cancel these manually) (default: True) | No |
| `workday_url` | Workday home URL (default: https://wd5.myworkday.com/redhat/d/home.htmld) | No |
