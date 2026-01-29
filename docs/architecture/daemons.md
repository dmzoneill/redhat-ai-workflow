# 🤖 Daemon Architecture

This document describes the background daemon services that provide autonomous functionality for the AI Workflow system.

## Overview

The AI Workflow system includes 6 background daemons that run independently of the MCP server, providing:

- **Slack monitoring** - Real-time message listening and AI response
- **Sprint automation** - Automated Jira issue processing
- **Meeting management** - Google Meet auto-join and note-taking
- **Video rendering** - Virtual camera for meeting overlays
- **Session synchronization** - Cursor chat state tracking
- **Job scheduling** - Cron-based task execution

All daemons use a common D-Bus IPC architecture for control and monitoring.

## Architecture Diagram

```mermaid
graph TB
    subgraph Systemd["Systemd User Services"]
        S1[bot-slack.service]
        S2[bot-sprint.service]
        S3[bot-meet.service]
        S4[bot-video.service]
        S5[bot-session.service]
        S6[bot-cron.service]
    end

    subgraph Daemons["Daemon Processes"]
        D1[slack_daemon.py]
        D2[sprint_daemon.py]
        D3[meet_daemon.py]
        D4[video_daemon.py]
        D5[session_daemon.py]
        D6[cron_daemon.py]
    end

    subgraph DBus["D-Bus Session Bus"]
        B1[com.aiworkflow.BotSlack]
        B2[com.aiworkflow.BotSprint]
        B3[com.aiworkflow.BotMeet]
        B4[com.aiworkflow.BotVideo]
        B5[com.aiworkflow.BotSession]
        B6[com.aiworkflow.BotCron]
    end

    subgraph Clients["Control Clients"]
        CLI[service_control.py]
        HEALTH[health_check.py]
        VSCODE[VSCode Extension]
    end

    S1 --> D1
    S2 --> D2
    S3 --> D3
    S4 --> D4
    S5 --> D5
    S6 --> D6

    D1 --> B1
    D2 --> B2
    D3 --> B3
    D4 --> B4
    D5 --> B5
    D6 --> B6

    CLI --> B1 & B2 & B3 & B4 & B5 & B6
    HEALTH --> B1 & B2 & B3 & B4 & B5 & B6
    VSCODE --> B1 & B2 & B3 & B4 & B5 & B6

    style DBus fill:#f59e0b,stroke:#d97706,color:#fff
```

## D-Bus Base Architecture

All daemons inherit from `DaemonDBusBase` in `scripts/common/dbus_base.py`, providing:

### Standard D-Bus Interface

```mermaid
classDiagram
    class DaemonDBusBase {
        <<abstract>>
        +Running: bool
        +Uptime: float
        +Stats: string
        +GetStatus() string
        +GetStats() string
        +Shutdown() string
        +CallMethod(name, args) string
        +HealthCheck() string
        #get_service_stats()* dict
        #get_service_status()* dict
        #health_check()* dict
        #register_handler(name, func)
        #record_successful_operation()
        #record_failed_operation()
    }

    class SlackDaemon {
        +send_message()
        +approve_message()
        +reject_message()
        +get_pending_messages()
        +get_message_history()
    }

    class SprintDaemon {
        +approve_issue()
        +skip_issue()
        +get_status()
        +get_execution_trace()
        +list_issues()
    }

    class MeetDaemon {
        +list_meetings()
        +approve_meeting()
        +join_meeting()
        +leave_meeting()
        +get_captions()
        +mute_audio()
    }

    class CronDaemon {
        +run_job()
        +list_jobs()
        +get_history()
        +toggle_scheduler()
        +toggle_job()
    }

    DaemonDBusBase <|-- SlackDaemon
    DaemonDBusBase <|-- SprintDaemon
    DaemonDBusBase <|-- MeetDaemon
    DaemonDBusBase <|-- CronDaemon
```

### D-Bus Signals

All daemons emit standard signals:

| Signal | Parameters | Purpose |
|--------|------------|---------|
| `StatusChanged` | status (string) | Daemon state changes |
| `Event` | event_type, data | Generic event notification |

## Daemon Details

### 1. Slack Daemon (`slack_daemon.py`)

**Purpose**: Monitors Slack messages and routes them through AI workflow

**Service Name**: `com.aiworkflow.BotSlack`

**Features**:
- Real-time Slack message listening via WebSocket
- Message classification and intent detection
- Approval workflow for messages requiring human review
- Thread support for message replies
- Desktop notifications (via `gi.repository.Notify`)
- Sleep/wake awareness (pauses during system sleep)

