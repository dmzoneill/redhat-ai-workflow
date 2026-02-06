# Video Daemon

> Virtual camera and avatar generation pipeline

## Diagram

```mermaid
flowchart TB
    subgraph Input[Input Sources]
        AUDIO[Audio Input]
        TEXT[Text Input]
        EMOTION[Emotion Cues]
    end

    subgraph Processing[Video Processing]
        subgraph Avatar[Avatar Generation]
            FACE[Face Model]
            LIP[Lip Sync]
            EXPR[Expression]
            BLEND[Blending]
        end

        subgraph Effects[Visual Effects]
            BG[Background]
            OVERLAY[Overlays]
            FILTER[Filters]
        end
    end

    subgraph Output[Output]
        FRAMES[Frame Buffer]
        V4L2[V4L2 Loopback]
        VIRTUAL[Virtual Camera]
    end

    AUDIO --> LIP
    TEXT --> EXPR
    EMOTION --> EXPR

    FACE --> BLEND
    LIP --> BLEND
    EXPR --> BLEND

    BLEND --> BG
    BG --> OVERLAY
    OVERLAY --> FILTER

    FILTER --> FRAMES
    FRAMES --> V4L2
    V4L2 --> VIRTUAL
```

## Class Structure

```mermaid
classDiagram
    class VideoDaemon {
        +name: str = "video"
        +service_name: str
        -_generator: VideoGenerator
        -_v4l2_device: str
        -_frame_rate: int
        -_running: bool
        +startup() async
        +run_daemon() async
        +shutdown() async
        +set_avatar(config) async
        +set_expression(expr) async
        +get_service_stats() async
    }

    class VideoGenerator {
        +face_model: FaceModel
        +lip_sync: LipSync
        +expression_engine: ExpressionEngine
        +generate_frame(audio): ndarray
        +set_background(bg)
        +set_overlay(overlay)
    }

    class V4L2Output {
        +device: str
        +width: int
        +height: int
        +fps: int
        +open()
        +write_frame(frame)
        +close()
    }

    class AvatarConfig {
        +model_path: str
        +background: str
        +expressions: dict
        +lip_sync_enabled: bool
    }

    VideoDaemon --> VideoGenerator
    VideoDaemon --> V4L2Output
    VideoGenerator --> AvatarConfig
```

## Pipeline Flow

```mermaid
sequenceDiagram
    participant Audio as Audio Source
    participant Daemon as VideoDaemon
    participant Gen as VideoGenerator
    participant Lip as LipSync
    participant Expr as Expression
    participant V4L2 as V4L2 Device
    participant App as Video App

    loop Frame Generation
        Audio->>Daemon: Audio chunk
        Daemon->>Lip: Analyze phonemes
        Lip-->>Gen: Mouth shape

        Daemon->>Expr: Get expression
        Expr-->>Gen: Face expression

        Gen->>Gen: Render frame
        Gen-->>Daemon: Frame data

        Daemon->>V4L2: Write frame
        V4L2-->>App: Virtual camera feed
    end
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| VideoDaemon | `services/video/daemon.py` | Main daemon class |
| VideoGenerator | `tool_modules/aa_meet_bot/src/video_generator.py` | Frame generation |
| AvatarGenerator | `tool_modules/aa_meet_bot/src/avatar_generator.py` | Avatar rendering |
| IntelStreaming | `tool_modules/aa_meet_bot/src/intel_streaming.py` | Intel NPU acceleration |

## V4L2 Setup

```bash
# Load v4l2loopback module
sudo modprobe v4l2loopback devices=1 video_nr=10 \
    card_label="AI Avatar" exclusive_caps=1

# Check device
v4l2-ctl --list-devices
```

## D-Bus Methods

| Method | Description |
|--------|-------------|
| `start_video()` | Start video output |
| `stop_video()` | Stop video output |
| `set_avatar(config)` | Change avatar config |
| `set_expression(expr)` | Set expression |
| `set_background(bg)` | Change background |
| `get_frame_rate()` | Get current FPS |

## Configuration

```json
{
  "video": {
    "device": "/dev/video10",
    "width": 1280,
    "height": 720,
    "fps": 30,
    "avatar": {
      "model": "default",
      "background": "blur",
      "lip_sync": true
    }
  }
}
```

## Related Diagrams

- [Daemon Overview](./daemon-overview.md)
- [Meet Daemon](./meet-daemon.md)
- [Meet Bot Pipeline](../03-tools/meet-bot-pipeline.md)
