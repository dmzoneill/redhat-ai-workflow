# Tool Registry

> Tool registration and discovery system

## Diagram

```mermaid
classDiagram
    class ToolRegistry {
        +server: FastMCP
        +tools: list~str~
        +tool(**kwargs) decorator
        +count: int
        +list_tools(): list~str~
        +__len__(): int
        +__contains__(name): bool
    }

    class FastMCP {
        +tool() decorator
        +remove_tool(name)
        +list_tools()
        +providers: list
    }

    class ToolModule {
        +register_tools(server)
        +tools_basic.py
        +tools_core.py
        +tools_extra.py
    }

    class tool_discovery {
        +discover_tool_modules()
        +get_available_modules()
        +is_valid_module(name)
    }

    class tool_paths {
        +PROJECT_DIR
        +TOOL_MODULES_DIR
        +get_tools_file_path(name)
        +TOOLS_FILE
        +TOOLS_BASIC_FILE
        +TOOLS_EXTRA_FILE
    }

    ToolRegistry --> FastMCP : wraps
    ToolModule --> ToolRegistry : uses
    tool_discovery --> tool_paths : uses
    FastMCP --> ToolModule : loads
```

## Registration Flow

```mermaid
sequenceDiagram
    participant Module as Tool Module
    participant Registry as ToolRegistry
    participant FastMCP as FastMCP Server

    Module->>Registry: registry = ToolRegistry(server)
    
    loop For each tool function
        Module->>Registry: @registry.tool()
        Registry->>Registry: tools.append(tool_name)
        Registry->>FastMCP: server.tool()(func)
    end

    Module-->>FastMCP: return registry.count
```

## Tool Module Structure

```mermaid
graph TB
    subgraph ToolModule[aa_example/]
        PYPROJECT[pyproject.toml]
        subgraph src[src/]
            INIT[__init__.py]
            BASIC[tools_basic.py]
            CORE[tools_core.py]
            EXTRA[tools_extra.py]
            ADAPTER[adapter.py]
        end
    end

    BASIC --> |"Essential tools"| REGISTRY[ToolRegistry]
    CORE --> |"Core tools"| REGISTRY
    EXTRA --> |"Extended tools"| REGISTRY
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| ToolRegistry | `server/tool_registry.py` | Decorator-based tool tracking |
| tool_discovery | `server/tool_discovery.py` | Module discovery |
| tool_paths | `server/tool_paths.py` | Path resolution utilities |
| tools_basic.py | `tool_modules/aa_*/src/` | Essential tools |
| tools_core.py | `tool_modules/aa_*/src/` | Core tools |
| tools_extra.py | `tool_modules/aa_*/src/` | Extended tools |

## Tool Tiers

| Tier | File | Purpose |
|------|------|---------|
| basic | `tools_basic.py` | Essential, always-needed tools |
| core | `tools_core.py` | Core functionality |
| extra | `tools_extra.py` | Extended/advanced tools |
| style | `tools_style.py` | Style-related tools |

## Related Diagrams

- [MCP Server Core](./mcp-server-core.md)
- [Persona Loader](./persona-loader.md)
- [Tool Module Structure](../03-tools/tool-module-structure.md)
