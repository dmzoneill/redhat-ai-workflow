# SLOP Daemon

> Stateful Loop Orchestration Protocol daemon

## Diagram

```mermaid
stateDiagram-v2
    [*] --> Idle: Daemon started

    Idle --> Initializing: Start orchestrator
    Initializing --> Ready: Loops loaded

    state Ready {
        [*] --> Waiting
        Waiting --> Dispatching: Loop trigger
        Dispatching --> Executing: Loop selected
        Executing --> Waiting: Loop complete
        Executing --> Retrying: Loop failed
        Retrying --> Executing: Retry attempt
        Retrying --> Waiting: Max retries
    }

    Ready --> Paused: Pause requested
    Paused --> Ready: Resume requested

    Ready --> Shutdown: Stop requested
    Shutdown --> [*]
```

## Class Structure

```mermaid
classDiagram
    class SLOPDaemon {
        +name: str = "slop"
        +service_name: str
        -_orchestrator: Orchestrator
        -_loops: dict
        -_active_loop: str
        +startup() async
        +run_daemon() async
        +shutdown() async
        +start_loop(name) async
        +stop_loop(name) async
        +get_loop_status(name): dict
        +get_service_stats() async
    }

    class Orchestrator {
        +loops: dict
        +active: str
        +register_loop(name, config)
        +start_loop(name)
        +stop_loop(name)
        +get_status(): dict
    }

    class Loop {
        +name: str
        +config: LoopConfig
        +state: LoopState
        +execute() async
        +pause()
        +resume()
        +get_status(): dict
    }

    class LoopConfig {
        +trigger: TriggerType
        +interval: int
        +max_retries: int
        +timeout: int
        +tools: list
    }

    class LoopState {
        +status: str
        +last_run: datetime
        +run_count: int
        +error_count: int
    }

    SLOPDaemon --> Orchestrator
    Orchestrator --> Loop
    Loop --> LoopConfig
    Loop --> LoopState
```

## Loop Execution

```mermaid
flowchart TB
    subgraph Trigger[Triggers]
        INTERVAL[Interval Timer]
        EVENT[External Event]
        MANUAL[Manual Start]
        CHAIN[Loop Chain]
    end

    subgraph Orchestrator[Orchestrator]
        DISPATCH[Dispatch Loop]
        CONTEXT[Build Context]
        EXECUTE[Execute Steps]
        HANDLE[Handle Result]
    end

    subgraph Loop[Loop Execution]
        STEP1[Step 1: Tool Call]
        STEP2[Step 2: Process]
        STEP3[Step 3: Store]
        DECIDE[Decision Point]
    end

    subgraph Output[Output]
        SUCCESS[Success Path]
        RETRY[Retry Path]
        FAIL[Failure Path]
        NEXT[Next Loop]
    end

    INTERVAL --> DISPATCH
    EVENT --> DISPATCH
    MANUAL --> DISPATCH
    CHAIN --> DISPATCH

    DISPATCH --> CONTEXT
    CONTEXT --> EXECUTE
    EXECUTE --> STEP1
    STEP1 --> STEP2
    STEP2 --> STEP3
    STEP3 --> DECIDE
    DECIDE --> HANDLE

    HANDLE --> SUCCESS
    HANDLE --> RETRY
    HANDLE --> FAIL
    SUCCESS --> NEXT
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| SLOPDaemon | `services/slop/daemon.py` | Main daemon class |
| Orchestrator | `services/slop/orchestrator.py` | Loop orchestration |
| loops | `services/slop/loops.py` | Loop definitions |
| external_tools | `services/slop/external_tools.py` | External tool calls |
| database | `services/slop/database.py` | State persistence |

## D-Bus Methods

| Method | Description |
|--------|-------------|
| `start_loop(name)` | Start a loop |
| `stop_loop(name)` | Stop a loop |
| `pause_loop(name)` | Pause a loop |
| `resume_loop(name)` | Resume a loop |
| `get_loop_status(name)` | Get loop status |
| `list_loops()` | List all loops |
| `trigger_loop(name)` | Trigger immediate run |

## Loop Types

| Type | Trigger | Use Case |
|------|---------|----------|
| polling | Interval | Check for updates |
| reactive | Event | Respond to changes |
| scheduled | Cron | Timed execution |
| chained | Previous loop | Sequential processing |

## Configuration

```yaml
loops:
  jira_sync:
    trigger: interval
    interval: 300
    max_retries: 3
    tools:
      - jira_search
      - memory_write
    on_success: slack_notify
    on_failure: log_error
```

## Related Diagrams

- [Daemon Overview](./daemon-overview.md)
- [SLOP Loops](./slop-loops.md)
- [Ralph Loop Manager](../01-server/ralph-loop-manager.md)
