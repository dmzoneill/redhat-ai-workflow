"""Video-overlay text renderer built on :class:`GPUTextRenderer`."""

import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from tool_modules.aa_meet_bot.src.gpu_text import GPUTextRenderer, gpu_libraries, logger

_gpu = gpu_libraries()


class VideoTextRenderer:  # pylint: disable=too-many-instance-attributes
    """High-level text renderer optimized for video generation.

    Features:
    - Auto-detects monospace fonts
    - Multiple font sizes for different text elements
    - Caches rendered frames for reuse
    - Thread-safe initialization

    Usage:
        renderer = VideoTextRenderer(1920, 1080)

        # Render a complete frame with all text
        frame = renderer.render_frame([
            TextItem("TITLE", 100, 50, "cyan", "large"),
            TextItem("Status: OK", 100, 100, "green", "normal"),
            TextItem("Details...", 100, 130, "green", "small"),
        ])
    """

    # Standard monospace fonts to try
    FONT_PATHS = [
        "/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono.tt",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.tt",
        "/usr/share/fonts/liberation-mono/LiberationMono-Regular.tt",
        "/usr/share/fonts/google-noto-vf/NotoSansMono[wght].ttf",
    ]

    # Color presets (RGB)
    COLORS = {
        "green": (0, 255, 0),
        "dark_green": (0, 100, 0),
        "cyan": (0, 255, 255),
        "yellow": (255, 255, 0),
        "orange": (255, 165, 0),
        "red": (255, 0, 0),
        "white": (255, 255, 255),
        "gray": (128, 128, 128),
    }

    def __init__(
        self,
        width: int,
        height: int,
        font_sizes: Optional[Dict[str, int]] = None,
    ):
        """Initialize video text renderer.

        Args:
            width: Frame width
            height: Frame height
            font_sizes: Dict mapping size names to pixel sizes.
                       Default: {"large": 24, "normal": 16, "small": 12}
        """
        self.width = width
        self.height = height
        self._renderer: Optional[GPUTextRenderer] = None
        self._initialized = False
        self._font_path: Optional[str] = None
        self._output_buffer: Optional[np.ndarray] = None
        self._rgba_buffer: Optional[np.ndarray] = None

        # Font size presets
        self.font_sizes = font_sizes or {
            "large": 24,
            "normal": 16,
            "small": 12,
            "tiny": 10,
        }

        # Find available font
        for path in self.FONT_PATHS:
            if Path(path).exists():
                self._font_path = path
                break

        if not self._font_path:
            logger.warning("No suitable monospace font found for GPU text rendering")

    def initialize(self) -> bool:
        """Initialize the renderer (lazy init on first use)."""
        if self._initialized:
            return True

        if not self._font_path:
            return False

        try:
            # Single renderer with all font sizes pre-loaded
            self._renderer = GPUTextRenderer(self.width, self.height, headless=True)
            if not self._renderer.initialize():
                return False

            # Pre-load all font sizes into the same renderer
            for name, size in self.font_sizes.items():
                if self._renderer.load_font(self._font_path, size):
                    logger.debug("Loaded font size %s=%s", name, size)
                else:
                    logger.warning("Failed to load font size %s=%s", name, size)

            self._initialized = True
            # Pre-allocate output buffer to avoid repeated allocations
            self._output_buffer = np.zeros((self.height, self.width, 3), dtype=np.uint8)
            self._rgba_buffer = np.zeros((self.height, self.width, 4), dtype=np.uint8)
            logger.info("VideoTextRenderer initialized: %sx%s", self.width, self.height)
            return True

        except Exception as exc:  # pylint: disable=broad-exception-caught
            # GPU init failure should leave the overlay renderer unused.
            logger.error("Failed to initialize VideoTextRenderer: %s", exc)
            return False

    def render_text_items(
        self,
        items: List[Tuple[str, int, int, str, str]],
        background: Tuple[int, int, int] = (0, 0, 0),
    ) -> np.ndarray:
        """Render text items to BGR frame.

        Args:
            items: List of (text, x, y, color_name, size_name) tuples
                   color_name: "green", "cyan", "yellow", "red", "white"
                   size_name: "large", "normal", "small", "tiny"
            background: Background color (R, G, B)

        Returns:
            BGR numpy array (height, width, 3)
        """
        if not self._initialized:
            if not self.initialize():
                # Fallback: return black frame
                return np.zeros((self.height, self.width, 3), dtype=np.uint8)

        renderer = self._renderer
        font_path = self._font_path
        output = self._output_buffer
        rgba = self._rgba_buffer
        if renderer is None or font_path is None or output is None or rgba is None:
            return np.zeros((self.height, self.width, 3), dtype=np.uint8)

        # Render all text in a single OpenGL pass.
        _gpu.glfw.make_context_current(renderer.window)
        _gpu.gl.glBindFramebuffer(_gpu.gl.GL_FRAMEBUFFER, renderer.framebuffer)
        _gpu.gl.glViewport(0, 0, self.width, self.height)

        _gpu.gl.glClearColor(
            background[0] / 255.0, background[1] / 255.0, background[2] / 255.0, 1.0
        )
        _gpu.gl.glClear(_gpu.gl.GL_COLOR_BUFFER_BIT)
        self._draw_text_items(items)

        _gpu.gl.glReadPixels(
            0,
            0,
            self.width,
            self.height,
            _gpu.gl.GL_RGBA,
            _gpu.gl.GL_UNSIGNED_BYTE,
            rgba,
        )
        _gpu.gl.glBindFramebuffer(_gpu.gl.GL_FRAMEBUFFER, 0)
        np.copyto(output[:, :, 0], np.flipud(rgba[:, :, 2]))
        np.copyto(output[:, :, 1], np.flipud(rgba[:, :, 1]))
        np.copyto(output[:, :, 2], np.flipud(rgba[:, :, 0]))
        return output

    def render_frame(
        self,
        text_items: List[Tuple[str, int, int, str, str]],
        shapes: Optional[List[Tuple[Any, ...]]] = None,
        background: Tuple[int, int, int] = (0, 0, 0),
    ) -> np.ndarray:
        """Render text and shapes to BGR frame in a single OpenGL pass.

        Args:
            text_items: List of (text, x, y, color_name, size_name) tuples
            shapes: List of shape tuples:
                   ("rect", x, y, w, h, color_name, thickness) - rectangle outline
                   ("filled_rect", x, y, w, h, color_name) - filled rectangle
                   ("line", x1, y1, x2, y2, color_name, thickness) - line
                   ("circle", cx, cy, radius, color_name, thickness) - circle outline
            background: Background color (R, G, B)

        Returns:
            BGR numpy array (height, width, 3)
        """
        if not self._initialized:
            if not self.initialize():
                return np.zeros((self.height, self.width, 3), dtype=np.uint8)

        shapes = shapes or []
        renderer = self._renderer
        output = self._output_buffer
        rgba = self._rgba_buffer
        if renderer is None or output is None or rgba is None:
            return np.zeros((self.height, self.width, 3), dtype=np.uint8)

        # Set up OpenGL context
        _gpu.glfw.make_context_current(renderer.window)
        _gpu.gl.glBindFramebuffer(_gpu.gl.GL_FRAMEBUFFER, renderer.framebuffer)
        _gpu.gl.glViewport(0, 0, self.width, self.height)

        # Clear with background
        _gpu.gl.glClearColor(
            background[0] / 255.0, background[1] / 255.0, background[2] / 255.0, 1.0
        )
        _gpu.gl.glClear(_gpu.gl.GL_COLOR_BUFFER_BIT)

        self._draw_shapes(shapes)
        self._draw_text_items(text_items)

        # Single readback at the end - use pre-allocated buffer
        _gpu.gl.glReadPixels(
            0,
            0,
            self.width,
            self.height,
            _gpu.gl.GL_RGBA,
            _gpu.gl.GL_UNSIGNED_BYTE,
            rgba,
        )

        _gpu.gl.glBindFramebuffer(_gpu.gl.GL_FRAMEBUFFER, 0)

        # Convert RGBA to BGR in-place using pre-allocated buffer
        np.copyto(output[:, :, 0], np.flipud(rgba[:, :, 2]))
        np.copyto(output[:, :, 1], np.flipud(rgba[:, :, 1]))
        np.copyto(output[:, :, 2], np.flipud(rgba[:, :, 0]))

        return output

    def _draw_shapes(self, shapes: List[Tuple[Any, ...]]) -> None:
        """Draw overlay primitives behind the text."""
        renderer = self._renderer
        if renderer is None:
            return
        for shape in shapes:
            kind = shape[0]
            color_name = shape[-2] if kind in ("rect", "line", "circle") else shape[-1]
            color = self.COLORS.get(color_name, (0, 255, 0))
            if kind == "rect":
                renderer.draw_rectangle(
                    shape[1], shape[2], shape[3], shape[4], color, thickness=shape[6]
                )
            elif kind == "filled_rect":
                renderer.draw_filled_rectangle(
                    shape[1], shape[2], shape[3], shape[4], color
                )
            elif kind == "line":
                renderer.draw_line(
                    shape[1], shape[2], shape[3], shape[4], color, thickness=shape[6]
                )
            elif kind == "circle":
                renderer.draw_circle(
                    shape[1], shape[2], shape[3], color, thickness=shape[5]
                )

    def _draw_text_items(
        self, text_items: List[Tuple[str, int, int, str, str]]
    ) -> None:
        """Draw text grouped by font size."""
        renderer = self._renderer
        font_path = self._font_path
        if renderer is None or font_path is None:
            return
        _gpu.gl.glUseProgram(renderer.shader_program)
        items_by_size: Dict[str, List[Tuple[str, int, int, Tuple[int, int, int]]]] = {}
        for text, x_pos, y_pos, color_name, size_name in text_items:
            color = self.COLORS.get(color_name, (0, 255, 0))
            size_name = size_name if size_name in self.font_sizes else "normal"
            items_by_size.setdefault(size_name, []).append((text, x_pos, y_pos, color))
        for size_name, size_items in items_by_size.items():
            size = self.font_sizes.get(size_name, 16)
            renderer.load_font(font_path, size)
            atlas = renderer.current_atlas
            if atlas is None:
                continue
            _gpu.gl.glActiveTexture(_gpu.gl.GL_TEXTURE0)
            _gpu.gl.glBindTexture(_gpu.gl.GL_TEXTURE_2D, atlas.texture_id)
            for text, x_pos, y_pos, color in size_items:
                renderer.render_string(text, x_pos, y_pos, color)

    def composite_onto_frame(
        self, frame: np.ndarray, items: List[Tuple[str, int, int, str, str]]
    ) -> np.ndarray:
        """Composite text onto existing BGR frame.

        Args:
            frame: Existing BGR frame
            items: List of (text, x, y, color_name, size_name) tuples

        Returns:
            BGR frame with text composited
        """
        if not self._initialized:
            if not self.initialize():
                return frame

        # Render text with transparent background
        text_frame = self.render_text_items(items, (0, 0, 0))

        # Simple composite: where text is non-black, use text
        # This is fast but doesn't handle anti-aliasing perfectly
        mask = np.any(text_frame > 10, axis=2, keepdims=True)
        return np.where(mask, text_frame, frame)

    def cleanup(self):
        """Release resources."""
        if self._renderer:
            self._renderer.cleanup()
        self._renderer = None
        self._initialized = False

    def __del__(self):
        self.cleanup()


