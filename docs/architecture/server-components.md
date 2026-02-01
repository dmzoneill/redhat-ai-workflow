# Server Components Architecture

The `server/` directory contains the core MCP server infrastructure that powers the AI Workflow system. This document details each component and their interactions.

## Overview

```mermaid
graph TB
    subgraph Entry["Entry Points"]
        MAIN[main.py]
        MODULE[__main__.py]
    end

    subgraph Core["Core Infrastructure"]
        PERSONA[PersonaLoader]
        TOOL_REG[ToolRegistry]
        CONFIG[ConfigManager]
        STATE[StateManager]
    end

    subgraph Workspace["Workspace Management"]
        WS_STATE[WorkspaceState]
        WS_REG[WorkspaceRegistry]
        WS_TOOLS[WorkspaceTools]
        CHAT[ChatSession]
    end

    subgraph AutoHeal["Auto-Heal System"]
        DECORATOR[AutoHealDecorator]
        DEBUG[Debuggable]
        PATTERNS[UsagePatterns]
    end

    subgraph RealTime["Real-Time"]
        WS[WebSocketServer]
        NOTIFY[Notifications]
    end

    subgraph Utilities["Utilities"]
        UTILS[utils.py]
        PATHS[paths.py]
        HTTP[http_client.py]
        TIMEOUTS[timeouts.py]
    end

    MAIN --> PERSONA
    MAIN --> TOOL_REG
    PERSONA --> WS_REG
    WS_REG --> WS_STATE
    WS_STATE --> CHAT

    DECORATOR --> PATTERNS
    DEBUG --> DECORATOR

    MAIN --> WS

    style MAIN fill:#10b981,stroke:#059669,color:#fff
    style WS_REG fill:#6366f1,stroke:#4f46e5,color:#fff
    style DECORATOR fill:#f59e0b,stroke:#d97706,color:#fff
```

## Component Reference

### Entry Points

#### main.py

The primary entry point for the MCP server.

```mermaid
sequenceDiagram
    participant CLI
    participant Main as main.py
    participant Persona as PersonaLoader
    participant Tools as ToolRegistry
    participant WS as WebSocket
    participant Scheduler

    CLI->>Main: python -m server --agent devops
    Main->>Main: Parse arguments
    Main->>Main: create_mcp_server()

    loop For each tool module
        Main->>Tools: _load_single_tool_module()
        Tools-->>Main: Loaded tools
    end

    Main->>Persona: init_loader(server)
    Persona-->>Main: PersonaLoader instance

    Main->>Main: run_mcp_server()
    Main->>WS: start_websocket_server()
    Main->>Scheduler: init_scheduler()

    Main->>Main: server.run_stdio_async()
```

**Key Functions:**

| Function | Purpose |
|----------|---------|
| `create_mcp_server()` | Create and configure FastMCP server |
| `run_mcp_server()` | Run in stdio mode (for AI integration) |
| `init_scheduler()` | Initialize cron scheduler subsystem |

#### __main__.py

Enables `python -m server` invocation.

```python
# server/__main__.py
from .main import main
main()
```

### Core Infrastructure

#### persona_loader.py

Manages dynamic persona switching at runtime.

```mermaid
classDiagram
    class PersonaLoader {
        -server: FastMCP
        -loaded_modules: set[str]
        -_tool_to_module: dict
        +switch_persona(persona_name, ctx) Result
        +get_available_personas() list
        +get_loaded_modules() set
        -_unload_tools(module_name)
        -_load_module(module_name)
    }

    class PersonaConfig {
        +name: str
        +description: str
        +modules: list[str]
        +persona: str
        +skills: list[str]
    }

    PersonaLoader --> PersonaConfig: loads
```

**Tool Module Discovery:**

```mermaid
flowchart LR
    subgraph Discovery["Module Discovery"]
        SCAN[Scan tool_modules/]
        CHECK[Check for tools files]
        ADD[Add to registry]
    end

    subgraph FileTypes["File Types"]
        BASIC[tools_basic.py]
        EXTRA[tools_extra.py]
        LEGACY[tools.py]
    end

    SCAN --> CHECK
    CHECK --> BASIC
    CHECK --> EXTRA
    CHECK --> LEGACY
    BASIC --> ADD
    EXTRA --> ADD
    LEGACY --> ADD
```

