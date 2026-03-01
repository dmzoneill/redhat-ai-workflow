"""
Video configuration and data classes.

Extracted from video_generator.py. Contains:
- Attendee - meeting attendee with optional Slack enrichment
- VideoConfig - layout and timing configuration
- VideoResult - result of video generation (backward compatibility)
- Shared constants: RESEARCH_TOOLS, FAKE_CATEGORIES, FAKE_FINDINGS, THREAT_ASSESSMENTS
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class Attendee:
    """Meeting attendee with optional enriched data from Slack."""

    name: str
    mugshot_path: Optional[Path] = None  # Optional photo (legacy)
    title: str = "Engineer"
    # Slack enrichment data
    slack_id: Optional[str] = None
    slack_display_name: Optional[str] = None
    photo_path: Optional[str] = None  # Path to cached Slack photo
    email: Optional[str] = None


@dataclass
class VideoConfig:
    """Configuration for the research video.

    All layout values are native pixel coordinates - NO SCALING at runtime.
    Use hd_720p() or hd_1080p() class methods for preset configurations.
    """

    # Resolution
    width: int = 1920
    height: int = 1080
    fps: int = 12

    # Timing
    duration_per_person: float = 15.0
    tool_display_time: float = 1.0
    finding_display_time: float = 1.5
    num_tools: int = 6  # Reduced - work integrations
    num_findings: int = 0  # Disabled - removed per user request

    # === NATIVE LAYOUT COORDINATES (1080p defaults) ===
    # All values are absolute pixels - no scaling

    # Left column - title and tools (all Y values shifted up 8px)
    left_margin: int = 35
    title_y: int = 27  # moved up 10px more
    title_font_scale: float = 0.7
    name_y: int = 72  # moved up 10px more
    name_font_scale: float = 0.9
    tools_start_y: int = 117  # moved up 10px more
    tools_line_height: int = 40  # +8px per user request
    tools_font_scale: float = 0.5
    findings_start_y: int = 397  # moved up 10px more
    findings_line_height: int = 32
    findings_font_scale: float = 0.5
    assessment_y: int = 557  # moved up 10px more
    assessment_font_scale: float = 0.65

    # Waveform box (GPU renders bars inside) - shifted up 8px
    wave_x: int = 35
    wave_y: int = 417  # moved up another 75px per user request
    wave_w: int = 1000  # Exact match: 200 bars * 5px = 1000px
    wave_h: int = 200  # box +50px bigger (was 150)
    wave_label_y: int = 569  # moved up 10px more
    wave_font_scale: float = 0.55
    num_bars: int = 200
    bar_width: int = 4
    bar_gap: int = 1

    # Voice stats box (below waveform) - shifted up 8px
    voice_stats_y: int = 697  # moved up 10px more
    voice_stats_h: int = 140
    voice_stats_font_scale: float = 0.45
    voice_stats_line_height: int = 22

    # Facial recognition box - TOP RIGHT (75% of doubled size)
    face_x: int = 1455  # Moved 15px left
    face_y: int = 30  # Top of screen
    face_w: int = 450  # 600 * 0.75
    face_h: int = 570  # 760 * 0.75
    face_font_scale: float = 0.55
    face_head_radius: int = 105  # 140 * 0.75
    face_body_width: int = 135  # 180 * 0.75

    # Voice profile - LEFT of facial recognition (adjusted for larger face)
    voice_profile_x: int = 920  # Left of face box
    voice_profile_y: int = 30  # Same height as face

    # Right column - REMOVED (no longer used)
    right_col_x: int = 1560
    right_col_title_y: int = 97
    right_col_font_scale: float = 0.55
    right_col_section_height: int = 230
    right_col_item_font_scale: float = 0.42
    right_col_item_height: int = 24

    # NPU stats - moved up significantly for larger text
    npu_y: int = 870  # Moved down another 50px per user request
    npu_font_scale: float = 0.55

    # Progress bar - stays at bottom
    progress_y: int = 1047  # Moved down 2px
    progress_h: int = 18  # Reduced by 2px
    progress_margin: int = 30

    # Legacy aliases for FFmpeg fallback mode (computed from native values)
    @property
    def right_column_width(self) -> int:
        return self.width - self.right_col_x

    @property
    def npu_width(self) -> int:
        return self.width

    # Legacy colors (not used in GPU mode)
    background_color: str = "black"
    text_color: str = "green"
    highlight_color: str = "white"
    font: str = "monospace"

    # Performance options (GPU-only pipeline)
    use_gpu: bool = True
    prefer_intel_gpu: bool = True

    @classmethod
    def hd_720p(cls) -> "VideoConfig":
        """720p HD preset (1280x720) - all native coordinates."""
        return cls(
            width=1280,
            height=720,
            # Left column
            left_margin=20,
            title_y=30,
            title_font_scale=0.5,
            name_y=60,
            name_font_scale=0.65,
            tools_start_y=90,
            tools_line_height=22,
            tools_font_scale=0.38,
            findings_start_y=280,
            findings_line_height=22,
            findings_font_scale=0.38,
            assessment_y=385,
            assessment_font_scale=0.5,
            # Waveform
            wave_x=20,
            wave_y=410,
            wave_w=700,
            wave_h=70,
            wave_label_y=400,
            wave_font_scale=0.42,
            num_bars=200,
            bar_width=3,
            bar_gap=1,
            # Voice stats
            voice_stats_y=495,
            voice_stats_h=100,
            voice_stats_font_scale=0.35,
            voice_stats_line_height=16,
            # Face
            face_x=780,
            face_y=55,
            face_w=200,
            face_h=240,
            face_font_scale=0.42,
            face_head_radius=45,
            face_body_width=55,
            # Right column
            right_col_x=1040,
            right_col_title_y=80,
            right_col_font_scale=0.42,
            right_col_section_height=155,
            right_col_item_font_scale=0.32,
            right_col_item_height=17,
            # NPU
            npu_y=605,
            npu_font_scale=0.42,
            # Progress
            progress_y=700,  # Moved down 2px
            progress_h=12,  # Reduced by 2px
            progress_margin=18,
        )

    @classmethod
    def hd_1080p(cls) -> "VideoConfig":
        """1080p Full HD preset (1920x1080) - default values."""
        return cls()  # Default values are 1080p


@dataclass
class VideoResult:
    """Result of video generation."""

    success: bool
    video_path: Optional[Path] = None
    duration_seconds: float = 0.0
    resolution: tuple[int, int] = (1280, 720)
    fps: int = 30
    source: str = "static"  # "wav2lip", "static", or "research"
    error: Optional[str] = None


# Work-related data sources for attendee lookup
RESEARCH_TOOLS = [
    # Primary work integrations
    "slack://user_activity",
    "gmail://inbox_summary",
    "gdrive://shared_docs",
    "gitlab://merge_requests",
    "github://pull_requests",
    "memory://context_history",
    # Secondary sources
    "jira://assigned_issues",
    "confluence://recent_pages",
    "calendar://meetings_today",
    "rover://employee_profile",
]

# Fake data categories
FAKE_CATEGORIES = [
    "Git Commits",
    "Slack Messages",
    "Meeting History",
    "Code Reviews",
    "Jira Tickets",
    "Wiki Edits",
    "Email Patterns",
    "Login History",
    "Badge Access",
    "Travel Records",
    "Expense Reports",
    "Training Certs",
    "Peer Reviews",
    "Project Roles",
    "Team Memberships",
]

# Work context findings
FAKE_FINDINGS = [
    "Active on 3 projects this sprint",
    "Last commit: 2 hours ago",
    "Open MRs: 2 pending review",
    "Jira tickets: 5 in progress",
    "Slack: online in #platform",
    "Calendar: 3 meetings today",
    "Recent docs: API design spec",
    "Team: Platform Engineering",
    "sudo usage: responsible",
    "Container preference: podman",
    "Cloud: hybrid enthusiast",
    "Agile certified: probably",
    "Standup attendance: 89%",
]

# Fake threat levels (all low/harmless)
THREAT_ASSESSMENTS = [
    "THREAT LEVEL: Minimal ✓",
    "RISK SCORE: 0.02 (safe)",
    "CLEARANCE: Approved ✓",
    "VERDICT: Good human 👍",
    "ANALYSIS: Seems nice",
    "RATING: 5 stars ⭐⭐⭐⭐⭐",
]
