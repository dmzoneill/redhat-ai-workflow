"""
Google Meet Bot - AI-powered meeting assistant.

This module provides:
- Browser automation to join Google Meet meetings
- Caption capture for transcription (primary) with Whisper fallback
- Wake-word detection ("David") for command activation
- GPT-SoVITS voice cloning for responses
- Wav2Lip lip-sync for avatar video generation
- Virtual audio/video device management
"""

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT
__version__ = "0.1.0"


