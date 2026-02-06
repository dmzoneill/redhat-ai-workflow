# D-Bus Communication

> Inter-process communication between daemons

## Diagram

```mermaid
graph TB
    subgraph Daemons[Daemon Processes]
        SLACK[SlackDaemon]
        CRON[CronDaemon]
        MEMORY[MemoryDaemon]
        SESSION[SessionDaemon]
        CONFIG[ConfigDaemon]
    end

    subgraph Bus[D-Bus Session Bus]
        DBUS[org.redhat.workflow.*]
    end

    subgraph Clients[D-Bus Clients]
        MCP[MCP Server]
        VSCODE[VSCode Extension]
        CLI[CLI Tools]
    end

    Daemons --> DBUS
    DBUS --> Clients
```

## Service Names

| Daemon | D-Bus Name | Interface |
|--------|------------|-----------|
| Slack | `org.redhat.workflow.Slack` | `org.redhat.workflow.SlackInterface` |
| Cron | `org.redhat.workflow.Cron` | `org.redhat.workflow.CronInterface` |
| Memory | `org.redhat.workflow.Memory` | `org.redhat.workflow.MemoryInterface` |
| Session | `org.redhat.workflow.Session` | `org.redhat.workflow.SessionInterface` |
| Config | `org.redhat.workflow.Config` | `org.redhat.workflow.ConfigInterface` |

## Method Call Flow

```mermaid
sequenceDiagram
    participant Client as MCP Server
    participant Bus as D-Bus
    participant Daemon as SlackDaemon

    Client->>Bus: Call method
    Note over Client,Bus: org.redhat.workflow.Slack.SendMessage

    Bus->>Daemon: Dispatch call
    Daemon->>Daemon: Execute method
    Daemon-->>Bus: Return result
    Bus-->>Client: Method result
```

## Signal Flow

```mermaid
sequenceDiagram
    participant Daemon as ConfigDaemon
    participant Bus as D-Bus
    participant Client1 as MCP Server
    participant Client2 as VSCode

    Daemon->>Bus: Emit signal
    Note over Daemon,Bus: ConfigChanged(section, key, value)

    par Broadcast to subscribers
        Bus->>Client1: Signal
        Bus->>Client2: Signal
    end

    Client1->>Client1: Handle change
    Client2->>Client2: Handle change
```

## Common Methods

### SlackDaemon

```python
# Methods
SendMessage(channel: str, text: str) -> str
GetStatus() -> dict
SetPersona(status: str, emoji: str) -> bool

# Signals
MessageReceived(channel: str, user: str, text: str)
```

### CronDaemon

```python
# Methods
ListJobs() -> list
AddJob(name: str, schedule: str, command: str) -> str
RemoveJob(job_id: str) -> bool
TriggerJob(job_id: str) -> dict

# Signals
JobStarted(job_id: str, name: str)
JobCompleted(job_id: str, result: str)
```

### MemoryDaemon

```python
# Methods
Read(path: str) -> str  # YAML string
Write(path: str, data: str) -> bool
Invalidate(path: str) -> bool

# Signals
MemoryChanged(path: str)
```

## D-Bus Integration Pattern

```mermaid
flowchart TB
    subgraph Daemon[Daemon Process]
        BASE[BaseDaemon]
        DBUS_MIXIN[DaemonDBusBase]
        IMPL[Daemon Implementation]
    end

    subgraph DBus[D-Bus Setup]
        BUS[Connect to session bus]
        NAME[Request bus name]
        EXPORT[Export interface]
    end

    BASE --> DBUS_MIXIN
    DBUS_MIXIN --> IMPL
    IMPL --> DBus
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| DaemonDBusBase | `services/base/dbus.py` | D-Bus mixin |
| BaseDaemon | `services/base/daemon.py` | Base class |
| Daemon implementations | `services/*/daemon.py` | Specific daemons |

## Related Diagrams

- [Base Daemon](../02-services/base-daemon.md)
- [Slack D-Bus](../02-services/slack-dbus.md)
- [Daemon Overview](../02-services/daemon-overview.md)
