# Slack Tools

> aa_slack and aa_slack_persona modules for Slack integration

## Diagram

```mermaid
classDiagram
    class SlackBasic {
        +slack_search_messages(query): list
        +slack_get_channel_history(channel): list
        +slack_list_channels(): list
        +slack_get_user_info(user_id): dict
        +slack_get_thread(channel, ts): list
    }

    class SlackCore {
        +slack_send_message(channel, text): dict
        +slack_reply_thread(channel, ts, text): dict
        +slack_add_reaction(channel, ts, emoji): dict
        +slack_update_message(channel, ts, text): dict
        +slack_delete_message(channel, ts): dict
    }

    class SlackPersona {
        +slack_persona_sync(): dict
        +slack_update_status(text, emoji): dict
        +slack_update_avatar(url): dict
        +slack_get_style_profile(): dict
    }

    SlackBasic <|-- SlackCore
    SlackCore --> SlackPersona : uses
```

## Message Flow

```mermaid
sequenceDiagram
    participant Tool as Slack Tool
    participant Client as Slack Client
    participant API as Slack API
    participant WS as WebSocket

    alt REST API Call
        Tool->>Client: Build request
        Client->>API: POST /api/chat.postMessage
        API-->>Client: Response
        Client-->>Tool: Formatted result
    else WebSocket Event
        WS->>Client: message event
        Client->>Tool: Process event
        Tool-->>Tool: Handle message
    end
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| tools_basic.py | `tool_modules/aa_slack/src/` | Read operations |
| tools_core.py | `tool_modules/aa_slack/src/` | Write operations |
| sync.py | `tool_modules/aa_slack_persona/src/` | Persona sync |
| adapter.py | `tool_modules/aa_slack_persona/src/` | Memory adapter |

## Tool Summary

| Tool | Module | Description |
|------|--------|-------------|
| `slack_search_messages` | aa_slack | Search messages |
| `slack_get_channel_history` | aa_slack | Get channel history |
| `slack_send_message` | aa_slack | Send message |
| `slack_reply_thread` | aa_slack | Reply in thread |
| `slack_persona_sync` | aa_slack_persona | Sync persona to Slack |
| `slack_update_status` | aa_slack_persona | Update status |

## Persona Sync

```mermaid
flowchart TB
    subgraph Source[Persona Source]
        YAML[personas/slack.yaml]
        STYLE[Style Profile]
        AVATAR[Avatar Config]
    end

    subgraph Sync[Sync Process]
        LOAD[Load persona]
        ANALYZE[Analyze style]
        UPDATE[Update Slack]
    end

    subgraph Slack[Slack Profile]
        STATUS[Status]
        PHOTO[Profile Photo]
        NAME[Display Name]
    end

    YAML --> LOAD
    STYLE --> ANALYZE
    AVATAR --> UPDATE

    LOAD --> UPDATE
    ANALYZE --> UPDATE

    UPDATE --> STATUS
    UPDATE --> PHOTO
    UPDATE --> NAME
```

## Configuration

```json
{
  "slack": {
    "workspace": "redhat",
    "bot_token_env": "SLACK_BOT_TOKEN",
    "user_token_env": "SLACK_USER_TOKEN",
    "default_channel": "#ai-workflow"
  }
}
```

## Related Diagrams

- [Tool Module Structure](./tool-module-structure.md)
- [Slack Integration](../07-integrations/slack-integration.md)
- [Slack Daemon](../02-services/slack-daemon.md)
