"""Tests for tool_modules/aa_workflow/src/notification_engine.py - Multi-channel notifications."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from tool_modules.aa_workflow.src.notification_engine import (
    DesktopNotificationBackend,
    MemoryNotificationBackend,
    NotificationBackend,
    NotificationEngine,
    SlackNotificationBackend,
    get_notification_engine,
    init_notification_engine,
    send_notification,
)

# ==================== NotificationBackend (base) ====================


class TestNotificationBackend:
    """Tests for the base NotificationBackend."""

    @pytest.mark.asyncio
    async def test_send_raises_not_implemented(self):
        backend = NotificationBackend()
        with pytest.raises(NotImplementedError):
            await backend.send("title", "message")


# ==================== SlackNotificationBackend ====================


class TestSlackNotificationBackend:
    """Tests for SlackNotificationBackend."""

    @pytest.mark.asyncio
    async def test_no_server(self):
        backend = SlackNotificationBackend(server=None)
        result = await backend.send("Test", "Message")
        assert result is False

    @pytest.mark.asyncio
    async def test_no_channel(self):
        server = AsyncMock()
        backend = SlackNotificationBackend(server=server, config={})
        result = await backend.send("Test", "Message")
        assert result is False

    @pytest.mark.asyncio
    async def test_channel_from_kwargs(self):
        server = AsyncMock()
        backend = SlackNotificationBackend(server=server, config={})
        result = await backend.send("Test", "Message", channel="C123")
        assert result is True
        server.call_tool.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_channel_from_config_default(self):
        server = AsyncMock()
        backend = SlackNotificationBackend(
            server=server, config={"default_channel": "C456"}
        )
        result = await backend.send("Test", "Message")
        assert result is True

    @pytest.mark.asyncio
    async def test_channel_from_self_dm(self):
        server = AsyncMock()
        backend = SlackNotificationBackend(
            server=server, config={"self_dm_channel": "D789"}
        )
        result = await backend.send("Test", "Message")
        assert result is True

    @pytest.mark.asyncio
    async def test_success_emoji(self):
        server = AsyncMock()
        backend = SlackNotificationBackend(
            server=server, config={"default_channel": "C1"}
        )
        await backend.send("Title", "Body", success=True)
        call_args = server.call_tool.call_args
        message = (
            call_args[1]["message"]
            if "message" in (call_args[1] or {})
            else call_args[0][1]["message"]
        )
        assert "\u2705" in message  # checkmark

    @pytest.mark.asyncio
    async def test_failure_emoji(self):
        server = AsyncMock()
        backend = SlackNotificationBackend(
            server=server, config={"default_channel": "C1"}
        )
        await backend.send("Title", "Body", success=False)
        call_args = server.call_tool.call_args
        message = call_args[0][1]["message"]
        assert "\u274c" in message  # cross mark

    @pytest.mark.asyncio
    async def test_truncates_long_message(self):
        server = AsyncMock()
        backend = SlackNotificationBackend(
            server=server, config={"default_channel": "C1"}
        )
        long_msg = "x" * 3000
        await backend.send("Title", long_msg)
        call_args = server.call_tool.call_args
        message = call_args[0][1]["message"]
        # Message body should be truncated to 2000
        # Total includes emoji + title + newlines + truncated body
        assert len(message) < 2100

    @pytest.mark.asyncio
    async def test_send_error(self):
        server = AsyncMock()
        server.call_tool.side_effect = RuntimeError("API down")
        backend = SlackNotificationBackend(
            server=server, config={"default_channel": "C1"}
        )
        result = await backend.send("Title", "Body")
        assert result is False


# ==================== DesktopNotificationBackend ====================


class TestDesktopNotificationBackend:
    """Tests for DesktopNotificationBackend."""

    @pytest.mark.asyncio
    @patch(
        "tool_modules.aa_workflow.src.notification_engine.platform.system",
        return_value="Linux",
    )
    async def test_linux_success(self, _mock_sys):
        backend = DesktopNotificationBackend()
        backend.system = "Linux"
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        with patch(
            "asyncio.create_subprocess_exec", return_value=mock_proc
        ) as mock_exec:
            result = await backend.send("Title", "Message", success=True)
            assert result is True
            # Check that notify-send was called
            call_args = mock_exec.call_args[0]
            assert call_args[0] == "notify-send"
            assert "dialog-information" in call_args
            assert "normal" in call_args

    @pytest.mark.asyncio
    async def test_linux_failure_urgency(self):
        backend = DesktopNotificationBackend()
        backend.system = "Linux"
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        with patch(
            "asyncio.create_subprocess_exec", return_value=mock_proc
        ) as mock_exec:
            await backend.send("Title", "Error", success=False)
            call_args = mock_exec.call_args[0]
            assert "dialog-error" in call_args
            assert "critical" in call_args

    @pytest.mark.asyncio
    async def test_linux_notify_send_fails(self):
        backend = DesktopNotificationBackend()
        backend.system = "Linux"
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await backend.send("Title", "Message")
            assert result is False

    @pytest.mark.asyncio
    async def test_macos_success(self):
        backend = DesktopNotificationBackend()
        backend.system = "Darwin"
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        with patch(
            "asyncio.create_subprocess_exec", return_value=mock_proc
        ) as mock_exec:
            result = await backend.send("Title", "Message")
            assert result is True
            call_args = mock_exec.call_args[0]
            assert call_args[0] == "osascript"

    @pytest.mark.asyncio
    async def test_macos_escapes_quotes(self):
        backend = DesktopNotificationBackend()
        backend.system = "Darwin"
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        with patch(
            "asyncio.create_subprocess_exec", return_value=mock_proc
        ) as mock_exec:
            await backend.send('Say "hello"', 'The "test"')
            call_args = mock_exec.call_args[0]
            script = call_args[2]
            assert '\\"' in script

    @pytest.mark.asyncio
    async def test_unsupported_platform(self):
        backend = DesktopNotificationBackend()
        backend.system = "Windows"
        result = await backend.send("Title", "Message")
        assert result is False

    @pytest.mark.asyncio
    async def test_truncates_long_message(self):
        backend = DesktopNotificationBackend()
        backend.system = "Linux"
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        with patch(
            "asyncio.create_subprocess_exec", return_value=mock_proc
        ) as mock_exec:
            long_msg = "x" * 500
            await backend.send("Title", long_msg)
            call_args = mock_exec.call_args[0]
            # The message arg (last positional) should be truncated
            msg_arg = call_args[-1]
            assert len(msg_arg) <= 203  # 200 + "..."

    @pytest.mark.asyncio
    async def test_exception_handling(self):
        backend = DesktopNotificationBackend()
        backend.system = "Linux"
        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError("notify-send not found"),
        ):
            result = await backend.send("Title", "Message")
            assert result is False


# ==================== MemoryNotificationBackend ====================


class TestMemoryNotificationBackend:
    """Tests for MemoryNotificationBackend."""

    @pytest.mark.asyncio
    async def test_send_creates_file(self, tmp_path):
        backend = MemoryNotificationBackend(memory_dir=tmp_path)
        result = await backend.send(
            "Test Title", "Test message", success=True, job_name="test_job"
        )
        assert result is True
        assert backend.notifications_file.exists()

        with open(backend.notifications_file) as f:
            data = yaml.safe_load(f)
        assert len(data["notifications"]) == 1
        assert data["notifications"][0]["title"] == "Test Title"
        assert data["notifications"][0]["job_name"] == "test_job"

    @pytest.mark.asyncio
    async def test_appends_to_existing(self, tmp_path):
        backend = MemoryNotificationBackend(memory_dir=tmp_path)
        await backend.send("First", "msg1")
        await backend.send("Second", "msg2")

        with open(backend.notifications_file) as f:
            data = yaml.safe_load(f)
        assert len(data["notifications"]) == 2

    @pytest.mark.asyncio
    async def test_truncates_message(self, tmp_path):
        backend = MemoryNotificationBackend(memory_dir=tmp_path)
        long_msg = "x" * 1000
        await backend.send("Title", long_msg)

        with open(backend.notifications_file) as f:
            data = yaml.safe_load(f)
        assert len(data["notifications"][0]["message"]) <= 500

    @pytest.mark.asyncio
    async def test_keeps_last_100(self, tmp_path):
        backend = MemoryNotificationBackend(memory_dir=tmp_path)
        # Pre-populate with 99 notifications
        state_dir = tmp_path / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        existing = [{"title": f"old-{i}", "message": "msg"} for i in range(99)]
        with open(backend.notifications_file, "w") as f:
            yaml.dump({"notifications": existing}, f)

        # Add 2 more -> total 101, should keep 100
        await backend.send("New 1", "msg")
        await backend.send("New 2", "msg")

        with open(backend.notifications_file) as f:
            data = yaml.safe_load(f)
        assert len(data["notifications"]) == 100

    @pytest.mark.asyncio
    async def test_handles_write_error(self):
        backend = MemoryNotificationBackend(memory_dir=Path("/nonexistent/path/deep"))
        # Override notifications_file to a path that can't be created
        backend.notifications_file = Path("/proc/self/nonexistent/file.yaml")
        result = await backend.send("Title", "Message")
        assert result is False

    @pytest.mark.asyncio
    async def test_handles_corrupt_existing_file(self, tmp_path):
        backend = MemoryNotificationBackend(memory_dir=tmp_path)
        state_dir = tmp_path / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        with open(backend.notifications_file, "w") as f:
            f.write("not: valid: yaml: [[[")

        # Should handle gracefully
        result = await backend.send("Title", "Message")
        # yaml.safe_load on invalid YAML may return the string or raise
        # The code handles exceptions, so result may be True or False
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_records_skill_kwarg(self, tmp_path):
        backend = MemoryNotificationBackend(memory_dir=tmp_path)
        await backend.send("Title", "msg", skill="deploy_prod")

        with open(backend.notifications_file) as f:
            data = yaml.safe_load(f)
        assert data["notifications"][0]["skill"] == "deploy_prod"


# ==================== NotificationEngine ====================


class TestNotificationEngine:
    """Tests for NotificationEngine."""

    def test_init_creates_backends(self):
        engine = NotificationEngine()
        assert "slack" in engine.backends
        assert "desktop" in engine.backends
        assert "memory" in engine.backends

    def test_get_available_channels(self):
        engine = NotificationEngine()
        channels = engine.get_available_channels()
        assert "slack" in channels
        assert "desktop" in channels
        assert "memory" in channels

    @pytest.mark.asyncio
    async def test_notify_success(self, tmp_path):
        engine = NotificationEngine()
        # Replace memory backend with one using tmp_path
        engine.backends["memory"] = MemoryNotificationBackend(memory_dir=tmp_path)

        results = await engine.notify(
            job_name="test_job",
            skill="deploy",
            success=True,
            output="Deployed OK\nVersion 1.2",
            channels=["memory"],
        )
        assert results["memory"] is True

    @pytest.mark.asyncio
    async def test_notify_failure(self, tmp_path):
        engine = NotificationEngine()
        engine.backends["memory"] = MemoryNotificationBackend(memory_dir=tmp_path)

        results = await engine.notify(
            job_name="test_job",
            skill="deploy",
            success=False,
            error="Connection timeout",
            channels=["memory"],
        )
        assert results["memory"] is True

    @pytest.mark.asyncio
    async def test_notify_default_channel(self, tmp_path):
        engine = NotificationEngine()
        engine.backends["memory"] = MemoryNotificationBackend(memory_dir=tmp_path)

        # No channels specified -> defaults to ["memory"]
        results = await engine.notify(job_name="test", skill="test", success=True)
        assert results["memory"] is True

    @pytest.mark.asyncio
    async def test_notify_unknown_channel(self):
        engine = NotificationEngine()
        results = await engine.notify(
            job_name="test",
            skill="test",
            success=True,
            channels=["nonexistent"],
        )
        assert results["nonexistent"] is False

    @pytest.mark.asyncio
    async def test_notify_backend_exception(self):
        engine = NotificationEngine()
        bad_backend = AsyncMock()
        bad_backend.send.side_effect = RuntimeError("Backend broke")
        engine.backends["bad"] = bad_backend

        results = await engine.notify(
            job_name="test",
            skill="test",
            success=True,
            channels=["bad"],
        )
        assert results["bad"] is False

    @pytest.mark.asyncio
    async def test_notify_multiple_channels(self, tmp_path):
        engine = NotificationEngine()
        engine.backends["memory"] = MemoryNotificationBackend(memory_dir=tmp_path)
        mock_desktop = AsyncMock()
        mock_desktop.send.return_value = True
        engine.backends["desktop"] = mock_desktop

        results = await engine.notify(
            job_name="test",
            skill="test",
            success=True,
            channels=["memory", "desktop"],
        )
        assert results["memory"] is True
        assert results["desktop"] is True

    @pytest.mark.asyncio
    async def test_send_custom(self, tmp_path):
        engine = NotificationEngine()
        engine.backends["memory"] = MemoryNotificationBackend(memory_dir=tmp_path)

        results = await engine.send_custom(
            title="Custom Alert",
            message="Something happened",
            channels=["memory"],
            success=False,
        )
        assert results["memory"] is True

    @pytest.mark.asyncio
    async def test_send_custom_backend_exception(self):
        engine = NotificationEngine()
        bad_backend = AsyncMock()
        bad_backend.send.side_effect = RuntimeError("Failed")
        engine.backends["bad"] = bad_backend

        results = await engine.send_custom(
            title="Test", message="msg", channels=["bad"]
        )
        assert results["bad"] is False

    def test_get_recent_notifications(self, tmp_path):
        engine = NotificationEngine()
        mem_backend = MemoryNotificationBackend(memory_dir=tmp_path)
        engine.backends["memory"] = mem_backend

        # No file yet
        assert engine.get_recent_notifications() == []

    def test_get_recent_notifications_with_data(self, tmp_path):
        engine = NotificationEngine()
        mem_backend = MemoryNotificationBackend(memory_dir=tmp_path)
        engine.backends["memory"] = mem_backend

        state_dir = tmp_path / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        notifications = [{"title": f"n{i}"} for i in range(30)]
        with open(mem_backend.notifications_file, "w") as f:
            yaml.dump({"notifications": notifications}, f)

        result = engine.get_recent_notifications(limit=10)
        assert len(result) == 10

    def test_get_recent_notifications_no_memory_backend(self):
        engine = NotificationEngine()
        engine.backends["memory"] = MagicMock()  # Not a MemoryNotificationBackend
        result = engine.get_recent_notifications()
        assert result == []


# ==================== Global functions ====================


class TestGlobalFunctions:
    """Tests for module-level convenience functions."""

    def test_init_notification_engine(self):
        engine = init_notification_engine(config={"slack": {"default_channel": "C1"}})
        assert isinstance(engine, NotificationEngine)

    def test_get_notification_engine(self):
        init_notification_engine()
        engine = get_notification_engine()
        assert isinstance(engine, NotificationEngine)

    @pytest.mark.asyncio
    async def test_send_notification_with_engine(self, tmp_path):
        engine = init_notification_engine()
        engine.backends["memory"] = MemoryNotificationBackend(memory_dir=tmp_path)

        await send_notification(
            job_name="test",
            skill="deploy",
            success=True,
            channels=["memory"],
        )
        # Verify notification was logged
        mem = engine.backends["memory"]
        assert mem.notifications_file.exists()

    @pytest.mark.asyncio
    async def test_send_notification_no_engine(self):
        import tool_modules.aa_workflow.src.notification_engine as mod

        original = mod._notification_engine
        mod._notification_engine = None
        # Should not raise
        await send_notification(job_name="test", skill="test", success=True)
        mod._notification_engine = original
        assert True  # Reached without exception
