# State Persistence

> Runtime state storage and management

## Diagram

```mermaid
graph TB
    subgraph StateRoot[state/]
        CURRENT[current_work.yaml<br/>Active issues, branches]
        ENVS[environments.yaml<br/>Cluster configs]
        KNOWLEDGE[knowledge.yaml<br/>Discovered facts]
        SHARED[shared_context.yaml<br/>Cross-session context]
        PROJECTS[projects/<br/>Per-project state]
    end

    subgraph Managers[State Managers]
        STATE_MGR[StateManager<br/>state.json]
        MEMORY_DAEMON[MemoryDaemon<br/>YAML files]
    end

    subgraph Consumers[State Consumers]
        SESSION[Session Builder]
        TOOLS[Tool Execution]
        SKILLS[Skill Engine]
    end

    STATE_MGR --> StateRoot
    MEMORY_DAEMON --> StateRoot
    StateRoot --> Consumers
```

## State Files

```yaml
# state/current_work.yaml
active_issues:
  - key: AAP-12345
    summary: Fix authentication bug
    branch: aap-12345-fix-auth
    status: In Progress
    started: 2026-02-04T09:00:00

active_branches:
  - name: aap-12345-fix-auth
    issue: AAP-12345
    created: 2026-02-04T09:05:00
    last_commit: 2026-02-04T11:30:00

# state/environments.yaml
ephemeral:
  namespace: ephemeral-abc123
  reserved_until: 2026-02-04T17:00:00
  deployed_apps:
    - name: tower-analytics-clowdapp
      image: sha256:abc123...

stage:
  namespace: tower-analytics-stage
  last_deploy: 2026-02-03T14:00:00

# state/projects/automation-analytics-backend/current_work.yaml
branch: aap-12345-fix-auth
last_test_run: 2026-02-04T10:00:00
test_status: passed
```

## State Update Flow

```mermaid
sequenceDiagram
    participant Tool as Tool Execution
    participant Memory as memory_append
    participant Daemon as MemoryDaemon
    participant Lock as File Lock
    participant YAML as YAML File

    Tool->>Memory: Update current work
    Memory->>Daemon: append(path, key, value)

    Daemon->>Lock: acquire()
    Lock-->>Daemon: locked

    Daemon->>YAML: Read current
    YAML-->>Daemon: data

    Daemon->>Daemon: Append value
    Daemon->>YAML: Write updated

    Daemon->>Lock: release()
    Daemon-->>Memory: success
```

## State vs Config

```mermaid
flowchart TB
    subgraph Config[config.json - Static]
        PROJECTS_CFG[Project definitions]
        CREDS[Credentials]
        URLS[Service URLs]
    end

    subgraph State[state.json - Runtime]
        SESSIONS[Active sessions]
        PERSONA[Current persona]
        TOOLS[Loaded tools]
    end

    subgraph Memory[memory/ - Persistent]
        WORK[Current work]
        LEARNED[Learned patterns]
        KNOWLEDGE[Domain knowledge]
    end

    Config -->|Read-only| State
    State -->|Updates| Memory
```

## Persistence Guarantees

| Storage | Durability | Consistency | Use Case |
|---------|------------|-------------|----------|
| state.json | Debounced write | Eventually consistent | Runtime state |
| memory/*.yaml | Immediate write | Strongly consistent | Persistent data |
| In-memory cache | None | Read-your-writes | Performance |

## Components

| Component | File | Description |
|-----------|------|-------------|
| StateManager | `server/state_manager.py` | state.json management |
| MemoryDaemon | `services/memory/daemon.py` | YAML file access |
| memory_write | `memory_tools.py` | Write tool |

## Related Diagrams

- [Memory Architecture](./memory-architecture.md)
- [State Manager](../01-server/state-manager.md)
- [Config System](../01-server/config-system.md)