```mermaid
stateDiagram-v2
    [*] --> Listening: Start

    Listening --> MessageReceived: Slack WebSocket event

    MessageReceived --> Classify: Parse message
    Classify --> AutoRespond: Low risk
    Classify --> PendingApproval: Needs review

    AutoRespond --> SendResponse: AI generates response
    SendResponse --> Listening

    PendingApproval --> Approved: User approves
    PendingApproval --> Rejected: User rejects
    Approved --> SendResponse
    Rejected --> Listening

    Listening --> Sleeping: System sleep
    Sleeping --> Listening: System wake
```

**Custom D-Bus Methods**:

| Method | Parameters | Returns |
|--------|------------|---------|
| `send_message` | channel_id, text | message_id |
| `approve_message` | message_id | success |
| `reject_message` | message_id | success |
| `get_pending_messages` | - | JSON array |
| `get_message_history` | limit | JSON array |

**State File**: `~/.config/aa-workflow/slack_state.db` (SQLite)

---

### 2. Sprint Daemon (`sprint_daemon.py`)

**Purpose**: Autonomous issue processing during working hours

**Service Name**: `com.aiworkflow.BotSprint`

**Features**:
- Workflow execution for Jira issues
- Execution tracing with step-by-step logging
- Time-aware (respects Mon-Fri 9am-5pm)
- Issue prioritization
- Progress tracking

```mermaid
sequenceDiagram
    participant Timer as Working Hours Check
    participant Daemon as Sprint Daemon
    participant Jira as Jira API
    participant Claude as Claude CLI
    participant Memory as Memory System

    Timer->>Daemon: Check if within working hours
    Daemon->>Jira: Fetch approved issues
    Jira-->>Daemon: Issue list

    loop For each approved issue
        Daemon->>Daemon: Start execution trace
        Daemon->>Claude: Execute workflow steps
        Claude-->>Daemon: Step results
        Daemon->>Memory: Log progress
        Daemon->>Jira: Update issue status
    end
```

**Custom D-Bus Methods**:

| Method | Parameters | Returns |
|--------|------------|---------|
| `approve_issue` | issue_key | success |
| `skip_issue` | issue_key, reason | success |
| `get_status` | - | JSON status |
| `get_execution_trace` | issue_key | JSON trace |
| `list_issues` | - | JSON array |

**State File**: `~/.config/aa-workflow/sprint_state_v2.json`

---

### 3. Meet Daemon (`meet_daemon.py`)

**Purpose**: Google Meet bot for auto-join and note-taking

**Service Name**: `com.aiworkflow.BotMeet`

**Features**:
- Calendar polling for upcoming meetings
- Auto-join with configurable modes
- Live caption extraction
- Participant tracking
- Audio control (mute/unmute)
- Browser automation

```mermaid
flowchart TD
    A[Poll Calendars] --> B{Meetings Found?}
    B -->|No| A
    B -->|Yes| C[Schedule Auto-Join]

    C --> D{Meeting Time?}
    D -->|Not Yet| D
    D -->|Now| E[Join Meeting]

    E --> F[Start Captions]
    F --> G[Monitor Participants]
    G --> H{Meeting Ended?}
    H -->|No| G
    H -->|Yes| I[Save Notes]
    I --> A

    subgraph Meeting Modes
        M1[Notes Mode: Auto note-taking]
        M2[Interactive Mode: Bot can speak]
    end
```

**Custom D-Bus Methods**:

| Method | Parameters | Returns |
|--------|------------|---------|
| `list_meetings` | - | JSON array |
| `approve_meeting` | event_id, mode | success |
| `join_meeting` | url, title, mode | success |
| `leave_meeting` | - | success |
| `get_captions` | limit | JSON array |
| `get_participants` | - | JSON array |
| `mute_audio` | - | success |
| `unmute_audio` | - | success |

**State File**: `~/.config/aa-workflow/meet_state.json`
**Database**: `~/.config/aa-workflow/meetings.db` (SQLite)

---

### 4. Video Daemon (`video_daemon.py`)

**Purpose**: Real-time video rendering to virtual camera

**Service Name**: `com.aiworkflow.BotVideo`

**Features**:
- v4l2loopback virtual camera output
- Real-time video rendering with overlays
- Audio waveform visualization
- Attendee display
- WebRTC/MJPEG streaming support
- Horizontal flip toggle

```mermaid
flowchart LR
    subgraph Inputs
        CAMERA[Physical Camera]
        AUDIO[Audio Input]
        ATTENDEES[Attendee List]
    end

    subgraph Processing
        RENDER[Video Renderer]
        OVERLAY[Overlay Generator]
        WAVE[Waveform Visualizer]
    end

    subgraph Outputs
        V4L2[v4l2loopback Device]
        STREAM[WebRTC/MJPEG Stream]
    end

    CAMERA --> RENDER
    AUDIO --> WAVE
    ATTENDEES --> OVERLAY
    WAVE --> OVERLAY
    OVERLAY --> RENDER
    RENDER --> V4L2
    RENDER --> STREAM
```

