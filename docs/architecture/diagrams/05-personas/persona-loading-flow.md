# Persona Loading Flow

> Detailed persona switch process

## Diagram

```mermaid
sequenceDiagram
    participant User as User/Claude
    participant Tool as persona_load
    participant Loader as PersonaLoader
    participant Config as Config Files
    participant Registry as ToolRegistry
    participant MCP as FastMCP
    participant Cursor as Cursor IDE

    User->>Tool: persona_load("devops")
    Tool->>Loader: switch_persona("devops")

    Note over Loader: Phase 1: Load Config
    Loader->>Config: Read devops.yaml
    Config-->>Loader: PersonaConfig

    alt Has extends
        Loader->>Config: Read base persona
        Config-->>Loader: Base config
        Loader->>Loader: Merge tool lists
    end

    Note over Loader: Phase 2: Calculate Changes
    Loader->>Loader: current_modules = get_loaded()
    Loader->>Loader: new_modules = persona.tools
    Loader->>Loader: to_unload = current - new - CORE
    Loader->>Loader: to_load = new - current

    Note over Loader: Phase 3: Unload Old Tools
    loop For each module in to_unload
        Loader->>Registry: Get module tools
        Registry-->>Loader: Tool list
        loop For each tool
            Loader->>MCP: server.remove_tool(name)
        end
        Loader->>Loader: loaded_modules.remove(module)
    end

    Note over Loader: Phase 4: Load New Tools
    loop For each module in to_load
        Loader->>Loader: import_module(module)
        Loader->>Registry: Get module tools
        Registry-->>Loader: Tool list
        loop For each tool
            Loader->>MCP: server.add_tool(tool)
        end
        Loader->>Loader: loaded_modules.add(module)
    end

    Note over Loader: Phase 5: Notify Clients
    Loader->>MCP: Emit tools/list_changed
    MCP->>Cursor: WebSocket notification
    Cursor->>Cursor: Refresh tool list

    Loader-->>Tool: {status, loaded, unloaded}
    Tool-->>User: "Switched to devops (74 tools)"
```

## State Changes

```mermaid
stateDiagram-v2
    [*] --> Idle: Server started

    Idle --> Loading: persona_load() called
    Loading --> Validating: Load config
    Validating --> Calculating: Config valid
    Validating --> Error: Config invalid

    Calculating --> Unloading: Calculate changes
    Unloading --> LoadingNew: Unload complete
    LoadingNew --> Notifying: Load complete
    Notifying --> Idle: Notification sent

    Error --> Idle: Return error
```

## Module Resolution

```mermaid
flowchart TB
    subgraph Input[Persona Config]
        TOOLS["tools: [aa_git_basic, aa_jira_core]"]
    end

    subgraph Resolution[Module Resolution]
        PARSE[Parse module names]
        LOCATE[Locate in tool_modules/]
        IMPORT[Import Python module]
        REGISTER[Get registered tools]
    end

    subgraph Output[Loaded Tools]
        TOOL1[git_status]
        TOOL2[git_log]
        TOOL3[jira_transition]
        TOOL4[jira_add_comment]
    end

    TOOLS --> PARSE
    PARSE --> LOCATE
    LOCATE --> IMPORT
    IMPORT --> REGISTER
    REGISTER --> TOOL1
    REGISTER --> TOOL2
    REGISTER --> TOOL3
    REGISTER --> TOOL4
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| switch_persona | `persona_loader.py` | Main switch method |
| _load_module | `persona_loader.py` | Module import |
| _unload_module | `persona_loader.py` | Module removal |
| CORE_TOOLS | `persona_loader.py` | Protected modules |

## Performance Considerations

| Phase | Typical Duration | Notes |
|-------|-----------------|-------|
| Load config | <10ms | YAML parsing |
| Calculate changes | <5ms | Set operations |
| Unload modules | 50-200ms | Per module |
| Load modules | 100-500ms | Per module |
| Notify clients | <50ms | WebSocket |

## Related Diagrams

- [Persona Architecture](./persona-architecture.md)
- [Tool Registry](../01-server/tool-registry.md)
- [Persona Tool Mapping](./persona-tool-mapping.md)
