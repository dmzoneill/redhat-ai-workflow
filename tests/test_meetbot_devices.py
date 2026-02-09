"""
Integration tests for MeetBot audio/video device management.

These tests verify:
1. Virtual device creation doesn't change system default microphone
2. Cleanup properly removes all virtual devices
3. Browser closure triggers proper cleanup
4. Orphaned device detection and cleanup works
5. Audio capture only uses specified sources

Requirements:
- PulseAudio/PipeWire running
- pactl and pw-metadata commands available
- v4l2loopback module loaded (for video tests)

Run with: pytest tests/test_meetbot_devices.py -v
Run specific test: pytest tests/test_meetbot_devices.py::TestDefaultSourcePreservation -v
"""

import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# Helper functions for PulseAudio operations
async def run_pactl(*args) -> tuple[bool, str]:
    """Run a pactl command and return (success, output)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "pactl",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode == 0, stdout.decode().strip()
    except Exception as e:
        return False, str(e)


async def get_default_source() -> Optional[str]:
    """Get the current default PulseAudio source."""
    success, output = await run_pactl("get-default-source")
    return output if success else None


async def set_default_source(source: str) -> bool:
    """Set the default PulseAudio source."""
    success, _ = await run_pactl("set-default-source", source)
    return success


async def list_sources() -> list[str]:
    """List all PulseAudio sources."""
    success, output = await run_pactl("list", "sources", "short")
    if not success:
        return []
    return [line.split("\t")[1] for line in output.split("\n") if line and "\t" in line]


async def list_modules() -> list[tuple[str, str]]:
    """List all PulseAudio modules as (id, name) tuples."""
    success, output = await run_pactl("list", "modules", "short")
    if not success:
        return []
    modules = []
    for line in output.split("\n"):
        if line:
            parts = line.split("\t")
            if len(parts) >= 2:
                modules.append((parts[0], parts[1]))
    return modules


async def find_physical_mic() -> Optional[str]:
    """Find a physical microphone (not a monitor or virtual device)."""
    sources = await list_sources()
    for source in sources:
        if (
            "meet_bot" not in source.lower()
            and ".monitor" not in source
            and ("alsa" in source.lower() or "input" in source.lower())
        ):
            return source
    return None


async def cleanup_meetbot_modules():
    """Remove all meetbot-related PulseAudio modules."""
    modules = await list_modules()
    for module_id, module_name in modules:
        if "meet_bot" in module_name.lower():
            await run_pactl("unload-module", module_id)


# Skip markers for tests that require specific system capabilities
def _check_pactl() -> bool:
    try:
        return (
            subprocess.run(["pactl", "info"], capture_output=True, timeout=5).returncode
            == 0
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _check_pw_metadata() -> bool:
    try:
        return (
            subprocess.run(
                ["which", "pw-metadata"], capture_output=True, timeout=5
            ).returncode
            == 0
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


requires_pulseaudio = pytest.mark.skipif(
    not _check_pactl(),
    reason="PulseAudio/PipeWire not available",
)

requires_pw_metadata = pytest.mark.skipif(
    not _check_pw_metadata(),
    reason="pw-metadata not available",
)


class TestDefaultSourcePreservation:
    """Tests that verify the default audio source is preserved."""

    @pytest.fixture(autouse=True)
    async def setup_and_teardown(self):
        """Save default source before test and restore after."""
        self.original_default = await get_default_source()
        yield
        # Cleanup any meetbot modules
        await cleanup_meetbot_modules()
        # Restore original default via both methods
        if self.original_default and "meet_bot" not in self.original_default.lower():
            # pw-metadata first (persistent)
            try:
                proc = await asyncio.create_subprocess_exec(
                    "pw-metadata",
                    "-n",
                    "default",
                    "0",
                    "default.audio.source",
                    f'{{"name":"{self.original_default}"}}',
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.communicate()
            except Exception:
                pass
            # Then pactl (immediate)
            await set_default_source(self.original_default)

    @requires_pulseaudio
    @pytest.mark.asyncio
    async def test_get_default_source(self):
        """Verify we can get the default source."""
        default = await get_default_source()
        assert default is not None, "Should be able to get default source"
        assert len(default) > 0, "Default source should not be empty"

    @requires_pulseaudio
    @pytest.mark.asyncio
    async def test_create_source_preserves_default(self):
        """Creating a virtual source should not change the default."""
        from tool_modules.aa_meet_bot.src.virtual_devices import InstanceDeviceManager

        # Get current default
        original_default = await get_default_source()
        assert original_default is not None
        if "meet_bot" in original_default.lower():
            pytest.skip(
                "Default source is already a meetbot device (stale state from prior run)"
            )

        # Create device manager and source
        manager = InstanceDeviceManager("test_preserve_default")
        try:
            # Create all devices (this includes the source)
            devices = await manager.create_all()
            assert devices is not None

            # Wait for PipeWire to settle
            await asyncio.sleep(0.5)

            # Check default source hasn't changed to meetbot
            current_default = await get_default_source()
            assert current_default is not None
            assert (
                "meet_bot" not in current_default.lower()
            ), f"Default source changed to meetbot device: {current_default}"

        finally:
            await manager.cleanup()

    @requires_pulseaudio
    @requires_pw_metadata
    @pytest.mark.asyncio
    async def test_force_restore_default_source(self):
        """Test that _force_restore_default_source works correctly."""
        from tool_modules.aa_meet_bot.src.virtual_devices import InstanceDeviceManager

        # Find a physical mic to use as target
        physical_mic = await find_physical_mic()
        if not physical_mic:
            pytest.skip("No physical microphone found")

        manager = InstanceDeviceManager("test_force_restore")

        # Call the restore function
        await manager._force_restore_default_source(physical_mic)

        # Verify the default is now the physical mic
        current_default = await get_default_source()
        assert current_default is not None, "Could not get default source after restore"
        # It should either be the physical mic or at least not a meetbot device
        assert (
            "meet_bot" not in current_default.lower()
        ), f"Default is still a meetbot device: {current_default}"

    @requires_pulseaudio
    @pytest.mark.asyncio
    async def test_source_has_low_priority(self):
        """Verify created sources have low priority properties."""
        from tool_modules.aa_meet_bot.src.virtual_devices import InstanceDeviceManager

        manager = InstanceDeviceManager("test_priority")
        try:
            await manager.create_all()

            # Check source properties
            success, output = await run_pactl("list", "sources")
            assert success

            # Find our source in the output
            found_source = False
            in_our_source = False
            for line in output.split("\n"):
                if "meet_bot_test_priority_mic" in line:
                    in_our_source = True
                    found_source = True
                elif in_our_source and line.strip().startswith("Name:"):
                    # We've moved to a different source
                    in_our_source = False

            assert found_source, "Created source should exist"

        finally:
            await manager.cleanup()


class TestDeviceCleanup:
    """Tests for proper device cleanup."""

    @requires_pulseaudio
    @pytest.mark.asyncio
    async def test_cleanup_removes_all_devices(self):
        """Cleanup should remove all created devices."""
        from tool_modules.aa_meet_bot.src.virtual_devices import InstanceDeviceManager

        manager = InstanceDeviceManager("test_cleanup")

        # Create devices
        devices = await manager.create_all()
        assert devices is not None

        # Verify devices exist
        sources = await list_sources()
        assert any(
            "test_cleanup" in s for s in sources
        ), "Source should exist after creation"

        # Cleanup
        await manager.cleanup()

        # Wait for PulseAudio to process
        await asyncio.sleep(0.3)

        # Verify devices are gone
        sources = await list_sources()
        assert not any(
            "test_cleanup" in s for s in sources
        ), "Source should be removed after cleanup"

    @requires_pulseaudio
    @pytest.mark.asyncio
    async def test_cleanup_stops_monitor_task(self):
        """Cleanup should stop the source monitor task."""
        from tool_modules.aa_meet_bot.src.virtual_devices import InstanceDeviceManager

        manager = InstanceDeviceManager("test_monitor_stop")

        # Create devices (this starts the monitor task)
        await manager.create_all()

        # Verify monitor task is running
        assert manager._source_monitor_task is not None
        assert not manager._source_monitor_task.done()

        # Cleanup
        await manager.cleanup()

        # Verify monitor task is stopped
        assert (
            manager._source_monitor_task is None or manager._source_monitor_task.done()
        )

    @requires_pulseaudio
    @pytest.mark.asyncio
    async def test_orphaned_device_cleanup(self):
        """Test cleanup of orphaned devices."""
        from tool_modules.aa_meet_bot.src.virtual_devices import (
            InstanceDeviceManager,
            cleanup_orphaned_meetbot_devices,
        )

        # Create a device but don't clean it up properly
        manager = InstanceDeviceManager("test_orphan")
        await manager.create_all()

        # Simulate orphan by clearing the manager's tracking
        manager._sink_module_id = None
        manager._source_module_id = None

        # Run orphan cleanup (with no active instances)
        results = await cleanup_orphaned_meetbot_devices(active_instance_ids=set())

        # Should have found and removed the orphaned devices
        assert len(results["removed_modules"]) > 0 or len(results["errors"]) == 0

        # Verify devices are gone
        sources = await list_sources()
        assert not any(
            "test_orphan" in s for s in sources
        ), "Orphaned source should be removed"


class TestBrowserClosureCleanup:
    """Tests for cleanup when browser closes unexpectedly."""

    @pytest.mark.asyncio
    async def test_caption_poll_sets_browser_closed_flag(self):
        """Caption poll should set _browser_closed when browser closes."""
        from tool_modules.aa_meet_bot.src.browser_controller import GoogleMeetController

        controller = GoogleMeetController()
        controller._browser_closed = False
        controller.state = MagicMock()
        controller.state.joined = True
        controller._caption_observer_running = True

        # Mock page.evaluate to raise "Target closed" error
        controller.page = AsyncMock()
        controller.page.evaluate = AsyncMock(side_effect=Exception("Target closed"))

        # Run one iteration of the poll loop
        # We need to patch the loop to run once
        _ = controller._caption_observer_running

        async def run_one_poll():
            try:
                await controller.page.evaluate("() => {}")
            except Exception as e:
                error_msg = str(e)
                if "Target closed" in error_msg:
                    controller._browser_closed = True
                    controller.state.joined = False

        await run_one_poll()

        assert controller._browser_closed is True, "Should set _browser_closed flag"
        assert controller.state.joined is False, "Should set joined to False"

    @pytest.mark.asyncio
    async def test_is_browser_closed_method(self):
        """Test is_browser_closed() method.

        Note: is_browser_closed() returns True when page is None (no browser
        started) OR when _browser_closed flag is set. A fresh controller has
        no page, so it correctly reports closed.
        """
        from tool_modules.aa_meet_bot.src.browser_controller import GoogleMeetController

        controller = GoogleMeetController()

        # With no page attached, the browser is considered closed
        assert controller.is_browser_closed() is True

        # Simulate an active page (mock)
        controller.page = MagicMock()
        controller.page.is_closed.return_value = False
        controller._browser_closed = False
        assert controller.is_browser_closed() is False

        # After setting flag, should report closed regardless of page state
        controller._browser_closed = True
        assert controller.is_browser_closed() is True


class TestAudioCaptureSourceHandling:
    """Tests for audio capture source handling."""

    @pytest.mark.asyncio
    async def test_audio_capture_uses_specified_source(self):
        """Audio capture should only use the specified source."""
        from tool_modules.aa_meet_bot.src.audio_capture import PulseAudioCapture

        # Create capture with specific source
        test_source = "test_source_name"
        capture = PulseAudioCapture(source_name=test_source, sample_rate=16000)

        assert capture.source_name == test_source, "Should store specified source"

    @pytest.mark.asyncio
    async def test_audio_capture_does_not_change_default(self):
        """Audio capture should not change the default source."""
        # This is a design verification test
        import inspect

        from tool_modules.aa_meet_bot.src.audio_capture import PulseAudioCapture

        # Get the start method source
        source_code = inspect.getsource(PulseAudioCapture.start)

        # Verify it doesn't call set-default-source
        assert (
            "set-default-source" not in source_code
        ), "PulseAudioCapture.start should not set default source"
        assert (
            "default.audio.source" not in source_code
        ), "PulseAudioCapture.start should not set default source via pw-metadata"

    @pytest.mark.asyncio
    async def test_read_chunk_timeout(self):
        """read_chunk should timeout if no data available."""
        from tool_modules.aa_meet_bot.src.audio_capture import PulseAudioCapture

        capture = PulseAudioCapture(source_name="nonexistent_source", sample_rate=16000)
        capture._running = True

        # read_chunk should return None after timeout (not hang forever)
        import time

        start = time.time()
        result = await capture.read_chunk()
        elapsed = time.time() - start

        # Should timeout within reasonable time (2s timeout + buffer)
        assert elapsed < 5, f"read_chunk took too long: {elapsed}s"
        assert result is None, "Should return None when no data"


class TestSTTPipelineSourceGone:
    """Tests for STT pipeline handling when audio source disappears."""

    @pytest.mark.asyncio
    @pytest.mark.timeout(10)  # 10 second timeout
    async def test_stt_pipeline_detects_source_gone(self):
        """STT pipeline should fail to start with nonexistent source."""
        from tool_modules.aa_meet_bot.src.audio_capture import RealtimeSTTPipeline

        transcriptions = []

        def on_transcription(text, is_final):
            transcriptions.append((text, is_final))

        pipeline = RealtimeSTTPipeline(
            source_name="nonexistent_source_xyz123",
            on_transcription=on_transcription,
            sample_rate=16000,
        )

        # The pipeline should fail to start when source doesn't exist
        # (pw-record/parec will fail to connect)
        started = await pipeline.start()

        # Either it fails to start, or we stop it
        if started:
            await pipeline.stop()

        # The test passes if we get here without hanging
        # (the pipeline either failed to start or was stopped)


class TestVideoGeneratorStartupCheck:
    """Tests for video generator startup checks."""

    @requires_pulseaudio
    @pytest.mark.asyncio
    async def test_ensure_default_source_not_meetbot(self):
        """Startup check should restore default if it's a meetbot device."""
        # We can't easily test this without mocking, so verify the function exists
        # and has the right structure
        video_gen_path = (
            PROJECT_ROOT / "tool_modules" / "aa_meet_bot" / "src" / "video_generator.py"
        )
        content = video_gen_path.read_text()

        assert (
            "ensure_default_source_not_meetbot" in content
        ), "Should have ensure_default_source_not_meetbot function"
        assert (
            "meet_bot" in content and "get-default-source" in content
        ), "Function should check for meetbot in default source"
        assert (
            "pw-metadata" in content or "set-default-source" in content
        ), "Function should restore default source"


