# Base Daemon

> Foundation classes for all AI Workflow daemons

## Diagram

```mermaid
classDiagram
    class BaseDaemon {
        <<abstract>>
        +name: str
        +description: str
        +verbose: bool
        +enable_dbus: bool
        -_shutdown_event: Event
        -_single_instance: SingleInstance
        -_watchdog_task: Task
        -_watchdog_healthy: bool
        +run_daemon()* async
        +startup() async
        +shutdown() async
        +request_shutdown()
        +run()
        +main() classmethod
        +configure_logging() classmethod
        +create_argument_parser() classmethod
        +handle_status() classmethod
        +handle_stop() classmethod
        -_setup_signal_handlers()
        -_watchdog_loop() async
        -_verify_health() async
        -_run() async
    }

    class SingleInstance {
        +name: str
        +lock_dir: Path
        -_lock_file: file
        -_acquired: bool
        +lock_path: Path
        +pid_path: Path
        +acquire(): bool
        +release()
        +get_running_pid(): int
        +is_acquired: bool
    }

    class DaemonDBusBase {
        +service_name: str
        +object_path: str
        +interface_name: str
        -_bus: MessageBus
        -_dbus_interface: Interface
        -_handlers: dict
        +start_dbus() async
        +stop_dbus() async
        +register_handler(name, func)
        +get_base_stats(): dict
        +get_service_stats() async
        +get_service_status() async
        +health_check() async
    }

    class SleepWakeAwareDaemon {
        -_sleep_monitor_task: Task
        +start_sleep_monitor() async
        +stop_sleep_monitor() async
        +on_system_wake() async
        -_monitor_sleep_wake() async
    }

    class AIRouter {
        +route_to_claude(prompt): str
        +route_to_ollama(prompt): str
        +get_best_model(task): str
    }

    BaseDaemon --> SingleInstance : uses
    DaemonDBusBase --|> BaseDaemon : mixin
    SleepWakeAwareDaemon --|> BaseDaemon : mixin
    BaseDaemon --> AIRouter : optional
```

## Daemon Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Init: main() called

    Init --> AcquireLock: Create daemon instance
    AcquireLock --> Running: Lock acquired
    AcquireLock --> Exit: Another instance running

    state Running {
        [*] --> Startup
        Startup --> DBusStart: enable_dbus=true
        DBusStart --> Ready: D-Bus started
        Startup --> Ready: enable_dbus=false

        Ready --> Notify: sd_notify READY=1
        Notify --> WatchdogLoop: Start watchdog
        WatchdogLoop --> MainLoop: run_daemon()

        MainLoop --> MainLoop: Process events
        MainLoop --> ShutdownRequested: Signal received
    }

    ShutdownRequested --> Shutdown: _shutdown_event.set()
    Shutdown --> DBusStop: Stop D-Bus
    DBusStop --> Cleanup: shutdown()
    Cleanup --> ReleaseLock: Release lock
    ReleaseLock --> Exit: Clean exit

    Exit --> [*]
```

## Signal Handling

```mermaid
sequenceDiagram
    participant OS as Operating System
    participant Daemon as BaseDaemon
    participant Event as _shutdown_event
    participant Loop as run_daemon()

    OS->>Daemon: SIGTERM/SIGINT
    Daemon->>Daemon: signal_handler()
    Daemon->>Event: set()
    Event-->>Loop: Wake up
    Loop->>Daemon: Exit run_daemon()
    Daemon->>Daemon: shutdown()
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| BaseDaemon | `services/base/daemon.py` | Abstract base class |
| SingleInstance | `services/base/daemon.py` | Lock file management |
| DaemonDBusBase | `services/base/dbus.py` | D-Bus IPC mixin |
| SleepWakeAwareDaemon | `services/base/sleep_wake.py` | Sleep/wake handling |
| AIRouter | `services/base/ai_router.py` | AI model routing |
| sd_notify | `services/base/daemon.py` | Systemd notification |
| get_watchdog_interval | `services/base/daemon.py` | Watchdog timing |

## CLI Arguments

| Argument | Description |
|----------|-------------|
| `--status` | Check if daemon is running |
| `--stop` | Stop running daemon |
| `-v, --verbose` | Enable verbose logging |
| `--dbus` | Enable D-Bus IPC (default) |
| `--no-dbus` | Disable D-Bus IPC |

## Inheritance Order (MRO)

```python
# CORRECT order - mixins before BaseDaemon
class MyDaemon(SleepWakeAwareDaemon, DaemonDBusBase, BaseDaemon):
    pass

# INCORRECT - will break method resolution
class MyDaemon(BaseDaemon, DaemonDBusBase, SleepWakeAwareDaemon):
    pass
```

## Related Diagrams

- [Daemon Overview](./daemon-overview.md)
- [D-Bus Architecture](../09-deployment/dbus-architecture.md)
- [Systemd Services](../09-deployment/systemd-services.md)
