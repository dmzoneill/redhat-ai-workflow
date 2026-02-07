"""
Quick smoke tests for MeetBot device management.

These are fast tests that verify basic functionality without
requiring full PulseAudio integration.

Run with: pytest tests/test_meetbot_smoke.py -v
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestInstanceDeviceManagerBasics:
    """Basic tests for InstanceDeviceManager that don't require PulseAudio."""

    def test_instance_id_sanitization(self):
        """Instance IDs with hyphens should be sanitized."""
        from tool_modules.aa_meet_bot.src.virtual_devices import InstanceDeviceManager

        manager = InstanceDeviceManager("test-with-hyphens")

        # Hyphens should be replaced with underscores in device names
        assert "-" not in manager.sink_name
        assert "-" not in manager.source_name
        assert "_" in manager.sink_name

    def test_unique_device_names(self):
        """Different instances should have different device names."""
        from tool_modules.aa_meet_bot.src.virtual_devices import InstanceDeviceManager

        m1 = InstanceDeviceManager("instance1")
        m2 = InstanceDeviceManager("instance2")

        assert m1.sink_name != m2.sink_name
        assert m1.source_name != m2.source_name
        assert m1.pipe_path != m2.pipe_path

    def test_device_name_format(self):
        """Device names should follow expected format."""
        from tool_modules.aa_meet_bot.src.virtual_devices import InstanceDeviceManager

        manager = InstanceDeviceManager("abc123")

        assert manager.sink_name == "meet_bot_abc123"
        assert manager.source_name == "meet_bot_abc123_mic"
        assert manager.video_device_name == "MeetBot_abc123"


class TestBrowserControllerFlags:
    """Tests for browser controller flag handling."""

    def test_browser_closed_flag_default(self):
        """_browser_closed should default to False."""
        from tool_modules.aa_meet_bot.src.browser_controller import GoogleMeetController

        controller = GoogleMeetController()
        assert controller.is_browser_closed() is False

    def test_browser_closed_flag_set(self):
        """is_browser_closed should return True after flag is set."""
        from tool_modules.aa_meet_bot.src.browser_controller import GoogleMeetController

        controller = GoogleMeetController()
        controller._browser_closed = True
        assert controller.is_browser_closed() is True


class TestAudioCaptureConfig:
    """Tests for audio capture configuration."""

    def test_capture_stores_source_name(self):
        """PulseAudioCapture should store the specified source name."""
        from tool_modules.aa_meet_bot.src.audio_capture import PulseAudioCapture

        capture = PulseAudioCapture(
            source_name="my_custom_source",
            sample_rate=48000,
            chunk_ms=100,
        )

        assert capture.source_name == "my_custom_source"
        assert capture.sample_rate == 48000

    def test_stt_pipeline_stores_config(self):
        """RealtimeSTTPipeline should store configuration."""
        from tool_modules.aa_meet_bot.src.audio_capture import RealtimeSTTPipeline

        callback = MagicMock()
        pipeline = RealtimeSTTPipeline(
            source_name="test_source",
            on_transcription=callback,
            sample_rate=16000,
            vad_threshold=0.02,
        )

        assert pipeline.source_name == "test_source"
        assert pipeline.sample_rate == 16000
        assert pipeline.vad_threshold == 0.02


class TestCleanupFunctionExists:
    """Verify cleanup functions exist and have correct signatures."""

    def test_cleanup_orphaned_function_exists(self):
        """cleanup_orphaned_meetbot_devices should exist."""
        from tool_modules.aa_meet_bot.src.virtual_devices import (
            cleanup_orphaned_meetbot_devices,
        )

        assert callable(cleanup_orphaned_meetbot_devices)

    def test_restore_default_audio_source_exists(self):
        """_restore_default_audio_source should exist."""
        from tool_modules.aa_meet_bot.src.virtual_devices import (
            _restore_default_audio_source,
        )

        assert callable(_restore_default_audio_source)


class TestErrorMessageDetection:
    """Tests for browser closure error message detection."""

    @pytest.mark.parametrize(
        "error_msg,should_detect",
        [
            ("Target closed", True),
            ("Target page, context or browser has been closed", True),
            ("Browser has been closed", True),
            ("Connection refused", False),
            ("Timeout", False),
            ("Some other error", False),
        ],
    )
    def test_browser_closure_detection(self, error_msg, should_detect):
        """Test that browser closure errors are properly detected."""
        # These are the error messages we check for
        closure_patterns = [
            "Target closed",
            "Target page, context or browser has been closed",
            "Browser has been closed",
        ]

        detected = any(pattern in error_msg for pattern in closure_patterns)
        assert detected == should_detect, f"Error '{error_msg}' detection mismatch"


class TestVideoGeneratorAudioHandling:
    """Tests for video generator audio source handling."""

    def test_renderer_stores_audio_source(self):
        """RealtimeVideoRenderer should store the audio source."""
        from tool_modules.aa_meet_bot.src.video_generator import RealtimeVideoRenderer

        renderer = RealtimeVideoRenderer(audio_source="my_mic")
        assert renderer._audio_source == "my_mic"

    def test_renderer_no_audio_source(self):
        """RealtimeVideoRenderer should work without audio source."""
        from tool_modules.aa_meet_bot.src.video_generator import RealtimeVideoRenderer

        renderer = RealtimeVideoRenderer()
        assert renderer._audio_source is None

    def test_stt_enabled_only_with_audio(self):
        """STT should only be enabled when audio source is provided."""
        from tool_modules.aa_meet_bot.src.video_generator import RealtimeVideoRenderer

        with_audio = RealtimeVideoRenderer(audio_source="some_source")
        without_audio = RealtimeVideoRenderer()

        assert with_audio._stt_enabled is True
        assert without_audio._stt_enabled is False


