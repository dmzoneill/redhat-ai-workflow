# 🤖 Meet Bot Module (aa_meet_bot)

Automated Google Meet participation with browser control, virtual devices, AI avatar video, and real-time transcription.

## Overview

The Meet Bot module provides:
- **Automatic meeting join**: Monitors calendar and joins meetings
- **Virtual camera/microphone**: Loopback devices for video/audio
- **AI avatar video**: TTS speech with lip-sync video
- **Live transcription**: Captures meeting transcript
- **Multi-meeting support**: Concurrent browser instances

## Architecture

```mermaid
graph TB
    subgraph Calendar["Google Calendar"]
        CAL[Calendar API]
        EVENTS[Meeting Events]
    end

    subgraph Browser["Browser Automation"]
        CHROME[Chrome/Playwright]
        TABS[Multiple Tabs]
    end

    subgraph Virtual["Virtual Devices"]
        V4L[v4l2loopback<br/>Virtual Camera]
        PULSE[PulseAudio<br/>Virtual Mic]
    end

    subgraph Avatar["Avatar Generation"]
        TTS[GPT-SoVITS<br/>Text-to-Speech]
        LIP[Wav2Lip<br/>Lip Sync]
        VIDEO[Video Stream]
    end

    subgraph Storage["Persistence"]
        DB[(SQLite DB)]
        NOTES[Meeting Notes]
        TRANSCRIPT[Transcripts]
    end

    CAL --> EVENTS
    EVENTS --> CHROME
    CHROME --> V4L
    CHROME --> PULSE
    TTS --> LIP
    LIP --> VIDEO
    VIDEO --> V4L
    CHROME --> DB
    DB --> NOTES
    DB --> TRANSCRIPT

    style CHROME fill:#6366f1,stroke:#4f46e5,color:#fff
    style V4L fill:#10b981,stroke:#059669,color:#fff
    style TTS fill:#f59e0b,stroke:#d97706,color:#fff
```

## Components

### Browser Controller

Controls Chrome via Playwright for meeting automation:

```mermaid
sequenceDiagram
    participant Cal as Calendar
    participant Bot as Meet Bot
    participant Browser as Chrome
    participant Meet as Google Meet

    Cal->>Bot: Meeting starting in 1 min
    Bot->>Browser: Launch instance
    Browser->>Meet: Navigate to meet URL
    Meet->>Browser: Permission prompts
    Browser->>Meet: Grant camera/mic
    Browser->>Meet: Click "Join now"

    loop During meeting
        Meet->>Bot: Transcript updates
        Bot->>Bot: Store transcript
    end

    Cal->>Bot: Meeting ended
    Bot->>Browser: Leave meeting
    Browser->>Bot: Final transcript
    Bot->>Bot: Generate notes
```

### Virtual Devices

Creates loopback devices for video and audio:

```mermaid
graph LR
    subgraph System["System Devices"]
        V4L_MOD[v4l2loopback<br/>Kernel Module]
        PULSE_SRV[PulseAudio<br/>Server]
    end

    subgraph Virtual["Virtual Devices"]
        VCAM[/dev/video10<br/>Virtual Camera]
        VMIC[Virtual Sink<br/>Monitor Source]
    end

    subgraph Bot["Meet Bot"]
        FFMPEG[FFmpeg<br/>Video Feed]
        AUDIO[Audio Stream]
    end

    V4L_MOD --> VCAM
    PULSE_SRV --> VMIC
    FFMPEG --> VCAM
    AUDIO --> VMIC
```

### Avatar Video Pipeline

Generates AI avatar video with lip-synced speech:

```mermaid
graph TB
    subgraph Input["Input"]
        TEXT[Text to Speak]
        BASE[Base Avatar Image]
    end

    subgraph TTS["Text-to-Speech"]
        SOVITS[GPT-SoVITS]
        AUDIO[Audio WAV]
    end

    subgraph LipSync["Lip Synchronization"]
        WAV2LIP[Wav2Lip Model]
        FRAMES[Video Frames]
    end

    subgraph Output["Output"]
        FFMPEG[FFmpeg Encoder]
        STREAM[Video Stream]
        V4L[Virtual Camera]
    end

    TEXT --> SOVITS
    SOVITS --> AUDIO
    BASE --> WAV2LIP
    AUDIO --> WAV2LIP
    WAV2LIP --> FRAMES
    FRAMES --> FFMPEG
    FFMPEG --> STREAM
    STREAM --> V4L

    style SOVITS fill:#f59e0b,stroke:#d97706,color:#fff
    style WAV2LIP fill:#6366f1,stroke:#4f46e5,color:#fff
```

