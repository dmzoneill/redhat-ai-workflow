# MCP Server Core

> FastMCP server entry point and core initialization flow

## Diagram

```mermaid
classDiagram
    class FastMCP {
        +name: str
        +providers: list
        +tool() decorator
        +remove_tool(name)
        +list_tools()
        +run_stdio_async()
    }

    class main {
        +create_mcp_server(name, tools)
        +run_mcp_server(server, enable_scheduler)
        +init_scheduler(server)
        +stop_scheduler()
        +main()
    }

    class ServerComponents {
        +PersonaLoader
        +SkillEngine
        +ToolRegistry
        +StateManager
        +ConfigManager
        +SessionBuilder
        +WebSocketServer
    }

    class ToolLoading {
        +get_available_modules()
        +is_valid_module(name)
        +load_agent_config(agent)
        +get_tool_module(name)
        +_load_single_tool_module()
    }

    class Scheduler {
        +init_cron_scheduler()
        +init_poll_engine()
        +init_notification_engine()
        +start_scheduler()
    }

    main --> FastMCP : creates
    main --> ToolLoading : uses
    main --> Scheduler : initializes
    FastMCP --> ServerComponents : integrates
    ToolLoading --> FastMCP : registers tools
```

## Initialization Flow

```mermaid
sequenceDiagram
    participant CLI as Command Line
    participant Main as main.py
    participant FastMCP as FastMCP Server
    participant Loader as PersonaLoader
    participant Tools as Tool Modules
    participant Debug as Debuggable
    participant WS as WebSocket Server
    participant MAL as Memory Abstraction
    participant Scheduler as Scheduler

    CLI->>Main: python -m server --agent devops
    Main->>Main: setup_logging()
    Main->>Main: load_agent_config("devops")
    Main->>FastMCP: create_mcp_server(name, tools)

    loop For each tool module
        Main->>Main: _get_tool_names_sync() [before]
        FastMCP->>Tools: _load_single_tool_module()
        Tools-->>FastMCP: register_tools(server)
        Main->>Main: _get_tool_names_sync() [after]
    end

    Main->>Debug: register_debug_tool(server)
    Main->>Debug: wrap_server_tools_runtime(server)
    Main->>Loader: init_loader(server)
    Loader-->>Main: PersonaLoader instance
    Main->>Main: WorkspaceRegistry.restore_if_empty()

    Main->>Main: run_mcp_server(server)
    Main->>WS: start_websocket_server()
    Main->>MAL: discover_and_load_all_adapters()
    Main->>MAL: MemoryInterface(adapters, ws_server)
    Main->>Scheduler: init_scheduler(server)
    Main->>FastMCP: run_stdio_async()
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| FastMCP | External library | MCP protocol implementation |
| main | `server/main.py` | Entry point and server creation |
| create_mcp_server | `server/main.py` | Factory function for server |
| run_mcp_server | `server/main.py` | Async server runner |
| init_scheduler | `server/main.py` | Scheduler subsystem init |
| stop_scheduler | `server/main.py` | Graceful scheduler shutdown |
| load_agent_config | `server/main.py` | Load persona YAML |
| _get_tool_names_sync | `server/main.py` | Get tools from FastMCP v3 providers |
| _load_single_tool_module | `server/main.py` | Load and register one tool module |
| _register_debug_for_module | `server/main.py` | Register debug hooks for module |
| setup_logging | `server/main.py` | Configure journald-compatible logging |
| MemoryInterface | `services/memory_abstraction/` | Memory abstraction layer |

## Command Line Options

| Option | Description |
|--------|-------------|
| `--agent NAME` | Load tools for persona (devops, developer, etc.) |
| `--tools LIST` | Comma-separated tool modules |
| `--all` | Load all available tools |
| `--name NAME` | Custom server name |
| `--no-scheduler` | Disable cron scheduler |

## Related Diagrams

- [Tool Registry](./tool-registry.md)
- [Persona Loader](./persona-loader.md)
- [Config System](./config-system.md)
