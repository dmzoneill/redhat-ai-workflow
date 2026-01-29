# Meet Daemon

> Google Meet auto-join and note-taking bot

## Overview

The Meet Daemon (`scripts/meet_daemon.py`) is a standalone service that monitors calendars for upcoming meetings with Google Meet links and automatically joins them with configurable modes.

## Architecture

```mermaid
graph TB
    subgraph Google["Google Services"]
        CAL[Calendar API]
        MEET[Google Meet]
    end

    subgraph Daemon["Meet Daemon"]
        SCHEDULER[MeetingScheduler<br/>Calendar polling]
        BROWSER[BrowserController<br/>Playwright automation]
        NOTES[NotesBot<br/>Caption extraction]
        ATTENDEES[AttendeeService<br/>Participant tracking]
    end

    subgraph Audio["Audio System"]
        PULSE[PulseAudio/PipeWire]
        SINK[Virtual Sink<br/>Capture audio]
        SOURCE[Virtual Source<br/>TTS output]
    end

    subgraph State["Persistence"]
        DB[(meetings.db<br/>SQLite)]
        STATE[(meet_state.json)]
    end

    CAL --> SCHEDULER
    SCHEDULER --> BROWSER
    BROWSER --> MEET
    MEET --> NOTES
    NOTES --> ATTENDEES

    BROWSER --> SINK
    SOURCE --> BROWSER

    NOTES --> DB
    SCHEDULER --> STATE
```

## Features

| Feature | Description |
|---------|-------------|
| Calendar polling | Monitors multiple calendars |
| Auto-join | Joins meetings with buffer time |
| Meeting modes | Notes-only or interactive |
| Caption extraction | Real-time transcript capture |
| Participant tracking | Who's in the meeting |
| Meeting history | SQLite database storage |
| Audio routing | Virtual audio devices |

## D-Bus Interface

**Service**: `com.aiworkflow.BotMeet`

### Methods

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `GetStatus` | - | JSON | Get daemon status |
| `ListMeetings` | - | JSON | List upcoming meetings |
| `ApproveMeeting` | event_id, mode? | JSON | Pre-approve for auto-join |
| `UnapproveMeeting` | event_id | JSON | Cancel approval |
| `SkipMeeting` | event_id | JSON | Skip a meeting |
| `ForceJoin` | event_id | JSON | Immediately join meeting |
| `JoinMeeting` | url, title?, mode? | JSON | Join by URL |
| `LeaveMeeting` | session_id? | JSON | Leave current meeting |
| `SetMeetingMode` | event_id, mode | JSON | Set meeting mode |
| `ListCalendars` | - | JSON | List monitored calendars |
| `GetCaptions` | limit? | JSON | Get recent captions |
| `GetParticipants` | - | JSON | Get current participants |
| `GetMeetingHistory` | limit? | JSON | Get past meetings |
| `MuteAudio` | - | JSON | Mute meeting audio |
| `UnmuteAudio` | - | JSON | Unmute meeting audio |
| `GetAudioState` | - | JSON | Get audio mute state |

### Signals

| Signal | Parameters | Description |
|--------|------------|-------------|
| `MeetingJoined` | event_id, title | Joined a meeting |
| `MeetingLeft` | event_id | Left a meeting |
| `CaptionReceived` | speaker, text | New caption captured |

## Meeting Modes

```mermaid
flowchart TD
    MEETING[Meeting] --> MODE{Bot Mode}

    MODE -->|notes| NOTES[Notes Mode]
    MODE -->|interactive| INTER[Interactive Mode]

    NOTES --> CAPTURE[Capture captions]
    NOTES --> MUTED[Audio muted]
    NOTES --> VIDEO_OFF[Camera off]
    NOTES --> PASSIVE[Passive presence]

    INTER --> CAPTURE
    INTER --> UNMUTED[Audio enabled]
    INTER --> VIDEO[Virtual camera]
    INTER --> ACTIVE[Can respond]
```

| Mode | Audio | Video | Purpose |
|------|-------|-------|---------|
| `notes` | Muted | Off | Silent note-taking |
| `interactive` | On | Virtual camera | Active participation |

## Meeting Lifecycle

```mermaid
sequenceDiagram
    participant Cal as Calendar
    participant Sched as Scheduler
    participant Browser
    participant Meet as Google Meet
    participant Notes as NotesBot

    loop Every minute
        Sched->>Cal: Poll for meetings
        Cal-->>Sched: Meeting list
    end

    Sched->>Sched: Meeting starting soon?

    alt Approved meeting
        Sched->>Browser: Launch browser
        Browser->>Meet: Navigate to URL

        Meet->>Browser: Join flow
        Browser->>Browser: Handle popups
        Browser->>Meet: Join meeting

        loop While in meeting
            Meet->>Notes: Extract captions
            Notes->>Notes: Store transcript
        end

        Meet-->>Browser: Meeting ended
        Browser->>Browser: Cleanup
    end
```

## Calendar Configuration

### Adding Calendars

```python
# Via MCP tool
meet_add_calendar(
    calendar_id="primary",
    name="Work Calendar",
    enabled=True,
    auto_join=False,  # Require approval
    bot_mode="notes"
)
```

### Calendar Properties