## Tools

### Calendar & Scheduling

| Tool | Description |
|------|-------------|
| `meet_list_upcoming` | List upcoming meetings from calendar |
| `meet_check_conflicts` | Check for scheduling conflicts |
| `meet_schedule` | Schedule a new meeting |
| `meet_reschedule` | Reschedule an existing meeting |

### Meeting Control

| Tool | Description |
|------|-------------|
| `meet_join` | Join a meeting by URL or ID |
| `meet_leave` | Leave current meeting |
| `meet_status` | Get current meeting status |
| `meet_list_active` | List all active meeting sessions |

### Transcript & Notes

| Tool | Description |
|------|-------------|
| `meet_get_transcript` | Get live or saved transcript |
| `meet_get_notes` | Get AI-generated meeting notes |
| `meet_summarize` | Generate meeting summary |
| `meet_search_transcripts` | Search across all transcripts |

### Avatar & Video

| Tool | Description |
|------|-------------|
| `meet_speak` | Speak text using TTS avatar |
| `meet_set_avatar` | Change avatar image |
| `meet_toggle_video` | Toggle virtual camera on/off |
| `meet_toggle_audio` | Toggle virtual mic on/off |

### Device Management

| Tool | Description |
|------|-------------|
| `meet_setup_devices` | Initialize virtual devices |
| `meet_cleanup_devices` | Remove virtual devices |
| `meet_check_devices` | Verify device status |

## State Management

### Meeting States

```mermaid
stateDiagram-v2
    [*] --> Idle: Bot started

    Idle --> Scheduled: Meeting in calendar
    Scheduled --> Joining: 1 min before start
    Joining --> InMeeting: Join successful
    Joining --> Failed: Join failed

    InMeeting --> Speaking: TTS triggered
    Speaking --> InMeeting: Speech complete
    InMeeting --> Leaving: Meeting end time
    InMeeting --> Leaving: Manual leave

    Leaving --> ProcessingNotes: Generate summary
    ProcessingNotes --> Idle: Notes saved

    Failed --> Idle: Retry timer
```

### Database Schema

```mermaid
erDiagram
    MEETINGS {
        string id PK
        string title
        datetime start_time
        datetime end_time
        string meet_url
        string status
        datetime joined_at
        datetime left_at
    }

    TRANSCRIPTS {
        int id PK
        string meeting_id FK
        datetime timestamp
        string speaker
        string text
    }

    NOTES {
        int id PK
        string meeting_id FK
        string summary
        json action_items
        json decisions
        datetime created_at
    }

    MEETINGS ||--o{ TRANSCRIPTS : has
    MEETINGS ||--o| NOTES : has
```

## Configuration

### config.json Settings

```json
{
  "meet_bot": {
    "calendar_id": "primary",
    "join_before_minutes": 1,
    "auto_join": true,
    "auto_leave": true,
    "auto_notes": true,
    "avatar_image": "~/.config/aa-workflow/avatar.png",
    "tts_model": "gpt-sovits",
    "browser_profile": "~/.config/aa-workflow/chrome-profile"
  }
}
```

### Virtual Device Setup

```bash
# Load v4l2loopback kernel module
sudo modprobe v4l2loopback devices=1 video_nr=10 \
    card_label="Meet Bot Camera" exclusive_caps=1

# Create PulseAudio virtual sink
pactl load-module module-null-sink sink_name=meet_bot_sink \
    sink_properties=device.description="Meet Bot Audio"
```

## Multi-Meeting Support

The bot can participate in multiple meetings concurrently:

