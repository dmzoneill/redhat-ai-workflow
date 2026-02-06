# Meet Bot Tools

> aa_meet_bot module components for meeting automation

## Diagram

```mermaid
graph TB
    subgraph Input[Input Components]
        AUDIO_CAP[audio_capture.py<br/>Audio input]
        BROWSER[browser_controller.py<br/>Browser automation]
        CALENDAR[meeting_scheduler.py<br/>Calendar integration]
    end

    subgraph Processing[Processing Components]
        STT[stt_engine.py<br/>Speech-to-text]
        LLM[llm_responder.py<br/>AI responses]
        WAKE[wake_word.py<br/>Wake detection]
        ENRICH[attendee_enricher.py<br/>Attendee info]
    end

    subgraph Output[Output Components]
        TTS[tts_engine.py<br/>Text-to-speech]
        VIDEO[video_generator.py<br/>Avatar generation]
        AUDIO_OUT[audio_output.py<br/>Audio output]
        NOTES[notes_bot.py<br/>Note taking]
    end

    subgraph Storage[Storage Components]
        DB[notes_database.py<br/>SQLite storage]
        JIRA[jira_preloader.py<br/>Issue context]
    end

    AUDIO_CAP --> STT
    BROWSER --> AUDIO_CAP
    CALENDAR --> BROWSER

    STT --> WAKE
    STT --> LLM
    WAKE --> LLM
    ENRICH --> LLM

    LLM --> TTS
    LLM --> NOTES
    TTS --> AUDIO_OUT
    TTS --> VIDEO

    NOTES --> DB
    JIRA --> LLM
```

## Component Classes

```mermaid
classDiagram
    class BrowserController {
        +launch() async
        +join_meet(url) async
        +leave_meet() async
        +get_audio_stream()
        +send_audio(data)
    }

    class STTEngine {
        +transcribe(audio): str
        +get_speaker(): str
        +start_stream()
        +stop_stream()
    }

    class LLMResponder {
        +generate_response(context): str
        +get_meeting_context(): dict
        +summarize(): str
    }

    class TTSEngine {
        +synthesize(text): bytes
        +set_voice(voice)
        +get_voices(): list
    }

    class VideoGenerator {
        +generate_frame(audio): ndarray
        +set_avatar(config)
        +set_expression(expr)
    }

    class NotesBot {
        +start_recording()
        +add_transcript(text, speaker)
        +generate_summary(): str
        +save_notes()
    }

    class NotesDatabase {
        +create_meeting(id)
        +add_entry(meeting_id, data)
        +get_meeting(id): dict
        +search(query): list
    }

    BrowserController --> STTEngine
    STTEngine --> LLMResponder
    LLMResponder --> TTSEngine
    TTSEngine --> VideoGenerator
    LLMResponder --> NotesBot
    NotesBot --> NotesDatabase
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| browser_controller | `browser_controller.py` | Selenium/Playwright automation |
| stt_engine | `stt_engine.py` | Whisper/Google STT |
| llm_responder | `llm_responder.py` | Claude/Gemini responses |
| tts_engine | `tts_engine.py` | Text-to-speech synthesis |
| video_generator | `video_generator.py` | Avatar frame generation |
| notes_bot | `notes_bot.py` | Meeting note capture |
| notes_database | `notes_database.py` | SQLite storage |
| wake_word | `wake_word.py` | Wake word detection |
| attendee_enricher | `attendee_enricher.py` | Attendee info lookup |
| jira_preloader | `jira_preloader.py` | Jira context loading |

## MCP Tools

| Tool | Description |
|------|-------------|
| `meet_join` | Join a meeting |
| `meet_leave` | Leave current meeting |
| `meet_get_transcript` | Get current transcript |
| `meet_summarize` | Generate summary |
| `meet_search_notes` | Search past notes |

## Configuration

```json
{
  "meet_bot": {
    "stt": {
      "engine": "whisper",
      "model": "base"
    },
    "tts": {
      "engine": "piper",
      "voice": "en_US-lessac-medium"
    },
    "llm": {
      "provider": "gemini",
      "model": "gemini-pro"
    },
    "avatar": {
      "enabled": true,
      "model": "default"
    },
    "wake_word": "hey assistant"
  }
}
```

## Related Diagrams

- [Meet Bot Pipeline](./meet-bot-pipeline.md)
- [Meet Daemon](../02-services/meet-daemon.md)
- [Video Daemon](../02-services/video-daemon.md)
