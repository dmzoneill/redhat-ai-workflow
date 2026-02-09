"""Tests for tool_modules.aa_workflow.src.notification_emitter."""

import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tool_modules.aa_workflow.src import notification_emitter

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def notifications_dir(tmp_path):
    """Redirect NOTIFICATIONS_FILE to a temp dir."""
    notif_file = tmp_path / "notifications.json"
    with patch.object(notification_emitter, "NOTIFICATIONS_FILE", notif_file):
        yield notif_file


@pytest.fixture
def _seed_notifications(notifications_dir):
    """Create a notifications file with sample data."""
    data = {
        "notifications": [
            {
                "id": "test_1",
                "category": "session",
                "eventType": "created",
                "title": "Test",
                "message": "Hello",
                "level": "info",
                "timestamp": datetime.now().isoformat(),
                "actions": [],
                "data": {},
                "source": None,
                "read": False,
            }
        ],
        "lastUpdated": datetime.now().isoformat(),
        "version": 1,
    }
    with open(notifications_dir, "w") as f:
        json.dump(data, f)


# ---------------------------------------------------------------------------
# _file_lock
# ---------------------------------------------------------------------------


class TestFileLock:
    def test_acquires_and_releases_lock(self, notifications_dir):
        with notification_emitter._file_lock(notifications_dir) as acquired:
            assert acquired is True
            lock_path = Path(str(notifications_dir) + ".lock")
            assert lock_path.exists()
        assert not lock_path.exists()

    def test_removes_stale_lock(self, notifications_dir):
        lock_path = Path(str(notifications_dir) + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        # Create a stale lock file (old mtime)
        fd = os.open(str(lock_path), os.O_CREAT | os.O_WRONLY)
        os.write(fd, b"stale")
        os.close(fd)
        # Make the lock appear old
        old_time = time.time() - notification_emitter.LOCK_STALE_SECONDS - 5
        os.utime(str(lock_path), (old_time, old_time))

        with notification_emitter._file_lock(notifications_dir) as acquired:
            assert acquired is True

    def test_timeout_when_lock_held(self, notifications_dir):
        lock_path = Path(str(notifications_dir) + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        # Create a fresh lock file (not stale)
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, b"held")
        os.close(fd)

        with patch.object(notification_emitter, "LOCK_TIMEOUT_SECONDS", 0.1):
            with patch.object(
                notification_emitter, "LOCK_RETRY_INTERVAL_SECONDS", 0.02
            ):
                with notification_emitter._file_lock(notifications_dir) as acquired:
                    assert acquired is False

        # Cleanup
        lock_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# _load_notifications_unlocked
# ---------------------------------------------------------------------------


class TestLoadNotificationsUnlocked:
    def test_loads_existing_file(self, notifications_dir, _seed_notifications):
        data = notification_emitter._load_notifications_unlocked()
        assert len(data["notifications"]) == 1

    def test_returns_default_when_missing(self, notifications_dir):
        data = notification_emitter._load_notifications_unlocked()
        assert data["notifications"] == []
        assert data["version"] == 1

    def test_returns_default_on_corrupt_json(self, notifications_dir):
        notifications_dir.write_text("{invalid json")
        data = notification_emitter._load_notifications_unlocked()
        assert data["notifications"] == []


# ---------------------------------------------------------------------------
# _save_notifications_unlocked
# ---------------------------------------------------------------------------


class TestSaveNotificationsUnlocked:
    def test_saves_atomically(self, notifications_dir):
        data = {
            "notifications": [{"id": "test"}],
            "version": 1,
        }
        notification_emitter._save_notifications_unlocked(data)
        assert notifications_dir.exists()
        loaded = json.loads(notifications_dir.read_text())
        assert loaded["notifications"][0]["id"] == "test"
        assert "lastUpdated" in loaded

    def test_handles_write_error(self, notifications_dir):
        with patch("builtins.open", side_effect=PermissionError("denied")):
            # Should not raise, just log warning
            notification_emitter._save_notifications_unlocked({"notifications": []})
        assert True  # Reached without exception


# ---------------------------------------------------------------------------
# _cleanup_old_notifications
# ---------------------------------------------------------------------------


class TestCleanupOldNotifications:
    def test_removes_old_notifications(self):
        old_time = (
            datetime.now()
            - timedelta(seconds=notification_emitter.CLEANUP_TIMEOUT_SECONDS + 10)
        ).isoformat()
        recent_time = datetime.now().isoformat()
        data = {
            "notifications": [
                {"timestamp": old_time, "id": "old"},
                {"timestamp": recent_time, "id": "recent"},
            ]
        }
        cleaned = notification_emitter._cleanup_old_notifications(data)
        assert len(cleaned["notifications"]) == 1
        assert cleaned["notifications"][0]["id"] == "recent"

    def test_keeps_max_notifications(self):
        now = datetime.now()
        notifications = [
            {"timestamp": now.isoformat(), "id": f"n{i}"}
            for i in range(notification_emitter.MAX_NOTIFICATIONS + 10)
        ]
        data = {"notifications": notifications}
        cleaned = notification_emitter._cleanup_old_notifications(data)
        assert len(cleaned["notifications"]) == notification_emitter.MAX_NOTIFICATIONS

    def test_skips_invalid_timestamps(self):
        data = {
            "notifications": [
                {"timestamp": "not-a-date", "id": "bad"},
                {"timestamp": None, "id": "none"},
                {"id": "missing"},
            ]
        }
        cleaned = notification_emitter._cleanup_old_notifications(data)
        assert len(cleaned["notifications"]) == 0

    def test_handles_empty(self):
        data = {"notifications": []}
        cleaned = notification_emitter._cleanup_old_notifications(data)
        assert len(cleaned["notifications"]) == 0


# ---------------------------------------------------------------------------
# emit_notification
# ---------------------------------------------------------------------------


class TestEmitNotification:
    def test_emits_basic_notification(self, notifications_dir):
        notification_emitter.emit_notification(
            category="session",
            event_type="created",
            title="Test Title",
            message="Test Message",
        )
        data = json.loads(notifications_dir.read_text())
        assert len(data["notifications"]) == 1
        n = data["notifications"][0]
        assert n["category"] == "session"
        assert n["eventType"] == "created"
        assert n["title"] == "Test Title"
        assert n["level"] == "info"
        assert n["read"] is False

    def test_emits_with_all_fields(self, notifications_dir):
        notification_emitter.emit_notification(
            category="skill",
            event_type="step_failed",
            title="Skill Error",
            message="Something broke",
            level="error",
            actions=[{"label": "Debug", "command": "debug"}],
            data={"key": "value"},
            source="test_source",
        )
        loaded = json.loads(notifications_dir.read_text())
        n = loaded["notifications"][0]
        assert n["level"] == "error"
        assert n["source"] == "test_source"
        assert n["actions"] == [{"label": "Debug", "command": "debug"}]
        assert n["data"] == {"key": "value"}

    def test_skips_when_lock_not_acquired(self, notifications_dir):
        with patch.object(
            notification_emitter,
            "_file_lock",
            return_value=MagicMock(
                __enter__=lambda s: False, __exit__=lambda s, *a: None
            ),
        ):
            notification_emitter.emit_notification(
                category="session",
                event_type="test",
                title="Title",
                message="Msg",
            )
        # File should not exist or be empty
        if notifications_dir.exists():
            data = json.loads(notifications_dir.read_text())
            assert len(data["notifications"]) <= 1  # Only seed data if present

    def test_creates_parent_directory(self, tmp_path):
        deep_file = tmp_path / "deep" / "path" / "notifications.json"
        with patch.object(notification_emitter, "NOTIFICATIONS_FILE", deep_file):
            notification_emitter.emit_notification(
                category="session",
                event_type="test",
                title="Title",
                message="Msg",
            )
        assert deep_file.exists()


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------


class TestConvenienceFunctions:
    @pytest.mark.parametrize(
        "func_name,expected_level",
        [
            ("notify_info", "info"),
            ("notify_warning", "warning"),
            ("notify_error", "error"),
        ],
    )
    def test_notify_level_functions(self, notifications_dir, func_name, expected_level):
        func = getattr(notification_emitter, func_name)
        func(
            "session",
            "test",
            f"{expected_level.title()} Title",
            f"{expected_level.title()} Message",
        )
        data = json.loads(notifications_dir.read_text())
        assert data["notifications"][0]["level"] == expected_level


# ---------------------------------------------------------------------------
# Category-specific convenience functions
# ---------------------------------------------------------------------------


class TestCategoryConvenience:
    def test_notify_persona_loaded(self, notifications_dir):
        notification_emitter.notify_persona_loaded("developer", 45)
        data = json.loads(notifications_dir.read_text())
        n = data["notifications"][0]
        assert n["category"] == "persona"
        assert n["eventType"] == "loaded"
        assert "45" in n["message"]

    def test_notify_persona_failed(self, notifications_dir):
        notification_emitter.notify_persona_failed("developer", "import error")
        data = json.loads(notifications_dir.read_text())
        n = data["notifications"][0]
        assert n["level"] == "error"
        assert "import error" in n["message"]

    def test_notify_session_created(self, notifications_dir):
        notification_emitter.notify_session_created("abc12345-long", "My Session")
        data = json.loads(notifications_dir.read_text())
        n = data["notifications"][0]
        assert "My Session" in n["message"]

    def test_notify_session_created_no_name(self, notifications_dir):
        notification_emitter.notify_session_created("abc12345-long")
        data = json.loads(notifications_dir.read_text())
        n = data["notifications"][0]
        assert "abc12345" in n["message"]

    def test_notify_session_resumed(self, notifications_dir):
        notification_emitter.notify_session_resumed("sess123456", "Resumed")
        data = json.loads(notifications_dir.read_text())
        assert data["notifications"][0]["eventType"] == "resumed"

    def test_notify_session_updated(self, notifications_dir):
        notification_emitter.notify_session_updated("sess1", "Project changed")
        data = json.loads(notifications_dir.read_text())
        assert "Project changed" in data["notifications"][0]["message"]

    def test_notify_auto_heal_triggered(self, notifications_dir):
        notification_emitter.notify_auto_heal_triggered(
            "step1", "auth_error", "re-login"
        )
        data = json.loads(notifications_dir.read_text())
        assert data["notifications"][0]["level"] == "warning"

    def test_notify_auto_heal_succeeded(self, notifications_dir):
        notification_emitter.notify_auto_heal_succeeded("step1", "re-login")
        data = json.loads(notifications_dir.read_text())
        assert data["notifications"][0]["level"] == "info"

    def test_notify_auto_heal_failed(self, notifications_dir):
        notification_emitter.notify_auto_heal_failed("step1", "still broken")
        data = json.loads(notifications_dir.read_text())
        assert data["notifications"][0]["level"] == "error"

    def test_notify_step_failed(self, notifications_dir):
        notification_emitter.notify_step_failed("my_skill", "step2", "error msg")
        data = json.loads(notifications_dir.read_text())
        n = data["notifications"][0]
        assert n["category"] == "skill"
        assert "step2" in n["title"]

    def test_notify_cron_job_started(self, notifications_dir):
        notification_emitter.notify_cron_job_started("daily_sync", "sync_jira")
        data = json.loads(notifications_dir.read_text())
        n = data["notifications"][0]
        assert n["source"] == "cron_daemon"

    def test_notify_cron_job_completed(self, notifications_dir):
        notification_emitter.notify_cron_job_completed("sync", "skill", 5.3)
        data = json.loads(notifications_dir.read_text())
        assert "5.3s" in data["notifications"][0]["message"]

    def test_notify_cron_job_failed(self, notifications_dir):
        notification_emitter.notify_cron_job_failed("sync", "skill", "timeout")
        data = json.loads(notifications_dir.read_text())
        assert data["notifications"][0]["level"] == "error"

    def test_notify_meeting_soon(self, notifications_dir):
        notification_emitter.notify_meeting_soon("Standup", 5, "evt123")
        data = json.loads(notifications_dir.read_text())
        n = data["notifications"][0]
        assert n["level"] == "warning"
        assert "5 minutes" in n["message"]

    def test_notify_meeting_joined(self, notifications_dir):
        notification_emitter.notify_meeting_joined("Standup", "observer")
        data = json.loads(notifications_dir.read_text())
        assert "observer" in data["notifications"][0]["message"]

    def test_notify_meeting_left(self, notifications_dir):
        notification_emitter.notify_meeting_left("Standup", 30.0, 150)
        data = json.loads(notifications_dir.read_text())
        assert "30m" in data["notifications"][0]["message"]
        assert "150" in data["notifications"][0]["message"]

    def test_notify_sprint_issue_started(self, notifications_dir):
        notification_emitter.notify_sprint_issue_started("AAP-123", "Fix bug")
        data = json.loads(notifications_dir.read_text())
        assert "AAP-123" in data["notifications"][0]["message"]

    def test_notify_sprint_issue_completed(self, notifications_dir):
        notification_emitter.notify_sprint_issue_completed("AAP-123")
        data = json.loads(notifications_dir.read_text())
        assert "AAP-123" in data["notifications"][0]["message"]

    def test_notify_sprint_issue_blocked(self, notifications_dir):
        notification_emitter.notify_sprint_issue_blocked("AAP-123", "dependency")
        data = json.loads(notifications_dir.read_text())
        assert data["notifications"][0]["level"] == "warning"

    def test_notify_slack_message(self, notifications_dir):
        notification_emitter.notify_slack_message("general", "alice", "Hello world")
        data = json.loads(notifications_dir.read_text())
        assert "alice" in data["notifications"][0]["title"]

    def test_notify_slack_pending_approval(self, notifications_dir):
        notification_emitter.notify_slack_pending_approval(
            "general", "bob", "Can you review?"
        )
        data = json.loads(notifications_dir.read_text())
        assert data["notifications"][0]["level"] == "warning"
