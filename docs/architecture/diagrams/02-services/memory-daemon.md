# Memory Daemon

> Memory service for YAML-based persistence

## Diagram

```mermaid
graph TB
    subgraph Clients[Memory Clients]
        MCP[MCP Server]
        DAEMONS[Other Daemons]
        TOOLS[Tool Modules]
        VSCODE[VSCode Extension]
    end

    subgraph Daemon[Memory Daemon]
        INTERFACE[D-Bus Interface]
        CACHE[Memory Cache]
        WRITER[YAML Writer]
        WATCHER[File Watcher]
    end

    subgraph Storage[Storage Layer]
        STATE[state/]
        LEARNED[learned/]
        KNOWLEDGE[knowledge/]
        SESSIONS[sessions/]
    end

    MCP --> INTERFACE
    DAEMONS --> INTERFACE
    TOOLS --> INTERFACE
    VSCODE --> INTERFACE

    INTERFACE --> CACHE
    CACHE --> WRITER
    WRITER --> STATE
    WRITER --> LEARNED
    WRITER --> KNOWLEDGE
    WRITER --> SESSIONS

    WATCHER --> STATE
    WATCHER --> LEARNED
    WATCHER --> CACHE
```

## Class Structure

```mermaid
classDiagram
    class MemoryDaemon {
        +name: str = "memory"
        +service_name: str
        -_cache: dict
        -_watcher: FileWatcher
        -_write_queue: Queue
        +startup() async
        +run_daemon() async
        +shutdown() async
        +read(path): dict
        +write(path, data)
        +append(path, key, value)
        +query(pattern): list
        +get_service_stats() async
    }

    class MemoryCache {
        -_data: dict
        -_timestamps: dict
        +get(path): dict
        +set(path, data)
        +invalidate(path)
        +is_valid(path): bool
    }

    class YAMLWriter {
        +write(path, data)
        +append(path, key, value)
        +atomic_write(path, data)
    }

    class FileWatcher {
        +watch_dir: Path
        +on_change: Callable
        +start()
        +stop()
    }

    MemoryDaemon --> MemoryCache
    MemoryDaemon --> YAMLWriter
    MemoryDaemon --> FileWatcher
```

## Read/Write Flow

```mermaid
sequenceDiagram
    participant Client as D-Bus Client
    participant Daemon as MemoryDaemon
    participant Cache as MemoryCache
    participant Writer as YAMLWriter
    participant File as YAML File

    Note over Client,File: Read Operation
    Client->>Daemon: read("state/current_work")
    Daemon->>Cache: get(path)

    alt Cache hit
        Cache-->>Daemon: Cached data
    else Cache miss
        Daemon->>File: Read YAML
        File-->>Daemon: File contents
        Daemon->>Cache: set(path, data)
    end

    Daemon-->>Client: Data

    Note over Client,File: Write Operation
    Client->>Daemon: write("state/current_work", data)
    Daemon->>Cache: set(path, data)
    Daemon->>Writer: atomic_write(path, data)
    Writer->>File: Write YAML
    Daemon-->>Client: Success
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| MemoryDaemon | `services/memory/daemon.py` | Main daemon class |
| MemoryCache | Internal | In-memory cache |
| YAMLWriter | Internal | Atomic YAML writes |

## D-Bus Methods

| Method | Description |
|--------|-------------|
| `read(path)` | Read memory path |
| `write(path, data)` | Write to memory path |
| `append(path, key, value)` | Append to list/dict |
| `delete(path, key)` | Delete key |
| `query(pattern)` | Query with pattern |
| `list_paths()` | List all paths |
| `invalidate_cache()` | Clear cache |

## Memory Paths

| Path | Description |
|------|-------------|
| `state/current_work` | Active work items |
| `state/environments` | Environment status |
| `learned/patterns` | Learned patterns |
| `learned/tool_fixes` | Tool fix history |
| `knowledge/personas/*` | Persona knowledge |
| `sessions/YYYY-MM-DD` | Daily session logs |

## Configuration

```json
{
  "memory": {
    "cache_ttl": 60,
    "write_debounce": 2,
    "watch_enabled": true,
    "backup_enabled": true
  }
}
```

## Related Diagrams

- [Daemon Overview](./daemon-overview.md)
- [Memory Architecture](../06-memory/memory-architecture.md)
- [Memory Layers](../06-memory/memory-layers.md)
