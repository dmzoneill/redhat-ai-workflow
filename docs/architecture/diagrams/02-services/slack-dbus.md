# Slack D-Bus Interface

> D-Bus IPC interface for Slack daemon control

## Diagram

```mermaid
graph LR
    subgraph Clients[D-Bus Clients]
        VSCODE[VSCode Extension]
        CLI[CLI Tools]
        MCP[MCP Server]
        OTHER[Other Daemons]
    end

    subgraph DBus[D-Bus Session Bus]
        BUS[com.aiworkflow.BotSlack]
    end

    subgraph Daemon[Slack Daemon]
        INTERFACE[SlackDBusInterface]
        HANDLERS[Method Handlers]
        DAEMON[SlackDaemon]
    end

    VSCODE --> BUS
    CLI --> BUS
    MCP --> BUS
    OTHER --> BUS

    BUS --> INTERFACE
    INTERFACE --> HANDLERS
    HANDLERS --> DAEMON
```

## Interface Definition

```mermaid
classDiagram
    class SlackDBusInterface {
        <<interface>>
        +Ping(): str
        +GetStatus(): dict
        +GetStats(): dict
        +HealthCheck(): dict
        +SendMessage(channel, text): dict
        +SetPersona(persona): dict
        +ToggleResponses(enabled): dict
        +GetHistory(limit): dict
        +SearchMessages(query): dict
    }

    class SignalEmitter {
        +MessageReceived(channel, user, text)
        +ResponseSent(channel, text)
        +PersonaChanged(persona)
        +StatusChanged(status)
    }

    SlackDBusInterface --> SignalEmitter : emits
```

## Method Calls

```mermaid
sequenceDiagram
    participant Client as D-Bus Client
    participant Bus as Session Bus
    participant Interface as SlackDBusInterface
    participant Daemon as SlackDaemon

    Client->>Bus: Call SendMessage(channel, text)
    Bus->>Interface: Dispatch method
    Interface->>Daemon: send_message(channel, text)
    Daemon-->>Interface: Result
    Interface-->>Bus: Return dict
    Bus-->>Client: Response
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| SlackDBusInterface | `services/slack/dbus.py` | D-Bus interface class |
| get_client | `services/base/dbus.py` | Get D-Bus client |
| DaemonDBusBase | `services/base/dbus.py` | Base D-Bus mixin |

## D-Bus Methods

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| Ping | - | str | Health check |
| GetStatus | - | dict | Full status |
| GetStats | - | dict | Statistics |
| HealthCheck | - | dict | Health info |
| SendMessage | channel, text | dict | Send message |
| SetPersona | persona | dict | Change persona |
| ToggleResponses | enabled | dict | Toggle AI responses |
| GetHistory | limit | dict | Recent messages |
| SearchMessages | query | dict | Search messages |

## D-Bus Signals

| Signal | Parameters | Description |
|--------|------------|-------------|
| MessageReceived | channel, user, text | New message received |
| ResponseSent | channel, text | AI response sent |
| PersonaChanged | persona | Persona changed |
| StatusChanged | status | Daemon status changed |

## Client Usage

```python
from services.base.dbus import get_client

# Get Slack daemon client
client = get_client("com.aiworkflow.BotSlack")

# Send message
result = await client.call("SendMessage", "#general", "Hello!")

# Get status
status = await client.call("GetStatus")

# Toggle responses
await client.call("ToggleResponses", False)
```

## Related Diagrams

- [Slack Daemon](./slack-daemon.md)
- [D-Bus Architecture](../09-deployment/dbus-architecture.md)
- [Base Daemon](./base-daemon.md)