#### config.py / config_manager.py

Configuration loading and management.

```python
# config.py - Simple config access
from server.config import get_config, get_config_value

config = get_config()
jira_url = get_config_value("jira.url", "https://issues.redhat.com")
```

```mermaid
graph LR
    subgraph Sources["Config Sources"]
        JSON[config.json]
        ENV[Environment Variables]
        DEFAULTS[Defaults]
    end

    subgraph Manager["ConfigManager"]
        LOAD[Load]
        MERGE[Merge]
        CACHE[Cache]
    end

    subgraph Access["Access"]
        GET[get_config()]
        VAL[get_config_value()]
    end

    JSON --> LOAD
    ENV --> MERGE
    DEFAULTS --> MERGE
    LOAD --> MERGE
    MERGE --> CACHE
    CACHE --> GET
    CACHE --> VAL
```

#### state_manager.py

Manages persistent state across sessions.

```mermaid
classDiagram
    class StateManager {
        -state_file: Path
        -_state: dict
        +load() dict
        +save()
        +get(key, default) Any
        +set(key, value)
        +is_service_enabled(service) bool
        +enable_service(service)
        +disable_service(service)
    }

    class ServiceState {
        +scheduler: bool
        +slack: bool
        +sprint: bool
        +meet: bool
        +cron: bool
    }

    StateManager --> ServiceState: manages
```

**State File Location:** `~/.config/aa-workflow/state.json`

### Workspace Management

#### workspace_state.py

Per-workspace and per-session context management.

```mermaid
classDiagram
    class WorkspaceRegistry {
        <<singleton>>
        -_workspaces: dict[str, WorkspaceState]
        +get_for_ctx(ctx) WorkspaceState
        +get_for_uri(uri) WorkspaceState
        +get_all_workspaces() list
        +restore_if_empty() int
        +persist()
    }

    class WorkspaceState {
        +workspace_uri: str
        +project: str
        +persona: str
        +active_session_id: str
        +sessions: dict[str, ChatSession]
        +create_session() ChatSession
        +get_session(id) ChatSession
        +get_active_session() ChatSession
    }

    class ChatSession {
        +session_id: str
        +name: str
        +persona: str
        +project: str
        +issue_key: str
        +branch: str
        +created_at: datetime
        +last_activity: datetime
        +update_activity()
    }

    WorkspaceRegistry "1" --> "*" WorkspaceState
    WorkspaceState "1" --> "*" ChatSession
```

```mermaid
sequenceDiagram
    participant Tool as MCP Tool
    participant Reg as WorkspaceRegistry
    participant WS as WorkspaceState
    participant Session as ChatSession

    Tool->>Reg: get_for_ctx(ctx)
    Reg->>Reg: Extract workspace URI from ctx

    alt Workspace exists
        Reg-->>WS: Return existing
    else New workspace
        Reg->>WS: Create WorkspaceState
        WS->>Session: create_session()
        Reg-->>WS: Return new
    end

    WS->>Session: get_active_session()
    Session-->>Tool: ChatSession with context
```

#### workspace_utils.py

Utility functions for workspace operations.

| Function | Purpose |
|----------|---------|
| `get_workspace_uri(ctx)` | Extract workspace URI from context |
| `detect_project(path)` | Auto-detect project from path |
| `format_workspace_status()` | Format status for display |

### Auto-Heal System

#### auto_heal_decorator.py

Decorator for automatic error recovery.

```mermaid
flowchart TD
    A[Decorated Tool Called] --> B[Execute Original]
    B --> C{Check Result}

    C -->|Success| D[Return Result]
    C -->|Error Pattern Detected| E[Classify Error]

    E -->|Network| F[vpn_connect]
    E -->|Auth| G[kube_login]
    E -->|Unknown| H[Return Error]

    F --> I[Retry]
    G --> I

    I --> J{Retry Success?}
    J -->|Yes| K[Log to Memory]
    K --> D
    J -->|No| H
```

