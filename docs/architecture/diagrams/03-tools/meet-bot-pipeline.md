# Meet Bot Pipeline

> Audio/video processing pipeline for meeting bot

## Diagram

```mermaid
flowchart TB
    subgraph AudioInput[Audio Input Pipeline]
        MIC[Microphone/Meet Audio]
        CAPTURE[Audio Capture]
        BUFFER[Audio Buffer]
        VAD[Voice Activity Detection]
    end

    subgraph STT[Speech-to-Text Pipeline]
        CHUNK[Audio Chunks]
        WHISPER[Whisper Model]
        TRANSCRIPT[Transcript Text]
        SPEAKER[Speaker Diarization]
    end

    subgraph Processing[AI Processing]
        WAKE[Wake Word Detection]
        CONTEXT[Context Assembly]
        LLM[LLM Response]
        DECISION[Response Decision]
    end

    subgraph TTS[Text-to-Speech Pipeline]
        TEXT[Response Text]
        PIPER[Piper TTS]
        AUDIO_GEN[Generated Audio]
        PHONEMES[Phoneme Extraction]
    end

    subgraph Video[Video Pipeline]
        FACE[Face Model]
        LIP_SYNC[Lip Sync]
        EXPRESSION[Expression Engine]
        BLEND[Frame Blending]
        V4L2[V4L2 Output]
    end

    MIC --> CAPTURE
    CAPTURE --> BUFFER
    BUFFER --> VAD
    VAD --> CHUNK

    CHUNK --> WHISPER
    WHISPER --> TRANSCRIPT
    WHISPER --> SPEAKER

    TRANSCRIPT --> WAKE
    TRANSCRIPT --> CONTEXT
    WAKE --> DECISION
    CONTEXT --> LLM
    LLM --> DECISION

    DECISION --> TEXT
    TEXT --> PIPER
    PIPER --> AUDIO_GEN
    PIPER --> PHONEMES

    PHONEMES --> LIP_SYNC
    FACE --> BLEND
    LIP_SYNC --> BLEND
    EXPRESSION --> BLEND
    BLEND --> V4L2
```

## Pipeline Timing

```mermaid
sequenceDiagram
    participant Audio as Audio Input
    participant STT as STT Engine
    participant LLM as LLM
    participant TTS as TTS Engine
    participant Video as Video Gen

    Note over Audio,Video: Real-time pipeline (~500ms latency)

    Audio->>STT: Audio chunk (100ms)
    STT->>STT: Transcribe (200ms)
    STT->>LLM: Transcript
    LLM->>LLM: Generate (300ms)
    LLM->>TTS: Response text
    
    par Audio and Video
        TTS->>Audio: Audio output
        TTS->>Video: Phonemes
        Video->>Video: Generate frames
    end
```

## Intel NPU Acceleration

```mermaid
flowchart TB
    subgraph CPU[CPU Tasks]
        AUDIO[Audio I/O]
        BUFFER[Buffering]
        OUTPUT[Output Routing]
    end

    subgraph NPU[Intel NPU Tasks]
        STT_NPU[Whisper Inference]
        VAD_NPU[VAD Model]
        EMBED_NPU[Embeddings]
    end

    subgraph GPU[GPU Tasks]
        VIDEO_GPU[Video Rendering]
        LIP_GPU[Lip Sync]
    end

    AUDIO --> BUFFER
    BUFFER --> VAD_NPU
    VAD_NPU --> STT_NPU
    STT_NPU --> EMBED_NPU

    EMBED_NPU --> VIDEO_GPU
    VIDEO_GPU --> LIP_GPU
    LIP_GPU --> OUTPUT
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| audio_capture | `audio_capture.py` | PulseAudio capture |
| stt_engine | `stt_engine.py` | Whisper inference |
| voice_pipeline | `voice_pipeline.py` | Full voice pipeline |
| intel_streaming | `intel_streaming.py` | NPU acceleration |
| video_generator | `video_generator.py` | Frame generation |
| virtual_devices | `virtual_devices.py` | V4L2/PulseAudio setup |

## Latency Budget

| Stage | Target | Description |
|-------|--------|-------------|
| Audio capture | 50ms | Buffer size |
| VAD | 20ms | Voice detection |
| STT | 200ms | Transcription |
| LLM | 300ms | Response generation |
| TTS | 100ms | Speech synthesis |
| Video | 33ms | Frame generation (30fps) |
| **Total** | **~700ms** | End-to-end |

## Configuration

```json
{
  "pipeline": {
    "audio": {
      "sample_rate": 16000,
      "chunk_size": 1600,
      "channels": 1
    },
    "stt": {
      "model": "whisper-base",
      "device": "npu"
    },
    "tts": {
      "model": "piper-lessac",
      "sample_rate": 22050
    },
    "video": {
      "fps": 30,
      "resolution": [1280, 720]
    }
  }
}
```

## Related Diagrams

- [Meet Bot Tools](./meet-bot-tools.md)
- [Meet Daemon](../02-services/meet-daemon.md)
- [Video Daemon](../02-services/video-daemon.md)
