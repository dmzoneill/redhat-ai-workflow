# Cron Daemon

> Scheduled job execution using APScheduler

## Diagram

```mermaid
flowchart TB
    subgraph Config[Configuration]
        CONFIG_JSON[config.json]
        STATE_JSON[state.json]
        JOBS[Job Definitions]
    end

    subgraph Scheduler[APScheduler]
        CRON_TRIGGER[Cron Triggers]
        INTERVAL[Interval Triggers]
        DATE[Date Triggers]
        JOB_STORE[Job Store]
    end

    subgraph Execution[Job Execution]
        CLAUDE_CLI[Claude CLI]
        SKILL_ENGINE[Skill Engine]
        DIRECT[Direct Python]
    end

    subgraph Notification[Notifications]
        MEMORY_LOG[Memory Log]
        SLACK_NOTIFY[Slack]
        DBUS_EVENT[D-Bus Event]
    end

    CONFIG_JSON --> JOBS
    STATE_JSON --> JOBS
    JOBS --> CRON_TRIGGER
    JOBS --> INTERVAL
    JOBS --> DATE

    CRON_TRIGGER --> JOB_STORE
    INTERVAL --> JOB_STORE
    DATE --> JOB_STORE

    JOB_STORE --> CLAUDE_CLI
    JOB_STORE --> SKILL_ENGINE
    JOB_STORE --> DIRECT

    CLAUDE_CLI --> MEMORY_LOG
    SKILL_ENGINE --> MEMORY_LOG
    DIRECT --> MEMORY_LOG

    MEMORY_LOG --> SLACK_NOTIFY
    MEMORY_LOG --> DBUS_EVENT
```

## Class Structure

```mermaid
classDiagram
    class CronDaemon {
        +name: str = "cron"
        +service_name: str
        -_scheduler: APScheduler
        -_jobs_executed: int
        -_jobs_failed: int
        -_state_writer_task: Task
        +startup() async
        +run_daemon() async
        +shutdown() async
        +get_service_stats() async
        +health_check() async
        -_handle_run_job(name) async
        -_handle_list_jobs() async
        -_handle_toggle_scheduler(enabled) async
        -_handle_toggle_job(name, enabled) async
        -_write_state() async
    }

    class SchedulerConfig {
        +enabled: bool
        +timezone: str
        +execution_mode: str
        +jobs: list
        +reload()
        +get_cron_jobs(): list
        +get_poll_jobs(): list
    }

    class ExecutionLog {
        +entries: list
        +add_entry(job, result)
        +get_recent(limit): list
        +get_by_job(name): list
    }

    class JobExecutor {
        +execute_skill(skill, inputs)
        +execute_claude_cli(prompt)
        +execute_python(func)
    }

    CronDaemon --> SchedulerConfig
    CronDaemon --> ExecutionLog
    CronDaemon --> JobExecutor
```

## Job Execution Flow

```mermaid
sequenceDiagram
    participant Scheduler as APScheduler
    participant Daemon as CronDaemon
    participant Executor as JobExecutor
    participant Claude as Claude CLI
    participant Skill as Skill Engine
    participant Log as ExecutionLog
    participant Notify as Notification

    Scheduler->>Daemon: Job triggered
    Daemon->>Daemon: Check job enabled
    
    alt Job enabled
        Daemon->>Executor: Execute job
        
        alt execution_mode = claude_cli
            Executor->>Claude: Run with prompt
            Claude-->>Executor: Result
        else execution_mode = skill
            Executor->>Skill: skill_run()
            Skill-->>Executor: Result
        end
        
        Executor-->>Daemon: Execution result
        Daemon->>Log: Log execution
        
        alt Has notifications
            Daemon->>Notify: Send notifications
        end
    else Job disabled
        Daemon->>Log: Log skipped
    end
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| CronDaemon | `services/cron/daemon.py` | Main daemon class |
| SchedulerConfig | `tool_modules/aa_workflow/src/scheduler.py` | Configuration |
| ExecutionLog | `tool_modules/aa_workflow/src/scheduler.py` | Execution history |
| init_scheduler | `tool_modules/aa_workflow/src/scheduler.py` | Scheduler init |

## Job Configuration

```json
{
  "schedules": {
    "enabled": true,
    "timezone": "America/New_York",
    "execution_mode": "claude_cli",
    "jobs": [
      {
        "name": "morning_coffee",
        "description": "Morning briefing",
        "cron": "0 9 * * 1-5",
        "skill": "coffee",
        "persona": "developer",
        "enabled": true,
        "notify": ["slack", "memory"]
      }
    ]
  }
}
```

## D-Bus Methods

| Method | Description |
|--------|-------------|
| `run_job(name)` | Run job immediately |
| `list_jobs()` | List all jobs |
| `get_history(limit)` | Get execution history |
| `toggle_scheduler(enabled)` | Enable/disable scheduler |
| `toggle_job(name, enabled)` | Enable/disable job |
| `get_state()` | Get full cron state |

## Related Diagrams

- [Daemon Overview](./daemon-overview.md)
- [Skill Engine](../04-skills/skill-engine-architecture.md)
- [Automation Skills](../04-skills/automation-skills.md)
