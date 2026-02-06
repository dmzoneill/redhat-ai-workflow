# Memory Operations

> Read, write, append, and query operations

## Diagram

```mermaid
flowchart TB
    subgraph Operations[Memory Operations]
        READ[memory_read<br/>Read YAML path]
        WRITE[memory_write<br/>Write YAML path]
        APPEND[memory_append<br/>Append to list/dict]
        QUERY[memory_query<br/>Search memory]
        ASK[memory_ask<br/>Unified query]
    end

    subgraph Storage[Storage Layer]
        YAML[YAML Files]
        CACHE[In-Memory Cache]
    end

    subgraph External[External Sources]
        ADAPTERS[Memory Adapters]
    end

    READ --> CACHE
    CACHE --> YAML
    WRITE --> YAML
    APPEND --> YAML
    QUERY --> YAML
    ASK --> YAML
    ASK --> ADAPTERS
```

## Operation Details

### memory_read

```mermaid
sequenceDiagram
    participant Tool as memory_read
    participant Daemon as MemoryDaemon
    participant Cache as Cache
    participant File as YAML File

    Tool->>Daemon: read(path)

    alt Cache hit
        Daemon->>Cache: get(path)
        Cache-->>Daemon: data
    else Cache miss
        Daemon->>File: read(path.yaml)
        File-->>Daemon: yaml_content
        Daemon->>Daemon: parse YAML
        Daemon->>Cache: set(path, data)
    end

    Daemon-->>Tool: dict
```

### memory_write

```mermaid
sequenceDiagram
    participant Tool as memory_write
    participant Daemon as MemoryDaemon
    participant Lock as File Lock
    participant File as YAML File
    participant Cache as Cache

    Tool->>Daemon: write(path, data)
    Daemon->>Lock: acquire()
    Lock-->>Daemon: locked

    Daemon->>Daemon: serialize to YAML
    Daemon->>File: write atomically
    File-->>Daemon: success

    Daemon->>Cache: invalidate(path)
    Daemon->>Lock: release()

    Daemon-->>Tool: success
```

### memory_append

```mermaid
sequenceDiagram
    participant Tool as memory_append
    participant Daemon as MemoryDaemon
    participant File as YAML File

    Tool->>Daemon: append(path, key, value)
    Daemon->>Daemon: read current
    Daemon->>Daemon: append to key

    alt Key is list
        Daemon->>Daemon: data[key].append(value)
    else Key is dict
        Daemon->>Daemon: data[key].update(value)
    end

    Daemon->>File: write updated
    Daemon-->>Tool: success
```

### memory_ask

```mermaid
sequenceDiagram
    participant Tool as memory_ask
    participant Interface as MemoryInterface
    participant YAML as YAML Adapter
    participant Jira as Jira Adapter
    participant GitLab as GitLab Adapter

    Tool->>Interface: ask(question, sources)

    par Query fast sources
        Interface->>YAML: query(question)
        YAML-->>Interface: yaml_results
    end

    opt include_slow=true
        par Query slow sources
            Interface->>Jira: query(question)
            Jira-->>Interface: jira_results
            Interface->>GitLab: query(question)
            GitLab-->>Interface: gitlab_results
        end
    end

    Interface->>Interface: merge & rank results
    Interface-->>Tool: formatted response
```

## Operation Matrix

| Operation | Read | Write | External | Cached |
|-----------|------|-------|----------|--------|
| memory_read | ✓ | | | ✓ |
| memory_write | | ✓ | | invalidates |
| memory_append | ✓ | ✓ | | invalidates |
| memory_query | ✓ | | | ✓ |
| memory_ask | ✓ | | ✓ | partial |

## Components

| Component | File | Description |
|-----------|------|-------------|
| memory_read | `memory_tools.py` | Read operation |
| memory_write | `memory_tools.py` | Write operation |
| memory_append | `memory_tools.py` | Append operation |
| memory_ask | `memory_unified.py` | Unified query |

## Related Diagrams

- [Memory Architecture](./memory-architecture.md)
- [Memory Paths](./memory-paths.md)
- [Unified Memory Query](./unified-memory-query.md)
