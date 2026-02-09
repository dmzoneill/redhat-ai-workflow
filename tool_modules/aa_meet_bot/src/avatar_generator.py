"""
Avatar Generator - Creates fallback avatars with initials.

When a profile photo is not available, generates a colored circle
with the user's initials. Color is deterministic based on name hash.
"""

import colorsys
import hashlib
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

# Cache directory for generated avatars
AVATAR_CACHE_DIR = Path.home() / ".cache" / "aa-workflow" / "avatars"


def get_initials(name: str) -> str:
    """
    Extract initials from a name.

    Args:
        name: Full name (e.g., "John Doe")

    Returns:
        Initials (e.g., "JD")
    """
    if not name:
        return "?"

    parts = name.split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    elif len(parts) == 1 and len(parts[0]) >= 2:
        return parts[0][:2].upper()
    elif len(parts) == 1:
        return parts[0][0].upper()
    return "?"


def get_color_for_name(name: str) -> Tuple[int, int, int]:
    """
    Get a deterministic color for a name.

    Uses HSV color space with fixed saturation and value
    for visually pleasing, distinct colors.

    Args:
        name: Name to generate color for

    Returns:
        BGR color tuple (for OpenCV)
    """
    # Hash the name for deterministic color
    name_hash = hashlib.md5(name.lower().encode()).hexdigest()

    # Use first 6 hex chars for hue (0-360)
    hue = int(name_hash[:6], 16) % 360

    # Fixed saturation and value for nice colors
    saturation = 0.65
    value = 0.85

    # Convert HSV to RGB
    r, g, b = colorsys.hsv_to_rgb(hue / 360, saturation, value)

    # Convert to 0-255 range and BGR order for OpenCV
    return (int(b * 255), int(g * 255), int(r * 255))


def generate_initials_avatar(
    name: str, size: int = 128, use_cache: bool = True
) -> np.ndarray:
    """
    Generate an avatar with initials on a colored circle.

    Args:
        name: Name to generate avatar for
        size: Avatar size in pixels (square)
        use_cache: Whether to use/save cached avatars

    Returns:
        BGR numpy array of shape (size, size, 3)
    """
    import cv2

    # Check cache
    if use_cache:
        cache_path = _get_cache_path(name, size)
        if cache_path.exists():
            cached = cv2.imread(str(cache_path))
            if cached is not None:
                return cached

    # Create blank image with alpha
    avatar = np.zeros((size, size, 3), dtype=np.uint8)

    # Get color and initials
    bg_color = get_color_for_name(name)
    initials = get_initials(name)

    # Draw filled circle
    center = (size // 2, size // 2)
    radius = size // 2 - 2  # Small margin
    cv2.circle(avatar, center, radius, bg_color, -1, cv2.LINE_AA)

    # Calculate text size for centering
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = size / 80  # Scale font with avatar size
    thickness = max(1, int(size / 40))

    (text_w, text_h), baseline = cv2.getTextSize(initials, font, font_scale, thickness)

    # Center text
    text_x = (size - text_w) // 2
    text_y = (size + text_h) // 2

    # Draw initials in white
    cv2.putText(
        avatar,
        initials,
        (text_x, text_y),
        font,
        font_scale,
        (255, 255, 255),
        thickness,
        cv2.LINE_AA,
    )

    # Save to cache
    if use_cache:
        cache_path = _get_cache_path(name, size)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(cache_path), avatar)

    return avatar