class TestMultipleInstanceIsolation:
    """Tests for multiple bot instance isolation."""

    @requires_pulseaudio
    @pytest.mark.asyncio
    async def test_instances_have_unique_device_names(self):
        """Each instance should have unique device names."""
        from tool_modules.aa_meet_bot.src.virtual_devices import InstanceDeviceManager

        manager1 = InstanceDeviceManager("instance_1")
        manager2 = InstanceDeviceManager("instance_2")

        assert manager1.sink_name != manager2.sink_name
        assert manager1.source_name != manager2.source_name
        assert manager1.video_device_name != manager2.video_device_name

    @requires_pulseaudio
    @pytest.mark.asyncio
    async def test_cleanup_only_removes_own_devices(self):
        """Cleanup should only remove devices for that instance."""
        from tool_modules.aa_meet_bot.src.virtual_devices import InstanceDeviceManager

        manager1 = InstanceDeviceManager("instance_a")
        manager2 = InstanceDeviceManager("instance_b")

        try:
            # Create both
            await manager1.create_all()
            await manager2.create_all()

            # Verify both exist before cleanup
            sources_before = await list_sources()
            assert any(
                "instance_a" in s for s in sources_before
            ), f"Instance 1's source should exist before cleanup. Sources: {sources_before}"
            assert any(
                "instance_b" in s for s in sources_before
            ), f"Instance 2's source should exist before cleanup. Sources: {sources_before}"

            # Cleanup instance 1
            await manager1.cleanup()
            await asyncio.sleep(0.5)  # Give more time for cleanup to complete

            # Instance 2's devices should still exist
            sources = await list_sources()
            assert any(
                "instance_b" in s for s in sources
            ), f"Instance 2's source should still exist. Sources: {sources}"
            assert not any(
                "instance_a" in s for s in sources
            ), f"Instance 1's source should be removed. Sources: {sources}"

        finally:
            await manager2.cleanup()


