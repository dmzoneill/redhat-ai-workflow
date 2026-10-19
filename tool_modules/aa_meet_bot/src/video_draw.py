"""Static cache, FFT, waveform, and NPU panel drawing."""

import logging
import math

import cv2
import numpy as np

from tool_modules.aa_meet_bot.src.dynamic_fields import DynamicFields
from tool_modules.aa_meet_bot.src.video_theme import (
    CV_CYAN,
    CV_DARK_GREEN,
    CV_GREEN,
    CV_RED,
    draw_text,
)

logger = logging.getLogger(__name__)


class RealtimeDrawMixin(DynamicFields):  # pylint: disable=too-few-public-methods
    """Private drawing helpers for RealtimeVideoRenderer.

    ``too-few-public-methods`` is disabled because every helper is private.
    The public render API stays on RealtimeVideoRenderer.
    """

    # Live flow kept together after the duplicate copy was removed.
    # pylint: disable-next=too-many-locals,too-many-statements
    def _init_static_cache(self):
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
        draw_text(
            base_frame,
            "[ AI RESEARCH MODULE v2.1 ]",
            (padding, 22),
            (font_medium, CV_CYAN, thickness),
        )

        # Right column vertical divider
        cv2.line(
            base_frame, (right_col_x, 50), (right_col_x, bottom_section_y), CV_GREEN, 2
        )

        # "Building Context" heading
        draw_text(
            base_frame,
            "BUILDING CONTEXT",
            (right_col_x + 8, 68),
            (font_small, CV_RED, thickness),
        )

        # Section headers (static)
        sections_start_y = 75
        section_height = (bottom_section_y - sections_start_y) // 4
        section_headers = ["[ JIRA ]", "[ SLACK ]", "[ SEMANTIC ]", "[ COMMS ]"]
        for i, header in enumerate(section_headers):
            sec_y = sections_start_y + i * section_height + 12
            draw_text(
                base_frame,
                header,
                (right_col_x + 8, sec_y),
                (font_small, CV_CYAN, thickness),
            )

        # Facial recognition box and label
        silhouette_w = 180
        silhouette_h = 200
        silhouette_x = right_col_x - silhouette_w - 20
        silhouette_y = 55
        draw_text(
            base_frame,
            "FACIAL RECOGNITION",
            (silhouette_x + 20, silhouette_y - 5),
            (font_small, CV_RED, thickness),
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
        draw_text(
            base_frame,
            "ANALYZING SPEECH PATTERNS",
            (wave_x + wave_w - 265, config.assessment_y),
            (font_small, CV_CYAN, thickness),
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

        # Pre-allocate waveform and NPU buffers
        self.__dict__["_wave_buffer"] = np.zeros(
            (self.wave_height, self.wave_width, 3), dtype=np.uint8
        )
        self.__dict__["_npu_buffer"] = np.zeros(
            (self.npu_height, self.npu_width, 3), dtype=np.uint8
        )

        # Pre-allocate FFT computation buffers to avoid per-frame allocations
        self.__dict__["_fft_bar_heights"] = np.zeros(self.wave_bars, dtype=np.float32)
        self.__dict__["_fft_silence_bars"] = np.full(
            self.wave_bars, 0.12, dtype=np.float32
        )
        self.__dict__["_fft_hanning"] = (
            None  # Will be created on first use with correct size
        )

        logger.debug("Static element cache initialized (OpenCV)")

    def _compute_fft_bars(self, audio: np.ndarray) -> np.ndarray:
        """Compute FFT and convert to bar heights for visualization.

        Includes noise gate: when audio RMS is below threshold, returns
        minimal bars to indicate silence/muted mic.
        """
        # Noise gate: check if audio is essentially silent
        rms = np.sqrt(np.mean(audio**2))
        noise_threshold = 0.005  # Below this RMS, consider it silence/muted

        if rms < noise_threshold:
            # Return minimal flat bars for silence (reuse pre-allocated buffer)
            np.copyto(self.__dict__["_fft_bar_heights"], self._fft_silence_bars)
            # Add small random variation in-place
            self.__dict__["_fft_bar_heights"] += np.random.uniform(
                -0.02, 0.02, self.wave_bars
            )
            np.clip(
                self.__dict__["_fft_bar_heights"],
                0.1,
                0.15,
                out=self.__dict__["_fft_bar_heights"],
            )
            if self._prev_fft_bars is None:
                self.__dict__["_prev_fft_bars"] = self.__dict__[
                    "_fft_bar_heights"
                ].copy()
            else:
                np.copyto(self._prev_fft_bars, self.__dict__["_fft_bar_heights"])
            return self.__dict__["_fft_bar_heights"]

        # Create/reuse hanning window (only allocate once per audio size)
        if self._fft_hanning is None or len(self._fft_hanning) != len(audio):
            self.__dict__["_fft_hanning"] = np.hanning(len(audio)).astype(np.float32)

        # Apply window function to reduce spectral leakage (in-place multiply)
        windowed = audio * self._fft_hanning

        # Compute FFT
        fft = np.abs(np.fft.rfft(windowed))

        # We only care about frequencies up to ~8kHz (half of 16kHz sample rate)
        n_fft_bins = len(fft)

        # Use logarithmic frequency scaling - write directly to pre-allocated buffer
        self.__dict__["_fft_bar_heights"].fill(0)

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
                self.__dict__["_fft_bar_heights"][i] = np.mean(fft[low_freq:high_freq])

        # Normalize to 0-1 range with some headroom (in-place)
        max_val = np.max(self.__dict__["_fft_bar_heights"])
        if max_val > 0:
            self.__dict__["_fft_bar_heights"] /= max_val

        # Scale by RMS (in-place)
        rms_scale = min(1.0, (rms / 0.02) * 3.0)
        self.__dict__["_fft_bar_heights"] *= rms_scale

        # Apply smoothing with previous frame (in-place)
        if self._prev_fft_bars is not None:
            self.__dict__["_fft_bar_heights"] *= 0.7
            self.__dict__["_fft_bar_heights"] += 0.3 * self._prev_fft_bars

        # Update prev_fft_bars
        if self._prev_fft_bars is None:
            self.__dict__["_prev_fft_bars"] = self.__dict__["_fft_bar_heights"].copy()
        else:
            np.copyto(self._prev_fft_bars, self.__dict__["_fft_bar_heights"])

        # Apply final scaling (in-place)
        self.__dict__["_fft_bar_heights"] *= 0.64
        self.__dict__["_fft_bar_heights"] += 0.15

        return self.__dict__["_fft_bar_heights"]

    def _generate_waveform_frame_from_audio(
        self, bar_heights: np.ndarray, out: np.ndarray | None = None
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
        # bar_heights are now floats 0.1-1.0, convert to pixels
        # Replace NaN/inf with default value to avoid cast warnings
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

    # Live flow kept together after the duplicate copy was removed.
    # pylint: disable-next=too-many-locals
    def _generate_waveform_frame(
        self, t: float, out: np.ndarray | None = None
    ) -> np.ndarray:
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

    # Live flow kept together after the duplicate copy was removed.
    # pylint: disable-next=too-many-locals
    def _generate_npu_frame(
        self, t: float, frame_num: int, out: np.ndarray | None = None
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
        draw_text(
            frame,
            "[ INTEL NPU - METEOR LAKE ]",
            (15, 18),
            (font_small, CV_CYAN, thickness),
        )

        y = 35
        line_h = 16

        # Column 1 - NPU stats
        stats1 = [
            "FREQ: 1400 MHz",
            f"BUSY: {t * 1.2 + 17.99:.1f}s",
            "MEM: 65.5 MB",
            f"UTIL: {40 + int(30 * math.sin(t * 0.4))}%",
            f"TEMP: {45 + int(10 * math.sin(t * 0.2))}C",
        ]
        for i, s in enumerate(stats1):
            draw_text(frame, s, (15, y + i * line_h), (font_small, CV_GREEN, thickness))

        # Column 2 - Model info
        stats2 = [
            "MODEL: whisper-int8",
            "PRECISION: INT8",
            "INPUT: 16kHz PCM",
            "TILES: 2/2",
            "CACHE: ENABLED",
        ]
        for i, s in enumerate(stats2):
            draw_text(
                frame, s, (180, y + i * line_h), (font_small, CV_GREEN, thickness)
            )

        # Column 3 - Counters
        stats3 = [
            f"SAMPLES: {int(t * 16000)}",
            f"INFERENCES: {int(t * 18)}",
            f"TOKENS: {int(t * 45)}",
            f"FRAMES: {frame_num}",
            f"TIME: {int(t) // 60:02d}:{int(t) % 60:02d}.{int((t % 1) * 100):02d}",
        ]
        for i, s in enumerate(stats3):
            draw_text(
                frame, s, (380, y + i * line_h), (font_small, CV_GREEN, thickness)
            )

        # Column 4 - System stats
        stats4 = [
            f"CPU: {15 + int(10 * math.sin(t * 0.5))}%",
            f"MEM: {65 + int(5 * math.sin(t * 0.3))} MB",
            f"QUEUE: {int((t * 3) % 5)}",
            f"LATENCY: {25 + int(8 * math.sin(t * 2))}ms",
            "STATUS: ACTIVE",
        ]
        for i, s in enumerate(stats4):
            color = CV_CYAN if i == 4 else CV_GREEN
            draw_text(frame, s, (560, y + i * line_h), (font_small, color, thickness))

        # Column 5 - Additional telemetry
        stats5 = [
            f"RATE: {15 + int(10 * math.sin(t * 0.5))} req/s",
            f"THROUGHPUT: {0.8 + 0.4 * math.sin(t * 0.3):.2f} TOPS",
            f"POWER: {4.2 + 0.8 * math.sin(t * 0.2):.1f}W",
            "DMA: ACTIVE",
            f"IRQ: {146 + int(t) % 10}",
        ]
        for i, s in enumerate(stats5):
            draw_text(
                frame, s, (740, y + i * line_h), (font_small, CV_GREEN, thickness)
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
            draw_text(frame, s, (920, y + i * line_h), (font_small, color, thickness))

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
        draw_text(
            frame,
            f"PROCESSING: {int((t % 15) / 15 * 100)}%",
            (self.npu_width - padding - 130, bar_y + 10),
            (font_small, CV_GREEN, thickness),
        )

        # Return BGR array directly (caller expects BGR for OpenCV compatibility)
        return frame
