# Slack Daemon Control

Control the autonomous Slack daemon via D-Bus IPC.

## Instructions

Control the Slack daemon:

```text
skill_run("slack_daemon_control", '{"action": "$ACTION"}')
```

## Actions

| Action | Description |
|--------|-------------|
| `start` | Start the daemon |
| `stop` | Stop the daemon |
| `status` | Check daemon status |
| `pending` | List pending messages awaiting approval |
| `approve` | Approve a specific message |
| `approve_all` | Approve all pending messages |
| `history` | Show message history |
| `send` | Send a message to channel/user |

## Examples

```bash
# Start the daemon
skill_run("slack_daemon_control", '{"action": "start"}')

# Check status
skill_run("slack_daemon_control", '{"action": "status"}')

# View pending messages
skill_run("slack_daemon_control", '{"action": "pending"}')

# Approve a specific message
skill_run("slack_daemon_control", '{"action": "approve", "message_id": "msg_123"}')

# Approve all pending
skill_run("slack_daemon_control", '{"action": "approve_all"}')

# Send a message to a channel
skill_run("slack_daemon_control", '{"action": "send", "target": "#team-channel", "message": "Build complete!"}')

# Send a DM
skill_run("slack_daemon_control", '{"action": "send", "target": "@username", "message": "PR ready for review"}')

# View history
skill_run("slack_daemon_control", '{"action": "history", "limit": 50}')

# Stop the daemon
skill_run("slack_daemon_control", '{"action": "stop"}')
```

## Notes

- Daemon runs in background monitoring Slack
- Messages require approval before sending (safety)
- Use `approve_all` carefully