```mermaid
graph TB
    subgraph Manager["Meeting Manager"]
        SCHED[Scheduler]
        POOL[Browser Pool]
    end

    subgraph Sessions["Active Sessions"]
        S1[Session 1<br/>Team Standup]
        S2[Session 2<br/>Design Review]
        S3[Session 3<br/>1:1 with Manager]
    end

    subgraph Resources["Shared Resources"]
        DB[(Database)]
        TTS[TTS Service]
    end

    SCHED --> S1
    SCHED --> S2
    SCHED --> S3

    S1 --> POOL
    S2 --> POOL
    S3 --> POOL

    S1 --> DB
    S2 --> DB
    S3 --> DB

    S1 --> TTS
    S2 --> TTS
    S3 --> TTS
```

## TTS Pipeline

### GPT-SoVITS Integration

```mermaid
sequenceDiagram
    participant Bot as Meet Bot
    participant TTS as GPT-SoVITS Server
    participant Wav2Lip as Wav2Lip
    participant Camera as Virtual Camera

    Bot->>TTS: POST /tts {text: "Hello!"}
    TTS-->>Bot: audio.wav (speech audio)

    Bot->>Wav2Lip: Generate lip-sync video
    Note over Wav2Lip: Uses base avatar image
    Wav2Lip-->>Bot: video frames

    Bot->>Camera: Stream frames to v4l2loopback
    Camera-->>Meet: Video visible in meeting
```

### Audio Processing

```mermaid
graph LR
    subgraph Input["TTS Output"]
        WAV[WAV Audio]
    end

    subgraph Processing["Audio Processing"]
        RESAMPLE[Resample to 48kHz]
        NORMALIZE[Normalize Volume]
    end

    subgraph Output["Virtual Microphone"]
        PULSE[PulseAudio Sink]
        MONITOR[Source Monitor]
    end

    WAV --> RESAMPLE
    RESAMPLE --> NORMALIZE
    NORMALIZE --> PULSE
    PULSE --> MONITOR
```

## Error Handling

### Meeting Join Failures

```mermaid
flowchart TD
    A[Join Attempt] --> B{Success?}
    B -->|Yes| C[In Meeting]
    B -->|No| D{Error Type}

    D -->|Auth Error| E[Re-authenticate]
    D -->|Network Error| F[Retry with Backoff]
    D -->|Permission Denied| G[Check Device Permissions]
    D -->|Meeting Ended| H[Mark as Missed]

    E --> A
    F --> A
    G --> I[Alert User]
    H --> J[Log and Skip]
```

### Device Recovery

```mermaid
flowchart TD
    A[Device Check] --> B{Camera OK?}
    B -->|Yes| C{Mic OK?}
    B -->|No| D[Recreate v4l2loopback]

    C -->|Yes| E[All Good]
    C -->|No| F[Recreate PulseAudio Sink]

    D --> G{Module Loaded?}
    G -->|Yes| H[Reset Device]
    G -->|No| I[Load Module]

    H --> A
    I --> A
    F --> A
```

## Dependencies

### System Requirements

- **Chrome/Chromium**: For Playwright browser automation
- **v4l2loopback**: Kernel module for virtual camera
- **PulseAudio**: Audio server with null-sink support
- **FFmpeg**: Video/audio encoding and streaming

### Python Packages

- **playwright**: Browser automation
- **google-api-python-client**: Calendar API access
- **SQLite3**: Meeting data persistence
- **torch**: For Wav2Lip model (optional)

### Optional Services

- **GPT-SoVITS**: Text-to-speech server
- **Wav2Lip**: Lip synchronization model

## Daemon Integration

The Meet Bot runs as a systemd daemon:

```mermaid
graph TB
    subgraph Systemd["Systemd Service"]
        SERVICE[bot-meet.service]
    end

    subgraph Daemon["Meet Daemon"]
        MAIN[Main Loop]
        DBUS[D-Bus Interface]
        MONITOR[Calendar Monitor]
    end

    subgraph IPC["D-Bus Methods"]
        JOIN[Join Meeting]
        LEAVE[Leave Meeting]
        STATUS[Get Status]
        SPEAK[Speak Text]
    end

    SERVICE --> MAIN
    MAIN --> MONITOR
    MAIN --> DBUS
    DBUS --> JOIN
    DBUS --> LEAVE
    DBUS --> STATUS
    DBUS --> SPEAK
```

## See Also

- [Daemons Architecture](../architecture/daemons.md)
- [Meet Daemon](../daemons/meet.md)
- [Google Calendar Module](./google_calendar.md)
- [Video Daemon](../daemons/video.md)