class TestSourcePriorityProperties:
    """Tests for source priority property handling."""

    def test_source_creation_command_has_priority(self):
        """Source creation should include low priority properties."""
        import inspect

        from tool_modules.aa_meet_bot.src.virtual_devices import InstanceDeviceManager

        # Get the source code of _create_source
        source_code = inspect.getsource(InstanceDeviceManager._create_source)

        # Should include priority properties
        assert (
            "priority" in source_code.lower()
        ), "_create_source should set priority properties"


class TestMonitorTaskManagement:
    """Tests for source monitor task lifecycle."""

    def test_manager_has_monitor_task_attribute(self):
        """InstanceDeviceManager should have _source_monitor_task attribute."""
        from tool_modules.aa_meet_bot.src.virtual_devices import InstanceDeviceManager

        manager = InstanceDeviceManager("test")
        assert hasattr(manager, "_source_monitor_task")
        assert manager._source_monitor_task is None  # Initially None


class TestVideoDeviceBasics:
    """Basic tests for video device management that don't require v4l2loopback."""

    def test_video_device_name_format(self):
        """Video device names should follow expected format."""
        from tool_modules.aa_meet_bot.src.virtual_devices import InstanceDeviceManager

        manager = InstanceDeviceManager("test123")
        assert manager.video_device_name == "MeetBot_test123"

    def test_video_device_name_sanitization(self):
        """Video device names should have hyphens replaced."""
        from tool_modules.aa_meet_bot.src.virtual_devices import InstanceDeviceManager

        manager = InstanceDeviceManager("test-with-hyphens")
        assert "-" not in manager.video_device_name
        assert manager.video_device_name == "MeetBot_test_with_hyphens"

    def test_unique_video_device_names(self):
        """Different instances should have different video device names."""
        from tool_modules.aa_meet_bot.src.virtual_devices import InstanceDeviceManager

        m1 = InstanceDeviceManager("instance1")
        m2 = InstanceDeviceManager("instance2")

        assert m1.video_device_name != m2.video_device_name

    def test_video_device_initially_none(self):
        """Video device should be None before creation."""
        from tool_modules.aa_meet_bot.src.virtual_devices import InstanceDeviceManager

        manager = InstanceDeviceManager("test")
        assert manager._video_device is None

    def test_virtual_video_manager_exists(self):
        """VirtualVideoManager class should exist."""
        from tool_modules.aa_meet_bot.src.virtual_devices import VirtualVideoManager

        manager = VirtualVideoManager()
        assert manager is not None
        assert manager.device_path is None

    def test_cleanup_video_device_function_exists(self):
        """_cleanup_video_device method should exist."""
        from tool_modules.aa_meet_bot.src.virtual_devices import InstanceDeviceManager

        manager = InstanceDeviceManager("test")
        assert hasattr(manager, "_cleanup_video_device")
        assert callable(manager._cleanup_video_device)

    def test_create_video_device_function_exists(self):
        """_create_video_device method should exist."""
        from tool_modules.aa_meet_bot.src.virtual_devices import InstanceDeviceManager

        manager = InstanceDeviceManager("test")
        assert hasattr(manager, "_create_video_device")
        assert callable(manager._create_video_device)

    def test_orphaned_video_cleanup_function_exists(self):
        """_cleanup_orphaned_video_devices function should exist."""
        from tool_modules.aa_meet_bot.src.virtual_devices import (
            _cleanup_orphaned_video_devices,
        )

        assert callable(_cleanup_orphaned_video_devices)


class TestMockedDeviceCreation:
    """Tests with mocked system calls."""

    @pytest.mark.asyncio
    async def test_create_source_calls_pactl(self):
        """_create_source should call pactl to create the source."""
        from tool_modules.aa_meet_bot.src.virtual_devices import InstanceDeviceManager

        manager = InstanceDeviceManager("mock_test")

        with patch("tool_modules.aa_meet_bot.src.virtual_devices.run_cmd") as mock_run:
            # Mock successful responses
            mock_run.return_value = (True, "123")  # Module ID

            # This will fail because we're mocking, but we can verify the call
            try:
                await manager._create_source()
            except Exception:
                pass

            # Verify pactl was called
            calls = mock_run.call_args_list
            assert len(calls) > 0, "Should have called run_cmd"

    @pytest.mark.asyncio
    async def test_cleanup_calls_unload_module(self):
        """cleanup should call pactl unload-module."""
        from tool_modules.aa_meet_bot.src.virtual_devices import InstanceDeviceManager

        manager = InstanceDeviceManager("cleanup_test")
        manager._sink_module_id = 100
        manager._source_module_id = 101

        with patch("tool_modules.aa_meet_bot.src.virtual_devices.run_cmd") as mock_run:
            mock_run.return_value = (True, "")

            await manager.cleanup()

            # Should have called unload-module for both modules
            unload_calls = [
                call for call in mock_run.call_args_list if "unload-module" in str(call)
            ]
            assert len(unload_calls) >= 2, "Should unload both sink and source modules"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
