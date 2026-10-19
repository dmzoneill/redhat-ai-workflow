"""GPU-accelerated text rendering using OpenGL + FreeType.

Renders smooth anti-aliased text entirely on the GPU with minimal CPU overhead.
Uses a glyph atlas texture for efficient character rendering.

"""

import logging
import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from tool_modules.aa_meet_bot.src import gpu_shaders as _shaders

# Set before the optional OpenGL import in _ensure_imports.
os.environ.setdefault("PYOPENGL_PLATFORM", "glx")

logger = logging.getLogger(__name__)


class _OptionalGl:  # pylint: disable=too-few-public-methods
    """Optional OpenGL libraries, filled in by _ensure_imports."""

    glfw: Any
    gl: Any
    freetype: Any

    def __init__(self) -> None:
        self.glfw = None
        self.gl = None
        self.freetype = None


_gpu = _OptionalGl()


def gpu_libraries() -> _OptionalGl:
    """Return the lazily loaded OpenGL library holder."""
    return _gpu


def _ensure_imports() -> None:
    """Import OpenGL and FreeType on first use.

    These native packages are optional. Importing them at module import
    would make every Meet bot import fail on machines without a GPU stack.
    """
    if _gpu.glfw is not None:
        return
    try:
        import freetype as ft_mod  # pylint: disable=import-outside-toplevel
        import glfw as glfw_mod  # pylint: disable=import-outside-toplevel
        import OpenGL.GL as gl_mod  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        raise ImportError(
            "GPU text rendering requires: uv add PyOpenGL PyOpenGL_accelerate freetype-py glfw"
        ) from exc
    _gpu.glfw = glfw_mod
    _gpu.gl = gl_mod
    _gpu.freetype = ft_mod


@dataclass
class Glyph:  # pylint: disable=too-many-instance-attributes
    """Information about a single glyph in the atlas.

    Each field is a distinct FreeType glyph metric and stays separate so
    the atlas packer can read them without unpacking a nested structure.
    """

    char: str
    texture_x: int  # X position in atlas
    texture_y: int  # Y position in atlas
    width: int  # Glyph width in pixels
    height: int  # Glyph height in pixels
    bearing_x: int  # Offset from cursor to left edge
    bearing_y: int  # Offset from baseline to top
    advance: int  # Horizontal advance to next character


@dataclass
class FontAtlas:
    """A texture atlas containing all glyphs for a font at a specific size."""

    texture_id: int
    width: int
    height: int
    glyphs: Dict[str, Glyph] = field(default_factory=dict)
    font_size: int = 16
    line_height: int = 20


def _pack_ascii_glyphs(face, atlas, atlas_data, char_height, atlas_width):
    """Rasterize ASCII 32-126 into ``atlas`` and ``atlas_data``."""
    cursor_x, cursor_y = 0, 0
    for code in range(32, 127):
        char = chr(code)
        face.load_char(char, _gpu.freetype.FT_LOAD_RENDER)
        glyph = face.glyph
        bitmap = glyph.bitmap
        if cursor_x + bitmap.width + 2 > atlas_width:
            cursor_x = 0
            cursor_y += char_height
        if bitmap.width > 0 and bitmap.rows > 0:
            bitmap_array = np.array(bitmap.buffer, dtype=np.uint8).reshape(
                bitmap.rows, bitmap.width
            )
            atlas_data[
                cursor_y : cursor_y + bitmap.rows, cursor_x : cursor_x + bitmap.width
            ] = bitmap_array
        atlas.glyphs[char] = Glyph(
            char=char,
            texture_x=cursor_x,
            texture_y=cursor_y,
            width=bitmap.width,
            height=bitmap.rows,
            bearing_x=glyph.bitmap_left,
            bearing_y=glyph.bitmap_top,
            advance=glyph.advance.x >> 6,
        )
        cursor_x += bitmap.width + 2


def _glyph_quad_vertices(glyph, cursor_x, baseline_y, atlas):
    """Return the 6-vertex quad for one glyph and the next cursor x."""
    xpos = cursor_x + glyph.bearing_x
    ypos = baseline_y + (atlas.font_size - glyph.bearing_y)
    width = glyph.width
    height = glyph.height
    tex_x = glyph.texture_x / atlas.width
    tex_y = glyph.texture_y / atlas.height
    tex_w = glyph.width / atlas.width
    tex_h = glyph.height / atlas.height
    quad = [
        xpos,
        ypos,
        tex_x,
        tex_y,
        xpos,
        ypos + height,
        tex_x,
        tex_y + tex_h,
        xpos + width,
        ypos + height,
        tex_x + tex_w,
        tex_y + tex_h,
        xpos,
        ypos,
        tex_x,
        tex_y,
        xpos + width,
        ypos + height,
        tex_x + tex_w,
        tex_y + tex_h,
        xpos + width,
        ypos,
        tex_x + tex_w,
        tex_y,
    ]
    return quad, cursor_x + glyph.advance


