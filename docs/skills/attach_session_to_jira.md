# Skill: attach_session_to_jira

Attach AI session context to a Jira issue for investigation and audit trail.

## Overview

This skill exports the current Cursor AI session context (conversation history, tool calls, code changes) and posts it as a formatted comment on a Jira issue. This enables team members to investigate what was discussed and done during an AI-assisted work session.

## Use Cases

- **Investigation**: Team members can review what the AI discussed and recommended
- **Audit Trail**: Document AI-assisted work for compliance or review
- **Handoff**: Share context when passing work to another developer
- **Debugging**: Review AI actions when troubleshooting issues
- **Knowledge Sharing**: Capture problem-solving approaches for future reference

## Usage

### Basic Usage

```python
skill_run("attach_session_to_jira", '{"issue_key": "AAP-12345"}')
```

### With Full Transcript

```python
skill_run("attach_session_to_jira", '{"issue_key": "AAP-12345", "include_transcript": true}')
```

### Specific Session

```python
skill_run("attach_session_to_jira", '{"issue_key": "AAP-12345", "session_id": "abc123-def456"}')
```

## Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `issue_key` | string | Yes | - | Jira issue key (e.g., AAP-12345) |
| `session_id` | string | No | "" | Session ID to export. Uses active session if empty. |
| `include_transcript` | boolean | No | false | Include full conversation transcript (collapsible) |

## What Gets Attached

The Jira comment includes:

### Session Metadata
- Session ID (truncated for readability)
- Persona (developer, devops, incident, release)
- Project name
- Git branch (if set)
- Session start time and duration

### Summary Statistics
- Message counts (user vs assistant)
- Tool call count
- Code reference count
- Related issue keys mentioned

### Key Actions
- Extracted from tool results
- Shows what the AI actually did (commits, deployments, etc.)

### Optional: Full Transcript
- Complete conversation history
- Collapsible in Jira's UI (uses `{expand}` macro)
- Truncated to 5000 characters to avoid huge comments

## Jira Comment Format

The comment uses Jira wiki markup with:
- `{panel}` for the main container
- `{expand}` for collapsible transcript
- `{code}` for code blocks
- `{monospace}` for inline code

Example output:

```
{panel:title=AI Session Context|borderStyle=solid|borderColor=#0052CC}
*Session ID:* abc123...
*Persona:* developer
*Project:* automation-analytics-backend
*Branch:* {monospace}AAP-12345-fix-billing{monospace}
*Started:* 2026-01-27 10:30
*Duration:* ~45 minutes

h3. Summary
* *Messages:* 12 user, 15 assistant
* *Tool Calls:* 8
* *Code References:* 3
* *Related Issues:* AAP-12345, AAP-12346

h3. Key Actions
* Created branch AAP-12345-fix-billing
* Fixed race condition in billing handler
* Created MR !1459

{expand:Full Transcript}
{code}
[10:30:15] USER: Start work on AAP-12345
[10:30:20] ASSISTANT: I'll help you start work on AAP-12345...
...
{code}
{expand}
{panel}
```

## Related Tools

### `jira_attach_session`
The underlying MCP tool that does the actual attachment:
```python
jira_attach_session(issue_key="AAP-12345", include_transcript=True)
```

### `session_export_context`
Export session context locally (without posting to Jira):
```python
session_export_context()  # Markdown format
session_export_context(format="json")  # JSON format
```

## Error Handling

| Error | Cause | Solution |
|-------|-------|----------|
| Invalid issue key | Wrong format | Use format like AAP-12345 |
| No active session | Session not started | Run `session_start()` first |
| Failed to add comment | Jira auth/permission | Check JIRA_JPAT, verify issue access |
| No conversation content | New session or ID mismatch | Session may be too new |

## Best Practices

1. **Attach at End of Session**: Best to attach after completing work, when context is complete
2. **Use Meaningful Session Names**: `session_start(name="Fixing AAP-12345 billing bug")` makes comments more useful
3. **Include Transcript for Complex Issues**: For debugging or investigation, the full transcript is valuable
4. **Link Related Issues**: The skill auto-detects mentioned issue keys

## Technical Details

### Data Sources

The skill extracts data from:
1. **Cursor SQLite DB** (`~/.config/Cursor/User/globalStorage/state.vscdb`)
   - Chat messages (bubbles)
   - Tool results
   - Code chunks
   - Timestamps

2. **Session State** (`~/.config/aa-workflow/workspace_states.json`)
   - Persona
   - Project
   - Branch
   - Issue key

### Functions Used

- `get_cursor_chat_content()` - Extracts messages from Cursor DB
- `format_session_context_for_jira()` - Formats as Jira wiki markup
- `_jira_add_comment_impl()` - Posts to Jira via rh-issue CLI

## See Also

- [Session Management](../architecture/session-management.md)
- [Memory System](../architecture/memory-system.md)
- [Jira Tools](../tool-modules/README.md#jira)