**Custom D-Bus Methods**:

| Method | Parameters | Returns |
|--------|------------|---------|
| `start_video` | device, audio_in, audio_out, width, height, flip | success |
| `stop_video` | - | success |
| `update_attendees` | JSON | success |
| `set_flip` | bool | success |
| `get_render_stats` | - | JSON stats |
| `start_streaming` | device, mode, port | success |
| `stop_streaming` | - | success |

**D-Bus Signals**:

| Signal | Parameters | Purpose |
|--------|------------|---------|
| `RenderingStarted` | device | Video started |
| `RenderingStopped` | - | Video stopped |
| `StreamingStarted` | mode, port | Stream started |
| `StreamingStopped` | - | Stream stopped |
| `Error` | message | Error occurred |

---

### 5. Session Daemon (`session_daemon.py`)

**Purpose**: Cursor IDE session state management

**Service Name**: `com.aiworkflow.BotSession`

**Features**:
- Cursor database watching
- Session synchronization
- Full-text chat search
- Workspace state tracking

```mermaid
flowchart TD
    A[Watch Cursor DB] --> B{Changes Detected?}
    B -->|No| A
    B -->|Yes| C[Extract Chat Data]

    C --> D[Update Session State]
    D --> E[Sync with workspace_states.json]
    E --> F[Notify Clients]
    F --> A

    G[Search Request] --> H[Query Chat Content]
    H --> I[Return Results with Context]
```

**Custom D-Bus Methods**:

| Method | Parameters | Returns |
|--------|------------|---------|
| `search_chats` | query, limit | JSON results |
| `get_sessions` | - | JSON array |
| `refresh_now` | - | success |
| `get_state` | - | JSON state |
| `write_state` | - | success |

**State File**: `~/.config/aa-workflow/session_state.json`

---

### 6. Cron Daemon (`cron_daemon.py`)

**Purpose**: Scheduled job execution via APScheduler

**Service Name**: `com.aiworkflow.BotCron`

**Features**:
- APScheduler integration
- Dynamic config reloading
- Execution history tracking
- Job enable/disable at runtime
- Claude CLI job execution

```mermaid
sequenceDiagram
    participant Config as config.json
    participant Daemon as Cron Daemon
    participant Scheduler as APScheduler
    participant Claude as Claude CLI
    participant Memory as Memory System

    Config->>Daemon: Load job definitions
    Daemon->>Scheduler: Register jobs

    loop Each scheduled time
        Scheduler->>Daemon: Trigger job
        Daemon->>Daemon: Check if job enabled
        Daemon->>Claude: Execute skill
        Claude-->>Daemon: Result
        Daemon->>Memory: Log execution
        Daemon->>Daemon: Record history
    end

    Note over Config,Daemon: Config changes trigger reload
    Config->>Daemon: File changed notification
    Daemon->>Scheduler: Update jobs
```

**Job Definition Format** (in `config.json`):

```yaml
schedules:
  enabled: true
  timezone: "America/New_York"
  execution_mode: "claude_cli"
  jobs:
    - name: "daily_standup"
      cron: "0 9 * * MON-FRI"
      skill: "coffee"
      persona: "developer"
      inputs: {}
      notify: ["memory", "slack"]
      enabled: true
```

**Custom D-Bus Methods**:

| Method | Parameters | Returns |
|--------|------------|---------|
| `run_job` | job_name | JSON result |
| `list_jobs` | - | JSON array |
| `get_history` | limit | JSON array |
| `toggle_scheduler` | enabled | success |
| `toggle_job` | job_name, enabled | success |
| `update_config` | section, key, value | success |
| `get_config` | section, key | value |

**State File**: `~/.config/aa-workflow/cron_state.json`

## Sleep/Wake Awareness

All daemons implement sleep/wake detection via the `SleepWakeAwareDaemon` mixin:

```mermaid
sequenceDiagram
    participant System as System (logind)
    participant DBus as D-Bus
    participant Daemon as Any Daemon
    participant External as External Services

    Note over System,Daemon: Method 1: D-Bus Signal
    System->>DBus: PrepareForSleep(true)
    DBus->>Daemon: Signal received
    Daemon->>Daemon: Pause operations

    System->>DBus: PrepareForSleep(false)
    DBus->>Daemon: Signal received
    Daemon->>Daemon: on_system_wake()
    Daemon->>External: Refresh connections

    Note over Daemon: Method 2: Time Gap Detection
    Daemon->>Daemon: Check time since last tick
    alt Gap > 30 seconds
        Daemon->>Daemon: Assume sleep occurred
        Daemon->>Daemon: on_system_wake()
    end
```

