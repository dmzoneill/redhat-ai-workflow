"""Shared video theme constants and small drawing helpers."""

import gc
import logging
import random
import resource
import time
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# OpenCV font settings (much faster than PIL)
CV_FONT = cv2.FONT_HERSHEY_SIMPLEX
CV_FONT_MONO = cv2.FONT_HERSHEY_PLAIN  # More monospace-like

# Use LINE_8 instead of LINE_AA for 3.7x faster text rendering
# LINE_AA = anti-aliased (slow), LINE_8 = 8-connected line (fast)
CV_LINE_TYPE = cv2.LINE_8  # Was CV_LINE_TYPE

# Color constants for OpenCV (BGR format)
CV_GREEN = (0, 200, 0)
CV_CYAN = (200, 200, 0)
CV_WHITE = (255, 255, 255)
CV_YELLOW = (0, 255, 255)
CV_RED = (0, 0, 200)
CV_DARK_GREEN = (0, 100, 0)

# Memory management thresholds (in MB)
MEMORY_WARNING_MB = 3000  # Trigger GC warning
MEMORY_CRITICAL_MB = 4000  # Trigger emergency cleanup

# Pre-compute RGB to YUV conversion matrices (BT.601)
# These are used for fast vectorized color conversion
_RGB_TO_Y = np.array([66, 129, 25], dtype=np.int16)
_RGB_TO_U = np.array([-38, -74, 112], dtype=np.int16)
_RGB_TO_V = np.array([112, -94, -18], dtype=np.int16)


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


def get_memory_mb() -> float:
    """Get current process memory usage in MB."""
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_maxrss / 1024  # Convert KB to MB on Linux


class _GcClock:  # pylint: disable=too-few-public-methods
    """Last garbage-collection timestamp, without a global statement."""

    last = 0.0


def maybe_gc(force: bool = False) -> None:
    """Run garbage collection periodically (every 30s) or if forced."""
    now = time.time()
    if force or (now - _GcClock.last > 30.0):
        gc.collect()
        _GcClock.last = now


def get_npu_stats() -> list[str]:
    """Read real-time NPU statistics from sysfs."""
    stats = []
    npu_path = Path("/sys/devices/pci0000:00/0000:00:0b.0")

    try:
        # Current frequency
        freq = (npu_path / "npu_current_frequency_mhz").read_text().strip()
        max_freq = (npu_path / "npu_max_frequency_mhz").read_text().strip()
        stats.append(f"NPU FREQ: {freq}/{max_freq} MHz")

        # Busy time
        busy_us = int((npu_path / "npu_busy_time_us").read_text().strip())
        busy_sec = busy_us / 1_000_000
        stats.append(f"NPU BUSY TIME: {busy_sec:.2f}s")

        # Memory utilization
        mem_bytes = int((npu_path / "npu_memory_utilization").read_text().strip())
        mem_mb = mem_bytes / (1024 * 1024)
        stats.append(f"NPU MEMORY: {mem_mb:.1f} MB")

        # Power state
        power_state = (npu_path / "power_state").read_text().strip()
        stats.append(f"POWER STATE: {power_state}")

        # Runtime status
        runtime = (npu_path / "power" / "runtime_status").read_text().strip()
        stats.append(f"RUNTIME: {runtime.upper()}")

        # Active time
        active_ms = int(
            (npu_path / "power" / "runtime_active_time").read_text().strip()
        )
        active_sec = active_ms / 1000
        stats.append(f"ACTIVE TIME: {active_sec:.1f}s")

        # Add some fake processing stats for effect
        stats.append(f"INFERENCE RATE: {random.randint(15, 25)} req/s")
        stats.append(f"LATENCY: {random.randint(20, 45)}ms")
        stats.append(f"THROUGHPUT: {random.uniform(0.8, 1.2):.2f} TOPS")
        stats.append(f"TEMP: {random.randint(42, 58)}C")
        stats.append(f"UTILIZATION: {random.randint(35, 85)}%")

    except OSError:
        # Fallback fake stats if NPU not available
        stats = [
            "NPU FREQ: 1400/1400 MHz",
            "NPU BUSY TIME: 12.34s",
            "NPU MEMORY: 128.5 MB",
            "POWER STATE: D0",
            "RUNTIME: ACTIVE",
            "ACTIVE TIME: 45.2s",
            f"INFERENCE RATE: {random.randint(15, 25)} req/s",
            f"LATENCY: {random.randint(20, 45)}ms",
            f"THROUGHPUT: {random.uniform(0.8, 1.2):.2f} TOPS",
            f"TEMP: {random.randint(42, 58)}C",
            f"UTILIZATION: {random.randint(35, 85)}%",
        ]

    return stats


def apply_wave_layout(renderer) -> None:
    """Copy waveform and NPU panel geometry onto a renderer."""
    # Waveform config - from native pixel config
    renderer.wave_width = renderer.config.wave_w
    renderer.wave_height = renderer.config.wave_h
    renderer.wave_bars = renderer.config.num_bars

    # NPU panel config - full width at bottom
    renderer.npu_width = renderer.config.width
    renderer.npu_height = 140

    # Pre-compute bar positions for waveform
    renderer.wave_step = renderer.wave_width / renderer.wave_bars
    renderer.wave_bar_width = max(2, int(renderer.wave_step) - 1)

    # Random phases for waveform animation (using numpy for speed)
    np.random.seed(42)  # Reproducible
    renderer.wave_phases = np.random.uniform(0, 6.28, renderer.wave_bars)
    renderer.wave_speeds = np.random.uniform(0.8, 1.2, renderer.wave_bars)
    renderer.wave_i_arr = np.arange(renderer.wave_bars)

    # Audio analysis state
    setattr(renderer, "_fft_smoothing", 0.3)
    setattr(renderer, "_prev_fft_bars", None)


def draw_text(image, text, origin, style, font=CV_FONT):
    """Draw one OpenCV text run.

    ``style`` is ``(scale, color, thickness)`` so the helper stays within
    pylint's argument limit while each call site stays a single line.
    """
    scale, color, thickness = style
    cv2.putText(image, text, origin, font, scale, color, thickness, CV_LINE_TYPE)
