"""
Video overlay rendering — text, layout calculations, and frame composition.

Handles all CPU-side frame rendering including:
- Static cache initialization (OpenCV base frame with UI elements)
- Per-attendee base frame creation (GPU text + shapes via OpenGL)
- Waveform generation (simulated and audio-reactive)
- NPU stats panel rendering
- FFT computation for audio visualization

Extracted from video_generator.py to separate rendering concerns from
device I/O and orchestration.
"""

import logging
import math
import random
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import cv2
import numpy as np

if TYPE_CHECKING:
    from .gpu_text import VideoTextRenderer
    from .video_generator import Attendee, VideoConfig

logger = logging.getLogger(__name__)

# OpenCV font settings (much faster than PIL)
CV_FONT = cv2.FONT_HERSHEY_SIMPLEX
CV_FONT_MONO = cv2.FONT_HERSHEY_PLAIN  # More monospace-like

# Use LINE_8 instead of LINE_AA for 3.7x faster text rendering
CV_LINE_TYPE = cv2.LINE_8

# Color constants for OpenCV (BGR format)
CV_GREEN = (0, 200, 0)
CV_CYAN = (200, 200, 0)
CV_WHITE = (255, 255, 255)
CV_YELLOW = (0, 255, 255)
CV_RED = (0, 0, 200)
CV_DARK_GREEN = (0, 100, 0)

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

THREAT_ASSESSMENTS = [
    "THREAT LEVEL: Minimal ✓",
    "RISK SCORE: 0.02 (safe)",
    "CLEARANCE: Approved ✓",
    "VERDICT: Good human 👍",
    "ANALYSIS: Seems nice",
    "RATING: 5 stars ⭐⭐⭐⭐⭐",
]