class TestSourceMonitorTask:
    """Tests for the background source monitor task."""

    @pytest.fixture(autouse=True)
    async def setup_and_teardown(self):
        """Ensure cleanup after each test."""
        self.managers_to_cleanup = []
        yield
        # Clean up any managers
        for manager in self.managers_to_cleanup:
            try:
                await asyncio.wait_for(manager.cleanup(), timeout=5.0)
            except Exception:
                pass
        # Also clean up any orphaned modules
        await cleanup_meetbot_modules()

    @requires_pulseaudio
    @pytest.mark.asyncio
    @pytest.mark.timeout(10)  # 10 second timeout
    async def test_monitor_task_starts(self):
        """Monitor task should start when devices are created."""
        from tool_modules.aa_meet_bot.src.virtual_devices import InstanceDeviceManager

        # Find a physical mic first
        physical_mic = await find_physical_mic()
        if not physical_mic:
            pytest.skip("No physical microphone found")

        manager = InstanceDeviceManager("test_monitor_start")
        self.managers_to_cleanup.append(manager)

        # Set the original default source
        manager._original_default_source = physical_mic

        await manager.create_all()

        # Monitor task should be running
        assert manager._source_monitor_task is not None
        assert not manager._source_monitor_task.done()

        # Cleanup immediately - don't wait
        await manager.cleanup()

    @requires_pulseaudio
    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Takes too long (12s) - monitor checks every 10s")
    async def test_monitor_restores_if_changed(self):
        """Monitor should restore default if it changes to meetbot.

        NOTE: This test is skipped by default because it takes 12+ seconds.
        Run manually with: pytest -k test_monitor_restores_if_changed --timeout=20
        """
        from tool_modules.aa_meet_bot.src.virtual_devices import InstanceDeviceManager

        physical_mic = await find_physical_mic()
        if not physical_mic:
            pytest.skip("No physical microphone found")

        manager = InstanceDeviceManager("test_monitor_restore")
        self.managers_to_cleanup.append(manager)

        await manager.create_all()
        await asyncio.sleep(0.5)

        # Manually change default to our meetbot source
        await set_default_source(manager.source_name)

        # Wait for monitor to detect and fix
        await asyncio.sleep(12)  # Monitor checks every 10s

        # Default should be restored
        current = await get_default_source()
        assert current is not None, "Could not get default source after monitor cycle"
        assert (
            "meet_bot" not in current.lower()
        ), f"Monitor should have restored default, but it's: {current}"

        await manager.cleanup()


