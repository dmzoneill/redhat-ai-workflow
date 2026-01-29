# Cron Daemon

> Scheduled job execution using Claude CLI

## Overview

The Cron Daemon (`scripts/cron_daemon.py`) is a standalone service that runs scheduled jobs using APScheduler. Jobs execute skills via Claude CLI, enabling automated AI-powered workflows.

## Architecture

```mermaid
graph TB
    subgraph Config["Configuration"]
        JSON[config.json<br/>schedules section]
        STATE[state.json<br/>Runtime overrides]
    end

    subgraph Daemon["Cron Daemon"]
        LOADER[ConfigLoader<br/>Job definitions]
        APSCHED[APScheduler<br/>Cron triggers]
        EXECUTOR[JobExecutor<br/>Claude CLI]
        LOGGER[ExecutionLog<br/>History tracking]
    end

    subgraph Execution["Job Execution"]
        CLI[Claude CLI<br/>Skill invocation]
        SKILL[Skill Engine<br/>Tool orchestration]
        TOOLS[MCP Tools]
    end

    subgraph Output["Notification"]
        MEMORY[Memory<br/>Session log]
        SLACK[Slack<br/>Optional]
        DESKTOP[Desktop<br/>Optional]
    end

    JSON --> LOADER
    STATE --> LOADER
    LOADER --> APSCHED
    APSCHED --> EXECUTOR
    EXECUTOR --> CLI
    CLI --> SKILL
    SKILL --> TOOLS

    EXECUTOR --> LOGGER
    EXECUTOR --> MEMORY
    EXECUTOR --> SLACK
```

## Features

| Feature | Description |
|---------|-------------|
| Cron scheduling | Standard cron syntax support |
| Poll triggers | Interval-based polling jobs |
| Dynamic config | Hot-reload on config changes |
| Job toggle | Enable/disable individual jobs |
| Execution history | Track success/failure |
| Multiple executors | Claude CLI, direct skill, MCP |

## D-Bus Interface

**Service**: `com.aiworkflow.BotCron`

### Methods

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `GetStatus` | - | JSON | Get daemon status |
| `ListJobs` | - | JSON | List scheduled jobs |
| `RunJob` | job_name | JSON | Run job immediately |
| `GetHistory` | limit? | JSON | Get execution history |
| `ToggleScheduler` | enabled | JSON | Enable/disable scheduler |
| `ToggleJob` | job_name, enabled | JSON | Enable/disable specific job |
| `UpdateConfig` | section, key, value | JSON | Update config value |
| `GetConfig` | section, key? | JSON | Get config value |

### Signals

| Signal | Parameters | Description |
|--------|------------|-------------|
| `JobStarted` | job_name | Job execution started |
| `JobCompleted` | job_name, success | Job execution finished |
| `ConfigReloaded` | - | Configuration was reloaded |

## Job Configuration

### Cron Jobs

```json
{
  "schedules": {
    "enabled": true,
    "timezone": "Europe/Dublin",
    "execution_mode": "claude_cli",
    "jobs": [
      {
        "name": "daily_standup",
        "description": "Generate daily standup summary",
        "trigger": "cron",
        "cron": "0 9 * * 1-5",
        "skill": "standup_summary",
        "persona": "developer",
        "inputs": {
          "days": 1
        },
        "notify": ["memory", "slack"],
        "enabled": true
      }
    ]
  }
}
```

### Poll Jobs

```json
{
  "name": "check_mr_feedback",
  "description": "Check MRs for new comments",
  "trigger": "poll",
  "interval_minutes": 30,
  "skill": "check_feedback",
  "notify": ["memory", "desktop"]
}
```

### Job Fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Unique job identifier |
| `description` | No | Human-readable description |
| `trigger` | Yes | `cron` or `poll` |
| `cron` | If trigger=cron | Cron expression |
| `interval_minutes` | If trigger=poll | Poll interval |
| `skill` | Yes | Skill to execute |
| `persona` | No | Persona to load |
| `inputs` | No | Skill input parameters |
| `notify` | No | Notification channels |
| `enabled` | No | Whether job is active (default: true) |

## Execution Modes

```mermaid
flowchart TD
    JOB[Job Triggered] --> MODE{Execution Mode}

    MODE -->|claude_cli| CLI[Claude CLI<br/>Full agent capabilities]
    MODE -->|skill_run| SKILL[skill_run tool<br/>Direct MCP call]
    MODE -->|mcp_direct| MCP[MCP Protocol<br/>Raw tool calls]

    CLI --> RESULT
    SKILL --> RESULT
    MCP --> RESULT

    RESULT[Execution Result] --> NOTIFY{Notify?}

    NOTIFY -->|memory| MEM[Session Log]
    NOTIFY -->|slack| SLACK[Slack Channel]
    NOTIFY -->|desktop| DESK[Desktop Notification]
```

### Mode Comparison