class VideoOverlayRenderer:
    """
    Renders text overlays, layout elements, and frame composition.

    All methods operate on numpy arrays (BGR format) and do not access
    GPU/OpenGL state directly. The GPU text renderer is used via its
    public API only.
    """

    def __init__(
        self,
        config: "VideoConfig",
        gpu_text_renderer: Optional["VideoTextRenderer"] = None,
    ):
        """
        Initialize the overlay renderer.

        Args:
            config: VideoConfig with native pixel coordinates
            gpu_text_renderer: Optional GPU text renderer for anti-aliased text
        """
        self.config = config
        self._gpu_text_renderer = gpu_text_renderer

        # Waveform config - from native pixel config
        self.wave_width = config.wave_w
        self.wave_height = config.wave_h
        self.wave_bars = config.num_bars

        # NPU panel config - full width at bottom
        self.npu_width = config.width
        self.npu_height = 140

        # Pre-compute bar positions for waveform
        self.wave_step = self.wave_width / self.wave_bars
        self.wave_bar_width = max(2, int(self.wave_step) - 1)

        # Random phases for waveform animation (using numpy for speed)
        np.random.seed(42)  # Reproducible
        self.wave_phases = np.random.uniform(0, 6.28, self.wave_bars)
        self.wave_speeds = np.random.uniform(0.8, 1.2, self.wave_bars)
        self.wave_i_arr = np.arange(self.wave_bars)

        # Audio analysis state
        self._fft_smoothing = 0.3  # Smoothing factor for FFT
        self._prev_fft_bars: Optional[np.ndarray] = None

        # Pre-render static elements for performance
        self._static_cache: dict = {}
        self._init_static_cache()

        # Pre-allocate waveform and NPU buffers
        self._wave_buffer = np.zeros(
            (self.wave_height, self.wave_width, 3), dtype=np.uint8
        )
        self._npu_buffer = np.zeros(
            (self.npu_height, self.npu_width, 3), dtype=np.uint8
        )

        # Pre-allocate FFT computation buffers to avoid per-frame allocations
        self._fft_bar_heights = np.zeros(self.wave_bars, dtype=np.float32)
        self._fft_silence_bars = np.full(self.wave_bars, 0.12, dtype=np.float32)
        self._fft_hanning = None  # Will be created on first use with correct size

    def _init_static_cache(self) -> None:
        """
        Pre-render static UI elements using OpenCV (much faster than PIL).

        This significantly reduces text rendering overhead by caching:
        - Header text
        - Section headers
        - Static labels
        - UI borders/lines
        """
        config = self.config

        # Create a base frame with OpenCV (BGR format)
        base_frame = np.zeros((config.height, config.width, 3), dtype=np.uint8)

        # Layout constants
        right_col_x = config.width - config.right_column_width
        npu_panel_height = self.npu_height
        bottom_section_y = config.height - npu_panel_height
        padding = 15

        # Font scales for different sizes
        font_small = 0.45
        font_medium = 0.55
        thickness = 1

        # Static header
        cv2.putText(
            base_frame,
            "[ AI RESEARCH MODULE v2.1 ]",
            (padding, 22),
            CV_FONT,
            font_medium,
            CV_CYAN,
            thickness,
            CV_LINE_TYPE,
        )

        # Right column vertical divider
        cv2.line(
            base_frame, (right_col_x, 50), (right_col_x, bottom_section_y), CV_GREEN, 2
        )

        # "Building Context" heading
        cv2.putText(
            base_frame,
            "BUILDING CONTEXT",
            (right_col_x + 8, 68),
            CV_FONT,
            font_small,
            CV_RED,
            thickness,
            CV_LINE_TYPE,
        )

        # Section headers (static)
        sections_start_y = 75
        section_height = (bottom_section_y - sections_start_y) // 4
        section_headers = ["[ JIRA ]", "[ SLACK ]", "[ SEMANTIC ]", "[ COMMS ]"]
        for i, header in enumerate(section_headers):
            sec_y = sections_start_y + i * section_height + 12
            cv2.putText(
                base_frame,
                header,
                (right_col_x + 8, sec_y),
                CV_FONT,
                font_small,
                CV_CYAN,
                thickness,
                CV_LINE_TYPE,
            )

        # Facial recognition box and label
        silhouette_w = 180
        silhouette_h = 200
        silhouette_x = right_col_x - silhouette_w - 20
        silhouette_y = 55
        cv2.putText(
            base_frame,
            "FACIAL RECOGNITION",
            (silhouette_x + 20, silhouette_y - 5),
            CV_FONT,
            font_small,
            CV_RED,
            thickness,
            CV_LINE_TYPE,
        )
        cv2.rectangle(
            base_frame,
            (silhouette_x, silhouette_y),
            (silhouette_x + silhouette_w, silhouette_y + silhouette_h),
            CV_GREEN,
            2,
        )

        # Silhouette shape (static) - using filled shapes
        head_cx = silhouette_x + silhouette_w // 2
        head_cy = silhouette_y + 50
        cv2.circle(base_frame, (head_cx, head_cy), 28, CV_DARK_GREEN, -1)  # Head
        cv2.rectangle(
            base_frame,
            (head_cx - 40, head_cy + 35),
            (head_cx + 40, head_cy + 145),
            CV_DARK_GREEN,
            -1,
        )  # Body
        cv2.rectangle(
            base_frame,
            (head_cx - 55, head_cy + 35),
            (head_cx + 55, head_cy + 60),
            CV_DARK_GREEN,
            -1,
        )  # Shoulders

        # Waveform box - from native config
        wave_w = config.wave_w
        wave_h = config.wave_h
        wave_x = config.wave_x
        wave_y = config.wave_y
        cv2.rectangle(
            base_frame,
            (wave_x, wave_y),
            (wave_x + wave_w, wave_y + wave_h),
            CV_GREEN,
            2,
        )
        cv2.putText(
            base_frame,
            "ANALYZING SPEECH PATTERNS",
            (wave_x + wave_w - 265, config.assessment_y),
            CV_FONT,
            font_small,
            CV_CYAN,
            thickness,
            CV_LINE_TYPE,
        )

        # Horizontal line above NPU
        cv2.line(
            base_frame,
            (0, bottom_section_y),
            (config.width, bottom_section_y),
            (0, 180, 0),
            2,
        )

        # Store as BGR (OpenCV native format) to avoid per-frame conversion
        self._static_cache["base_frame_bgr"] = base_frame

        # Cache layout constants
        self._static_cache["right_col_x"] = right_col_x
        self._static_cache["bottom_section_y"] = bottom_section_y
        self._static_cache["sections_start_y"] = sections_start_y
        self._static_cache["section_height"] = section_height
        self._static_cache["silhouette_x"] = silhouette_x
        self._static_cache["silhouette_y"] = silhouette_y
        self._static_cache["silhouette_w"] = silhouette_w
        self._static_cache["silhouette_h"] = silhouette_h
        self._static_cache["wave_x"] = wave_x
        self._static_cache["wave_y"] = wave_y
        self._static_cache["wave_w"] = wave_w
        self._static_cache["wave_h"] = wave_h
        self._static_cache["padding"] = padding

        # Cache font settings
        self._static_cache["font_small"] = font_small
        self._static_cache["font_medium"] = font_medium

        # Pre-compute waveform scaling indices (avoids per-frame computation)
        scale_y = (wave_h - 4) / self.wave_height
        scale_x = (wave_w - 4) / self.wave_width
        self._static_cache["wave_y_indices"] = np.clip(
            (np.arange(wave_h - 4) / scale_y).astype(np.int32), 0, self.wave_height - 1
        )
        self._static_cache["wave_x_indices"] = np.clip(
            (np.arange(wave_w - 4) / scale_x).astype(np.int32), 0, self.wave_width - 1
        )

        logger.debug("Static element cache initialized (OpenCV)")

    def compute_fft_bars(self, audio: np.ndarray) -> np.ndarray:
        """Compute FFT and convert to bar heights for visualization.

        Includes noise gate: when audio RMS is below threshold, returns
        minimal bars to indicate silence/muted mic.

        Args:
            audio: Audio samples as float32 numpy array

        Returns:
            Bar heights as float32 numpy array (0-1 range)
        """
        # Noise gate: check if audio is essentially silent
        rms = np.sqrt(np.mean(audio**2))
        noise_threshold = 0.005  # Below this RMS, consider it silence/muted

        if rms < noise_threshold:
            # Return minimal flat bars for silence (reuse pre-allocated buffer)
            np.copyto(self._fft_bar_heights, self._fft_silence_bars)
            # Add small random variation in-place
            self._fft_bar_heights += np.random.uniform(-0.02, 0.02, self.wave_bars)
            np.clip(self._fft_bar_heights, 0.1, 0.15, out=self._fft_bar_heights)
            if self._prev_fft_bars is None:
                self._prev_fft_bars = self._fft_bar_heights.copy()
            else:
                np.copyto(self._prev_fft_bars, self._fft_bar_heights)
            return self._fft_bar_heights

        # Create/reuse hanning window (only allocate once per audio size)
        if self._fft_hanning is None or len(self._fft_hanning) != len(audio):
            self._fft_hanning = np.hanning(len(audio)).astype(np.float32)

        # Apply window function to reduce spectral leakage (in-place multiply)
        windowed = audio * self._fft_hanning

        # Compute FFT
        fft = np.abs(np.fft.rfft(windowed))

        # We only care about frequencies up to ~8kHz (half of 16kHz sample rate)
        n_fft_bins = len(fft)

        # Use logarithmic frequency scaling - write directly to pre-allocated buffer
        self._fft_bar_heights.fill(0)

        for i in range(self.wave_bars):
            # Logarithmic mapping: more resolution at low frequencies
            low_freq = int(
                n_fft_bins
                * (np.exp(i / self.wave_bars * np.log(n_fft_bins)) - 1)
                / (n_fft_bins - 1)
            )
            high_freq = int(
                n_fft_bins
                * (np.exp((i + 1) / self.wave_bars * np.log(n_fft_bins)) - 1)
                / (n_fft_bins - 1)
            )
            high_freq = max(high_freq, low_freq + 1)

            # Average the FFT bins for this bar
            if high_freq <= n_fft_bins:
                self._fft_bar_heights[i] = np.mean(fft[low_freq:high_freq])

        # Normalize to 0-1 range with some headroom (in-place)
        max_val = np.max(self._fft_bar_heights)
        if max_val > 0:
            self._fft_bar_heights /= max_val

        # Scale by RMS (in-place)
        rms_scale = min(1.0, (rms / 0.02) * 3.0)
        self._fft_bar_heights *= rms_scale

        # Apply smoothing with previous frame (in-place)
        if self._prev_fft_bars is not None:
            self._fft_bar_heights *= 0.7
            self._fft_bar_heights += 0.3 * self._prev_fft_bars

        # Update prev_fft_bars
        if self._prev_fft_bars is None:
            self._prev_fft_bars = self._fft_bar_heights.copy()
        else:
            np.copyto(self._prev_fft_bars, self._fft_bar_heights)

        # Apply final scaling (in-place)
        self._fft_bar_heights *= 0.64
        self._fft_bar_heights += 0.15

        return self._fft_bar_heights

    def generate_waveform_frame_from_audio(
        self, bar_heights: np.ndarray, out: np.ndarray = None
    ) -> np.ndarray:
        """Generate waveform frame from audio-derived bar heights.

        Args:
            bar_heights: Array of bar heights from FFT analysis
            out: Optional pre-allocated output buffer

        Returns:
            numpy array (wave_height, wave_width, 3)
        """
        # Use pre-allocated buffer or create new one
        if out is None:
            img = np.zeros((self.wave_height, self.wave_width, 3), dtype=np.uint8)
        else:
            img = out
            img.fill(0)

        img[:, :, 1] = 18  # Green channel background

        # Convert normalized bar heights (0-1) to pixel heights
        bar_heights = np.nan_to_num(bar_heights, nan=0.1, posinf=1.0, neginf=0.1)
        pixel_heights = (bar_heights * self.wave_height).astype(np.int32)
        pixel_heights = np.clip(pixel_heights, 4, self.wave_height - 2)

        x_starts = (self.wave_i_arr * self.wave_step).astype(np.int32)
        tops = ((self.wave_height - pixel_heights) // 2).astype(np.int32)
        bottoms = ((self.wave_height + pixel_heights) // 2).astype(np.int32)

        # Draw all bars
        for idx in range(self.wave_bars):
            x = int(x_starts[idx])
            x_end = min(x + self.wave_bar_width, self.wave_width)
            top = int(tops[idx])
            bottom = int(bottoms[idx])
            # Brighter green for audio-reactive mode
            img[top:bottom, x:x_end, 0] = 30
            img[top:bottom, x:x_end, 1] = 220
            img[top:bottom, x:x_end, 2] = 30

        return img

    def generate_waveform_frame(self, t: float, out: np.ndarray = None) -> np.ndarray:
        """Generate a single waveform frame at time t using numpy (fast).

        Args:
            t: Time in seconds
            out: Optional pre-allocated output buffer (wave_height, wave_width, 3)

        Returns:
            numpy array (wave_height, wave_width, 3) in RGB format
        """
        # Use pre-allocated buffer or create new one
        if out is None:
            img = np.zeros((self.wave_height, self.wave_width, 3), dtype=np.uint8)
        else:
            img = out
            img.fill(0)

        img[:, :, 1] = 18  # Green channel background

        # Vectorized height calculation (use cached arrays)
        i = self.wave_i_arr
        p = self.wave_phases
        s = self.wave_speeds

        heights = (
            45
            + 35 * np.sin(t * 4 * s + i * 0.12 + p)
            + 20 * np.sin(t * 7 * s + i * 0.2 + p * 1.3)
            + 12 * np.sin(t * 11 * s + i * 0.35 + p * 0.7)
            + 15 * np.sin(t * 2.5 * s + i * 0.06)
        )

        # Spike bursts
        st = (t * 3 + i * 0.1) % 4
        spike_mask = st < 0.3
        heights[spike_mask] += np.sin(st[spike_mask] / 0.3 * np.pi) * 25

        heights = np.clip(heights, 6, self.wave_height - 4).astype(np.int32)

        x_starts = (i * self.wave_step).astype(np.int32)
        tops = (self.wave_height - heights) // 2
        bottoms = (self.wave_height + heights) // 2

        # Draw all bars (loop is fast enough for 150 bars)
        for idx in range(self.wave_bars):
            x = x_starts[idx]
            x_end = min(x + self.wave_bar_width, self.wave_width)
            top = tops[idx]
            bottom = bottoms[idx]
            # Green bar (BGR format for OpenCV compatibility)
            img[top:bottom, x:x_end, 0] = 25
            img[top:bottom, x:x_end, 1] = 200
            img[top:bottom, x:x_end, 2] = 25

        return img

    def generate_npu_frame(
        self, t: float, frame_num: int, out: np.ndarray = None
    ) -> np.ndarray:
        """Generate a single NPU panel frame using OpenCV (much faster than PIL).

        Args:
            t: Time in seconds
            frame_num: Current frame number
            out: Optional pre-allocated output buffer (npu_height, npu_width, 3)

        Returns:
            numpy array (npu_height, npu_width, 3) in BGR format
        """
        # Use pre-allocated buffer or create new one
        if out is None:
            frame = np.zeros((self.npu_height, self.npu_width, 3), dtype=np.uint8)
        else:
            frame = out
            frame.fill(0)

        frame[:, :, 1] = 17  # Dark green background

        font_small = 0.4
        thickness = 1

        # Header
        cv2.putText(
            frame,
            "[ INTEL NPU - METEOR LAKE ]",
            (15, 18),
            CV_FONT,
            font_small,
            CV_CYAN,
            thickness,
            CV_LINE_TYPE,
        )

        y = 35
        line_h = 16

        # Column 1 - NPU stats
        stats1 = [
            "FREQ: 1400 MHz",
            f"BUSY: {t*1.2+17.99:.1f}s",
            "MEM: 65.5 MB",
            f"UTIL: {40+int(30*math.sin(t*0.4))}%",
            f"TEMP: {45+int(10*math.sin(t*0.2))}C",
        ]
        for i, s in enumerate(stats1):
            cv2.putText(
                frame,
                s,
                (15, y + i * line_h),
                CV_FONT,
                font_small,
                CV_GREEN,
                thickness,
                CV_LINE_TYPE,
            )

        # Column 2 - Model info
        stats2 = [
            "MODEL: whisper-int8",
            "PRECISION: INT8",
            "INPUT: 16kHz PCM",
            "TILES: 2/2",
            "CACHE: ENABLED",
        ]
        for i, s in enumerate(stats2):
            cv2.putText(
                frame,
                s,
                (180, y + i * line_h),
                CV_FONT,
                font_small,
                CV_GREEN,
                thickness,
                CV_LINE_TYPE,
            )

        # Column 3 - Counters
        stats3 = [
            f"SAMPLES: {int(t*16000)}",
            f"INFERENCES: {int(t*18)}",
            f"TOKENS: {int(t*45)}",
            f"FRAMES: {frame_num}",
            f"TIME: {int(t) // 60:02d}:{int(t) % 60:02d}.{int((t % 1) * 100):02d}",
        ]
        for i, s in enumerate(stats3):
            cv2.putText(
                frame,
                s,
                (380, y + i * line_h),
                CV_FONT,
                font_small,
                CV_GREEN,
                thickness,
                CV_LINE_TYPE,
            )

        # Column 4 - System stats
        stats4 = [
            f"CPU: {15+int(10*math.sin(t*0.5))}%",
            f"MEM: {65+int(5*math.sin(t*0.3))} MB",
            f"QUEUE: {int((t * 3) % 5)}",
            f"LATENCY: {25+int(8*math.sin(t*2))}ms",
            "STATUS: ACTIVE",
        ]
        for i, s in enumerate(stats4):
            color = CV_CYAN if i == 4 else CV_GREEN
            cv2.putText(
                frame,
                s,
                (560, y + i * line_h),
                CV_FONT,
                font_small,
                color,
                thickness,
                CV_LINE_TYPE,
            )

        # Column 5 - Additional telemetry
        stats5 = [
            f"RATE: {15+int(10*math.sin(t*0.5))} req/s",
            f"THROUGHPUT: {0.8+0.4*math.sin(t*0.3):.2f} TOPS",
            f"POWER: {4.2+0.8*math.sin(t*0.2):.1f}W",
            "DMA: ACTIVE",
            f"IRQ: {146 + int(t) % 10}",
        ]
        for i, s in enumerate(stats5):
            cv2.putText(
                frame,
                s,
                (740, y + i * line_h),
                CV_FONT,
                font_small,
                CV_GREEN,
                thickness,
                CV_LINE_TYPE,
            )

        # Column 6 - Far right
        stats6 = [
            "BATCH: 1",
            "STREAMS: 1",
            f"CONTEXT: {int(t * 100) % 512}",
            "BUFFER: 480ms",
            "RUNTIME: ACTIVE",
        ]
        for i, s in enumerate(stats6):
            color = CV_CYAN if i == 4 else CV_GREEN
            cv2.putText(
                frame,
                s,
                (920, y + i * line_h),
                CV_FONT,
                font_small,
                color,
                thickness,
                CV_LINE_TYPE,
            )

        # Progress bar at bottom
        padding = 15
        bar_max_width = self.npu_width - padding * 2 - 150
        bar_width = int((t % 15) / 15 * bar_max_width)
        bar_y = self.npu_height - 20

        # Outline
        cv2.rectangle(
            frame, (padding, bar_y), (padding + bar_max_width, bar_y + 12), CV_GREEN, 1
        )
        # Fill
        if bar_width > 0:
            cv2.rectangle(
                frame,
                (padding + 2, bar_y + 2),
                (padding + 2 + bar_width, bar_y + 10),
                CV_GREEN,
                -1,
            )
        # Percentage text
        cv2.putText(
            frame,
            f"PROCESSING: {int((t % 15) / 15 * 100)}%",
            (self.npu_width - padding - 130, bar_y + 10),
            CV_FONT,
            font_small,
            CV_GREEN,
            thickness,
            CV_LINE_TYPE,
        )

        # Return BGR array directly (caller expects BGR for OpenCV compatibility)
        return frame

    def precompute_attendee_data(self, attendee: "Attendee") -> dict:
        """Pre-compute attendee-specific data to avoid per-frame string operations.

        Includes real Slack data if available from the attendee object.
        Also loads and resizes the profile photo if available.

        Args:
            attendee: Attendee object with name and optional enrichment data

        Returns:
            Dictionary of pre-computed attendee data
        """
        name_parts = attendee.name.split()
        first_name = name_parts[0].lower() if name_parts else "user"
        last_name = name_parts[-1].lower() if len(name_parts) > 1 else first_name
        username = f"{first_name[0]}{last_name}" if len(name_parts) > 1 else first_name
        email_domain = "redhat.com"

        # Use real Slack data if available
        slack_id = attendee.slack_id or f"U{hash(attendee.name) % 99999999:08d}"
        slack_display_name = attendee.slack_display_name or attendee.name
        photo_path = attendee.photo_path
        email = attendee.email or f"{username}@{email_domain}"

        # Load and resize profile photo if available
        photo_bgr = None
        if photo_path and Path(photo_path).exists():
            try:
                img = cv2.imread(photo_path)
                if img is not None:
                    # Resize to fit in face box (keep aspect ratio)
                    c = self.config
                    target_size = min(c.face_w - 20, c.face_h - 40)  # Leave margin
                    h, w = img.shape[:2]
                    scale = target_size / max(h, w)
                    new_w, new_h = int(w * scale), int(h * scale)
                    photo_bgr = cv2.resize(
                        img, (new_w, new_h), interpolation=cv2.INTER_AREA
                    )
                    logger.debug(
                        f"Loaded photo for {attendee.name}: {photo_path} -> {new_w}x{new_h}"
                    )
            except Exception as e:
                logger.warning(f"Failed to load photo {photo_path}: {e}")

        return {
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
            "email_domain": email_domain,
            "voice_print_id": hash(attendee.name) % 99999,
            # Real Slack data
            "slack_id": slack_id,
            "slack_display_name": slack_display_name,
            "photo_path": photo_path,
            "photo_bgr": photo_bgr,  # Pre-loaded and resized photo
            "email": email,
            "has_slack_data": attendee.slack_id is not None,
            "tools": [
                (
                    f"slack://user/{slack_id}"
                    if attendee.slack_id
                    else f"slack://search?user={first_name}.{last_name}"
                ),
                f"ldap://query?uid={username}",
                f"jira://search?assignee={username}",
                f"gitlab://commits?author={email}",
                f"confluence://pages?author={attendee.name.replace(' ', '+')}",
                f"workday://profile/{username}",
                f"google://calendar?email={email}",
                f"deepface://match?name={attendee.name.replace(' ', '_')}",
            ],
        }

    def create_base_frame(
        self,
        attendee: "Attendee",
        attendee_idx: int,
        total_attendees: int,
        tools: list,
        findings: list,
        assessment: str,
        attendee_data: dict,
        t: float = 0.0,
        frame_num: int = 0,
        transcript_history: list = None,
        npu_stats: dict = None,
        stt_stats: dict = None,
        stt_enabled: bool = False,
    ) -> np.ndarray:
        """
        Create base frame using full GPU pipeline (OpenGL text + shapes).

        All text and shapes are rendered via OpenGL for smooth anti-aliased output.
        Dynamic NPU stats are included and update each second.

        Args:
            attendee: Current attendee being rendered
            attendee_idx: Index of current attendee
            total_attendees: Total number of attendees
            tools: List of tool strings to display
            findings: List of finding strings to display
            assessment: Assessment string
            attendee_data: Pre-computed attendee data from precompute_attendee_data
            t: Time in seconds (for dynamic NPU stats and animations)
            frame_num: Current frame number
            transcript_history: List of recent transcriptions (most recent first)
            npu_stats: Real NPU stats dict (from sysfs monitoring)
            stt_stats: Real STT/inference stats dict
            stt_enabled: Whether STT is currently active
        """
        transcript_history = transcript_history or []
        npu_stats = npu_stats or {
            "freq_mhz": 0,
            "max_freq_mhz": 1400,
            "busy_us": 0,
            "busy_delta_us": 0,
            "mem_bytes": 0,
            "power_state": "D0",
            "runtime_status": "active",
            "active_ms": 0,
            "last_update": 0.0,
        }
        stt_stats = stt_stats or {
            "inference_count": 0,
            "samples_processed": 0,
            "last_inference_ms": 0.0,
            "last_rt": 0.0,
            "avg_rt": 0.0,
            "avg_latency_ms": 0.0,
            "inferences_per_second": 0.0,
        }

        if not self._gpu_text_renderer:
            raise RuntimeError(
                "GPU text renderer not initialized - required for video generation"
            )

        c = self.config

        # Build list of text items: (text, x, y, color_name, size_name)
        text_items = []

        # === LEFT SIDE: Target info and tools ===
        text_items.append(
            (
                "[ AI WORKFLOW COMMAND CENTER ]",
                c.left_margin,
                c.title_y,
                "green",
                "large",
            )
        )

        # Name with animated dots (cycles through 1-3 dots) - XLARGE font (+10pt)
        dot_count = (int(t * 2) % 3) + 1  # 1, 2, 3 dots cycling
        name_with_dots = f"{attendee.name} {'.' * dot_count}"
        text_items.append((name_with_dots, c.left_margin, c.name_y, "green", "xlarge"))

        # Tools list - appear one at a time (1 per second) - MEDIUM font (+6pt)
        visible_tools = min(int(t) + 1, 8)  # Show 1 more tool each second, max 8
        for i, tool in enumerate(tools[:visible_tools]):
            y = c.tools_start_y + i * c.tools_line_height
            text_items.append((f"> {tool}", c.left_margin, y, "green", "medium"))

        # Findings
        for i, finding in enumerate(findings[:4]):
            y = c.findings_start_y + i * c.findings_line_height
            text_items.append((f"[+] {finding}", c.left_margin, y, "cyan", "normal"))

        # === WAVEFORM LABEL - above the waveform box, left aligned ===
        text_items.append(
            ("ANALYZING SPEECH PATTERNS", c.wave_x, c.wave_y - 15, "cyan", "medium")
        )

        # === LIVE TRANSCRIPTION STACK (below waveform box) ===
        transcript_start_y = c.wave_y + c.wave_h + 20
        transcript_line_height = 34  # +8px line height per user request
        max_chars = 90  # Max characters per line

        if transcript_history:
            for i, text in enumerate(transcript_history[:6]):  # Show up to 6 lines
                # Truncate long lines
                display_text = text[-max_chars:] if len(text) > max_chars else text
                # Fade older lines (newest is brightest)
                if i == 0:
                    color = "white"  # Most recent - bright white
                elif i == 1:
                    color = "cyan"  # Second most recent
                else:
                    color = "dark_green"  # Older - faded

                y = transcript_start_y + i * transcript_line_height
                text_items.append((f"> {display_text}", c.wave_x, y, color, "medium"))

        # === VOICE PROFILE ANALYSIS - LEFT of facial recognition (top right area) ===
        voice_x = c.voice_profile_x
        voice_y = c.voice_profile_y
        text_items.append(
            ("VOICE PROFILE ANALYSIS", voice_x, voice_y, "green", "large")
        )

        stats = [
            f"Voice Print ID: {attendee_data['voice_print_id']:05d}",
            "",
            f"Freq: 125-4000 Hz | Pitch: {random.randint(150, 220)} Hz",
            f"Cadence: {random.randint(120, 160)} wpm | Conf: {random.uniform(90, 99):.1f}%",
        ]
        for i, stat in enumerate(stats):
            if stat:  # Skip empty lines
                text_items.append(
                    (stat, voice_x, voice_y + 45 + i * 40, "orange", "medium")
                )

        # === FACIAL RECOGNITION - TOP RIGHT ===
        text_items.append(
            ("FACIAL RECOGNITION", c.face_x, c.face_y - 10, "red", "large")
        )

        # Show Slack username below the profile image
        if attendee_data and attendee_data.get("has_slack_data"):
            slack_name = attendee_data.get("slack_display_name", "")
            slack_id = attendee_data.get("slack_id", "")
            # Position below the face box
            slack_info_y = c.face_y + c.face_h + 25
            text_items.append(
                (f"@{slack_name}", c.face_x, slack_info_y, "cyan", "medium")
            )
            text_items.append(
                (f"[{slack_id}]", c.face_x, slack_info_y + 25, "dark_green", "normal")
            )

        # === NPU STATS (all GPU-rendered for consistent quality) ===
        npu_header_y = c.npu_y + 18
        text_items.append(
            (
                "[ INTEL NPU - METEOR LAKE ]",
                c.left_margin,
                npu_header_y,
                "cyan",
                "normal",
            )
        )

        # NPU stats layout
        npu_stats_y = c.npu_y + 55  # More space after header
        npu_line_h = 38 if c.height >= 1080 else 28
        npu_size = "large"

        # Column positions (proportional to width)
        col_x = [
            int(c.width * 0.02),
            int(c.width * 0.17),
            int(c.width * 0.33),
            int(c.width * 0.53),
            int(c.width * 0.69),
            int(c.width * 0.84),
        ]

        # Get real NPU stats from cached values
        npu = npu_stats
        busy_sec = npu["busy_us"] / 1_000_000
        mem_mb = npu["mem_bytes"] / (1024 * 1024)
        util_pct = (
            min(100, int(npu["busy_delta_us"] / 5000))
            if npu["busy_delta_us"] > 0
            else 0
        )
        runtime_status = npu["runtime_status"].upper()

        # Column 1 - NPU core stats
        col1_stats = [
            f"FREQ: {npu['freq_mhz']}/{npu['max_freq_mhz']} MHz",
            f"BUSY: {busy_sec:.2f}s",
            f"MEM: {mem_mb:.1f} MB",
        ]
        for i, stat in enumerate(col1_stats):
            text_items.append(
                (stat, col_x[0], npu_stats_y + i * npu_line_h, "green", npu_size)
            )

        # Column 2 - NPU utilization
        col2_stats = [
            f"UTIL: {util_pct}%",
            f"POWER: {npu['power_state']}",
            f"RUNTIME: {runtime_status}",
        ]
        for i, stat in enumerate(col2_stats):
            color = "cyan" if "ACTIVE" in stat else "green"
            text_items.append(
                (stat, col_x[1], npu_stats_y + i * npu_line_h, color, npu_size)
            )

        # Column 3 - Model info (static but accurate)
        col3_stats = [
            "MODEL: whisper-base",
            "PRECISION: FP16",
            "INPUT: 16kHz PCM",
        ]
        for i, stat in enumerate(col3_stats):
            text_items.append(
                (stat, col_x[2], npu_stats_y + i * npu_line_h, "green", npu_size)
            )

        # Column 4 - Real inference counters from STT engine
        stt = stt_stats
        col4_stats = [
            f"SAMPLES: {stt['samples_processed']}",
            f"INFERENCES: {stt['inference_count']}",
            f"FRAMES: {frame_num}",
        ]
        for i, stat in enumerate(col4_stats):
            text_items.append(
                (stat, col_x[3], npu_stats_y + i * npu_line_h, "green", npu_size)
            )

        # Column 5 - Real inference performance
        rtf_display = f"{stt['avg_rtf']:.2f}" if stt["avg_rt"] > 0 else "---"
        col5_stats = [
            f"RTF: {rtf_display}",
            f"DEVICE: {stt.get('device', 'NPU')[:8]}",
            f"STT: {'ON' if stt_enabled else 'OFF'}",
        ]
        for i, stat in enumerate(col5_stats):
            color = "cyan" if "ON" in stat or stt["avg_rt"] < 0.5 else "green"
            text_items.append(
                (stat, col_x[4], npu_stats_y + i * npu_line_h, color, npu_size)
            )

        # Column 6 - Real telemetry from STT engine
        latency_display = (
            f"{stt['avg_latency_ms']:.0f}ms" if stt["avg_latency_ms"] > 0 else "---"
        )
        rate_display = (
            f"{stt['inferences_per_second']:.1f}/s"
            if stt["inferences_per_second"] > 0
            else "---"
        )
        col6_stats = [
            f"RATE: {rate_display}",
            f"LATENCY: {latency_display}",
            f"STATUS: {runtime_status}",
        ]
        for i, stat in enumerate(col6_stats):
            color = "cyan" if "ACTIVE" in stat else "green"
            text_items.append(
                (stat, col_x[5], npu_stats_y + i * npu_line_h, color, npu_size)
            )

        # Build shapes list for GPU rendering
        has_photo = attendee_data and attendee_data.get("photo_bgr") is not None

        shapes = [
            # Waveform box border
            (
                "rect",
                c.wave_x - 3,
                c.wave_y - 3,
                c.wave_w + 6,
                c.wave_h + 6,
                "dark_green",
                1,
            ),
            # NPU divider line
            ("line", 0, c.npu_y, c.width, c.npu_y, "dark_green", 1),
            # Progress bar outline
            (
                "rect",
                c.progress_margin,
                c.progress_y,
                c.width - c.progress_margin * 2,
                c.progress_h,
                "dark_green",
                1,
            ),
        ]

        # Only show face box and silhouette if NO photo available
        if not has_photo:
            # Face box outline
            shapes.append(
                ("rect", c.face_x, c.face_y, c.face_w, c.face_h, "dark_green", 1)
            )
            # Silhouette
            center_x = c.face_x + c.face_w // 2
            silhouette_size = 180
            head_radius = silhouette_size // 3
            center_y = c.face_y + 25 + head_radius + 10
            body_width = head_radius
            body_top = center_y + head_radius + 15
            body_height = silhouette_size - head_radius * 2 - 25
            # Silhouette head (circle)
            shapes.append(("circle", center_x, center_y, head_radius, "green", 2))
            # Silhouette body (rectangle)
            shapes.append(
                (
                    "rect",
                    center_x - body_width,
                    body_top,
                    body_width * 2,
                    body_height,
                    "green",
                    2,
                )
            )

        # Render all text AND shapes with GPU in single pass
        frame = self._gpu_text_renderer.render_frame(text_items, shapes, (0, 0, 0))

        # Overlay profile photo in face area if available
        if has_photo:
            photo = attendee_data["photo_bgr"]
            ph, pw = photo.shape[:2]
            # Center photo in face box area
            photo_x = c.face_x + (c.face_w - pw) // 2
            photo_y = c.face_y + 25  # Below "FACIAL RECOGNITION" header
            # Ensure we don't go out of bounds
            if photo_y + ph <= c.height and photo_x + pw <= c.width:
                frame[photo_y : photo_y + ph, photo_x : photo_x + pw] = photo

        # NPU section - dark green background tint for Terminator look
        npu_bg_y = c.npu_y + 1
        npu_bg_h = c.height - c.npu_y - 1
        frame[npu_bg_y : npu_bg_y + npu_bg_h, :, 1] = np.maximum(
            frame[npu_bg_y : npu_bg_y + npu_bg_h, :, 1], 17
        )  # Dark green tint

        return frame

    def generate_complete_frame_rgb(
        self,
        t: float,
        frame_num: int,
        attendee: "Attendee",
        attendee_idx: int,
        total_attendees: int,
        tools: list[str],
        findings: list[str],
        assessment: str,
        duration: float,
        attendee_data: dict = None,
        frame_buffer: np.ndarray = None,
        audio_buffer: np.ndarray = None,
    ) -> np.ndarray:
        """
        Generate a complete video frame using OpenCV (2-3x faster than PIL).

        Returns numpy array (H, W, 3) in BGR format for direct YUYV conversion.

        Args:
            t: Time in seconds
            frame_num: Current frame number
            attendee: Current attendee being rendered
            attendee_idx: Index of current attendee
            total_attendees: Total number of attendees
            tools: List of tool strings
            findings: List of finding strings
            assessment: Assessment string
            duration: Total duration for this attendee
            attendee_data: Optional pre-computed attendee data
            frame_buffer: Optional pre-allocated buffer
            audio_buffer: Optional audio FFT bars for reactive waveform
        """
        config = self.config

        # Use pre-allocated buffer or create new one
        if frame_buffer is not None:
            np.copyto(frame_buffer, self._static_cache["base_frame_bgr"])
            frame = frame_buffer
        else:
            frame = self._static_cache["base_frame_bgr"].copy()

        # Get cached layout constants
        padding = self._static_cache["padding"]
        right_col_x = self._static_cache["right_col_x"]
        bottom_section_y = self._static_cache["bottom_section_y"]
        sections_start_y = self._static_cache["sections_start_y"]
        section_height = self._static_cache["section_height"]
        silhouette_x = self._static_cache["silhouette_x"]
        silhouette_y = self._static_cache["silhouette_y"]
        silhouette_h = self._static_cache["silhouette_h"]
        wave_x = self._static_cache["wave_x"]
        wave_y = self._static_cache["wave_y"]
        wave_w = self._static_cache["wave_w"]
        wave_h = self._static_cache["wave_h"]

        # Font settings
        font_small = self._static_cache["font_small"]
        font_medium = self._static_cache["font_medium"]
        thickness = 1

        # Use pre-computed data if available
        if attendee_data:
            realistic_tools = attendee_data["tools"]
        else:
            # Fallback to computing on the fly
            name_parts = attendee.name.split()
            first_name = name_parts[0].lower() if name_parts else "user"
            last_name = name_parts[-1].lower() if len(name_parts) > 1 else first_name
            username = (
                f"{first_name[0]}{last_name}" if len(name_parts) > 1 else first_name
            )
            email_domain = "redhat.com"
            realistic_tools = [
                f"ldap://query?uid={username}",
                f"jira://search?assignee={username}",
                f"gitlab://commits?author={username}@{email_domain}",
                f"slack://history?user={first_name}.{last_name}",
                f"confluence://pages?author={attendee.name.replace(' ', '+')}",
                f"workday://profile/{username}",
                f"google://calendar?email={username}@{email_domain}",
                f"deepface://match?name={attendee.name.replace(' ', '_')}",
            ]

        # === DYNAMIC ELEMENTS (OpenCV) ===

        # Progress counter (changes per attendee)
        cv2.putText(
            frame,
            f"[{attendee_idx + 1}/{total_attendees}]",
            (config.width - 70, 22),
            CV_FONT,
            font_small,
            CV_CYAN,
            thickness,
            CV_LINE_TYPE,
        )

        # Animated dots (changes per frame)
        dots = "." * (int(t * 3) % 4)
        cv2.putText(
            frame,
            f"ANALYZING{dots}",
            (padding, 45),
            CV_FONT,
            font_small,
            CV_GREEN,
            thickness,
            CV_LINE_TYPE,
        )

        # Person name (changes per attendee)
        cv2.putText(
            frame,
            attendee.name,
            (padding, 70),
            CV_FONT,
            font_medium,
            CV_WHITE,
            thickness,
            CV_LINE_TYPE,
        )

        # Tools - appear over time (dynamic)
        y_pos = 100
        for j, tool in enumerate(realistic_tools[: config.num_tools]):
            tool_start = j * config.tool_display_time
            if t >= tool_start:
                cv2.putText(
                    frame,
                    f"> {tool}",
                    (padding, y_pos + j * 20),
                    CV_FONT,
                    font_small,
                    CV_GREEN,
                    thickness,
                    CV_LINE_TYPE,
                )

        # Findings - appear after tools (dynamic)
        findings_start = (
            len(realistic_tools[: config.num_tools]) * config.tool_display_time
        )
        findings_y = y_pos + config.num_tools * 20 + 15
        for j, finding in enumerate(findings):
            finding_start = findings_start + j * 1.0
            if t >= finding_start:
                cv2.putText(
                    frame,
                    finding,
                    (padding, findings_y + j * 20),
                    CV_FONT,
                    font_small,
                    CV_YELLOW,
                    thickness,
                    CV_LINE_TYPE,
                )

        # Assessment at end (dynamic)
        if t >= duration - 2:
            cv2.putText(
                frame,
                assessment,
                (padding, findings_y + len(findings) * 20 + 15),
                CV_FONT,
                font_medium,
                CV_CYAN,
                thickness,
                CV_LINE_TYPE,
            )

        # "PROCESSING..." label below silhouette
        cv2.putText(
            frame,
            "PROCESSING...",
            (silhouette_x + 45, silhouette_y + silhouette_h + 18),
            CV_FONT,
            font_small,
            CV_YELLOW,
            thickness,
            CV_LINE_TYPE,
        )

        # Right column dynamic values
        sections_data = [
            ["VEL: 42", "BLOCK: 3", "EPIC: 7"],
            ["CH: 847", "DM: ON", "KW: 12"],
            ["VEC: 4.2M", "COS: 0.85", "LAT: 12ms"],
            ["MAIL: 12K", "CAL: LIVE", "RISK: MED"],
        ]
        for i, items in enumerate(sections_data):
            sec_y = sections_start_y + i * section_height + 28
            for j, item in enumerate(items):
                cv2.putText(
                    frame,
                    item,
                    (right_col_x + 8, sec_y + j * 14),
                    CV_FONT,
                    font_small,
                    CV_GREEN,
                    thickness,
                    CV_LINE_TYPE,
                )

        # === VOICE PROFILE STATS - Below waveform (dynamic) ===
        voice_stats_y = wave_y + wave_h + 18

        has_audio = audio_buffer is not None

        # Calculate animated stats
        freq_peak = 180 + int(60 * math.sin(t * 0.7))
        formant_f1 = 500 + int(100 * math.sin(t * 0.5))
        formant_f2 = 1500 + int(200 * math.sin(t * 0.3))
        pitch_var = 12 + int(8 * math.sin(t * 0.9))

        # Left stats column
        voice_print_id = (
            attendee_data["voice_print_id"]
            if attendee_data
            else hash(attendee.name) % 99999
        )
        cv2.putText(
            frame,
            f"VOICE PRINT ID: VP-{voice_print_id:05d}",
            (wave_x, voice_stats_y),
            CV_FONT,
            font_small,
            CV_GREEN,
            thickness,
            CV_LINE_TYPE,
        )
        cv2.putText(
            frame,
            f"FREQ PEAK: {freq_peak}Hz",
            (wave_x, voice_stats_y + 14),
            CV_FONT,
            font_small,
            CV_GREEN,
            thickness,
            CV_LINE_TYPE,
        )
        cv2.putText(
            frame,
            f"FORMANT F1: {formant_f1}Hz",
            (wave_x, voice_stats_y + 28),
            CV_FONT,
            font_small,
            CV_GREEN,
            thickness,
            CV_LINE_TYPE,
        )
        cv2.putText(
            frame,
            f"FORMANT F2: {formant_f2}Hz",
            (wave_x, voice_stats_y + 42),
            CV_FONT,
            font_small,
            CV_GREEN,
            thickness,
            CV_LINE_TYPE,
        )

        # Middle stats column
        mid_x = wave_x + 200
        cv2.putText(
            frame,
            f"PITCH VAR: {pitch_var}%",
            (mid_x, voice_stats_y),
            CV_FONT,
            font_small,
            CV_GREEN,
            thickness,
            CV_LINE_TYPE,
        )
        cv2.putText(
            frame,
            f"MFCC VECTORS: {int(t * 12)}",
            (mid_x, voice_stats_y + 14),
            CV_FONT,
            font_small,
            CV_GREEN,
            thickness,
            CV_LINE_TYPE,
        )
        cv2.putText(
            frame,
            "SPEAKER MODEL: BUILDING",
            (mid_x, voice_stats_y + 28),
            CV_FONT,
            font_small,
            CV_YELLOW,
            thickness,
            CV_LINE_TYPE,
        )
        cv2.putText(
            frame,
            f"CONFIDENCE: {min(99, int(t * 6.5))}%",
            (mid_x, voice_stats_y + 42),
            CV_FONT,
            font_small,
            CV_GREEN,
            thickness,
            CV_LINE_TYPE,
        )

        # Right stats column
        right_stats_x = wave_x + 420
        cv2.putText(
            frame,
            f"SAMPLES: {int(t * 16000)}",
            (right_stats_x, voice_stats_y),
            CV_FONT,
            font_small,
            CV_GREEN,
            thickness,
            CV_LINE_TYPE,
        )
        cv2.putText(
            frame,
            f"SNR: {25 + int(5 * math.sin(t))}dB",
            (right_stats_x, voice_stats_y + 14),
            CV_FONT,
            font_small,
            CV_GREEN,
            thickness,
            CV_LINE_TYPE,
        )
        vad_text = "VAD: ACTIVE" if int(t * 3) % 2 == 0 else "VAD: SPEECH"
        cv2.putText(
            frame,
            vad_text,
            (right_stats_x, voice_stats_y + 28),
            CV_FONT,
            font_small,
            CV_GREEN,
            thickness,
            CV_LINE_TYPE,
        )
        profile_color = (
            (0, 255, 0) if t > 10 else CV_GREEN
        )  # Bright green when complete
        cv2.putText(
            frame,
            f"PROFILE: {min(100, int(t * 7))}%",
            (right_stats_x, voice_stats_y + 42),
            CV_FONT,
            font_small,
            profile_color,
            thickness,
            CV_LINE_TYPE,
        )

        # Generate waveform into pre-allocated buffer
        if has_audio:
            wave_arr = self.generate_waveform_frame_from_audio(
                audio_buffer, self._wave_buffer
            )
        else:
            wave_arr = self.generate_waveform_frame(t, self._wave_buffer)

        # Scale waveform using cv2.resize (100x faster than fancy indexing)
        target_h = wave_h - 4
        target_w = wave_w - 4
        scaled_wave = cv2.resize(
            wave_arr, (target_w, target_h), interpolation=cv2.INTER_NEAREST
        )

        # Paste waveform
        frame[
            wave_y + 2 : wave_y + 2 + target_h, wave_x + 2 : wave_x + 2 + target_w
        ] = scaled_wave

        # Generate NPU panel into pre-allocated buffer
        npu_arr = self.generate_npu_frame(t, frame_num, self._npu_buffer)

        # Paste NPU panel at bottom
        npu_y = bottom_section_y
        available_height = config.height - npu_y
        paste_height = min(self.npu_height, available_height)
        frame[npu_y : npu_y + paste_height, 0 : self.npu_width] = npu_arr[:paste_height]

        # Return numpy array for direct YUYV conversion
        return frame
