# Meet Daemon

> Google Meet bot for meeting transcription and AI participation

## Diagram

```mermaid
sequenceDiagram
    participant Calendar as Google Calendar
    participant Daemon as MeetDaemon
    participant Browser as Browser Controller
    participant Meet as Google Meet
    participant STT as Speech-to-Text
    participant LLM as LLM Responder
    participant TTS as Text-to-Speech
    participant Video as Video Generator
    participant DB as Notes Database

    Daemon->>Calendar: Check upcoming meetings
    Calendar-->>Daemon: Meeting in 5 minutes

    Daemon->>Browser: Launch browser
    Browser->>Meet: Join meeting
    Meet-->>Browser: Joined

    loop During meeting
        Meet->>Browser: Audio stream
        Browser->>STT: Audio data
        STT-->>Daemon: Transcription
        Daemon->>DB: Store transcript

        alt Wake word detected
            Daemon->>LLM: Generate response
            LLM-->>Daemon: Response text
            Daemon->>TTS: Synthesize speech
            TTS-->>Browser: Audio output
            Browser->>Meet: Play audio

            Daemon->>Video: Generate avatar
            Video-->>Browser: Video frames
            Browser->>Meet: Virtual camera
        end
    end

    Meet->>Daemon: Meeting ended
    Daemon->>DB: Finalize notes
    Daemon->>Browser: Close browser
```

## Class Structure

```mermaid
classDiagram
    class MeetDaemon {
        +name: str = "meet"
        +service_name: str
        -_browser: BrowserController
        -_stt: STTEngine
        -_tts: TTSEngine
        -_llm: LLMResponder
        -_video: VideoGenerator
        -_db: NotesDatabase
        +startup() async
        +run_daemon() async
        +shutdown() async
        +join_meeting(url) async
        +leave_meeting() async
        +get_service_stats() async
    }

    class BrowserController {
        +launch() async
        +join_meet(url) async
        +leave_meet() async
        +get_audio_stream()
        +send_audio(data)
        +send_video(frames)
    }

    class STTEngine {
        +transcribe(audio): str
        +detect_wake_word(audio): bool
        +get_speaker(): str
    }

    class LLMResponder {
        +generate_response(context): str
        +get_meeting_context(): dict
        +summarize_discussion(): str
    }

    class VideoGenerator {
        +generate_avatar(audio): frames
        +set_expression(expr)
        +get_frame_rate(): int
    }

    class NotesDatabase {
        +create_meeting(id)
        +add_transcript(text, speaker)
        +add_summary(text)
        +get_meeting(id): Meeting
    }

    MeetDaemon --> BrowserController
    MeetDaemon --> STTEngine
    MeetDaemon --> LLMResponder
    MeetDaemon --> VideoGenerator
    MeetDaemon --> NotesDatabase
```

## Meeting Flow

```mermaid
flowchart TB
    subgraph Scheduling[Meeting Detection]
        CALENDAR[Google Calendar]
        CHECK[Check upcoming]
        FILTER[Filter by criteria]
        QUEUE[Meeting queue]
    end

    subgraph Join[Meeting Join]
        LAUNCH[Launch browser]
        NAVIGATE[Navigate to Meet]
        AUTH[Authenticate]
        ENTER[Enter meeting]
    end

    subgraph Active[Active Meeting]
        CAPTURE[Audio capture]
        TRANSCRIBE[Transcription]
        DETECT[Wake word detection]
        RESPOND[AI response]
        AVATAR[Avatar generation]
    end

    subgraph End[Meeting End]
        LEAVE[Leave meeting]
        SUMMARIZE[Generate summary]
        STORE[Store notes]
        NOTIFY[Notify user]
    end

    CALENDAR --> CHECK
    CHECK --> FILTER
    FILTER --> QUEUE
    QUEUE --> LAUNCH

    LAUNCH --> NAVIGATE
    NAVIGATE --> AUTH
    AUTH --> ENTER

    ENTER --> CAPTURE
    CAPTURE --> TRANSCRIBE
    TRANSCRIBE --> DETECT
    DETECT --> RESPOND
    RESPOND --> AVATAR

    CAPTURE --> LEAVE
    LEAVE --> SUMMARIZE
    SUMMARIZE --> STORE
    STORE --> NOTIFY
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| MeetDaemon | `services/meet/daemon.py` | Main daemon class |
| BrowserController | `tool_modules/aa_meet_bot/src/browser_controller.py` | Browser automation |
| STTEngine | `tool_modules/aa_meet_bot/src/stt_engine.py` | Speech recognition |
| TTSEngine | `tool_modules/aa_meet_bot/src/tts_engine.py` | Speech synthesis |
| LLMResponder | `tool_modules/aa_meet_bot/src/llm_responder.py` | AI responses |
| VideoGenerator | `tool_modules/aa_meet_bot/src/video_generator.py` | Avatar generation |
| NotesDatabase | `tool_modules/aa_meet_bot/src/notes_database.py` | SQLite storage |

## D-Bus Methods

| Method | Description |
|--------|-------------|
| `join_meeting(url)` | Join a meeting |
| `leave_meeting()` | Leave current meeting |
| `get_transcript()` | Get current transcript |
| `toggle_responses(enabled)` | Enable/disable AI responses |
| `set_wake_word(word)` | Change wake word |

## Related Diagrams

- [Daemon Overview](./daemon-overview.md)
- [Meet Bot Pipeline](../03-tools/meet-bot-pipeline.md)
- [Meeting Flow](../08-data-flows/meeting-flow.md)
