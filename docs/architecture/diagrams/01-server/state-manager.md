# State Manager

> Thread-safe, debounced state persistence

## Diagram

```mermaid
classDiagram
    class StateManager {
        -_instance: StateManager
        -_instance_lock: Lock
        -_lock: RLock
        -_cache: dict
        -_dirty: bool
        -_last_mtime: float
        -_debounce_timer: Timer
        +get(section, key, default): Any
        +get_all(): dict
        +set(section, key, value, flush)
        +update_section(section, data, merge, flush)
        +delete(section, key, flush): bool
        +flush()
        +reload()
        +has_section(section): bool
        +sections(): list~str~
        +is_dirty: bool
        +state_file: Path
        +is_service_enabled(service): bool
        +set_service_enabled(service, enabled, flush)
        +is_job_enabled(job): bool
        +set_job_enabled(job, enabled, flush)
        +get_meeting_overrides(): dict
        +set_meeting_override(key, status, flush)
    }

    class DEFAULT_STATE {
        <<constant>>
        +version: 1
        +services: dict
        +jobs: dict
        +last_updated: null
    }

    class state_json {
        <<file>>
        services/
        jobs/
        meetings/
        last_updated
    }

    StateManager --> DEFAULT_STATE : initializes from
    StateManager --> state_json : reads/writes
```

## Read/Write Flow

```mermaid
sequenceDiagram
    participant Caller as Caller
    participant SM as StateManager
    participant Lock as RLock
    participant File as state.json
    participant Timer as Debounce Timer

    Note over SM: Read Operation
    Caller->>SM: get("services", "scheduler")
    SM->>Lock: acquire
    SM->>SM: _check_reload()
    alt File modified externally
        SM->>File: Read and parse
        File-->>SM: Update cache
    end
    SM->>SM: Return from cache
    SM->>Lock: release
    SM-->>Caller: value

    Note over SM: Write Operation
    Caller->>SM: set("services", "scheduler", {...})
    SM->>Lock: acquire
    SM->>SM: _check_reload()
    SM->>SM: Update cache
    SM->>SM: _mark_dirty()
    SM->>Timer: Schedule flush (2s)
    SM->>Lock: release

    Note over SM: Debounced Flush
    Timer->>SM: _flush_debounced()
    SM->>Lock: acquire
    SM->>File: Write with flock
    SM->>Lock: release
```

## State Structure

```mermaid
graph TB
    subgraph StateJSON[state.json]
        VERSION[version: 1]
        subgraph Services[services]
            SCHEDULER[scheduler: enabled]
            SPRINT[sprint_bot: enabled]
            GCAL[google_calendar: enabled]
            GMAIL[gmail: enabled]
        end
        subgraph Jobs[jobs]
            JOB1[morning_coffee: enabled]
            JOB2[jira_hygiene: enabled]
        end
        subgraph Meetings[meetings]
            OVERRIDES[overrides: {...}]
        end
        UPDATED[last_updated: timestamp]
    end
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| StateManager | `server/state_manager.py` | Singleton state manager |
| state | `server/state_manager.py` | Global instance |
| DEFAULT_STATE | `server/state_manager.py` | Default structure |
| DEBOUNCE_DELAY | `server/state_manager.py` | 2.0 seconds |
| STATE_FILE | `server/paths.py` | File path |

## Thread Safety Features

| Feature | Implementation |
|---------|----------------|
| Singleton | `__new__` with class lock |
| Thread-safe ops | RLock for all operations |
| Cross-process | fcntl.flock on writes |
| External changes | mtime checking on reads |
| Debounced writes | Timer-based batching |

## Related Diagrams

- [Config System](./config-system.md)
- [MCP Server Core](./mcp-server-core.md)
