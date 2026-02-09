#!/usr/bin/env python3
"""
Shared v4l2loopback Video Device Management.

Provides functions for creating and managing v4l2loopback virtual camera devices.
Used by both meet_daemon (production) and video_daemon (with --create-device flag).

Usage:
    from scripts.common.video_device import setup_v4l2_device, cleanup_device

    # Create/configure device
    device_path = setup_v4l2_device(1920, 1080)

    # Use device...

    # Cleanup on exit
    cleanup_device()
"""

import logging
import os
import re
import subprocess
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Device configuration
DEVICE_LABEL = "AI_Workflow"  # Our device label
PREFERRED_DEVICE_NUMBERS = [
    10,
    11,
    12,
    13,
    14,
    15,
]  # Avoid 0-9 which may be real cameras

# Global state for cleanup
_active_device_path: Optional[str] = None
_active_v4l2_fd: Optional[int] = None


def find_existing_device() -> Optional[tuple[str, int]]:
    """
    Find an existing AI_Workflow v4l2loopback device.

    Returns:
        Tuple of (device_path, device_number) or None if not found
    """
    try:
        result = subprocess.run(
            ["v4l2-ctl", "--list-devices"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.debug(f"v4l2-ctl not available or timed out: {e}")
        return None
    if result.returncode != 0:
        return None

    lines = result.stdout.split("\n")
    for i, line in enumerate(lines):
        if DEVICE_LABEL in line or "AI_Research" in line:
            # Next line should have the device path
            if i + 1 < len(lines):
                device_line = lines[i + 1].strip()
                if device_line.startswith("/dev/video"):
                    match = re.search(r"/dev/video(\d+)", device_line)
                    if match:
                        return (device_line, int(match.group(1)))
    return None


def find_free_device_number() -> int:
    """
    Find a free video device number.

    Returns:
        Available device number (e.g., 10 for /dev/video10)

    Raises:
        RuntimeError: If no free device numbers available
    """
    for num in PREFERRED_DEVICE_NUMBERS:
        if not os.path.exists(f"/dev/video{num}"):
            return num
    # Fallback to higher numbers
    for num in range(20, 30):
        if not os.path.exists(f"/dev/video{num}"):
            return num
    raise RuntimeError("No free video device numbers available")


def get_device_format(device_path: str) -> tuple[int, int]:
    """
    Get current width/height of a v4l2 device.

    Args:
        device_path: Path to video device (e.g., /dev/video10)

    Returns:
        Tuple of (width, height), or (0, 0) if unable to determine
    """
    try:
        result = subprocess.run(
            ["v4l2-ctl", "-d", device_path, "--get-fmt-video"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.debug(f"Could not get device format: {e}")
        return (0, 0)

    width, height = 0, 0
    for line in result.stdout.split("\n"):
        if "Width/Height" in line:
            match = re.search(r"(\d+)/(\d+)", line)
            if match:
                width, height = int(match.group(1)), int(match.group(2))
                break
    return width, height


def setup_v4l2_device(width: int, height: int, force_reload: bool = False) -> str:
    """
    Set up a v4l2loopback device for streaming.

    ALWAYS reloads the module to ensure correct resolution unless an existing
    device with matching resolution is found.

    v4l2loopback format is set at module load time, not via v4l2-ctl.

    Args:
        width: Desired video width (e.g., 1920)
        height: Desired video height (e.g., 1080)
        force_reload: If True, always reload module even if format matches

    Returns:
        Device path (e.g., /dev/video10)

    Raises:
        RuntimeError: If device setup fails
    """
    global _active_device_path

    logger.info(f"Setting up video device for {width}x{height}...")

    # Check if v4l2loopback module is loaded
    try:
        result = subprocess.run(["lsmod"], capture_output=True, text=True, timeout=10)
        module_loaded = "v4l2loopback" in result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning(f"Could not check loaded modules: {e}")
        module_loaded = False

    # Try to find existing device and check its format
    existing = find_existing_device()
    need_reload = force_reload
    device_num = PREFERRED_DEVICE_NUMBERS[0]  # Default to first preferred

    if existing and not force_reload:
        device_path, device_num = existing
        current_w, current_h = get_device_format(device_path)
        logger.info(f"Found existing device: {device_path} ({current_w}x{current_h})")

        # Check if format matches what we need
        if current_w == width and current_h == height:
            logger.info("Format already correct, reusing device")
            need_reload = False
        else:
            logger.info(
                f"Format mismatch ({current_w}x{current_h} vs {width}x{height}), reloading module..."
            )
            need_reload = True
    elif not existing:
        device_num = find_free_device_number()
        logger.info(f"No existing device, creating /dev/video{device_num}...")
        need_reload = True

    device_path = f"/dev/video{device_num}"

    if need_reload:
        # Kill any processes using the device
        if os.path.exists(device_path):
            subprocess.run(
                ["sudo", "fuser", "-k", device_path], capture_output=True, timeout=5
            )
            time.sleep(0.3)

        # Unload module
        if module_loaded:
            logger.info("Unloading v4l2loopback module...")
            result = subprocess.run(
                ["sudo", "modprobe", "-r", "v4l2loopback"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                # Force kill anything holding it
                subprocess.run(
                    ["sudo", "fuser", "-k", "/dev/video*"],
                    capture_output=True,
                    shell=True,
                )
                time.sleep(0.5)
                subprocess.run(
                    ["sudo", "modprobe", "-r", "v4l2loopback"],
                    capture_output=True,
                    timeout=10,
                )
            time.sleep(0.5)

        # Load with our configuration - max_width/max_height are CRITICAL
        logger.info(f"Loading v4l2loopback: video_nr={device_num}, {width}x{height}...")
        result = subprocess.run(
            [
                "sudo",
                "modprobe",
                "v4l2loopback",
                "devices=1",
                f"video_nr={device_num}",
                f"card_label={DEVICE_LABEL}",
                "exclusive_caps=1",
                f"max_width={width}",
                f"max_height={height}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Failed to load v4l2loopback: {result.stderr}")

        # Wait for device to appear
        for _ in range(30):
            if os.path.exists(device_path):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError(
                f"Device {device_path} did not appear after loading module"
            )

        # Small delay for device to stabilize
        time.sleep(0.3)

    # Verify device exists and is accessible
    if not os.path.exists(device_path):
        raise RuntimeError(f"Device {device_path} does not exist")

    # Check we can open it
    try:
        fd = os.open(device_path, os.O_RDWR | os.O_NONBLOCK)
        os.close(fd)
    except OSError as e:
        raise RuntimeError(f"Cannot open {device_path}: {e}")

    # Verify the format
    actual_w, actual_h = get_device_format(device_path)
    if actual_w > 0 and actual_h > 0 and (actual_w != width or actual_h != height):
        logger.warning(
            f"Device format is {actual_w}x{actual_h}, expected {width}x{height}"
        )

    logger.info(f"Device ready: {device_path} ({width}x{height})")
    _active_device_path = device_path
    return device_path


def cleanup_device():
    """
    Clean up device resources.

    Should be called on exit to release the v4l2 device file descriptor.
    """
    global _active_v4l2_fd, _active_device_path

    if _active_v4l2_fd is not None:
        try:
            os.close(_active_v4l2_fd)
            logger.info(f"Released device: {_active_device_path}")
        except Exception as e:
            logger.warning(f"Error closing device: {e}")
        _active_v4l2_fd = None
    _active_device_path = None


def get_active_device() -> Optional[str]:
    """Get the currently active device path, or None."""
    return _active_device_path


def set_active_fd(fd: int):
    """Set the active file descriptor for cleanup tracking."""
    global _active_v4l2_fd
    _active_v4l2_fd = fd


def unload_v4l2loopback() -> bool:
    """
    Unload the v4l2loopback kernel module.

    Returns:
        True if successful, False otherwise
    """
    # Clean up our state first
    cleanup_device()

    # Check if module is loaded
    result = subprocess.run(["lsmod"], capture_output=True, text=True)
    if "v4l2loopback" not in result.stdout:
        logger.info("v4l2loopback module not loaded")
        return True

    # Kill any processes using video devices
    for num in PREFERRED_DEVICE_NUMBERS:
        device_path = f"/dev/video{num}"
        if os.path.exists(device_path):
            subprocess.run(
                ["sudo", "fuser", "-k", device_path], capture_output=True, timeout=5
            )

    time.sleep(0.3)

    # Unload module
    result = subprocess.run(
        ["sudo", "modprobe", "-r", "v4l2loopback"],
        capture_output=True,
        text=True,
        timeout=10,
    )

    if result.returncode == 0:
        logger.info("Unloaded v4l2loopback module")
        return True
    else:
        logger.error(f"Failed to unload v4l2loopback: {result.stderr}")
        return False
