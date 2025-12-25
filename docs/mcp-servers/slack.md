# 💬 slack

> Slack messaging and automation

## Overview

The `aa-slack` module provides tools for Slack integration including message handling, reactions, and channel management.

## Tool Count

**13 tools**

## Tools

### Message Operations

| Tool | Description |
|------|-------------|
| `slack_list_messages` | Get recent messages |
| `slack_send_message` | Send message (with threading) |
| `slack_search_messages` | Search Slack messages |
| `slack_add_reaction` | Add emoji reaction |

### Pending Queue

| Tool | Description |
|------|-------------|
| `slack_get_pending` | Get messages awaiting response |
| `slack_mark_processed` | Mark message as handled |
| `slack_respond_and_mark` | Respond and mark in one step |

### User & Channel Info

| Tool | Description |
|------|-------------|
| `slack_get_user` | Resolve user ID to profile |
| `slack_list_channels` | List available channels |
| `slack_validate_session` | Check credentials |

### Listener Control

| Tool | Description |
|------|-------------|
| `slack_listener_start` | Start background listener |
| `slack_listener_stop` | Stop listener |
| `slack_listener_status` | Get listener stats |

## Usage Examples

### Send Message

```python
slack_send_message(
    channel="C12345678",
    text="📋 *AAP-12345* is now In Progress",
    thread_ts="1234567890.123456"  # Optional, for threading
)
```

### Get Pending Messages

```python
slack_get_pending(limit=10)
```

### Respond and Mark

```python
slack_respond_and_mark(
    message_id="C123_1234567890.123456",
    text="Here's the issue status..."
)
```

## Authentication

> ⚠️ Uses Slack's internal web API (not official Bot API)

Required credentials (from browser dev tools):
- `SLACK_XOXC_TOKEN` - Token from API requests
- `SLACK_D_COOKIE` - Session cookie

## Loaded By

- [💬 Slack Agent](../agents/slack.md)

## Related Skills

- [investigate_slack_alert](../skills/investigate_slack_alert.md) - Handle alerts
- [slack_daemon_control](../skills/slack_daemon_control.md) - Daemon management

