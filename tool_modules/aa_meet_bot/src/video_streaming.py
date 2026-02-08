"""
V4L2 video streaming and device I/O.

Handles v4l2loopback device setup, format negotiation, and frame output.
Extracted from video_generator.py to separate device I/O concerns from rendering.
"""

import fcntl
import logging
import os
import struct

import numpy as np

logger = logging.getLogger(__name__)

# V4L2 constants
VIDIOC_S_FMT = 0xC0D05605  # _IOWR('V', 5, struct v4l2_format)
V4L2_BUF_TYPE_VIDEO_OUTPUT = 2
V4L2_PIX_FMT_YUYV = 0x56595559  # 'YUYV'
V4L2_FIELD_NONE = 1


class V4L2OutputStream:
    """
    Manages a v4l2loopback output device.

    Handles device open/close, format setup, and frame writes.
    Supports both YUYV frame data and pre-encoded black frames.
    """

    def __init__(self, device_path: str, width: int, height: int):
        """
        Initialize v4l2 output stream.

        Args:
            device_path: Path to v4l2loopback device (e.g., /dev/video10)
            width: Frame width in pixels
            height: Frame height in pixels
        """
        self.device_path = device_path
        self.width = width
        self.height = height
        self._fd: int | None = None

        # Pre-create black frame for "black" mode (YUYV format)
        black_frame = np.zeros((height, width, 2), dtype=np.uint8)
        black_frame[:, :, 0] = 16  # Y (luma) - black
        black_frame[:, :, 1] = 128  # U/V (chroma) - neutral
        self._black_bytes = black_frame.tobytes()

    def open(self) -> None:
        """Open the v4l2 device and set the output format."""
        self._fd = os.open(self.device_path, os.O_RDWR)

        bytesperline = self.width * 2  # YUYV = 2 bytes per pixel
        sizeimage = bytesperline * self.height

        # Build v4l2_format structure (208 bytes total)
        fmt = struct.pack(
            "II"  # type, padding
            + "IIIIIIII"  # width, height, pixelformat, field, bytesperline, sizeimage, colorspace, priv
            + "II"  # flags, ycbcr_enc/hsv_enc
            + "II"  # quantization, xfer_func
            + "152x",  # reserved
            V4L2_BUF_TYPE_VIDEO_OUTPUT,
            0,
            self.width,
            self.height,
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
            fcntl.ioctl(self._fd, VIDIOC_S_FMT, fmt)
            logger.info(f"Set v4l2 format: {self.width}x{self.height} YUYV")
        except OSError as e:
            logger.warning(f"Failed to set v4l2 format via ioctl: {e}")

        # Test write to verify device is ready
        test_frame = np.zeros((self.height, self.width * 2), dtype=np.uint8)
        os.write(self._fd, test_frame.tobytes())
        logger.info("v4l2 output initialized")

    def write_frame(self, yuyv: np.ndarray) -> bool:
        """
        Write a YUYV frame to the v4l2 device.

        Args:
            yuyv: YUYV frame as numpy array (H, W*2)

        Returns:
            True on success, False on error
        """
        try:
            os.write(self._fd, memoryview(yuyv))
            return True
        except OSError as e:
            logger.warning(f"v4l2 write error: {e}")
            return False

    def write_black(self) -> bool:
        """
        Write a pre-encoded black frame to the v4l2 device.

        Returns:
            True on success, False on error
        """
        try:
            os.write(self._fd, self._black_bytes)
            return True
        except OSError as e:
            logger.warning(f"v4l2 write error: {e}")
            return False

    @property
    def fd(self) -> int | None:
        """Return the file descriptor for the v4l2 device."""
        return self._fd

    def close(self) -> None:
        """Close the v4l2 device."""
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
            logger.info(f"Closed v4l2 device: {self.device_path}")
