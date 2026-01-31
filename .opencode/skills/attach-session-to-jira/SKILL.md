---
name: attach-session-to-jira
description: Attach the current AI session context to a Jira issue as a formatted comment
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: attach_session_to_jira.yaml
  executable: "true"
---

# attach_session_to_jira

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

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("attach_session_to_jira", '{
  "issue_key": "example-issue_key",
  "session_id": "example-session_id",
  "include_transcript": false
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Validate Jira issue key format**
2. **Get current session information**
3. **Verify session exists**
4. **Attach session context to Jira issue**
5. **Log attachment to session log**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `issue_key` | string | Yes | `-` | Jira issue key to attach context to (e.g., AAP-12345) |
| `session_id` | string | No | `-` | Session ID to export. If empty, uses the active session. |
| `include_transcript` | boolean | No | `false` | Include full conversation transcript (collapsible in Jira) |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the attach_session_to_jira skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("attach_session_to_jira", '{
  "issue_key": "example-issue_key",
  "session_id": "example-session_id",
  "include_transcript": false
}')
```

### Via Command (if configured)

```
/attach-session-to-jira
```

## MCP Tools Used

- `jira_attach_session`
- `memory_session_log`
- `session_info`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/attach_session_to_jira.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/attach_session_to_jira.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
