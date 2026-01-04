# 💬 slack

> Slack messaging and automation

## Overview

The `aa-slack` module provides tools for Slack integration including message handling, channel management, team notifications, and background listening for autonomous responses.

## Tool Count

**15 tools**

## Tools

### Message Operations

| Tool | Description |
|------|-------------|
| `slack_list_messages` | Get recent messages from a channel |
| `slack_send_message` | Send message to channel/user (with threading) |
| `slack_search_messages` | Search Slack messages |
| `slack_add_reaction` | Add emoji reaction |

### Team & Channel Tools

| Tool | Description |
|------|-------------|
| `slack_get_channels` | Get configured channels (team, standup, alerts) |
| `slack_post_team` | Post to team channel (convenience wrapper) |

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

### Post to Team Channel

```python
# Easy way - uses configured team channel
slack_post_team(
    text="🚀 Release v1.2.3 deployed to production!"
)
```

### Send Message to Any Channel

```python
slack_send_message(
    target="C12345678",  # Channel ID, user ID, or @username
    text="📋 *AAP-12345* is now In Progress",
    thread_ts="1234567890.123456"  # Optional, for threading
)
```

### Get Configured Channels

```python
slack_get_channels()
# Returns:
# {
#   "channels": {
#     "team": {"id": "C089F16L30T", "name": "aa-api-team-test"},
#     "standup": {"id": "C089F16L30T", "name": "aa-api-team-test"}
#   },
#   "alert_channels": {...},
#   "team_channel_id": "C089F16L30T"
# }
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

## Configuration

Configure channels in `config.json`:

```json
{
  "slack": {
    "channels": {
      "team": {
        "id": "C089F16L30T",
        "name": "aa-api-team-test",
        "description": "Team channel for notifications"
      },
      "standup": {
        "id": "C089F16L30T",
        "name": "aa-api-team-test",
        "description": "Daily standup summaries"
      }
    },
    "user_mapping": {
      "gitlab_username": "U_SLACK_USER_ID"
    }
  }
}
```

## Authentication

> ⚠️ Uses Slack's internal web API (not official Bot API)

Required credentials in `config.json` (from browser dev tools):

```json
{
  "slack": {
    "auth": {
      "xoxc_token": "xoxc-...",
      "d_cookie": "xoxd-...",
      "workspace_id": "E...",
      "host": "your-company.enterprise.slack.com"
    }
  }
}
```

## Loaded By

- [💬 Slack Persona](../personas/slack.md)

## Related Skills

- [investigate_slack_alert](../skills/investigate_slack_alert.md) - Handle alerts
- [slack_daemon_control](../skills/slack_daemon_control.md) - Daemon management
