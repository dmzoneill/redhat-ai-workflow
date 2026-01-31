---
name: slack-daemon-control
description: Control the autonomous Slack daemon via D-Bus IPC
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: slack_daemon_control.yaml
  executable: "true"
---

# slack_daemon_control

Control the autonomous Slack daemon via D-Bus IPC.

Actions:
- start: Launch daemon in background with nohup
- stop: Gracefully shutdown the daemon
- status: Get daemon status and stats
- pending: List messages awaiting approval
- approve <id>: Approve and send a pending message
- approve_all: Approve all pending messages
- reject <id>: Reject a pending message
- history: Get message history with filters
- send: Send a direct message to Slack
- reload: Reload configuration

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("slack_daemon_control", '{
  "action": "example-action",
  "message_id": "example-message_id",
  "target": "example-target",
  "channel": "example-channel",
  "message": "example-message",
  "thread": "example-thread",
  "limit": 50,
  "filter_channel": "example-filter_channel",
  "filter_user": "example-filter_user",
  "filter_status": "example-filter_status",
  "enable_llm": false,
  "verbose": false
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Search for code related to Slack daemon**
2. **Parse daemon code search results**
3. **Validate the action and required parameters**
4. **Execute the daemon control action**
5. **Log daemon action to session**
6. **Track daemon state in memory**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `action` | string | Yes | `-` | Action to perform: start, stop, status, pending, approve, approve_all, reject, history, send, reload |
| `message_id` | string | No | `-` | Message ID for approve/reject actions |
| `target` | string | No | `-` | Target for send action: Channel (C123), User ID (U123), or @username |
| `channel` | string | No | `-` | Alias for target (deprecated, use target instead) |
| `message` | string | No | `-` | Message text for send action |
| `thread` | string | No | `-` | Thread timestamp for send action |
| `limit` | integer | No | `50` | Limit for history query (default: 50) |
| `filter_channel` | string | No | `-` | Channel ID filter for history |
| `filter_user` | string | No | `-` | User ID filter for history |
| `filter_status` | string | No | `-` | Status filter for history (pending, sent, skipped, etc.) |
| `enable_llm` | boolean | No | `false` | Enable LLM for start action |
| `verbose` | boolean | No | `false` | Enable verbose output for start action |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the slack_daemon_control skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("slack_daemon_control", '{
  "action": "example-action",
  "message_id": "example-message_id",
  "target": "example-target",
  "channel": "example-channel",
  "message": "example-message",
  "thread": "example-thread",
  "limit": 50,
  "filter_channel": "example-filter_channel",
  "filter_user": "example-filter_user",
  "filter_status": "example-filter_status",
  "enable_llm": false,
  "verbose": false
}')
```

### Via Command (if configured)

```
/slack-daemon-control
```

## MCP Tools Used

- `code_search`
- `memory_session_log`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/slack_daemon_control.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/slack_daemon_control.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