## State Management

### State File Locations

All daemon state files are stored in `~/.config/aa-workflow/`:

| Daemon | State File | Format |
|--------|------------|--------|
| Slack | `slack_state.db` | SQLite |
| Sprint | `sprint_state_v2.json` | JSON |
| Meet | `meet_state.json` | JSON |
| Meet | `meetings.db` | SQLite |
| Session | `session_state.json` | JSON |
| Cron | `cron_state.json` | JSON |

### Atomic Writes

All JSON state files use atomic writes:

```python
def atomic_write(path: Path, data: dict):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2))
    temp.rename(path)  # Atomic on POSIX
```

## Systemd Integration

### Service Unit Template

```ini
[Unit]
Description=AI Workflow Bot - %s
After=network.target dbus.service

[Service]
Type=simple
WorkingDirectory=%h/src/redhat-ai-workflow
ExecStart=%h/src/redhat-ai-workflow/.venv/bin/python scripts/%s_daemon.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

### Service Management

```bash
# Start a daemon
systemctl --user start bot-slack

# Check status
systemctl --user status bot-slack

# View logs
journalctl --user -u bot-slack -f

# Enable auto-start on login
systemctl --user enable bot-slack

# Stop a daemon
systemctl --user stop bot-slack
```

### Installing Services

```bash
# Install all services
./scripts/install_services.sh

# Or manually
cp systemd/*.service ~/.config/systemd/user/
systemctl --user daemon-reload
```

## Health Monitoring

The `health_check.py` script provides unified health monitoring:

```bash
# Check all services
python scripts/health_check.py

# Check specific service
python scripts/health_check.py --service slack

# JSON output for scripting
python scripts/health_check.py --json

# Continuous monitoring
python scripts/health_check.py --watch

# Attempt auto-repair
python scripts/health_check.py --fix
```

### Health Check Flow

```mermaid
flowchart TD
    A[health_check.py] --> B[Query D-Bus Services]
    B --> C{Service Running?}
    C -->|No| D[Mark Unhealthy]
    C -->|Yes| E[Call HealthCheck Method]
    E --> F{Health OK?}
    F -->|Yes| G[Mark Healthy]
    F -->|No| H[Check Consecutive Failures]
    H --> I{> 3 Failures?}
    I -->|Yes| D
    I -->|No| J[Mark Degraded]

    D --> K{--fix Flag?}
    K -->|Yes| L[Attempt Restart]
    K -->|No| M[Report Status]
    L --> M
    G --> M
    J --> M
```

## Service Control CLI

The `service_control.py` script provides unified CLI control:

```bash
# Show all service status
python scripts/service_control.py status

# Show specific service
python scripts/service_control.py status slack

# Stop a service
python scripts/service_control.py stop slack

# Run a cron job
python scripts/service_control.py run-job daily_standup

# List scheduled jobs
python scripts/service_control.py list-jobs

# List upcoming meetings
python scripts/service_control.py list-meetings

# Search chat content
python scripts/service_control.py search-chats "deploy ephemeral"

# Approve sprint issue
python scripts/service_control.py approve-issue AAP-12345

# Skip sprint issue
python scripts/service_control.py skip-issue AAP-12345 "Blocked by dependency"
```

## D-Bus Client Usage

### Python Client Example

```python
from scripts.common.dbus_base import DaemonClient

async def example():
    client = DaemonClient(
        service_name="com.aiworkflow.BotCron",
        object_path="/com/aiworkflow/BotCron",
        interface_name="com.aiworkflow.BotCron"
    )

    if await client.connect():
        # Get status
        status = await client.get_status()
        print(f"Status: {status}")

        # Run a job
        result = await client.call_method("run_job", ["daily_standup"])
        print(f"Job result: {result}")

        # Health check
        health = await client.health_check()
        print(f"Health: {health}")

        await client.disconnect()
```

### Command Line D-Bus

```bash
# List available services
busctl --user list | grep aiworkflow

# Call a method
busctl --user call com.aiworkflow.BotCron \
    /com/aiworkflow/BotCron \
    com.aiworkflow.BotCron \
    GetStatus

# Monitor signals
dbus-monitor --session "interface='com.aiworkflow.BotSlack'"
```

## See Also

- [Architecture Overview](./README.md) - System overview
- [VSCode Extension](./vscode-extension.md) - IDE integration
- [State Management](./state-management.md) - Persistence patterns
- [Development Guide](../DEVELOPMENT.md) - Contributing guidelines
