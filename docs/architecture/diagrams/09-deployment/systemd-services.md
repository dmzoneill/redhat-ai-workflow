# Systemd Services

> Service management with systemd

## Diagram

```mermaid
graph TB
    subgraph Services[Systemd Services]
        SLACK[bot-slack.service]
        CRON[bot-cron.service]
        MEMORY[bot-memory.service]
        SESSION[bot-session.service]
        CONFIG[bot-config.service]
        SPRINT[bot-sprint.service]
        MEET[bot-meet.service]
        VIDEO[bot-video.service]
        SLOP[bot-slop.service]
        STATS[bot-stats.service]
    end

    subgraph Timers[Systemd Timers]
        INSCOPE_TIMER[inscope-token-refresh.timer]
    end

    subgraph Control[Service Control]
        SYSTEMCTL[systemctl --user]
        JOURNALCTL[journalctl --user]
    end

    Control --> Services
    Control --> Timers
```

## Service Dependencies

```mermaid
flowchart TB
    subgraph Core[Core Services]
        CONFIG[bot-config]
        MEMORY[bot-memory]
    end

    subgraph Dependent[Dependent Services]
        SLACK[bot-slack]
        CRON[bot-cron]
        SESSION[bot-session]
        SPRINT[bot-sprint]
    end

    subgraph Optional[Optional Services]
        MEET[bot-meet]
        VIDEO[bot-video]
        SLOP[bot-slop]
    end

    CONFIG --> Dependent
    MEMORY --> Dependent
    Dependent --> Optional
```

## Service Unit File

```ini
# systemd/bot-slack.service
[Unit]
Description=AI Workflow Slack Daemon
After=network.target dbus.service
Wants=bot-config.service bot-memory.service

[Service]
Type=notify
ExecStart=/usr/bin/python -m services.slack
Restart=on-failure
RestartSec=5
WatchdogSec=30

Environment=PYTHONPATH=/home/user/src/redhat-ai-workflow
WorkingDirectory=/home/user/src/redhat-ai-workflow

[Install]
WantedBy=default.target
```

## Service States

```mermaid
stateDiagram-v2
    [*] --> Inactive: Not started

    Inactive --> Starting: systemctl start
    Starting --> Running: Startup complete
    Starting --> Failed: Startup error

    Running --> Stopping: systemctl stop
    Running --> Failed: Runtime error
    Running --> Restarting: Watchdog timeout

    Stopping --> Inactive: Clean shutdown
    Restarting --> Starting: Restart triggered

    Failed --> Inactive: systemctl reset-failed
    Failed --> Starting: systemctl restart
```

## Management Commands

```bash
# Start service
systemctl --user start bot-slack

# Stop service
systemctl --user stop bot-slack

# Restart service
systemctl --user restart bot-slack

# Check status
systemctl --user status bot-slack

# View logs
journalctl --user -u bot-slack -f

# Enable at login
systemctl --user enable bot-slack

# List all bot services
systemctl --user list-units 'bot-*'
```

## Components

| Service | File | Description |
|---------|------|-------------|
| bot-slack | `systemd/bot-slack.service` | Slack daemon |
| bot-cron | `systemd/bot-cron.service` | Cron daemon |
| bot-memory | `systemd/bot-memory.service` | Memory daemon |
| bot-session | `systemd/bot-session.service` | Session daemon |

## Related Diagrams

- [Daemon Overview](../02-services/daemon-overview.md)
- [Base Daemon](../02-services/base-daemon.md)
- [CLI Interface](./cli-interface.md)