| Property | Type | Description |
|----------|------|-------------|
| `calendar_id` | string | Google Calendar ID |
| `name` | string | Display name |
| `enabled` | bool | Monitor this calendar |
| `auto_join` | bool | Join without approval |
| `bot_mode` | string | Default mode (notes/interactive) |

## State Management

### State File Structure

`~/.config/aa-workflow/meet_state.json`:

```json
{
  "schedulerRunning": true,
  "upcomingMeetings": [
    {
      "id": "event123",
      "title": "Team Standup",
      "url": "https://meet.google.com/abc-defg-hij",
      "startTime": "2026-01-26T10:00:00Z",
      "endTime": "2026-01-26T10:30:00Z",
      "organizer": "manager@example.com",
      "status": "approved",
      "botMode": "notes"
    }
  ],
  "currentMeetings": [],
  "monitoredCalendars": [
    {"id": "primary", "name": "Work", "enabled": true}
  ],
  "nextMeeting": {...},
  "countdown": "45m",
  "countdownSeconds": 2700,
  "lastPoll": "2026-01-26T09:15:00Z"
}
```

### Meeting Statuses

| Status | Description |
|--------|-------------|
| `scheduled` | On calendar, awaiting action |
| `approved` | Will auto-join |
| `skipped` | User chose to skip |
| `joining` | Currently joining |
| `joined` | In the meeting |
| `completed` | Meeting ended |

## Database Schema

```mermaid
erDiagram
    MEETINGS {
        int id PK
        string event_id
        string title
        string meet_url
        datetime scheduled_start
        datetime scheduled_end
        datetime actual_start
        datetime actual_end
        string organizer
        string status
        string bot_mode
        int transcript_count
    }

    TRANSCRIPT_ENTRIES {
        int id PK
        int meeting_id FK
        string speaker
        string text
        datetime timestamp
        float confidence
    }

    PARTICIPANTS {
        int id PK
        int meeting_id FK
        string name
        datetime joined_at
        datetime left_at
    }

    MEETINGS ||--o{ TRANSCRIPT_ENTRIES : has
    MEETINGS ||--o{ PARTICIPANTS : has
```

## Audio Routing

In interactive mode, the daemon sets up virtual audio devices:

```mermaid
graph LR
    subgraph Meeting["Google Meet"]
        MEET_OUT[Meeting Audio]
        MEET_IN[Meeting Mic Input]
    end

    subgraph Virtual["Virtual Devices"]
        SINK[meet_bot_sink<br/>Capture sink]
        MON[.monitor<br/>For transcription]
        SOURCE[meet_bot_mic<br/>TTS source]
    end

    subgraph Processing["Processing"]
        TRANS[Transcription<br/>STT]
        TTS[TTS Engine]
    end

    MEET_OUT --> SINK
    SINK --> MON
    MON --> TRANS

    TTS --> SOURCE
    SOURCE --> MEET_IN
```

## Usage

### Starting the Daemon

```bash
# Run in foreground
python scripts/meet_daemon.py

# Run with D-Bus IPC
python scripts/meet_daemon.py --dbus

# List upcoming meetings
python scripts/meet_daemon.py --list
```

### Systemd Service

```bash
# Start service
systemctl --user start bot-meet

# View logs
journalctl --user -u bot-meet -f

# Check status
systemctl --user status bot-meet
```

### D-Bus Control

```bash
# Via service_control.py
python scripts/service_control.py list-meetings

# Approve a meeting
busctl --user call com.aiworkflow.BotMeet \
    /com/aiworkflow/BotMeet \
    com.aiworkflow.BotMeet \
    ApproveMeeting "ss" "event123" "notes"

# Join by URL
busctl --user call com.aiworkflow.BotMeet \
    /com/aiworkflow/BotMeet \
    com.aiworkflow.BotMeet \
    JoinMeeting "sss" "https://meet.google.com/abc" "Quick Meeting" "notes"
```

## Sleep/Wake Handling

```mermaid
sequenceDiagram
    participant System as System (logind)
    participant DBus as D-Bus
    participant Daemon as Meet Daemon
    participant Browser

    System->>DBus: PrepareForSleep(true)
    DBus->>Daemon: Sleep signal

    Daemon->>Daemon: Pause operations

    Note over System: System sleeps

    System->>DBus: PrepareForSleep(false)
    DBus->>Daemon: Wake signal

    Daemon->>Daemon: on_system_wake()
    Daemon->>Daemon: Re-poll calendars
    Daemon->>Browser: Check if stale
    Daemon->>Daemon: Refresh state
```

## Configuration

### Required Setup

1. Google OAuth credentials configured
2. Calendar API enabled
3. Playwright browsers installed

### config.json Settings

```json
{
  "google": {
    "credentials_file": "~/.config/aa-workflow/google_credentials.json",
    "token_file": "~/.config/aa-workflow/google_token.json"
  },
  "meet": {
    "join_buffer_minutes": 2,
    "leave_after_minutes": 5,
    "screenshot_interval_seconds": 30
  }
}
```

## See Also

- [Daemons Overview](./README.md) - All background services
- [Video Daemon](./video.md) - Virtual camera rendering
- [Daemon Architecture](../architecture/daemons.md) - Technical details