**Error Patterns:**

```python
AUTH_PATTERNS = [
    "unauthorized", "401", "forbidden", "403",
    "token expired", "authentication required",
    "not authorized", "permission denied"
]

NETWORK_PATTERNS = [
    "no route to host", "connection refused",
    "network unreachable", "timeout", "dial tcp",
    "connection reset", "eof", "cannot connect"
]
```

#### debuggable.py

Source code analysis for debugging failed tools.

```mermaid
sequenceDiagram
    participant Claude
    participant Debug as debug_tool
    participant Registry as Tool Registry
    participant Source as Source Loader

    Claude->>Debug: debug_tool("failing_tool", "error")
    Debug->>Registry: Find tool source file
    Registry-->>Debug: File path

    Debug->>Source: Load source code
    Source-->>Debug: Source text

    Debug-->>Claude: {source, file, error, diagnosis}
```

#### Usage Pattern System

Six modules for learning from usage patterns:

```mermaid
graph TB
    subgraph Classification["Pattern Classification"]
        CLASSIFIER[usage_pattern_classifier.py]
    end

    subgraph Extraction["Pattern Extraction"]
        EXTRACTOR[usage_pattern_extractor.py]
    end

    subgraph Learning["Pattern Learning"]
        LEARNER[usage_pattern_learner.py]
    end

    subgraph Prevention["Prevention"]
        CHECKER[usage_pattern_checker.py]
        TRACKER[usage_prevention_tracker.py]
    end

    subgraph Context["Context Injection"]
        INJECTOR[usage_context_injector.py]
    end

    subgraph Storage["Persistence"]
        STORAGE[usage_pattern_storage.py]
        OPTIMIZER[usage_pattern_optimizer.py]
    end

    CLASSIFIER --> EXTRACTOR
    EXTRACTOR --> LEARNER
    LEARNER --> STORAGE
    CHECKER --> STORAGE
    INJECTOR --> CHECKER
    OPTIMIZER --> STORAGE
    TRACKER --> STORAGE
```

### Real-Time Communication

#### websocket_server.py

WebSocket server for real-time UI updates.

```mermaid
sequenceDiagram
    participant VSCode as VSCode Extension
    participant WS as WebSocket Server
    participant Skill as Skill Engine
    participant Memory

    VSCode->>WS: Connect ws://localhost:9876

    Skill->>WS: skill_started event
    WS->>VSCode: Broadcast event

    loop For each step
        Skill->>WS: step_completed event
        WS->>VSCode: Broadcast event
    end

    Skill->>WS: skill_completed event
    WS->>VSCode: Broadcast event
    WS->>Memory: Log execution
```

**Event Types:**

| Event | Payload |
|-------|---------|
| `skill_started` | `{skill, execution_id, inputs}` |
| `step_started` | `{step_id, step_type}` |
| `step_completed` | `{step_id, success, result, duration}` |
| `step_skipped` | `{step_id, reason}` |
| `skill_completed` | `{execution_id, success, outputs, duration}` |
| `skill_failed` | `{execution_id, error, step_id}` |
| `workspace_updated` | `{workspace_uri, sessions, persona}` |

### Utilities

#### paths.py

Centralized path management.

```python
from server.paths import (
    PROJECT_DIR,          # Root of redhat-ai-workflow
    TOOL_MODULES_DIR,     # tool_modules/
    PERSONAS_DIR,         # personas/
    SKILLS_DIR,           # skills/
    MEMORY_DIR,           # memory/
    AA_CONFIG_DIR,        # ~/.config/aa-workflow/
    WORKSPACE_STATES_FILE, # State persistence
)
```

#### utils.py

Common utility functions.

| Function | Purpose |
|----------|---------|
| `load_config()` | Load config.json |
| `run_cmd(cmd)` | Run command, return (success, output) |
| `run_cmd_full(cmd)` | Run command with full output |
| `run_cmd_shell(cmd)` | Run via shell |
| `atomic_write(path, data)` | Atomic file write |

#### http_client.py

Shared HTTP client with retry logic.

