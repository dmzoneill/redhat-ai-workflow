"""
GPT-SoVITS Text-to-Speech Engine.

Provides voice cloning TTS using the trained "dave" model.
Uses subprocess to call GPT-SoVITS in its own venv.
"""

import asyncio
import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from tool_modules.aa_meet_bot.src.config import get_config

logger = logging.getLogger(__name__)

# GPT-SoVITS paths
GPT_SOVITS_ROOT = Path("/home/daoneill/src/GPT-SoVITS")
GPT_SOVITS_VENV = GPT_SOVITS_ROOT / "venv" / "bin" / "python"
VOICE_SAMPLES_DIR = Path(__file__).parent.parent / "voice_samples"


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
                    subprocess.run([
                        "ffmpeg", "-y", "-i", str(full_recording),
                        "-ss", "0", "-t", "10", "-ar", "32000", "-ac", "1",
                        str(self.ref_audio)
                    ], capture_output=True)
            
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
                    error="Failed to initialize TTS engine"
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
                None,
                self._synthesize_subprocess,
                text,
                str(ref_audio),
                ref_text,
                str(output_path)
            )
            
            if result.get("success"):
                return TTSResult(
                    audio_path=Path(result["output"]),
                    duration_seconds=result["duration"],
                    sample_rate=result["sample_rate"],
                    text=text,
                    success=True
                )
            else:
                return TTSResult(
                    audio_path=Path(""),
                    duration_seconds=0,
                    sample_rate=0,
                    text=text,
                    success=False,
                    error=result.get("error", "Unknown error")
                )
                
        except Exception as e:
            logger.error(f"TTS synthesis failed: {e}")
            return TTSResult(
                audio_path=Path(""),
                duration_seconds=0,
                sample_rate=0,
                text=text,
                success=False,
                error=str(e)
            )
    
    def _synthesize_subprocess(
        self,
        text: str,
        ref_audio_path: str,
        ref_text: str,
        output_path: str
    ) -> dict:
        """Run synthesis via subprocess in GPT-SoVITS venv."""
        try:
            cmd = [
                str(GPT_SOVITS_VENV),
                str(self._tts_script),
                "--gpt_model", str(self.gpt_model),
                "--sovits_model", str(self.sovits_model),
                "--ref_audio", ref_audio_path,
                "--ref_text", ref_text,
                "--text", text,
                "--output", output_path,
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(GPT_SOVITS_ROOT),
                env={**os.environ, "CUDA_VISIBLE_DEVICES": "0"}
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
    
    async def synthesize_stream(
        self,
        text: str,
        chunk_callback: callable
    ):
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


# Global engine instance
_tts_engine: Optional[GPTSoVITSEngine] = None


def get_tts_engine() -> GPTSoVITSEngine:
    """Get or create the global TTS engine instance."""
    global _tts_engine
    if _tts_engine is None:
        _tts_engine = GPTSoVITSEngine()
    return _tts_engine


async def synthesize_speech(text: str, output_filename: Optional[str] = None) -> TTSResult:
    """
    Convenience function to synthesize speech.
    
    Args:
        text: Text to synthesize
        output_filename: Optional output filename
        
    Returns:
        TTSResult with audio path and metadata
    """
    engine = get_tts_engine()
    return await engine.synthesize(text, output_filename)


