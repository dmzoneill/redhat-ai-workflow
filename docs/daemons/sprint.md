# Sprint Daemon

> Automated Jira issue processing during work hours

## Overview

The Sprint Daemon (`scripts/sprint_daemon.py`) is a standalone service that automates sprint work by fetching Jira issues, prioritizing them, and orchestrating Cursor chats to work on approved issues.

## Architecture

```mermaid
graph TB
    subgraph Jira["Jira"]
        SPRINT[Active Sprint]
        ISSUES[Sprint Issues]
    end

    subgraph Daemon["Sprint Daemon"]
        FETCHER[Issue Fetcher<br/>Jira API polling]
        PRIORITIZER[Prioritizer<br/>Story points, priority, age]
        SCHEDULER[Work Scheduler<br/>Working hours check]
        ORCHESTRATOR[Orchestrator<br/>Issue processing]
    end

    subgraph Cursor["Cursor IDE"]
        CHAT[New Chat<br/>D-Bus launch]
        WORK[Claude Work<br/>Issue implementation]
    end

    subgraph State["State"]
        FILE[(sprint_state_v2.json)]
        TIMELINE[Issue Timeline<br/>Action history]
    end

    SPRINT --> FETCHER
    FETCHER --> ISSUES
    ISSUES --> PRIORITIZER
    PRIORITIZER --> SCHEDULER
    SCHEDULER --> ORCHESTRATOR
    ORCHESTRATOR --> CHAT
    CHAT --> WORK

    FETCHER --> FILE
    ORCHESTRATOR --> TIMELINE
```

## Features

| Feature | Description |
|---------|-------------|
| Working hours | Operates Mon-Fri 9am-5pm (configurable) |
| Issue prioritization | Ranks by story points, priority, age, type |
| Approval workflow | User approves issues before processing |
| Execution tracing | Detailed logs of all actions taken |
| Progress tracking | Real-time UI updates via state file |
| Skip-on-block | Skips blocked issues automatically |

## D-Bus Interface

**Service**: `com.aiworkflow.BotSprint`

### Methods

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `GetStatus` | - | JSON | Get daemon status |
| `ListIssues` | status?, actionable? | JSON | List sprint issues |
| `ApproveIssue` | issue_key | JSON | Approve issue for processing |
| `SkipIssue` | issue_key, reason? | JSON | Skip/block an issue |
| `ApproveAll` | - | JSON | Approve all actionable issues |
| `Refresh` | - | JSON | Refresh from Jira |
| `Enable` | - | JSON | Enable automatic mode |
| `Disable` | - | JSON | Disable automatic mode |
| `Start` | - | JSON | Manual start (ignores schedule) |
| `Stop` | - | JSON | Manual stop |
| `ProcessNext` | - | JSON | Process next approved issue |
| `StartIssue` | issue_key | JSON | Start work on specific issue |
| `GetWorkLog` | issue_key | JSON | Get work log for issue |
| `OpenInCursor` | issue_key | JSON | Open issue in Cursor |

### Signals

| Signal | Parameters | Description |
|--------|------------|-------------|
| `IssueStarted` | issue_key | Started working on issue |
| `IssueCompleted` | issue_key | Finished issue work |
| `IssueSkipped` | issue_key, reason | Issue was skipped |

## Issue Prioritization

```mermaid
flowchart TD
    ISSUES[Sprint Issues] --> FILTER{Actionable?}

    FILTER -->|No| SKIP[Not actionable<br/>In Review/Done]
    FILTER -->|Yes| SCORE[Calculate Score]

    SCORE --> SP[Story Points<br/>Lower = higher priority]
    SCORE --> PRI[Priority<br/>Blocker > Critical > Major]
    SCORE --> AGE[Age<br/>Older = higher priority]
    SCORE --> TYPE[Type<br/>Bug > Story > Task]

    SP --> RANK
    PRI --> RANK
    AGE --> RANK
    TYPE --> RANK

    RANK[Final Ranking] --> SORTED[Sorted Issue List]
```

### Actionable Statuses

| Status | Actionable | Description |
|--------|------------|-------------|
| New | Yes | Fresh issue |
| Refinement | Yes | Needs work |
| Backlog | Yes | Ready to start |
| In Progress | No | Already being worked |
| In Review | No | Waiting for review |
| Done | No | Completed |

## Working Hours

The daemon respects working hours to avoid running during off-hours:

```mermaid
flowchart TD
    CHECK[Check Schedule] --> DAY{Weekday?}

    DAY -->|No| OUTSIDE[Outside hours]
    DAY -->|Yes| TIME{Within hours?}

    TIME -->|No| OUTSIDE
    TIME -->|Yes| ACTIVE[Active]

    subgraph Config["Configuration"]
        START[Start: 9:00]
        END[End: 17:00]
        TZ[Timezone: Europe/Dublin]
    end

    ACTIVE --> PROCESS[Process issues]
    OUTSIDE --> WAIT[Wait for working hours]
```

### Configuration

