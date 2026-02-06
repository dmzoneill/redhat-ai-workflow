# Slack Integration

> Slack API and real-time messaging integration

## Diagram

```mermaid
graph TB
    subgraph Components[Slack Components]
        TOOLS[aa_slack<br/>MCP tools]
        PERSONA[aa_slack_persona<br/>Persona sync]
        DAEMON[SlackDaemon<br/>Real-time]
    end

    subgraph Operations[Operations]
        SEARCH[slack_search]
        SEND[slack_send_message]
        REACT[slack_add_reaction]
        STATUS[slack_set_status]
        AVATAR[slack_set_avatar]
    end

    subgraph API[Slack API]
        REST[Web API]
        WEBSOCKET[Socket Mode]
        EVENTS[Events API]
    end

    subgraph Config[Configuration]
        BOT_TOKEN[Bot Token]
        USER_TOKEN[User Token]
        APP_TOKEN[App Token]
    end

    Components --> Operations
    Operations --> API
    Config --> API
```

## Real-Time Flow

```mermaid
sequenceDiagram
    participant Slack as Slack
    participant WS as WebSocket
    participant Daemon as SlackDaemon
    participant AI as AI Router
    participant Memory as Memory

    Slack->>WS: message event
    WS->>Daemon: Receive message

    Daemon->>Daemon: Parse message
    Daemon->>Memory: Get context

    Daemon->>AI: Generate response
    AI-->>Daemon: Response text

    Daemon->>Slack: Post reply
    Daemon->>Memory: Log interaction
```

## Tool Categories

### Message Tools

| Tool | Description | API |
|------|-------------|-----|
| slack_search | Search messages | search.messages |
| slack_send_message | Send message | chat.postMessage |
| slack_add_reaction | Add reaction | reactions.add |
| slack_get_thread | Get thread | conversations.replies |

### Persona Tools

| Tool | Description | API |
|------|-------------|-----|
| slack_set_status | Set status | users.profile.set |
| slack_set_avatar | Set avatar | users.setPhoto |
| slack_get_presence | Get presence | users.getPresence |

## Daemon Architecture

```mermaid
flowchart TB
    subgraph SlackDaemon[Slack Daemon]
        CONNECT[WebSocket Connect]
        HANDLER[Message Handler]
        ROUTER[AI Router]
        PERSONA_SYNC[Persona Sync]
    end

    subgraph External[External]
        SLACK_API[Slack API]
        DBUS[D-Bus]
        MEMORY[Memory]
    end

    CONNECT --> SLACK_API
    HANDLER --> ROUTER
    ROUTER --> MEMORY
    PERSONA_SYNC --> SLACK_API
    SlackDaemon --> DBUS
```

## Authentication

```mermaid
flowchart TB
    subgraph Tokens[Token Types]
        BOT["Bot Token (xoxb-...)<br/>Bot actions"]
        USER["User Token (xoxp-...)<br/>User actions"]
        APP["App Token (xapp-...)<br/>Socket Mode"]
    end

    subgraph Usage[Token Usage]
        BOT_USE["Post messages<br/>Read channels"]
        USER_USE["Set status<br/>Set avatar"]
        APP_USE["WebSocket connection"]
    end

    BOT --> BOT_USE
    USER --> USER_USE
    APP --> APP_USE
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| aa_slack | `tool_modules/aa_slack/` | MCP tools |
| aa_slack_persona | `tool_modules/aa_slack_persona/` | Persona sync |
| SlackDaemon | `services/slack/daemon.py` | Real-time daemon |

## Related Diagrams

- [Slack Tools](../03-tools/slack-tools.md)
- [Slack Daemon](../02-services/slack-daemon.md)
- [Slack D-Bus](../02-services/slack-dbus.md)
