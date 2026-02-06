# WebSocket Server

> Real-time skill execution updates and confirmations

## Diagram

```mermaid
sequenceDiagram
    participant Extension as VSCode Extension
    participant WS as WebSocket Server
    participant Skill as Skill Engine
    participant AutoHeal as Auto-Heal

    Extension->>WS: Connect ws://localhost:9876
    WS-->>Extension: connected + running_skills + pending_confirmations

    loop Heartbeat
        Extension->>WS: heartbeat
        WS-->>Extension: heartbeat_ack
    end

    Skill->>WS: skill_started(id, name, steps)
    WS->>Extension: skill_started event

    loop For each step
        Skill->>WS: step_started(skill_id, index, name)
        WS->>Extension: step_started event

        alt Step succeeds
            Skill->>WS: step_completed(skill_id, index, duration)
            WS->>Extension: step_completed event
        else Step fails
            Skill->>WS: step_failed(skill_id, index, error)
            WS->>Extension: step_failed event

            alt Auto-heal triggered
                AutoHeal->>WS: auto_heal_triggered(skill_id, type, action)
                WS->>Extension: auto_heal_triggered event
                AutoHeal->>WS: auto_heal_completed(skill_id, success)
                WS->>Extension: auto_heal_completed event
            end
        end
    end

    alt Skill completes
        Skill->>WS: skill_completed(id, duration)
        WS->>Extension: skill_completed event
    else Skill fails
        Skill->>WS: skill_failed(id, error)
        WS->>Extension: skill_failed event
    end
```

## Class Structure

```mermaid
classDiagram
    class SkillWebSocketServer {
        +host: str
        +port: int
        +clients: set
        +pending_confirmations: dict
        +running_skills: dict
        -_server: WebSocketServer
        -_started: bool
        -_clients_lock: Lock
        -_confirmations_lock: Lock
        -_skills_lock: Lock
        +start()
        +stop()
        +is_running: bool
        +broadcast(event)
        +skill_started(id, name, steps, inputs, source)
        +skill_completed(id, duration)
        +skill_failed(id, error, duration)
        +step_started(skill_id, index, name, desc)
        +step_completed(skill_id, index, name, duration)
        +step_failed(skill_id, index, name, error)
        +auto_heal_triggered(skill_id, index, type, action)
        +auto_heal_completed(skill_id, index, action, success)
        +request_confirmation(skill_id, index, prompt, options)
        +memory_query_started(id, query, sources)
        +memory_query_completed(id, intent, sources, count, latency)
    }

    class SkillState {
        +skill_id: str
        +skill_name: str
        +total_steps: int
        +current_step: int
        +status: str
        +started_at: datetime
        +source: str
    }

    class PendingConfirmation {
        +id: str
        +skill_id: str
        +step_index: int
        +prompt: str
        +options: list~str~
        +claude_suggestion: str
        +timeout_seconds: int
        +created_at: datetime
        +future: Future
    }

    SkillWebSocketServer --> SkillState : tracks
    SkillWebSocketServer --> PendingConfirmation : manages
```

## Event Types

```mermaid
graph TB
    subgraph SkillEvents[Skill Lifecycle]
        STARTED[skill_started]
        COMPLETED[skill_completed]
        FAILED[skill_failed]
    end

    subgraph StepEvents[Step Progress]
        STEP_START[step_started]
        STEP_DONE[step_completed]
        STEP_FAIL[step_failed]
    end

    subgraph HealEvents[Auto-Heal]
        HEAL_TRIGGER[auto_heal_triggered]
        HEAL_DONE[auto_heal_completed]
    end

    subgraph ConfirmEvents[Confirmations]
        CONF_REQ[confirmation_required]
        CONF_ANS[confirmation_answered]
        CONF_EXP[confirmation_expired]
    end

    subgraph MemoryEvents[Memory Queries]
        MEM_START[memory_query_started]
        MEM_DONE[memory_query_completed]
        INTENT[intent_classified]
    end

    subgraph ClientEvents[Client Messages]
        HEARTBEAT[heartbeat]
        CONF_RESP[confirmation_response]
        PAUSE[pause_timer]
        RESUME[resume_timer]
    end
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| SkillWebSocketServer | `server/websocket_server.py` | Main server class |
| SkillState | `server/websocket_server.py` | Running skill state |
| PendingConfirmation | `server/websocket_server.py` | Confirmation request |
| get_websocket_server | `server/websocket_server.py` | Get global instance |
| start_websocket_server | `server/websocket_server.py` | Start server |
| stop_websocket_server | `server/websocket_server.py` | Stop server |

## Confirmation Flow

```mermaid
sequenceDiagram
    participant Skill as Skill Engine
    participant WS as WebSocket Server
    participant Extension as VSCode Extension
    participant User as User

    Skill->>WS: request_confirmation(prompt, options)
    WS->>WS: Create PendingConfirmation
    WS->>WS: _bring_cursor_to_front()
    WS->>WS: _play_notification_sound()
    WS->>Extension: confirmation_required event

    Extension->>User: Show confirmation dialog

    alt User responds
        User->>Extension: Select option
        Extension->>WS: confirmation_response
        WS->>WS: Set future result
        WS->>Extension: confirmation_answered
        WS-->>Skill: {response, remember}
    else Timeout
        WS->>Extension: confirmation_expired
        WS->>WS: Try Zenity fallback
        WS-->>Skill: {response: "let_claude"}
    end
```

## Related Diagrams

- [MCP Server Core](./mcp-server-core.md)
- [Skill Execution Flow](../04-skills/skill-execution-flow.md)
- [VSCode Extension](../10-vscode-extension/README.md)
