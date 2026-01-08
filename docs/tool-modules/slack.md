# 💬 slack

> Slack messaging and automation

## Overview

The `aa_slack` module provides tools for Slack integration including message handling, channel management, team notifications, and background listening for autonomous responses.

## Tool Count

**10 tools**

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

### Automatic Extraction

```bash
pip install pycookiecheat
python scripts/get_slack_creds.py
```

### Manual Extraction

From Chrome DevTools while logged into Slack:
1. **d_cookie**: Application → Cookies → find `d` cookie
2. **xoxc_token**: Application → Local Storage → find `xoxc` value

### Configuration

Add to `config.json`:

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

### Token Refresh

Tokens expire periodically. Re-run `get_slack_creds.py` when you see auth errors.

## Alert Channels

Configure channels for automatic alert detection:

```json
{
  "slack": {
    "alert_channels": {
      "C089XXXXXX": {
        "name": "aleets",
        "environment": "stage"
      },
      "C089YYYYYY": {
        "name": "prod-alerts",
        "environment": "prod"
      }
    }
  }
}
```

The daemon will:
1. Monitor these channels for Prometheus/AlertManager messages
2. Detect `[FIRING]` alerts automatically
3. Run `investigate_slack_alert` skill
4. Post investigation findings back to the channel

## Running the Daemon

```bash
# Foreground
make slack-daemon

# Background with D-Bus control
make slack-daemon-bg
make slack-status
make slack-daemon-stop
```

See [Slack Persona](../personas/slack.md) for full installation guide.

## Loaded By

- [💬 Slack Persona](../personas/slack.md)

## Related Skills

- [investigate_slack_alert](../skills/investigate_slack_alert.md) - Handle alerts
- [slack_daemon_control](../skills/slack_daemon_control.md) - Daemon management
