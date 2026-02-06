# Workspace State Management

> Per-workspace and per-session context management for MCP server

## Diagram

```mermaid
classDiagram
    class WorkspaceRegistry {
        <<singleton>>
        -_workspaces: dict~str, WorkspaceState~
        -_access_count: int
        +get_for_ctx(ctx): WorkspaceState
        +get_or_create(uri): WorkspaceState
        +save_to_disk()
        +restore_if_empty()
        +cleanup_stale()
    }

    class WorkspaceState {
        +workspace_uri: str
        +project: str
        +sessions: dict~str, ChatSession~
        +active_session_id: str
        +create_session(): ChatSession
        +get_active_session(): ChatSession
        +get_session(id): ChatSession
        +cleanup_stale_sessions()
    }

    class ChatSession {
        +session_id: str
        +project: str
        +persona: str
        +active_issue: str
        +active_branch: str
        +tool_counts: int
        +tool_filter_cache: dict
        +created_at: datetime
        +last_activity: datetime
        +touch()
        +to_dict(): dict
        +from_dict(data): ChatSession
    }

    WorkspaceRegistry --> WorkspaceState : manages
    WorkspaceState --> ChatSession : contains
```

## Architecture Flow

```mermaid
sequenceDiagram
    participant Tool as MCP Tool
    participant WR as WorkspaceRegistry
    participant WS as WorkspaceState
    participant Session as ChatSession
    participant FS as Filesystem

    Tool->>WR: get_for_ctx(ctx)
    WR->>WR: ctx.session.list_roots()
    WR->>WR: Get workspace URI

    alt Workspace exists
        WR-->>Tool: existing WorkspaceState
    else New workspace
        WR->>WS: create WorkspaceState
        WR-->>Tool: new WorkspaceState
    end

    Tool->>WS: get_active_session()

    alt Session exists
        WS-->>Tool: existing ChatSession
    else No active session
        Tool->>WS: create_session()
        WS->>Session: new ChatSession
        WS-->>Tool: new session
    end

    Tool->>Session: touch()
    WR->>FS: save_to_disk() [periodically]
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| `ChatSession` | `server/workspace_state.py` | Per-chat session state |
| `WorkspaceState` | `server/workspace_state.py` | Per-workspace state container |
| `WorkspaceRegistry` | `server/workspace_state.py` | Global registry singleton |
| `get_default_persona` | `server/workspace_state.py` | Read default persona from config |
| `get_cursor_chat_info_from_db` | `server/workspace_state.py` | Read chat info from Cursor's DB |

## ChatSession

Each chat session maintains its own:
- **session_id**: Unique identifier (from Cursor DB or generated)
- **project**: Which project is being worked on
- **persona**: Current persona (developer, devops, etc.)
- **active_issue**: Current Jira issue key
- **active_branch**: Current git branch
- **tool_counts**: Number of tools available
- **tool_filter_cache**: NPU filter cache
- **timestamps**: created_at, last_activity

## WorkspaceState

A workspace (Cursor folder) can have multiple chat sessions:
- **workspace_uri**: Cursor workspace identifier
- **project**: Shared project context
- **sessions**: Map of session_id to ChatSession
- **active_session_id**: Currently active session

## WorkspaceRegistry

Singleton registry that manages all workspaces:
- **get_for_ctx(ctx)**: Get workspace for MCP context
- **save_to_disk()**: Persist to ~/.config/aa-workflow/workspace_states.json
- **restore_if_empty()**: Load from disk on startup
- **cleanup_stale()**: Remove sessions older than 24 hours

## Persistence

Sessions persist across server restarts:

```
~/.config/aa-workflow/workspace_states.json
```

```json
{
  "file:///home/user/project": {
    "workspace_uri": "file:///home/user/project",
    "project": "automation-analytics-backend",
    "active_session_id": "abc123",
    "sessions": {
      "abc123": {
        "session_id": "abc123",
        "project": "automation-analytics-backend",
        "persona": "developer",
        "created_at": "2026-02-04T09:00:00Z"
      }
    }
  }
}
```

## Usage

```python
from server.workspace_state import WorkspaceRegistry

# In a tool function with MCP context
workspace = await WorkspaceRegistry.get_for_ctx(ctx)

# Get active session
session = workspace.get_active_session()
if session:
    print(f"Persona: {session.persona}")
    print(f"Project: {session.project}")

# Create new session
session = workspace.create_session()
session.persona = "developer"
session.project = "my-project"

# Save periodically
WorkspaceRegistry.save_to_disk()
```

## Session Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Created: session_start()
    Created --> Active: First tool call
    Active --> Active: touch()
    Active --> Stale: No activity > 24h
    Stale --> [*]: cleanup_stale()
```

## Configuration

- **SESSION_STALE_HOURS**: 24 hours (sessions older are cleaned up)
- **MAX_FILTER_CACHE_SIZE**: 50 entries (per-session NPU cache limit)
- **DEFAULT_PROJECT**: "redhat-ai-workflow" (fallback)
- **DEFAULT_WORKSPACE**: "default" (when list_roots unavailable)

## Related Diagrams

- [MCP Server Core](./mcp-server-core.md)
- [Session Builder](./session-builder.md)
- [State Manager](./state-manager.md)
