"""
Video Avatar Generator.

Provides lip-sync video generation using:
- Primary: Wav2Lip for real-time lip-sync on RTX 4060
- Fallback: Pre-generated video clips for common phrases

Hardware: RTX 4060 6GB VRAM
Target: 256x256 @ 25fps
"""

import asyncio
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List

import numpy as np

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from tool_modules.aa_meet_bot.src.config import get_config

logger = logging.getLogger(__name__)

# Paths
WAV2LIP_ROOT = Path("/home/daoneill/src/Wav2Lip")
AVATAR_IMAGE = Path("/home/daoneill/Documents/Identification/IMG_3249_.jpg")


@dataclass
class VideoResult:
    """Result of video generation."""
    video_path: Path
    duration_seconds: float
    resolution: tuple[int, int]
    fps: int
    timestamp: datetime = field(default_factory=datetime.now)
    success: bool = True
    error: Optional[str] = None
    source: str = "wav2lip"  # "wav2lip", "pregenerated", "static"


@dataclass
class PreGeneratedClip:
    """A pre-generated video clip for common phrases."""
    phrase: str
    video_path: Path
    audio_path: Path
    duration_seconds: float
    keywords: List[str] = field(default_factory=list)


class VideoGenerator:
    """
    Video avatar generator with lip-sync.
    
    Uses Wav2Lip for real-time generation or falls back to pre-generated clips.
    """
    
    def __init__(self):
        self.config = get_config()
        self.initialized = False
        self.wav2lip_available = False
        
        # Avatar image
        self.avatar_image = AVATAR_IMAGE
        
        # Output settings
        self.output_resolution = (256, 256)
        self.output_fps = 25
        
        # Output directory
        self.output_dir = Path(self.config.avatar.clips_dir).expanduser()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Pre-generated clips cache
        self.clips_cache: dict[str, PreGeneratedClip] = {}
        
    async def initialize(self) -> bool:
        """Initialize the video generator."""
        if self.initialized:
            return True
            
        try:
            # Check if Wav2Lip is available
            if WAV2LIP_ROOT.exists():
                # Check for required model
                checkpoint = WAV2LIP_ROOT / "checkpoints" / "wav2lip_gan.pth"
                if checkpoint.exists():
                    self.wav2lip_available = True
                    logger.info("Wav2Lip available with checkpoint")
                else:
                    logger.warning(f"Wav2Lip checkpoint not found: {checkpoint}")
                    logger.info("Run: cd ~/src/Wav2Lip && ./download_models.sh")
            else:
                logger.warning(f"Wav2Lip not found at {WAV2LIP_ROOT}")
                logger.info("To install: git clone https://github.com/Rudrabha/Wav2Lip ~/src/Wav2Lip")
            
            # Load pre-generated clips
            await self._load_pregenerated_clips()
            
            self.initialized = True
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize video generator: {e}")
            return False
    
    async def _load_pregenerated_clips(self):
        """Load pre-generated video clips from disk."""
        clips_dir = self.output_dir / "pregenerated"
        if not clips_dir.exists():
            clips_dir.mkdir(parents=True, exist_ok=True)
            return
            
        # Look for clip metadata files
        for meta_file in clips_dir.glob("*.json"):
            try:
                import json
                with open(meta_file) as f:
                    data = json.load(f)
                
                clip = PreGeneratedClip(
                    phrase=data["phrase"],
                    video_path=clips_dir / data["video_file"],
                    audio_path=clips_dir / data["audio_file"],
                    duration_seconds=data["duration"],
                    keywords=data.get("keywords", [])
                )
                
                if clip.video_path.exists():
                    self.clips_cache[clip.phrase.lower()] = clip
                    logger.debug(f"Loaded pre-generated clip: {clip.phrase}")
                    
            except Exception as e:
                logger.warning(f"Failed to load clip metadata {meta_file}: {e}")
    
    async def generate_video(
        self,
        audio_path: Path,
        output_filename: Optional[str] = None,
        use_pregenerated: bool = True
    ) -> VideoResult:
        """
        Generate lip-sync video from audio.
        
        Args:
            audio_path: Path to audio file
            output_filename: Optional output filename
            use_pregenerated: Whether to check for pre-generated clips first
            
        Returns:
            VideoResult with video path and metadata
        """
        if not self.initialized:
            await self.initialize()
        
        # Generate output filename
        if not output_filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"avatar_{timestamp}.mp4"
        
        output_path = self.output_dir / output_filename
        
        # Try Wav2Lip if available
        if self.wav2lip_available:
            result = await self._generate_wav2lip(audio_path, output_path)
            if result.success:
                return result
            logger.warning(f"Wav2Lip failed: {result.error}, trying fallback")
        
        # Fallback: Generate static video with audio
        return await self._generate_static_video(audio_path, output_path)
    
    async def _generate_wav2lip(
        self,
        audio_path: Path,
        output_path: Path
    ) -> VideoResult:
        """Generate video using Wav2Lip."""
        try:
            logger.info(f"Generating Wav2Lip video: {audio_path} -> {output_path}")
            
            # Wav2Lip command - use system python to ensure correct environment
            cmd = [
                "python",  # Use system python for Wav2Lip dependencies
                str(WAV2LIP_ROOT / "inference.py"),
                "--checkpoint_path", str(WAV2LIP_ROOT / "checkpoints" / "wav2lip_gan.pth"),
                "--face", str(self.avatar_image),
                "--audio", str(audio_path),
                "--outfile", str(output_path),
                "--resize_factor", "2",  # Faster processing
            ]
            
            # Run in subprocess
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    cwd=str(WAV2LIP_ROOT),
                    timeout=120  # 2 minute timeout
                )
            )
            
            if result.returncode == 0 and output_path.exists():
                # Get video info
                duration = await self._get_video_duration(output_path)
                
                return VideoResult(
                    video_path=output_path,
                    duration_seconds=duration,
                    resolution=self.output_resolution,
                    fps=self.output_fps,
                    source="wav2lip"
                )
            else:
                return VideoResult(
                    video_path=Path(""),
                    duration_seconds=0,
                    resolution=(0, 0),
                    fps=0,
                    success=False,
                    error=f"Wav2Lip failed: {result.stderr[:500]}"
                )
                
        except subprocess.TimeoutExpired:
            return VideoResult(
                video_path=Path(""),
                duration_seconds=0,
                resolution=(0, 0),
                fps=0,
                success=False,
                error="Wav2Lip timed out"
            )
        except Exception as e:
            return VideoResult(
                video_path=Path(""),
                duration_seconds=0,
                resolution=(0, 0),
                fps=0,
                success=False,
                error=str(e)
            )
    
    async def _generate_static_video(
        self,
        audio_path: Path,
        output_path: Path
    ) -> VideoResult:
        """Generate static image video with audio (fallback)."""
        try:
            logger.info(f"Generating static video: {audio_path} -> {output_path}")
            
            # Use ffmpeg to create video from static image + audio
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1",
                "-i", str(self.avatar_image),
                "-i", str(audio_path),
                "-c:v", "libx264",
                "-tune", "stillimage",
                "-c:a", "aac",
                "-b:a", "192k",
                "-pix_fmt", "yuv420p",
                "-vf", f"scale={self.output_resolution[0]}:{self.output_resolution[1]}",
                "-shortest",
                "-r", str(self.output_fps),
                str(output_path)
            ]
            
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=60
                )
            )
            
            if result.returncode == 0 and output_path.exists():
                duration = await self._get_video_duration(output_path)
                
                return VideoResult(
                    video_path=output_path,
                    duration_seconds=duration,
                    resolution=self.output_resolution,
                    fps=self.output_fps,
                    source="static"
                )
            else:
                return VideoResult(
                    video_path=Path(""),
                    duration_seconds=0,
                    resolution=(0, 0),
                    fps=0,
                    success=False,
                    error=f"FFmpeg failed: {result.stderr[:500]}"
                )
                
        except Exception as e:
            return VideoResult(
                video_path=Path(""),
                duration_seconds=0,
                resolution=(0, 0),
                fps=0,
                success=False,
                error=str(e)
            )
    
    async def _get_video_duration(self, video_path: Path) -> float:
        """Get video duration using ffprobe."""
        try:
            cmd = [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            return float(result.stdout.strip())
        except:
            return 0.0
    
    async def pregenerate_clip(
        self,
        phrase: str,
        audio_path: Path,
        keywords: Optional[List[str]] = None
    ) -> PreGeneratedClip:
        """
        Pre-generate a video clip for a common phrase.
        
        Args:
            phrase: The phrase text
            audio_path: Path to the audio file
            keywords: Optional keywords for matching
            
        Returns:
            PreGeneratedClip object
        """
        import json
        
        clips_dir = self.output_dir / "pregenerated"
        clips_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate safe filename
        safe_name = "".join(c if c.isalnum() else "_" for c in phrase[:30])
        video_filename = f"{safe_name}.mp4"
        
        # Generate video
        result = await self.generate_video(
            audio_path,
            output_filename=f"pregenerated/{video_filename}",
            use_pregenerated=False
        )
        
        if not result.success:
            raise RuntimeError(f"Failed to generate clip: {result.error}")
        
        # Create clip object
        clip = PreGeneratedClip(
            phrase=phrase,
            video_path=result.video_path,
            audio_path=audio_path,
            duration_seconds=result.duration_seconds,
            keywords=keywords or []
        )
        
        # Save metadata
        meta_path = clips_dir / f"{safe_name}.json"
        with open(meta_path, "w") as f:
            json.dump({
                "phrase": clip.phrase,
                "video_file": video_filename,
                "audio_file": str(audio_path),
                "duration": clip.duration_seconds,
                "keywords": clip.keywords
            }, f, indent=2)
        
        # Add to cache
        self.clips_cache[phrase.lower()] = clip
        
        return clip
    
    def find_pregenerated_clip(self, text: str) -> Optional[PreGeneratedClip]:
        """
        Find a pre-generated clip that matches the text.
        
        Args:
            text: Text to match
            
        Returns:
            Matching PreGeneratedClip or None
        """
        text_lower = text.lower()
        
        # Exact match
        if text_lower in self.clips_cache:
            return self.clips_cache[text_lower]
        
        # Keyword match
        for clip in self.clips_cache.values():
            for keyword in clip.keywords:
                if keyword.lower() in text_lower:
                    return clip
        
        return None


# Global instance
_video_generator: Optional[VideoGenerator] = None


def get_video_generator() -> VideoGenerator:
    """Get or create the global video generator instance."""
    global _video_generator
    if _video_generator is None:
        _video_generator = VideoGenerator()
    return _video_generator


async def generate_avatar_video(audio_path: Path, output_filename: Optional[str] = None) -> VideoResult:
    """
    Convenience function to generate avatar video.
    
    Args:
        audio_path: Path to audio file
        output_filename: Optional output filename
        
    Returns:
        VideoResult with video path and metadata
    """
    generator = get_video_generator()
    return await generator.generate_video(audio_path, output_filename)


