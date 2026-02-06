# Config Daemon

> Configuration synchronization and change propagation

## Diagram

```mermaid
sequenceDiagram
    participant User as User/Tool
    participant Daemon as ConfigDaemon
    participant Watcher as File Watcher
    participant Config as config.json
    participant State as state.json
    participant DBus as D-Bus
    participant Clients as Other Daemons

    User->>Daemon: Update config
    Daemon->>Config: Write change
    Config-->>Watcher: File changed
    Watcher->>Daemon: on_config_change()
    Daemon->>Daemon: Validate config
    Daemon->>DBus: Emit ConfigChanged signal
    DBus->>Clients: ConfigChanged(section, data)
    Clients->>Clients: Reload affected config
```

## Class Structure

```mermaid
classDiagram
    class ConfigDaemon {
        +name: str = "config"
        +service_name: str
        -_config_watcher: FileWatcher
        -_state_watcher: FileWatcher
        -_validators: dict
        +startup() async
        +run_daemon() async
        +shutdown() async
        +get_config(section): dict
        +set_config(section, key, value)
        +validate_config(): list
        +get_service_stats() async
    }

    class ConfigValidator {
        +validate_section(section, data): list
        +validate_all(config): list
        +get_schema(section): dict
    }

    class ChangeNotifier {
        +emit_change(section, data)
        +subscribe(section, callback)
        +unsubscribe(section, callback)
    }

    ConfigDaemon --> ConfigValidator
    ConfigDaemon --> ChangeNotifier
```

## Change Propagation

```mermaid
flowchart TB
    subgraph Sources[Change Sources]
        USER[User Edit]
        MCP[MCP Tool]
        DBUS_CALL[D-Bus Call]
        FILE_EDIT[Direct File Edit]
    end

    subgraph Daemon[Config Daemon]
        WATCHER[File Watcher]
        VALIDATOR[Validator]
        NOTIFIER[Change Notifier]
    end

    subgraph Consumers[Config Consumers]
        CRON[Cron Daemon]
        SLACK[Slack Daemon]
        SPRINT[Sprint Daemon]
        MCP_SERVER[MCP Server]
    end

    USER --> FILE_EDIT
    MCP --> DBUS_CALL
    DBUS_CALL --> WATCHER
    FILE_EDIT --> WATCHER

    WATCHER --> VALIDATOR
    VALIDATOR --> NOTIFIER

    NOTIFIER --> CRON
    NOTIFIER --> SLACK
    NOTIFIER --> SPRINT
    NOTIFIER --> MCP_SERVER
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| ConfigDaemon | `services/config/daemon.py` | Main daemon class |
| ConfigValidator | Internal | Schema validation |
| ChangeNotifier | Internal | D-Bus signal emitter |

## D-Bus Methods

| Method | Description |
|--------|-------------|
| `get_config(section)` | Get config section |
| `set_config(section, key, value)` | Update config |
| `validate_config()` | Validate all config |
| `reload_config()` | Force reload |
| `get_schema(section)` | Get section schema |

## D-Bus Signals

| Signal | Parameters | Description |
|--------|------------|-------------|
| ConfigChanged | section, data | Config section changed |
| StateChanged | section, data | State section changed |
| ValidationError | section, errors | Validation failed |

## Config Sections

| Section | Watched By | Description |
|---------|------------|-------------|
| schedules | Cron Daemon | Job schedules |
| slack | Slack Daemon | Slack settings |
| sprint | Sprint Daemon | Sprint settings |
| agent | MCP Server | Agent settings |
| paths | All | Path configuration |

## Validation Schema

```json
{
  "schedules": {
    "type": "object",
    "properties": {
      "enabled": {"type": "boolean"},
      "timezone": {"type": "string"},
      "jobs": {"type": "array"}
    }
  }
}
```

## Related Diagrams

- [Daemon Overview](./daemon-overview.md)
- [Config System](../01-server/config-system.md)
- [State Manager](../01-server/state-manager.md)
