# Check MR Feedback

Check your open Merge Requests for comments awaiting your response.

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
```

## Meeting Requests

If a reviewer requests a meeting, you can create a Google Calendar invite:

```
google_calendar_quick_meeting(
  title="MR !1445 Race Condition Discussion",
  attendee_email="bthomass@redhat.com",
  when="tomorrow 10:00",
  duration_minutes=30
)
```

First, check Google Calendar setup:
```
google_calendar_status()
```
