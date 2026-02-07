"""Tests for scripts/common/video_device.py"""

import os
import subprocess
from unittest.mock import MagicMock, call, patch

import pytest

import scripts.common.video_device as vd
from scripts.common.video_device import (
    DEVICE_LABEL,
    PREFERRED_DEVICE_NUMBERS,
    cleanup_device,
    find_existing_device,
    find_free_device_number,
    get_active_device,
    get_device_format,
    set_active_fd,
    setup_v4l2_device,
    unload_v4l2loopback,
)


@pytest.fixture(autouse=True)
def reset_globals():
    """Reset module globals before and after each test."""
    vd._active_device_path = None
    vd._active_v4l2_fd = None
    yield
    vd._active_device_path = None
    vd._active_v4l2_fd = None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_device_label(self):
        assert DEVICE_LABEL == "AI_Workflow"

    def test_preferred_numbers(self):
        assert PREFERRED_DEVICE_NUMBERS == [10, 11, 12, 13, 14, 15]
        # All should be >= 10 to avoid real cameras
        assert all(n >= 10 for n in PREFERRED_DEVICE_NUMBERS)


# ---------------------------------------------------------------------------
# find_existing_device
# ---------------------------------------------------------------------------


class TestFindExistingDevice:
    @patch("subprocess.run")
    def test_found_ai_workflow(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="AI_Workflow (platform:v4l2loopback-000):\n\t/dev/video10\n\n",
        )
        result = find_existing_device()
        assert result == ("/dev/video10", 10)

    @patch("subprocess.run")
    def test_found_ai_research(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="AI_Research (platform:v4l2loopback-000):\n\t/dev/video12\n\n",
        )
        result = find_existing_device()
        assert result == ("/dev/video12", 12)

    @patch("subprocess.run")
    def test_no_matching_device(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Integrated Camera:\n\t/dev/video0\n\n",
        )
        assert find_existing_device() is None

    @patch("subprocess.run")
    def test_v4l2ctl_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError("not found")
        assert find_existing_device() is None

    @patch("subprocess.run")
    def test_v4l2ctl_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired("v4l2-ctl", 10)
        assert find_existing_device() is None

    @patch("subprocess.run")
    def test_v4l2ctl_error_return(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert find_existing_device() is None

    @patch("subprocess.run")
    def test_device_label_but_no_device_path(self, mock_run):
        # Label present but next line doesn't start with /dev/video
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="AI_Workflow (platform:v4l2loopback):\n\t\n",
        )
        assert find_existing_device() is None

    @patch("subprocess.run")
    def test_label_at_last_line(self, mock_run):
        # Label is the last line, no next line
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="AI_Workflow (platform:v4l2loopback-000):",
        )
        assert find_existing_device() is None


# ---------------------------------------------------------------------------
# find_free_device_number
# ---------------------------------------------------------------------------


class TestFindFreeDeviceNumber:
    @patch("os.path.exists", return_value=False)
    def test_first_preferred(self, mock_exists):
        assert find_free_device_number() == 10

    @patch("os.path.exists")
    def test_third_preferred(self, mock_exists):
        # 10 and 11 exist, 12 is free
        def side_effect(path):
            return path in ("/dev/video10", "/dev/video11")

        mock_exists.side_effect = side_effect
        assert find_free_device_number() == 12

    @patch("os.path.exists", return_value=True)
    def test_all_preferred_taken_fallback(self, mock_exists):
        # All preferred and fallback 20-29 are taken -> RuntimeError
        with pytest.raises(RuntimeError, match="No free"):
            find_free_device_number()

    @patch("os.path.exists")
    def test_fallback_to_20(self, mock_exists):
        # All preferred taken, but 20 is free
        def side_effect(path):
            for n in PREFERRED_DEVICE_NUMBERS:
                if path == f"/dev/video{n}":
                    return True
            return False

        mock_exists.side_effect = side_effect
        assert find_free_device_number() == 20


# ---------------------------------------------------------------------------
# get_device_format
# ---------------------------------------------------------------------------


class TestGetDeviceFormat:
    @patch("subprocess.run")
    def test_parses_width_height(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Format Video Capture:\n\tWidth/Height      : 1920/1080\n\tPixel Format : 'YU12'\n",
        )
        assert get_device_format("/dev/video10") == (1920, 1080)

    @patch("subprocess.run")
    def test_no_width_height_line(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Format Video Capture:\n\tPixel Format : 'YU12'\n",
        )
        assert get_device_format("/dev/video10") == (0, 0)

    @patch("subprocess.run")
    def test_file_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        assert get_device_format("/dev/video10") == (0, 0)

    @patch("subprocess.run")
    def test_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired("v4l2-ctl", 10)
        assert get_device_format("/dev/video10") == (0, 0)


# ---------------------------------------------------------------------------
# setup_v4l2_device
# ---------------------------------------------------------------------------


