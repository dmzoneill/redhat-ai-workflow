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

import asyncio
import gc
import logging
import math
import random
import resource
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)


def get_memory_mb() -> float:
    """Get current process memory usage in MB."""
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_maxrss / 1024  # Convert KB to MB on Linux


_last_gc_time = 0.0


def maybe_gc(force: bool = False) -> None:
    """Run garbage collection periodically (every 30s) or if forced."""
    global _last_gc_time
    import time

    now = time.time()
    if force or (now - _last_gc_time > 30.0):
        gc.collect()
        _last_gc_time = now


# Live meeting data integration
_attendee_client_available = False
try:
    from .attendee_service import AttendeeDataClient, EnrichedAttendee, MeetingState
    from .avatar_generator import generate_initials_avatar, load_or_generate_avatar
    from .matrix_animation import MatrixAnimation

    _attendee_client_available = True
except ImportError:
    logger.debug("Live attendee client not available")

# Optional GPU text rendering (smooth anti-aliased TrueType fonts)
_gpu_text_available = False
try:
    from .gpu_text import VideoTextRenderer

    _gpu_text_available = True
except ImportError:
    logger.debug("GPU text rendering not available (install PyOpenGL freetype-py glfw)")

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

# Pre-compute RGB to YUV conversion matrices (BT.601)
# These are used for fast vectorized color conversion
_RGB_TO_Y = np.array([66, 129, 25], dtype=np.int16)
_RGB_TO_U = np.array([-38, -74, 112], dtype=np.int16)
_RGB_TO_V = np.array([112, -94, -18], dtype=np.int16)


def rgb_to_yuyv_fast(rgb: np.ndarray) -> np.ndarray:
    """
    Convert RGB numpy array to YUYV422 format using vectorized operations.

    This is ~2x faster than FFmpeg's software conversion and eliminates
    the need for a separate FFmpeg process.

    Args:
        rgb: numpy array of shape (H, W, 3) with dtype uint8

    Returns:
        numpy array of shape (H, W*2) with dtype uint8 in YUYV format
    """
    # Convert to int16 for math operations
    r = rgb[:, :, 0].astype(np.int16)
    g = rgb[:, :, 1].astype(np.int16)
    b = rgb[:, :, 2].astype(np.int16)

    # BT.601 conversion (scaled by 256 for integer math)
    y = ((66 * r + 129 * g + 25 * b + 128) >> 8) + 16
    u = ((-38 * r - 74 * g + 112 * b + 128) >> 8) + 128
    v = ((112 * r - 94 * g - 18 * b + 128) >> 8) + 128

    # Clip to valid ranges
    y = np.clip(y, 16, 235).astype(np.uint8)
    u = np.clip(u, 16, 240).astype(np.uint8)
    v = np.clip(v, 16, 240).astype(np.uint8)

    # Pack into YUYV format: Y0 U0 Y1 V0 (4 bytes per 2 horizontal pixels)
    h, w = rgb.shape[:2]
    yuyv = np.zeros((h, w * 2), dtype=np.uint8)
    yuyv[:, 0::4] = y[:, 0::2]  # Y0 (even pixels)
    yuyv[:, 1::4] = u[:, 0::2]  # U (subsampled from even pixels)
    yuyv[:, 2::4] = y[:, 1::2]  # Y1 (odd pixels)
    yuyv[:, 3::4] = v[:, 0::2]  # V (subsampled from even pixels)

    return yuyv


