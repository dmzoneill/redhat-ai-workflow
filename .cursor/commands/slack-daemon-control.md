# Slack Daemon Control

Control the Slack daemon service.

## Instructions

```text
skill_run("slack_daemon_control", '{"action": "$ACTION"}')
```

## What It Does

Controls the Slack agent daemon that monitors channels and responds to messages.

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `action` | Action: start, stop, restart, status | Yes |

## Examples

```bash
# Check status
skill_run("slack_daemon_control", '{"action": "status"}')

# Restart daemon
skill_run("slack_daemon_control", '{"action": "restart"}')

# Stop daemon
skill_run("slack_daemon_control", '{"action": "stop"}')
```
