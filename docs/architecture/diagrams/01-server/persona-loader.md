# Persona Loader

> Dynamic tool loading and persona switching at runtime

## Diagram

```mermaid
sequenceDiagram
    participant User as User/Claude
    participant MCP as MCP Server
    participant Loader as PersonaLoader
    participant Config as personas/*.yaml
    participant Tools as Tool Modules
    participant WS as WorkspaceState
    participant Client as IDE Client

    User->>MCP: persona_load("devops")
    MCP->>Loader: switch_persona("devops", ctx)
    Loader->>Config: load_persona_config("devops")
    Config-->>Loader: {tools: [...], description: ...}

    Loader->>Loader: _clear_non_core_tools()
    
    loop For each tool module
        Loader->>Tools: _load_tool_module(module)
        Tools-->>Loader: new_tool_names[]
        Loader->>Loader: _tool_to_module[tool] = module
    end

    Loader->>WS: update workspace persona
    Loader->>Client: send_tool_list_changed()
    Loader-->>MCP: {success, tool_count, persona_context}
```

## Class Structure

```mermaid
classDiagram
    class PersonaLoader {
        +server: FastMCP
        +current_persona: str
        +loaded_modules: set~str~
        -_tool_to_module: dict
        -_state_lock: asyncio.Lock
        +load_persona_config(name): dict
        +switch_persona(name, ctx): dict
        +get_workspace_persona(ctx): str
        +set_workspace_persona(ctx, name)
        +get_status(): dict
        +get_workspace_status(ctx): dict
        -_load_tool_module(name): list~str~
        -_unload_module_tools(name): int
        -_clear_non_core_tools(): int
    }

    class CORE_TOOLS {
        <<constant>>
        persona_load
        persona_list
        session_start
        debug_tool
        memory_ask
        memory_search
        memory_store
        memory_health
        memory_list_adapters
    }

    class PersonaConfig {
        +name: str
        +description: str
        +tools: list~str~
        +persona: str
        +persona_append: str
    }

    PersonaLoader --> CORE_TOOLS : preserves
    PersonaLoader --> PersonaConfig : loads
```

## Persona Switching State

```mermaid
stateDiagram-v2
    [*] --> Idle: Server started

    Idle --> Loading: persona_load() called
    Loading --> ClearingTools: Load config success
    Loading --> Error: Config not found

    ClearingTools --> LoadingModules: Non-core tools removed
    LoadingModules --> LoadingModules: Load next module
    LoadingModules --> Updating: All modules loaded

    Updating --> NotifyingClient: Workspace updated
    NotifyingClient --> Idle: tool_list_changed sent

    Error --> Idle: Return error response
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| PersonaLoader | `server/persona_loader.py` | Main loader class |
| CORE_TOOLS | `server/persona_loader.py` | Protected tool names |
| discover_tool_modules | `server/persona_loader.py` | Module discovery |
| get_available_modules | `server/persona_loader.py` | Available modules cache |
| init_loader | `server/persona_loader.py` | Global instance init |
| get_loader | `server/persona_loader.py` | Get global instance |

## Persona Config Structure

```yaml
# personas/devops.yaml
name: DevOps
description: Infrastructure and deployment tools
tools:
  - k8s_basic
  - bonfire_basic
  - jira_basic
  - quay_basic
  - konflux_basic
persona: personas/devops.md
```

## Related Diagrams

- [MCP Server Core](./mcp-server-core.md)
- [Tool Registry](./tool-registry.md)
- [Persona Architecture](../05-personas/persona-architecture.md)
