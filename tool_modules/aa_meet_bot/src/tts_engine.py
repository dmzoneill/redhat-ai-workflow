"""
Text-to-Speech Engine.

Provides TTS with multiple backends:
- Piper TTS (default): Fast, in-memory synthesis, good quality
- GPT-SoVITS: Voice cloning, higher quality but slower

Based on Xenith project approach for zero-copy audio processing.
"""

import asyncio
import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from tool_modules.aa_meet_bot.src.config import get_config

logger = logging.getLogger(__name__)

# GPT-SoVITS paths (for voice cloning backend)
GPT_SOVITS_ROOT = Path("/home/daoneill/src/GPT-SoVITS")
GPT_SOVITS_VENV = GPT_SOVITS_ROOT / "venv" / "bin" / "python"
VOICE_SAMPLES_DIR = Path(__file__).parent.parent / "voice_samples"

# Piper TTS paths
PIPER_MODELS_DIR = Path.home() / ".cache" / "piper"


@dataclass
class TTSResult:
    """Result of TTS synthesis."""

    audio_path: Path
    duration_seconds: float
    sample_rate: int
    text: str
    timestamp: datetime = field(default_factory=datetime.now)
    success: bool = True
    error: Optional[str] = None
    # In-memory audio data (optional, for zero-copy pipeline)
    audio_data: Optional[np.ndarray] = None


