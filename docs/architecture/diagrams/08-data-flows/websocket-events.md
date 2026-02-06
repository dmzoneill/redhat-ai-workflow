# WebSocket Events

> Real-time event flow to clients

## Diagram

```mermaid
graph TB
    subgraph Sources[Event Sources]
        SKILL[Skill Engine]
        AUTO_HEAL[Auto-Heal]
        DAEMON[Daemons]
    end

    subgraph Server[WebSocket Server]
        HANDLER[Event Handler]
        BROADCAST[Broadcaster]
    end

    subgraph Clients[Connected Clients]
        VSCODE[VSCode Extension]
        CLI[CLI Tools]
        WEB[Web UI]
    end

    Sources --> HANDLER
    HANDLER --> BROADCAST
    BROADCAST --> Clients
```

## Event Types

```mermaid
flowchart TB
    subgraph SkillEvents[Skill Events]
        SKILL_START[skill_started]
        STEP_START[step_started]
        STEP_COMPLETE[step_completed]
        SKILL_COMPLETE[skill_completed]
        SKILL_ERROR[skill_error]
    end

    subgraph ConfirmEvents[Confirmation Events]
        CONFIRM_REQ[confirmation_required]
        CONFIRM_RESP[confirmation_response]
    end

    subgraph HealEvents[Auto-Heal Events]
        HEAL_START[heal_started]
        HEAL_COMPLETE[heal_completed]
    end

    subgraph SystemEvents[System Events]
        PERSONA_CHANGE[persona_changed]
        TOOLS_CHANGE[tools_list_changed]
    end
```

## Event Flow

```mermaid
sequenceDiagram
    participant Engine as Skill Engine
    participant WS as WebSocket Server
    participant Client as VSCode Extension

    Engine->>WS: skill_started
    WS->>Client: {"type": "skill_started", ...}

    loop For each step
        Engine->>WS: step_started
        WS->>Client: {"type": "step_started", ...}

        opt Confirmation required
            Engine->>WS: confirmation_required
            WS->>Client: {"type": "confirmation_required", ...}
            Client-->>WS: {"type": "confirmation_response", ...}
            WS-->>Engine: User response
        end

        Engine->>WS: step_completed
        WS->>Client: {"type": "step_completed", ...}
    end

    Engine->>WS: skill_completed
    WS->>Client: {"type": "skill_completed", ...}
```

## Event Schemas

```typescript
// Skill started
{
  "type": "skill_started",
  "skill_name": "start_work",
  "session_id": "abc123",
  "timestamp": "2026-02-04T10:30:00Z"
}

// Step completed
{
  "type": "step_completed",
  "skill_name": "start_work",
  "step_name": "fetch_issue",
  "step_index": 0,
  "total_steps": 5,
  "result": "success",
  "output": {...}
}

// Confirmation required
{
  "type": "confirmation_required",
  "skill_name": "start_work",
  "step_name": "create_branch",
  "message": "Create branch aap-12345-fix-auth?",
  "options": ["yes", "no", "skip"],
  "timeout_seconds": 60
}

// Auto-heal event
{
  "type": "heal_started",
  "tool_name": "k8s_get_pods",
  "error": "Unauthorized",
  "fix_action": "kube_login"
}
```

## Client Handling

```mermaid
flowchart TB
    subgraph Receive[Receive Event]
        PARSE[Parse JSON]
        ROUTE[Route by type]
    end

    subgraph Handle[Handle Event]
        SKILL_UI[Update skill progress]
        CONFIRM_UI[Show confirmation dialog]
        TOAST[Show toast notification]
        LOG[Log to console]
    end

    PARSE --> ROUTE
    ROUTE -->|skill_*| SKILL_UI
    ROUTE -->|confirmation_*| CONFIRM_UI
    ROUTE -->|heal_*| TOAST
    ROUTE -->|*| LOG
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| WebSocket Server | `server/websocket_server.py` | Event broadcasting |
| VSCode handler | `extensions/aa_workflow_vscode/` | Client handling |
| Skill Engine | `skill_engine.py` | Event emission |

## Related Diagrams

- [WebSocket Server](../01-server/websocket-server.md)
- [Skill Execution Flow](./skill-execution-flow.md)
- [Auto-Heal Flow](./auto-heal-flow.md)
