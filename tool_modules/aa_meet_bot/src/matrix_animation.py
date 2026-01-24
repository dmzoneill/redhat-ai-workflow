"""
Matrix-style Animation for "INITIALIZING..." state.

Creates the classic falling green characters effect from The Matrix,
with "INITIALIZING..." text displayed in the center.
"""

import random
from dataclasses import dataclass
from typing import Optional

import numpy as np

# Matrix characters - mix of katakana, numbers, and symbols
MATRIX_CHARS = (
    "アイウエオカキクケコサシスセソタチツテトナニヌネノ"
    "ハヒフヘホマミムメモヤユヨラリルレロワヲン"
    "0123456789"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "!@#$%^&*()+-=[]{}|;:,.<>?"
)


@dataclass
class MatrixColumn:
    """A single column of falling characters."""

    x: int  # X position in pixels
    y: float  # Current Y position (can be fractional for smooth animation)
    speed: float  # Fall speed in pixels per frame
    length: int  # Number of characters in the trail
    chars: list[str]  # Characters in the column
    brightness: list[float]  # Brightness of each character (0-1)

    def update(self, height: int, dt: float) -> None:
        """Update column position and characters."""
        self.y += self.speed * dt * 60  # Normalize to ~60fps

        # Wrap around when off screen
        if self.y - self.length * 20 > height:
            self.y = -self.length * 20
            self.speed = random.uniform(3, 12)
            self.length = random.randint(5, 25)
            self._regenerate_chars()

        # Occasionally change a character
        if random.random() < 0.1:
            idx = random.randint(0, len(self.chars) - 1)
            self.chars[idx] = random.choice(MATRIX_CHARS)

    def _regenerate_chars(self) -> None:
        """Regenerate characters for the column."""
        self.chars = [random.choice(MATRIX_CHARS) for _ in range(self.length)]
        # Brightness gradient - brightest at the head
        self.brightness = [max(0.2, 1.0 - (i / self.length) * 0.8) for i in range(self.length)]


class MatrixAnimation:
    """
    Matrix-style falling characters animation.

    Renders green falling characters with "INITIALIZING..." in the center.
    """

    def __init__(self, width: int, height: int):
        """
        Initialize the animation.

        Args:
            width: Frame width in pixels
            height: Frame height in pixels
        """
        self.width = width
        self.height = height
        self.columns: list[MatrixColumn] = []

        # Character spacing
        self.char_width = 14
        self.char_height = 20

        # Create columns
        num_columns = width // self.char_width
        for i in range(num_columns):
            col = MatrixColumn(
                x=i * self.char_width,
                y=random.uniform(-height, height),
                speed=random.uniform(3, 12),
                length=random.randint(5, 25),
                chars=[],
                brightness=[],
            )
            col._regenerate_chars()
            self.columns.append(col)

        # Center text
        self.center_text = "INITIALIZING..."
        self.center_subtext = "SCANNING MEETING PARTICIPANTS"

        # Animation state
        self.time = 0.0
        self.dot_count = 0
        self.last_dot_time = 0.0

    def update(self, dt: float) -> None:
        """
        Update animation state.

        Args:
            dt: Time delta in seconds
        """
        self.time += dt

        # Update columns
        for col in self.columns:
            col.update(self.height, dt)

        # Update dots animation
        if self.time - self.last_dot_time > 0.5:
            self.dot_count = (self.dot_count + 1) % 4
            self.last_dot_time = self.time

    def render_to_frame(self, frame: np.ndarray) -> np.ndarray:
        """
        Render the animation to a BGR frame.

        Args:
            frame: BGR numpy array to render into (modified in place)

        Returns:
            The modified frame
        """
        import cv2

        # Fill with near-black
        frame[:] = (5, 5, 5)

        # Draw falling characters
        for col in self.columns:
            for i, (char, brightness) in enumerate(zip(col.chars, col.brightness)):
                y = int(col.y - i * self.char_height)

                if 0 <= y < self.height:
                    # Green color with varying brightness
                    green = int(200 * brightness)
                    color = (0, green, 0)

                    # Head character is white-green
                    if i == 0:
                        color = (180, 255, 180)

                    # Draw character
                    cv2.putText(frame, char, (col.x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)

        # Draw center text with glow effect
        center_y = self.height // 2

        # "INITIALIZING..." with animated dots
        dots = "." * self.dot_count
        main_text = f"INITIALIZING{dots}"

        # Get text size for centering
        (text_w, text_h), _ = cv2.getTextSize(main_text, cv2.FONT_HERSHEY_SIMPLEX, 1.5, 2)
        text_x = (self.width - text_w) // 2

        # Draw glow (multiple passes with decreasing alpha)
        for offset in [4, 2]:
            cv2.putText(
                frame,
                main_text,
                (text_x, center_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.5,
                (0, 80, 0),  # Dim green glow
                3 + offset,
                cv2.LINE_AA,
            )

        # Draw main text
        cv2.putText(
            frame,
            main_text,
            (text_x, center_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.5,
            (0, 255, 0),  # Bright green
            2,
            cv2.LINE_AA,
        )

        # Draw subtext
        (sub_w, sub_h), _ = cv2.getTextSize(self.center_subtext, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
        sub_x = (self.width - sub_w) // 2

        cv2.putText(
            frame,
            self.center_subtext,
            (sub_x, center_y + 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 180, 0),
            1,
            cv2.LINE_AA,
        )

        # Draw scanning bar animation
        bar_y = center_y + 100
        bar_width = 400
        bar_x = (self.width - bar_width) // 2

        # Background bar
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_width, bar_y + 10), (0, 50, 0), -1)

        # Animated progress
        progress = (self.time % 3.0) / 3.0  # 3 second cycle
        progress_width = int(bar_width * progress)

        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + progress_width, bar_y + 10), (0, 200, 0), -1)

        return frame

    def render_frame(self, t: float) -> np.ndarray:
        """
        Render a frame at time t.

        Args:
            t: Time in seconds

        Returns:
            BGR numpy array
        """
        # Calculate dt from last render
        dt = t - self.time if t > self.time else 1 / 30
        self.update(dt)

        # Create frame
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        return self.render_to_frame(frame)