```python
from server.http_client import get_client, async_get, async_post

# Async HTTP with retries
response = await async_get("https://api.example.com/data")
```

#### timeouts.py

Centralized timeout configuration.

```python
from server.timeouts import (
    TOOL_TIMEOUT,        # Default tool timeout
    HTTP_TIMEOUT,        # HTTP request timeout
    K8S_TIMEOUT,         # Kubernetes operations
    GIT_TIMEOUT,         # Git operations
)
```

### Tool Discovery

#### tool_discovery.py

Dynamic tool module discovery.

```mermaid
flowchart TD
    A[Start Discovery] --> B[Scan tool_modules/]

    B --> C{For each aa_* dir}
    C --> D[Check src/tools_basic.py]
    C --> E[Check src/tools_extra.py]
    C --> F[Check src/tools.py]

    D -->|exists| G[Add module_basic]
    E -->|exists| H[Add module_extra]
    F -->|exists| I[Add module]

    G --> J[Return all modules]
    H --> J
    I --> J
```

#### tool_registry.py

Tool registration and management.

```mermaid
classDiagram
    class ToolRegistry {
        -_tools: dict[str, Tool]
        -_module_map: dict[str, str]
        +register(name, func, module)
        +get(name) Tool
        +list_by_module(module) list
        +get_module_for_tool(name) str
    }

    class Tool {
        +name: str
        +func: Callable
        +module: str
        +description: str
        +parameters: dict
    }

    ToolRegistry "1" --> "*" Tool
```

## Data Flow

### Request Processing

```mermaid
sequenceDiagram
    participant Cursor
    participant MCP as MCP Server
    participant Registry as WorkspaceRegistry
    participant Session as ChatSession
    participant Tool
    participant AutoHeal

    Cursor->>MCP: JSON-RPC Request
    MCP->>Registry: get_for_ctx(ctx)
    Registry-->>MCP: WorkspaceState

    MCP->>Session: Get active session
    Session-->>MCP: Session context

    MCP->>Tool: Execute tool
    Tool->>AutoHeal: Check for auto-heal
    AutoHeal-->>Tool: Apply fixes if needed
    Tool-->>MCP: Result

    MCP-->>Cursor: JSON-RPC Response
```

### State Persistence

```mermaid
flowchart LR
    subgraph Memory["In-Memory"]
        WS_REG[WorkspaceRegistry]
        SESSIONS[ChatSessions]
    end

    subgraph Disk["Disk Storage"]
        JSON[workspace_states.json]
        STATE[state.json]
    end

    subgraph Events["Triggers"]
        CREATE[Session Created]
        UPDATE[Session Updated]
        SHUTDOWN[Server Shutdown]
    end

    CREATE --> WS_REG
    WS_REG --> SESSIONS
    UPDATE --> SESSIONS

    SESSIONS --> JSON
    SHUTDOWN --> JSON
    SHUTDOWN --> STATE
```

## Configuration

### Server Startup Options

```bash
# Run with specific agent
python -m server --agent devops

# Run with specific tools
python -m server --tools git,jira,gitlab

# Run all tools (may exceed limits)
python -m server --all

# Disable scheduler
python -m server --no-scheduler
```

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `JIRA_JPAT` | Jira API token |
| `GITLAB_TOKEN` | GitLab API token |
| `ANTHROPIC_API_KEY` | Claude API key |
| `SLACK_BOT_TOKEN` | Slack bot token |
| `SLACK_APP_TOKEN` | Slack app token |

## File Locations

| Path | Purpose |
|------|---------|
| `~/.config/aa-workflow/` | User configuration |
| `~/.config/aa-workflow/state.json` | Service state |
| `~/.config/aa-workflow/workspace_states.json` | Session persistence |
| `~/.cache/aa-workflow/vectors/` | Vector database |
| `memory/` | Project memory files |

## See Also

- [Architecture Overview](./README.md) - System design
- [MCP Implementation](./mcp-implementation.md) - Protocol details
- [Auto-Heal System](./auto-heal.md) - Error recovery
- [Session Management](./session-management.md) - Session handling
- [State Management](./state-management.md) - Persistence patterns