class TestSetupV4l2Device:
    @patch("scripts.common.video_device.get_device_format", return_value=(1920, 1080))
    @patch(
        "scripts.common.video_device.find_existing_device",
        return_value=("/dev/video10", 10),
    )
    @patch("subprocess.run")
    @patch("os.path.exists", return_value=True)
    @patch("os.open", return_value=5)
    @patch("os.close")
    def test_reuse_existing_matching_format(
        self, mock_close, mock_open, mock_exists, mock_run, mock_find, mock_fmt
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout="v4l2loopback something")
        result = setup_v4l2_device(1920, 1080)
        assert result == "/dev/video10"
        assert vd._active_device_path == "/dev/video10"

    @patch("scripts.common.video_device.get_device_format")
    @patch(
        "scripts.common.video_device.find_existing_device",
        return_value=("/dev/video10", 10),
    )
    @patch("subprocess.run")
    @patch("os.path.exists", return_value=True)
    @patch("os.open", return_value=5)
    @patch("os.close")
    @patch("time.sleep")
    def test_reload_on_format_mismatch(
        self,
        mock_sleep,
        mock_close,
        mock_open,
        mock_exists,
        mock_run,
        mock_find,
        mock_fmt,
    ):
        # First call returns wrong format, second call (after reload) returns correct format
        mock_fmt.side_effect = [(640, 480), (1920, 1080)]
        mock_run.return_value = MagicMock(returncode=0, stdout="v4l2loopback something")
        result = setup_v4l2_device(1920, 1080)
        assert result == "/dev/video10"

    @patch("scripts.common.video_device.get_device_format", return_value=(1920, 1080))
    @patch("scripts.common.video_device.find_existing_device", return_value=None)
    @patch("scripts.common.video_device.find_free_device_number", return_value=10)
    @patch("subprocess.run")
    @patch("os.path.exists", return_value=True)
    @patch("os.open", return_value=5)
    @patch("os.close")
    @patch("time.sleep")
    def test_create_new_device(
        self,
        mock_sleep,
        mock_close,
        mock_open,
        mock_exists,
        mock_run,
        mock_free,
        mock_find,
        mock_fmt,
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        result = setup_v4l2_device(1920, 1080)
        assert result == "/dev/video10"

    @patch("scripts.common.video_device.get_device_format", return_value=(0, 0))
    @patch("scripts.common.video_device.find_existing_device", return_value=None)
    @patch("scripts.common.video_device.find_free_device_number", return_value=10)
    @patch("subprocess.run")
    @patch("os.path.exists", return_value=True)
    @patch("os.open", return_value=5)
    @patch("os.close")
    @patch("time.sleep")
    def test_force_reload(
        self,
        mock_sleep,
        mock_close,
        mock_open,
        mock_exists,
        mock_run,
        mock_free,
        mock_find,
        mock_fmt,
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout="v4l2loopback")
        result = setup_v4l2_device(1920, 1080, force_reload=True)
        assert result == "/dev/video10"

    @patch("scripts.common.video_device.find_existing_device", return_value=None)
    @patch("scripts.common.video_device.find_free_device_number", return_value=10)
    @patch("subprocess.run")
    @patch("os.path.exists")
    @patch("time.sleep")
    def test_device_not_appear_raises(
        self, mock_sleep, mock_exists, mock_run, mock_free, mock_find
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        # Device never appears
        mock_exists.return_value = False
        with pytest.raises(RuntimeError, match="did not appear"):
            setup_v4l2_device(1920, 1080)

    @patch("scripts.common.video_device.get_device_format", return_value=(1920, 1080))
    @patch(
        "scripts.common.video_device.find_existing_device",
        return_value=("/dev/video10", 10),
    )
    @patch("subprocess.run")
    @patch("os.path.exists")
    @patch("os.open", side_effect=OSError("Permission denied"))
    def test_cannot_open_device_raises(
        self, mock_open, mock_exists, mock_run, mock_find, mock_fmt
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout="v4l2loopback")
        mock_exists.return_value = True
        with pytest.raises(RuntimeError, match="Cannot open"):
            setup_v4l2_device(1920, 1080)

    @patch("scripts.common.video_device.get_device_format", return_value=(1920, 1080))
    @patch(
        "scripts.common.video_device.find_existing_device",
        return_value=("/dev/video10", 10),
    )
    @patch("subprocess.run")
    @patch("os.path.exists")
    def test_device_not_exists_after_setup_raises(
        self, mock_exists, mock_run, mock_find, mock_fmt
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout="v4l2loopback")
        # Device does not exist in final check
        mock_exists.return_value = False
        with pytest.raises(RuntimeError, match="does not exist"):
            setup_v4l2_device(1920, 1080)

    @patch("scripts.common.video_device.find_existing_device", return_value=None)
    @patch("scripts.common.video_device.find_free_device_number", return_value=10)
    @patch("subprocess.run")
    @patch("os.path.exists", return_value=True)
    @patch("time.sleep")
    def test_modprobe_fails_raises(
        self, mock_sleep, mock_exists, mock_run, mock_free, mock_find
    ):
        # lsmod succeeds, modprobe -r succeeds, modprobe load fails
        def run_side_effect(cmd, **kwargs):
            if "modprobe" in cmd and "-r" not in cmd and "v4l2loopback" in cmd:
                return MagicMock(returncode=1, stderr="Module not found")
            return MagicMock(returncode=0, stdout="")

        mock_run.side_effect = run_side_effect
        with pytest.raises(RuntimeError, match="Failed to load"):
            setup_v4l2_device(1920, 1080)

    @patch("scripts.common.video_device.get_device_format", return_value=(640, 480))
    @patch(
        "scripts.common.video_device.find_existing_device",
        return_value=("/dev/video10", 10),
    )
    @patch("subprocess.run")
    @patch("os.path.exists", return_value=True)
    @patch("os.open", return_value=5)
    @patch("os.close")
    def test_format_mismatch_warning(
        self, mock_close, mock_open, mock_exists, mock_run, mock_find, mock_fmt
    ):
        """If format verification shows mismatch but device is reusable, log warning."""
        mock_run.return_value = MagicMock(returncode=0, stdout="v4l2loopback")
        # First call: existing format (matching to avoid reload)
        # Second call: verification shows mismatch
        mock_fmt.side_effect = [(1920, 1080), (640, 480)]
        result = setup_v4l2_device(1920, 1080)
        assert result == "/dev/video10"


# ---------------------------------------------------------------------------
# cleanup_device
# ---------------------------------------------------------------------------


class TestCleanupDevice:
    def test_cleanup_with_fd(self):
        vd._active_v4l2_fd = 42
        vd._active_device_path = "/dev/video10"
        with patch("os.close") as mock_close:
            cleanup_device()
            mock_close.assert_called_once_with(42)
        assert vd._active_v4l2_fd is None
        assert vd._active_device_path is None

    def test_cleanup_without_fd(self):
        vd._active_v4l2_fd = None
        vd._active_device_path = "/dev/video10"
        cleanup_device()
        assert vd._active_device_path is None

    def test_cleanup_close_error_handled(self):
        vd._active_v4l2_fd = 42
        vd._active_device_path = "/dev/video10"
        with patch("os.close", side_effect=OSError("bad fd")):
            cleanup_device()  # Should not raise
        assert vd._active_v4l2_fd is None
        assert vd._active_device_path is None


# ---------------------------------------------------------------------------
# get_active_device / set_active_fd
# ---------------------------------------------------------------------------


class TestActiveDeviceHelpers:
    def test_get_active_device_none(self):
        assert get_active_device() is None

    def test_get_active_device_set(self):
        vd._active_device_path = "/dev/video10"
        assert get_active_device() == "/dev/video10"

    def test_set_active_fd(self):
        set_active_fd(99)
        assert vd._active_v4l2_fd == 99


# ---------------------------------------------------------------------------
# unload_v4l2loopback
# ---------------------------------------------------------------------------


class TestUnloadV4l2loopback:
    @patch("subprocess.run")
    @patch("os.path.exists", return_value=False)
    @patch("time.sleep")
    def test_module_not_loaded(self, mock_sleep, mock_exists, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="some_module 12345 0")
        result = unload_v4l2loopback()
        assert result is True

    @patch("subprocess.run")
    @patch("os.path.exists", return_value=False)
    @patch("time.sleep")
    def test_unload_success(self, mock_sleep, mock_exists, mock_run):
        # lsmod shows v4l2loopback, modprobe -r succeeds
        def run_side_effect(cmd, **kwargs):
            if cmd == ["lsmod"]:
                return MagicMock(returncode=0, stdout="v4l2loopback 12345 0")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = run_side_effect
        result = unload_v4l2loopback()
        assert result is True

    @patch("subprocess.run")
    @patch("os.path.exists", return_value=False)
    @patch("time.sleep")
    def test_unload_failure(self, mock_sleep, mock_exists, mock_run):
        def run_side_effect(cmd, **kwargs):
            if cmd == ["lsmod"]:
                return MagicMock(returncode=0, stdout="v4l2loopback 12345 0")
            if "modprobe" in cmd:
                return MagicMock(returncode=1, stderr="Device busy")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = run_side_effect
        result = unload_v4l2loopback()
        assert result is False

    @patch("subprocess.run")
    @patch("os.path.exists")
    @patch("time.sleep")
    def test_kills_processes_on_devices(self, mock_sleep, mock_exists, mock_run):
        mock_exists.side_effect = lambda p: p == "/dev/video10"

        def run_side_effect(cmd, **kwargs):
            if cmd == ["lsmod"]:
                return MagicMock(returncode=0, stdout="v4l2loopback 12345 0")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = run_side_effect
        unload_v4l2loopback()
        # Should have called fuser -k on the existing device
        fuser_calls = [
            c for c in mock_run.call_args_list if len(c[0]) > 0 and "fuser" in c[0][0]
        ]
        assert len(fuser_calls) >= 1

    def test_cleans_up_own_state_first(self):
        vd._active_v4l2_fd = 42
        vd._active_device_path = "/dev/video10"
        with (
            patch("os.close"),
            patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="")),
            patch("os.path.exists", return_value=False),
            patch("time.sleep"),
        ):
            unload_v4l2loopback()
        assert vd._active_v4l2_fd is None
        assert vd._active_device_path is None