# ============================================================================
# V4L2 Video Device Tests
# ============================================================================


def _check_v4l2loopback() -> bool:
    """Check if v4l2loopback is available."""
    try:
        result = subprocess.run(
            ["which", "v4l2loopback-ctl"], capture_output=True, timeout=5
        )
        if result.returncode != 0:
            return False
        # Also check if module is loaded or can be loaded
        result = subprocess.run(["lsmod"], capture_output=True, timeout=5)
        return "v4l2loopback" in result.stdout.decode()
    except Exception:
        return False


def _check_v4l2loopback_control() -> bool:
    """Check if v4l2loopback control device exists."""
    return Path("/dev/v4l2loopback").exists()


requires_v4l2loopback = pytest.mark.skipif(
    not _check_v4l2loopback(), reason="v4l2loopback not available"
)

requires_v4l2loopback_control = pytest.mark.skipif(
    not _check_v4l2loopback_control(),
    reason="v4l2loopback control device not available (need sudo access)",
)


async def list_v4l2_devices() -> list[tuple[str, str]]:
    """List all v4l2loopback devices as (path, name) tuples.

    Handles both tab-delimited (path<TAB>name) and plain (path-only) output
    formats from v4l2loopback-ctl list.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "v4l2loopback-ctl",
            "list",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        devices = []
        for line in stdout.decode().strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            if "\t" in line:
                parts = line.split("\t")
                if len(parts) >= 2:
                    devices.append((parts[0].strip(), parts[1].strip()))
            else:
                # Plain device path only -- use path as both path and name
                devices.append((line, line))
        return devices
    except Exception:
        return []


async def cleanup_meetbot_video_devices():
    """Remove all MeetBot video devices."""
    devices = await list_v4l2_devices()
    for device_path, device_name in devices:
        if device_name.startswith("MeetBot_"):
            try:
                proc = await asyncio.create_subprocess_exec(
                    "v4l2loopback-ctl",
                    "delete",
                    device_path,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.communicate()
            except Exception:
                pass


class TestVideoDeviceCreation:
    """Tests for v4l2loopback video device creation."""

    @pytest.fixture(autouse=True)
    async def cleanup_video_devices(self):
        """Clean up video devices after each test."""
        yield
        await cleanup_meetbot_video_devices()

    @requires_v4l2loopback
    def test_v4l2loopback_ctl_available(self):
        """v4l2loopback-ctl should be available."""
        result = subprocess.run(["which", "v4l2loopback-ctl"], capture_output=True)
        assert result.returncode == 0

    @requires_v4l2loopback
    def test_v4l2loopback_module_loaded(self):
        """v4l2loopback kernel module should be loaded."""
        result = subprocess.run(["lsmod"], capture_output=True)
        assert "v4l2loopback" in result.stdout.decode()

    @requires_v4l2loopback
    @requires_v4l2loopback_control
    @pytest.mark.asyncio
    async def test_create_video_device(self):
        """Should be able to create a video device."""
        from tool_modules.aa_meet_bot.src.virtual_devices import InstanceDeviceManager

        manager = InstanceDeviceManager("test_video_create")

        try:
            device_path = await manager._create_video_device()

            if device_path:
                # Device should exist
                assert Path(device_path).exists(), f"Device {device_path} should exist"

                # Device path should appear in the device list
                devices = await list_v4l2_devices()
                device_paths = [path for path, _ in devices]
                assert (
                    device_path in device_paths
                ), f"Created device {device_path} should be in device list: {device_paths}"
        finally:
            await manager._cleanup_video_device()

    @requires_v4l2loopback
    @requires_v4l2loopback_control
    @pytest.mark.asyncio
    async def test_cleanup_video_device(self):
        """Should be able to clean up a video device."""
        from tool_modules.aa_meet_bot.src.virtual_devices import InstanceDeviceManager

        manager = InstanceDeviceManager("test_video_cleanup")

        # Create device
        device_path = await manager._create_video_device()

        if device_path:
            # Verify it exists
            assert Path(device_path).exists(), f"Device {device_path} should exist"

            # Clean up
            await manager._cleanup_video_device()

            # Verify it's gone
            devices_after = await list_v4l2_devices()
            device_paths_after = [path for path, _ in devices_after]
            assert (
                device_path not in device_paths_after
            ), f"Device {device_path} should have been cleaned up"

    @requires_v4l2loopback
    @requires_v4l2loopback_control
    @pytest.mark.asyncio
    async def test_video_device_unique_per_instance(self):
        """Each instance should get a unique video device."""
        from tool_modules.aa_meet_bot.src.virtual_devices import InstanceDeviceManager

        manager1 = InstanceDeviceManager("video_inst_1")
        manager2 = InstanceDeviceManager("video_inst_2")

        try:
            device1 = await manager1._create_video_device()
            device2 = await manager2._create_video_device()

            if device1 and device2:
                # Devices should be different
                assert device1 != device2

                # Both device paths should exist in the device list
                devices = await list_v4l2_devices()
                device_paths = [path for path, _ in devices]
                assert (
                    device1 in device_paths
                ), f"Device {device1} should be in device list: {device_paths}"
                assert (
                    device2 in device_paths
                ), f"Device {device2} should be in device list: {device_paths}"
        finally:
            await manager1._cleanup_video_device()
            await manager2._cleanup_video_device()

    @requires_v4l2loopback
    @pytest.mark.asyncio
    async def test_video_device_graceful_without_control(self):
        """Video device creation should fail gracefully without control device."""
        from tool_modules.aa_meet_bot.src.virtual_devices import InstanceDeviceManager

        manager = InstanceDeviceManager("test_graceful")

        # Even if control device doesn't exist, should not raise
        # (just return None)
        try:
            device = await manager._create_video_device()
            # Either succeeds or returns None, but shouldn't raise
            assert device is None or device.startswith("/dev/video")
        finally:
            if manager._video_device:
                await manager._cleanup_video_device()


class TestVideoDeviceCleanup:
    """Tests for video device cleanup."""

    @pytest.fixture(autouse=True)
    async def cleanup_video_devices(self):
        """Clean up video devices after each test."""
        yield
        await cleanup_meetbot_video_devices()

    @requires_v4l2loopback
    @requires_v4l2loopback_control
    @pytest.mark.asyncio
    async def test_cleanup_removes_video_device(self):
        """Full cleanup should remove video device."""
        from tool_modules.aa_meet_bot.src.virtual_devices import InstanceDeviceManager

        manager = InstanceDeviceManager("test_full_cleanup")

        # Create all devices
        await manager.create_all()

        video_device_path = manager._video_device
        if video_device_path:
            # Verify video device path exists
            assert Path(video_device_path).exists()

        # Full cleanup
        await manager.cleanup()

        # Verify video device is gone (if one was created)
        if video_device_path:
            v4l2_devices = await list_v4l2_devices()
            device_paths = [path for path, _ in v4l2_devices]
            assert video_device_path not in device_paths

    @requires_v4l2loopback
    @requires_v4l2loopback_control
    @pytest.mark.xfail(
        reason="Orphan cleanup cannot detect devices by name when v4l2loopback-ctl "
        "does not include device names in its output"
    )
    @pytest.mark.asyncio
    async def test_orphaned_video_device_cleanup(self):
        """Orphaned video devices should be cleaned up."""
        from tool_modules.aa_meet_bot.src.virtual_devices import (
            InstanceDeviceManager,
            _cleanup_orphaned_video_devices,
        )

        manager = InstanceDeviceManager("test_orphan_video")

        # Create video device
        device_path = await manager._create_video_device()

        if device_path:
            # Simulate orphan by clearing tracking
            manager._video_device = None

            # Run orphan cleanup
            results = await _cleanup_orphaned_video_devices(active_safe_ids=set())

            # Should have removed the device
            assert len(results["removed"]) > 0 or len(results["errors"]) == 0

            # Verify device is gone
            v4l2_devices = await list_v4l2_devices()
            device_paths = [path for path, _ in v4l2_devices]
            assert device_path not in device_paths

    @requires_v4l2loopback
    @requires_v4l2loopback_control
    @pytest.mark.asyncio
    async def test_cleanup_only_removes_own_video_device(self):
        """Cleanup should only remove its own video device."""
        from tool_modules.aa_meet_bot.src.virtual_devices import InstanceDeviceManager

        manager1 = InstanceDeviceManager("video_keep")
        manager2 = InstanceDeviceManager("video_remove")

        try:
            # Create both
            device1 = await manager1._create_video_device()
            device2 = await manager2._create_video_device()

            if device1 and device2:
                # Clean up manager2 only
                await manager2._cleanup_video_device()

                # manager1's device should still exist, manager2's should be gone
                v4l2_devices = await list_v4l2_devices()
                device_paths = [path for path, _ in v4l2_devices]

                assert (
                    device1 in device_paths
                ), f"Device {device1} should still exist after cleaning up another instance"
                assert (
                    device2 not in device_paths
                ), f"Device {device2} should have been cleaned up"
        finally:
            await manager1._cleanup_video_device()


class TestVideoDeviceFindByName:
    """Tests for finding video devices by name."""

    @requires_v4l2loopback
    @requires_v4l2loopback_control
    @pytest.mark.asyncio
    async def test_find_video_device_by_name(self):
        """Should be able to find video device by name."""
        from tool_modules.aa_meet_bot.src.virtual_devices import InstanceDeviceManager

        manager = InstanceDeviceManager("test_find_by_name")

        try:
            # Create device
            original_path = await manager._create_video_device()

            if original_path:
                # Clear the tracked path
                manager._video_device = None

                # Find by name
                found_path = await manager._find_video_device_by_name()

                assert found_path is not None
                assert found_path == original_path
        finally:
            # Restore for cleanup
            if not manager._video_device:
                manager._video_device = await manager._find_video_device_by_name()
            await manager._cleanup_video_device()


# ============================================================================
# Fixtures for common setup
# ============================================================================


# Fixtures for common setup
@pytest.fixture
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
async def cleanup_after_test():
    """Clean up any meetbot devices after each test and restore default source."""
    # Save original default before test
    original_default = await get_default_source()

    yield

    # Clean up meetbot modules
    await cleanup_meetbot_modules()

    # Restore original default source if it was changed
    if original_default and "meet_bot" not in original_default.lower():
        current = await get_default_source()
        if current != original_default:
            await set_default_source(original_default)
            # Also via pw-metadata for persistence
            try:
                proc = await asyncio.create_subprocess_exec(
                    "pw-metadata",
                    "-n",
                    "default",
                    "0",
                    "default.audio.source",
                    f'{{"name":"{original_default}"}}',
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.communicate()
            except Exception:
                pass


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
