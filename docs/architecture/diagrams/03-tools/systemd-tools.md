# Systemd Tools

> aa_systemd module for systemd service and journal management

## Diagram

```mermaid
classDiagram
    class ServiceTools {
        +systemctl_status(unit): str
        +systemctl_start(unit): str
        +systemctl_stop(unit): str
        +systemctl_restart(unit): str
        +systemctl_enable(unit): str
        +systemctl_disable(unit): str
        +systemctl_is_active(unit): str
        +systemctl_is_enabled(unit): str
    }

    class ListTools {
        +systemctl_list_units(type): str
        +systemctl_list_unit_files(type): str
    }

    class JournalTools {
        +journalctl_logs(lines): str
        +journalctl_unit(unit, lines): str
        +journalctl_boot(boot): str
        +journalctl_follow(unit, lines): str
    }

    class SystemTools {
        +systemctl_daemon_reload(): str
        +hostnamectl_status(): str
        +timedatectl_status(): str
    }
```

## Tool Categories

```mermaid
graph TB
    subgraph Service[Service Management]
        STATUS[systemctl_status]
        START[systemctl_start]
        STOP[systemctl_stop]
        RESTART[systemctl_restart]
        ENABLE[systemctl_enable]
    end

    subgraph Journal[Log Viewing]
        LOGS[journalctl_logs]
        UNIT_LOGS[journalctl_unit]
        BOOT[journalctl_boot]
        FOLLOW[journalctl_follow]
    end

    subgraph System[System Info]
        RELOAD[daemon_reload]
        HOST[hostnamectl_status]
        TIME[timedatectl_status]
    end
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| tools_basic.py | `tool_modules/aa_systemd/src/` | All systemd tools |

## Tool Summary

### Service Tools

| Tool | Description |
|------|-------------|
| `systemctl_status` | Get service status |
| `systemctl_start` | Start a service |
| `systemctl_stop` | Stop a service |
| `systemctl_restart` | Restart a service |
| `systemctl_enable` | Enable service at boot |
| `systemctl_disable` | Disable service at boot |
| `systemctl_is_active` | Check if service is active |
| `systemctl_is_enabled` | Check if service is enabled |

### List Tools

| Tool | Description |
|------|-------------|
| `systemctl_list_units` | List active units |
| `systemctl_list_unit_files` | List unit files |

### Journal Tools

| Tool | Description |
|------|-------------|
| `journalctl_logs` | View recent journal logs |
| `journalctl_unit` | View logs for specific unit |
| `journalctl_boot` | View logs from current/previous boot |
| `journalctl_follow` | Get recent logs (tail-like) |

### System Tools

| Tool | Description |
|------|-------------|
| `systemctl_daemon_reload` | Reload systemd configuration |
| `hostnamectl_status` | Get hostname info |
| `timedatectl_status` | Get time/date info |

## Usage Examples

```python
# Check service status
result = await systemctl_status("bot-slack")

# Restart a daemon
result = await systemctl_restart("bot-slack")

# View service logs
result = await journalctl_unit("bot-slack", lines=50)

# Reload after editing unit files
result = await systemctl_daemon_reload()
```

## Bot Daemon Management

This module is commonly used to manage the workflow daemons:

| Daemon | Service Name |
|--------|--------------|
| Slack | bot-slack |
| Sprint | bot-sprint |
| Meet | bot-meet |
| Video | bot-video |
| Session | bot-session |
| Cron | bot-cron |
| Memory | bot-memory |
| Config | bot-config |
| SLOP | bot-slop |
| Stats | bot-stats |

## Related Diagrams

- [Daemon Overview](../02-services/daemon-overview.md)
- [Systemd Services](../09-deployment/systemd-services.md)