| Mode | Use Case | Capabilities |
|------|----------|--------------|
| `claude_cli` | Complex multi-step jobs | Full Claude reasoning |
| `skill_run` | Simple skill execution | Fast, deterministic |
| `mcp_direct` | Single tool calls | Minimal overhead |

## Job Lifecycle

```mermaid
sequenceDiagram
    participant Sched as APScheduler
    participant Exec as Executor
    participant CLI as Claude CLI
    participant Skill as Skill Engine
    participant Log as ExecutionLog

    Sched->>Exec: Job triggered
    Exec->>Log: Log job start

    Exec->>CLI: Launch claude-code

    alt Skill Mode
        CLI->>Skill: skill_run(job.skill, job.inputs)
        Skill->>Skill: Execute steps
        Skill-->>CLI: Result
    else Direct Mode
        CLI->>CLI: Process job
    end

    CLI-->>Exec: Exit code + output

    Exec->>Log: Log completion
    Exec->>Exec: Send notifications
```

## State Management

### State File Structure

`~/.config/aa-workflow/cron_state.json`:

```json
{
  "enabled": true,
  "timezone": "Europe/Dublin",
  "execution_mode": "claude_cli",
  "jobs": [
    {
      "name": "daily_standup",
      "description": "Generate daily standup summary",
      "skill": "standup_summary",
      "cron": "0 9 * * 1-5",
      "trigger": "cron",
      "persona": "developer",
      "enabled": true,
      "notify": ["memory", "slack"],
      "next_run": "2026-01-27T09:00:00+00:00"
    }
  ],
  "history": [
    {
      "job": "daily_standup",
      "started_at": "2026-01-26T09:00:00Z",
      "completed_at": "2026-01-26T09:02:30Z",
      "success": true,
      "duration_seconds": 150
    }
  ],
  "total_history": 1,
  "updated_at": "2026-01-26T09:02:30Z"
}
```

### Runtime State Overrides

The daemon uses `StateManager` for runtime overrides:

```python
# Toggle scheduler
state_manager.set_service_enabled("scheduler", False, flush=True)

# Toggle individual job
state_manager.set_job_enabled("daily_standup", False, flush=True)
```

These overrides persist in `state.json` and survive restarts.

## Execution History

```mermaid
classDiagram
    class ExecutionLog {
        +entries: list[LogEntry]
        +max_entries: int
        +add(entry)
        +get_recent(limit)
        +get_for_job(job_name)
        +get_failures(hours)
    }

    class LogEntry {
        +job: str
        +started_at: datetime
        +completed_at: datetime
        +success: bool
        +duration_seconds: float
        +error: str
        +output_summary: str
    }

    ExecutionLog "1" --> "*" LogEntry
```

## Usage

### Starting the Daemon

```bash
# Run in foreground
python scripts/cron_daemon.py

# Run with D-Bus IPC
python scripts/cron_daemon.py --dbus

# List configured jobs
python scripts/cron_daemon.py --list-jobs
```

### Systemd Service

```bash
# Start service
systemctl --user start bot-cron

# View logs
journalctl --user -u bot-cron -f

# Check status
systemctl --user status bot-cron
```

### D-Bus Control

```bash
# List jobs
python scripts/service_control.py list-jobs

# Run job immediately
python scripts/service_control.py run-job daily_standup

# Toggle job
busctl --user call com.aiworkflow.BotCron \
    /com/aiworkflow/BotCron \
    com.aiworkflow.BotCron \
    ToggleJob "sb" "daily_standup" false
```

## Sleep/Wake Handling

```mermaid
sequenceDiagram
    participant System as System (logind)
    participant DBus as D-Bus
    participant Daemon as Cron Daemon
    participant Sched as APScheduler

    System->>DBus: PrepareForSleep(true)
    DBus->>Daemon: Sleep signal

    Note over System: System sleeps

    System->>DBus: PrepareForSleep(false)
    DBus->>Daemon: Wake signal

    Daemon->>Daemon: on_system_wake()
    Daemon->>Sched: Check missed jobs

    Note over Sched: APScheduler handles<br/>misfire_grace_time
```

APScheduler automatically handles missed jobs based on `misfire_grace_time`. Jobs missed during sleep may run immediately on wake if within the grace period.

## Common Cron Expressions

| Expression | Schedule |
|------------|----------|
| `0 9 * * 1-5` | 9am weekdays |
| `*/30 * * * *` | Every 30 minutes |
| `0 */4 * * *` | Every 4 hours |
| `0 0 * * 0` | Midnight on Sunday |
| `0 17 * * 5` | 5pm on Friday |

## Configuration

### Required Setup

1. Claude CLI installed and configured
2. Skills defined in `skills/` directory

### config.json Settings

```json
{
  "schedules": {
    "enabled": true,
    "timezone": "Europe/Dublin",
    "execution_mode": "claude_cli",
    "misfire_grace_time": 300,
    "jobs": [...]
  }
}
```

## See Also

- [Daemons Overview](./README.md) - All background services
- [Skills Reference](../skills/README.md) - Available skills
- [Daemon Architecture](../architecture/daemons.md) - Technical details
