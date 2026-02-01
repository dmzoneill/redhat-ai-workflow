# AI Workflow Services

This folder contains all daemon/service implementations for the AI Workflow system.
Each service runs as a systemd user service and communicates via D-Bus.

## Structure

```
services/
  base/                     # Common daemon infrastructure
    daemon.py               # BaseDaemon class (CLI, signals, lifecycle)
    dbus.py                 # DaemonDBusBase (D-Bus interface)
    sleep_wake.py           # SleepWakeAwareDaemon (sleep/wake detection)

  cron/                     # Cron scheduler service
    daemon.py               # CronDaemon implementation

  meet/                     # Google Meet bot service
    daemon.py               # MeetDaemon implementation

  slack/                    # Slack persona service
    daemon.py               # SlackDaemon implementation
    dbus.py                 # Slack-specific D-Bus interface
    control.py              # CLI control interface
    path_setup.py           # Path configuration

  sprint/                   # Sprint automation bot
    daemon.py               # SprintDaemon implementation
    bot/                    # Sprint bot logic
      execution_tracer.py
      workflow_config.py

  video/                    # Virtual camera video generator
    daemon.py               # VideoDaemon implementation

  session/                  # Cursor session state watcher
    daemon.py               # SessionDaemon implementation

  config/                   # Configuration cache service
    daemon.py               # ConfigDaemon implementation

  memory/                   # Memory/state service
    daemon.py               # MemoryDaemon implementation

  stats/                    # Statistics service
    daemon.py               # StatsDaemon implementation

  extension_watcher/        # VS Code extension watcher
    daemon.py               # ExtensionWatcher implementation
```

## Running Services

Each service can be run as a Python module:

```bash
# Run directly
python -m services.cron --dbus
python -m services.slack --dbus
python -m services.meet --dbus

# Check status
python -m services.cron --status

# Stop running daemon
python -m services.cron --stop
```

## Systemd Integration

Services are designed to run as systemd user services:

```bash
# Install services
./scripts/install_services.sh

# Start services
systemctl --user start bot-cron bot-slack bot-meet

# Check status
systemctl --user status 'bot-*'

# View logs
journalctl --user -u bot-cron -f
```

## D-Bus Interface

All services expose a D-Bus interface for IPC:

| Service | D-Bus Name |
|---------|------------|
| cron | com.aiworkflow.BotCron |
| meet | com.aiworkflow.BotMeet |
| slack | com.aiworkflow.BotSlack |
| sprint | com.aiworkflow.BotSprint |
| video | com.aiworkflow.BotVideo |
| session | com.aiworkflow.BotSession |
| config | com.aiworkflow.BotConfig |
| memory | com.aiworkflow.Memory |
| stats | com.aiworkflow.BotStats |

## Base Classes

### BaseDaemon

Provides common daemon functionality:
- Single instance enforcement via lock files
- Standard CLI arguments (--status, --stop, --verbose, --dbus)
- Signal handling for graceful shutdown
- Logging configuration for systemd/journald

### DaemonDBusBase

Provides D-Bus interface:
- Standard properties (Running, Uptime, Stats)
- Standard methods (Ping, GetStatus, GetStats, Shutdown, HealthCheck)
- Custom method registration via `register_handler()`
- Signal emission (StatusChanged, Event)

### SleepWakeAwareDaemon

Mixin for sleep/wake awareness:
- Detects system sleep via systemd-logind D-Bus signals
- Fallback detection via time gap monitoring
- Automatic callback on wake (`on_system_wake()`)

## Creating a New Service

1. Create a new folder under `services/`:
   ```
   services/myservice/
     __init__.py
     __main__.py
     daemon.py
   ```

2. Implement the daemon class:
   ```python
   from services.base import BaseDaemon, DaemonDBusBase, SleepWakeAwareDaemon

   class MyDaemon(SleepWakeAwareDaemon, DaemonDBusBase, BaseDaemon):
       name = "myservice"
       description = "My Service Daemon"

       service_name = "com.aiworkflow.MyService"
       object_path = "/com/aiworkflow/MyService"
       interface_name = "com.aiworkflow.MyService"

       async def run_daemon(self):
           # Main daemon logic
           while not self._shutdown_event.is_set():
               await asyncio.sleep(1)

       async def get_service_stats(self) -> dict:
           return {"my_stat": 42}

       async def get_service_status(self) -> dict:
           return {"status": "running"}

       async def on_system_wake(self):
           # Called after system wakes from sleep
           pass
   ```

3. Add systemd service file in `systemd/bot-myservice.service`

4. Update `scripts/install_services.sh` to include the new service
