# Session Daemon

> IDE session synchronization and state management

## Diagram

```mermaid
sequenceDiagram
    participant Cursor as Cursor IDE
    participant DB as Cursor SQLite
    participant Daemon as SessionDaemon
    participant Memory as Memory System
    participant DBus as D-Bus

    Daemon->>DB: Watch for changes

    loop Monitor Loop
        DB->>Daemon: New chat/session detected
        Daemon->>Daemon: Parse session data
        Daemon->>Memory: Update session state

        alt Session has context
            Daemon->>Memory: Extract context
            Memory-->>Daemon: Stored
        end
    end

    DBus->>Daemon: get_active_sessions()
    Daemon->>DB: Query sessions
    DB-->>Daemon: Session data
    Daemon-->>DBus: Session list

    Cursor->>Daemon: Session ended
    Daemon->>Memory: Archive session
```

## Class Structure

```mermaid
classDiagram
    class SessionDaemon {
        +name: str = "session"
        +service_name: str
        -_db_path: Path
        -_watcher: FileWatcher
        -_sessions: dict
        +startup() async
        +run_daemon() async
        +shutdown() async
        +get_active_sessions(): list
        +get_session_context(id): dict
        +sync_session(id) async
        +get_service_stats() async
    }

    class CursorDBReader {
        +db_path: Path
        +get_chats(): list
        +get_chat_messages(id): list
        +get_workspaces(): list
        +watch_changes(callback)
    }

    class SessionState {
        +session_id: str
        +workspace: str
        +persona: str
        +project: str
        +messages: list
        +created_at: datetime
        +last_active: datetime
    }

    class SessionArchiver {
        +archive_session(session)
        +get_archived(date): list
        +search_archives(query): list
    }

    SessionDaemon --> CursorDBReader
    SessionDaemon --> SessionState
    SessionDaemon --> SessionArchiver
```

## Session Sync Flow

```mermaid
flowchart TB
    subgraph Sources[Data Sources]
        CURSOR_DB[Cursor SQLite]
        WORKSPACE[Workspace State]
        MCP[MCP Server]
    end

    subgraph Processing[Session Processing]
        DETECT[Detect Changes]
        PARSE[Parse Session]
        EXTRACT[Extract Context]
        MERGE[Merge State]
    end

    subgraph Storage[Storage]
        MEMORY[Memory YAML]
        ARCHIVE[Session Archive]
        STATE[Session State]
    end

    CURSOR_DB --> DETECT
    WORKSPACE --> DETECT
    MCP --> DETECT

    DETECT --> PARSE
    PARSE --> EXTRACT
    EXTRACT --> MERGE

    MERGE --> MEMORY
    MERGE --> ARCHIVE
    MERGE --> STATE
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| SessionDaemon | `services/session/daemon.py` | Main daemon class |
| CursorDBReader | Internal | SQLite reader |
| SessionState | Internal | Session model |

## Cursor SQLite Schema

| Table | Description |
|-------|-------------|
| chats | Chat sessions |
| messages | Chat messages |
| workspaces | Workspace info |
| settings | IDE settings |

## D-Bus Methods

| Method | Description |
|--------|-------------|
| `get_active_sessions()` | List active sessions |
| `get_session_context(id)` | Get session context |
| `sync_session(id)` | Force sync session |
| `archive_session(id)` | Archive session |
| `search_sessions(query)` | Search sessions |

## Session State Structure

```yaml
sessions:
  abc123:
    session_id: "abc123"
    workspace: "/home/user/project"
    persona: "developer"
    project: "automation-analytics-backend"
    created_at: "2024-01-15T10:00:00"
    last_active: "2024-01-15T12:30:00"
    context:
      active_issue: "AAP-12345"
      active_branch: "aap-12345-fix-bug"
      recent_files:
        - "src/app.py"
        - "tests/test_app.py"
```

## Related Diagrams

- [Daemon Overview](./daemon-overview.md)
- [Workspace Tools](../01-server/workspace-tools.md)
- [Session Builder](../01-server/session-builder.md)
