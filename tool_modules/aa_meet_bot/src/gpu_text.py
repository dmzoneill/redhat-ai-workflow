"""GPU-accelerated text rendering using OpenGL + FreeType.

Renders smooth anti-aliased text entirely on the GPU with minimal CPU overhead.
Uses a glyph atlas texture for efficient character rendering.

Architecture:
1. FreeType renders glyphs to a texture atlas (one-time per font/size)
2. OpenGL renders quads with glyph textures (per frame)
3. Result is read back or composited with OpenCL frame

Dependencies:
    uv add PyOpenGL PyOpenGL_accelerate freetype-py glfw
"""

import os

# Force GLX platform for OpenGL on Linux (required for headless rendering)
os.environ.setdefault("PYOPENGL_PLATFORM", "glx")

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Lazy imports for optional dependencies
_glfw = None
_gl = None
_freetype = None


def _ensure_imports():
    """Lazy import OpenGL and FreeType."""
    global _glfw, _gl, _freetype
    if _glfw is None:
        try:
            import freetype as ft_mod
            import glfw as glfw_mod
            import OpenGL.GL as gl_mod

            _glfw = glfw_mod
            _gl = gl_mod
            _freetype = ft_mod
        except ImportError as e:
            raise ImportError(
                "GPU text rendering requires: uv add PyOpenGL PyOpenGL_accelerate freetype-py glfw"
            ) from e


@dataclass
class Glyph:
    """Information about a single glyph in the atlas."""

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


# Vertex shader for text rendering
_VERTEX_SHADER = """
#version 330 core
layout (location = 0) in vec4 vertex;  // <vec2 pos, vec2 tex>
out vec2 TexCoords;

uniform mat4 projection;

void main() {
    gl_Position = projection * vec4(vertex.xy, 0.0, 1.0);
    TexCoords = vertex.zw;
}
"""

# Fragment shader with anti-aliasing
_FRAGMENT_SHADER = """
#version 330 core
in vec2 TexCoords;
out vec4 color;

uniform sampler2D text_texture;
uniform vec3 textColor;

void main() {
    float alpha = texture(text_texture, TexCoords).r;
    color = vec4(textColor, alpha);
}
"""

# Simple vertex shader for solid shapes (no texture)
_SHAPE_VERTEX_SHADER = """
#version 330 core
layout (location = 0) in vec2 position;

uniform mat4 projection;

void main() {
    gl_Position = projection * vec4(position, 0.0, 1.0);
}
"""

# Simple fragment shader for solid shapes
_SHAPE_FRAGMENT_SHADER = """
#version 330 core
out vec4 color;

uniform vec3 shapeColor;

void main() {
    color = vec4(shapeColor, 1.0);
}
"""