# Convenience function for quick text rendering
def render_text_gpu(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    width: int,
    height: int,
    text_items: List[Tuple[str, int, int, Tuple[int, int, int]]],
    font_path: str = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.tt",
    font_size: int = 16,
    background: Tuple[int, int, int] = (0, 0, 0),
) -> np.ndarray:
    """One-shot GPU text rendering.

    For repeated rendering, use GPUTextRenderer class directly.
    """
    renderer = GPUTextRenderer(width, height)
    try:
        renderer.load_font(font_path, font_size)
        return renderer.render_text(text_items, (*background, 255))[:, :, :3]
    finally:
        renderer.cleanup()


def _demo() -> None:
    """Manual benchmark for the GPU text renderer."""
    print("Testing GPU text renderer...")

    # Find a monospace font
    font_paths = [
        "/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono.tt",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.tt",
        "/usr/share/fonts/google-droid-sans-mono-fonts/DroidSansMono.tt",
        "/usr/share/fonts/liberation-mono/LiberationMono-Regular.tt",
        "/usr/share/fonts/google-noto-vf/NotoSansMono[wght].tt",
    ]

    chosen_font = None
    for candidate in font_paths:
        if Path(candidate).exists():
            chosen_font = candidate
            break

    if not chosen_font:
        print("No suitable font found!")
        sys.exit(1)

    print(f"Using font: {chosen_font}")

    demo_renderer = GPUTextRenderer(1280, 720, headless=True)

    if not demo_renderer.initialize():
        print("Failed to initialize renderer")
        sys.exit(1)

    if not demo_renderer.load_font(chosen_font, 16):
        print("Failed to load font")
        sys.exit(1)

    # Benchmark
    demo_items = [
        ("[ AI RESEARCH MODULE v2.1 ]", 35, 50, (0, 255, 0)),
        ("ANALYZING: John Smith", 35, 80, (0, 255, 0)),
        ("> Scanning LinkedIn profile...", 35, 110, (0, 200, 0)),
        ("> Cross-referencing GitHub...", 35, 130, (0, 200, 0)),
        ("> Building context graph...", 35, 150, (0, 200, 0)),
        ("[+] Found 47 connections", 35, 180, (0, 255, 255)),
        ("[+] Identified 12 projects", 35, 200, (0, 255, 255)),
        ("THREAT LEVEL: MINIMAL", 35, 230, (255, 255, 0)),
        ("FACIAL RECOGNITION", 800, 50, (255, 0, 0)),
        ("BUILDING CONTEXT", 1000, 80, (255, 0, 0)),
    ]

    # Warmup
    for _ in range(5):
        demo_frame = demo_renderer.render_text(demo_items, (0, 0, 0, 255))

    benchmark_iterations = 100
    start = time.perf_counter()
    for _ in range(benchmark_iterations):
        demo_frame = demo_renderer.render_text(demo_items, (0, 0, 0, 255))
    elapsed = time.perf_counter() - start

    fps = benchmark_iterations / elapsed
    ms_per_frame = (elapsed / benchmark_iterations) * 1000

    print("\nBenchmark results:")
    print("  Resolution: 1280x720")
    print(f"  Text items: {len(demo_items)}")
    print(f"  Time per frame: {ms_per_frame:.2f}ms")
    print(f"  Potential FPS: {fps:.1f}")
    print(f"  Frame shape: {demo_frame.shape}")

    # cv2 is only needed to write the demo image.
    import tempfile  # pylint: disable=import-outside-toplevel

    import cv2  # pylint: disable=import-outside-toplevel

    bgr = cv2.cvtColor(demo_frame, cv2.COLOR_RGBA2BGR)
    output_path = str(Path(tempfile.gettempdir()) / "gpu_text_test.png")
    cv2.imwrite(output_path, bgr)
    print(f"\nSaved test image to {output_path}")

    demo_renderer.cleanup()
    print("Done!")


if __name__ == "__main__":
    _demo()