```python
working_hours = {
    "start_hour": 9,
    "start_minute": 0,
    "end_hour": 17,
    "end_minute": 0,
    "weekdays_only": True,
    "timezone": "Europe/Dublin",
}
```

## Issue Processing Flow

```mermaid
sequenceDiagram
    participant Daemon as Sprint Daemon
    participant Jira as Jira API
    participant Cursor as Cursor IDE
    participant Claude as Claude Agent
    participant GitLab

    Daemon->>Jira: Fetch sprint issues
    Jira-->>Daemon: Issue list

    Daemon->>Daemon: Prioritize & filter

    loop For each approved issue
        Daemon->>Daemon: Check working hours

        alt Within hours
            Daemon->>Cursor: Launch chat (D-Bus)
            Cursor->>Claude: Work on issue

            Claude->>Jira: Update status
            Claude->>GitLab: Create branch/MR

            Claude-->>Daemon: Work complete
            Daemon->>Daemon: Log timeline
        else Outside hours
            Daemon->>Daemon: Wait
        end
    end
```

## State Management

### State File Structure

`~/.config/aa-workflow/sprint_state_v2.json`:

```json
{
  "issues": [
    {
      "key": "AAP-12345",
      "summary": "Fix billing calculation",
      "type": "Bug",
      "priority": "Major",
      "storyPoints": 3,
      "jiraStatus": "New",
      "approvalStatus": "approved",
      "isActionable": true,
      "timeline": [
        {
          "timestamp": "2026-01-26T10:00:00Z",
          "action": "approved",
          "description": "Issue approved for sprint bot"
        }
      ]
    }
  ],
  "processingIssue": null,
  "automaticMode": true,
  "manuallyStarted": false,
  "lastUpdated": "2026-01-26T09:30:00Z"
}
```

### Approval Statuses

| Status | Description |
|--------|-------------|
| `pending` | Awaiting user approval |
| `approved` | Ready for processing |
| `skipped` | User skipped this issue |
| `processing` | Currently being worked |
| `completed` | Work finished |
| `failed` | Processing failed |

## Execution Tracing

The daemon creates detailed traces of all work:

```mermaid
classDiagram
    class ExecutionTracer {
        +trace_id: str
        +issue_key: str
        +started_at: datetime
        +steps: list[TraceStep]
        +start_step(name)
        +complete_step(status)
        +save()
    }

    class TraceStep {
        +step_id: str
        +name: str
        +status: StepStatus
        +started_at: datetime
        +completed_at: datetime
        +output: dict
    }

    class StepStatus {
        <<enumeration>>
        PENDING
        RUNNING
        COMPLETED
        FAILED
        SKIPPED
    }

    ExecutionTracer "1" --> "*" TraceStep
    TraceStep --> StepStatus
```

## Usage

### Starting the Daemon

```bash
# Run in foreground
python scripts/sprint_daemon.py

# Run with D-Bus IPC
python scripts/sprint_daemon.py --dbus

# List sprint issues
python scripts/sprint_daemon.py --list
```

### Systemd Service

```bash
# Start service
systemctl --user start bot-sprint

# View logs
journalctl --user -u bot-sprint -f

# Check status
systemctl --user status bot-sprint
```

### D-Bus Control

```bash
# Via service_control.py
python scripts/service_control.py approve-issue AAP-12345
python scripts/service_control.py skip-issue AAP-12345 "Blocked by dependency"
python scripts/service_control.py status sprint

# Via D-Bus directly
busctl --user call com.aiworkflow.BotSprint \
    /com/aiworkflow/BotSprint \
    com.aiworkflow.BotSprint \
    ApproveIssue "s" "AAP-12345"
```

## Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Initializing: Start

    Initializing --> Loading: Load config
    Loading --> Refreshing: Fetch from Jira

    Refreshing --> Idle: Outside hours
    Refreshing --> Ready: Within hours

    state Ready {
        [*] --> Checking: Check next issue
        Checking --> Processing: Approved issue found
        Checking --> Waiting: No issues ready

        Processing --> Launching: Launch Cursor
        Launching --> Working: Chat started
        Working --> Completed: Work done
        Working --> Failed: Error

        Completed --> Checking: Check next
        Failed --> Checking: Check next
        Waiting --> Checking: Periodic check
    }

    Ready --> Idle: End of hours
    Idle --> Ready: Start of hours

    Ready --> [*]: Shutdown
    Idle --> [*]: Shutdown
```

## Configuration

### config.json Settings

```json
{
  "sprint": {
    "jira_project": "AAP",
    "jira_component": null,
    "check_interval_seconds": 300,
    "jira_refresh_interval_seconds": 1800,
    "skip_blocked_after_minutes": 30,
    "working_hours": {
      "start_hour": 9,
      "end_hour": 17,
      "weekdays_only": true,
      "timezone": "Europe/Dublin"
    }
  }
}
```

## See Also

- [Daemons Overview](./README.md) - All background services
- [Daemon Architecture](../architecture/daemons.md) - Technical details
- [Jira Tools](../tool-modules/aa_jira.md) - Jira integration