class GPUTextRenderer:
    """Renders anti-aliased text on the GPU using OpenGL.

    Usage:
        renderer = GPUTextRenderer(1920, 1080)
        renderer.load_font("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 16)

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

    def initialize(self) -> bool:
        """Initialize OpenGL context and resources."""
        if self._initialized:
            return True

        try:
            # Initialize GLFW with X11 platform (required for headless rendering on Linux)
            try:
                _glfw.init_hint(_glfw.PLATFORM, _glfw.PLATFORM_X11)
            except Exception as e:
                logger.warning(f"Could not set X11 platform hint: {e}")

            if not _glfw.init():
                raise RuntimeError("Failed to initialize GLFW")

            logger.debug(f"GLFW initialized, platform: {_glfw.get_platform()}")

            # Configure for offscreen rendering
            _glfw.window_hint(_glfw.VISIBLE, _glfw.FALSE if self.headless else _glfw.TRUE)
            _glfw.window_hint(_glfw.CONTEXT_VERSION_MAJOR, 3)
            _glfw.window_hint(_glfw.CONTEXT_VERSION_MINOR, 3)
            _glfw.window_hint(_glfw.OPENGL_PROFILE, _glfw.OPENGL_CORE_PROFILE)

            # Create window (hidden for offscreen)
            self._window = _glfw.create_window(self.width, self.height, "GPUText", None, None)
            if not self._window:
                error = _glfw.get_error()
                _glfw.terminate()
                raise RuntimeError(f"Failed to create GLFW window: {error}")

            logger.debug("GLFW window created")
            _glfw.make_context_current(self._window)
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
            _gl.glEnable(_gl.GL_BLEND)
            _gl.glBlendFunc(_gl.GL_SRC_ALPHA, _gl.GL_ONE_MINUS_SRC_ALPHA)

            # Set up orthographic projection
            self._setup_projection()

            self._initialized = True
            logger.info(f"GPU text renderer initialized: {self.width}x{self.height}")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize GPU text renderer: {e}")
            return False

    def _compile_shaders(self) -> int:
        """Compile vertex and fragment shaders."""
        # Vertex shader
        vertex_shader = _gl.glCreateShader(_gl.GL_VERTEX_SHADER)
        _gl.glShaderSource(vertex_shader, _VERTEX_SHADER)
        _gl.glCompileShader(vertex_shader)
        if not _gl.glGetShaderiv(vertex_shader, _gl.GL_COMPILE_STATUS):
            error = _gl.glGetShaderInfoLog(vertex_shader).decode()
            raise RuntimeError(f"Vertex shader compilation failed: {error}")

        # Fragment shader
        fragment_shader = _gl.glCreateShader(_gl.GL_FRAGMENT_SHADER)
        _gl.glShaderSource(fragment_shader, _FRAGMENT_SHADER)
        _gl.glCompileShader(fragment_shader)
        if not _gl.glGetShaderiv(fragment_shader, _gl.GL_COMPILE_STATUS):
            error = _gl.glGetShaderInfoLog(fragment_shader).decode()
            raise RuntimeError(f"Fragment shader compilation failed: {error}")

        # Link program
        program = _gl.glCreateProgram()
        _gl.glAttachShader(program, vertex_shader)
        _gl.glAttachShader(program, fragment_shader)
        _gl.glLinkProgram(program)
        if not _gl.glGetProgramiv(program, _gl.GL_LINK_STATUS):
            error = _gl.glGetProgramInfoLog(program).decode()
            raise RuntimeError(f"Shader program linking failed: {error}")

        # Clean up
        _gl.glDeleteShader(vertex_shader)
        _gl.glDeleteShader(fragment_shader)

        return program

    def _compile_shape_shaders(self) -> int:
        """Compile vertex and fragment shaders for solid shapes."""
        # Vertex shader
        vertex_shader = _gl.glCreateShader(_gl.GL_VERTEX_SHADER)
        _gl.glShaderSource(vertex_shader, _SHAPE_VERTEX_SHADER)
        _gl.glCompileShader(vertex_shader)
        if not _gl.glGetShaderiv(vertex_shader, _gl.GL_COMPILE_STATUS):
            error = _gl.glGetShaderInfoLog(vertex_shader).decode()
            raise RuntimeError(f"Shape vertex shader compilation failed: {error}")

        # Fragment shader
        fragment_shader = _gl.glCreateShader(_gl.GL_FRAGMENT_SHADER)
        _gl.glShaderSource(fragment_shader, _SHAPE_FRAGMENT_SHADER)
        _gl.glCompileShader(fragment_shader)
        if not _gl.glGetShaderiv(fragment_shader, _gl.GL_COMPILE_STATUS):
            error = _gl.glGetShaderInfoLog(fragment_shader).decode()
            raise RuntimeError(f"Shape fragment shader compilation failed: {error}")

        # Link program
        program = _gl.glCreateProgram()
        _gl.glAttachShader(program, vertex_shader)
        _gl.glAttachShader(program, fragment_shader)
        _gl.glLinkProgram(program)
        if not _gl.glGetProgramiv(program, _gl.GL_LINK_STATUS):
            error = _gl.glGetProgramInfoLog(program).decode()
            raise RuntimeError(f"Shape shader program linking failed: {error}")

        # Clean up
        _gl.glDeleteShader(vertex_shader)
        _gl.glDeleteShader(fragment_shader)

        return program

    def _create_buffers(self):
        """Create VAO and VBO for rendering text quads."""
        self._vao = _gl.glGenVertexArrays(1)
        self._vbo = _gl.glGenBuffers(1)

        _gl.glBindVertexArray(self._vao)
        _gl.glBindBuffer(_gl.GL_ARRAY_BUFFER, self._vbo)

        # Reserve space for 6 vertices per character (2 triangles)
        # Each vertex: x, y, tex_x, tex_y (4 floats)
        _gl.glBufferData(_gl.GL_ARRAY_BUFFER, 4 * 6 * 4 * 1000, None, _gl.GL_DYNAMIC_DRAW)

        _gl.glEnableVertexAttribArray(0)
        _gl.glVertexAttribPointer(0, 4, _gl.GL_FLOAT, _gl.GL_FALSE, 4 * 4, None)

        _gl.glBindBuffer(_gl.GL_ARRAY_BUFFER, 0)
        _gl.glBindVertexArray(0)

    def _create_shape_buffers(self):
        """Create VAO and VBO for rendering shapes."""
        self._shape_vao = _gl.glGenVertexArrays(1)
        self._shape_vbo = _gl.glGenBuffers(1)

        _gl.glBindVertexArray(self._shape_vao)
        _gl.glBindBuffer(_gl.GL_ARRAY_BUFFER, self._shape_vbo)

        # Reserve space for shape vertices (x, y) - 2 floats per vertex
        # Circles need: 48 segments * 6 vertices * 2 floats * 4 bytes = 2304 bytes
        # Allocate 4096 bytes to be safe
        _gl.glBufferData(_gl.GL_ARRAY_BUFFER, 4096, None, _gl.GL_DYNAMIC_DRAW)

        _gl.glEnableVertexAttribArray(0)
        _gl.glVertexAttribPointer(0, 2, _gl.GL_FLOAT, _gl.GL_FALSE, 2 * 4, None)

        _gl.glBindBuffer(_gl.GL_ARRAY_BUFFER, 0)
        _gl.glBindVertexArray(0)

    def _create_framebuffer(self):
        """Create framebuffer for offscreen rendering."""
        self._fbo = _gl.glGenFramebuffers(1)
        _gl.glBindFramebuffer(_gl.GL_FRAMEBUFFER, self._fbo)

        # Create texture to render to
        self._fbo_texture = _gl.glGenTextures(1)
        _gl.glBindTexture(_gl.GL_TEXTURE_2D, self._fbo_texture)
        _gl.glTexImage2D(
            _gl.GL_TEXTURE_2D, 0, _gl.GL_RGBA, self.width, self.height, 0, _gl.GL_RGBA, _gl.GL_UNSIGNED_BYTE, None
        )
        _gl.glTexParameteri(_gl.GL_TEXTURE_2D, _gl.GL_TEXTURE_MIN_FILTER, _gl.GL_LINEAR)
        _gl.glTexParameteri(_gl.GL_TEXTURE_2D, _gl.GL_TEXTURE_MAG_FILTER, _gl.GL_LINEAR)

        _gl.glFramebufferTexture2D(
            _gl.GL_FRAMEBUFFER, _gl.GL_COLOR_ATTACHMENT0, _gl.GL_TEXTURE_2D, self._fbo_texture, 0
        )

        if _gl.glCheckFramebufferStatus(_gl.GL_FRAMEBUFFER) != _gl.GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError("Framebuffer is not complete")

        _gl.glBindFramebuffer(_gl.GL_FRAMEBUFFER, 0)

    def _setup_projection(self):
        """Set up orthographic projection matrix."""
        _gl.glUseProgram(self._shader_program)

        # Orthographic projection: (0,0) at top-left, (width, height) at bottom-right
        projection = np.array(
            [[2.0 / self.width, 0, 0, -1], [0, -2.0 / self.height, 0, 1], [0, 0, -1, 0], [0, 0, 0, 1]], dtype=np.float32
        )

        loc = _gl.glGetUniformLocation(self._shader_program, "projection")
        _gl.glUniformMatrix4fv(loc, 1, _gl.GL_TRUE, projection)

        # Also set up projection for shape shader
        _gl.glUseProgram(self._shape_shader_program)
        loc = _gl.glGetUniformLocation(self._shape_shader_program, "projection")
        _gl.glUniformMatrix4fv(loc, 1, _gl.GL_TRUE, projection)

    def draw_rectangle(self, x: int, y: int, w: int, h: int, color: Tuple[int, int, int], thickness: int = 1):
        """Draw a rectangle outline.

        Args:
            x, y: Top-left corner
            w, h: Width and height
            color: RGB color tuple (0-255)
            thickness: Line thickness in pixels
        """
        if not self._initialized:
            return

        _gl.glUseProgram(self._shape_shader_program)

        # Set color uniform
        loc = _gl.glGetUniformLocation(self._shape_shader_program, "shapeColor")
        _gl.glUniform3f(loc, color[0] / 255.0, color[1] / 255.0, color[2] / 255.0)

        _gl.glBindVertexArray(self._shape_vao)
        _gl.glBindBuffer(_gl.GL_ARRAY_BUFFER, self._shape_vbo)

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

            _gl.glBufferSubData(_gl.GL_ARRAY_BUFFER, 0, vertices.nbytes, vertices)
            _gl.glDrawArrays(_gl.GL_TRIANGLES, 0, 6)

        _gl.glBindBuffer(_gl.GL_ARRAY_BUFFER, 0)
        _gl.glBindVertexArray(0)

    def draw_filled_rectangle(self, x: int, y: int, w: int, h: int, color: Tuple[int, int, int]):
        """Draw a filled rectangle.

        Args:
            x, y: Top-left corner
            w, h: Width and height
            color: RGB color tuple (0-255)
        """
        if not self._initialized:
            return

        _gl.glUseProgram(self._shape_shader_program)

        # Set color uniform
        loc = _gl.glGetUniformLocation(self._shape_shader_program, "shapeColor")
        _gl.glUniform3f(loc, color[0] / 255.0, color[1] / 255.0, color[2] / 255.0)

        _gl.glBindVertexArray(self._shape_vao)
        _gl.glBindBuffer(_gl.GL_ARRAY_BUFFER, self._shape_vbo)

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

        _gl.glBufferSubData(_gl.GL_ARRAY_BUFFER, 0, vertices.nbytes, vertices)
        _gl.glDrawArrays(_gl.GL_TRIANGLES, 0, 6)

        _gl.glBindBuffer(_gl.GL_ARRAY_BUFFER, 0)
        _gl.glBindVertexArray(0)

    def draw_line(self, x1: int, y1: int, x2: int, y2: int, color: Tuple[int, int, int], thickness: int = 1):
        """Draw a line.

        Args:
            x1, y1: Start point
            x2, y2: End point
            color: RGB color tuple (0-255)
            thickness: Line thickness in pixels
        """
        if not self._initialized:
            return

        _gl.glUseProgram(self._shape_shader_program)

        # Set color uniform
        loc = _gl.glGetUniformLocation(self._shape_shader_program, "shapeColor")
        _gl.glUniform3f(loc, color[0] / 255.0, color[1] / 255.0, color[2] / 255.0)

        _gl.glBindVertexArray(self._shape_vao)
        _gl.glBindBuffer(_gl.GL_ARRAY_BUFFER, self._shape_vbo)

        # Calculate perpendicular offset for thickness
        import math

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

        _gl.glBufferSubData(_gl.GL_ARRAY_BUFFER, 0, vertices.nbytes, vertices)
        _gl.glDrawArrays(_gl.GL_TRIANGLES, 0, 6)

        _gl.glBindBuffer(_gl.GL_ARRAY_BUFFER, 0)
        _gl.glBindVertexArray(0)

    def draw_circle(self, cx: int, cy: int, radius: int, color: Tuple[int, int, int], thickness: int = 1):
        """Draw a circle outline.

        Args:
            cx, cy: Center point
            radius: Circle radius
            color: RGB color tuple (0-255)
            thickness: Line thickness in pixels
        """
        if not self._initialized:
            return

        import math

        _gl.glUseProgram(self._shape_shader_program)

        # Set color uniform
        loc = _gl.glGetUniformLocation(self._shape_shader_program, "shapeColor")
        _gl.glUniform3f(loc, color[0] / 255.0, color[1] / 255.0, color[2] / 255.0)

        _gl.glBindVertexArray(self._shape_vao)
        _gl.glBindBuffer(_gl.GL_ARRAY_BUFFER, self._shape_vbo)

        # Draw circle as line segments
        segments = 48
        inner_r = radius - thickness / 2
        outer_r = radius + thickness / 2

        vertices = []
        for i in range(segments):
            angle1 = 2 * math.pi * i / segments
            angle2 = 2 * math.pi * (i + 1) / segments

            # Inner and outer points for this segment
            ix1, iy1 = cx + inner_r * math.cos(angle1), cy + inner_r * math.sin(angle1)
            ox1, oy1 = cx + outer_r * math.cos(angle1), cy + outer_r * math.sin(angle1)
            ix2, iy2 = cx + inner_r * math.cos(angle2), cy + inner_r * math.sin(angle2)
            ox2, oy2 = cx + outer_r * math.cos(angle2), cy + outer_r * math.sin(angle2)

            # Two triangles per segment
            vertices.extend(
                [
                    [ix1, iy1],
                    [ox1, oy1],
                    [ox2, oy2],
                    [ix1, iy1],
                    [ox2, oy2],
                    [ix2, iy2],
                ]
            )

        vertices = np.array(vertices, dtype=np.float32)
        _gl.glBufferSubData(_gl.GL_ARRAY_BUFFER, 0, vertices.nbytes, vertices)
        _gl.glDrawArrays(_gl.GL_TRIANGLES, 0, len(vertices))

        _gl.glBindBuffer(_gl.GL_ARRAY_BUFFER, 0)
        _gl.glBindVertexArray(0)

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
            face = _freetype.Face(font_path)
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
            texture_id = _gl.glGenTextures(1)
            _gl.glBindTexture(_gl.GL_TEXTURE_2D, texture_id)
            _gl.glPixelStorei(_gl.GL_UNPACK_ALIGNMENT, 1)

            atlas = FontAtlas(
                texture_id=texture_id,
                width=atlas_width,
                height=atlas_height,
                font_size=size,
                line_height=int(size * 1.2),
            )

            # Render each ASCII character to atlas
            x, y = 0, 0
            for i in range(32, 127):
                char = chr(i)
                face.load_char(char, _freetype.FT_LOAD_RENDER)

                glyph = face.glyph
                bitmap = glyph.bitmap

                # Check if we need to move to next row
                if x + bitmap.width + 2 > atlas_width:
                    x = 0
                    y += char_height

                # Copy bitmap to atlas
                if bitmap.width > 0 and bitmap.rows > 0:
                    bitmap_array = np.array(bitmap.buffer, dtype=np.uint8).reshape(bitmap.rows, bitmap.width)
                    atlas_data[y : y + bitmap.rows, x : x + bitmap.width] = bitmap_array

                # Store glyph info
                atlas.glyphs[char] = Glyph(
                    char=char,
                    texture_x=x,
                    texture_y=y,
                    width=bitmap.width,
                    height=bitmap.rows,
                    bearing_x=glyph.bitmap_left,
                    bearing_y=glyph.bitmap_top,
                    advance=glyph.advance.x >> 6,  # Convert from 26.6 fixed point
                )

                x += bitmap.width + 2

            # Upload atlas to GPU
            _gl.glTexImage2D(
                _gl.GL_TEXTURE_2D,
                0,
                _gl.GL_RED,
                atlas_width,
                atlas_height,
                0,
                _gl.GL_RED,
                _gl.GL_UNSIGNED_BYTE,
                atlas_data,
            )

            _gl.glTexParameteri(_gl.GL_TEXTURE_2D, _gl.GL_TEXTURE_WRAP_S, _gl.GL_CLAMP_TO_EDGE)
            _gl.glTexParameteri(_gl.GL_TEXTURE_2D, _gl.GL_TEXTURE_WRAP_T, _gl.GL_CLAMP_TO_EDGE)
            _gl.glTexParameteri(_gl.GL_TEXTURE_2D, _gl.GL_TEXTURE_MIN_FILTER, _gl.GL_LINEAR)
            _gl.glTexParameteri(_gl.GL_TEXTURE_2D, _gl.GL_TEXTURE_MAG_FILTER, _gl.GL_LINEAR)

            self._font_atlases[key] = atlas
            self._current_atlas = atlas

            logger.info(f"Loaded font: {font_path} @ {size}px, atlas: {atlas_width}x{atlas_height}")
            return True

        except Exception as e:
            logger.error(f"Failed to load font {font_path}: {e}")
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
        if not self._initialized or not self._current_atlas:
            raise RuntimeError("Renderer not initialized or no font loaded")

        _glfw.make_context_current(self._window)

        # Bind framebuffer
        _gl.glBindFramebuffer(_gl.GL_FRAMEBUFFER, self._fbo)
        _gl.glViewport(0, 0, self.width, self.height)

        # Clear with transparent or specified color
        _gl.glClearColor(
            clear_color[0] / 255.0,
            clear_color[1] / 255.0,
            clear_color[2] / 255.0,
            clear_color[3] / 255.0 if len(clear_color) > 3 else 0.0,
        )
        _gl.glClear(_gl.GL_COLOR_BUFFER_BIT)

        # Render each text item
        _gl.glUseProgram(self._shader_program)
        _gl.glActiveTexture(_gl.GL_TEXTURE0)
        _gl.glBindTexture(_gl.GL_TEXTURE_2D, self._current_atlas.texture_id)

        for text, x, y, color in text_items:
            self._render_string(text, x, y, color)

        # Read back pixels
        _gl.glBindFramebuffer(_gl.GL_FRAMEBUFFER, self._fbo)
        pixels = _gl.glReadPixels(0, 0, self.width, self.height, _gl.GL_RGBA, _gl.GL_UNSIGNED_BYTE)

        # Convert to numpy and flip vertically (OpenGL origin is bottom-left)
        frame = np.frombuffer(pixels, dtype=np.uint8).reshape(self.height, self.width, 4)
        frame = np.flipud(frame).copy()

        _gl.glBindFramebuffer(_gl.GL_FRAMEBUFFER, 0)

        return frame

    def _render_string(self, text: str, x: int, y: int, color: Tuple[int, int, int]):
        """Render a single string at position."""
        atlas = self._current_atlas

        # Set text color
        color_loc = _gl.glGetUniformLocation(self._shader_program, "textColor")
        _gl.glUniform3f(color_loc, color[0] / 255.0, color[1] / 255.0, color[2] / 255.0)

        _gl.glBindVertexArray(self._vao)

        vertices = []
        cursor_x = x

        for char in text:
            if char not in atlas.glyphs:
                char = "?"  # Fallback for unknown characters
            if char not in atlas.glyphs:
                continue

            g = atlas.glyphs[char]

            # Calculate quad position
            xpos = cursor_x + g.bearing_x
            ypos = y + (atlas.font_size - g.bearing_y)  # Baseline adjustment

            w = g.width
            h = g.height

            # Texture coordinates (normalized)
            tx = g.texture_x / atlas.width
            ty = g.texture_y / atlas.height
            tw = g.width / atlas.width
            th = g.height / atlas.height

            # Two triangles for quad (6 vertices)
            # Each vertex: x, y, tex_x, tex_y
            quad_vertices = [
                # Triangle 1
                xpos,
                ypos,
                tx,
                ty,
                xpos,
                ypos + h,
                tx,
                ty + th,
                xpos + w,
                ypos + h,
                tx + tw,
                ty + th,
                # Triangle 2
                xpos,
                ypos,
                tx,
                ty,
                xpos + w,
                ypos + h,
                tx + tw,
                ty + th,
                xpos + w,
                ypos,
                tx + tw,
                ty,
            ]
            vertices.extend(quad_vertices)

            cursor_x += g.advance

        if vertices:
            vertices = np.array(vertices, dtype=np.float32)

            _gl.glBindBuffer(_gl.GL_ARRAY_BUFFER, self._vbo)
            _gl.glBufferSubData(_gl.GL_ARRAY_BUFFER, 0, vertices.nbytes, vertices)

            _gl.glDrawArrays(_gl.GL_TRIANGLES, 0, len(vertices) // 4)

        _gl.glBindVertexArray(0)

    def composite_text_onto_frame(
        self, frame: np.ndarray, text_items: List[Tuple[str, int, int, Tuple[int, int, int]]]
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
        if not self._current_atlas:
            return 0

        width = 0
        for char in text:
            if char in self._current_atlas.glyphs:
                width += self._current_atlas.glyphs[char].advance
        return width

    def render_to_bgr(
        self, text_items: List[Tuple[str, int, int, Tuple[int, int, int]]], background: Tuple[int, int, int] = (0, 0, 0)
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
                _glfw.make_context_current(self._window)

                if self._fbo:
                    _gl.glDeleteFramebuffers(1, [self._fbo])
                if self._fbo_texture:
                    _gl.glDeleteTextures(1, [self._fbo_texture])
                if self._vao:
                    _gl.glDeleteVertexArrays(1, [self._vao])
                if self._vbo:
                    _gl.glDeleteBuffers(1, [self._vbo])
                if self._shader_program:
                    _gl.glDeleteProgram(self._shader_program)

                for atlas in self._font_atlases.values():
                    _gl.glDeleteTextures(1, [atlas.texture_id])

                _glfw.destroy_window(self._window)
                _glfw.terminate()

            except Exception as e:
                logger.warning(f"Error during cleanup: {e}")

            self._initialized = False

    def __del__(self):
        self.cleanup()


class VideoTextRenderer:
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
        "/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/liberation-mono/LiberationMono-Regular.ttf",
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

    def __init__(self, width: int, height: int, font_sizes: Dict[str, int] = None):
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
                    logger.debug(f"Loaded font size {name}={size}")
                else:
                    logger.warning(f"Failed to load font size {name}={size}")

            self._initialized = True
            # Pre-allocate output buffer to avoid repeated allocations
            self._output_buffer = np.zeros((self.height, self.width, 3), dtype=np.uint8)
            self._rgba_buffer = np.zeros((self.height, self.width, 4), dtype=np.uint8)
            logger.info(f"VideoTextRenderer initialized: {self.width}x{self.height}")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize VideoTextRenderer: {e}")
            return False

    def render_text_items(
        self, items: List[Tuple[str, int, int, str, str]], background: Tuple[int, int, int] = (0, 0, 0)
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

        # Group items by font size for efficient rendering
        items_by_size: Dict[str, List[Tuple[str, int, int, Tuple[int, int, int]]]] = {}

        for text, x, y, color_name, size_name in items:
            color = self.COLORS.get(color_name, (0, 255, 0))
            size_name = size_name if size_name in self.font_sizes else "normal"

            if size_name not in items_by_size:
                items_by_size[size_name] = []
            items_by_size[size_name].append((text, x, y, color))

        # Render all text in a single OpenGL pass
        # Switch fonts within the same context (fast - just texture switch)
        _glfw.make_context_current(self._renderer._window)
        _gl.glBindFramebuffer(_gl.GL_FRAMEBUFFER, self._renderer._fbo)
        _gl.glViewport(0, 0, self.width, self.height)

        # Clear with background
        _gl.glClearColor(background[0] / 255.0, background[1] / 255.0, background[2] / 255.0, 1.0)
        _gl.glClear(_gl.GL_COLOR_BUFFER_BIT)

        _gl.glUseProgram(self._renderer._shader_program)

        # Render each font size batch
        for size_name, size_items in items_by_size.items():
            size = self.font_sizes.get(size_name, 16)
            # Load font (cached - just switches active atlas)
            self._renderer.load_font(self._font_path, size)

            _gl.glActiveTexture(_gl.GL_TEXTURE0)
            _gl.glBindTexture(_gl.GL_TEXTURE_2D, self._renderer._current_atlas.texture_id)

            for text, x, y, color in size_items:
                self._renderer._render_string(text, x, y, color)

        # Single readback at the end - use pre-allocated buffer
        _gl.glReadPixels(0, 0, self.width, self.height, _gl.GL_RGBA, _gl.GL_UNSIGNED_BYTE, self._rgba_buffer)

        _gl.glBindFramebuffer(_gl.GL_FRAMEBUFFER, 0)

        # Convert RGBA to BGR in-place using pre-allocated buffer
        # Flip vertically (OpenGL origin is bottom-left) and swap R/B channels
        np.copyto(self._output_buffer[:, :, 0], np.flipud(self._rgba_buffer[:, :, 2]))  # B
        np.copyto(self._output_buffer[:, :, 1], np.flipud(self._rgba_buffer[:, :, 1]))  # G
        np.copyto(self._output_buffer[:, :, 2], np.flipud(self._rgba_buffer[:, :, 0]))  # R

        return self._output_buffer

    def render_frame(
        self,
        text_items: List[Tuple[str, int, int, str, str]],
        shapes: List[Tuple[str, ...]] = None,
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

        # Set up OpenGL context
        _glfw.make_context_current(self._renderer._window)
        _gl.glBindFramebuffer(_gl.GL_FRAMEBUFFER, self._renderer._fbo)
        _gl.glViewport(0, 0, self.width, self.height)

        # Clear with background
        _gl.glClearColor(background[0] / 255.0, background[1] / 255.0, background[2] / 255.0, 1.0)
        _gl.glClear(_gl.GL_COLOR_BUFFER_BIT)

        # Draw shapes first (behind text)
        for shape in shapes:
            shape_type = shape[0]
            color_name = shape[-2] if shape_type in ("rect", "line", "circle") else shape[-1]
            color = self.COLORS.get(color_name, (0, 255, 0))

            if shape_type == "rect":
                _, x, y, w, h, _, thickness = shape
                self._renderer.draw_rectangle(x, y, w, h, color, thickness)
            elif shape_type == "filled_rect":
                _, x, y, w, h, _ = shape
                self._renderer.draw_filled_rectangle(x, y, w, h, color)
            elif shape_type == "line":
                _, x1, y1, x2, y2, _, thickness = shape
                self._renderer.draw_line(x1, y1, x2, y2, color, thickness)
            elif shape_type == "circle":
                _, cx, cy, radius, _, thickness = shape
                self._renderer.draw_circle(cx, cy, radius, color, thickness)

        # Draw text on top
        _gl.glUseProgram(self._renderer._shader_program)

        # Group items by font size for efficient rendering
        items_by_size: Dict[str, List[Tuple[str, int, int, Tuple[int, int, int]]]] = {}

        for text, x, y, color_name, size_name in text_items:
            color = self.COLORS.get(color_name, (0, 255, 0))
            size_name = size_name if size_name in self.font_sizes else "normal"

            if size_name not in items_by_size:
                items_by_size[size_name] = []
            items_by_size[size_name].append((text, x, y, color))

        # Render each font size batch
        for size_name, size_items in items_by_size.items():
            size = self.font_sizes.get(size_name, 16)
            self._renderer.load_font(self._font_path, size)

            _gl.glActiveTexture(_gl.GL_TEXTURE0)
            _gl.glBindTexture(_gl.GL_TEXTURE_2D, self._renderer._current_atlas.texture_id)

            for text, x, y, color in size_items:
                self._renderer._render_string(text, x, y, color)

        # Single readback at the end - use pre-allocated buffer
        _gl.glReadPixels(0, 0, self.width, self.height, _gl.GL_RGBA, _gl.GL_UNSIGNED_BYTE, self._rgba_buffer)

        _gl.glBindFramebuffer(_gl.GL_FRAMEBUFFER, 0)

        # Convert RGBA to BGR in-place using pre-allocated buffer
        np.copyto(self._output_buffer[:, :, 0], np.flipud(self._rgba_buffer[:, :, 2]))  # B
        np.copyto(self._output_buffer[:, :, 1], np.flipud(self._rgba_buffer[:, :, 1]))  # G
        np.copyto(self._output_buffer[:, :, 2], np.flipud(self._rgba_buffer[:, :, 0]))  # R

        return self._output_buffer

    def composite_onto_frame(self, frame: np.ndarray, items: List[Tuple[str, int, int, str, str]]) -> np.ndarray:
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
def render_text_gpu(
    width: int,
    height: int,
    text_items: List[Tuple[str, int, int, Tuple[int, int, int]]],
    font_path: str = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
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


if __name__ == "__main__":
    # Test GPU text rendering
    import time

    print("Testing GPU text renderer...")

    # Find a monospace font
    font_paths = [
        "/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/google-droid-sans-mono-fonts/DroidSansMono.ttf",
        "/usr/share/fonts/liberation-mono/LiberationMono-Regular.ttf",
        "/usr/share/fonts/google-noto-vf/NotoSansMono[wght].ttf",
    ]

    font_path = None
    for p in font_paths:
        if Path(p).exists():
            font_path = p
            break

    if not font_path:
        print("No suitable font found!")
        exit(1)

    print(f"Using font: {font_path}")

    # Create renderer
    renderer = GPUTextRenderer(1280, 720, headless=True)

    if not renderer.initialize():
        print("Failed to initialize renderer")
        exit(1)

    if not renderer.load_font(font_path, 16):
        print("Failed to load font")
        exit(1)

    # Benchmark
    text_items = [
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
        frame = renderer.render_text(text_items, (0, 0, 0, 255))

    # Benchmark
    iterations = 100
    start = time.perf_counter()
    for _ in range(iterations):
        frame = renderer.render_text(text_items, (0, 0, 0, 255))
    elapsed = time.perf_counter() - start

    fps = iterations / elapsed
    ms_per_frame = (elapsed / iterations) * 1000

    print(f"\nBenchmark results:")
    print(f"  Resolution: 1280x720")
    print(f"  Text items: {len(text_items)}")
    print(f"  Time per frame: {ms_per_frame:.2f}ms")
    print(f"  Potential FPS: {fps:.1f}")
    print(f"  Frame shape: {frame.shape}")

    # Save test image
    import cv2

    # Convert RGBA to BGR for saving
    bgr = cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR)
    cv2.imwrite("/tmp/gpu_text_test.png", bgr)
    print(f"\nSaved test image to /tmp/gpu_text_test.png")

    renderer.cleanup()
    print("Done!")
