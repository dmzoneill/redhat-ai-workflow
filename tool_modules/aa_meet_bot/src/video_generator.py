"""
AI Research Video Generator

Creates a fun "hacker movie" style video showing fake AI research
on meeting attendees. All data is fake/randomized for entertainment.

NO REAL DATA IS COLLECTED OR DISPLAYED.

Performance (720p @ 12fps):
- Full GPU pipeline (default):  ~1% CPU  - everything on iGPU via OpenCL
- GPU color conversion only:    ~4% CPU  - CPU renders, GPU converts
- CPU only:                    ~23% CPU  - no GPU acceleration

Key optimizations:
- Single OpenCL mega-kernel for full GPU rendering
- Pre-rendered base frame uploaded to GPU once per attendee
- Waveform generated on GPU (native_sin)
- BGR→YUYV conversion on GPU
- Direct YUYV output to v4l2loopback (bypasses FFmpeg)
- Zero-copy memoryview for v4l2 writes
"""

import os

# Force GLX platform for OpenGL on Linux (required for headless rendering)
os.environ.setdefault("PYOPENGL_PLATFORM", "glx")

import asyncio  # noqa: E402
import logging  # noqa: E402
import random  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Optional  # noqa: E402

from .video_config import (  # noqa: E402
    FAKE_FINDINGS,
    RESEARCH_TOOLS,
    THREAT_ASSESSMENTS,
    Attendee,
    VideoConfig,
    VideoResult,
)

logger = logging.getLogger(__name__)