def generate_initials_avatar_rgba(name: str, size: int = 128) -> np.ndarray:
    """
    Generate an avatar with transparent background.

    Args:
        name: Name to generate avatar for
        size: Avatar size in pixels (square)

    Returns:
        BGRA numpy array of shape (size, size, 4)
    """
    import cv2

    # Create blank image with alpha
    avatar = np.zeros((size, size, 4), dtype=np.uint8)

    # Get color and initials
    bg_color = get_color_for_name(name)
    initials = get_initials(name)

    # Create mask for circle
    mask = np.zeros((size, size), dtype=np.uint8)
    center = (size // 2, size // 2)
    radius = size // 2 - 2
    cv2.circle(mask, center, radius, 255, -1, cv2.LINE_AA)

    # Draw filled circle
    avatar[:, :, 0] = bg_color[0]  # B
    avatar[:, :, 1] = bg_color[1]  # G
    avatar[:, :, 2] = bg_color[2]  # R
    avatar[:, :, 3] = mask  # Alpha

    # Calculate text size for centering
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = size / 80
    thickness = max(1, int(size / 40))

    (text_w, text_h), baseline = cv2.getTextSize(initials, font, font_scale, thickness)

    text_x = (size - text_w) // 2
    text_y = (size + text_h) // 2

    # Draw initials in white
    cv2.putText(
        avatar,
        initials,
        (text_x, text_y),
        font,
        font_scale,
        (255, 255, 255, 255),
        thickness,
        cv2.LINE_AA,
    )

    return avatar


def _get_cache_path(name: str, size: int) -> Path:
    """Get cache path for an avatar."""
    # Use hash of name for filename
    name_hash = hashlib.md5(name.lower().encode()).hexdigest()[:12]
    return AVATAR_CACHE_DIR / f"{name_hash}_{size}.png"


def load_or_generate_avatar(
    name: str, photo_path: Optional[str] = None, size: int = 128
) -> np.ndarray:
    """
    Load a profile photo or generate an initials avatar.

    Args:
        name: Name for fallback avatar
        photo_path: Path to profile photo (optional)
        size: Desired size in pixels

    Returns:
        BGR numpy array of shape (size, size, 3)
    """
    import cv2

    # Try to load photo
    if photo_path:
        photo = cv2.imread(photo_path)
        if photo is not None:
            # Resize to target size
            photo = cv2.resize(photo, (size, size), interpolation=cv2.INTER_AREA)
            return photo

    # Generate initials avatar
    return generate_initials_avatar(name, size)


def create_circular_avatar(image: np.ndarray, size: int = 128) -> np.ndarray:
    """
    Create a circular avatar from a square image.

    Args:
        image: BGR numpy array
        size: Output size in pixels

    Returns:
        BGR numpy array with circular mask applied
    """
    import cv2

    # Resize if needed
    if image.shape[0] != size or image.shape[1] != size:
        image = cv2.resize(image, (size, size), interpolation=cv2.INTER_AREA)

    # Create circular mask
    mask = np.zeros((size, size), dtype=np.uint8)
    center = (size // 2, size // 2)
    radius = size // 2 - 1
    cv2.circle(mask, center, radius, 255, -1, cv2.LINE_AA)

    # Apply mask
    result = np.zeros_like(image)
    result[mask == 255] = image[mask == 255]

    return result


# OpenGL texture generation for GPU rendering
def generate_avatar_texture_data(
    name: str, photo_path: Optional[str] = None, size: int = 128
) -> Tuple[np.ndarray, int, int]:
    """
    Generate avatar data suitable for OpenGL texture upload.

    Args:
        name: Name for fallback avatar
        photo_path: Path to profile photo (optional)
        size: Texture size in pixels

    Returns:
        Tuple of (RGBA data as bytes, width, height)
    """
    import cv2

    # Get BGR avatar
    avatar = load_or_generate_avatar(name, photo_path, size)

    # Make circular
    avatar = create_circular_avatar(avatar, size)

    # Convert BGR to RGBA for OpenGL
    rgba = cv2.cvtColor(avatar, cv2.COLOR_BGR2RGBA)

    # Set alpha based on circular mask
    mask = np.zeros((size, size), dtype=np.uint8)
    center = (size // 2, size // 2)
    radius = size // 2 - 1
    cv2.circle(mask, center, radius, 255, -1, cv2.LINE_AA)
    rgba[:, :, 3] = mask

    return rgba, size, size
