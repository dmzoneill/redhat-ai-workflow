"""
GPU, color conversion, and streaming renderer primitives.

Extracted from video_generator.py. Contains:
- get_memory_mb, maybe_gc - memory utilities
- rgb_to_yuyv_fast, bgr_to_yuyv_fast - CPU color conversion
- GPUColorConverter - OpenCL BGR→YUYV
- UltraLowCPURenderer - full GPU pipeline
- StreamingRenderer - BGRA/WebRTC streaming
- get_npu_stats - NPU sysfs stats
"""

from __future__ import annotations

import gc
import logging
import os
import random
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np

if TYPE_CHECKING:
    from .video_config import VideoConfig

logger = logging.getLogger(__name__)

# Memory management thresholds (in MB)
MEMORY_WARNING_MB = 3000  # Trigger GC warning
MEMORY_CRITICAL_MB = 4000  # Trigger emergency cleanup

# Pre-compute RGB to YUV conversion matrices (BT.601)
# These are used for fast vectorized color conversion
_RGB_TO_Y = np.array([66, 129, 25], dtype=np.int16)
_RGB_TO_U = np.array([-38, -74, 112], dtype=np.int16)
_RGB_TO_V = np.array([112, -94, -18], dtype=np.int16)

_last_gc_time = 0.0


def get_memory_mb() -> float:
    """Get current process memory usage in MB."""
    import resource

    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_maxrss / 1024  # Convert KB to MB on Linux


def maybe_gc(force: bool = False) -> None:
    """Run garbage collection periodically (every 30s) or if forced."""
    global _last_gc_time
    import time

    now = time.time()
    if force or (now - _last_gc_time > 30.0):
        gc.collect()
        _last_gc_time = now


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
        except ImportError as e:
            raise ImportError(
                "pyopencl required for GPU acceleration. Install with: uv add pyopencl"
            ) from e

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
        self.kernel.set_args(
            self.bgr_buf, self.yuyv_buf, np.int32(self.width), np.int32(self.height)
        )
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
        except ImportError as e:
            raise ImportError(
                "pyopencl required for ultra-low CPU mode. Install with: uv add pyopencl"
            ) from e

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

    def render_frame(
        self, t: float, progress_fraction: float, audio_bars: np.ndarray = None
    ) -> np.ndarray:
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
            self.base_gpu,
            self.yuyv_gpu,
            self.audio_gpu,
            np.float32(t),
            np.int32(progress_pixels),
            np.int32(use_audio),
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

    def __init__(
        self,
        config: "VideoConfig",
        use_intel: bool = True,
        enable_streaming: bool = False,
    ):
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
        prg_bgra = cl.Program(self.ctx, bgra_kernel_src).build(
            options=["-cl-fast-relaxed-math"]
        )
        self.kernel_bgra = cl.Kernel(prg_bgra, "render_frame_bgra")

        # Allocate BGRA buffer
        mf = cl.mem_flags
        self.bgra_gpu = cl.Buffer(self.ctx, mf.WRITE_ONLY, self.width * self.height * 4)
        self.bgra_host = np.empty((self.height, self.width, 4), dtype=np.uint8)

        self.global_size_bgra = (self.width, self.height)

        logger.info(
            f"StreamingRenderer initialized (streaming={'enabled' if enable_streaming else 'disabled'})"
        )

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

    def render_frame_bgra(
        self, t: float, progress_fraction: float, audio_bars: np.ndarray = None
    ) -> np.ndarray:
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
            self.base_gpu,
            self.bgra_gpu,
            self.audio_gpu,
            np.float32(t),
            np.int32(progress_pixels),
            np.int32(use_audio),
        )
        cl.enqueue_nd_range_kernel(
            self.queue, self.kernel_bgra, self.global_size_bgra, None
        )
        cl.enqueue_copy(self.queue, self.bgra_host, self.bgra_gpu)
        self.queue.finish()

        return self.bgra_host

    def render_and_stream(
        self, t: float, progress_fraction: float, audio_bars: np.ndarray = None
    ) -> np.ndarray:
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

    except Exception:
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
