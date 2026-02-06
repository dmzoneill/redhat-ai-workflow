---
name: attach-session-to-jira
description: "Attach the current AI session context to a Jira issue as a formatted comment."
arguments:
  - name: issue_key
    required: true
  - name: session_id
  - name: include_transcript
---
# Attach Session To Jira

Attach the current AI session context to a Jira issue as a formatted comment.

## Instructions

```text
skill_run("attach_session_to_jira", '{"issue_key": "$ISSUE_KEY", "session_id": "", "include_transcript": ""}')
```

## What It Does

Attach the current AI session context to a Jira issue as a formatted comment.

This skill extracts conversation history, tool calls, and metadata from the
current Cursor session and posts it to Jira. Useful for:

- **Investigation**: Team members can see what was discussed and done
- **Audit Trail**: Document AI-assisted work on issues
- **Handoff**: Share context when passing work to another developer
- **Debugging**: Review what the AI did when troubleshooting

The Jira comment includes:
- Session metadata (ID, persona, project, branch, duration)
- Summary statistics (messages, tool calls, code references)
- Key actions extracted from tool results
- Related issue keys mentioned in conversation
- Optional: Full conversation transcript (collapsible)

Uses MCP tools: jira_attach_session, session_info

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `issue_key` | Jira issue key to attach context to (e.g., AAP-12345) | Yes |
| `session_id` | Session ID to export. If empty, uses the active session. | No |
| `include_transcript` | Include full conversation transcript (collapsible in Jira) | No |