class GPUTextRenderer:  # pylint: disable=too-many-instance-attributes
    """Renders anti-aliased text on the GPU using OpenGL.

    The instance attributes are the OpenGL object graph (window, shaders,
    buffers, atlases). They stay as attributes so each GL name can be bound
    and deleted on its own.

    Usage:
        renderer = GPUTextRenderer(1920, 1080)
        renderer.load_font("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.tt", 16)

        # Render text to numpy array
        frame = renderer.render_text_to_array([
            ("Hello World", 100, 100, (0, 255, 0)),
            ("Status: OK", 100, 130, (0, 255, 255)),
        ])

        # Or composite onto existing frame
        renderer.composite_text(existing_frame, [
            ("Dynamic text", 50, 50, (0, 255, 0)),
        ])
    """

    def __init__(self, width: int, height: int, headless: bool = True):
        """Initialize GPU text renderer.

        Args:
            width: Frame width in pixels
            height: Frame height in pixels
            headless: If True, use offscreen rendering (no window)
        """
        _ensure_imports()

        self.width = width
        self.height = height
        self.headless = headless
        self._initialized = False
        self._window = None
        self._shader_program = None
        self._vao = None
        self._vbo = None
        self._fbo = None
        self._fbo_texture = None
        self._font_atlases: Dict[Tuple[str, int], FontAtlas] = {}
        self._current_atlas: Optional[FontAtlas] = None
        self._shape_shader_program = None
        self._shape_vao = None
        self._shape_vbo = None

    @property
    def window(self) -> Any:
        """GLFW window used by this renderer."""
        return self._window

    @property
    def framebuffer(self) -> Any:
        """Offscreen framebuffer object name."""
        return self._fbo

    @property
    def shader_program(self) -> Any:
        """Linked text shader program."""
        return self._shader_program

    @property
    def current_atlas(self) -> Optional[FontAtlas]:
        """Glyph atlas bound for the current font size."""
        return self._current_atlas

    def render_string(
        self, text: str, x: int, y: int, color: Tuple[int, int, int]
    ) -> None:
        """Draw one string with the currently loaded font."""
        self._render_string(text, x, y, color)

    def initialize(self) -> bool:
        """Initialize OpenGL context and resources."""
        if self._initialized:
            return True

        try:
            # Initialize GLFW with X11 platform (required for headless rendering on Linux)
            try:
                _gpu.glfw.init_hint(_gpu.glfw.PLATFORM, _gpu.glfw.PLATFORM_X11)
            except (
                AttributeError,
                OSError,
                RuntimeError,
                TypeError,
                ValueError,
            ) as exc:
                logger.warning("Could not set X11 platform hint: %s", exc)

            if not _gpu.glfw.init():
                raise RuntimeError("Failed to initialize GLFW")

            logger.debug("GLFW initialized, platform: %s", _gpu.glfw.get_platform())

            # Configure for offscreen rendering
            _gpu.glfw.window_hint(
                _gpu.glfw.VISIBLE, _gpu.glfw.FALSE if self.headless else _gpu.glfw.TRUE
            )
            _gpu.glfw.window_hint(_gpu.glfw.CONTEXT_VERSION_MAJOR, 3)
            _gpu.glfw.window_hint(_gpu.glfw.CONTEXT_VERSION_MINOR, 3)
            _gpu.glfw.window_hint(
                _gpu.glfw.OPENGL_PROFILE, _gpu.glfw.OPENGL_CORE_PROFILE
            )

            # Create window (hidden for offscreen)
            self._window = _gpu.glfw.create_window(
                self.width, self.height, "GPUText", None, None
            )
            if not self._window:
                error = _gpu.glfw.get_error()
                _gpu.glfw.terminate()
                raise RuntimeError(f"Failed to create GLFW window: {error}")

            logger.debug("GLFW window created")
            _gpu.glfw.make_context_current(self._window)
            logger.debug("OpenGL context made current")

            # Compile shaders
            self._shader_program = self._compile_shaders()
            self._shape_shader_program = self._compile_shape_shaders()

            # Create VAO/VBO for text quads
            self._create_buffers()
            self._create_shape_buffers()

            # Create framebuffer for offscreen rendering
            self._create_framebuffer()

            # Enable blending for anti-aliased text
            _gpu.gl.glEnable(_gpu.gl.GL_BLEND)
            _gpu.gl.glBlendFunc(_gpu.gl.GL_SRC_ALPHA, _gpu.gl.GL_ONE_MINUS_SRC_ALPHA)

            # Set up orthographic projection
            self._setup_projection()

            self._initialized = True
            logger.info("GPU text renderer initialized: %sx%s", self.width, self.height)
            return True

        except Exception as exc:  # pylint: disable=broad-exception-caught
            # Any GLFW/OpenGL failure must leave the renderer uninitialized.
            logger.error("Failed to initialize GPU text renderer: %s", exc)
            return False

    def _compile_shaders(self) -> int:
        """Compile vertex and fragment shaders."""
        # Vertex shader
        vertex_shader = _gpu.gl.glCreateShader(_gpu.gl.GL_VERTEX_SHADER)
        _gpu.gl.glShaderSource(vertex_shader, _shaders.VERTEX_SHADER)
        _gpu.gl.glCompileShader(vertex_shader)
        if not _gpu.gl.glGetShaderiv(vertex_shader, _gpu.gl.GL_COMPILE_STATUS):
            error = _gpu.gl.glGetShaderInfoLog(vertex_shader).decode()
            raise RuntimeError(f"Vertex shader compilation failed: {error}")

        # Fragment shader
        fragment_shader = _gpu.gl.glCreateShader(_gpu.gl.GL_FRAGMENT_SHADER)
        _gpu.gl.glShaderSource(fragment_shader, _shaders.FRAGMENT_SHADER)
        _gpu.gl.glCompileShader(fragment_shader)
        if not _gpu.gl.glGetShaderiv(fragment_shader, _gpu.gl.GL_COMPILE_STATUS):
            error = _gpu.gl.glGetShaderInfoLog(fragment_shader).decode()
            raise RuntimeError(f"Fragment shader compilation failed: {error}")

        # Link program
        program = _gpu.gl.glCreateProgram()
        _gpu.gl.glAttachShader(program, vertex_shader)
        _gpu.gl.glAttachShader(program, fragment_shader)
        _gpu.gl.glLinkProgram(program)
        if not _gpu.gl.glGetProgramiv(program, _gpu.gl.GL_LINK_STATUS):
            error = _gpu.gl.glGetProgramInfoLog(program).decode()
            raise RuntimeError(f"Shader program linking failed: {error}")

        # Clean up
        _gpu.gl.glDeleteShader(vertex_shader)
        _gpu.gl.glDeleteShader(fragment_shader)

        return program

    def _compile_shape_shaders(self) -> int:
        """Compile vertex and fragment shaders for solid shapes."""
        # Vertex shader
        vertex_shader = _gpu.gl.glCreateShader(_gpu.gl.GL_VERTEX_SHADER)
        _gpu.gl.glShaderSource(vertex_shader, _shaders.SHAPE_VERTEX_SHADER)
        _gpu.gl.glCompileShader(vertex_shader)
        if not _gpu.gl.glGetShaderiv(vertex_shader, _gpu.gl.GL_COMPILE_STATUS):
            error = _gpu.gl.glGetShaderInfoLog(vertex_shader).decode()
            raise RuntimeError(f"Shape vertex shader compilation failed: {error}")

        # Fragment shader
        fragment_shader = _gpu.gl.glCreateShader(_gpu.gl.GL_FRAGMENT_SHADER)
        _gpu.gl.glShaderSource(fragment_shader, _shaders.SHAPE_FRAGMENT_SHADER)
        _gpu.gl.glCompileShader(fragment_shader)
        if not _gpu.gl.glGetShaderiv(fragment_shader, _gpu.gl.GL_COMPILE_STATUS):
            error = _gpu.gl.glGetShaderInfoLog(fragment_shader).decode()
            raise RuntimeError(f"Shape fragment shader compilation failed: {error}")

        # Link program
        program = _gpu.gl.glCreateProgram()
        _gpu.gl.glAttachShader(program, vertex_shader)
        _gpu.gl.glAttachShader(program, fragment_shader)
        _gpu.gl.glLinkProgram(program)
        if not _gpu.gl.glGetProgramiv(program, _gpu.gl.GL_LINK_STATUS):
            error = _gpu.gl.glGetProgramInfoLog(program).decode()
            raise RuntimeError(f"Shape shader program linking failed: {error}")

        # Clean up
        _gpu.gl.glDeleteShader(vertex_shader)
        _gpu.gl.glDeleteShader(fragment_shader)

        return program

    def _create_buffers(self):
        """Create VAO and VBO for rendering text quads."""
        self._vao = _gpu.gl.glGenVertexArrays(1)
        self._vbo = _gpu.gl.glGenBuffers(1)

        _gpu.gl.glBindVertexArray(self._vao)
        _gpu.gl.glBindBuffer(_gpu.gl.GL_ARRAY_BUFFER, self._vbo)

        # Reserve space for 6 vertices per character (2 triangles)
        # Each vertex: x, y, tex_x, tex_y (4 floats)
        _gpu.gl.glBufferData(
            _gpu.gl.GL_ARRAY_BUFFER, 4 * 6 * 4 * 1000, None, _gpu.gl.GL_DYNAMIC_DRAW
        )

        _gpu.gl.glEnableVertexAttribArray(0)
        _gpu.gl.glVertexAttribPointer(
            0, 4, _gpu.gl.GL_FLOAT, _gpu.gl.GL_FALSE, 4 * 4, None
        )

        _gpu.gl.glBindBuffer(_gpu.gl.GL_ARRAY_BUFFER, 0)
        _gpu.gl.glBindVertexArray(0)

    def _create_shape_buffers(self):
        """Create VAO and VBO for rendering shapes."""
        self._shape_vao = _gpu.gl.glGenVertexArrays(1)
        self._shape_vbo = _gpu.gl.glGenBuffers(1)

        _gpu.gl.glBindVertexArray(self._shape_vao)
        _gpu.gl.glBindBuffer(_gpu.gl.GL_ARRAY_BUFFER, self._shape_vbo)

        # Reserve space for shape vertices (x, y) - 2 floats per vertex
        # Circles need: 48 segments * 6 vertices * 2 floats * 4 bytes = 2304 bytes
        # Allocate 4096 bytes to be safe
        _gpu.gl.glBufferData(
            _gpu.gl.GL_ARRAY_BUFFER, 4096, None, _gpu.gl.GL_DYNAMIC_DRAW
        )

        _gpu.gl.glEnableVertexAttribArray(0)
        _gpu.gl.glVertexAttribPointer(
            0, 2, _gpu.gl.GL_FLOAT, _gpu.gl.GL_FALSE, 2 * 4, None
        )

        _gpu.gl.glBindBuffer(_gpu.gl.GL_ARRAY_BUFFER, 0)
        _gpu.gl.glBindVertexArray(0)

    def _create_framebuffer(self):
        """Create framebuffer for offscreen rendering."""
        self._fbo = _gpu.gl.glGenFramebuffers(1)
        _gpu.gl.glBindFramebuffer(_gpu.gl.GL_FRAMEBUFFER, self._fbo)

        # Create texture to render to
        self._fbo_texture = _gpu.gl.glGenTextures(1)
        _gpu.gl.glBindTexture(_gpu.gl.GL_TEXTURE_2D, self._fbo_texture)
        _gpu.gl.glTexImage2D(
            _gpu.gl.GL_TEXTURE_2D,
            0,
            _gpu.gl.GL_RGBA,
            self.width,
            self.height,
            0,
            _gpu.gl.GL_RGBA,
            _gpu.gl.GL_UNSIGNED_BYTE,
            None,
        )
        _gpu.gl.glTexParameteri(
            _gpu.gl.GL_TEXTURE_2D, _gpu.gl.GL_TEXTURE_MIN_FILTER, _gpu.gl.GL_LINEAR
        )
        _gpu.gl.glTexParameteri(
            _gpu.gl.GL_TEXTURE_2D, _gpu.gl.GL_TEXTURE_MAG_FILTER, _gpu.gl.GL_LINEAR
        )

        _gpu.gl.glFramebufferTexture2D(
            _gpu.gl.GL_FRAMEBUFFER,
            _gpu.gl.GL_COLOR_ATTACHMENT0,
            _gpu.gl.GL_TEXTURE_2D,
            self._fbo_texture,
            0,
        )

        if (
            _gpu.gl.glCheckFramebufferStatus(_gpu.gl.GL_FRAMEBUFFER)
            != _gpu.gl.GL_FRAMEBUFFER_COMPLETE
        ):
            raise RuntimeError("Framebuffer is not complete")

        _gpu.gl.glBindFramebuffer(_gpu.gl.GL_FRAMEBUFFER, 0)

    def _setup_projection(self):
        """Set up orthographic projection matrix."""
        _gpu.gl.glUseProgram(self._shader_program)

        # Orthographic projection: (0,0) at top-left, (width, height) at bottom-right
        projection = np.array(
            [
                [2.0 / self.width, 0, 0, -1],
                [0, -2.0 / self.height, 0, 1],
                [0, 0, -1, 0],
                [0, 0, 0, 1],
            ],
            dtype=np.float32,
        )

        loc = _gpu.gl.glGetUniformLocation(self._shader_program, "projection")
        _gpu.gl.glUniformMatrix4fv(loc, 1, _gpu.gl.GL_TRUE, projection)

        # Also set up projection for shape shader
        _gpu.gl.glUseProgram(self._shape_shader_program)
        loc = _gpu.gl.glGetUniformLocation(self._shape_shader_program, "projection")
        _gpu.gl.glUniformMatrix4fv(loc, 1, _gpu.gl.GL_TRUE, projection)

    def draw_rectangle(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        color: Tuple[int, int, int],
        thickness: int = 1,
    ):
        """Draw a rectangle outline.

        Args:
            x, y: Top-left corner
            w, h: Width and height
            color: RGB color tuple (0-255)
            thickness: Line thickness in pixels
        """
        if not self._initialized:
            return

        _gpu.gl.glUseProgram(self._shape_shader_program)

        # Set color uniform
        loc = _gpu.gl.glGetUniformLocation(self._shape_shader_program, "shapeColor")
        _gpu.gl.glUniform3f(loc, color[0] / 255.0, color[1] / 255.0, color[2] / 255.0)

        _gpu.gl.glBindVertexArray(self._shape_vao)
        _gpu.gl.glBindBuffer(_gpu.gl.GL_ARRAY_BUFFER, self._shape_vbo)

        # Draw 4 lines for rectangle outline
        t = thickness
        lines = [
            # Top line
            [(x, y), (x + w, y), (x + w, y + t), (x, y + t)],
            # Bottom line
            [(x, y + h - t), (x + w, y + h - t), (x + w, y + h), (x, y + h)],
            # Left line
            [(x, y), (x + t, y), (x + t, y + h), (x, y + h)],
            # Right line
            [(x + w - t, y), (x + w, y), (x + w, y + h), (x + w - t, y + h)],
        ]

        for line_verts in lines:
            vertices = np.array(
                [
                    [line_verts[0][0], line_verts[0][1]],
                    [line_verts[1][0], line_verts[1][1]],
                    [line_verts[2][0], line_verts[2][1]],
                    [line_verts[0][0], line_verts[0][1]],
                    [line_verts[2][0], line_verts[2][1]],
                    [line_verts[3][0], line_verts[3][1]],
                ],
                dtype=np.float32,
            )

            _gpu.gl.glBufferSubData(
                _gpu.gl.GL_ARRAY_BUFFER, 0, vertices.nbytes, vertices
            )
            _gpu.gl.glDrawArrays(_gpu.gl.GL_TRIANGLES, 0, 6)

        _gpu.gl.glBindBuffer(_gpu.gl.GL_ARRAY_BUFFER, 0)
        _gpu.gl.glBindVertexArray(0)

    def draw_filled_rectangle(
        self, x: int, y: int, w: int, h: int, color: Tuple[int, int, int]
    ):
        """Draw a filled rectangle.

        Args:
            x, y: Top-left corner
            w, h: Width and height
            color: RGB color tuple (0-255)
        """
        if not self._initialized:
            return

        _gpu.gl.glUseProgram(self._shape_shader_program)

        # Set color uniform
        loc = _gpu.gl.glGetUniformLocation(self._shape_shader_program, "shapeColor")
        _gpu.gl.glUniform3f(loc, color[0] / 255.0, color[1] / 255.0, color[2] / 255.0)

        _gpu.gl.glBindVertexArray(self._shape_vao)
        _gpu.gl.glBindBuffer(_gpu.gl.GL_ARRAY_BUFFER, self._shape_vbo)

        # Two triangles for filled rectangle
        vertices = np.array(
            [
                [x, y],
                [x + w, y],
                [x + w, y + h],
                [x, y],
                [x + w, y + h],
                [x, y + h],
            ],
            dtype=np.float32,
        )

        _gpu.gl.glBufferSubData(_gpu.gl.GL_ARRAY_BUFFER, 0, vertices.nbytes, vertices)
        _gpu.gl.glDrawArrays(_gpu.gl.GL_TRIANGLES, 0, 6)

        _gpu.gl.glBindBuffer(_gpu.gl.GL_ARRAY_BUFFER, 0)
        _gpu.gl.glBindVertexArray(0)

    def draw_line(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        color: Tuple[int, int, int],
        thickness: int = 1,
    ):
        """Draw a line.

        Args:
            x1, y1: Start point
            x2, y2: End point
            color: RGB color tuple (0-255)
            thickness: Line thickness in pixels
        """
        if not self._initialized:
            return

        _gpu.gl.glUseProgram(self._shape_shader_program)

        # Set color uniform
        loc = _gpu.gl.glGetUniformLocation(self._shape_shader_program, "shapeColor")
        _gpu.gl.glUniform3f(loc, color[0] / 255.0, color[1] / 255.0, color[2] / 255.0)

        _gpu.gl.glBindVertexArray(self._shape_vao)
        _gpu.gl.glBindBuffer(_gpu.gl.GL_ARRAY_BUFFER, self._shape_vbo)

        # Calculate perpendicular offset for thickness
        dx = x2 - x1
        dy = y2 - y1
        length = math.sqrt(dx * dx + dy * dy)
        if length < 0.001:
            return

        # Perpendicular unit vector
        px = -dy / length * (thickness / 2)
        py = dx / length * (thickness / 2)

        # Quad vertices
        vertices = np.array(
            [
                [x1 + px, y1 + py],
                [x2 + px, y2 + py],
                [x2 - px, y2 - py],
                [x1 + px, y1 + py],
                [x2 - px, y2 - py],
                [x1 - px, y1 - py],
            ],
            dtype=np.float32,
        )

        _gpu.gl.glBufferSubData(_gpu.gl.GL_ARRAY_BUFFER, 0, vertices.nbytes, vertices)
        _gpu.gl.glDrawArrays(_gpu.gl.GL_TRIANGLES, 0, 6)

        _gpu.gl.glBindBuffer(_gpu.gl.GL_ARRAY_BUFFER, 0)
        _gpu.gl.glBindVertexArray(0)

    def draw_circle(
        self,
        cx: int,
        cy: int,
        radius: int,
        color: Tuple[int, int, int],
        thickness: int = 1,
    ):
        """Draw a circle outline.

        Args:
            cx, cy: Center point
            radius: Circle radius
            color: RGB color tuple (0-255)
            thickness: Line thickness in pixels
        """
        if not self._initialized:
            return

        _gpu.gl.glUseProgram(self._shape_shader_program)

        # Set color uniform
        loc = _gpu.gl.glGetUniformLocation(self._shape_shader_program, "shapeColor")
        _gpu.gl.glUniform3f(loc, color[0] / 255.0, color[1] / 255.0, color[2] / 255.0)

        _gpu.gl.glBindVertexArray(self._shape_vao)
        _gpu.gl.glBindBuffer(_gpu.gl.GL_ARRAY_BUFFER, self._shape_vbo)

        vertices = _shaders.circle_outline_vertices(cx, cy, radius, thickness)
        _gpu.gl.glBufferSubData(_gpu.gl.GL_ARRAY_BUFFER, 0, vertices.nbytes, vertices)
        _gpu.gl.glDrawArrays(_gpu.gl.GL_TRIANGLES, 0, len(vertices))

        _gpu.gl.glBindBuffer(_gpu.gl.GL_ARRAY_BUFFER, 0)
        _gpu.gl.glBindVertexArray(0)

    def load_font(self, font_path: str, size: int = 16) -> bool:
        """Load a TrueType font and create glyph atlas.

        Args:
            font_path: Path to .ttf font file
            size: Font size in pixels

        Returns:
            True if font loaded successfully
        """
        if not self._initialized:
            if not self.initialize():
                return False

        key = (font_path, size)
        if key in self._font_atlases:
            self._current_atlas = self._font_atlases[key]
            return True

        try:
            # Load font with FreeType
            face = _gpu.freetype.Face(font_path)
            face.set_pixel_sizes(0, size)

            # Determine atlas size (power of 2)
            # ASCII printable characters: 32-126 (95 chars)
            chars_per_row = 16
            char_width = size + 4  # Add padding
            char_height = size + 4
            atlas_width = chars_per_row * char_width
            atlas_height = ((95 // chars_per_row) + 1) * char_height

            # Round up to power of 2
            atlas_width = 1 << (atlas_width - 1).bit_length()
            atlas_height = 1 << (atlas_height - 1).bit_length()

            # Create atlas texture
            atlas_data = np.zeros((atlas_height, atlas_width), dtype=np.uint8)

            # Create OpenGL texture
            texture_id = _gpu.gl.glGenTextures(1)
            _gpu.gl.glBindTexture(_gpu.gl.GL_TEXTURE_2D, texture_id)
            _gpu.gl.glPixelStorei(_gpu.gl.GL_UNPACK_ALIGNMENT, 1)

            atlas = FontAtlas(
                texture_id=texture_id,
                width=atlas_width,
                height=atlas_height,
                font_size=size,
                line_height=int(size * 1.2),
            )

            _pack_ascii_glyphs(face, atlas, atlas_data, char_height, atlas_width)

            # Upload atlas to GPU
            _gpu.gl.glTexImage2D(
                _gpu.gl.GL_TEXTURE_2D,
                0,
                _gpu.gl.GL_RED,
                atlas_width,
                atlas_height,
                0,
                _gpu.gl.GL_RED,
                _gpu.gl.GL_UNSIGNED_BYTE,
                atlas_data,
            )

            _gpu.gl.glTexParameteri(
                _gpu.gl.GL_TEXTURE_2D,
                _gpu.gl.GL_TEXTURE_WRAP_S,
                _gpu.gl.GL_CLAMP_TO_EDGE,
            )
            _gpu.gl.glTexParameteri(
                _gpu.gl.GL_TEXTURE_2D,
                _gpu.gl.GL_TEXTURE_WRAP_T,
                _gpu.gl.GL_CLAMP_TO_EDGE,
            )
            _gpu.gl.glTexParameteri(
                _gpu.gl.GL_TEXTURE_2D, _gpu.gl.GL_TEXTURE_MIN_FILTER, _gpu.gl.GL_LINEAR
            )
            _gpu.gl.glTexParameteri(
                _gpu.gl.GL_TEXTURE_2D, _gpu.gl.GL_TEXTURE_MAG_FILTER, _gpu.gl.GL_LINEAR
            )

            self._font_atlases[key] = atlas
            self._current_atlas = atlas

            logger.info(
                "Loaded font: %s @ %spx, atlas: %sx%s",
                font_path,
                size,
                atlas_width,
                atlas_height,
            )
            return True

        except Exception as exc:  # pylint: disable=broad-exception-caught
            # FreeType and OpenGL can raise several native errors; report and skip.
            logger.error("Failed to load font %s: %s", font_path, exc)
            return False

    def render_text(
        self,
        text_items: List[Tuple[str, int, int, Tuple[int, int, int]]],
        clear_color: Tuple[int, int, int, int] = (0, 0, 0, 0),
    ) -> np.ndarray:
        """Render text items to a numpy array.

        Args:
            text_items: List of (text, x, y, color_rgb) tuples
            clear_color: Background color (R, G, B, A) 0-255

        Returns:
            RGBA numpy array (height, width, 4)
        """
        atlas = self._current_atlas
        if not self._initialized or atlas is None:
            raise RuntimeError("Renderer not initialized or no font loaded")

        _gpu.glfw.make_context_current(self._window)

        # Bind framebuffer
        _gpu.gl.glBindFramebuffer(_gpu.gl.GL_FRAMEBUFFER, self._fbo)
        _gpu.gl.glViewport(0, 0, self.width, self.height)

        # Clear with transparent or specified color
        _gpu.gl.glClearColor(
            clear_color[0] / 255.0,
            clear_color[1] / 255.0,
            clear_color[2] / 255.0,
            clear_color[3] / 255.0 if len(clear_color) > 3 else 0.0,
        )
        _gpu.gl.glClear(_gpu.gl.GL_COLOR_BUFFER_BIT)

        # Render each text item
        _gpu.gl.glUseProgram(self._shader_program)
        _gpu.gl.glActiveTexture(_gpu.gl.GL_TEXTURE0)
        _gpu.gl.glBindTexture(_gpu.gl.GL_TEXTURE_2D, atlas.texture_id)

        for text, x, y, color in text_items:
            self._render_string(text, x, y, color)

        # Read back pixels
        _gpu.gl.glBindFramebuffer(_gpu.gl.GL_FRAMEBUFFER, self._fbo)
        pixels = _gpu.gl.glReadPixels(
            0, 0, self.width, self.height, _gpu.gl.GL_RGBA, _gpu.gl.GL_UNSIGNED_BYTE
        )

        # Convert to numpy and flip vertically (OpenGL origin is bottom-left)
        frame = np.frombuffer(pixels, dtype=np.uint8).reshape(
            self.height, self.width, 4
        )
        frame = np.flipud(frame).copy()

        _gpu.gl.glBindFramebuffer(_gpu.gl.GL_FRAMEBUFFER, 0)

        return frame

    def _render_string(self, text: str, x: int, y: int, color: Tuple[int, int, int]):
        """Render a single string at position."""
        atlas = self._current_atlas
        if atlas is None:
            return

        # Set text color
        color_loc = _gpu.gl.glGetUniformLocation(self._shader_program, "textColor")
        _gpu.gl.glUniform3f(
            color_loc, color[0] / 255.0, color[1] / 255.0, color[2] / 255.0
        )

        _gpu.gl.glBindVertexArray(self._vao)

        vertices = []
        cursor_x = x

        for char in text:
            if char not in atlas.glyphs:
                char = "?"
            if char not in atlas.glyphs:
                continue
            quad, cursor_x = _glyph_quad_vertices(
                atlas.glyphs[char], cursor_x, y, atlas
            )
            vertices.extend(quad)

        if vertices:
            vertex_array = np.array(vertices, dtype=np.float32)

            _gpu.gl.glBindBuffer(_gpu.gl.GL_ARRAY_BUFFER, self._vbo)
            _gpu.gl.glBufferSubData(
                _gpu.gl.GL_ARRAY_BUFFER, 0, vertex_array.nbytes, vertex_array
            )

            _gpu.gl.glDrawArrays(_gpu.gl.GL_TRIANGLES, 0, len(vertex_array) // 4)

        _gpu.gl.glBindVertexArray(0)

    def composite_text_onto_frame(
        self,
        frame: np.ndarray,
        text_items: List[Tuple[str, int, int, Tuple[int, int, int]]],
    ) -> np.ndarray:
        """Composite GPU-rendered text onto an existing BGR frame.

        Args:
            frame: BGR numpy array (height, width, 3)
            text_items: List of (text, x, y, color_rgb) tuples

        Returns:
            BGR frame with text composited
        """
        # Render text to RGBA
        text_rgba = self.render_text(text_items, clear_color=(0, 0, 0, 0))

        # Alpha blend onto frame
        alpha = text_rgba[:, :, 3:4] / 255.0
        text_rgb = text_rgba[:, :, :3]

        # Convert text from RGB to BGR for OpenCV compatibility
        text_bgr = text_rgb[:, :, ::-1]

        # Composite: result = text * alpha + frame * (1 - alpha)
        result = (text_bgr * alpha + frame * (1 - alpha)).astype(np.uint8)

        return result

    def get_text_width(self, text: str) -> int:
        """Get the width of a text string in pixels."""
        atlas = self._current_atlas
        if atlas is None:
            return 0

        width = 0
        for char in text:
            if char in atlas.glyphs:
                width += atlas.glyphs[char].advance
        return width

    def render_to_bgr(
        self,
        text_items: List[Tuple[str, int, int, Tuple[int, int, int]]],
        background: Tuple[int, int, int] = (0, 0, 0),
    ) -> np.ndarray:
        """Render text directly to BGR numpy array (for OpenCV compatibility).

        Args:
            text_items: List of (text, x, y, color_rgb) tuples
            background: Background color (R, G, B)

        Returns:
            BGR numpy array (height, width, 3)
        """
        rgba = self.render_text(text_items, (*background, 255))
        # Convert RGBA to BGR
        return rgba[:, :, [2, 1, 0]]  # Swap R and B channels, drop A

    def cleanup(self):
        """Release OpenGL resources."""
        if self._initialized:
            try:
                _gpu.glfw.make_context_current(self._window)

                if self._fbo:
                    _gpu.gl.glDeleteFramebuffers(1, [self._fbo])
                if self._fbo_texture:
                    _gpu.gl.glDeleteTextures(1, [self._fbo_texture])
                if self._vao:
                    _gpu.gl.glDeleteVertexArrays(1, [self._vao])
                if self._vbo:
                    _gpu.gl.glDeleteBuffers(1, [self._vbo])
                if self._shader_program:
                    _gpu.gl.glDeleteProgram(self._shader_program)

                for atlas in self._font_atlases.values():
                    _gpu.gl.glDeleteTextures(1, [atlas.texture_id])

                _gpu.glfw.destroy_window(self._window)
                _gpu.glfw.terminate()

            except Exception as exc:  # pylint: disable=broad-exception-caught
                # Destroying a half-initialized GL context must not raise.
                logger.warning("Error during cleanup: %s", exc)

            self._initialized = False

    def __del__(self):
        self.cleanup()


# Imported after GPUTextRenderer is defined so the video module can import it.
# isort: off
# pylint: disable=wrong-import-position
from tool_modules.aa_meet_bot.src.gpu_video_text import (  # noqa: E402
    VideoTextRenderer,
    render_text_gpu,
)

# pylint: enable=wrong-import-position
# isort: on

__all__ = [
    "FontAtlas",
    "GPUTextRenderer",
    "Glyph",
    "VideoTextRenderer",
    "gpu_libraries",
    "render_text_gpu",
]
