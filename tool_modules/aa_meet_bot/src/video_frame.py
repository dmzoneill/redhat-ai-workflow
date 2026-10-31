"""Per-attendee base frames and the full RGB composite."""

import logging
import math
import secrets
from pathlib import Path

import cv2
import numpy as np

from tool_modules.aa_meet_bot.src.dynamic_fields import DynamicFields
from tool_modules.aa_meet_bot.src.video_config import Attendee
from tool_modules.aa_meet_bot.src.video_theme import (
    CV_CYAN,
    CV_GREEN,
    CV_WHITE,
    CV_YELLOW,
    draw_text,
)

logger = logging.getLogger(__name__)

# Non-cryptographic jitter/variety; SystemRandom avoids the predictable Mersenne Twister flagged by scanners
_RNG = secrets.SystemRandom()


class RealtimeFrameMixin(DynamicFields):  # pylint: disable=too-few-public-methods
    """Private frame-composition helpers for RealtimeVideoRenderer.

    ``too-few-public-methods`` is disabled because every helper is private.
    """

    # Live flow kept together after the duplicate copy was removed.
    # pylint: disable-next=too-many-locals
    def _append_profile_items(self, text_items, c, transcript_history, attendee_data):
        """Helper extracted from the live renderer."""
        # === LIVE TRANSCRIPTION STACK (below waveform box) ===
        # Show most recent transcriptions, newest at top
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
                text_items.append((f"> {display_text}", c.wave_x, y, color, "medium"))  # +6pt

        # === VOICE PROFILE ANALYSIS - LEFT of facial recognition (top right area) ===
        voice_x = c.voice_profile_x
        voice_y = c.voice_profile_y
        text_items.append(("VOICE PROFILE ANALYSIS", voice_x, voice_y, "green", "large"))  # doubled size

        stats = [
            f"Voice Print ID: {attendee_data['voice_print_id']:05d}",
            "",
            f"Freq: 125-4000 Hz | Pitch: {_RNG.randint(150, 220)} Hz",
            f"Cadence: {_RNG.randint(120, 160)} wpm | Conf: {_RNG.uniform(90, 99):.1f}%",
        ]
        for i, stat in enumerate(stats):
            if stat:  # Skip empty lines
                text_items.append(
                    (stat, voice_x, voice_y + 45 + i * 40, "orange", "medium")
                )  # doubled size + line height

        # === FACIAL RECOGNITION - TOP RIGHT === (+10pt bigger text)
        text_items.append(("FACIAL RECOGNITION", c.face_x, c.face_y - 10, "red", "large"))

        # Show Slack username below the profile image
        if attendee_data and attendee_data.get("has_slack_data"):
            slack_name = attendee_data.get("slack_display_name", "")
            slack_id = attendee_data.get("slack_id", "")
            # Position below the face box
            slack_info_y = c.face_y + c.face_h + 25
            text_items.append((f"@{slack_name}", c.face_x, slack_info_y, "cyan", "medium"))
            text_items.append((f"[{slack_id}]", c.face_x, slack_info_y + 25, "dark_green", "normal"))

        # === RIGHT COLUMN REMOVED - no more "BUILDING CONTEXT" ===

    def _cyan_if_active(self, line: str) -> str:
        """Pick cyan when a stat line reports an active state."""
        return "cyan" if "ACTIVE" in line else "green"

    def _add_lines(self, text_items, lines, layout, color):
        """Append a vertical stack of text items.

        ``layout`` is ``(x, y, line_height, size)``.
        """
        origin_x, origin_y, step, size = layout
        for index, line in enumerate(lines):
            if not line:
                continue
            paint = color(line) if callable(color) else color
            text_items.append((line, origin_x, origin_y + index * step, paint, size))

    # Live flow kept together after the duplicate copy was removed.
    # pylint: disable-next=too-many-locals
    def _append_npu_items(self, text_items, c, frame_num):
        """Helper extracted from the live renderer."""
        # === NPU STATS (all GPU-rendered for consistent quality) ===
        # LARGER FONT - moved up to give more vertical space
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

        # NPU stats layout - LARGE font for readability
        npu_stats_y = c.npu_y + 55  # More space after header
        npu_line_h = 38 if c.height >= 1080 else 28  # EVEN LARGER line height
        npu_size = "large"  # GPU text size for NPU stats - DOUBLED from normal

        # Column positions (proportional to width) - 6 columns spread across full width
        # Adjusted: col 1 +50px wider, all others shifted right
        col_x = [
            int(c.width * 0.02),  # Column 1 - FREQ/BUSY/MEM
            int(c.width * 0.17),  # Column 2 - UTIL/POWER/RUNTIME (+50px / ~0.03)
            int(c.width * 0.33),  # Column 3 - MODEL
            int(c.width * 0.53),  # Column 4 - SAMPLES/INFERENCES/FRAMES
            int(c.width * 0.69),  # Column 5 - CPU/GPU/STT
            int(c.width * 0.84),  # Column 6 - RATE/LATENCY/STATUS
        ]

        # Get real NPU stats from cached values (updated every 0.5s by background task)
        npu = self._npu_stats
        busy_sec = npu["busy_us"] / 1_000_000
        mem_mb = npu["mem_bytes"] / (1024 * 1024)
        # Calculate utilization from delta (busy_delta over 500ms = busy_delta/500000 * 100%)
        util_pct = min(100, int(npu["busy_delta_us"] / 5000)) if npu["busy_delta_us"] > 0 else 0
        runtime_status = npu["runtime_status"].upper()

        # Distribute stats across 6 columns (fewer items per column = larger text fits)
        # Column 1 - NPU core stats
        stt = self._stt_stats
        rtf_display = f"{stt['avg_rtf']:.2f}" if stt["avg_rt"] > 0 else "---"
        latency_display = f"{stt['avg_latency_ms']:.0f}ms" if stt["avg_latency_ms"] > 0 else "---"
        rate_display = f"{stt['inferences_per_second']:.1f}/s" if stt["inferences_per_second"] > 0 else "---"
        active = self._cyan_if_active
        self._add_lines(
            text_items,
            [
                f"FREQ: {npu['freq_mhz']}/{npu['max_freq_mhz']} MHz",
                f"BUSY: {busy_sec:.2f}s",
                f"MEM: {mem_mb:.1f} MB",
            ],
            (col_x[0], npu_stats_y, npu_line_h, npu_size),
            "green",
        )
        self._add_lines(
            text_items,
            [
                f"UTIL: {util_pct}%",
                f"POWER: {npu['power_state']}",
                f"RUNTIME: {runtime_status}",
            ],
            (col_x[1], npu_stats_y, npu_line_h, npu_size),
            active,
        )
        self._add_lines(
            text_items,
            ["MODEL: whisper-base", "PRECISION: FP16", "INPUT: 16kHz PCM"],
            (col_x[2], npu_stats_y, npu_line_h, npu_size),
            "green",
        )
        self._add_lines(
            text_items,
            [
                f"SAMPLES: {stt['samples_processed']}",
                f"INFERENCES: {stt['inference_count']}",
                f"FRAMES: {frame_num}",
            ],
            (col_x[3], npu_stats_y, npu_line_h, npu_size),
            "green",
        )
        self._add_lines(
            text_items,
            [
                f"RTF: {rtf_display}",
                f"DEVICE: {stt.get('device', 'NPU')[:8]}",
                f"STT: {'ON' if self._stt_enabled else 'OFF'}",
            ],
            (col_x[4], npu_stats_y, npu_line_h, npu_size),
            lambda line: "cyan" if "ON" in line or stt["avg_rt"] < 0.5 else "green",
        )
        self._add_lines(
            text_items,
            [
                f"RATE: {rate_display}",
                f"LATENCY: {latency_display}",
                f"STATUS: {runtime_status}",
            ],
            (col_x[5], npu_stats_y, npu_line_h, npu_size),
            active,
        )

    # Live flow kept together after the duplicate copy was removed.
    # pylint: disable-next=too-many-locals
    def _paint_base_frame(self, text_items, c, attendee_data):
        """Render shapes, photo, and the NPU tint."""
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
            shapes.append(("rect", c.face_x, c.face_y, c.face_w, c.face_h, "dark_green", 1))
            # Silhouette - sized to match typical photo dimensions
            center_x = c.face_x + c.face_w // 2
            # Make silhouette fit typical photo size (roughly 200x200 centered)
            silhouette_size = 180  # Typical photo is around this size
            head_radius = silhouette_size // 3  # Head is ~1/3 of total height
            center_y = c.face_y + 25 + head_radius + 10  # Below header
            body_width = head_radius  # Body width matches head
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
        # (This is a pixel operation, keep it in numpy for now)
        npu_bg_y = c.npu_y + 1
        npu_bg_h = c.height - c.npu_y - 1
        frame[npu_bg_y : npu_bg_y + npu_bg_h, :, 1] = np.maximum(
            frame[npu_bg_y : npu_bg_y + npu_bg_h, :, 1], 17
        )  # Dark green tint

        return frame

    # Live flow kept together after the duplicate copy was removed.
    # pylint: disable-next=too-many-locals,too-many-arguments,too-many-positional-arguments
    def _create_base_frame(
        self,
        attendee: Attendee,
        _attendee_idx: int,
        _total_attendees: int,
        tools: list,
        findings: list,
        _assessment: str,
        attendee_data: dict,
        t: float = 0.0,
        frame_num: int = 0,
        transcript_history: list | None = None,
    ) -> np.ndarray:
        """
        Create base frame using full GPU pipeline (OpenGL text + shapes).

        All text and shapes are rendered via OpenGL for smooth anti-aliased output.
        Dynamic NPU stats are included and update each second.

        Args:
            t: Time in seconds (for dynamic NPU stats and animations)
            frame_num: Current frame number
            transcript_history: List of recent transcriptions (most recent first)
        """
        transcript_history = transcript_history or []
        if not self._gpu_text_renderer:
            raise RuntimeError("GPU text renderer not initialized - required for video generation")

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

        # Assessment - REMOVED per user request
        # text_items.append((assessment, c.left_margin, c.assessment_y, "yellow", "normal"))

        # === WAVEFORM LABEL - above the waveform box, left aligned ===
        text_items.append(("ANALYZING SPEECH PATTERNS", c.wave_x, c.wave_y - 15, "cyan", "medium"))  # +6pt

        self._append_profile_items(text_items, c, transcript_history, attendee_data)

        self._append_npu_items(text_items, c, frame_num)

        base_frame: np.ndarray = self._paint_base_frame(text_items, c, attendee_data)
        return base_frame

    # Live flow kept together after the duplicate copy was removed.
    # pylint: disable-next=too-many-locals
    def _precompute_attendee_data(self, attendee: Attendee) -> dict:
        """Pre-compute attendee-specific data to avoid per-frame string operations.

        Includes real Slack data if available from the attendee object.
        Also loads and resizes the profile photo if available.
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
                    photo_bgr = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
                    logger.debug(
                        "Loaded photo for %s: %s -> %sx%s",
                        attendee.name,
                        photo_path,
                        new_w,
                        new_h,
                    )
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("Failed to load photo %s: %s", photo_path, e, exc_info=True)

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
                (f"slack://user/{slack_id}" if attendee.slack_id else f"slack://search?user={first_name}.{last_name}"),
                f"ldaps://query?uid={username}",
                f"jira://search?assignee={username}",
                f"gitlab://commits?author={email}",
                f"confluence://pages?author={attendee.name.replace(' ', '+')}",
                f"workday://profile/{username}",
                f"google://calendar?email={email}",
                f"deepface://match?name={attendee.name.replace(' ', '_')}",
            ],
        }

    # Live flow kept together after the duplicate copy was removed.
    # pylint: disable-next=too-many-locals
    def _draw_voice_and_panels(self, frame, t, frame_num, attendee, attendee_data):
        """Draw voice stats, the waveform, and the NPU strip."""
        config = self.config
        cache = self._static_cache
        font_small = cache["font_small"]
        thickness = 1
        wave_x = cache["wave_x"]
        wave_y = cache["wave_y"]
        wave_w = cache["wave_w"]
        wave_h = cache["wave_h"]
        bottom_section_y = cache["bottom_section_y"]
        # === VOICE PROFILE STATS - Below waveform (dynamic) ===
        voice_stats_y = wave_y + wave_h + 18

        audio_data = self._audio_buffer
        has_audio = audio_data is not None

        # Calculate animated stats
        freq_peak = 180 + int(60 * math.sin(t * 0.7))
        formant_f1 = 500 + int(100 * math.sin(t * 0.5))
        formant_f2 = 1500 + int(200 * math.sin(t * 0.3))
        pitch_var = 12 + int(8 * math.sin(t * 0.9))

        # Left stats column
        voice_print_id = attendee_data["voice_print_id"] if attendee_data else hash(attendee.name) % 99999
        draw_text(
            frame,
            f"VOICE PRINT ID: VP-{voice_print_id:05d}",
            (wave_x, voice_stats_y),
            (font_small, CV_GREEN, thickness),
        )
        draw_text(
            frame,
            f"FREQ PEAK: {freq_peak}Hz",
            (wave_x, voice_stats_y + 14),
            (font_small, CV_GREEN, thickness),
        )
        draw_text(
            frame,
            f"FORMANT F1: {formant_f1}Hz",
            (wave_x, voice_stats_y + 28),
            (font_small, CV_GREEN, thickness),
        )
        draw_text(
            frame,
            f"FORMANT F2: {formant_f2}Hz",
            (wave_x, voice_stats_y + 42),
            (font_small, CV_GREEN, thickness),
        )

        # Middle stats column
        mid_x = wave_x + 200
        draw_text(
            frame,
            f"PITCH VAR: {pitch_var}%",
            (mid_x, voice_stats_y),
            (font_small, CV_GREEN, thickness),
        )
        draw_text(
            frame,
            f"MFCC VECTORS: {int(t * 12)}",
            (mid_x, voice_stats_y + 14),
            (font_small, CV_GREEN, thickness),
        )
        draw_text(
            frame,
            "SPEAKER MODEL: BUILDING",
            (mid_x, voice_stats_y + 28),
            (font_small, CV_YELLOW, thickness),
        )
        draw_text(
            frame,
            f"CONFIDENCE: {min(99, int(t * 6.5))}%",
            (mid_x, voice_stats_y + 42),
            (font_small, CV_GREEN, thickness),
        )

        # Right stats column
        right_stats_x = wave_x + 420
        draw_text(
            frame,
            f"SAMPLES: {int(t * 16000)}",
            (right_stats_x, voice_stats_y),
            (font_small, CV_GREEN, thickness),
        )
        draw_text(
            frame,
            f"SNR: {25 + int(5 * math.sin(t))}dB",
            (right_stats_x, voice_stats_y + 14),
            (font_small, CV_GREEN, thickness),
        )
        vad_text = "VAD: ACTIVE" if int(t * 3) % 2 == 0 else "VAD: SPEECH"
        draw_text(
            frame,
            vad_text,
            (right_stats_x, voice_stats_y + 28),
            (font_small, CV_GREEN, thickness),
        )
        profile_color = (0, 255, 0) if t > 10 else CV_GREEN  # Bright green when complete
        draw_text(
            frame,
            f"PROFILE: {min(100, int(t * 7))}%",
            (right_stats_x, voice_stats_y + 42),
            (font_small, profile_color, thickness),
        )

        # Generate waveform into pre-allocated buffer
        if has_audio:
            wave_arr = self._generate_waveform_frame_from_audio(audio_data, self._wave_buffer)
        else:
            wave_arr = self._generate_waveform_frame(t, self._wave_buffer)

        # Scale waveform using cv2.resize (100x faster than fancy indexing)
        target_h = wave_h - 4
        target_w = wave_w - 4
        scaled_wave = cv2.resize(wave_arr, (target_w, target_h), interpolation=cv2.INTER_NEAREST)

        # Paste waveform
        frame[wave_y + 2 : wave_y + 2 + target_h, wave_x + 2 : wave_x + 2 + target_w] = scaled_wave

        # Generate NPU panel into pre-allocated buffer
        npu_arr = self._generate_npu_frame(t, frame_num, self._npu_buffer)

        # Paste NPU panel at bottom
        npu_y = bottom_section_y
        available_height = config.height - npu_y
        paste_height = min(self.npu_height, available_height)
        frame[npu_y : npu_y + paste_height, 0 : self.npu_width] = npu_arr[:paste_height]

        # Return numpy array for direct YUYV conversion
        return frame

    # Live flow kept together after the duplicate copy was removed.
    # pylint: disable-next=too-many-locals,too-many-arguments,too-many-positional-arguments
    def _draw_dynamic_labels(
        self,
        frame,
        t,
        attendee,
        attendee_idx,
        total_attendees,
        _tools,
        findings,
        assessment,
        duration,
        realistic_tools,
    ):
        """Draw the changing OpenCV labels."""
        config = self.config
        cache = self._static_cache
        font_small = cache["font_small"]
        font_medium = cache["font_medium"]
        thickness = 1
        padding = cache["padding"]
        right_col_x = cache["right_col_x"]
        sections_start_y = cache["sections_start_y"]
        section_height = cache["section_height"]
        silhouette_x = cache["silhouette_x"]
        silhouette_y = cache["silhouette_y"]
        silhouette_h = cache["silhouette_h"]
        # === DYNAMIC ELEMENTS (OpenCV) ===

        # Progress counter (changes per attendee)
        draw_text(
            frame,
            f"[{attendee_idx + 1}/{total_attendees}]",
            (config.width - 70, 22),
            (font_small, CV_CYAN, thickness),
        )

        # Animated dots (changes per frame)
        dots = "." * (int(t * 3) % 4)
        draw_text(frame, f"ANALYZING{dots}", (padding, 45), (font_small, CV_GREEN, thickness))

        # Person name (changes per attendee)
        draw_text(frame, attendee.name, (padding, 70), (font_medium, CV_WHITE, thickness))

        # Tools - appear over time (dynamic)
        y_pos = 100
        for j, tool in enumerate(realistic_tools[: config.num_tools]):
            tool_start = j * config.tool_display_time
            if t >= tool_start:
                draw_text(
                    frame,
                    f"> {tool}",
                    (padding, y_pos + j * 20),
                    (font_small, CV_GREEN, thickness),
                )

        # Findings - appear after tools (dynamic)
        findings_start = len(realistic_tools[: config.num_tools]) * config.tool_display_time
        findings_y = y_pos + config.num_tools * 20 + 15
        for j, finding in enumerate(findings):
            finding_start = findings_start + j * 1.0
            if t >= finding_start:
                draw_text(
                    frame,
                    finding,
                    (padding, findings_y + j * 20),
                    (font_small, CV_YELLOW, thickness),
                )

        # Assessment at end (dynamic)
        if t >= duration - 2:
            draw_text(
                frame,
                assessment,
                (padding, findings_y + len(findings) * 20 + 15),
                (font_medium, CV_CYAN, thickness),
            )

        # "PROCESSING..." label below silhouette
        draw_text(
            frame,
            "PROCESSING...",
            (silhouette_x + 45, silhouette_y + silhouette_h + 18),
            (font_small, CV_YELLOW, thickness),
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
                draw_text(
                    frame,
                    item,
                    (right_col_x + 8, sec_y + j * 14),
                    (font_small, CV_GREEN, thickness),
                )

    # pylint: disable-next=too-many-arguments,too-many-positional-arguments
    def _generate_complete_frame_rgb(
        self,
        t: float,
        frame_num: int,
        attendee: Attendee,
        attendee_idx: int,
        total_attendees: int,
        tools: list[str],
        findings: list[str],
        assessment: str,
        duration: float,
        attendee_data: dict | None = None,
        frame_buffer: np.ndarray | None = None,
    ) -> np.ndarray:
        """
        Generate a complete video frame using OpenCV (2-3x faster than PIL).

        Returns numpy array (H, W, 3) in BGR format for direct YUYV conversion.

        Args:
            frame_buffer: Optional pre-allocated buffer. If provided, copies base
                         frame into it instead of allocating new array.
        """
        if frame_buffer is not None:
            np.copyto(frame_buffer, self._static_cache["base_frame_bgr"])
            frame = frame_buffer
        else:
            frame = self._static_cache["base_frame_bgr"].copy()

        realistic_tools = self._realistic_tools(attendee, attendee_data)
        self._draw_dynamic_labels(
            frame,
            t,
            attendee,
            attendee_idx,
            total_attendees,
            tools,
            findings,
            assessment,
            duration,
            realistic_tools,
        )
        complete: np.ndarray = self._draw_voice_and_panels(frame, t, frame_num, attendee, attendee_data)
        return complete

    def _realistic_tools(self, attendee, attendee_data):
        """Return tool URLs from enrichment data or a stable fallback."""
        if attendee_data:
            return attendee_data["tools"]
        name_parts = attendee.name.split()
        first_name = name_parts[0].lower() if name_parts else "user"
        last_name = name_parts[-1].lower() if len(name_parts) > 1 else first_name
        username = f"{first_name[0]}{last_name}" if len(name_parts) > 1 else first_name
        email_domain = "redhat.com"
        return [
            f"ldaps://query?uid={username}",
            f"jira://search?assignee={username}",
            f"gitlab://commits?author={username}@{email_domain}",
            f"slack://history?user={first_name}.{last_name}",
            f"confluence://pages?author={attendee.name.replace(' ', '+')}",
            f"workday://profile/{username}",
            f"google://calendar?email={username}@{email_domain}",
            f"deepface://match?name={attendee.name.replace(' ', '_')}",
        ]

    def _build_base_filters(
        self,
        _attendee: Attendee,
        _attendee_idx: int,
        _total_attendees: int,
        _duration: float,
    ) -> list[str]:
        """Build FFmpeg filter list for base elements (used in hybrid mode)."""
        filters = []

        # Header
        filters.append("drawtext=text='[ AI RESEARCH MODULE v2.1 ]':fontsize=32:fontcolor=cyan:x=30:y=15")

        return filters