def bgr_to_yuyv_fast(bgr: np.ndarray, yuyv_out: np.ndarray = None) -> np.ndarray:
    """
    Convert BGR numpy array to YUYV422 format using OpenCV.

    Uses OpenCV's hardware-optimized cvtColor for YUV conversion,
    then packs into YUYV format using 4D view for faster indexing.

    Args:
        bgr: numpy array of shape (H, W, 3) with dtype uint8 in BGR format
        yuyv_out: Optional pre-allocated output buffer (H, W*2). If provided,
                  avoids allocation overhead.

    Returns:
        numpy array of shape (H, W*2) with dtype uint8 in YUYV format
    """
    # Use OpenCV's optimized BGR->YUV conversion
    yuv = cv2.cvtColor(bgr, cv2.COLOR_BGR2YUV)

    h, w = bgr.shape[:2]

    # Use pre-allocated buffer or create new one
    if yuyv_out is None:
        yuyv_out = np.empty((h, w * 2), dtype=np.uint8)

    # Use 4D view for faster packing (avoids stride calculations)
    yuyv_4d = yuyv_out.reshape(h, w // 2, 4)
    yuyv_4d[:, :, 0] = yuv[:, 0::2, 0]  # Y0 (even pixels)
    yuyv_4d[:, :, 1] = yuv[:, 0::2, 1]  # U (subsampled)
    yuyv_4d[:, :, 2] = yuv[:, 1::2, 0]  # Y1 (odd pixels)
    yuyv_4d[:, :, 3] = yuv[:, 0::2, 2]  # V (subsampled)

    return yuyv_out


class GPUColorConverter:
    """
    OpenCL-based BGR to YUYV converter using iGPU or NVIDIA GPU.

    Reduces CPU usage from ~12% to ~2% for color conversion.
    """

    _KERNEL_SRC = """
    __kernel void bgr_to_yuyv(
        __global const uchar* bgr,
        __global uchar* yuyv,
        const int width,
        const int height
    ) {
        int x = get_global_id(0) * 2;  // Process 2 pixels at a time
        int y = get_global_id(1);

        if (x >= width || y >= height) return;

        // Read 2 BGR pixels
        int bgr_idx0 = (y * width + x) * 3;
        int bgr_idx1 = (y * width + x + 1) * 3;

        uchar b0 = bgr[bgr_idx0];
        uchar g0 = bgr[bgr_idx0 + 1];
        uchar r0 = bgr[bgr_idx0 + 2];

        uchar b1 = bgr[bgr_idx1];
        uchar g1 = bgr[bgr_idx1 + 1];
        uchar r1 = bgr[bgr_idx1 + 2];

        // BT.601 conversion
        int y0 = ((66 * r0 + 129 * g0 + 25 * b0 + 128) >> 8) + 16;
        int y1 = ((66 * r1 + 129 * g1 + 25 * b1 + 128) >> 8) + 16;
        int u = ((-38 * r0 - 74 * g0 + 112 * b0 + 128) >> 8) + 128;
        int v = ((112 * r0 - 94 * g0 - 18 * b0 + 128) >> 8) + 128;

        // Clamp to valid ranges
        y0 = clamp(y0, 16, 235);
        y1 = clamp(y1, 16, 235);
        u = clamp(u, 16, 240);
        v = clamp(v, 16, 240);

        // Write YUYV (4 bytes for 2 pixels)
        int yuyv_idx = (y * width + x) * 2;
        yuyv[yuyv_idx] = (uchar)y0;
        yuyv[yuyv_idx + 1] = (uchar)u;
        yuyv[yuyv_idx + 2] = (uchar)y1;
        yuyv[yuyv_idx + 3] = (uchar)v;
    }
    """

    def __init__(self, width: int, height: int, use_intel: bool = True):
        """
        Initialize GPU color converter.

        Args:
            width: Frame width
            height: Frame height
            use_intel: If True, prefer Intel iGPU. If False, use NVIDIA.
        """
        try:
            import pyopencl as cl
        except ImportError:
            raise ImportError("pyopencl required for GPU acceleration. Install with: pip install pyopencl")

        self.width = width
        self.height = height
        self._cl = cl

        # Select device
        platforms = cl.get_platforms()
        if use_intel:
            platform = next((p for p in platforms if "Intel" in p.name), None)
            if not platform:
                logger.warning("Intel GPU not found, falling back to first available")
                platform = platforms[0]
        else:
            platform = next((p for p in platforms if "NVIDIA" in p.name), None)
            if not platform:
                logger.warning("NVIDIA GPU not found, falling back to first available")
                platform = platforms[0]

        device = platform.get_devices()[0]
        self.device_name = device.name
        self.ctx = cl.Context([device])
        self.queue = cl.CommandQueue(self.ctx)

        logger.info(f"GPU color converter using: {device.name}")

        # Compile kernel
        prg = cl.Program(self.ctx, self._KERNEL_SRC).build()
        self.kernel = cl.Kernel(prg, "bgr_to_yuyv")

        # Pre-allocate buffers
        mf = cl.mem_flags
        self.bgr_buf = cl.Buffer(self.ctx, mf.READ_ONLY, width * height * 3)
        self.yuyv_buf = cl.Buffer(self.ctx, mf.WRITE_ONLY, width * height * 2)
        self.yuyv_host = np.empty((height, width * 2), dtype=np.uint8)

        self.global_size = (width // 2, height)

    def convert(self, bgr_frame: np.ndarray) -> np.ndarray:
        """
        Convert BGR frame to YUYV using GPU.

        Args:
            bgr_frame: BGR frame as numpy array (H, W, 3)

        Returns:
            YUYV frame as numpy array (H, W*2)
        """
        cl = self._cl

        # Upload to GPU
        cl.enqueue_copy(self.queue, self.bgr_buf, bgr_frame)

        # Run kernel
        self.kernel.set_args(self.bgr_buf, self.yuyv_buf, np.int32(self.width), np.int32(self.height))
        cl.enqueue_nd_range_kernel(self.queue, self.kernel, self.global_size, None)

        # Download from GPU
        cl.enqueue_copy(self.queue, self.yuyv_host, self.yuyv_buf)
        self.queue.finish()

        return self.yuyv_host


class UltraLowCPURenderer:
    """
    Full GPU pipeline renderer with ~1.5% CPU usage.

    All rendering happens on the GPU via a single mega-kernel:
    - Waveform generation (sin waves or audio-reactive)
    - Progress bar updates
    - Color conversion (BGR→YUYV)
    - Optional horizontal flip for Google Meet (set FLIP=1 env var)

    Only the static base frame is rendered on CPU (once per attendee).

    Environment Variables:
        FLIP=1  - Enable horizontal flip (pre-mirror for Google Meet)
        FLIP=0  - Disable flip (default, normal output)
    """

    # OpenCL kernel with hardcoded constants for maximum performance
    # MIRROR_OUTPUT: 1 = flip horizontally (for Google Meet), 0 = normal
    _KERNEL_TEMPLATE = """
    #define WIDTH {width}
    #define HEIGHT {height}
    #define WAVE_X {wave_x}
    #define WAVE_Y {wave_y}
    #define WAVE_W {wave_w}
    #define WAVE_H {wave_h}
    #define NUM_BARS {num_bars}
    #define BAR_W {bar_w}
    #define BAR_GAP {bar_gap}
    #define BAR_TOTAL {bar_total}
    #define PROGRESS_Y {progress_y}
    #define PROGRESS_H {progress_h}
    #define MIRROR_OUTPUT {mirror_output}

    __kernel void render_frame(
        __global const uchar* base_frame,
        __global uchar* yuyv_out,
        __global const float* audio_bars,  // Audio bar heights (0-1), or NULL for simulated
        const float time,
        const int progress_pixels,
        const int use_audio  // 1 = use audio_bars, 0 = generate waveform
    ) {{
        int px = get_global_id(0) * 2;
        int py = get_global_id(1);

        // For horizontal flip: read from mirrored position, write to normal position
        // This pre-mirrors the output so Google Meet's mirror shows it correctly
        int src_px, src_px1;
        if (MIRROR_OUTPUT) {{
            // Mirror: read pixel pair from opposite side of frame
            // px=0,1 reads from WIDTH-2,WIDTH-1; px=2,3 reads from WIDTH-4,WIDTH-3; etc.
            src_px = WIDTH - 2 - px;  // First pixel of mirrored pair
            src_px1 = src_px + 1;     // Second pixel of mirrored pair
        }} else {{
            src_px = px;
            src_px1 = px + 1;
        }}

        // Read base frame from source position (possibly mirrored)
        int idx0 = (py * WIDTH + src_px) * 3;
        int idx1 = (py * WIDTH + src_px1) * 3;

        uchar b0 = base_frame[idx0];
        uchar g0 = base_frame[idx0 + 1];
        uchar r0 = base_frame[idx0 + 2];

        uchar b1 = base_frame[idx1];
        uchar g1 = base_frame[idx1 + 1];
        uchar r1 = base_frame[idx1 + 2];

        // For overlays, use source coordinates (same as base frame read position)
        // This ensures overlays appear at the correct position relative to content
        int overlay_px0 = src_px;
        int overlay_px1 = src_px1;

        // Waveform overlay for pixel 0
        if (py >= WAVE_Y && py < WAVE_Y + WAVE_H && overlay_px0 >= WAVE_X && overlay_px0 < WAVE_X + WAVE_W) {{
            int wx = overlay_px0 - WAVE_X;
            int wy = py - WAVE_Y;
            int bar_idx = wx / BAR_TOTAL;
            int bar_x = wx % BAR_TOTAL;

            if (bar_x < BAR_W && bar_idx < NUM_BARS) {{
                float h;
                if (use_audio) {{
                    h = audio_bars[bar_idx];
                }} else {{
                    // Animated waveform - multiple frequencies for more dynamic look
                    float t = time * 8.0f;  // Faster animation
                    float wave1 = native_sin(t + bar_idx * 0.15f);
                    float wave2 = native_sin(t * 1.7f + bar_idx * 0.08f) * 0.5f;
                    float wave3 = native_sin(t * 0.5f + bar_idx * 0.3f) * 0.3f;
                    h = 0.15f + 0.85f * fabs(wave1 + wave2 + wave3) / 1.8f;
                }}
                int bar_pixels = (int)(h * WAVE_H);
                if (WAVE_H - 1 - wy < bar_pixels) {{
                    g0 = 200;
                }}
            }}
        }}

        // Waveform overlay for pixel 1
        if (py >= WAVE_Y && py < WAVE_Y + WAVE_H && overlay_px1 >= WAVE_X && overlay_px1 < WAVE_X + WAVE_W) {{
            int wx = overlay_px1 - WAVE_X;
            int wy = py - WAVE_Y;
            int bar_idx = wx / BAR_TOTAL;
            int bar_x = wx % BAR_TOTAL;

            if (bar_x < BAR_W && bar_idx < NUM_BARS) {{
                float h;
                if (use_audio) {{
                    h = audio_bars[bar_idx];
                }} else {{
                    // Animated waveform - multiple frequencies for more dynamic look
                    float t = time * 8.0f;  // Faster animation
                    float wave1 = native_sin(t + bar_idx * 0.15f);
                    float wave2 = native_sin(t * 1.7f + bar_idx * 0.08f) * 0.5f;
                    float wave3 = native_sin(t * 0.5f + bar_idx * 0.3f) * 0.3f;
                    h = 0.15f + 0.85f * fabs(wave1 + wave2 + wave3) / 1.8f;
                }}
                int bar_pixels = (int)(h * WAVE_H);
                if (WAVE_H - 1 - wy < bar_pixels) {{
                    g1 = 200;
                }}
            }}
        }}

        // Progress bar (use source coordinates for consistent positioning)
        if (py >= PROGRESS_Y && py < PROGRESS_Y + PROGRESS_H) {{
            if (overlay_px0 >= 16 && overlay_px0 < 16 + progress_pixels) g0 = 200;
            if (overlay_px1 >= 16 && overlay_px1 < 16 + progress_pixels) g1 = 200;
        }}

        // BGR to YUYV
        int y0 = ((66 * r0 + 129 * g0 + 25 * b0 + 128) >> 8) + 16;
        int y1 = ((66 * r1 + 129 * g1 + 25 * b1 + 128) >> 8) + 16;
        int u = ((-38 * r0 - 74 * g0 + 112 * b0 + 128) >> 8) + 128;
        int v = ((112 * r0 - 94 * g0 - 18 * b0 + 128) >> 8) + 128;

        int yuyv_idx = (py * WIDTH + px) * 2;
        yuyv_out[yuyv_idx] = (uchar)clamp(y0, 16, 235);
        yuyv_out[yuyv_idx + 1] = (uchar)clamp(u, 16, 240);
        yuyv_out[yuyv_idx + 2] = (uchar)clamp(y1, 16, 235);
        yuyv_out[yuyv_idx + 3] = (uchar)clamp(v, 16, 240);
    }}
    """

    def __init__(self, config: "VideoConfig", use_intel: bool = True):
        """
        Initialize ultra-low CPU renderer.

        Args:
            config: VideoConfig with native pixel coordinates (no scaling)
            use_intel: If True, prefer Intel iGPU. If False, use NVIDIA.

        Environment Variables:
            FLIP=1 or FLIP=true - Enable horizontal flip (for Google Meet)
            FLIP=0 or FLIP=false or unset - Normal output (default)
        """
        try:
            import pyopencl as cl
        except ImportError:
            raise ImportError("pyopencl required for ultra-low CPU mode. Install with: pip install pyopencl")

        self.width = config.width
        self.height = config.height
        self._cl = cl

        # Check FLIP environment variable (default: False/no flip)
        flip_env = os.environ.get("FLIP", "").lower()
        self.mirror_output = flip_env in ("1", "true", "yes", "on")

        # Layout constants from config - native pixels, NO SCALING
        self.wave_x = config.wave_x
        self.wave_y = config.wave_y
        self.wave_w = config.wave_w
        self.wave_h = config.wave_h
        self.num_bars = config.num_bars
        self.bar_w = config.bar_width
        self.bar_gap = config.bar_gap
        self.progress_y = config.progress_y
        self.progress_h = config.progress_h
        self.progress_width = config.width - (config.progress_margin * 2)

        # Setup OpenCL
        platforms = cl.get_platforms()
        if use_intel:
            platform = next((p for p in platforms if "Intel" in p.name), platforms[0])
        else:
            platform = next((p for p in platforms if "NVIDIA" in p.name), platforms[0])

        device = platform.get_devices()[0]
        self.device_name = device.name
        self.ctx = cl.Context([device])
        self.queue = cl.CommandQueue(self.ctx)

        flip_str = "FLIPPED (for Google Meet)" if self.mirror_output else "normal"
        logger.info(f"UltraLowCPU renderer using: {device.name} ({flip_str})")

        # Compile kernel with hardcoded constants
        kernel_src = self._KERNEL_TEMPLATE.format(
            width=self.width,
            height=self.height,
            wave_x=self.wave_x,
            wave_y=self.wave_y,
            wave_w=self.wave_w,
            wave_h=self.wave_h,
            num_bars=self.num_bars,
            bar_w=self.bar_w,
            bar_gap=self.bar_gap,
            bar_total=self.bar_w + self.bar_gap,
            progress_y=self.progress_y,
            progress_h=self.progress_h,
            mirror_output=1 if self.mirror_output else 0,
        )
        prg = cl.Program(self.ctx, kernel_src).build(options=["-cl-fast-relaxed-math"])
        self.kernel = cl.Kernel(prg, "render_frame")

        # Allocate buffers
        mf = cl.mem_flags
        self.base_gpu = cl.Buffer(self.ctx, mf.READ_ONLY, self.width * self.height * 3)
        self.yuyv_gpu = cl.Buffer(self.ctx, mf.WRITE_ONLY, self.width * self.height * 2)
        self.audio_gpu = cl.Buffer(self.ctx, mf.READ_ONLY, self.num_bars * 4)  # float32
        self.yuyv_host = np.empty((self.height, self.width * 2), dtype=np.uint8)
        self.audio_host = np.zeros(self.num_bars, dtype=np.float32)

        # Initialize audio GPU buffer with zeros (prevents uninitialized memory reads)
        cl.enqueue_copy(self.queue, self.audio_gpu, self.audio_host)
        self.queue.finish()

        self.global_size = (self.width // 2, self.height)

    def upload_base_frame(self, frame: np.ndarray):
        """Upload pre-rendered base frame to GPU."""
        cl = self._cl
        cl.enqueue_copy(self.queue, self.base_gpu, frame)
        self.queue.finish()

    def render_frame(self, t: float, progress_fraction: float, audio_bars: np.ndarray = None) -> np.ndarray:
        """
        Render a frame on GPU and return YUYV data.

        Args:
            t: Time in seconds (for simulated waveform)
            progress_fraction: Progress bar fill (0-1)
            audio_bars: Optional audio bar heights (0-1) for audio-reactive mode

        Returns:
            YUYV frame as numpy array
        """
        cl = self._cl
        progress_pixels = int(progress_fraction * self.progress_width)

        # Upload audio bars if provided
        use_audio = 0
        if audio_bars is not None:
            np.copyto(self.audio_host[: len(audio_bars)], audio_bars[: self.num_bars])
            cl.enqueue_copy(self.queue, self.audio_gpu, self.audio_host)
            use_audio = 1

        self.kernel.set_args(
            self.base_gpu, self.yuyv_gpu, self.audio_gpu, np.float32(t), np.int32(progress_pixels), np.int32(use_audio)
        )
        cl.enqueue_nd_range_kernel(self.queue, self.kernel, self.global_size, None)
        cl.enqueue_copy(self.queue, self.yuyv_host, self.yuyv_gpu)
        self.queue.finish()

        return self.yuyv_host


class StreamingRenderer(UltraLowCPURenderer):
    """
    Streaming-optimized renderer that outputs BGRA for hardware encoding.

    Extends UltraLowCPURenderer to support:
    - BGRA output (for VA-API/GStreamer pipeline)
    - YUYV output (for v4l2loopback, backward compatible)
    - Integrated WebRTC streaming via IntelStreamingPipeline

    The BGRA output is more efficient for hardware encoding because:
    - VA-API postproc handles color conversion on GPU
    - No CPU-side YUYV packing needed
    - Zero-copy path to encoder possible
    """

    # Additional kernel for BGRA output (no color conversion)
    _BGRA_KERNEL_TEMPLATE = """
    #define WIDTH {width}
    #define HEIGHT {height}
    #define WAVE_X {wave_x}
    #define WAVE_Y {wave_y}
    #define WAVE_W {wave_w}
    #define WAVE_H {wave_h}
    #define NUM_BARS {num_bars}
    #define BAR_W {bar_w}
    #define BAR_GAP {bar_gap}
    #define BAR_TOTAL {bar_total}
    #define PROGRESS_Y {progress_y}
    #define PROGRESS_H {progress_h}
    #define MIRROR_OUTPUT {mirror_output}

    __kernel void render_frame_bgra(
        __global const uchar* base_frame,
        __global uchar* bgra_out,
        __global const float* audio_bars,
        const float time,
        const int progress_pixels,
        const int use_audio
    ) {{
        int px = get_global_id(0);
        int py = get_global_id(1);

        if (px >= WIDTH || py >= HEIGHT) return;

        // For horizontal flip: read from mirrored position
        int src_px;
        if (MIRROR_OUTPUT) {{
            src_px = WIDTH - 1 - px;
        }} else {{
            src_px = px;
        }}

        // Read base frame (BGR format)
        int idx = (py * WIDTH + src_px) * 3;
        uchar b = base_frame[idx];
        uchar g = base_frame[idx + 1];
        uchar r = base_frame[idx + 2];

        // Waveform overlay
        if (py >= WAVE_Y && py < WAVE_Y + WAVE_H && src_px >= WAVE_X && src_px < WAVE_X + WAVE_W) {{
            int wx = src_px - WAVE_X;
            int wy = py - WAVE_Y;
            int bar_idx = wx / BAR_TOTAL;
            int bar_x = wx % BAR_TOTAL;

            if (bar_x < BAR_W && bar_idx < NUM_BARS) {{
                float h;
                if (use_audio) {{
                    h = audio_bars[bar_idx];
                }} else {{
                    float t = time * 8.0f;
                    float wave1 = native_sin(t + bar_idx * 0.15f);
                    float wave2 = native_sin(t * 1.7f + bar_idx * 0.08f) * 0.5f;
                    float wave3 = native_sin(t * 0.5f + bar_idx * 0.3f) * 0.3f;
                    h = 0.15f + 0.85f * fabs(wave1 + wave2 + wave3) / 1.8f;
                }}
                int bar_pixels = (int)(h * WAVE_H);
                if (WAVE_H - 1 - wy < bar_pixels) {{
                    g = 200;
                }}
            }}
        }}

        // Progress bar
        if (py >= PROGRESS_Y && py < PROGRESS_Y + PROGRESS_H) {{
            if (src_px >= 16 && src_px < 16 + progress_pixels) {{
                g = 200;
            }}
        }}

        // Output BGRA (note: GStreamer expects BGRA, not RGBA)
        int out_idx = (py * WIDTH + px) * 4;
        bgra_out[out_idx] = b;
        bgra_out[out_idx + 1] = g;
        bgra_out[out_idx + 2] = r;
        bgra_out[out_idx + 3] = 255;  // Alpha
    }}
    """

    def __init__(self, config: "VideoConfig", use_intel: bool = True, enable_streaming: bool = False):
        """
        Initialize streaming renderer.

        Args:
            config: VideoConfig with native pixel coordinates
            use_intel: If True, prefer Intel iGPU
            enable_streaming: If True, initialize WebRTC streaming pipeline
        """
        # Initialize parent (YUYV renderer)
        super().__init__(config, use_intel)

        self.enable_streaming = enable_streaming
        self._streaming_pipeline = None

        # Compile BGRA kernel
        cl = self._cl
        bgra_kernel_src = self._BGRA_KERNEL_TEMPLATE.format(
            width=self.width,
            height=self.height,
            wave_x=self.wave_x,
            wave_y=self.wave_y,
            wave_w=self.wave_w,
            wave_h=self.wave_h,
            num_bars=self.num_bars,
            bar_w=self.bar_w,
            bar_gap=self.bar_gap,
            bar_total=self.bar_w + self.bar_gap,
            progress_y=self.progress_y,
            progress_h=self.progress_h,
            mirror_output=1 if self.mirror_output else 0,
        )
        prg_bgra = cl.Program(self.ctx, bgra_kernel_src).build(options=["-cl-fast-relaxed-math"])
        self.kernel_bgra = cl.Kernel(prg_bgra, "render_frame_bgra")

        # Allocate BGRA buffer
        mf = cl.mem_flags
        self.bgra_gpu = cl.Buffer(self.ctx, mf.WRITE_ONLY, self.width * self.height * 4)
        self.bgra_host = np.empty((self.height, self.width, 4), dtype=np.uint8)

        self.global_size_bgra = (self.width, self.height)

        logger.info(f"StreamingRenderer initialized (streaming={'enabled' if enable_streaming else 'disabled'})")

    def start_streaming(self, signaling_port: int = 8765, v4l2_device: str = None):
        """
        Start the WebRTC streaming pipeline.

        Args:
            signaling_port: WebSocket port for WebRTC signaling
            v4l2_device: Optional v4l2 device for Google Meet output
        """
        if self._streaming_pipeline:
            logger.warning("Streaming already started")
            return

        try:
            from .intel_streaming import IntelStreamingPipeline, StreamConfig

            config = StreamConfig(
                width=self.width,
                height=self.height,
                framerate=30,
                bitrate=4000,
                encoder="va",
                codec="h264",
                signaling_port=signaling_port,
                flip=False,  # Already handled in our kernel
                v4l2_device=v4l2_device,
            )

            self._streaming_pipeline = IntelStreamingPipeline(config)
            self._streaming_pipeline.start(mode="webrtc")

            logger.info(f"WebRTC streaming started on port {signaling_port}")

        except ImportError as e:
            logger.error(f"Failed to import streaming module: {e}")
        except Exception as e:
            logger.error(f"Failed to start streaming: {e}")

    def stop_streaming(self):
        """Stop the WebRTC streaming pipeline."""
        if self._streaming_pipeline:
            self._streaming_pipeline.stop()
            self._streaming_pipeline = None
            logger.info("Streaming stopped")

    def render_frame_bgra(self, t: float, progress_fraction: float, audio_bars: np.ndarray = None) -> np.ndarray:
        """
        Render a frame on GPU and return BGRA data.

        This is more efficient for hardware encoding pipelines.

        Args:
            t: Time in seconds (for simulated waveform)
            progress_fraction: Progress bar fill (0-1)
            audio_bars: Optional audio bar heights (0-1)

        Returns:
            BGRA frame as numpy array (height, width, 4)
        """
        cl = self._cl
        progress_pixels = int(progress_fraction * self.progress_width)

        # Upload audio bars if provided
        use_audio = 0
        if audio_bars is not None:
            np.copyto(self.audio_host[: len(audio_bars)], audio_bars[: self.num_bars])
            cl.enqueue_copy(self.queue, self.audio_gpu, self.audio_host)
            use_audio = 1

        self.kernel_bgra.set_args(
            self.base_gpu, self.bgra_gpu, self.audio_gpu, np.float32(t), np.int32(progress_pixels), np.int32(use_audio)
        )
        cl.enqueue_nd_range_kernel(self.queue, self.kernel_bgra, self.global_size_bgra, None)
        cl.enqueue_copy(self.queue, self.bgra_host, self.bgra_gpu)
        self.queue.finish()

        return self.bgra_host

    def render_and_stream(self, t: float, progress_fraction: float, audio_bars: np.ndarray = None) -> np.ndarray:
        """
        Render frame and push to streaming pipeline.

        Returns YUYV for v4l2 compatibility while also streaming BGRA via WebRTC.

        Args:
            t: Time in seconds
            progress_fraction: Progress bar fill (0-1)
            audio_bars: Optional audio bar heights

        Returns:
            YUYV frame (for v4l2 backward compatibility)
        """
        # Render BGRA for streaming
        if self._streaming_pipeline and self._streaming_pipeline.is_running:
            bgra = self.render_frame_bgra(t, progress_fraction, audio_bars)
            self._streaming_pipeline.push_frame(bgra)

        # Also render YUYV for v4l2 output
        return self.render_frame(t, progress_fraction, audio_bars)

    def get_streaming_stats(self) -> dict:
        """Get streaming statistics."""
        if self._streaming_pipeline:
            return self._streaming_pipeline.get_stats()
        return {"running": False}


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
        active_ms = int((npu_path / "power" / "runtime_active_time").read_text().strip())
        active_sec = active_ms / 1000
        stats.append(f"ACTIVE TIME: {active_sec:.1f}s")

        # Add some fake processing stats for effect
        stats.append(f"INFERENCE RATE: {random.randint(15, 25)} req/s")
        stats.append(f"LATENCY: {random.randint(20, 45)}ms")
        stats.append(f"THROUGHPUT: {random.uniform(0.8, 1.2):.2f} TOPS")
        stats.append(f"TEMP: {random.randint(42, 58)}C")
        stats.append(f"UTILIZATION: {random.randint(35, 85)}%")

    except Exception as e:
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


@dataclass
class Attendee:
    """Meeting attendee for the fake research video."""

    name: str
    mugshot_path: Optional[Path] = None  # Optional photo
    title: str = "Engineer"


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

        total_duration = len(attendees) * self.config.duration_per_person + 3  # +3 for intro/outro

        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={self.config.background_color}:s={self.config.width}x{self.config.height}:r={self.config.fps}:d={total_duration}",
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

        logger.info(f"🎬 Starting real-time research video stream")
        logger.info(f"📋 {total_attendees} attendees to analyze")
        logger.info(f"📺 Output: {video_device} @ {config.width}x{config.height} {config.fps}fps")

        self._running = True
        iteration = 0

        while self._running:
            iteration += 1
            logger.info(f"🔄 Starting iteration {iteration} through {total_attendees} attendees")

            for idx, attendee in enumerate(attendees):
                if not self._running:
                    break

                logger.info(f"🔍 [{idx + 1}/{total_attendees}] Analyzing: {attendee.name}")
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
        import sys

        config = self.config
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
        tools = random.sample(RESEARCH_TOOLS, min(config.num_tools, len(RESEARCH_TOOLS)))
        findings = random.sample(FAKE_FINDINGS, min(config.num_findings, len(FAKE_FINDINGS)))
        assessment = random.choice(THREAT_ASSESSMENTS)

        # Build filter graph
        filters = []

        # Header
        filters.append(f"drawtext=text='AI RESEARCH MODULE v2.1':fontsize=24:fontcolor=gray:x=30:y=15")
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
            f":enable='lt(mod(t,4),1)'"
        )
        filters.append(
            f"drawtext=text='TARGET\\: {escaped_name} .'"
            f":fontsize=56:fontcolor={config.highlight_color}:x=30:y=140"
            f":enable='between(mod(t,4),1,2)'"
        )
        filters.append(
            f"drawtext=text='TARGET\\: {escaped_name} ..'"
            f":fontsize=56:fontcolor={config.highlight_color}:x=30:y=140"
            f":enable='between(mod(t,4),2,3)'"
        )
        filters.append(
            f"drawtext=text='TARGET\\: {escaped_name} ...'"
            f":fontsize=56:fontcolor={config.highlight_color}:x=30:y=140"
            f":enable='gte(mod(t,4),3)'"
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
            f":fontsize=28:fontcolor=cyan"
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
        tools = random.sample(RESEARCH_TOOLS, min(config.num_tools, len(RESEARCH_TOOLS)))
        findings = random.sample(FAKE_FINDINGS, min(config.num_findings, len(FAKE_FINDINGS)))
        assessment = random.choice(THREAT_ASSESSMENTS)

        # Check if we have pre-rendered waveform
        use_waveform_overlay = config.waveform_video and config.waveform_video.exists()

        # Build filter graph for this single attendee
        filters = []

        # Header with attendee count
        filters.append(f"drawtext=text='AI RESEARCH MODULE v2.1':fontsize=24:fontcolor=gray:x=30:y=15")
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
            f"drawbox=x={right_col_x}:y={right_col_top}:w=2:h={right_col_height}" f":color={config.text_color}:t=fill"
        )

        # 4 sections in right column, ~110px each
        section_height = 110
        section_x = right_col_x + 10
        section_w = config.right_column_width - 20

        # Section 1: JIRA ISSUE TRACKER
        sec1_y = right_col_top + 5
        filters.append(f"drawtext=text='[ JIRA ]':fontsize=12:fontcolor=cyan" f":x={section_x}:y={sec1_y}")
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
        filters.append(f"drawtext=text='[ SLACK ]':fontsize=12:fontcolor=cyan" f":x={section_x}:y={sec2_y}")
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
        filters.append(f"drawtext=text='[ SEMANTIC ]':fontsize=12:fontcolor=cyan" f":x={section_x}:y={sec3_y}")
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
        filters.append(f"drawtext=text='[ COMMS ]':fontsize=12:fontcolor=cyan" f":x={section_x}:y={sec4_y}")
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
        filters.append(f"drawbox=x={head_cx - 25}:y={head_cy - 25}:w=50:h=50" f":color={config.text_color}@0.5:t=fill")
        # Body
        filters.append(f"drawbox=x={head_cx - 35}:y={head_cy + 35}:w=70:h=120" f":color={config.text_color}@0.5:t=fill")
        # Shoulders
        filters.append(f"drawbox=x={head_cx - 55}:y={head_cy + 35}:w=110:h=25" f":color={config.text_color}@0.5:t=fill")
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
        filters.append(f"drawbox=x={wave_x}:y={wave_y}:w={wave_w}:h={wave_h}" f":color={config.text_color}:t=2")
        # Caption above the waveform
        filters.append(
            f"drawtext=text='VOICE ANALYSIS':fontsize=14:fontcolor=cyan" f":x={wave_x + 240}:y={wave_y - 18}"
        )
        # Additional label below
        filters.append(
            f"drawtext=text='[ AUDIO ]':fontsize=11:fontcolor=gray" f":x={wave_x + 270}:y={wave_y + wave_h + 5}"
        )

        # Target name with animated dots (cycles: name, name ., name .., name ...)
        escaped_name = self._escape_text(attendee.name)

        # State 0: no dots (t mod 4 < 1)
        filters.append(
            f"drawtext=text='TARGET\\: {escaped_name}'"
            f":fontsize=36:fontcolor={config.highlight_color}:x=20:y=100"
            f":enable='lt(mod(t,4),1)'"
        )
        # State 1: one dot (1 <= t mod 4 < 2)
        filters.append(
            f"drawtext=text='TARGET\\: {escaped_name} .'"
            f":fontsize=36:fontcolor={config.highlight_color}:x=20:y=100"
            f":enable='between(mod(t,4),1,2)'"
        )
        # State 2: two dots (2 <= t mod 4 < 3)
        filters.append(
            f"drawtext=text='TARGET\\: {escaped_name} ..'"
            f":fontsize=36:fontcolor={config.highlight_color}:x=20:y=100"
            f":enable='between(mod(t,4),2,3)'"
        )
        # State 3: three dots (3 <= t mod 4 < 4)
        filters.append(
            f"drawtext=text='TARGET\\: {escaped_name} ...'"
            f":fontsize=36:fontcolor={config.highlight_color}:x=20:y=100"
            f":enable='gte(mod(t,4),3)'"
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
                f":fontsize=16:fontcolor=yellow"
                f":x=240:y={310 + j * 24}:enable='gte(t,{finding_start})'"
            )

        # Assessment at end (last 2 seconds)
        filters.append(
            f"drawtext=text='{self._escape_text(assessment)}'"
            f":fontsize=20:fontcolor=cyan"
            f":x=240:y={310 + len(findings) * 24 + 20}:enable='gte(t,{duration - 2})'"
        )

        # NPU Stats Panel position
        npu_panel_y = config.height - self.config.npu_width // 3  # Bottom of screen

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

        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            logger.warning(f"FFmpeg error for {attendee.name}: {stderr.decode()[:200]}")

    def _build_filter_graph(self, attendees: list[Attendee]) -> str:
        """Build complete filter graph for all attendees (for file generation)."""
        filters = []
        config = self.config
        total_attendees = len(attendees)

        # Header - scaled for 720p
        filters.append(f"drawtext=text='AI RESEARCH MODULE v2.1':fontsize=18:fontcolor=gray:x=20:y=10")
        filters.append(
            f"drawtext=text='SCANNING {total_attendees} ATTENDEES...':fontsize=24:fontcolor={config.text_color}:x=20:y=35"
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
        filters.append(f"drawbox=x={head_cx - 22}:y={head_cy - 22}:w=44:h=44" f":color={config.text_color}@0.5:t=fill")
        # Body
        filters.append(f"drawbox=x={head_cx - 30}:y={head_cy + 30}:w=60:h=100" f":color={config.text_color}@0.5:t=fill")
        # Shoulders
        filters.append(f"drawbox=x={head_cx - 48}:y={head_cy + 30}:w=96:h=22" f":color={config.text_color}@0.5:t=fill")

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
        filters.append(f"drawbox=x={wave_x}:y={wave_y}:w={wave_w}:h={wave_h}" f":color={config.text_color}:t=2")

        # "ANALYZING SPEECH PATTERN" label
        filters.append(
            f"drawtext=text='VOICE ANALYSIS':fontsize=11:fontcolor=cyan" f":x={wave_x + 250}:y={wave_y + wave_h + 4}"
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
                finding_end = min(finding_start + config.finding_display_time + 1, end_time)
                filters.append(
                    f"drawtext=text='{self._escape_text(finding)}'"
                    f":fontsize=12:fontcolor=yellow"
                    f":x=220:y={210 + (j % 3) * 18}:enable='between(t,{finding_start},{finding_end})'"
                )

            # Assessment - appears at end
            assessment = random.choice(THREAT_ASSESSMENTS)
            filters.append(
                f"drawtext=text='{self._escape_text(assessment)}'"
                f":fontsize=16:fontcolor=cyan"
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


class RealtimeVideoRenderer:
    """
    Real-time video renderer using PIL for dynamic frame generation.

    Generates waveform and NPU panels on-the-fly instead of using pre-rendered files.
    This uses more CPU but allows truly dynamic content.

    Audio-Reactive Mode:
        When connected to a PulseAudio source, the waveform displays actual
        audio levels from the meeting in real-time.
    """

    def __init__(
        self, config: Optional[VideoConfig] = None, audio_source: Optional[str] = None, enable_webrtc: bool = False
    ):
        """
        Initialize the real-time video renderer.

        Args:
            config: Video configuration
            audio_source: Optional PulseAudio source name for audio-reactive waveform
                         (e.g., "meet_bot_abc123.monitor")
            enable_webrtc: Enable WebRTC streaming for preview (port 8765)
        """
        self.config = config or VideoConfig()
        self._running = False

        # WebRTC streaming for preview
        self._enable_webrtc = enable_webrtc
        self._webrtc_pipeline = None

        # Audio capture for reactive waveform
        self._audio_source = audio_source
        self._audio_capture = None
        self._audio_buffer: Optional[np.ndarray] = None
        # Note: Lock is created lazily in _start_audio_capture since we may not be in async context
        self._audio_lock: Optional[asyncio.Lock] = None

        # Speech-to-text using OpenVINO on NPU
        self._stt_engine = None
        self._stt_text: str = ""  # Current transcription text
        self._stt_text_lock: Optional[asyncio.Lock] = None
        # Pre-allocated contiguous buffer for STT audio (15 seconds max at 16kHz)
        self._stt_buffer_size = 16000 * 15  # 15 seconds = 240000 samples
        self._stt_buffer: np.ndarray = np.zeros(self._stt_buffer_size, dtype=np.float32)
        self._stt_write_pos: int = 0  # Write position (also = number of valid samples)
        self._stt_last_process: float = 0.0
        self._stt_enabled: bool = audio_source is not None  # Enable STT if audio source provided
        self._stt_history: list = []  # History of transcriptions (most recent first)
        self._stt_history_max: int = 6  # Max number of lines to keep

        # Real NPU stats (updated every 0.5s by background task)
        self._npu_stats: dict = {
            "freq_mhz": 0,
            "max_freq_mhz": 1400,
            "busy_us": 0,
            "busy_delta_us": 0,  # Change since last read (for utilization calc)
            "mem_bytes": 0,
            "power_state": "D0",
            "runtime_status": "active",
            "active_ms": 0,
            "last_update": 0.0,
        }
        self._npu_stats_prev_busy: int = 0  # For calculating delta

        # Try to load fonts
        try:
            from PIL import ImageFont

            self.font_small = ImageFont.truetype("/usr/share/fonts/liberation-mono/LiberationMono-Regular.ttf", 14)
            self.font_medium = ImageFont.truetype("/usr/share/fonts/liberation-mono/LiberationMono-Regular.ttf", 18)
            self.font_large = ImageFont.truetype("/usr/share/fonts/liberation-mono/LiberationMono-Regular.ttf", 24)
        except Exception:
            from PIL import ImageFont

            self.font_small = ImageFont.load_default()
            self.font_medium = self.font_small
            self.font_large = self.font_small

        # Waveform config - from native pixel config
        self.wave_width = self.config.wave_w
        self.wave_height = self.config.wave_h
        self.wave_bars = self.config.num_bars

        # NPU panel config - full width at bottom
        self.npu_width = self.config.width
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
        self._fft_smoothing = 0.3  # Smoothing factor for FFT (0=no smoothing, 1=max smoothing)
        self._prev_fft_bars: Optional[np.ndarray] = None

        # GPU text renderer (smooth anti-aliased TrueType fonts via OpenGL)
        # Font sizes are resolution-dependent: 1080p gets +2pt for readability
        self._gpu_text_renderer: Optional["VideoTextRenderer"] = None
        if _gpu_text_available:
            try:
                # 1080p: larger fonts for readability at higher res
                # 720p: smaller fonts to fit the layout
                if self.config.height >= 1080:
                    font_sizes = {"xlarge": 36, "large": 26, "medium": 24, "normal": 18, "small": 14, "tiny": 12}
                else:
                    font_sizes = {"xlarge": 34, "large": 24, "medium": 22, "normal": 16, "small": 12, "tiny": 10}

                self._gpu_text_renderer = VideoTextRenderer(
                    self.config.width, self.config.height, font_sizes=font_sizes
                )
                if self._gpu_text_renderer.initialize():
                    logger.info("GPU text rendering enabled (smooth anti-aliased fonts)")
                else:
                    raise RuntimeError("GPU text init failed")
            except Exception as e:
                raise RuntimeError(f"GPU text renderer required but not available: {e}")
        else:
            raise RuntimeError("GPU text renderer (OpenGL) is required but not available")

        # Pre-render static elements for performance
        self._static_cache = {}
        self._init_static_cache()

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
        cv2.line(base_frame, (right_col_x, 50), (right_col_x, bottom_section_y), CV_GREEN, 2)

        # "Building Context" heading
        cv2.putText(
            base_frame, "BUILDING CONTEXT", (right_col_x + 8, 68), CV_FONT, font_small, CV_RED, thickness, CV_LINE_TYPE
        )

        # Section headers (static)
        sections_start_y = 75
        section_height = (bottom_section_y - sections_start_y) // 4
        section_headers = ["[ JIRA ]", "[ SLACK ]", "[ SEMANTIC ]", "[ COMMS ]"]
        for i, header in enumerate(section_headers):
            sec_y = sections_start_y + i * section_height + 12
            cv2.putText(
                base_frame, header, (right_col_x + 8, sec_y), CV_FONT, font_small, CV_CYAN, thickness, CV_LINE_TYPE
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
            base_frame, (head_cx - 40, head_cy + 35), (head_cx + 40, head_cy + 145), CV_DARK_GREEN, -1
        )  # Body
        cv2.rectangle(
            base_frame, (head_cx - 55, head_cy + 35), (head_cx + 55, head_cy + 60), CV_DARK_GREEN, -1
        )  # Shoulders

        # Waveform box - from native config
        wave_w = config.wave_w
        wave_h = config.wave_h
        wave_x = config.wave_x
        wave_y = config.wave_y
        cv2.rectangle(base_frame, (wave_x, wave_y), (wave_x + wave_w, wave_y + wave_h), CV_GREEN, 2)
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
        cv2.line(base_frame, (0, bottom_section_y), (config.width, bottom_section_y), (0, 180, 0), 2)

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
        self._wave_buffer = np.zeros((self.wave_height, self.wave_width, 3), dtype=np.uint8)
        self._npu_buffer = np.zeros((self.npu_height, self.npu_width, 3), dtype=np.uint8)

        # Pre-allocate FFT computation buffers to avoid per-frame allocations
        self._fft_bar_heights = np.zeros(self.wave_bars, dtype=np.float32)
        self._fft_silence_bars = np.full(self.wave_bars, 0.12, dtype=np.float32)
        self._fft_hanning = None  # Will be created on first use with correct size

        logger.debug("Static element cache initialized (OpenCV)")

    async def _start_audio_capture(self) -> bool:
        """Start capturing audio from the PulseAudio source."""
        if not self._audio_source:
            return False

        try:
            from tool_modules.aa_meet_bot.src.audio_capture import PulseAudioCapture

            # Create lock now that we're in async context
            self._audio_lock = asyncio.Lock()

            self._audio_capture = PulseAudioCapture(
                source_name=self._audio_source,
                sample_rate=16000,
                chunk_ms=50,  # 50ms chunks for responsive visualization
            )

            if await self._audio_capture.start():
                logger.info(f"Audio capture started from {self._audio_source}")
                # Set running flag BEFORE starting processing loop
                self._running = True
                # Start audio processing task
                asyncio.create_task(self._audio_processing_loop())

                # Initialize STT engine (runs on NPU)
                if self._stt_enabled:
                    asyncio.create_task(self._init_stt_engine())

                # Start NPU stats monitoring (lightweight, every 0.5s)
                asyncio.create_task(self._npu_stats_loop())

                return True
            else:
                logger.warning(f"Failed to start audio capture from {self._audio_source}")
                return False

        except ImportError:
            logger.warning("audio_capture module not available, using simulated waveform")
            return False
        except Exception as e:
            logger.warning(f"Audio capture error: {e}, using simulated waveform")
            return False

    async def _audio_processing_loop(self):
        """Process audio chunks and update the visualization buffer.

        Optimized to reduce CPU overhead:
        - FFT computed at video frame rate (12fps) not audio chunk rate
        - Audio chunks accumulated in buffer, FFT runs periodically
        """
        import numpy as np

        # Buffer to hold recent audio samples for FFT
        # Keep ~100ms of audio for frequency analysis
        buffer_samples = int(16000 * 0.1)  # 100ms at 16kHz
        audio_buffer = np.zeros(buffer_samples, dtype=np.float32)

        chunk_count = 0
        last_log_time = asyncio.get_event_loop().time()
        last_fft_time = 0.0
        fft_interval = 1.0 / 12.0  # Match video frame rate (12fps)

        logger.info("Audio processing loop started")

        while self._running and self._audio_capture and self._audio_capture.is_running:
            try:
                chunk = await self._audio_capture.read_chunk()
                if chunk is None:
                    await asyncio.sleep(0.01)
                    continue

                chunk_count += 1

                # Shift buffer and add new samples (in-place to avoid allocation)
                chunk_len = len(chunk.data)
                audio_buffer[:-chunk_len] = audio_buffer[chunk_len:]  # Shift left in-place
                audio_buffer[-chunk_len:] = chunk.data  # Add new samples

                # Feed STT buffer (zero-copy write into pre-allocated array)
                if self._stt_enabled and self._stt_engine:
                    chunk_len = len(chunk.data)
                    end_pos = self._stt_write_pos + chunk_len
                    if end_pos <= self._stt_buffer_size:
                        # Direct write, no copy - numpy slice assignment
                        self._stt_buffer[self._stt_write_pos : end_pos] = chunk.data
                        self._stt_write_pos = end_pos
                    elif chunk_count % 100 == 0:  # Log occasionally
                        logger.warning(f"STT buffer full ({self._stt_write_pos} samples), dropping audio")

                # Compute FFT at video frame rate, not audio chunk rate
                now = asyncio.get_event_loop().time()
                if now - last_fft_time >= fft_interval:
                    fft_bars = self._compute_fft_bars(audio_buffer)
                    # Replace NaN with default values
                    if np.isnan(fft_bars).any():
                        fft_bars = np.nan_to_num(fft_bars, nan=0.1)
                    self._audio_buffer = fft_bars
                    last_fft_time = now

                # Log periodically
                if now - last_log_time >= 5.0:
                    rms = np.sqrt(np.mean(audio_buffer**2))
                    logger.info(
                        f"Audio processing: {chunk_count} chunks, RMS={rms:.4f}, buffer set={self._audio_buffer is not None}"
                    )
                    last_log_time = now

            except Exception as e:
                logger.debug(f"Audio processing error: {e}")
                await asyncio.sleep(0.01)

    async def _init_stt_engine(self):
        """Initialize the Speech-to-Text engine on NPU."""
        try:
            from tool_modules.aa_meet_bot.src.stt_engine import NPUWhisperSTT

            self._stt_text_lock = asyncio.Lock()
            self._stt_engine = NPUWhisperSTT(device="NPU")

            if await self._stt_engine.initialize():
                logger.info(f"STT engine initialized on {self._stt_engine._actual_device}")
                # Start STT processing loop
                asyncio.create_task(self._stt_processing_loop())
            else:
                logger.warning("STT engine failed to initialize, transcription disabled")
                self._stt_enabled = False

        except ImportError as e:
            logger.warning(f"STT engine not available: {e}")
            self._stt_enabled = False
        except Exception as e:
            logger.warning(f"STT initialization error: {e}")
            self._stt_enabled = False

    async def _stt_processing_loop(self):
        """Process audio for speech-to-text transcription.

        This loop processes audio from the shared STT buffer that is fed
        by the audio processing loop.
        """
        import time

        logger.info("STT processing loop started")
        last_transcription = time.time()

        while self._running:
            try:
                # Check if we have enough audio in the STT buffer
                if self._stt_write_pos < 1600:  # Less than 100ms
                    await asyncio.sleep(0.05)
                    continue

                # Calculate buffer duration
                buffer_duration = self._stt_write_pos / 16000

                # Check for silence at the end (last 1600 samples = 100ms) - NO COPY, just a view
                check_start = max(0, self._stt_write_pos - 1600)
                rms = np.sqrt(np.mean(self._stt_buffer[check_start : self._stt_write_pos] ** 2))
                is_silence = rms < 0.01

                # Decide when to transcribe:
                # 1. After silence with at least 1s of audio
                # 2. After 5s of audio (max buffer)
                # 3. HARD CAP at 10s
                should_transcribe = False

                if buffer_duration >= 1.0 and is_silence:
                    should_transcribe = True
                elif buffer_duration >= 5.0:
                    should_transcribe = True
                elif buffer_duration >= 10.0:
                    should_transcribe = True
                    logger.warning(f"STT buffer hit 10s cap ({self._stt_write_pos} samples), forcing transcribe")

                if should_transcribe and self._stt_write_pos > 0:
                    # Pass a VIEW to transcribe - NO COPY
                    # The STT engine must not hold a reference after returning
                    audio_view = self._stt_buffer[: self._stt_write_pos]
                    num_samples = self._stt_write_pos

                    # Reset write position BEFORE transcribe (so new audio writes to start)
                    self._stt_write_pos = 0

                    # Transcribe using the view
                    start = time.time()
                    result = await self._stt_engine.transcribe(audio_view, 16000)
                    proc_time = time.time() - start

                    if result.text and len(result.text.strip()) > 3:
                        # Filter out garbage (repeated chars, too short, single words)
                        text = result.text.strip()
                        # Skip if: too few unique chars, lots of punctuation, or single short word
                        is_garbage = (
                            len(set(text)) < 4
                            or text.count("!") > 3
                            or text.lower()
                            in ("you", "the", "a", "i", "to", "and", "is", "it", "thank you.", "thank you")
                        )
                        if not is_garbage:
                            async with self._stt_text_lock:
                                self._stt_text = text
                                # Add to history (most recent first)
                                self._stt_history.insert(0, text)
                                # Trim history to max size
                                if len(self._stt_history) > self._stt_history_max:
                                    self._stt_history = self._stt_history[: self._stt_history_max]
                            logger.info(f"STT [{proc_time:.2f}s]: {text}")
                            last_transcription = time.time()

                # Clear old text after 5 seconds of no new transcription
                if time.time() - last_transcription > 5.0 and self._stt_text:
                    async with self._stt_text_lock:
                        self._stt_text = ""

                await asyncio.sleep(0.2)  # Check every 200ms (reduced from 100ms)

            except Exception as e:
                logger.debug(f"STT processing error: {e}")
                await asyncio.sleep(0.2)

    async def _npu_stats_loop(self):
        """Read NPU statistics from sysfs every 0.5 seconds.

        This is very lightweight - just reading small text files.
        Results are cached in self._npu_stats for use by frame rendering.
        """
        import time

        npu_path = Path("/sys/devices/pci0000:00/0000:00:0b.0")

        logger.info("NPU stats monitoring started")

        while self._running:
            try:
                now = time.time()

                # Read all stats in one batch (minimize syscalls)
                try:
                    freq = int((npu_path / "npu_current_frequency_mhz").read_text().strip())
                    max_freq = int((npu_path / "npu_max_frequency_mhz").read_text().strip())
                    busy_us = int((npu_path / "npu_busy_time_us").read_text().strip())
                    mem_bytes = int((npu_path / "npu_memory_utilization").read_text().strip())
                    power_state = (npu_path / "power_state").read_text().strip()
                    runtime_status = (npu_path / "power" / "runtime_status").read_text().strip()
                    active_ms = int((npu_path / "power" / "runtime_active_time").read_text().strip())

                    # Calculate busy delta for utilization
                    busy_delta = busy_us - self._npu_stats_prev_busy
                    self._npu_stats_prev_busy = busy_us

                    # Update cached stats
                    self._npu_stats.update(
                        {
                            "freq_mhz": freq,
                            "max_freq_mhz": max_freq,
                            "busy_us": busy_us,
                            "busy_delta_us": busy_delta,
                            "mem_bytes": mem_bytes,
                            "power_state": power_state,
                            "runtime_status": runtime_status,
                            "active_ms": active_ms,
                            "last_update": now,
                        }
                    )

                except FileNotFoundError:
                    # NPU sysfs not available, use defaults
                    pass
                except Exception as e:
                    logger.debug(f"NPU stats read error: {e}")

                await asyncio.sleep(0.5)  # Update every 500ms

            except Exception as e:
                logger.debug(f"NPU stats loop error: {e}")
                await asyncio.sleep(1.0)

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
            low_freq = int(n_fft_bins * (np.exp(i / self.wave_bars * np.log(n_fft_bins)) - 1) / (n_fft_bins - 1))
            high_freq = int(n_fft_bins * (np.exp((i + 1) / self.wave_bars * np.log(n_fft_bins)) - 1) / (n_fft_bins - 1))
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

    def _generate_waveform_frame_from_audio(self, bar_heights: np.ndarray, out: np.ndarray = None) -> np.ndarray:
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

    def _generate_waveform_frame(self, t: float, out: np.ndarray = None) -> np.ndarray:
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

    def _generate_npu_frame(self, t: float, frame_num: int, out: np.ndarray = None) -> np.ndarray:
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
            frame, "[ INTEL NPU - METEOR LAKE ]", (15, 18), CV_FONT, font_small, CV_CYAN, thickness, CV_LINE_TYPE
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
            cv2.putText(frame, s, (15, y + i * line_h), CV_FONT, font_small, CV_GREEN, thickness, CV_LINE_TYPE)

        # Column 2 - Model info
        stats2 = [
            "MODEL: whisper-int8",
            "PRECISION: INT8",
            "INPUT: 16kHz PCM",
            "TILES: 2/2",
            "CACHE: ENABLED",
        ]
        for i, s in enumerate(stats2):
            cv2.putText(frame, s, (180, y + i * line_h), CV_FONT, font_small, CV_GREEN, thickness, CV_LINE_TYPE)

        # Column 3 - Counters
        stats3 = [
            f"SAMPLES: {int(t*16000)}",
            f"INFERENCES: {int(t*18)}",
            f"TOKENS: {int(t*45)}",
            f"FRAMES: {frame_num}",
            f"TIME: {int(t)//60:02d}:{int(t)%60:02d}.{int((t%1)*100):02d}",
        ]
        for i, s in enumerate(stats3):
            cv2.putText(frame, s, (380, y + i * line_h), CV_FONT, font_small, CV_GREEN, thickness, CV_LINE_TYPE)

        # Column 4 - System stats
        stats4 = [
            f"CPU: {15+int(10*math.sin(t*0.5))}%",
            f"MEM: {65+int(5*math.sin(t*0.3))} MB",
            f"QUEUE: {int((t*3)%5)}",
            f"LATENCY: {25+int(8*math.sin(t*2))}ms",
            "STATUS: ACTIVE",
        ]
        for i, s in enumerate(stats4):
            color = CV_CYAN if i == 4 else CV_GREEN
            cv2.putText(frame, s, (560, y + i * line_h), CV_FONT, font_small, color, thickness, CV_LINE_TYPE)

        # Column 5 - Additional telemetry
        stats5 = [
            f"RATE: {15+int(10*math.sin(t*0.5))} req/s",
            f"THROUGHPUT: {0.8+0.4*math.sin(t*0.3):.2f} TOPS",
            f"POWER: {4.2+0.8*math.sin(t*0.2):.1f}W",
            "DMA: ACTIVE",
            f"IRQ: {146 + int(t) % 10}",
        ]
        for i, s in enumerate(stats5):
            cv2.putText(frame, s, (740, y + i * line_h), CV_FONT, font_small, CV_GREEN, thickness, CV_LINE_TYPE)

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
            cv2.putText(frame, s, (920, y + i * line_h), CV_FONT, font_small, color, thickness, CV_LINE_TYPE)

        # Progress bar at bottom
        padding = 15
        bar_max_width = self.npu_width - padding * 2 - 150
        bar_width = int((t % 15) / 15 * bar_max_width)
        bar_y = self.npu_height - 20

        # Outline
        cv2.rectangle(frame, (padding, bar_y), (padding + bar_max_width, bar_y + 12), CV_GREEN, 1)
        # Fill
        if bar_width > 0:
            cv2.rectangle(frame, (padding + 2, bar_y + 2), (padding + 2 + bar_width, bar_y + 10), CV_GREEN, -1)
        # Percentage text
        cv2.putText(
            frame,
            f"PROCESSING: {int((t%15)/15*100)}%",
            (self.npu_width - padding - 130, bar_y + 10),
            CV_FONT,
            font_small,
            CV_GREEN,
            thickness,
            CV_LINE_TYPE,
        )

        # Return BGR array directly (caller expects BGR for OpenCV compatibility)
        return frame

    async def stream_realtime(
        self,
        attendees: list[Attendee],
        video_device: str,
        loop: bool = True,
    ) -> None:
        """
        Stream video with real-time generated overlays.

        Full GPU pipeline: OpenGL for text/shapes, OpenCL for color conversion.

        If audio_source was provided at init, the waveform will be audio-reactive.
        """
        import fcntl
        import struct

        config = self.config
        self._running = True

        logger.info(f"Starting real-time stream to {video_device} at {config.fps}fps")

        # Start audio capture if configured
        if self._audio_source:
            audio_started = await self._start_audio_capture()
            if audio_started:
                logger.info(f"Audio-reactive waveform enabled from {self._audio_source}")
                # Wait for audio buffer to be populated (up to 2s)
                # This ensures waveform is ready on first frame
                for i in range(200):  # 200 x 10ms = 2000ms max
                    if self._audio_buffer is not None:
                        logger.info(f"Audio buffer ready after {i * 10}ms")
                        break
                    await asyncio.sleep(0.01)
                else:
                    logger.warning("Audio buffer not ready after 2s, starting anyway")
            else:
                logger.info("Using simulated waveform (no audio capture)")

        # Reset GPU renderer to ensure clean state on each run
        if hasattr(self, "_ulc_renderer") and self._ulc_renderer is not None:
            logger.info("Resetting GPU renderer for clean state")
            self._ulc_renderer = None

        # Kill any processes using the device (except ourselves)
        try:
            subprocess.run(["sudo", "fuser", "-k", video_device], capture_output=True, timeout=5)
            await asyncio.sleep(0.5)  # Give processes time to die
        except Exception:
            pass  # fuser may not be available or device may not be in use

        # Open v4l2 device
        v4l2_fd = os.open(video_device, os.O_RDWR)

        # Set the video format using v4l2 ioctl
        # This is CRITICAL - v4l2loopback uses the format from the first VIDIOC_S_FMT
        VIDIOC_S_FMT = 0xC0D05605  # _IOWR('V', 5, struct v4l2_format)
        V4L2_BUF_TYPE_VIDEO_OUTPUT = 2
        V4L2_PIX_FMT_YUYV = 0x56595559  # 'YUYV'
        V4L2_FIELD_NONE = 1

        width = config.width
        height = config.height
        bytesperline = width * 2  # YUYV = 2 bytes per pixel
        sizeimage = bytesperline * height

        # Build v4l2_format structure (208 bytes total)
        fmt = struct.pack(
            "II"  # type, padding
            + "IIIIIIII"  # width, height, pixelformat, field, bytesperline, sizeimage, colorspace, priv
            + "II"  # flags, ycbcr_enc/hsv_enc
            + "II"  # quantization, xfer_func
            + "152x",  # reserved
            V4L2_BUF_TYPE_VIDEO_OUTPUT,
            0,
            width,
            height,
            V4L2_PIX_FMT_YUYV,
            V4L2_FIELD_NONE,
            bytesperline,
            sizeimage,
            0,
            0,
            0,
            0,
            0,
            0,
        )

        try:
            fcntl.ioctl(v4l2_fd, VIDIOC_S_FMT, fmt)
            logger.info(f"Set v4l2 format: {width}x{height} YUYV")
        except OSError as e:
            logger.warning(f"Failed to set v4l2 format via ioctl: {e}")

        # Test write to verify device is ready
        test_frame = np.zeros((config.height, config.width * 2), dtype=np.uint8)
        os.write(v4l2_fd, test_frame.tobytes())
        logger.info(f"v4l2 output initialized")

        # Initialize WebRTC streaming if enabled
        if self._enable_webrtc:
            try:
                from .intel_streaming import IntelStreamingPipeline
                from .intel_streaming import StreamConfig as StreamingConfig

                logger.info("Starting WebRTC preview server on ws://localhost:8765")
                logger.info("Using YUYV input format (zero-copy to VA-API encoder)")
                stream_config = StreamingConfig(
                    width=config.width,
                    height=config.height,
                    framerate=config.fps,
                    bitrate=4000,
                    encoder="va",
                    codec="h264",
                    signaling_port=8765,
                    flip=False,
                    v4l2_device=None,  # We push frames via appsrc, not v4l2
                    input_format="yuyv",  # Direct YUYV input - VA-API converts in hardware
                )
                self._webrtc_pipeline = IntelStreamingPipeline(stream_config)
                self._webrtc_pipeline.start(mode="webrtc")
                logger.info("WebRTC streaming initialized")
            except Exception as e:
                logger.warning(f"Failed to start WebRTC streaming: {e}")
                self._webrtc_pipeline = None

        try:
            while self._running:
                for attendee_idx, attendee in enumerate(attendees):
                    if not self._running:
                        break

                    duration = config.duration_per_person
                    logger.info(f"Streaming attendee {attendee_idx + 1}/{len(attendees)}: {attendee.name}")

                    # Stream frames using full GPU pipeline
                    await self._stream_gpu_pipeline(attendee, attendee_idx, len(attendees), duration, v4l2_fd)

                if not loop:
                    break
        finally:
            # Clean up
            if v4l2_fd is not None:
                os.close(v4l2_fd)

        logger.info("Real-time stream stopped")

    async def _stream_gpu_pipeline(
        self,
        attendee: Attendee,
        attendee_idx: int,
        total_attendees: int,
        duration: float,
        v4l2_fd: int,
    ) -> bool:
        """
        Stream frames using full GPU pipeline.

        Uses UltraLowCPURenderer for efficient GPU-accelerated rendering:
        - OpenGL renders text/shapes to base frame (~1x/second when content changes)
        - OpenCL applies waveform, progress bar, and YUYV conversion (every frame)
        - Target: ~13% CPU without audio, ~30% with audio+STT
        """
        config = self.config
        total_frames = int(duration * config.fps)
        frame_time = 1.0 / config.fps

        # Initialize GPU renderer if needed
        if not hasattr(self, "_ulc_renderer") or self._ulc_renderer is None:
            try:
                self._ulc_renderer = UltraLowCPURenderer(config, use_intel=config.prefer_intel_gpu)
                logger.info(f"UltraLowCPU renderer initialized: {self._ulc_renderer.device_name}")
            except Exception as e:
                logger.error(f"Failed to initialize GPU renderer: {e}")
                raise RuntimeError(f"GPU renderer required but failed to initialize: {e}")

        # Pre-compute attendee-specific data
        attendee_data = self._precompute_attendee_data(attendee)

        # Pre-select random data for this attendee
        tools = random.sample(RESEARCH_TOOLS, config.num_tools)
        findings = random.sample(FAKE_FINDINGS, config.num_findings)
        assessment = random.choice(THREAT_ASSESSMENTS)

        start_time = asyncio.get_event_loop().time()
        last_npu_update = -1
        last_history_len = 0
        current_history = self._stt_history.copy() if self._stt_enabled else []

        # Pre-render initial base frame
        base_frame = self._create_base_frame(
            attendee,
            attendee_idx,
            total_attendees,
            tools,
            findings,
            assessment,
            attendee_data,
            t=0.0,
            frame_num=0,
            transcript_history=current_history,
        )
        self._ulc_renderer.upload_base_frame(base_frame)

        for frame_num in range(total_frames):
            if not self._running:
                return False

            t = frame_num / config.fps
            progress = frame_num / total_frames

            # Get current transcript history
            current_history = self._stt_history.copy() if self._stt_enabled else []

            # Check if we need to update base frame (every second or transcript changed)
            current_second = int(t)
            history_changed = len(current_history) != last_history_len
            need_update = current_second != last_npu_update or history_changed

            if need_update:
                last_npu_update = current_second
                last_history_len = len(current_history)
                # Delete old base_frame before creating new one to help GC
                del base_frame
                # Re-render base frame with updated content
                base_frame = self._create_base_frame(
                    attendee,
                    attendee_idx,
                    total_attendees,
                    tools,
                    findings,
                    assessment,
                    attendee_data,
                    t=t,
                    frame_num=frame_num,
                    transcript_history=current_history,
                )
                self._ulc_renderer.upload_base_frame(base_frame)
                # Force GC after frame update to prevent memory buildup
                gc.collect()

            # Get audio bars if available
            audio_bars = None
            if frame_num % 60 == 0:
                # Log memory and state every ~5 seconds
                stt_buf_samples = self._stt_write_pos
                stt_history_len = len(self._stt_history) if self._stt_history else 0
                mem_mb = get_memory_mb()
                logger.info(
                    f"MEM: {mem_mb:.0f}MB | stt_buf: {stt_buf_samples}/{self._stt_buffer_size} samples | "
                    f"stt_history: {stt_history_len} | frame: {frame_num}"
                )
                # Warn if memory is growing dangerously
                if mem_mb > 3000:
                    logger.warning(f"HIGH MEMORY: {mem_mb:.0f}MB - running GC...")
                    gc.collect()
                if mem_mb > 4000:
                    logger.error(f"CRITICAL MEMORY: {mem_mb:.0f}MB - forcing cleanup")
                    self._stt_write_pos = 0  # Reset STT buffer
                    # Force full GC with all generations
                    gc.collect(0)
                    gc.collect(1)
                    gc.collect(2)
                else:
                    # Periodic GC every 5 seconds
                    gc.collect()
            if self._audio_capture and self._audio_buffer is not None:
                audio_bars = self._audio_buffer  # No copy needed - GPU upload copies it
                if audio_bars.max() <= audio_bars.min():
                    audio_bars = None
                elif frame_num % 60 == 0:
                    logger.info(
                        f"Audio bars: min={audio_bars.min():.3f}, max={audio_bars.max():.3f}, mean={audio_bars.mean():.3f}"
                    )

            # Render frame with GPU (waveform, progress bar, YUYV conversion)
            yuyv = self._ulc_renderer.render_frame(t, progress, audio_bars)

            # Write to v4l2
            try:
                os.write(v4l2_fd, memoryview(yuyv))
            except OSError as e:
                logger.warning(f"v4l2 write error: {e}")
                return False

            # Push to WebRTC if enabled (direct YUYV - zero CPU conversion)
            if self._webrtc_pipeline and self._webrtc_pipeline.is_running:
                try:
                    # Push YUYV directly - VA-API handles YUY2→NV12→H.264 in hardware
                    self._webrtc_pipeline.push_frame_yuyv(yuyv)
                except Exception as e:
                    if frame_num % 60 == 0:  # Log every ~5 seconds at 12fps
                        logger.warning(f"WebRTC push error: {e}")

            # Pace output to real-time
            elapsed = asyncio.get_event_loop().time() - start_time
            expected = (frame_num + 1) * frame_time
            if expected > elapsed:
                await asyncio.sleep(expected - elapsed)

        return True

    def _create_base_frame(
        self,
        attendee: Attendee,
        attendee_idx: int,
        total_attendees: int,
        tools: list,
        findings: list,
        assessment: str,
        attendee_data: dict,
        t: float = 0.0,
        frame_num: int = 0,
        transcript_history: list = None,
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
        text_items.append(("[ AI WORKFLOW COMMAND CENTER ]", c.left_margin, c.title_y, "green", "large"))

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
            f"Freq: 125-4000 Hz | Pitch: {random.randint(150, 220)} Hz",
            f"Cadence: {random.randint(120, 160)} wpm | Conf: {random.uniform(90, 99):.1f}%",
        ]
        for i, stat in enumerate(stats):
            if stat:  # Skip empty lines
                text_items.append(
                    (stat, voice_x, voice_y + 45 + i * 40, "orange", "medium")
                )  # doubled size + line height

        # === FACIAL RECOGNITION - TOP RIGHT === (+10pt bigger text)
        text_items.append(("FACIAL RECOGNITION", c.face_x, c.face_y - 10, "red", "large"))

        # === RIGHT COLUMN REMOVED - no more "BUILDING CONTEXT" ===

        # === NPU STATS (all GPU-rendered for consistent quality) ===
        # LARGER FONT - moved up to give more vertical space
        npu_header_y = c.npu_y + 18
        text_items.append(("[ INTEL NPU - METEOR LAKE ]", c.left_margin, npu_header_y, "cyan", "normal"))

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
        active_sec = npu["active_ms"] / 1000
        runtime_status = npu["runtime_status"].upper()

        # Distribute stats across 6 columns (fewer items per column = larger text fits)
        # Column 1 - NPU core stats
        col1_stats = [
            f"FREQ: {npu['freq_mhz']}/{npu['max_freq_mhz']} MHz",
            f"BUSY: {busy_sec:.2f}s",
            f"MEM: {mem_mb:.1f} MB",
        ]
        for i, stat in enumerate(col1_stats):
            text_items.append((stat, col_x[0], npu_stats_y + i * npu_line_h, "green", npu_size))

        # Column 2 - NPU utilization
        col2_stats = [
            f"UTIL: {util_pct}%",
            f"POWER: {npu['power_state']}",
            f"RUNTIME: {runtime_status}",
        ]
        for i, stat in enumerate(col2_stats):
            color = "cyan" if "ACTIVE" in stat else "green"
            text_items.append((stat, col_x[1], npu_stats_y + i * npu_line_h, color, npu_size))

        # Column 3 - Model info
        col3_stats = [
            "MODEL: whisper-int8",
            "PRECISION: INT8",
            "INPUT: 16kHz PCM",
        ]
        for i, stat in enumerate(col3_stats):
            text_items.append((stat, col_x[2], npu_stats_y + i * npu_line_h, "green", npu_size))

        # Column 4 - Counters
        col4_stats = [
            f"SAMPLES: {int(t * 16000)}",
            f"INFERENCES: {int(t * 2)}",
            f"FRAMES: {frame_num}",
        ]
        for i, stat in enumerate(col4_stats):
            text_items.append((stat, col_x[3], npu_stats_y + i * npu_line_h, "green", npu_size))

        # Column 5 - System stats
        col5_stats = [
            f"CPU: ~1%",
            f"GPU: Intel Arc",
            f"STT: {'ON' if self._stt_enabled else 'OFF'}",
        ]
        for i, stat in enumerate(col5_stats):
            color = "cyan" if "ON" in stat else "green"
            text_items.append((stat, col_x[4], npu_stats_y + i * npu_line_h, color, npu_size))

        # Column 6 - Telemetry
        throughput = 0.5 + (util_pct / 100) * 1.0
        col6_stats = [
            f"RATE: {max(1, int(util_pct / 5))} req/s",
            f"LATENCY: ~{50 + util_pct}ms",
            "STATUS: ACTIVE",
        ]
        for i, stat in enumerate(col6_stats):
            color = "cyan" if "ACTIVE" in stat else "green"
            text_items.append((stat, col_x[5], npu_stats_y + i * npu_line_h, color, npu_size))

        # Build shapes list for GPU rendering
        center_x = c.face_x + c.face_w // 2
        center_y = c.face_y + c.face_head_radius + 32  # +2px down

        shapes = [
            # Waveform box border
            ("rect", c.wave_x - 3, c.wave_y - 3, c.wave_w + 6, c.wave_h + 6, "dark_green", 1),
            # Face box
            ("rect", c.face_x, c.face_y, c.face_w, c.face_h, "dark_green", 1),
            # Silhouette head (circle)
            ("circle", center_x, center_y, c.face_head_radius, "green", 2),
            # Silhouette body (rectangle)
            (
                "rect",
                center_x - c.face_body_width,
                center_y + c.face_head_radius + 20,
                c.face_body_width * 2,
                c.face_y + c.face_h - 20 - (center_y + c.face_head_radius + 20),
                "green",
                2,
            ),
            # NPU divider line
            ("line", 0, c.npu_y, c.width, c.npu_y, "dark_green", 1),
            # Progress bar outline
            ("rect", c.progress_margin, c.progress_y, c.width - c.progress_margin * 2, c.progress_h, "dark_green", 1),
        ]

        # Render all text AND shapes with GPU in single pass
        frame = self._gpu_text_renderer.render_frame(text_items, shapes, (0, 0, 0))

        # NPU section - dark green background tint for Terminator look
        # (This is a pixel operation, keep it in numpy for now)
        npu_bg_y = c.npu_y + 1
        npu_bg_h = c.height - c.npu_y - 1
        frame[npu_bg_y : npu_bg_y + npu_bg_h, :, 1] = np.maximum(
            frame[npu_bg_y : npu_bg_y + npu_bg_h, :, 1], 17
        )  # Dark green tint

        return frame

    def _precompute_attendee_data(self, attendee: Attendee) -> dict:
        """Pre-compute attendee-specific data to avoid per-frame string operations."""
        name_parts = attendee.name.split()
        first_name = name_parts[0].lower() if name_parts else "user"
        last_name = name_parts[-1].lower() if len(name_parts) > 1 else first_name
        username = f"{first_name[0]}{last_name}" if len(name_parts) > 1 else first_name
        email_domain = "redhat.com"

        return {
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
            "email_domain": email_domain,
            "voice_print_id": hash(attendee.name) % 99999,
            "tools": [
                f"ldap://query?uid={username}",
                f"jira://search?assignee={username}",
                f"gitlab://commits?author={username}@{email_domain}",
                f"slack://history?user={first_name}.{last_name}",
                f"confluence://pages?author={attendee.name.replace(' ', '+')}",
                f"workday://profile/{username}",
                f"google://calendar?email={username}@{email_domain}",
                f"deepface://match?name={attendee.name.replace(' ', '_')}",
            ],
        }

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
        attendee_data: dict = None,
        frame_buffer: np.ndarray = None,
    ) -> np.ndarray:
        """
        Generate a complete video frame using OpenCV (2-3x faster than PIL).

        Returns numpy array (H, W, 3) in BGR format for direct YUYV conversion.

        Args:
            frame_buffer: Optional pre-allocated buffer. If provided, copies base
                         frame into it instead of allocating new array.
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
            username = f"{first_name[0]}{last_name}" if len(name_parts) > 1 else first_name
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
        cv2.putText(frame, f"ANALYZING{dots}", (padding, 45), CV_FONT, font_small, CV_GREEN, thickness, CV_LINE_TYPE)

        # Person name (changes per attendee)
        cv2.putText(frame, attendee.name, (padding, 70), CV_FONT, font_medium, CV_WHITE, thickness, CV_LINE_TYPE)

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
        findings_start = len(realistic_tools[: config.num_tools]) * config.tool_display_time
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

        audio_data = self._audio_buffer
        has_audio = audio_data is not None

        # Calculate animated stats
        freq_peak = 180 + int(60 * math.sin(t * 0.7))
        formant_f1 = 500 + int(100 * math.sin(t * 0.5))
        formant_f2 = 1500 + int(200 * math.sin(t * 0.3))
        pitch_var = 12 + int(8 * math.sin(t * 0.9))

        # Left stats column
        voice_print_id = attendee_data["voice_print_id"] if attendee_data else hash(attendee.name) % 99999
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
            frame, vad_text, (right_stats_x, voice_stats_y + 28), CV_FONT, font_small, CV_GREEN, thickness, CV_LINE_TYPE
        )
        profile_color = (0, 255, 0) if t > 10 else CV_GREEN  # Bright green when complete
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

    def _build_base_filters(
        self,
        attendee: Attendee,
        attendee_idx: int,
        total_attendees: int,
        duration: float,
    ) -> list[str]:
        """Build FFmpeg filter list for base elements (used in hybrid mode)."""
        config = self.config
        filters = []

        # Header
        filters.append(f"drawtext=text='[ AI RESEARCH MODULE v2.1 ]':fontsize=32:fontcolor=cyan:x=30:y=15")

        return filters

    async def stream_live(
        self,
        video_device: str,
        timeout: float = 300.0,
    ) -> None:
        """
        Stream video with live attendee data from the meeting bot.

        Connects to the AttendeeDataService socket to receive real-time
        participant updates. Shows Matrix-style "INITIALIZING..." animation
        until participants are detected.

        Args:
            video_device: v4l2loopback device path
            timeout: Max time to wait for attendee service (seconds)
        """
        if not _attendee_client_available:
            raise RuntimeError("Live attendee client not available - missing dependencies")

        import fcntl
        import struct

        config = self.config
        self._running = True

        logger.info(f"Starting LIVE stream to {video_device}")

        # Initialize Matrix animation for scanning state
        matrix_anim = MatrixAnimation(config.width, config.height)

        # Create attendee client
        client = AttendeeDataClient()

        # State tracking
        current_attendees: list[EnrichedAttendee] = []
        current_index = 0
        meeting_status = "scanning"
        last_rotation_time = 0.0
        rotation_interval = config.duration_per_person  # 15 seconds

        # Callbacks for attendee updates
        def on_attendees_update(attendees: list[EnrichedAttendee]):
            nonlocal current_attendees, meeting_status
            current_attendees = attendees
            if attendees:
                meeting_status = "active"
            logger.info(f"Received {len(attendees)} attendees from service")

        def on_status_change(status: str):
            nonlocal meeting_status
            meeting_status = status
            logger.info(f"Meeting status changed: {status}")

        def on_attendee_enriched(index: int, attendee: EnrichedAttendee):
            nonlocal current_attendees
            if 0 <= index < len(current_attendees):
                current_attendees[index] = attendee
                logger.debug(f"Attendee {index} enriched: {attendee.name}")

        client.on_attendees_update(on_attendees_update)
        client.on_status_change(on_status_change)
        client.on_attendee_enriched(on_attendee_enriched)

        # Try to connect to attendee service
        logger.info("Connecting to AttendeeDataService...")
        connected = await client.connect(timeout=5.0)

        if connected:
            logger.info("Connected to AttendeeDataService")
            await client.request_state()
        else:
            logger.warning("AttendeeDataService not available - will retry")

        # Start audio capture if configured
        if self._audio_source:
            audio_started = await self._start_audio_capture()
            if audio_started:
                logger.info(f"Audio-reactive waveform enabled from {self._audio_source}")
                for i in range(200):
                    if self._audio_buffer is not None:
                        break
                    await asyncio.sleep(0.01)

        # Reset GPU renderer
        if hasattr(self, "_ulc_renderer") and self._ulc_renderer is not None:
            self._ulc_renderer = None

        # Kill any processes using the device
        try:
            subprocess.run(["sudo", "fuser", "-k", video_device], capture_output=True, timeout=5)
            await asyncio.sleep(0.5)
        except Exception:
            pass

        # Open v4l2 device
        v4l2_fd = os.open(video_device, os.O_RDWR)

        # Set video format
        VIDIOC_S_FMT = 0xC0D05605
        V4L2_BUF_TYPE_VIDEO_OUTPUT = 2
        V4L2_PIX_FMT_YUYV = 0x56595559
        V4L2_FIELD_NONE = 1

        width = config.width
        height = config.height
        bytesperline = width * 2
        sizeimage = bytesperline * height

        fmt = struct.pack(
            "II" + "IIIIIIII" + "II" + "II" + "152x",
            V4L2_BUF_TYPE_VIDEO_OUTPUT,
            0,
            width,
            height,
            V4L2_PIX_FMT_YUYV,
            V4L2_FIELD_NONE,
            bytesperline,
            sizeimage,
            0,
            0,
            0,
            0,
            0,
            0,
        )

        try:
            fcntl.ioctl(v4l2_fd, VIDIOC_S_FMT, fmt)
            logger.info(f"Set v4l2 format: {width}x{height} YUYV")
        except OSError as e:
            logger.warning(f"Failed to set v4l2 format: {e}")

        # Test write
        test_frame = np.zeros((height, width * 2), dtype=np.uint8)
        os.write(v4l2_fd, test_frame.tobytes())

        # Initialize WebRTC streaming if enabled
        if self._enable_webrtc:
            try:
                from .intel_streaming import IntelStreamingPipeline
                from .intel_streaming import StreamConfig as StreamingConfig

                logger.info("Starting WebRTC preview server on ws://localhost:8765")
                logger.info("Using YUYV input format (zero-copy to VA-API encoder)")
                stream_config = StreamingConfig(
                    width=config.width,
                    height=config.height,
                    framerate=config.fps,
                    bitrate=4000,
                    encoder="va",
                    codec="h264",
                    signaling_port=8765,
                    flip=False,
                    v4l2_device=None,
                    input_format="yuyv",
                )
                self._webrtc_pipeline = IntelStreamingPipeline(stream_config)
                self._webrtc_pipeline.start(mode="webrtc")
                logger.info("WebRTC streaming initialized")
            except Exception as e:
                logger.warning(f"Failed to start WebRTC streaming: {e}")
                self._webrtc_pipeline = None

        frame_time = 1.0 / config.fps
        reconnect_interval = 5.0
        last_reconnect_attempt = 0.0

        try:
            while self._running:
                loop_start = asyncio.get_event_loop().time()

                # Try to reconnect if disconnected
                if not client.is_connected():
                    if loop_start - last_reconnect_attempt > reconnect_interval:
                        last_reconnect_attempt = loop_start
                        if await client.connect(timeout=2.0):
                            logger.info("Reconnected to AttendeeDataService")
                            await client.request_state()

                # Determine what to render
                if meeting_status == "scanning" or not current_attendees:
                    # Render Matrix animation
                    frame = matrix_anim.render_frame(loop_start)

                    # Convert to YUYV
                    yuyv = bgr_to_yuyv_fast(frame)

                else:
                    # Render attendee view
                    # Handle rotation
                    if loop_start - last_rotation_time >= rotation_interval:
                        last_rotation_time = loop_start
                        current_index = (current_index + 1) % len(current_attendees)
                        await client.set_current_index(current_index)
                        logger.info(f"Rotated to attendee {current_index + 1}/{len(current_attendees)}")

                    # Get current attendee
                    attendee = current_attendees[current_index]

                    # Convert EnrichedAttendee to Attendee for existing rendering code
                    simple_attendee = Attendee(name=attendee.name)

                    # Use existing GPU pipeline for this frame
                    if not hasattr(self, "_ulc_renderer") or self._ulc_renderer is None:
                        try:
                            self._ulc_renderer = UltraLowCPURenderer(config, use_intel=config.prefer_intel_gpu)
                            logger.info(f"GPU renderer initialized: {self._ulc_renderer.device_name}")
                        except Exception as e:
                            logger.error(f"GPU renderer failed: {e}")
                            raise

                    # Pre-compute attendee data
                    attendee_data = self._precompute_attendee_data(simple_attendee)

                    # Add enriched data
                    if attendee.team:
                        attendee_data["team"] = attendee.team
                    if attendee.role:
                        attendee_data["role"] = attendee.role
                    if attendee.github_username:
                        attendee_data["github"] = attendee.github_username

                    # Select random data for display
                    tools = random.sample(RESEARCH_TOOLS, config.num_tools)
                    findings = random.sample(FAKE_FINDINGS, config.num_findings)
                    assessment = random.choice(THREAT_ASSESSMENTS)

                    # Get transcript history if STT enabled
                    current_history = self._stt_history.copy() if self._stt_enabled else []

                    # Calculate progress within this attendee's display time
                    time_in_attendee = loop_start - last_rotation_time
                    progress = time_in_attendee / rotation_interval

                    # Only update base frame once per second (not every frame!)
                    current_second = int(loop_start)
                    if not hasattr(self, "_last_base_frame_second") or self._last_base_frame_second != current_second:
                        self._last_base_frame_second = current_second
                        # Delete old frame if exists
                        if hasattr(self, "_cached_base_frame"):
                            del self._cached_base_frame
                        # Create base frame
                        self._cached_base_frame = self._create_base_frame(
                            simple_attendee,
                            current_index,
                            len(current_attendees),
                            tools,
                            findings,
                            assessment,
                            attendee_data,
                            t=loop_start,
                            frame_num=int(loop_start * config.fps),
                            transcript_history=current_history,
                        )
                        # Upload and force GC
                        self._ulc_renderer.upload_base_frame(self._cached_base_frame)
                        gc.collect()

                    # Get audio bars
                    audio_bars = self._audio_buffer if self._audio_buffer is not None else None

                    # Render with GPU
                    yuyv = self._ulc_renderer.render_frame(loop_start, progress, audio_bars)

                # Write frame
                os.write(v4l2_fd, memoryview(yuyv))

                # Push to WebRTC if enabled (direct YUYV - zero CPU conversion)
                if self._webrtc_pipeline and self._webrtc_pipeline.is_running:
                    try:
                        self._webrtc_pipeline.push_frame_yuyv(yuyv)
                    except Exception:
                        pass  # Don't spam logs

                # Maintain frame rate
                elapsed = asyncio.get_event_loop().time() - loop_start
                sleep_time = frame_time - elapsed
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

        finally:
            # Cleanup
            if v4l2_fd is not None:
                os.close(v4l2_fd)
            await client.disconnect()

        logger.info("Live stream stopped")

    async def stop_async(self):
        """Stop the real-time stream (async version)."""
        self._running = False

        # Stop audio capture
        if self._audio_capture:
            await self._audio_capture.stop()
            self._audio_capture = None

        # Stop WebRTC streaming
        if self._webrtc_pipeline:
            try:
                self._webrtc_pipeline.stop()
            except Exception:
                pass
            self._webrtc_pipeline = None

        # Reset state for clean restart
        self._audio_buffer = None
        if hasattr(self, "_ulc_renderer"):
            self._ulc_renderer = None

    def stop(self):
        """Stop the real-time stream."""
        self._running = False

        # Stop WebRTC streaming
        if self._webrtc_pipeline:
            try:
                self._webrtc_pipeline.stop()
            except Exception:
                pass
            self._webrtc_pipeline = None

        # Reset state for clean restart
        self._audio_buffer = None
        if hasattr(self, "_ulc_renderer"):
            self._ulc_renderer = None


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
if __name__ == "__main__":
    import atexit
    import signal
    import sys

    logging.basicConfig(level=logging.INFO)

    # Import shared video device module
    # Add project root to path for imports
    _project_root = Path(__file__).parent.parent.parent.parent.parent
    sys.path.insert(0, str(_project_root))

    from scripts.common.video_device import cleanup_device, get_active_device, set_active_fd, setup_v4l2_device

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
        print("  python -m tool_modules.aa_meet_bot.src.video_generator --realtime --audio SOURCE")
        print("  python -m tool_modules.aa_meet_bot.src.video_generator --realtime /dev/videoX  # Use specific device")
        print("  python -m tool_modules.aa_meet_bot.src.video_generator --live")
        print("  python -m tool_modules.aa_meet_bot.src.video_generator --file output.mp4")
        print("")
        print("Commands:")
        print("  --realtime      Stream to v4l2loopback device with hardcoded attendees")
        print("  --live          Stream with LIVE attendee data from meeting bot")
        print("  --file          Generate video file")
        print("")
        print("Options:")
        print("  --audio SOURCE  PulseAudio source for audio-reactive waveform")
        print("                  Use 'pactl list sources short' to find available sources")
        print("  --720p          Use 1280x720 resolution (default: 1920x1080)")
        print("  --nvidia        Use NVIDIA GPU instead of Intel iGPU")
        print("  --flip          Flip video horizontally (for Google Meet mirror compensation)")
        print("  --webrtc        Enable WebRTC streaming for preview (ws://localhost:8765)")
        print("")
        print("Live Mode:")
        print("  Connects to AttendeeDataService socket (~/.config/aa-workflow/meetbot.sock)")
        print("  Shows Matrix-style 'INITIALIZING...' until participants are detected")
        print("  Receives real participant names from Google Meet via the meeting bot")
        print("")
        print("WebRTC Preview:")
        print("  With --webrtc, frames are pushed to a WebRTC server on port 8765")
        print("  Connect from the Meetings tab Video Preview (select WebRTC mode)")
        print("")
        print("The device is automatically created/configured. Press Ctrl+C to stop and release.")
        print("")
        print("Architecture:")
        print("  Full GPU pipeline: OpenGL (text/shapes) + OpenCL (color conversion)")
        print("  Target: ~1% CPU utilization at 1080p")

    async def main():
        global _active_device_path

        # Check for command line args
        if len(sys.argv) > 1:
            if sys.argv[1] == "--stream" and len(sys.argv) > 2:
                # Stream to v4l2loopback device (uses pre-rendered overlays)
                video_device = sys.argv[2]
                attendees = load_attendees_from_file(DEFAULT_ATTENDEES_FILE)
                if not attendees:
                    print(f"No attendees found in {DEFAULT_ATTENDEES_FILE}", file=sys.stderr)
                    return
                print(f"Streaming to {video_device} with {len(attendees)} attendees...", file=sys.stderr)
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
                    print(f"No attendees found in {DEFAULT_ATTENDEES_FILE}", file=sys.stderr)
                    return
                print(f"Real-time streaming to {video_device} with {len(attendees)} attendees...", file=sys.stderr)
                if audio_source:
                    print(f"Audio-reactive waveform from: {audio_source}", file=sys.stderr)
                else:
                    print("Using simulated waveform (no audio source)", file=sys.stderr)
                print("Press Ctrl+C to stop", file=sys.stderr)

                # Check for WebRTC streaming option
                use_webrtc = "--webrtc" in sys.argv
                if use_webrtc:
                    print("WebRTC preview enabled on ws://localhost:8765", file=sys.stderr)

                renderer = RealtimeVideoRenderer(config=config, audio_source=audio_source, enable_webrtc=use_webrtc)
                try:
                    await renderer.stream_realtime(attendees, video_device, loop=True)
                finally:
                    await renderer.stop_async()

            elif sys.argv[1] == "--live":
                # LIVE mode - get attendees from meeting bot via socket

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

                # Resolution options
                use_720p = "--720p" in sys.argv
                use_nvidia = "--nvidia" in sys.argv

                # Check for --flip option (horizontal mirror for Google Meet)
                use_flip = "--flip" in sys.argv

                if use_720p:
                    width, height = 1280, 720
                    config = VideoConfig.hd_720p()
                    print("Using 720p resolution (1280x720)", file=sys.stderr)
                else:
                    width, height = 1920, 1080
                    config = VideoConfig()
                    print("Using 1080p resolution (1920x1080)", file=sys.stderr)

                # Auto-setup device if not specified
                if video_device is None:
                    video_device = setup_v4l2_device(width, height)
                else:
                    print(f"Using specified device: {video_device}", file=sys.stderr)
                    setup_v4l2_device(width, height)

                _active_device_path = video_device

                config.prefer_intel_gpu = not use_nvidia
                gpu_name = "NVIDIA" if use_nvidia else "Intel iGPU"
                print(f"Using full GPU pipeline on {gpu_name}", file=sys.stderr)

                # Set flip mode
                if use_flip:
                    os.environ["FLIP"] = "1"
                    print("Horizontal flip ENABLED (for Google Meet)", file=sys.stderr)

                print(f"LIVE streaming to {video_device}...", file=sys.stderr)
                print("Connecting to AttendeeDataService for live participant data...", file=sys.stderr)
                print("Shows Matrix 'INITIALIZING...' until meeting participants detected", file=sys.stderr)
                if audio_source:
                    print(f"Audio-reactive waveform from: {audio_source}", file=sys.stderr)
                print("Press Ctrl+C to stop", file=sys.stderr)

                # Check for WebRTC streaming option
                use_webrtc = "--webrtc" in sys.argv
                if use_webrtc:
                    print("WebRTC preview enabled on ws://localhost:8765", file=sys.stderr)

                renderer = RealtimeVideoRenderer(config=config, audio_source=audio_source, enable_webrtc=use_webrtc)
                try:
                    await renderer.stream_live(video_device)
                finally:
                    await renderer.stop_async()

            elif sys.argv[1] == "--file":
                # Generate to file
                output_path = sys.argv[2] if len(sys.argv) > 2 else "research_video.mp4"
                attendees = load_attendees_from_file(DEFAULT_ATTENDEES_FILE)
                if not attendees:
                    print(f"No attendees found in {DEFAULT_ATTENDEES_FILE}", file=sys.stderr)
                    return
                generator = ResearchVideoGenerator()
                path = await generator.generate_video_file(attendees, Path(output_path))
                print(f"Generated: {path}", file=sys.stderr)

            elif sys.argv[1] == "--stdout":
                # Stream to stdout as matroska (pipe-friendly format)
                attendees = load_attendees_from_file(DEFAULT_ATTENDEES_FILE)
                if not attendees:
                    print(f"No attendees found in {DEFAULT_ATTENDEES_FILE}", file=sys.stderr)
                    return
                print(f"Streaming {len(attendees)} attendees to stdout...", file=sys.stderr)
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
                print(f"Loaded {len(attendees)} attendees from {DEFAULT_ATTENDEES_FILE}")
                generator = ResearchVideoGenerator()
                path = await generator.generate_video_file(attendees, Path("test_research.mp4"))
                print(f"Generated: {path}")
            else:
                # Fallback to example names
                names = ["John Smith", "Jane Doe", "Bob Wilson"]
                path = await generate_research_video(names, Path("test_research.mp4"))
                print(f"Generated: {path}")

    asyncio.run(main())
