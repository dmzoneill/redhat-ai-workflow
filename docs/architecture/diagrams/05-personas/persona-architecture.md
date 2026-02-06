# Persona Architecture

> Dynamic persona system for tool loading

## Diagram

```mermaid
classDiagram
    class PersonaLoader {
        +server: FastMCP
        +personas_dir: Path
        +current_persona: str
        +loaded_modules: set
        +switch_persona(name): dict
        +get_current(): str
        +list_personas(): list
        -_load_persona_config(name): dict
        -_load_module(module_name): None
        -_unload_module(module_name): None
    }

    class PersonaConfig {
        +name: str
        +description: str
        +tools: list~str~
        +extends: str
        +context: dict
    }

    class ToolModule {
        +name: str
        +tools: list~Tool~
        +register(server): None
        +unregister(server): None
    }

    class Tool {
        +name: str
        +description: str
        +handler: function
        +schema: dict
    }

    PersonaLoader --> PersonaConfig : loads
    PersonaLoader --> ToolModule : manages
    ToolModule --> Tool : contains
```

## Loading Flow

```mermaid
sequenceDiagram
    participant User as User/Claude
    participant Tool as persona_load tool
    participant Loader as PersonaLoader
    participant YAML as Persona YAML
    participant Registry as ToolRegistry
    participant MCP as FastMCP

    User->>Tool: persona_load("devops")
    Tool->>Loader: switch_persona("devops")

    Loader->>YAML: Load devops.yaml
    YAML-->>Loader: PersonaConfig

    alt Has extends
        Loader->>YAML: Load base persona
        YAML-->>Loader: Base config
        Loader->>Loader: Merge configs
    end

    Loader->>Loader: Calculate modules to unload
    loop For each module to unload
        Loader->>Registry: Unregister tools
        Loader->>MCP: Remove tools
    end

    Loader->>Loader: Calculate modules to load
    loop For each module to load
        Loader->>Registry: Register tools
        Loader->>MCP: Add tools
    end

    Loader->>MCP: Notify tools/list_changed
    Loader-->>Tool: Switch result
    Tool-->>User: "Switched to devops"
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| PersonaLoader | `server/persona_loader.py` | Main loader class |
| persona_load | `tool_modules/aa_workflow/src/tools_core.py` | MCP tool |
| persona_list | `tool_modules/aa_workflow/src/tools_basic.py` | List personas |
| Persona files | `personas/*.yaml` | Persona definitions |

## Core Tools Protection

```mermaid
flowchart TB
    subgraph CoreTools[CORE_TOOLS - Never Unloaded]
        WORKFLOW[aa_workflow]
        MEMORY[aa_memory]
        OLLAMA[aa_ollama]
    end

    subgraph PersonaTools[Persona-Specific Tools]
        JIRA[aa_jira]
        GITLAB[aa_gitlab]
        K8S[aa_k8s]
        BONFIRE[aa_bonfire]
    end

    subgraph Switch[Persona Switch]
        UNLOAD[Unload old tools]
        LOAD[Load new tools]
    end

    UNLOAD --> PersonaTools
    LOAD --> PersonaTools
    CoreTools -.->|Protected| UNLOAD
```

## Related Diagrams

- [Persona Tool Mapping](./persona-tool-mapping.md)
- [Persona Definitions](./persona-definitions.md)
- [Persona Loading Flow](./persona-loading-flow.md)
