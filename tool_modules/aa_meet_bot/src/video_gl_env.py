"""Set the OpenGL platform before any GL library is imported."""

import os

os.environ.setdefault("PYOPENGL_PLATFORM", "glx")
