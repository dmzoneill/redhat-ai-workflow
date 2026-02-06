# Request Lifecycle

> End-to-end flow of an MCP tool request

## Diagram

```mermaid
sequenceDiagram
    participant User as User
    participant Cursor as Cursor IDE
    participant Claude as Claude/LLM
    participant MCP as MCP Server
    participant Registry as ToolRegistry
    participant Tool as Tool Function
    participant External as External API

    User->>Cursor: Natural language request
    Cursor->>Claude: Send message

    Claude->>Claude: Parse intent
    Claude->>MCP: Tool call request

    MCP->>Registry: Look up tool
    Registry-->>MCP: Tool function

    MCP->>Tool: Execute with args
    Tool->>External: API call
    External-->>Tool: Response
    Tool-->>MCP: Result

    MCP-->>Claude: Tool result
    Claude->>Claude: Format response
    Claude-->>Cursor: Response
    Cursor-->>User: Display result
```

## Request Phases

```mermaid
flowchart TB
    subgraph Phase1[1. User Input]
        INPUT[Natural language]
        PARSE[Intent parsing]
    end

    subgraph Phase2[2. Tool Selection]
        MATCH[Match to tool]
        VALIDATE[Validate args]
    end

    subgraph Phase3[3. Execution]
        CALL[Call tool function]
        API[External API call]
        RESULT[Process result]
    end

    subgraph Phase4[4. Response]
        FORMAT[Format output]
        DISPLAY[Display to user]
    end

    Phase1 --> Phase2
    Phase2 --> Phase3
    Phase3 --> Phase4
```

## MCP Protocol Flow

```mermaid
sequenceDiagram
    participant Client as MCP Client
    participant Server as MCP Server
    participant Handler as Tool Handler

    Note over Client,Server: JSON-RPC over stdio

    Client->>Server: {"method": "tools/call", "params": {...}}
    Server->>Server: Validate request
    Server->>Handler: Execute tool

    alt Success
        Handler-->>Server: Result
        Server-->>Client: {"result": {...}}
    else Error
        Handler-->>Server: Error
        Server-->>Client: {"error": {...}}
    end
```

## Tool Execution Detail

```mermaid
flowchart TB
    subgraph Input[Input Processing]
        RECEIVE[Receive call]
        PARSE_ARGS[Parse arguments]
        VALIDATE[Validate schema]
    end

    subgraph Execution[Tool Execution]
        LOOKUP[Lookup handler]
        INJECT[Inject context]
        EXECUTE[Execute function]
    end

    subgraph Output[Output Processing]
        FORMAT[Format result]
        LOG[Log to memory]
        RETURN[Return response]
    end

    Input --> Execution
    Execution --> Output
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| MCP Server | `server/main.py` | Request handling |
| ToolRegistry | `server/tool_registry.py` | Tool lookup |
| Tool handlers | `tool_modules/*/src/*.py` | Tool functions |

## Related Diagrams

- [MCP Server Core](../01-server/mcp-server-core.md)
- [Tool Registry](../01-server/tool-registry.md)
- [Skill Execution Flow](../04-skills/skill-execution-flow.md)