class MatrixAnimationGPU:
    """
    GPU-accelerated Matrix animation using OpenGL.

    For use with the existing GPU text renderer.
    """

    def __init__(self, width: int, height: int):
        """Initialize GPU animation."""
        self.width = width
        self.height = height
        self.columns: list[MatrixColumn] = []
        self.time = 0.0
        self.dot_count = 0
        self.last_dot_time = 0.0

        # Character spacing
        self.char_width = 14
        self.char_height = 20

        # Create columns
        num_columns = width // self.char_width
        for i in range(num_columns):
            col = MatrixColumn(
                x=i * self.char_width,
                y=random.uniform(-height, height),
                speed=random.uniform(3, 12),
                length=random.randint(5, 25),
                chars=[],
                brightness=[],
            )
            col._regenerate_chars()
            self.columns.append(col)

    def get_text_items(self, t: float) -> list[tuple]:
        """
        Get text items for GPU rendering.

        Args:
            t: Time in seconds

        Returns:
            List of (text, x, y, color, font_size) tuples
        """
        # Update animation
        dt = t - self.time if t > self.time else 1 / 30
        self.time = t

        for col in self.columns:
            col.update(self.height, dt)

        # Update dots
        if t - self.last_dot_time > 0.5:
            self.dot_count = (self.dot_count + 1) % 4
            self.last_dot_time = t

        items = []

        # Falling characters
        for col in self.columns:
            for i, (char, brightness) in enumerate(zip(col.chars, col.brightness)):
                y = int(col.y - i * self.char_height)

                if 0 <= y < self.height:
                    # Green color with varying brightness
                    if i == 0:
                        color = (180, 255, 180)  # Head is white-green
                    else:
                        green = int(200 * brightness)
                        color = (0, green, 0)

                    items.append((char, col.x, y, color, "tiny"))

        # Center text
        center_y = self.height // 2
        dots = "." * self.dot_count
        main_text = f"INITIALIZING{dots}"

        # Approximate centering (GPU renderer will handle exact positioning)
        text_x = self.width // 2 - 150

        items.append((main_text, text_x, center_y, (0, 255, 0), "large"))

        # Subtext
        subtext = "SCANNING MEETING PARTICIPANTS"
        items.append((subtext, text_x - 50, center_y + 50, (0, 180, 0), "small"))

        return items

    def get_shapes(self, t: float) -> list[tuple]:
        """
        Get shapes for GPU rendering (progress bar).

        Args:
            t: Time in seconds

        Returns:
            List of shape tuples for the GPU renderer
        """
        shapes = []

        center_y = self.height // 2 + 100
        bar_width = 400
        bar_x = (self.width - bar_width) // 2

        # Background bar
        shapes.append(("rect", bar_x, center_y, bar_width, 10, (0, 50, 0)))

        # Progress bar
        progress = (t % 3.0) / 3.0
        progress_width = int(bar_width * progress)
        shapes.append(("rect", bar_x, center_y, progress_width, 10, (0, 200, 0)))

        return shapes
