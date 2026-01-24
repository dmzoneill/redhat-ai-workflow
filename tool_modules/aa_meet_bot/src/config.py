"""
Meet Bot Configuration.

Centralizes all configuration for the Google Meet bot including:
- Account credentials
- Avatar image paths
- Audio/video device settings
- Model paths
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

logger = logging.getLogger(__name__)


async def get_google_credentials(email: str = "daoneill@redhat.com") -> Tuple[str, str]:
    """
    Get Google credentials from the redhatter API.

    Uses the same method as vpn-connect to fetch credentials securely.

    Args:
        email: The email address (used for context)

    Returns:
        Tuple of (username, password)
    """
    import aiohttp

    token_file = Path.home() / ".cache/redhatter/auth_token"
    if not token_file.exists():
        raise RuntimeError(f"Auth token not found at {token_file}. Start redhatter service first.")

    token = token_file.read_text().strip()
    if not token:
        raise RuntimeError("Auth token is empty")

    # Use the redhatter API to get credentials
    async with aiohttp.ClientSession() as session:
        headers = {"Authorization": f"Bearer {token}"}
        async with session.get(
            "http://localhost:8009/get_creds?context=associate&headless=false", headers=headers
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Failed to get credentials: {resp.status}")

            creds_text = await resp.text()
            # Response format: "username,password" (with quotes)
            creds = creds_text.strip().strip('"')
            parts = creds.split(",")
            if len(parts) < 2:
                raise RuntimeError(f"Invalid credentials format: {creds_text}")

            username = parts[0]
            password = parts[1]

            logger.info(f"Retrieved credentials for {username}")
            return (username, password)


@dataclass
class GoogleAccount:
    """Google account configuration."""

    email: str
    profile_dir: str  # Chrome profile directory for this account
    is_bot_account: bool = False  # True if this is the bot joining account


@dataclass
class AvatarConfig:
    """Avatar image and video configuration."""

    # Static image for lip-sync (cropped face)
    face_image: Path = Path("/home/daoneill/Documents/Identification/IMG_3249_.jpg")

    # Pre-generated video clips directory
    clips_dir: Path = Path.home() / ".local/share/meet_bot/clips"

    # Output resolution for real-time generation
    output_width: int = 256
    output_height: int = 256
    output_fps: int = 25


@dataclass
class AudioConfig:
    """Audio device configuration."""

    # Virtual sink for capturing meeting audio (legacy, shared)
    virtual_sink_name: str = "meet_bot_sink"

    # Virtual source for injecting bot audio (legacy, shared)
    virtual_source_name: str = "meet_bot_source"

    # Sample rate for audio processing
    sample_rate: int = 16000

    # Chunk size for real-time processing
    chunk_size: int = 1024

    # Output directory for generated audio
    output_dir: Path = Path.home() / ".local/share/meet_bot/audio"

    # Per-instance audio device settings
    pipe_dir: Path = Path.home() / ".local/share/meet_bot/pipes"
    max_concurrent_meetings: int = 2


@dataclass
class VoicePipelineConfig:
    """Voice interaction pipeline configuration."""

    # Wake word settings
    wake_word: str = "david"

    # STT settings (OpenVINO Whisper)
    stt_model: str = "base"  # tiny, base, small, medium, large-v3
    stt_device: str = "NPU"  # NPU, GPU, CPU

    # LLM settings
    llm_backend: str = "gemini"  # gemini (Vertex AI), ollama (local)
    llm_model: str = "gemini-2.5-pro"  # For gemini backend

    # TTS settings
    tts_backend: str = "piper"  # piper (fast), gpt-sovits (voice cloning)
    tts_voice: str = "en_US-lessac-medium"  # Piper voice model

    # Performance settings
    use_parallel_tts: bool = True  # Start TTS while LLM streams
    target_latency_ms: int = 1200  # Target end-to-end latency

    # Audio settings
    sample_rate: int = 16000
    silence_threshold: float = 0.02
    min_silence_ms: int = 800  # Pause detection
    max_utterance_ms: int = 30000  # Max recording length


@dataclass
class VideoConfig:
    """Video device configuration."""

    # v4l2loopback device for virtual camera
    virtual_camera_device: str = "/dev/video10"

    # Output format
    width: int = 640
    height: int = 480
    fps: int = 30

    # Mirror output horizontally for Google Meet
    # Google Meet mirrors the camera preview, so we pre-flip the video
    # so that meeting participants see it correctly (un-mirrored)
    # Set to True (default) so text/content appears correctly to viewers
    mirror_for_meet: bool = True


@dataclass
class ModelPaths:
    """Paths to AI models."""

    # GPT-SoVITS voice model (to be trained)
    gpt_sovits_model: Optional[Path] = None
    gpt_sovits_ref_audio: Optional[Path] = None

    # Wav2Lip model
    wav2lip_checkpoint: Path = Path.home() / ".local/share/meet_bot/models/wav2lip.pth"
    wav2lip_face_detect: Path = Path.home() / ".local/share/meet_bot/models/s3fd.pth"

    # Whisper model (fallback STT)
    whisper_model: str = "small"  # OpenVINO optimized

    # Wake word model (fallback)
    wake_word_model: Optional[Path] = None


@dataclass
class MeetBotConfig:
    """Main configuration for the Meet Bot."""

    # Google accounts
    host_account: GoogleAccount = field(
        default_factory=lambda: GoogleAccount(
            email="daoneill@redhat.com", profile_dir="~/.config/google-chrome/Default", is_bot_account=False
        )
    )

    # Bot account - uses Red Hat SSO for authentication
    bot_account: GoogleAccount = field(
        default_factory=lambda: GoogleAccount(
            email="daoneill@redhat.com", profile_dir="~/.config/meet-bot-chrome", is_bot_account=True
        )
    )

    # Avatar settings
    avatar: AvatarConfig = field(default_factory=AvatarConfig)

    # Audio settings
    audio: AudioConfig = field(default_factory=AudioConfig)

    # Video settings
    video: VideoConfig = field(default_factory=VideoConfig)

    # Model paths
    models: ModelPaths = field(default_factory=ModelPaths)

    # Voice pipeline settings
    voice_pipeline: VoicePipelineConfig = field(default_factory=VoicePipelineConfig)

    # Wake word (legacy, use voice_pipeline.wake_word)
    wake_word: str = "david"

    # Response settings
    max_response_length: int = 100  # Max words in response
    response_timeout: float = 30.0  # Seconds to wait for LLM response

    # Meeting settings
    auto_enable_captions: bool = True
    auto_mute_on_join: bool = True

    # Voice interaction settings
    enable_voice_pipeline: bool = False  # Enable real-time voice interaction

    # Data directories
    data_dir: Path = Path.home() / ".local/share/meet_bot"
    logs_dir: Path = Path.home() / ".local/share/meet_bot/logs"
    recordings_dir: Path = Path.home() / ".local/share/meet_bot/recordings"

    def ensure_directories(self) -> None:
        """Create all required directories."""
        for dir_path in [
            self.data_dir,
            self.logs_dir,
            self.recordings_dir,
            self.avatar.clips_dir,
            self.audio.output_dir,
            self.audio.pipe_dir,
            self.models.wav2lip_checkpoint.parent,
        ]:
            dir_path.mkdir(parents=True, exist_ok=True)


# Global config instance
_config: Optional[MeetBotConfig] = None


def get_config() -> MeetBotConfig:
    """Get the global config instance."""
    global _config
    if _config is None:
        _config = MeetBotConfig()
        _config.ensure_directories()
    return _config


def update_config(**kwargs) -> MeetBotConfig:
    """Update config with new values."""
    global _config
    if _config is None:
        _config = MeetBotConfig(**kwargs)
    else:
        for key, value in kwargs.items():
            if hasattr(_config, key):
                setattr(_config, key, value)
    _config.ensure_directories()
    return _config
