# Memory Architecture

> YAML-based persistent memory system

## Diagram

```mermaid
graph TB
    subgraph Interface[Memory Interface]
        TOOLS[Memory Tools]
        DAEMON[Memory Daemon]
        ADAPTERS[Memory Adapters]
    end

    subgraph Storage[Memory Storage]
        STATE[state/<br/>Runtime state]
        LEARNED[learned/<br/>Patterns & fixes]
        KNOWLEDGE[knowledge/<br/>Domain knowledge]
        SESSIONS[sessions/<br/>Session history]
    end

    subgraph External[External Sources]
        JIRA[Jira]
        GITLAB[GitLab]
        SLACK[Slack]
        INSCOPE[InScope]
        CODE[Code Search]
    end

    TOOLS --> STATE
    TOOLS --> LEARNED
    TOOLS --> KNOWLEDGE
    TOOLS --> SESSIONS

    DAEMON --> Storage
    ADAPTERS --> External
```

## Class Structure

```mermaid
classDiagram
    class MemoryInterface {
        +read(path): dict
        +write(path, data): None
        +append(path, key, value): None
        +query(question): list
        +ask(question, sources): str
    }

    class MemoryDaemon {
        +cache: dict
        +file_watcher: FileWatcher
        +read(path): dict
        +write(path, data): None
        +invalidate(path): None
    }

    class MemoryAdapter {
        <<interface>>
        +name: str
        +latency_class: str
        +query(question): list
        +get_context(topic): str
    }

    class YAMLAdapter {
        +paths: list
        +query(question): list
    }

    class JiraAdapter {
        +client: JiraClient
        +query(question): list
    }

    MemoryInterface --> MemoryDaemon
    MemoryInterface --> MemoryAdapter
    MemoryAdapter <|-- YAMLAdapter
    MemoryAdapter <|-- JiraAdapter
```

## Memory Flow

```mermaid
sequenceDiagram
    participant Tool as memory_read
    participant Interface as MemoryInterface
    participant Daemon as MemoryDaemon
    participant Cache as In-Memory Cache
    participant YAML as YAML Files

    Tool->>Interface: read("state/current_work")
    Interface->>Daemon: D-Bus: Read(path)

    alt Cache hit
        Daemon->>Cache: Get cached data
        Cache-->>Daemon: Cached YAML
    else Cache miss
        Daemon->>YAML: Read file
        YAML-->>Daemon: File contents
        Daemon->>Cache: Store in cache
    end

    Daemon-->>Interface: YAML data
    Interface-->>Tool: Parsed dict
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| Memory tools | `tool_modules/aa_workflow/src/memory_tools.py` | MCP tools |
| Memory daemon | `services/memory/daemon.py` | Background service |
| Memory adapters | `tool_modules/*/src/adapter.py` | External sources |
| YAML storage | `memory/` | File storage |

## Related Diagrams

- [Memory Paths](./memory-paths.md)
- [Memory Daemon](../02-services/memory-daemon.md)
- [Adapter Pattern](../03-tools/adapter-pattern.md)
