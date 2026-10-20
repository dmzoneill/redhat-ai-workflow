"""GLSL sources and mesh helpers for GPU text rendering."""

import math

import numpy as np


def circle_outline_vertices(
    cx: float, cy: float, radius: float, thickness: float
) -> np.ndarray:
    """Build a triangle strip mesh for a circle outline."""
    segments = 48
    inner_r = radius - thickness / 2
    outer_r = radius + thickness / 2
    vertices = []
    for index in range(segments):
        start = 2 * math.pi * index / segments
        end = 2 * math.pi * (index + 1) / segments
        inner_start = (cx + inner_r * math.cos(start), cy + inner_r * math.sin(start))
        outer_start = (cx + outer_r * math.cos(start), cy + outer_r * math.sin(start))
        inner_end = (cx + inner_r * math.cos(end), cy + inner_r * math.sin(end))
        outer_end = (cx + outer_r * math.cos(end), cy + outer_r * math.sin(end))
        vertices.extend(
            [inner_start, outer_start, outer_end, inner_start, outer_end, inner_end]
        )
    return np.array(vertices, dtype=np.float32)


# Vertex shader for text rendering
VERTEX_SHADER = """
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
FRAGMENT_SHADER = """
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
SHAPE_VERTEX_SHADER = """
#version 330 core
layout (location = 0) in vec2 position;

uniform mat4 projection;

void main() {
    gl_Position = projection * vec4(position, 0.0, 1.0);
}
"""

# Simple fragment shader for solid shapes
SHAPE_FRAGMENT_SHADER = """
#version 330 core
out vec4 color;

uniform vec3 shapeColor;

void main() {
    color = vec4(shapeColor, 1.0);
}
"""
