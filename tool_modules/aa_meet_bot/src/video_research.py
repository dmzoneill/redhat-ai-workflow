"""FFmpeg research-video generation."""

import asyncio
import logging
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

from tool_modules.aa_meet_bot.src.video_config import Attendee, VideoConfig
from tool_modules.aa_meet_bot.src.video_theme import (
    FAKE_FINDINGS,
    RESEARCH_TOOLS,
    THREAT_ASSESSMENTS,
)

logger = logging.getLogger(__name__)

# Non-cryptographic jitter/variety; SystemRandom avoids the predictable Mersenne Twister flagged by scanners
_RNG = secrets.SystemRandom()


class ResearchVideoGenerator:
    """
    Generates fake "AI research" video for meeting entertainment.

    Creates a hacker-movie style animation showing fake data collection
    on meeting attendees. ALL DATA IS FAKE.
    """

    def _pick_fake_data(self) -> tuple[list, list, str]:
        """Pick this attendee's fake research tools, findings and threat assessment."""
        config = self.config
        tools = _RNG.sample(RESEARCH_TOOLS, min(config.num_tools, len(RESEARCH_TOOLS)))
        findings = _RNG.sample(FAKE_FINDINGS, min(config.num_findings, len(FAKE_FINDINGS)))
        return tools, findings, _RNG.choice(THREAT_ASSESSMENTS)

    def _header_filters(self, attendee_index: int, total_attendees: int) -> list[str]:
        """Drawtext filters for the module title, attendee count and position."""
        config = self.config
        return [
            "drawtext=text='AI RESEARCH MODULE v2.1':fontsize=24:fontcolor=gray:x=30:y=15",
            (
                f"drawtext=text='SCANNING {total_attendees} MEETING ATTENDEES...':fontsize=36"
                f":fontcolor={config.text_color}:x=30:y=55"
            ),
            (
                f"drawtext=text='[{attendee_index + 1}/{total_attendees}]':fontsize=28"
                f":fontcolor=cyan:x={config.width - 150}:y=15"
            ),
        ]

    def __init__(self, config: VideoConfig | None = None):
        self.config = config or VideoConfig()
        self._ffmpeg_process: subprocess.Popen | None = None
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

        total_duration = len(attendees) * self.config.duration_per_person + 3  # +3 for intro/outro

        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            (
                f"color=c={self.config.background_color}:s={self.config.width}x{self.config.height}"
                f":r={self.config.fps}:d={total_duration}"
            ),
            "-vf",
            filter_complex,
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-t",
            str(total_duration),
            str(output_path),
        ]

        logger.info("Generating research video: %s", output_path)
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        _stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logger.error("FFmpeg error: %s", stderr.decode())
            raise RuntimeError(f"Video generation failed: {stderr.decode()[:200]}")

        logger.info("Video generated: %s", output_path)
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
        logger.info("📋 %s attendees to analyze", total_attendees)
        logger.info(
            "📺 Output: %s @ %sx%s %sfps",
            video_device,
            config.width,
            config.height,
            config.fps,
        )

        self._running = True
        iteration = 0

        while self._running:
            iteration += 1
            logger.info(
                "🔄 Starting iteration %s through %s attendees",
                iteration,
                total_attendees,
            )

            for idx, attendee in enumerate(attendees):
                if not self._running:
                    break

                logger.info("🔍 [%s/%s] Analyzing: %s", idx + 1, total_attendees, attendee.name)
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

    # Live flow kept together after the duplicate copy was removed.
    # pylint: disable-next=too-many-locals
    async def _stream_single_attendee_stdout(
        self,
        attendee: Attendee,
        attendee_index: int,
        total_attendees: int,
    ) -> None:
        """Stream research animation for one attendee to stdout."""

        config = self.config
        duration = config.duration_per_person

        # Pick random fake data for this attendee
        tools, findings, assessment = self._pick_fake_data()

        # Build filter graph
        filters = []

        # Header
        filters.extend(self._header_filters(attendee_index, total_attendees))

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
            "-f",
            "lavfi",
            "-i",
            f"color=c={config.background_color}:s={config.width}x{config.height}:r={config.fps}:d={duration}",
            "-vf",
            filter_graph,
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-f",
            "matroska",
            "-",  # stdout
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=sys.stdout.buffer,
            stderr=asyncio.subprocess.DEVNULL,
        )

        await process.wait()

    # Live flow kept together after the duplicate copy was removed.
    # pylint: disable-next=too-many-locals,too-many-statements
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
        tools, findings, assessment = self._pick_fake_data()

        # Build filter graph for this single attendee
        filters = []

        # Header with attendee count
        filters.extend(self._header_filters(attendee_index, total_attendees))

        # Right column - 400px wide, with vertical divider
        right_col_x = config.width - config.right_column_width
        right_col_top = 60
        right_col_height = 480  # Down to NPU panel area (540 - 60)

        # Vertical green line divider
        filters.append(
            f"drawbox=x={right_col_x}:y={right_col_top}:w=2:h={right_col_height}:color={config.text_color}:t=fill"
        )

        # 4 sections in right column, ~110px each
        section_height = 110
        section_x = right_col_x + 10

        # Section 1: JIRA ISSUE TRACKER
        sec1_y = right_col_top + 5
        filters.append(f"drawtext=text='[ JIRA ]':fontsize=12:fontcolor=cyan:x={section_x}:y={sec1_y}")
        jira_items = [
            "VELOCITY: 42",
            "BLOCKERS: 3",
            "EPICS: 7",
            "POINTS: 89",
        ]
        for j, item in enumerate(jira_items):
            filters.append(
                f"drawtext=text='{self._escape_text(item)}':fontsize=11:"
                f"fontcolor={config.text_color}"
                f":x={section_x}:y={sec1_y + 18 + j * 18}"
            )

        # Section 2: SLACK SIGINT MODULE
        sec2_y = sec1_y + section_height
        filters.append(f"drawtext=text='[ SLACK ]':fontsize=12:fontcolor=cyan:x={section_x}:y={sec2_y}")
        slack_items = [
            "CHANNELS: 847",
            "DM: ACTIVE",
            "KEYWORDS: 12",
            "THREADS: 2.3K",
        ]
        for j, item in enumerate(slack_items):
            filters.append(
                f"drawtext=text='{self._escape_text(item)}':fontsize=11:"
                f"fontcolor={config.text_color}"
                f":x={section_x}:y={sec2_y + 18 + j * 18}"
            )

        # Section 3: SEMANTIC VECTOR SEARCH
        sec3_y = sec2_y + section_height
        filters.append(f"drawtext=text='[ SEMANTIC ]':fontsize=12:fontcolor=cyan:x={section_x}:y={sec3_y}")
        semantic_items = [
            "VECTORS: 4.2M",
            "COSINE: 0.847",
            "CLUSTERS: 156",
            "LATENCY: 12ms",
        ]
        for j, item in enumerate(semantic_items):
            filters.append(
                f"drawtext=text='{self._escape_text(item)}':fontsize=11:"
                f"fontcolor={config.text_color}"
                f":x={section_x}:y={sec3_y + 18 + j * 18}"
            )

        # Section 4: COMMS INTERCEPT ANALYSIS
        sec4_y = sec3_y + section_height
        filters.append(f"drawtext=text='[ COMMS ]':fontsize=12:fontcolor=cyan:x={section_x}:y={sec4_y}")
        comms_items = [
            "EMAIL: 12.4K",
            "CALENDAR: LIVE",
            "ENTITIES: 847",
            "RISK: MEDIUM",
        ]
        for j, item in enumerate(comms_items):
            filters.append(
                f"drawtext=text='{self._escape_text(item)}':fontsize=11:"
                f"fontcolor={config.text_color}"
                f":x={section_x}:y={sec4_y + 18 + j * 18}"
            )

        # Person silhouette box - left side
        silhouette_x = 20
        silhouette_y = 300
        silhouette_w = 200
        silhouette_h = 250

        filters.append(
            f"drawbox=x={silhouette_x}:y={silhouette_y}:w={silhouette_w}:h={silhouette_h}:color={config.text_color}:t=2"
        )
        # Head
        head_cx = silhouette_x + silhouette_w // 2
        head_cy = silhouette_y + 50
        filters.append(f"drawbox=x={head_cx - 25}:y={head_cy - 25}:w=50:h=50:color={config.text_color}@0.5:t=fill")
        # Body
        filters.append(f"drawbox=x={head_cx - 35}:y={head_cy + 35}:w=70:h=120:color={config.text_color}@0.5:t=fill")
        # Shoulders
        filters.append(f"drawbox=x={head_cx - 55}:y={head_cy + 35}:w=110:h=25:color={config.text_color}@0.5:t=fill")
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
        filters.append(f"drawbox=x={wave_x}:y={wave_y}:w={wave_w}:h={wave_h}:color={config.text_color}:t=2")
        # Caption above the waveform
        filters.append(f"drawtext=text='VOICE ANALYSIS':fontsize=14:fontcolor=cyan:x={wave_x + 240}:y={wave_y - 18}")
        # Additional label below
        filters.append(f"drawtext=text='[ AUDIO ]':fontsize=11:fontcolor=gray:x={wave_x + 270}:y={wave_y + wave_h + 5}")

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
            "-f",
            "lavfi",
            "-i",
            f"color=c={config.background_color}:s={config.width}x{config.height}:r={config.fps}:d={duration}",
            "-vf",
            filter_graph,
            "-t",
            str(duration),
            "-f",
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

        _stdout, stderr = await process.communicate()
        if process.returncode != 0:
            logger.warning("FFmpeg error for %s: %s", attendee.name, stderr.decode()[:200])

    # Live flow kept together after the duplicate copy was removed.
    # pylint: disable-next=too-many-locals
    def _build_filter_graph(self, attendees: list[Attendee]) -> str:
        """Build complete filter graph for all attendees (for file generation)."""
        filters = []
        config = self.config
        total_attendees = len(attendees)

        # Header - scaled for 720p
        filters.append("drawtext=text='AI RESEARCH MODULE v2.1':fontsize=18:fontcolor=gray:x=20:y=10")
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
            f"drawbox=x={silhouette_x}:y={silhouette_y}:w={silhouette_w}:h={silhouette_h}:color={config.text_color}:t=2"
        )

        # Draw person silhouette using simple shapes (head + body)
        head_cx = silhouette_x + silhouette_w // 2
        head_cy = silhouette_y + 45
        # Head
        filters.append(f"drawbox=x={head_cx - 22}:y={head_cy - 22}:w=44:h=44:color={config.text_color}@0.5:t=fill")
        # Body
        filters.append(f"drawbox=x={head_cx - 30}:y={head_cy + 30}:w=60:h=100:color={config.text_color}@0.5:t=fill")
        # Shoulders
        filters.append(f"drawbox=x={head_cx - 48}:y={head_cy + 30}:w=96:h=22:color={config.text_color}@0.5:t=fill")

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
        filters.append(f"drawbox=x={wave_x}:y={wave_y}:w={wave_w}:h={wave_h}:color={config.text_color}:t=2")

        # "ANALYZING SPEECH PATTERN" label
        filters.append(
            f"drawtext=text='VOICE ANALYSIS':fontsize=11:fontcolor=cyan:x={wave_x + 250}:y={wave_y + wave_h + 4}"
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
            tools = _RNG.sample(RESEARCH_TOOLS, config.num_tools)
            for j, tool in enumerate(tools):
                tool_start = start_time + j * config.tool_display_time
                tool_end = min(tool_start + config.tool_display_time + 1, end_time)
                filters.append(
                    f"drawtext=text='> {self._escape_text(tool)}'"
                    f":fontsize=14:fontcolor={config.text_color}"
                    f":x=20:y={100 + (j % 4) * 20}:enable='between(t,{tool_start},{tool_end})'"
                )

            # Random findings
            findings = _RNG.sample(FAKE_FINDINGS, config.num_findings)
            for j, finding in enumerate(findings):
                finding_start = start_time + 4 + j * config.finding_display_time
                finding_end = min(finding_start + config.finding_display_time + 1, end_time)
                filters.append(
                    f"drawtext=text='{self._escape_text(finding)}'"
                    ":fontsize=12:fontcolor=yellow"
                    f":x=220:y={210 + (j % 3) * 18}:"
                    f"enable='between(t,{finding_start},{finding_end})'"
                )

            # Assessment - appears at end
            assessment = _RNG.choice(THREAT_ASSESSMENTS)
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
        logger.warning("Attendees file not found: %s", filepath)
        return []

    attendees = []
    for line in filepath.read_text().strip().split("\n"):
        name = line.strip()
        if name and not name.startswith("#"):
            attendees.append(Attendee(name=name))

    logger.info("Loaded %s attendees from %s", len(attendees), filepath)
    return attendees


async def generate_research_video(
    attendee_names: list[str],
    output_path: Path | None = None,
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
