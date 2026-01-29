# 💬 monitor_jira_comments

> Daily monitoring of Jira comments on sprint issues with automatic responses

## Overview

The `monitor_jira_comments` skill runs daily to check your active sprint issues for new comments. It detects questions from team members, generates natural responses, and optionally notifies you via Slack. All responses are written in natural language - the skill never mentions "bot" or "automated."

This skill is designed to be scheduled via cron, running at 9 AM on weekdays to catch overnight comments.

## Quick Start

```text
skill_run("monitor_jira_comments", '{}')
```

Or with custom settings:

```text
skill_run("monitor_jira_comments", '{"hours_lookback": 48, "dry_run": true}')
```

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `jira_project` | string | No | `"AAP"` | Jira project key |
| `hours_lookback` | integer | No | `24` | How many hours back to check for new comments |
| `notify_user` | boolean | No | `true` | Whether to notify user via Slack |
| `slack_channel` | string | No | `""` | Slack channel for notifications (uses team default if empty) |
| `dry_run` | boolean | No | `false` | If true, don't post responses, just report what would be done |

## What It Does

1. **Load Developer Persona** - Ensures Jira tools are available
2. **Search Sprint Issues** - Finds all open sprint issues assigned to you
3. **Parse Issues** - Extracts issue keys from search results
4. **For Each Issue**:
   - **Get Details** - Fetches full issue with comments
   - **Analyze Comments** - Looks for questions using pattern matching
   - **Filter Own Comments** - Skips comments that appear to be your own responses
   - **Prepare Response** - Generates natural language response based on question type
   - **Post Response** - Adds comment to issue (unless dry run)
   - **Notify Slack** - Sends notification about the interaction
   - **Log Timeline** - Records the comment response event
5. **Compile Summary** - Generates statistics report
6. **Log Session** - Records monitoring run to memory

## Question Detection Patterns

The skill looks for these patterns in comments:

| Pattern | Example |
|---------|---------|
| Question marks | "Can you explain this?" |
| "can you", "could you", "would you" | "Could you add more tests?" |
| "please clarify" | "Please clarify the requirements" |
| "what about" | "What about error handling?" |
| "how do" | "How do we deploy this?" |
| "when will" | "When will this be ready?" |
| "any update" | "Any update on this?" |
| "status on" | "Status on the implementation?" |
| "thoughts on" | "Thoughts on this approach?" |
| "feedback" | "Need feedback on the design" |

## Response Templates

Responses are generated based on the type of question detected:

| Question Type | Example Response |
|---------------|------------------|
| Status/Update | "Thanks for checking in! I'm actively working on this and making good progress. I'll have an update soon with more details on the implementation." |
| Clarification | "Good question - let me clarify. I'll add more context to the description and follow up with specific details shortly." |
| Timeline | "I'm targeting to have this ready for review soon. I'll update the issue with a more specific timeline once I've completed the initial implementation." |
| Feedback | "Thanks for the input! I'll review and incorporate your feedback. Let me take a closer look and get back to you." |
| General | "Thanks for reaching out! I've seen your message and will respond with more details shortly." |

## Example Usage

### Default Check (Last 24 Hours)

```python
skill_run("monitor_jira_comments", '{}')
```

### Extended Lookback

```python
skill_run("monitor_jira_comments", '{"hours_lookback": 72}')
```

### Dry Run (Preview Only)

```python
skill_run("monitor_jira_comments", '{"dry_run": true}')
```

### Without Slack Notifications

```python
skill_run("monitor_jira_comments", '{"notify_user": false}')
```

### Custom Slack Channel

```python
skill_run("monitor_jira_comments", '{"slack_channel": "my-private-channel"}')
```

## Example Output

```text
## 💬 Jira Comment Monitoring Summary

**Issues Checked:** 8
**Questions Found:** 2
**Responses Sent:** 2
**Notifications Sent:** 2

### Interactions

**AAP-12345** - Responded to 1 question
- Question: "Any update on when this will be ready?"
- Response: Status update provided

**AAP-12348** - Responded to 1 question
- Question: "Could you clarify the API contract?"
- Response: Clarification promised
```

## Outputs

| Output | Description |
|--------|-------------|
| `issues_checked` | Number of issues checked |
| `questions_found` | Number of questions detected |
| `responses_sent` | Number of responses posted |
| `notifications_sent` | Number of Slack notifications sent |

## MCP Tools Used

- `persona_load` - Load developer persona
- `jira_search` - Find sprint issues
- `jira_view_issue` - Get issue details with comments
- `jira_add_comment` - Post responses
- `skill_run` - Invoke `notify_team` skill for Slack
- `memory_append` - Log timeline events
- `memory_session_log` - Log monitoring run

## Scheduling

This skill is designed to be run via cron. Example schedule:

```text
# Run at 9 AM on weekdays
0 9 * * 1-5 skill_run("monitor_jira_comments", '{}')
```

## Related Skills

- [check_mr_feedback](./check_mr_feedback.md) - Check for MR comments
- [coffee](./coffee.md) - Morning briefing
- [notify_team](./notify_team.md) - Send Slack notifications
