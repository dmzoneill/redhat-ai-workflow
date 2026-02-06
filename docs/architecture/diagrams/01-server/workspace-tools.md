# Workspace Tools

> Workspace state management and utilities

## Diagram

```mermaid
classDiagram
    class WorkspaceRegistry {
        <<singleton>>
        -_workspaces: dict~str,WorkspaceState~
        -_lock: asyncio.Lock
        +get_for_ctx(ctx): WorkspaceState
        +get_or_create(uri): WorkspaceState
        +list_workspaces(): list~str~
        +save_to_disk()
        +restore_if_empty(): int
    }

    class WorkspaceState {
        +workspace_uri: str
        +persona: str
        +project: str
        +active_tools: set~str~
        +sessions: dict~str,Session~
        +filter_cache: dict
        +created_at: datetime
        +get_active_session(): Session
        +create_session(persona): Session
        +clear_filter_cache()
    }

    class Session {
        +session_id: str
        +workspace_uri: str
        +persona: str
        +project: str
        +name: str
        +static_tool_count: int
        +created_at: datetime
        +last_active: datetime
    }

    class workspace_utils {
        +get_workspace_root(): Path
        +get_project_name(): str
        +detect_project_type(): str
        +find_config_file(): Path
    }

    WorkspaceRegistry --> WorkspaceState : manages
    WorkspaceState --> Session : contains
```

## Workspace Detection Flow

```mermaid
sequenceDiagram
    participant MCP as MCP Tool Call
    participant Registry as WorkspaceRegistry
    participant State as WorkspaceState
    participant Utils as workspace_utils

    MCP->>Registry: get_for_ctx(ctx)
    Registry->>Registry: Extract workspace URI from ctx

    alt Workspace exists
        Registry-->>MCP: Existing WorkspaceState
    else New workspace
        Registry->>State: Create WorkspaceState
        State->>Utils: Detect project info
        Utils-->>State: Project name, type
        Registry-->>MCP: New WorkspaceState
    end
```

## State Persistence

```mermaid
flowchart TB
    subgraph Runtime[Runtime State]
        REGISTRY[WorkspaceRegistry]
        STATES[WorkspaceState instances]
        SESSIONS[Session objects]
    end

    subgraph Disk[Disk Persistence]
        JSON_FILE[(~/.config/aa-workflow/workspaces.json)]
    end

    subgraph Operations[Operations]
        SAVE[save_to_disk]
        RESTORE[restore_if_empty]
    end

    REGISTRY --> STATES
    STATES --> SESSIONS

    SAVE --> JSON_FILE
    JSON_FILE --> RESTORE
    RESTORE --> REGISTRY
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| WorkspaceRegistry | `server/workspace_state.py` | Singleton registry |
| WorkspaceState | `server/workspace_state.py` | Per-workspace state |
| Session | `server/workspace_state.py` | Session within workspace |
| workspace_utils | `server/workspace_utils.py` | Utility functions |
| workspace_tools | `server/workspace_tools.py` | MCP tools for workspace |

## Workspace State Fields

| Field | Type | Description |
|-------|------|-------------|
| workspace_uri | str | Unique workspace identifier |
| persona | str | Current active persona |
| project | str | Detected project name |
| active_tools | set | Currently loaded tools |
| sessions | dict | Sessions in this workspace |
| filter_cache | dict | NPU filter cache |
| created_at | datetime | When workspace was created |

## Session Fields

| Field | Type | Description |
|-------|------|-------------|
| session_id | str | Unique session ID |
| workspace_uri | str | Parent workspace |
| persona | str | Session's persona |
| project | str | Session's project |
| name | str | User-friendly name |
| static_tool_count | int | Tools loaded |
| created_at | datetime | Session creation time |
| last_active | datetime | Last activity time |

## Related Diagrams

- [Session Builder](./session-builder.md)
- [Persona Loader](./persona-loader.md)
- [State Manager](./state-manager.md)
