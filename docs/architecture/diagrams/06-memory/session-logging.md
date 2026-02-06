# Session Logging

> Session history and action logging

## Diagram

```mermaid
graph TB
    subgraph SessionStorage[sessions/]
        SESSION_FILES[{session_id}.yaml<br/>Session metadata]
        LOGS[logs/<br/>Action logs]
    end

    subgraph SessionData[Session Data]
        META[Metadata<br/>name, created, persona]
        HISTORY[History<br/>Actions, results]
        CONTEXT[Context<br/>Project, issues]
    end

    subgraph Logging[Logging Operations]
        SESSION_LOG[memory_session_log]
        SESSION_START[session_start]
        SESSION_END[session_end]
    end

    Logging --> SessionStorage
    SessionStorage --> SessionData
```

## Session File Structure

```yaml
# sessions/{session_id}.yaml
id: abc123-def456
name: "Fixing AAP-12345"
created: 2026-02-04T09:00:00
last_active: 2026-02-04T11:30:00

persona: developer
project: automation-analytics-backend

context:
  issue_key: AAP-12345
  branch: aap-12345-fix-auth

history:
  - timestamp: 2026-02-04T09:05:00
    action: session_start
    details: "Started with developer persona"

  - timestamp: 2026-02-04T09:10:00
    action: jira_view_issue
    details: "Viewed AAP-12345"
    result: success

  - timestamp: 2026-02-04T09:30:00
    action: git_checkout
    details: "Created branch aap-12345-fix-auth"
    result: success

  - timestamp: 2026-02-04T11:30:00
    action: git_commit
    details: "Committed fix"
    result: success
```

## Logging Flow

```mermaid
sequenceDiagram
    participant Tool as Tool Execution
    participant Log as memory_session_log
    participant Session as Session State
    participant YAML as Session YAML

    Tool->>Log: Log action
    Log->>Session: Get current session
    Session-->>Log: session_id

    Log->>YAML: Read session file
    YAML-->>Log: session_data

    Log->>Log: Append to history
    Log->>YAML: Write updated

    Log-->>Tool: Logged
```

## Log Entry Types

```mermaid
flowchart TB
    subgraph Actions[Action Types]
        SESSION[Session actions<br/>start, end, switch]
        TOOL[Tool actions<br/>execution, result]
        SKILL[Skill actions<br/>run, step, complete]
        ERROR[Error actions<br/>failure, recovery]
    end

    subgraph Details[Log Details]
        TIMESTAMP[Timestamp]
        ACTION_TYPE[Action type]
        DESCRIPTION[Description]
        RESULT[Result/Status]
        METADATA[Additional metadata]
    end

    Actions --> Details
```

## Session Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Created: session_start

    Created --> Active: First action
    Active --> Active: Actions logged
    Active --> Paused: User inactive
    Paused --> Active: User returns
    Active --> Ended: session_end

    Ended --> [*]
```

## Log Queries

```mermaid
sequenceDiagram
    participant User as User/Claude
    participant Tool as memory_ask
    participant Sessions as sessions/

    User->>Tool: "What did I do yesterday?"
    Tool->>Sessions: Query session history
    Sessions-->>Tool: Matching entries

    Tool->>Tool: Format timeline
    Tool-->>User: "## Yesterday's Activity\n- 09:00 Started work on AAP-12345..."
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| memory_session_log | `memory_tools.py` | Log action |
| session_start | `session_tools.py` | Create session |
| Session files | `memory/sessions/` | YAML storage |

## Related Diagrams

- [Memory Architecture](./memory-architecture.md)
- [Session Management](../01-server/workspace-tools.md)
- [Session Bootstrap](../08-data-flows/session-bootstrap.md)
