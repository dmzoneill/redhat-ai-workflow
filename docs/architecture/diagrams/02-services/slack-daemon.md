# Slack Daemon

> Real-time Slack message handling and AI responses

## Diagram

```mermaid
sequenceDiagram
    participant Slack as Slack API
    participant WS as WebSocket Client
    participant Daemon as SlackDaemon
    participant AI as AI Router
    participant Memory as Memory System
    participant DBus as D-Bus

    Daemon->>Slack: Connect WebSocket
    Slack-->>WS: Connected

    loop Message Loop
        Slack->>WS: message event
        WS->>Daemon: on_message()
        
        alt Direct message or mention
            Daemon->>Daemon: Parse message
            Daemon->>Memory: Get context
            Memory-->>Daemon: User history, preferences
            
            Daemon->>AI: Route to Claude/Ollama
            AI-->>Daemon: Response
            
            Daemon->>Slack: Post reply
            Daemon->>Memory: Log interaction
        else Channel message
            Daemon->>Daemon: Check triggers
            alt Trigger matched
                Daemon->>AI: Process trigger
            end
        end
    end

    DBus->>Daemon: Control command
    Daemon-->>DBus: Status response
```

## Class Structure

```mermaid
classDiagram
    class BaseDaemon {
        +name: str
        +description: str
        +verbose: bool
        +enable_dbus: bool
        +startup() async
        +run_daemon() async
        +shutdown() async
    }

    class DaemonDBusBase {
        +service_name: str
        +object_path: str
        +interface_name: str
        +is_running: bool
        +start_dbus() async
        +stop_dbus() async
        +get_service_stats() async
        +get_service_status() async
        +health_check() async
        +register_handler(name, handler)
    }

    class SlackDaemon {
        +name: str = "slack"
        +service_name: str = "com.aiworkflow.BotSlack"
        +dry_run: bool
        +poll_interval_min: float
        +poll_interval_max: float
        +response_generator: ResponseGenerator
        +user_classifier: UserClassifier
        +channel_permissions: ChannelPermissions
        +command_handler: CommandHandler
    }

    class ResponseGenerator {
        +generate(message, context) async
        +route_to_claude(message) async
    }

    class UserClassifier {
        +classify(user_id): UserClassification
    }

    class CommandHandler {
        +handle_command(message) async
    }

    BaseDaemon <|-- SlackDaemon
    DaemonDBusBase <|-- SlackDaemon
    SlackDaemon --> ResponseGenerator : uses
    SlackDaemon --> UserClassifier : uses
    SlackDaemon --> CommandHandler : uses
```

## Message Flow

```mermaid
flowchart TB
    subgraph Input[Slack Events]
        DM[Direct Message]
        MENTION[App Mention]
        REACTION[Reaction Added]
        THREAD[Thread Reply]
    end

    subgraph Processing[Message Processing]
        PARSE[Parse Event]
        CONTEXT[Load Context]
        ROUTE[Route to AI]
        RESPOND[Generate Response]
    end

    subgraph Output[Responses]
        REPLY[Post Reply]
        REACT[Add Reaction]
        UPDATE[Update Message]
    end

    DM --> PARSE
    MENTION --> PARSE
    REACTION --> PARSE
    THREAD --> PARSE

    PARSE --> CONTEXT
    CONTEXT --> ROUTE
    ROUTE --> RESPOND

    RESPOND --> REPLY
    RESPOND --> REACT
    RESPOND --> UPDATE
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| SlackDaemon | `services/slack/daemon.py` | Main daemon class |
| SlackDBusInterface | `services/slack/dbus.py` | D-Bus interface |
| control | `services/slack/control.py` | Control functions |
| path_setup | `services/slack/path_setup.py` | Path configuration |

## D-Bus Interface

**Service:** `com.aiworkflow.BotSlack`
**Path:** `/com/aiworkflow/BotSlack`

### Standard Methods (from BaseDaemon)

| Method | Description |
|--------|-------------|
| `Ping()` | Simple ping, returns "pong" |
| `GetStatus()` | Get daemon status as JSON |
| `GetStats()` | Get daemon statistics as JSON |
| `Shutdown()` | Request graceful shutdown |
| `HealthCheck()` | Perform health check |
| `CallMethod(name, args)` | Call custom handler |

### Custom Handlers (via CallMethod)

Service-specific handlers are registered and called via `CallMethod("handler_name", args_json)`.
Check daemon source for available handlers.

## Configuration

```json
{
  "slack": {
    "workspace": "redhat",
    "bot_user_id": "U...",
    "channels": ["#ai-workflow"],
    "response_enabled": true,
    "persona": "slack"
  }
}
```

## Related Diagrams

- [Daemon Overview](./daemon-overview.md)
- [Slack Integration](../07-integrations/slack-integration.md)
- [Slack Tools](../03-tools/slack-tools.md)