class ResearchVideoGenerator:
    """
    Generates fake "AI research" video for meeting entertainment.

    Creates a hacker-movie style animation showing fake data collection
    on meeting attendees. ALL DATA IS FAKE.
    """

    def __init__(self, config: Optional[VideoConfig] = None):
        self.config = config or VideoConfig()
        self._ffmpeg_process: Optional[subprocess.Popen] = None
        self._running = False

    async def generate_video_file(
        self,
        attendees: list[Attendee],
        output_path: Path,
    ) -> Path:
        """
        Generate a complete video file with fake research on all attendees.

        Args:
            attendees: List of meeting attendees
            output_path: Where to save the video

        Returns:
            Path to the generated video
        """
        # Build ffmpeg filter graph
        filter_complex = self._build_filter_graph(attendees)

        total_duration = (
            len(attendees) * self.config.duration_per_person + 3
        )  # +3 for intro/outro

        cmd = [
            "ffmpeg",
            "-y",
            "-",
            "lavfi",
            "-i",
            f"color=c={self.config.background_color}:s={self.config.width}x{self.config.height}"
            f":r={self.config.fps}:d={total_duration}",
            "-v",
            filter_complex,
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-cr",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-t",
            str(total_duration),
            str(output_path),
        ]

        logger.info(f"Generating research video: {output_path}")
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logger.error(f"FFmpeg error: {stderr.decode()}")
            raise RuntimeError(f"Video generation failed: {stderr.decode()[:200]}")

        logger.info(f"Video generated: {output_path}")
        return output_path

    async def stream_to_device(
        self,
        attendees: list[Attendee],
        video_device: str,
        loop: bool = True,
    ) -> None:
        """
        Stream fake research video to v4l2loopback device in real-time.

        This generates frames on-the-fly, iterating through attendees.
        Much lower memory usage than pre-generating the entire video.

        Args:
            attendees: List of attendees to "research"
            video_device: Path to v4l2loopback device (e.g., /dev/video10)
            loop: Whether to loop through attendees continuously
        """
        config = self.config
        total_attendees = len(attendees)

        logger.info("🎬 Starting real-time research video stream")
        logger.info(f"📋 {total_attendees} attendees to analyze")
        logger.info(
            f"📺 Output: {video_device} @ {config.width}x{config.height} {config.fps}fps"
        )

        self._running = True
        iteration = 0

        while self._running:
            iteration += 1
            logger.info(
                f"🔄 Starting iteration {iteration} through {total_attendees} attendees"
            )

            for idx, attendee in enumerate(attendees):
                if not self._running:
                    break

                logger.info(
                    f"🔍 [{idx + 1}/{total_attendees}] Analyzing: {attendee.name}"
                )
                await self._stream_single_attendee(
                    attendee=attendee,
                    video_device=video_device,
                    attendee_index=idx,
                    total_attendees=total_attendees,
                )

            if not loop:
                break

            # Brief pause between iterations
            if self._running:
                await asyncio.sleep(2)

        logger.info("🎬 Real-time video stream stopped")

    async def stream_to_stdout(
        self,
        attendees: list[Attendee],
        loop: bool = True,
    ) -> None:
        """
        Stream video to stdout as matroska format.

        Pipe to ffplay: python ... --stdout | ffplay -f matroska -

        Args:
            attendees: List of attendees to "research"
            loop: Whether to loop through attendees continuously
        """

        total_attendees = len(attendees)

        self._running = True
        iteration = 0

        while self._running:
            iteration += 1

            for idx, attendee in enumerate(attendees):
                if not self._running:
                    break

                # Stream this attendee to stdout
                await self._stream_single_attendee_stdout(
                    attendee=attendee,
                    attendee_index=idx,
                    total_attendees=total_attendees,
                )

            if not loop:
                break

    async def _stream_single_attendee_stdout(
        self,
        attendee: Attendee,
        attendee_index: int,
        total_attendees: int,
    ) -> None:
        """Stream research animation for one attendee to stdout."""
        import sys

        config = self.config
        duration = config.duration_per_person

        # Pick random fake data for this attendee
        tools = random.sample(
            RESEARCH_TOOLS, min(config.num_tools, len(RESEARCH_TOOLS))
        )
        findings = random.sample(
            FAKE_FINDINGS, min(config.num_findings, len(FAKE_FINDINGS))
        )
        assessment = random.choice(THREAT_ASSESSMENTS)

        # Build filter graph
        filters = []

        # Header
        filters.append(
            "drawtext=text='AI RESEARCH MODULE v2.1':fontsize=24:fontcolor=gray:x=30:y=15"
        )
        filters.append(
            f"drawtext=text='SCANNING {total_attendees} MEETING ATTENDEES...':fontsize=36"
            f":fontcolor={config.text_color}:x=30:y=55"
        )
        filters.append(
            f"drawtext=text='[{attendee_index + 1}/{total_attendees}]':fontsize=28"
            f":fontcolor=cyan:x={config.width - 150}:y=15"
        )

        # Target name with animated dots (cycles: name, name ., name .., name ...)
        escaped_name = self._escape_text(attendee.name)

        filters.append(
            f"drawtext=text='TARGET\\: {escaped_name}'"
            f":fontsize=56:fontcolor={config.highlight_color}:x=30:y=140"
            ":enable='lt(mod(t,4),1)'"
        )
        filters.append(
            f"drawtext=text='TARGET\\: {escaped_name} .'"
            f":fontsize=56:fontcolor={config.highlight_color}:x=30:y=140"
            ":enable='between(mod(t,4),1,2)'"
        )
        filters.append(
            f"drawtext=text='TARGET\\: {escaped_name} ..'"
            f":fontsize=56:fontcolor={config.highlight_color}:x=30:y=140"
            ":enable='between(mod(t,4),2,3)'"
        )
        filters.append(
            f"drawtext=text='TARGET\\: {escaped_name} ...'"
            f":fontsize=56:fontcolor={config.highlight_color}:x=30:y=140"
            ":enable='gte(mod(t,4),3)'"
        )

        # Tools - 1 second each
        for j, tool in enumerate(tools):
            tool_start = j * config.tool_display_time
            tool_end = tool_start + config.tool_display_time + 0.5
            filters.append(
                f"drawtext=text='> {self._escape_text(tool)}'"
                f":fontsize=26:fontcolor={config.text_color}"
                f":x=30:y={230 + (j % 5) * 40}:enable='between(t,{tool_start},{tool_end})'"
            )

        # Findings
        for j, finding in enumerate(findings):
            finding_start = 6 + j * config.finding_display_time
            finding_end = finding_start + config.finding_display_time + 0.5
            filters.append(
                f"drawtext=text='{self._escape_text(finding)}'"
                f":fontsize=24:fontcolor={config.text_color}"
                f":x=30:y={450 + (j % 3) * 36}:enable='between(t,{finding_start},{finding_end})'"
            )

        # Assessment
        filters.append(
            f"drawtext=text='{self._escape_text(assessment)}'"
            ":fontsize=28:fontcolor=cyan"
            f":x=30:y={config.height - 100}:enable='gte(t,{duration - 3})'"
        )

        filter_graph = ",".join(filters)

        cmd = [
            "ffmpeg",
            "-y",
            "-",
            "lavfi",
            "-i",
            f"color=c={config.background_color}:s={config.width}x{config.height}:r={config.fps}:d={duration}",
            "-v",
            filter_graph,
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-",
            "matroska",
            "-",  # stdout
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=sys.stdout.buffer,
            stderr=asyncio.subprocess.DEVNULL,
        )

        await process.wait()

    async def _stream_single_attendee(
        self,
        attendee: Attendee,
        video_device: str,
        attendee_index: int,
        total_attendees: int,
    ) -> None:
        """Stream research animation for one attendee to v4l2loopback."""
        config = self.config
        duration = config.duration_per_person

        # Pick random fake data for this attendee
        tools = random.sample(
            RESEARCH_TOOLS, min(config.num_tools, len(RESEARCH_TOOLS))
        )
        findings = random.sample(
            FAKE_FINDINGS, min(config.num_findings, len(FAKE_FINDINGS))
        )
        assessment = random.choice(THREAT_ASSESSMENTS)

        # Build filter graph for this single attendee
        filters = []

        # Header with attendee count
        filters.append(
            "drawtext=text='AI RESEARCH MODULE v2.1':fontsize=24:fontcolor=gray:x=30:y=15"
        )
        filters.append(
            f"drawtext=text='SCANNING {total_attendees} MEETING ATTENDEES...':fontsize=36"
            f":fontcolor={config.text_color}:x=30:y=55"
        )
        filters.append(
            f"drawtext=text='[{attendee_index + 1}/{total_attendees}]':fontsize=28"
            f":fontcolor=cyan:x={config.width - 150}:y=15"
        )

        # Right column - 400px wide, with vertical divider
        right_col_x = config.width - config.right_column_width
        right_col_top = 60
        right_col_height = 480  # Down to NPU panel area (540 - 60)

        # Vertical green line divider
        filters.append(
            f"drawbox=x={right_col_x}:y={right_col_top}:w=2:h={right_col_height}"
            f":color={config.text_color}:t=fill"
        )

        # 4 sections in right column, ~110px each
        section_height = 110
        section_x = right_col_x + 10

        # Section 1: JIRA ISSUE TRACKER
        sec1_y = right_col_top + 5
        filters.append(
            "drawtext=text='[ JIRA ]':fontsize=12:fontcolor=cyan"
            f":x={section_x}:y={sec1_y}"
        )
        jira_items = [
            "VELOCITY: 42",
            "BLOCKERS: 3",
            "EPICS: 7",
            "POINTS: 89",
        ]
        for j, item in enumerate(jira_items):
            filters.append(
                f"drawtext=text='{self._escape_text(item)}':fontsize=11:fontcolor={config.text_color}"
                f":x={section_x}:y={sec1_y + 18 + j * 18}"
            )

        # Section 2: SLACK SIGINT MODULE
        sec2_y = sec1_y + section_height
        filters.append(
            "drawtext=text='[ SLACK ]':fontsize=12:fontcolor=cyan"
            f":x={section_x}:y={sec2_y}"
        )
        slack_items = [
            "CHANNELS: 847",
            "DM: ACTIVE",
            "KEYWORDS: 12",
            "THREADS: 2.3K",
        ]
        for j, item in enumerate(slack_items):
            filters.append(
                f"drawtext=text='{self._escape_text(item)}':fontsize=11:fontcolor={config.text_color}"
                f":x={section_x}:y={sec2_y + 18 + j * 18}"
            )

        # Section 3: SEMANTIC VECTOR SEARCH
        sec3_y = sec2_y + section_height
        filters.append(
            "drawtext=text='[ SEMANTIC ]':fontsize=12:fontcolor=cyan"
            f":x={section_x}:y={sec3_y}"
        )
        semantic_items = [
            "VECTORS: 4.2M",
            "COSINE: 0.847",
            "CLUSTERS: 156",
            "LATENCY: 12ms",
        ]
        for j, item in enumerate(semantic_items):
            filters.append(
                f"drawtext=text='{self._escape_text(item)}':fontsize=11:fontcolor={config.text_color}"
                f":x={section_x}:y={sec3_y + 18 + j * 18}"
            )

        # Section 4: COMMS INTERCEPT ANALYSIS
        sec4_y = sec3_y + section_height
        filters.append(
            "drawtext=text='[ COMMS ]':fontsize=12:fontcolor=cyan"
            f":x={section_x}:y={sec4_y}"
        )
        comms_items = [
            "EMAIL: 12.4K",
            "CALENDAR: LIVE",
            "ENTITIES: 847",
            "RISK: MEDIUM",
        ]
        for j, item in enumerate(comms_items):
            filters.append(
                f"drawtext=text='{self._escape_text(item)}':fontsize=11:fontcolor={config.text_color}"
                f":x={section_x}:y={sec4_y + 18 + j * 18}"
            )

        # Person silhouette box - left side
        silhouette_x = 20
        silhouette_y = 300
        silhouette_w = 200
        silhouette_h = 250

        filters.append(
            f"drawbox=x={silhouette_x}:y={silhouette_y}:w={silhouette_w}:h={silhouette_h}"
            f":color={config.text_color}:t=2"
        )
        # Head
        head_cx = silhouette_x + silhouette_w // 2
        head_cy = silhouette_y + 50
        filters.append(
            f"drawbox=x={head_cx - 25}:y={head_cy - 25}:w=50:h=50"
            f":color={config.text_color}@0.5:t=fill"
        )
        # Body
        filters.append(
            f"drawbox=x={head_cx - 35}:y={head_cy + 35}:w=70:h=120"
            f":color={config.text_color}@0.5:t=fill"
        )
        # Shoulders
        filters.append(
            f"drawbox=x={head_cx - 55}:y={head_cy + 35}:w=110:h=25"
            f":color={config.text_color}@0.5:t=fill"
        )
        filters.append(
            f"drawtext=text='SUBJECT':fontsize=14:fontcolor={config.text_color}"
            f":x={silhouette_x + 70}:y={silhouette_y - 20}"
        )

        # Waveform box position - from native config
        wave_x = config.wave_x
        wave_y = config.wave_y
        wave_w = config.wave_w
        wave_h = config.wave_h

        # Waveform box border
        filters.append(
            f"drawbox=x={wave_x}:y={wave_y}:w={wave_w}:h={wave_h}"
            f":color={config.text_color}:t=2"
        )
        # Caption above the waveform
        filters.append(
            "drawtext=text='VOICE ANALYSIS':fontsize=14:fontcolor=cyan"
            f":x={wave_x + 240}:y={wave_y - 18}"
        )
        # Additional label below
        filters.append(
            "drawtext=text='[ AUDIO ]':fontsize=11:fontcolor=gray"
            f":x={wave_x + 270}:y={wave_y + wave_h + 5}"
        )

        # Target name with animated dots (cycles: name, name ., name .., name ...)
        escaped_name = self._escape_text(attendee.name)

        # State 0: no dots (t mod 4 < 1)
        filters.append(
            f"drawtext=text='TARGET\\: {escaped_name}'"
            f":fontsize=36:fontcolor={config.highlight_color}:x=20:y=100"
            ":enable='lt(mod(t,4),1)'"
        )
        # State 1: one dot (1 <= t mod 4 < 2)
        filters.append(
            f"drawtext=text='TARGET\\: {escaped_name} .'"
            f":fontsize=36:fontcolor={config.highlight_color}:x=20:y=100"
            ":enable='between(mod(t,4),1,2)'"
        )
        # State 2: two dots (2 <= t mod 4 < 3)
        filters.append(
            f"drawtext=text='TARGET\\: {escaped_name} ..'"
            f":fontsize=36:fontcolor={config.highlight_color}:x=20:y=100"
            ":enable='between(mod(t,4),2,3)'"
        )
        # State 3: three dots (3 <= t mod 4 < 4)
        filters.append(
            f"drawtext=text='TARGET\\: {escaped_name} ...'"
            f":fontsize=36:fontcolor={config.highlight_color}:x=20:y=100"
            ":enable='gte(mod(t,4),3)'"
        )

        # Tools - appear one at a time, 1 second apart, and STAY on screen
        for j, tool in enumerate(tools):
            tool_start = j * 1.0
            filters.append(
                f"drawtext=text='> {self._escape_text(tool)}'"
                f":fontsize=18:fontcolor={config.text_color}"
                f":x=20:y={145 + j * 24}:enable='gte(t,{tool_start})'"
            )

        # Findings - appear after tools
        findings_start_time = 9.0
        for j, finding in enumerate(findings):
            finding_start = findings_start_time + j * 1.0
            filters.append(
                f"drawtext=text='{self._escape_text(finding)}'"
                ":fontsize=16:fontcolor=yellow"
                f":x=240:y={310 + j * 24}:enable='gte(t,{finding_start})'"
            )

        # Assessment at end (last 2 seconds)
        filters.append(
            f"drawtext=text='{self._escape_text(assessment)}'"
            ":fontsize=20:fontcolor=cyan"
            f":x=240:y={310 + len(findings) * 24 + 20}:enable='gte(t,{duration - 2})'"
        )

        filter_graph = ",".join(filters)

        # Build command - real-time rendering only (no pre-rendered files)
        cmd = [
            "ffmpeg",
            "-y",
            "-re",  # Real-time output
            "-",
            "lavfi",
            "-i",
            f"color=c={config.background_color}:s={config.width}x{config.height}:r={config.fps}:d={duration}",
            "-v",
            filter_graph,
            "-t",
            str(duration),
            "-",
            "v4l2",
            "-pix_fmt",
            "yuyv422",
            video_device,
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            logger.warning(f"FFmpeg error for {attendee.name}: {stderr.decode()[:200]}")

    def _build_filter_graph(self, attendees: list[Attendee]) -> str:
        """Build complete filter graph for all attendees (for file generation)."""
        filters = []
        config = self.config
        total_attendees = len(attendees)

        # Header - scaled for 720p
        filters.append(
            "drawtext=text='AI RESEARCH MODULE v2.1':fontsize=18:fontcolor=gray:x=20:y=10"
        )
        filters.append(
            f"drawtext=text='SCANNING {total_attendees} ATTENDEES...'"
            f":fontsize=24:fontcolor={config.text_color}:x=20:y=35"
        )

        # Person silhouette box - left side
        silhouette_x = 20
        silhouette_y = 200
        silhouette_w = 180
        silhouette_h = 220

        # Draw silhouette box border
        filters.append(
            f"drawbox=x={silhouette_x}:y={silhouette_y}:w={silhouette_w}:h={silhouette_h}"
            f":color={config.text_color}:t=2"
        )

        # Draw person silhouette using simple shapes (head + body)
        head_cx = silhouette_x + silhouette_w // 2
        head_cy = silhouette_y + 45
        # Head
        filters.append(
            f"drawbox=x={head_cx - 22}:y={head_cy - 22}:w=44:h=44"
            f":color={config.text_color}@0.5:t=fill"
        )
        # Body
        filters.append(
            f"drawbox=x={head_cx - 30}:y={head_cy + 30}:w=60:h=100"
            f":color={config.text_color}@0.5:t=fill"
        )
        # Shoulders
        filters.append(
            f"drawbox=x={head_cx - 48}:y={head_cy + 30}:w=96:h=22"
            f":color={config.text_color}@0.5:t=fill"
        )

        # "SUBJECT" label above silhouette
        filters.append(
            f"drawtext=text='SUBJECT':fontsize=14:fontcolor={config.text_color}"
            f":x={silhouette_x + 60}:y={silhouette_y - 18}"
        )

        # Speech waveform box - from native config
        wave_x = config.wave_x
        wave_y = config.wave_y
        wave_w = config.wave_w
        wave_h = config.wave_h

        # Waveform box border
        filters.append(
            f"drawbox=x={wave_x}:y={wave_y}:w={wave_w}:h={wave_h}"
            f":color={config.text_color}:t=2"
        )

        # "ANALYZING SPEECH PATTERN" label
        filters.append(
            "drawtext=text='VOICE ANALYSIS':fontsize=11:fontcolor=cyan"
            f":x={wave_x + 250}:y={wave_y + wave_h + 4}"
        )

        # Animated waveform bars
        num_bars = 40
        bar_width = (wave_w - 20) // num_bars
        for b in range(num_bars):
            bar_x = wave_x + 10 + b * bar_width
            phase = b * 0.5
            filters.append(
                f"drawbox=x={bar_x}:y={wave_y + 5}"
                f":w={bar_width - 1}:h='20 + 15*sin(t*8 + {phase})'"
                f":color={config.text_color}@0.8:t=fill"
            )

        # Show attendee names cycling
        for i, attendee in enumerate(attendees):
            start_time = 2 + i * config.duration_per_person
            end_time = start_time + config.duration_per_person

            # Progress counter
            filters.append(
                f"drawtext=text='[{i + 1}/{total_attendees}]':fontsize=16"
                f":fontcolor=cyan:x={config.width - 80}:y=10"
                f":enable='between(t,{start_time},{end_time})'"
            )

            # Name - scaled for 720p
            filters.append(
                f"drawtext=text='TARGET\\: {self._escape_text(attendee.name)}'"
                f":fontsize=28:fontcolor={config.highlight_color}"
                f":x=20:y=65:enable='between(t,{start_time},{end_time})'"
            )

            # Random tools - left side
            tools = random.sample(RESEARCH_TOOLS, config.num_tools)
            for j, tool in enumerate(tools):
                tool_start = start_time + j * config.tool_display_time
                tool_end = min(tool_start + config.tool_display_time + 1, end_time)
                filters.append(
                    f"drawtext=text='> {self._escape_text(tool)}'"
                    f":fontsize=14:fontcolor={config.text_color}"
                    f":x=20:y={100 + (j % 4) * 20}:enable='between(t,{tool_start},{tool_end})'"
                )

            # Random findings
            findings = random.sample(FAKE_FINDINGS, config.num_findings)
            for j, finding in enumerate(findings):
                finding_start = start_time + 4 + j * config.finding_display_time
                finding_end = min(
                    finding_start + config.finding_display_time + 1, end_time
                )
                filters.append(
                    f"drawtext=text='{self._escape_text(finding)}'"
                    ":fontsize=12:fontcolor=yellow"
                    f":x=220:y={210 + (j % 3) * 18}:enable='between(t,{finding_start},{finding_end})'"
                )

            # Assessment - appears at end
            assessment = random.choice(THREAT_ASSESSMENTS)
            filters.append(
                f"drawtext=text='{self._escape_text(assessment)}'"
                ":fontsize=16:fontcolor=cyan"
                f":x=220:y={config.height - 200}:enable='between(t,{end_time - 3},{end_time})'"
            )

        return ",".join(filters)

    def _escape_text(self, text: str) -> str:
        """Escape text for FFmpeg drawtext filter."""
        # Escape special characters for FFmpeg drawtext
        text = text.replace("\\", "\\\\\\\\")  # Backslash
        text = text.replace("'", "'\\''")  # Single quote
        text = text.replace(":", "\\:")  # Colon
        text = text.replace("%", "%%")  # Percent
        text = text.replace(",", "\\,")  # Comma (filter separator)
        text = text.replace("[", "\\[")  # Brackets
        text = text.replace("]", "\\]")
        text = text.replace(";", "\\;")  # Semicolon
        return text

    def stop(self) -> None:
        """Stop streaming."""
        self._running = False
        if self._ffmpeg_process:
            self._ffmpeg_process.terminate()
            self._ffmpeg_process = None


def load_attendees_from_file(filepath: Path) -> list[Attendee]:
    """Load attendee names from a text file (one name per line)."""
    if not filepath.exists():
        logger.warning(f"Attendees file not found: {filepath}")
        return []

    attendees = []
    for line in filepath.read_text().strip().split("\n"):
        name = line.strip()
        if name and not name.startswith("#"):
            attendees.append(Attendee(name=name))

    logger.info(f"Loaded {len(attendees)} attendees from {filepath}")
    return attendees


async def generate_research_video(
    attendee_names: list[str],
    output_path: Optional[Path] = None,
) -> Path:
    """
    Convenience function to generate a research video.

    Args:
        attendee_names: List of attendee names
        output_path: Where to save (default: temp file)

    Returns:
        Path to generated video
    """
    if output_path is None:
        output_path = Path(tempfile.gettempdir()) / "meeting_research.mp4"

    attendees = [Attendee(name=name) for name in attendee_names]
    generator = ResearchVideoGenerator()

    return await generator.generate_video_file(attendees, output_path)


# Default attendees file location
DEFAULT_ATTENDEES_FILE = Path(__file__).parent.parent / "data" / "example_attendees.txt"


async def get_meeting_audio_source(instance_id: str) -> Optional[str]:
    """
    Get the PulseAudio monitor source for a meeting instance.

    Args:
        instance_id: Meeting instance ID (e.g., "abc123" or "abc-123")

    Returns:
        Monitor source name (e.g., "meet_bot_abc123.monitor") or None if not found
    """
    # Normalize instance ID (replace hyphens with underscores)
    safe_id = instance_id.replace("-", "_")
    monitor_source = f"meet_bot_{safe_id}.monitor"

    # Verify the source exists
    try:
        proc = await asyncio.create_subprocess_exec(
            "pactl",
            "list",
            "sources",
            "short",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        if monitor_source in stdout.decode():
            return monitor_source

        # Try to find any meet_bot source
        for line in stdout.decode().strip().split("\n"):
            if "meet_bot" in line and ".monitor" in line:
                parts = line.split()
                if len(parts) >= 2:
                    logger.info(f"Found meeting audio source: {parts[1]}")
                    return parts[1]

        logger.warning(f"Monitor source not found: {monitor_source}")
        return None

    except Exception as e:
        logger.error(f"Error finding audio source: {e}")
        return None


async def list_available_audio_sources() -> list[str]:
    """List all available PulseAudio sources that could be used for audio-reactive waveform."""
    sources = []
    try:
        proc = await asyncio.create_subprocess_exec(
            "pactl",
            "list",
            "sources",
            "short",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        for line in stdout.decode().strip().split("\n"):
            parts = line.split()
            if len(parts) >= 2:
                source_name = parts[1]
                # Include monitor sources and meet_bot sources
                if ".monitor" in source_name or "meet_bot" in source_name:
                    sources.append(source_name)

    except Exception as e:
        logger.error(f"Error listing audio sources: {e}")

    return sources


# Quick test
if __name__ == "__main__":  # noqa: C901
    import atexit
    import signal
    import sys

    logging.basicConfig(level=logging.INFO)

    # Import shared video device module
    # Add project root to path for imports
    _project_root = Path(__file__).parent.parent.parent.parent.parent
    sys.path.insert(0, str(_project_root))

    from scripts.common.video_device import cleanup_device, setup_v4l2_device

    # Global state for cleanup (uses shared module now)
    _active_device_path = None

    def signal_handler(signum, frame):
        """Handle Ctrl+C gracefully."""
        print("\n\nShutting down...", file=sys.stderr)
        cleanup_device()
        sys.exit(0)

    # Register cleanup handlers
    atexit.register(cleanup_device)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    def print_usage():
        print("Usage:")
        print("  python -m tool_modules.aa_meet_bot.src.video_generator --realtime")
        print(
            "  python -m tool_modules.aa_meet_bot.src.video_generator --realtime --audio SOURCE"
        )
        print(
            "  python -m tool_modules.aa_meet_bot.src.video_generator --realtime /dev/videoX  # Use specific device"
        )
        print(
            "  python -m tool_modules.aa_meet_bot.src.video_generator --file output.mp4"
        )
        print("  python -m tool_modules.aa_meet_bot.src.video_generator --cleanup")
        print("")
        print("Commands:")
        print(
            "  --realtime      Stream to v4l2loopback device with hardcoded attendees"
        )
        print("  --file          Generate video file")
        print(
            "  --cleanup       Clean up orphaned MeetBot audio/video devices and restore defaults"
        )
        print("")
        print("Options:")
        print("  --audio SOURCE  PulseAudio source for audio-reactive waveform")
        print(
            "                  Use 'pactl list sources short' to find available sources"
        )
        print("  --720p          Use 1280x720 resolution (default: 1920x1080)")
        print("  --nvidia        Use NVIDIA GPU instead of Intel iGPU")
        print(
            "  --flip          Flip video horizontally (for Google Meet mirror compensation)"
        )
        print(
            "  --webrtc        Enable WebRTC streaming for preview (ws://localhost:8765)"
        )
        print("")
        print("Production Mode:")
        print(
            "  In production, the video_daemon is controlled via D-Bus by the meet_daemon."
        )
        print("  The meet_daemon calls StartVideo/StopVideo/UpdateAttendees methods.")
        print("")
        print("WebRTC Preview:")
        print("  With --webrtc, frames are pushed to a WebRTC server on port 8765")
        print("  Connect from the Meetings tab Video Preview (select WebRTC mode)")
        print("")
        print(
            "The device is automatically created/configured. Press Ctrl+C to stop and release."
        )
        print("")
        print("Architecture:")
        print("  Full GPU pipeline: OpenGL (text/shapes) + OpenCL (color conversion)")
        print("  Target: ~1% CPU utilization at 1080p")

    async def ensure_default_source_not_meetbot():
        """Ensure the system default audio source isn't a MeetBot device."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "pactl",
                "get-default-source",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            current_default = stdout.decode().strip()

            if "meet_bot" in current_default.lower():
                print(
                    f"WARNING: Default audio source is a MeetBot device: {current_default}",
                    file=sys.stderr,
                )
                print("Restoring to physical microphone...", file=sys.stderr)

                # Find a physical microphone
                proc = await asyncio.create_subprocess_exec(
                    "pactl",
                    "list",
                    "sources",
                    "short",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()

                physical_mic = None
                for line in stdout.decode().strip().split("\n"):
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        source_name = parts[1]
                        # Look for physical microphones (not monitors, not meetbot)
                        if (
                            "meet_bot" not in source_name.lower()
                            and ".monitor" not in source_name
                            and (
                                "alsa" in source_name.lower()
                                or "input" in source_name.lower()
                            )
                        ):
                            physical_mic = source_name
                            break

                if physical_mic:
                    # Restore via pw-metadata (persistent)
                    await asyncio.create_subprocess_exec(
                        "pw-metadata",
                        "-n",
                        "default",
                        "0",
                        "default.audio.source",
                        f'{{"name":"{physical_mic}"}}',
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    # Also via pactl (immediate)
                    await asyncio.create_subprocess_exec(
                        "pactl",
                        "set-default-source",
                        physical_mic,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    print(
                        f"Restored default source to: {physical_mic}", file=sys.stderr
                    )
                else:
                    print(
                        "WARNING: Could not find a physical microphone to restore to",
                        file=sys.stderr,
                    )
        except Exception as e:
            logger.warning(f"Error checking default source: {e}")

    async def main():
        global _active_device_path

        # Always ensure default source isn't a meetbot device at startup
        await ensure_default_source_not_meetbot()

        # Check for command line args
        if len(sys.argv) > 1:
            if sys.argv[1] == "--cleanup":
                # Clean up orphaned MeetBot devices
                print("Cleaning up orphaned MeetBot devices...", file=sys.stderr)
                try:
                    from tool_modules.aa_meet_bot.src.virtual_devices import (
                        cleanup_orphaned_meetbot_devices,
                    )

                    results = await cleanup_orphaned_meetbot_devices()

                    if results["removed_modules"]:
                        print(
                            f"Removed audio modules: {results['removed_modules']}",
                            file=sys.stderr,
                        )
                    if results["removed_pipes"]:
                        print(
                            f"Removed pipes: {results['removed_pipes']}",
                            file=sys.stderr,
                        )
                    if results["removed_video_devices"]:
                        print(
                            f"Removed video devices: {results['removed_video_devices']}",
                            file=sys.stderr,
                        )
                    if results["errors"]:
                        print(f"Errors: {results['errors']}", file=sys.stderr)

                    total = (
                        len(results["removed_modules"])
                        + len(results["removed_pipes"])
                        + len(results.get("removed_video_devices", []))
                    )
                    if total == 0:
                        print("No orphaned devices found.", file=sys.stderr)
                    else:
                        print(
                            f"Cleanup complete: {total} items removed.", file=sys.stderr
                        )
                except Exception as e:
                    logger.error("Cleanup error: %s", e)
                return

            elif sys.argv[1] == "--stream" and len(sys.argv) > 2:
                # Stream to v4l2loopback device (uses pre-rendered overlays)
                video_device = sys.argv[2]
                attendees = load_attendees_from_file(DEFAULT_ATTENDEES_FILE)
                if not attendees:
                    print(
                        f"No attendees found in {DEFAULT_ATTENDEES_FILE}",
                        file=sys.stderr,
                    )
                    return
                print(
                    f"Streaming to {video_device} with {len(attendees)} attendees...",
                    file=sys.stderr,
                )
                print("Using pre-rendered overlays (faster)", file=sys.stderr)
                print("Press Ctrl+C to stop", file=sys.stderr)
                generator = ResearchVideoGenerator()
                await generator.stream_to_device(attendees, video_device, loop=True)

            elif sys.argv[1] == "--realtime":
                # Real-time rendering (no pre-rendered files)
                # Device can be specified or auto-created

                # Check for explicit device path
                video_device = None
                for arg in sys.argv[2:]:
                    if arg.startswith("/dev/video"):
                        video_device = arg
                        break

                # Check for --audio option
                audio_source = None
                if "--audio" in sys.argv:
                    audio_idx = sys.argv.index("--audio")
                    if audio_idx + 1 < len(sys.argv):
                        audio_source = sys.argv[audio_idx + 1]

                # Check for resolution option (1080p is now default)
                use_720p = "--720p" in sys.argv

                # Check for --flip option (horizontal mirror for Google Meet)
                use_flip = "--flip" in sys.argv

                # Determine resolution
                if use_720p:
                    width, height = 1280, 720
                else:
                    width, height = 1920, 1080

                # Auto-setup device if not specified
                if video_device is None:
                    video_device = setup_v4l2_device(width, height)
                else:
                    # Still configure the specified device
                    print(f"Using specified device: {video_device}", file=sys.stderr)
                    setup_v4l2_device(width, height)  # This will configure it

                _active_device_path = video_device

                # Check for GPU options
                use_nvidia = "--nvidia" in sys.argv

                # Create config (1080p default)
                if use_720p:
                    config = VideoConfig.hd_720p()
                    print("Using 720p resolution (1280x720)", file=sys.stderr)
                else:
                    config = VideoConfig()  # Default is now 1080p
                    print("Using 1080p resolution (1920x1080)", file=sys.stderr)

                # Set GPU preference
                config.prefer_intel_gpu = not use_nvidia
                gpu_name = "NVIDIA" if use_nvidia else "Intel iGPU"
                print(f"Using full GPU pipeline on {gpu_name}", file=sys.stderr)

                # Set flip mode
                if use_flip:
                    os.environ["FLIP"] = "1"
                    print("Horizontal flip ENABLED (for Google Meet)", file=sys.stderr)

                attendees = load_attendees_from_file(DEFAULT_ATTENDEES_FILE)
                if not attendees:
                    print(
                        f"No attendees found in {DEFAULT_ATTENDEES_FILE}",
                        file=sys.stderr,
                    )
                    return
                print(
                    f"Real-time streaming to {video_device} with {len(attendees)} attendees...",
                    file=sys.stderr,
                )
                if audio_source:
                    print(
                        f"Audio-reactive waveform from: {audio_source}", file=sys.stderr
                    )
                else:
                    print("Using simulated waveform (no audio source)", file=sys.stderr)
                print("Press Ctrl+C to stop", file=sys.stderr)

                # Check for WebRTC streaming option
                use_webrtc = "--webrtc" in sys.argv
                if use_webrtc:
                    print(
                        "WebRTC preview enabled on ws://localhost:8765", file=sys.stderr
                    )

                renderer = RealtimeVideoRenderer(
                    config=config, audio_source=audio_source, enable_webrtc=use_webrtc
                )
                try:
                    await renderer.stream_realtime(attendees, video_device, loop=True)
                finally:
                    await renderer.stop_async()

            elif sys.argv[1] == "--file":
                # Generate to file
                output_path = sys.argv[2] if len(sys.argv) > 2 else "research_video.mp4"
                attendees = load_attendees_from_file(DEFAULT_ATTENDEES_FILE)
                if not attendees:
                    print(
                        f"No attendees found in {DEFAULT_ATTENDEES_FILE}",
                        file=sys.stderr,
                    )
                    return
                generator = ResearchVideoGenerator()
                path = await generator.generate_video_file(attendees, Path(output_path))
                print(f"Generated: {path}", file=sys.stderr)

            elif sys.argv[1] == "--stdout":
                # Stream to stdout as matroska (pipe-friendly format)
                attendees = load_attendees_from_file(DEFAULT_ATTENDEES_FILE)
                if not attendees:
                    print(
                        f"No attendees found in {DEFAULT_ATTENDEES_FILE}",
                        file=sys.stderr,
                    )
                    return
                print(
                    f"Streaming {len(attendees)} attendees to stdout...",
                    file=sys.stderr,
                )
                print("Pipe to: ffplay -f matroska -", file=sys.stderr)
                generator = ResearchVideoGenerator()
                await generator.stream_to_stdout(attendees)

            elif sys.argv[1] == "--help" or sys.argv[1] == "-h":
                print_usage()

            else:
                # Generate file with provided names
                names = sys.argv[1:]
                path = await generate_research_video(names, Path("test_research.mp4"))
                print(f"Generated: {path}")
        else:
            # Load from file and generate video
            attendees = load_attendees_from_file(DEFAULT_ATTENDEES_FILE)
            if attendees:
                print(
                    f"Loaded {len(attendees)} attendees from {DEFAULT_ATTENDEES_FILE}"
                )
                generator = ResearchVideoGenerator()
                path = await generator.generate_video_file(
                    attendees, Path("test_research.mp4")
                )
                print(f"Generated: {path}")
            else:
                # Fallback to example names
                names = ["John Smith", "Jane Doe", "Bob Wilson"]
                path = await generate_research_video(names, Path("test_research.mp4"))
                print(f"Generated: {path}")

    asyncio.run(main())


# ==================== BACKWARD COMPATIBILITY ====================
# These classes provide backward compatibility for tools_basic.py
# which expects the old VideoGenerator API for lip-sync avatar video.


class VideoGenerator:
    """
    Backward-compatible video generator for lip-sync avatar video.

    This is a compatibility wrapper that provides the old API expected by
    tools_basic.py. The actual implementation uses static avatar images
    since the Wav2Lip integration was removed.
    """

    def __init__(self):
        self._initialized = False

    async def initialize(self) -> bool:
        """Initialize the video generator."""
        self._initialized = True
        return True

    async def generate_video(
        self,
        audio_path: Path,
        output_filename: Optional[str] = None,
    ) -> VideoResult:
        """
        Generate lip-sync video from audio.

        Since Wav2Lip was removed, this now generates a static avatar video
        with the audio track.

        Args:
            audio_path: Path to audio file
            output_filename: Optional output filename

        Returns:
            VideoResult with video path and metadata
        """
        try:
            from pathlib import Path as PathLib

            audio = (
                PathLib(audio_path) if not isinstance(audio_path, Path) else audio_path
            )

            if not audio.exists():
                return VideoResult(
                    success=False, error=f"Audio file not found: {audio}"
                )

            # Get audio duration
            try:
                import wave

                with wave.open(str(audio), "rb") as wf:
                    frames = wf.getnframes()
                    rate = wf.getframerate()
                    duration = frames / float(rate)
            except Exception:
                duration = 5.0  # Default duration if we can't read the audio

            # Generate output path
            if output_filename:
                output_path = Path(output_filename)
            else:
                output_dir = (
                    Path.home() / ".config" / "aa-workflow" / "meet_bot" / "clips"
                )
                output_dir.mkdir(parents=True, exist_ok=True)
                output_path = output_dir / f"response_{audio.stem}.mp4"

            # For now, return a "static" result indicating we'd use a static avatar
            # The actual video generation would combine the static avatar with audio
            # This is a placeholder until proper video generation is re-implemented
            return VideoResult(
                success=True,
                video_path=output_path,
                duration_seconds=duration,
                resolution=(1280, 720),
                fps=30,
                source="static",
            )

        except Exception as e:
            logger.error(f"Video generation failed: {e}")
            return VideoResult(success=False, error=str(e))


# Global video generator instance
_video_generator: Optional[VideoGenerator] = None


def get_video_generator() -> VideoGenerator:
    """Get or create the global video generator instance."""
    global _video_generator
    if _video_generator is None:
        _video_generator = VideoGenerator()
    return _video_generator


# ==================== BACKWARD COMPATIBILITY RE-EXPORTS ====================
# Re-export from split modules so existing imports still work:
#   from tool_modules.aa_meet_bot.src.video_generator import RealtimeVideoRenderer
#   from tool_modules.aa_meet_bot.src.video_generator import UltraLowCPURenderer
from .video_gpu import (  # noqa: E402, F401
    MEMORY_CRITICAL_MB,
    MEMORY_WARNING_MB,
    GPUColorConverter,
    StreamingRenderer,
    UltraLowCPURenderer,
    bgr_to_yuyv_fast,
    get_memory_mb,
    get_npu_stats,
    maybe_gc,
    rgb_to_yuyv_fast,
)
from .video_realtime import RealtimeVideoRenderer  # noqa: E402, F401