class PiperTTS:
    """
    Piper TTS engine for fast synthesis.

    Uses the piper CLI for synthesis, which is more reliable than the Python package.
    """

    # Available voices (download from https://github.com/rhasspy/piper/releases)
    DEFAULT_VOICE = "en_US-lessac-medium"

    def __init__(self, voice: str = DEFAULT_VOICE):
        """
        Initialize Piper TTS.

        Args:
            voice: Voice model name (e.g., "en_US-lessac-medium")
        """
        self.voice = voice
        self._initialized = False
        self._model_path: Optional[Path] = None
        self._config_path: Optional[Path] = None
        self._piper_cli: Optional[str] = None

    async def initialize(self) -> bool:
        """Initialize the Piper TTS (check CLI is available)."""
        if self._initialized:
            return True

        try:
            import shutil

            # Check for piper CLI
            self._piper_cli = shutil.which("piper")
            if not self._piper_cli:
                logger.error("piper CLI not found. Install from: https://github.com/rhasspy/piper/releases")
                return False

            # Find or download model
            model_path = await self._get_model_path()
            if not model_path:
                logger.warning(f"Model {self.voice} not found, will try to download on first use")

            self._initialized = True
            logger.info(f"Piper TTS ready (CLI: {self._piper_cli}, voice: {self.voice})")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize Piper TTS: {e}")
            return False

    async def _get_model_path(self) -> Optional[Path]:
        """Get or download the voice model."""
        PIPER_MODELS_DIR.mkdir(parents=True, exist_ok=True)

        model_path = PIPER_MODELS_DIR / f"{self.voice}.onnx"
        config_path = PIPER_MODELS_DIR / f"{self.voice}.onnx.json"

        if model_path.exists() and config_path.exists():
            self._model_path = model_path
            self._config_path = config_path
            return model_path

        # Try to download model
        logger.info(f"Downloading Piper voice model: {self.voice}")

        try:
            # Use piper_download if available
            import subprocess

            result = subprocess.run(
                ["piper", "--download-dir", str(PIPER_MODELS_DIR), "--model", self.voice, "--update-voices"],
                capture_output=True,
                text=True,
                timeout=120,
            )

            if model_path.exists():
                self._model_path = model_path
                self._config_path = config_path
                return model_path

            # Manual download fallback
            base_url = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
            voice_parts = self.voice.split("-")
            lang = voice_parts[0]  # e.g., "en_US"

            import urllib.request

            model_url = f"{base_url}/{lang}/{self.voice}/{self.voice}.onnx"
            config_url = f"{base_url}/{lang}/{self.voice}/{self.voice}.onnx.json"

            urllib.request.urlretrieve(model_url, model_path)
            urllib.request.urlretrieve(config_url, config_path)

            if model_path.exists():
                self._model_path = model_path
                self._config_path = config_path
                return model_path

        except Exception as e:
            logger.error(f"Failed to download voice model: {e}")

        return None

    def synthesize(self, text: str) -> Tuple[np.ndarray, int]:
        """
        Synthesize text to audio using piper CLI.

        Args:
            text: Text to synthesize

        Returns:
            Tuple of (audio_data as float32 numpy array, sample_rate)
        """
        if not self._initialized or not self._piper_cli:
            raise RuntimeError("Piper TTS not initialized")

        import subprocess

        try:
            # Get full path to model file
            model_path = self._model_path
            if not model_path or not model_path.exists():
                # Try to find model in cache
                model_path = PIPER_MODELS_DIR / f"{self.voice}.onnx"
                if not model_path.exists():
                    logger.error(f"Model not found: {model_path}")
                    return np.array([], dtype=np.float32), 22050

            # Build piper command - output raw audio to stdout
            cmd = [
                self._piper_cli,
                "--model",
                str(model_path),
                "--output-raw",
            ]

            logger.debug(f"Running piper: {' '.join(cmd)}")

            # Run piper with text on stdin
            result = subprocess.run(cmd, input=text.encode(), capture_output=True, timeout=30)

            if result.returncode != 0:
                logger.error(f"Piper CLI error: {result.stderr.decode()}")
                return np.array([], dtype=np.float32), 22050

            # Parse raw audio (16-bit signed, mono, 22050 Hz by default)
            audio_data = np.frombuffer(result.stdout, dtype=np.int16)
            audio_data = audio_data.astype(np.float32) / 32768.0

            sample_rate = 22050  # Piper default
            logger.info(f"Piper synthesized {len(audio_data)} samples ({len(audio_data)/sample_rate:.1f}s)")

            return audio_data, sample_rate

        except subprocess.TimeoutExpired:
            logger.error("Piper CLI timed out")
            return np.array([], dtype=np.float32), 22050
        except Exception as e:
            logger.error(f"Piper synthesis error: {e}")
            return np.array([], dtype=np.float32), 22050

    async def synthesize_async(self, text: str) -> Tuple[np.ndarray, int]:
        """Async wrapper for synthesize."""
        if not self._initialized:
            await self.initialize()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.synthesize, text)

    async def synthesize_to_result(
        self,
        text: str,
        save_to_file: bool = False,
        output_dir: Optional[Path] = None,
    ) -> TTSResult:
        """
        Synthesize and return a TTSResult.

        Args:
            text: Text to synthesize
            save_to_file: Whether to also save to a file
            output_dir: Directory for output file (if saving)

        Returns:
            TTSResult with in-memory audio data
        """
        if not self._initialized:
            if not await self.initialize():
                return TTSResult(
                    audio_path=Path(""),
                    duration_seconds=0,
                    sample_rate=0,
                    text=text,
                    success=False,
                    error="Failed to initialize Piper TTS",
                )

        try:
            audio_data, sample_rate = await self.synthesize_async(text)
            duration = len(audio_data) / sample_rate

            audio_path = Path("")
            if save_to_file:
                output_dir = output_dir or get_config().audio.output_dir
                output_dir.mkdir(parents=True, exist_ok=True)

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                audio_path = output_dir / f"piper_{timestamp}.wav"

                # Save to file
                import wave

                with wave.open(str(audio_path), "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)  # 16-bit
                    wav.setframerate(sample_rate)
                    # Convert back to int16 for file
                    audio_int16 = (audio_data * 32767).astype(np.int16)
                    wav.writeframes(audio_int16.tobytes())

            return TTSResult(
                audio_path=audio_path,
                duration_seconds=duration,
                sample_rate=sample_rate,
                text=text,
                success=True,
                audio_data=audio_data,
            )

        except Exception as e:
            logger.error(f"Piper TTS synthesis failed: {e}")
            return TTSResult(
                audio_path=Path(""), duration_seconds=0, sample_rate=0, text=text, success=False, error=str(e)
            )


class GPTSoVITSEngine:
    """
    GPT-SoVITS voice cloning TTS engine.

    Uses subprocess to call GPT-SoVITS in its own virtual environment.
    """

    def __init__(self):
        self.config = get_config()
        self.initialized = False

        # Model paths
        self.gpt_model = GPT_SOVITS_ROOT / "GPT_weights_v2Pro" / "dave-e50.ckpt"
        self.sovits_model = GPT_SOVITS_ROOT / "SoVITS_weights_v2Pro" / "dave_e12_s240.pth"

        # Reference audio for voice cloning
        self.ref_audio = VOICE_SAMPLES_DIR / "ref_clip.wav"
        self.ref_text = "The quick brown fox jumps over the lazy dog."

        # Output directory
        self.output_dir = Path(self.config.audio.output_dir).expanduser()
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Create TTS script path
        self._tts_script = self._create_tts_script()

    def _create_tts_script(self) -> Path:
        """Create a standalone TTS script that runs in GPT-SoVITS venv."""
        script_path = self.output_dir / "run_tts.py"

        script_content = '''#!/usr/bin/env python3
"""Standalone TTS script for GPT-SoVITS."""
import sys
import json
import argparse

# Add GPT-SoVITS to path
sys.path.insert(0, "/home/daoneill/src/GPT-SoVITS")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gpt_model", required=True)
    parser.add_argument("--sovits_model", required=True)
    parser.add_argument("--ref_audio", required=True)
    parser.add_argument("--ref_text", required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    try:
        import soundfile as sf
        from GPT_SoVITS.inference_webui import (
            change_gpt_weights,
            change_sovits_weights,
            get_tts_wav,
        )
        from tools.i18n.i18n import I18nAuto
        i18n = I18nAuto()

        # Load models
        change_gpt_weights(gpt_path=args.gpt_model)
        change_sovits_weights(sovits_path=args.sovits_model)

        # Synthesize - use i18n for language keys
        synthesis_result = get_tts_wav(
            ref_wav_path=args.ref_audio,
            prompt_text=args.ref_text,
            prompt_language=i18n("英文"),  # "English"
            text=args.text,
            text_language=i18n("英文"),  # "English"
            top_p=1,
            temperature=1,
        )

        result_list = list(synthesis_result)

        if result_list:
            sample_rate, audio_data = result_list[-1]
            sf.write(args.output, audio_data, sample_rate)

            # Output result as JSON
            info = sf.info(args.output)
            print(json.dumps({
                "success": True,
                "output": args.output,
                "duration": info.duration,
                "sample_rate": info.samplerate
            }))
        else:
            print(json.dumps({"success": False, "error": "No audio generated"}))

    except Exception as e:
        import traceback
        print(json.dumps({"success": False, "error": str(e), "traceback": traceback.format_exc()}))
        sys.exit(1)

if __name__ == "__main__":
    main()
'''

        script_path.write_text(script_content)
        script_path.chmod(0o755)
        return script_path

    async def initialize(self) -> bool:
        """Check that GPT-SoVITS is available."""
        if self.initialized:
            return True

        try:
            # Check venv exists
            if not GPT_SOVITS_VENV.exists():
                logger.error(f"GPT-SoVITS venv not found: {GPT_SOVITS_VENV}")
                return False

            # Check models exist
            if not self.gpt_model.exists():
                logger.error(f"GPT model not found: {self.gpt_model}")
                return False

            if not self.sovits_model.exists():
                logger.error(f"SoVITS model not found: {self.sovits_model}")
                return False

            # Check reference audio
            if not self.ref_audio.exists():
                logger.warning(f"Reference audio not found: {self.ref_audio}")
                # Try to create from full recording
                full_recording = VOICE_SAMPLES_DIR / "reference.wav"
                if full_recording.exists():
                    logger.info("Creating reference clip from full recording...")
                    subprocess.run(
                        [
                            "ffmpeg",
                            "-y",
                            "-i",
                            str(full_recording),
                            "-ss",
                            "0",
                            "-t",
                            "10",
                            "-ar",
                            "32000",
                            "-ac",
                            "1",
                            str(self.ref_audio),
                        ],
                        capture_output=True,
                    )

            self.initialized = True
            logger.info("GPT-SoVITS engine ready")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize GPT-SoVITS: {e}")
            return False

    async def synthesize(
        self,
        text: str,
        output_filename: Optional[str] = None,
        ref_audio: Optional[Path] = None,
        ref_text: Optional[str] = None,
    ) -> TTSResult:
        """
        Synthesize speech from text using voice cloning.

        Args:
            text: Text to synthesize
            output_filename: Optional output filename (auto-generated if not provided)
            ref_audio: Optional reference audio (uses default if not provided)
            ref_text: Optional reference text (uses default if not provided)

        Returns:
            TTSResult with audio path and metadata
        """
        if not self.initialized:
            if not await self.initialize():
                return TTSResult(
                    audio_path=Path(""),
                    duration_seconds=0,
                    sample_rate=0,
                    text=text,
                    success=False,
                    error="Failed to initialize TTS engine",
                )

        try:
            # Use defaults if not provided
            ref_audio = ref_audio or self.ref_audio
            ref_text = ref_text or self.ref_text

            # Generate output filename
            if not output_filename:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_filename = f"tts_{timestamp}.wav"

            output_path = self.output_dir / output_filename

            logger.info(f"Synthesizing: '{text[:50]}...' -> {output_path}")

            # Run synthesis via subprocess
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self._synthesize_subprocess, text, str(ref_audio), ref_text, str(output_path)
            )

            if result.get("success"):
                return TTSResult(
                    audio_path=Path(result["output"]),
                    duration_seconds=result["duration"],
                    sample_rate=result["sample_rate"],
                    text=text,
                    success=True,
                )
            else:
                return TTSResult(
                    audio_path=Path(""),
                    duration_seconds=0,
                    sample_rate=0,
                    text=text,
                    success=False,
                    error=result.get("error", "Unknown error"),
                )

        except Exception as e:
            logger.error(f"TTS synthesis failed: {e}")
            return TTSResult(
                audio_path=Path(""), duration_seconds=0, sample_rate=0, text=text, success=False, error=str(e)
            )

    def _synthesize_subprocess(self, text: str, ref_audio_path: str, ref_text: str, output_path: str) -> dict:
        """Run synthesis via subprocess in GPT-SoVITS venv."""
        try:
            cmd = [
                str(GPT_SOVITS_VENV),
                str(self._tts_script),
                "--gpt_model",
                str(self.gpt_model),
                "--sovits_model",
                str(self.sovits_model),
                "--ref_audio",
                ref_audio_path,
                "--ref_text",
                ref_text,
                "--text",
                text,
                "--output",
                output_path,
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(GPT_SOVITS_ROOT),
                env={**os.environ, "CUDA_VISIBLE_DEVICES": "0"},
            )

            # Parse JSON output
            for line in result.stdout.strip().split("\n"):
                if line.startswith("{"):
                    return json.loads(line)

            # If no JSON found, check stderr
            if result.returncode != 0:
                return {"success": False, "error": result.stderr[:500]}

            return {"success": False, "error": "No output from TTS"}

        except subprocess.TimeoutExpired:
            return {"success": False, "error": "TTS timed out (120s)"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def synthesize_stream(self, text: str, chunk_callback: callable):
        """
        Stream synthesis for lower latency.

        Calls chunk_callback with each audio chunk as it's generated.
        """
        # For now, fall back to full synthesis
        result = await self.synthesize(text)
        if result.success:
            import soundfile as sf

            audio_data, sample_rate = sf.read(str(result.audio_path))
            await chunk_callback(audio_data, sample_rate)


class TTSEngine:
    """
    Unified TTS engine with multiple backends.

    Backends:
    - piper: Fast, in-memory synthesis (default)
    - gpt-sovits: Voice cloning, higher quality
    """

    def __init__(self, backend: str = "piper"):
        """
        Initialize TTS engine.

        Args:
            backend: "piper" (default, fast) or "gpt-sovits" (voice cloning)
        """
        self.backend = backend
        self._piper: Optional[PiperTTS] = None
        self._gpt_sovits: Optional[GPTSoVITSEngine] = None

    async def initialize(self) -> bool:
        """Initialize the selected backend."""
        if self.backend == "piper":
            self._piper = PiperTTS()
            return await self._piper.initialize()
        else:
            self._gpt_sovits = GPTSoVITSEngine()
            return await self._gpt_sovits.initialize()

    async def synthesize(
        self,
        text: str,
        output_filename: Optional[str] = None,
    ) -> TTSResult:
        """
        Synthesize text to speech.

        Args:
            text: Text to synthesize
            output_filename: Optional output filename (for file-based output)

        Returns:
            TTSResult with audio data and/or path
        """
        if self.backend == "piper":
            if not self._piper:
                self._piper = PiperTTS()
            return await self._piper.synthesize_to_result(
                text,
                save_to_file=bool(output_filename),
            )
        else:
            if not self._gpt_sovits:
                self._gpt_sovits = GPTSoVITSEngine()
            return await self._gpt_sovits.synthesize(text, output_filename)

    def synthesize_sync(self, text: str) -> Tuple[np.ndarray, int]:
        """
        Synchronous synthesis for low-latency pipeline.

        Only available with Piper backend.

        Returns:
            Tuple of (audio_data, sample_rate)
        """
        if self.backend != "piper" or not self._piper:
            raise RuntimeError("Sync synthesis only available with Piper backend")
        return self._piper.synthesize(text)

    async def speak_to_pipe(self, text: str, pipe_path: Path) -> float:
        """
        Synthesize text and write audio to a named pipe for Chrome mic injection.

        The pipe expects 16kHz, 16-bit, mono PCM audio.

        Adds silence padding at start/end to prevent choppy audio from
        PulseAudio latency and pipe buffering.

        Args:
            text: Text to synthesize
            pipe_path: Path to the named pipe (e.g., /tmp/meet_bot_audio_pipe)

        Returns:
            Duration in seconds of audio written, or 0 on failure
        """
        try:
            # Synthesize audio
            result = await self.synthesize(text)
            if not result.success or result.audio_data is None:
                logger.error(f"TTS synthesis failed: {result.error}")
                return 0.0

            audio_data = result.audio_data
            sample_rate = result.sample_rate

            # Resample to 16kHz if needed (Chrome mic expects 16kHz)
            target_rate = 16000
            if sample_rate != target_rate:
                import scipy.signal

                num_samples = int(len(audio_data) * target_rate / sample_rate)
                audio_data = scipy.signal.resample(audio_data, num_samples)
                sample_rate = target_rate

            # === AUDIO ENHANCEMENT FOR SMOOTH PLAYBACK ===

            # 1. Normalize audio to consistent level (prevents clipping and ensures audibility)
            max_val = np.max(np.abs(audio_data))
            if max_val > 0:
                audio_data = audio_data / max_val * 0.85  # Normalize to 85% to leave headroom

            # 2. Apply fade-in and fade-out to prevent clicks/pops
            fade_in_samples = int(sample_rate * 0.05)  # 50ms fade-in
            fade_out_samples = int(sample_rate * 0.08)  # 80ms fade-out

            # Fade-in curve (smooth cosine)
            fade_in = (1 - np.cos(np.linspace(0, np.pi, fade_in_samples))) / 2
            audio_data[:fade_in_samples] *= fade_in

            # Fade-out curve
            fade_out = (1 + np.cos(np.linspace(0, np.pi, fade_out_samples))) / 2
            audio_data[-fade_out_samples:] *= fade_out

            # 3. Add minimal silence padding with very low white noise
            # Reduced for faster response - the virtual pipe doesn't need much settling time
            noise_level = 0.0005  # Very quiet

            # Lead-in: 100ms (reduced from 500ms - virtual pipe is always ready)
            lead_in_samples = int(sample_rate * 0.1)
            silence_start = np.random.randn(lead_in_samples).astype(np.float32) * noise_level

            # Tail: 200ms (reduced from 800ms - just enough for audio to finish)
            tail_samples = int(sample_rate * 0.2)
            silence_end = np.random.randn(tail_samples).astype(np.float32) * noise_level

            # 4. Add a brief "wake-up" tone at the very start (helps PA/PW activate the stream)
            # This is a very short, very quiet 440Hz blip
            wake_samples = int(sample_rate * 0.02)  # 20ms
            t = np.linspace(0, 0.02, wake_samples)
            wake_tone = np.sin(2 * np.pi * 440 * t) * 0.01  # Very quiet
            wake_tone *= (1 - np.cos(np.linspace(0, np.pi, wake_samples))) / 2  # Fade envelope
            silence_start[:wake_samples] += wake_tone.astype(np.float32)

            audio_data = np.concatenate([silence_start, audio_data, silence_end])

            logger.info(
                f"Audio enhanced: {lead_in_samples/sample_rate:.2f}s lead-in, "
                f"{tail_samples/sample_rate:.2f}s tail, fade in/out applied"
            )

            # Convert to 16-bit PCM
            audio_int16 = (audio_data * 32767).astype(np.int16)

            duration = len(audio_int16) / sample_rate
            logger.info(f"Writing {len(audio_int16)} samples ({duration:.1f}s) to pipe: {pipe_path}")

            # Write to pipe using blocking I/O for reliability
            # Run in executor to not block the event loop
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(
                None, self._write_to_pipe_blocking, str(pipe_path), audio_int16.tobytes()
            )

            if success:
                logger.info("Successfully wrote audio to pipe")
                return duration
            else:
                return 0.0

        except Exception as e:
            logger.error(f"Failed to write to pipe: {e}")
            return 0.0

    def _write_to_pipe_blocking(self, pipe_path: str, audio_bytes: bytes) -> bool:
        """Write audio to pipe using blocking I/O (runs in thread pool)."""
        import os

        try:
            # Open pipe for writing (blocking mode)
            # This will wait until a reader is ready
            fd = os.open(pipe_path, os.O_WRONLY)
            try:
                # Write all data
                total_written = 0
                while total_written < len(audio_bytes):
                    written = os.write(fd, audio_bytes[total_written:])
                    if written == 0:
                        logger.warning("Pipe write returned 0")
                        break
                    total_written += written

                logger.debug(f"Wrote {total_written} bytes to pipe")
                return total_written == len(audio_bytes)
            finally:
                os.close(fd)

        except FileNotFoundError:
            logger.error(f"Pipe not found: {pipe_path}")
            return False
        except BrokenPipeError:
            logger.warning("Pipe reader closed")
            return False
        except Exception as e:
            logger.error(f"Pipe write error: {e}")
            return False


# Global engine instances
_tts_engine: Optional[TTSEngine] = None
_gpt_sovits_engine: Optional[GPTSoVITSEngine] = None


def get_tts_engine(backend: str = "piper") -> TTSEngine:
    """
    Get or create the global TTS engine instance.

    Args:
        backend: "piper" (default, fast) or "gpt-sovits" (voice cloning)
    """
    global _tts_engine
    if _tts_engine is None or _tts_engine.backend != backend:
        _tts_engine = TTSEngine(backend=backend)
    return _tts_engine


def get_gpt_sovits_engine() -> GPTSoVITSEngine:
    """Get the GPT-SoVITS engine specifically (for voice cloning)."""
    global _gpt_sovits_engine
    if _gpt_sovits_engine is None:
        _gpt_sovits_engine = GPTSoVITSEngine()
    return _gpt_sovits_engine


async def synthesize_speech(
    text: str,
    output_filename: Optional[str] = None,
    backend: str = "piper",
) -> TTSResult:
    """
    Convenience function to synthesize speech.

    Args:
        text: Text to synthesize
        output_filename: Optional output filename
        backend: "piper" (fast) or "gpt-sovits" (voice cloning)

    Returns:
        TTSResult with audio path and metadata
    """
    engine = get_tts_engine(backend)
    return await engine.synthesize(text, output_filename)
