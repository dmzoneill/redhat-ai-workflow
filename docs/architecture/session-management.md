# 📋 Session Management Architecture

This document describes the multi-chat session management system that maintains independent context for each Cursor chat within a workspace.

## Overview

The AI Workflow system supports **multiple concurrent chat sessions** within a single Cursor workspace. Each chat session maintains its own:

- Session ID (UUID)
- Session name
- Active persona
- Work context (issue, branch, MR)
- Activity history

This enables users to have specialized chats for different tasks (e.g., one for coding, one for reviewing, one for deployments) while sharing the same underlying tool infrastructure.

## Architecture

```mermaid
graph TB
    subgraph Cursor["Cursor IDE"]
        CHAT1[Chat 1: Coding]
        CHAT2[Chat 2: Review]
        CHAT3[Chat 3: Deploy]
    end

    subgraph MCP["MCP Server"]
        REGISTRY[WorkspaceRegistry<br/>Singleton]
        WS1[WorkspaceState<br/>/path/to/project]
    end

    subgraph Sessions["Chat Sessions"]
        S1[Session abc-123<br/>developer persona]
        S2[Session def-456<br/>developer persona]
        S3[Session ghi-789<br/>devops persona]
    end

    subgraph Storage["Persistence"]
        FILE[(workspace_states.json)]
        CURSOR_DB[(Cursor SQLite DB)]
    end

    CHAT1 --> S1
    CHAT2 --> S2
    CHAT3 --> S3

    REGISTRY --> WS1
    WS1 --> S1 & S2 & S3

    WS1 --> FILE
    CURSOR_DB -.-> WS1

    style REGISTRY fill:#10b981,stroke:#059669,color:#fff
```

## Core Components

### WorkspaceRegistry (Singleton)

**Location**: `server/workspace_state.py`

**Purpose**: Global registry managing all workspaces and their sessions.

```mermaid
classDiagram
    class WorkspaceRegistry {
        <<singleton>>
        -_workspaces: dict[str, WorkspaceState]
        -_active_workspace_uri: str
        -_persistence_path: Path
        +get_instance() WorkspaceRegistry
        +get_workspace(uri) WorkspaceState
        +get_or_create_workspace(uri) WorkspaceState
        +get_active_workspace() WorkspaceState
        +set_active_workspace(uri)
        +list_workspaces() list[WorkspaceState]
        +persist()
        +load()
        +sync_with_cursor()
    }
```

**Key Methods**:

| Method | Purpose |
|--------|---------|
| `get_instance()` | Get singleton instance |
| `get_workspace(uri)` | Get workspace by URI |
| `get_or_create_workspace(uri)` | Get or create workspace |
| `get_active_workspace()` | Get currently active workspace |
| `set_active_workspace(uri)` | Set active workspace |
| `persist()` | Save all state to disk |
| `load()` | Load state from disk |
| `sync_with_cursor()` | Sync with Cursor's database |

### WorkspaceState

**Purpose**: Represents a single Cursor workspace (folder path).

```mermaid
classDiagram
    class WorkspaceState {
        +uri: str
        +persona: str
        +project: str
        +active_issue: str
        +active_branch: str
        +active_mr: int
        +tool_filter_enabled: bool
        +sessions: dict[str, ChatSession]
        +created_at: datetime
        +updated_at: datetime
        +get_session(id) ChatSession
        +create_session(name, persona) ChatSession
        +update_session(id, data)
        +remove_session(id)
        +get_active_session() ChatSession
        +to_dict() dict
        +from_dict(data) WorkspaceState
    }
```

**Workspace Properties**:

| Property | Purpose |
|----------|---------|
| `uri` | Workspace folder URI (file:///path) |
| `persona` | Current persona (shared across sessions) |
| `project` | Active project name |
| `active_issue` | Current Jira issue key |
| `active_branch` | Current git branch |
| `active_mr` | Current MR ID |
| `tool_filter_enabled` | Whether tool filtering is active |
| `sessions` | Map of session_id to ChatSession |

### ChatSession

**Purpose**: Represents a single chat within a workspace.

```mermaid
classDiagram
    class ChatSession {
        +session_id: str
        +name: str
        +persona: str
        +created_at: datetime
        +updated_at: datetime
        +cursor_chat_id: str
        +activity: list[ActivityEntry]
        +touch()
        +add_activity(action, details)
        +to_dict() dict
        +from_dict(data) ChatSession
    }

    class ActivityEntry {
        +timestamp: datetime
        +action: str
        +details: str
    }

    ChatSession "1" --> "*" ActivityEntry
```

**Session Properties**:

| Property | Purpose |
|----------|---------|
| `session_id` | Unique UUID for this session |
| `name` | User-friendly name |
| `persona` | Session-specific persona (if different from workspace) |
| `created_at` | When session was created |
| `updated_at` | Last activity timestamp |
| `cursor_chat_id` | Cursor's internal chat ID (if synced) |
| `activity` | Recent activity log |

## Session Lifecycle

### Session Creation

```mermaid
sequenceDiagram
    participant Claude
    participant MCP as MCP Server
    participant Registry as WorkspaceRegistry
    participant Workspace as WorkspaceState
    participant File as workspace_states.json

    Claude->>MCP: session_start()
    MCP->>Registry: get_or_create_workspace(uri)
    Registry->>Registry: Detect workspace from MCP roots

    alt New Workspace
        Registry->>Registry: Create WorkspaceState
    end

    Registry-->>MCP: WorkspaceState

    MCP->>Workspace: create_session(name)
    Workspace->>Workspace: Generate UUID
    Workspace->>Workspace: Create ChatSession
    Workspace-->>MCP: ChatSession

    MCP->>Registry: persist()
    Registry->>File: Atomic write

    MCP-->>Claude: Session context + ID
```

### Session Resume

```mermaid
sequenceDiagram
    participant Claude
    participant MCP as MCP Server
    participant Registry as WorkspaceRegistry
    participant Workspace as WorkspaceState

    Claude->>MCP: session_start(session_id="abc-123")
    MCP->>Registry: get_workspace(uri)
    Registry-->>MCP: WorkspaceState

    MCP->>Workspace: get_session("abc-123")

    alt Session Found
        Workspace-->>MCP: ChatSession
        MCP->>Workspace: session.touch()
        MCP-->>Claude: Resumed session context
    else Session Not Found
        MCP->>Workspace: create_session()
        Workspace-->>MCP: New ChatSession
        MCP-->>Claude: New session (ID not found)
    end
```

### Session Switching

```mermaid
sequenceDiagram
    participant Claude
    participant MCP as MCP Server
    participant Registry as WorkspaceRegistry
    participant Workspace as WorkspaceState

    Claude->>MCP: session_switch(session_id="def-456")
    MCP->>Registry: get_active_workspace()
    Registry-->>MCP: WorkspaceState

    MCP->>Workspace: get_session("def-456")
    Workspace-->>MCP: ChatSession

    MCP->>Registry: Update active session
    MCP->>Registry: persist()

    MCP-->>Claude: Switched to session context
```

## Cursor Database Integration

The session system integrates with Cursor's internal SQLite database to:

1. **Discover existing chats** - Find chats created by the user
2. **Sync chat names** - Use Cursor's chat names
3. **Filter archived chats** - Skip deleted/archived conversations

```mermaid
flowchart TD
    A[Cursor SQLite DB] --> B[state.vscdb]
    B --> C[composer.composerData]
    C --> D[Parse JSON]

    D --> E{For each chat}
    E --> F{Archived?}
    F -->|Yes| G[Skip]
    F -->|No| H[Extract chat info]

    H --> I[Match to Session]
    I --> J{Session exists?}
    J -->|Yes| K[Update session]
    J -->|No| L[Create session]

    K & L --> M[Persist]
```

### Database Location

```
~/.config/Cursor/User/workspaceStorage/
├── <workspace-hash-1>/
│   └── state.vscdb          # SQLite database
├── <workspace-hash-2>/
│   └── state.vscdb
└── ...
```

### Data Extraction

```python
def sync_with_cursor_db(workspace_uri: str) -> None:
    """Sync sessions with Cursor's internal database."""

    # Find matching workspace storage
    cursor_storage = Path.home() / ".config/Cursor/User/workspaceStorage"

    for storage_dir in cursor_storage.iterdir():
        db_path = storage_dir / "state.vscdb"
        if not db_path.exists():
            continue

        # Check if this storage matches our workspace
        workspace_json = storage_dir / "workspace.json"
        if workspace_json.exists():
            workspace_data = json.loads(workspace_json.read_text())
            if workspace_data.get("folder") != workspace_uri:
                continue

        # Extract composer data
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT value FROM ItemTable WHERE key = 'composer.composerData'"
        )
        row = cursor.fetchone()

        if row:
            data = json.loads(row[0])
            for chat in data.get("chats", []):
                if not chat.get("archived"):
                    yield {
                        "id": chat.get("id"),
                        "name": chat.get("name", "Untitled"),
                        "updated_at": chat.get("updatedAt")
                    }

        conn.close()
```

## Persistence Format

### workspace_states.json

```json
{
  "workspaces": {
    "file:///home/user/src/project": {
      "uri": "file:///home/user/src/project",
      "persona": "developer",
      "project": "automation-analytics-backend",
      "active_issue": "AAP-12345",
      "active_branch": "aap-12345-feature",
      "active_mr": 1459,
      "tool_filter_enabled": true,
      "created_at": "2026-01-20T10:00:00Z",
      "updated_at": "2026-01-26T09:30:00Z",
      "sessions": {
        "abc-123-def-456": {
          "session_id": "abc-123-def-456",
          "name": "Working on AAP-12345",
          "persona": "developer",
          "created_at": "2026-01-25T14:00:00Z",
          "updated_at": "2026-01-26T09:30:00Z",
          "cursor_chat_id": "cursor-uuid-here",
          "activity": [
            {
              "timestamp": "2026-01-26T09:30:00Z",
              "action": "skill_run",
              "details": "Ran create_mr skill"
            }
          ]
        },
        "ghi-789-jkl-012": {
          "session_id": "ghi-789-jkl-012",
          "name": "Code Review",
          "persona": "developer",
          "created_at": "2026-01-26T08:00:00Z",
          "updated_at": "2026-01-26T08:45:00Z"
        }
      }
    }
  },
  "active_workspace": "file:///home/user/src/project",
  "global_persona": "developer",
  "version": 2,
  "updated_at": "2026-01-26T09:30:00Z"
}
```

## Session Tools

### session_start

Start a new session or resume an existing one.

```python
def session_start(
    agent: str = "",           # Optional persona to load
    project: str = "",         # Optional project context
    name: str = "",            # Optional session name
    session_id: str = ""       # Optional ID to resume
) -> dict:
    """
    Start or resume a session.

    If session_id is provided and valid, resumes that session.
    Otherwise creates a new session.

    Returns session context including:
    - session_id (save this!)
    - persona
    - project
    - active work state
    - learned patterns count
    """
```

### session_info

Get information about a session.

```python
def session_info(session_id: str = "") -> dict:
    """
    Get session information.

    If session_id provided, returns that session's info.
    Otherwise returns the workspace's active session.
    """
```

### session_list

List all sessions in the workspace.

```python
def session_list() -> list[dict]:
    """
    List all sessions in the current workspace.

    Returns list of sessions with:
    - session_id
    - name
    - persona
    - created_at
    - updated_at
    """
```

### session_rename

Rename a session.

```python
def session_rename(name: str, session_id: str = "") -> dict:
    """
    Rename a session.

    If session_id not provided, renames active session.
    """
```

### session_switch

Switch to a different session.

```python
def session_switch(session_id: str) -> dict:
    """
    Switch to a specific session.

    Updates the active session for the workspace.
    """
```

### session_sync

Sync sessions with Cursor's database.

```python
def session_sync() -> dict:
    """
    Sync MCP sessions with Cursor's internal database.

    - Adds sessions for Cursor chats without MCP sessions
    - Removes sessions for deleted Cursor chats
    - Updates session names to match Cursor
    """
```

## Multi-Chat Patterns

### Pattern 1: Task-Specific Chats

```mermaid
graph TD
    subgraph Workspace["Project Workspace"]
        C1[Chat 1: Coding<br/>developer persona<br/>AAP-12345]
        C2[Chat 2: Review<br/>developer persona<br/>MR Reviews]
        C3[Chat 3: Deploy<br/>devops persona<br/>Deployments]
    end

    C1 --> |session_id: abc| S1[Session: Working on AAP-12345]
    C2 --> |session_id: def| S2[Session: Code Reviews]
    C3 --> |session_id: ghi| S3[Session: Ephemeral Deploys]
```

### Pattern 2: Persona Switching Within Chat

```mermaid
sequenceDiagram
    participant Chat as Single Chat
    participant Session
    participant Persona as Persona Loader

    Chat->>Session: session_start()
    Note over Session: developer persona

    Chat->>Persona: Load devops
    Persona->>Session: Update persona
    Note over Session: devops persona

    Chat->>Persona: Load incident
    Persona->>Session: Update persona
    Note over Session: incident persona
```

### Pattern 3: Session Handoff

```mermaid
sequenceDiagram
    participant User1 as Morning Session
    participant Memory as Memory/State
    participant User2 as Evening Session

    User1->>Memory: session_start(name="Morning work")
    User1->>Memory: Work on AAP-12345
    User1->>Memory: Update current_work.yaml
    Note over Memory: Session persisted

    User2->>Memory: session_start()
    Memory-->>User2: Previous session context
    Note over User2: Continues from where left off
```

## Session Daemon Integration

The Session Daemon (`scripts/session_daemon.py`) provides:

1. **Cursor DB Watching** - Monitor for chat changes
2. **Periodic Sync** - Regular sync with workspace_states.json
3. **Full-Text Search** - Search across all chat content
4. **D-Bus Interface** - External control and queries

```mermaid
sequenceDiagram
    participant Cursor as Cursor DB
    participant Daemon as Session Daemon
    participant File as workspace_states.json
    participant Client as VSCode Extension

    loop Every 30 seconds
        Daemon->>Cursor: Check for changes
        Cursor-->>Daemon: Modified chats

        Daemon->>Daemon: Sync sessions
        Daemon->>File: Write updated state
    end

    Client->>Daemon: search_chats("deploy")
    Daemon->>Cursor: Query chat content
    Cursor-->>Daemon: Matching chats
    Daemon-->>Client: Search results
```

## Best Practices

### 1. Always Use session_id

```python
# Start a session and save the ID
result = session_start(name="Working on feature")
my_session_id = result['session_id']

# Later, use the ID to resume
session_start(session_id=my_session_id)
```

### 2. Name Sessions Descriptively

```python
# Good names
session_start(name="AAP-12345 - API refactor")
session_start(name="Code review - MR 1459")
session_start(name="Deploy to stage")

# Bad names
session_start(name="Chat 1")
session_start(name="Work")
```

### 3. Check Session Before Operations

```python
# Get current session context
info = session_info(session_id=my_id)
if info['persona'] != 'devops':
    # Load correct persona for deployment
    persona_load('devops')
```

### 4. Handle Session Not Found

```python
result = session_start(session_id="old-session-id")
if result.get('resumed') is False:
    # Session was not found, new one created
    print(f"Started new session: {result['session_id']}")
```

## See Also

- [Architecture Overview](./README.md) - System overview
- [State Management](./state-management.md) - Persistence patterns
- [Daemon Architecture](./daemons.md) - Session daemon details
- [VSCode Extension](./vscode-extension.md) - UI integration
