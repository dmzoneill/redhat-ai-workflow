"""Tests for tool_modules/aa_workflow/src/sprint_bot.py."""

import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tool_modules.aa_workflow.src.sprint_bot import (
    SprintBotConfig,
    WorkingHours,
    acquire_lock,
    approve_issue,
    disable_sprint_bot,
    enable_sprint_bot,
    get_sprint_status,
    is_within_working_hours,
    process_next_issue,
    refresh_sprint_state,
    release_lock,
    run_sprint_bot,
    skip_issue,
)
from tool_modules.aa_workflow.src.sprint_history import (
    SprintIssue,
    SprintState,
    TimelineEvent,
)
from tool_modules.aa_workflow.src.sprint_tools import ACTIONABLE_STATUSES, is_actionable

# Shared module path prefix for patching
MOD = "tool_modules.aa_workflow.src.sprint_bot"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _issue(
    key="AAP-1", status="New", approval="pending", summary="Test issue", points=3
):
    return SprintIssue(
        key=key,
        summary=summary,
        story_points=points,
        jira_status=status,
        approval_status=approval,
    )


def _state(issues=None, bot_enabled=False, processing_issue=None, last_updated=""):
    return SprintState(
        issues=issues or [],
        bot_enabled=bot_enabled,
        processing_issue=processing_issue,
        last_updated=last_updated or datetime.now().isoformat(),
    )


# ---------------------------------------------------------------------------
# WorkingHours dataclass
# ---------------------------------------------------------------------------


class TestWorkingHours:
    def test_defaults(self):
        wh = WorkingHours()
        assert wh.start_hour == 9
        assert wh.start_minute == 0
        assert wh.end_hour == 17
        assert wh.end_minute == 0
        assert wh.weekdays_only is True
        assert wh.timezone == "Europe/Dublin"

    def test_custom_values(self):
        wh = WorkingHours(
            start_hour=8, end_hour=18, weekdays_only=False, timezone="UTC"
        )
        assert wh.start_hour == 8
        assert wh.end_hour == 18
        assert wh.weekdays_only is False


# ---------------------------------------------------------------------------
# SprintBotConfig dataclass
# ---------------------------------------------------------------------------


class TestSprintBotConfig:
    def test_defaults(self):
        config = SprintBotConfig(working_hours=WorkingHours())
        assert config.jira_project == "AAP"
        assert config.jira_component is None
        assert config.auto_approve is False
        assert config.max_concurrent_chats == 1
        assert config.skip_blocked_after_minutes == 30

    def test_custom_values(self):
        config = SprintBotConfig(
            working_hours=WorkingHours(),
            jira_project="PROJ",
            jira_component="backend",
            auto_approve=True,
        )
        assert config.jira_project == "PROJ"
        assert config.jira_component == "backend"
        assert config.auto_approve is True


# ---------------------------------------------------------------------------
# is_within_working_hours
# ---------------------------------------------------------------------------


class TestIsWithinWorkingHours:
    """Test is_within_working_hours.

    The function imports ZoneInfo inside the function body. We mock
    zoneinfo.ZoneInfo to return a fixed-offset tz that yields a
    controlled datetime.now(tz).
    """

    def _mock_working_hours_check(self, config, fake_now):
        """Helper: patch datetime.now(tz) to return fake_now."""
        from zoneinfo import ZoneInfo

        real_tz = ZoneInfo(config.timezone)

        with patch(f"zoneinfo.ZoneInfo", return_value=real_tz):
            with patch(f"{MOD}.datetime") as mock_dt:
                # Make datetime.now(tz) return our fake
                mock_dt.now.return_value = fake_now
                # But time() constructor must still work
                mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                return is_within_working_hours(config)

    def test_within_hours_weekday(self):
        config = WorkingHours(start_hour=9, end_hour=17, weekdays_only=True)
        fake_now = datetime(2026, 2, 4, 12, 0, 0)  # Wednesday noon
        assert self._mock_working_hours_check(config, fake_now) is True

    def test_outside_hours_too_early(self):
        config = WorkingHours(start_hour=9, end_hour=17)
        fake_now = datetime(2026, 2, 4, 7, 0, 0)  # Wednesday 7am
        assert self._mock_working_hours_check(config, fake_now) is False

    def test_outside_hours_too_late(self):
        config = WorkingHours(start_hour=9, end_hour=17)
        fake_now = datetime(2026, 2, 4, 18, 0, 0)  # Wednesday 6pm
        assert self._mock_working_hours_check(config, fake_now) is False

    def test_weekend_rejected(self):
        config = WorkingHours(start_hour=9, end_hour=17, weekdays_only=True)
        fake_now = datetime(2026, 2, 7, 12, 0, 0)  # Saturday
        assert self._mock_working_hours_check(config, fake_now) is False

    def test_weekend_allowed_if_not_weekdays_only(self):
        config = WorkingHours(start_hour=9, end_hour=17, weekdays_only=False)
        fake_now = datetime(2026, 2, 7, 12, 0, 0)  # Saturday
        assert self._mock_working_hours_check(config, fake_now) is True

    def test_boundary_start(self):
        config = WorkingHours(start_hour=9, end_hour=17)
        fake_now = datetime(2026, 2, 4, 9, 0, 0)  # Exactly 9am Wed
        assert self._mock_working_hours_check(config, fake_now) is True

    def test_boundary_end(self):
        config = WorkingHours(start_hour=9, end_hour=17)
        fake_now = datetime(2026, 2, 4, 17, 0, 0)  # Exactly 5pm Wed
        assert self._mock_working_hours_check(config, fake_now) is True


# ---------------------------------------------------------------------------
# acquire_lock / release_lock
# ---------------------------------------------------------------------------


class TestLocking:
    def test_acquire_lock_no_existing(self, tmp_path):
        lock = tmp_path / "bot.lock"
        with patch(f"{MOD}.LOCK_FILE", lock):
            assert acquire_lock() is True
            assert lock.exists()
            data = json.loads(lock.read_text())
            assert "pid" in data
            assert "started" in data

    def test_acquire_lock_recent_exists(self, tmp_path):
        lock = tmp_path / "bot.lock"
        lock.write_text('{"pid": 1234}')
        with patch(f"{MOD}.LOCK_FILE", lock):
            assert acquire_lock() is False

    def test_acquire_lock_stale(self, tmp_path):
        lock = tmp_path / "bot.lock"
        lock.write_text('{"pid": 1234}')
        # Make the file appear stale (>1 hour old)
        import os

        old_time = datetime.now().timestamp() - 7200  # 2 hours ago
        os.utime(lock, (old_time, old_time))
        with patch(f"{MOD}.LOCK_FILE", lock):
            assert acquire_lock() is True

    def test_release_lock_exists(self, tmp_path):
        lock = tmp_path / "bot.lock"
        lock.write_text('{"pid": 1234}')
        with patch(f"{MOD}.LOCK_FILE", lock):
            release_lock()
            assert not lock.exists()

    def test_release_lock_not_exists(self, tmp_path):
        lock = tmp_path / "bot.lock"
        with patch(f"{MOD}.LOCK_FILE", lock):
            release_lock()  # Test verifies no exception is raised
            assert not lock.exists()


# ---------------------------------------------------------------------------
# is_actionable
# ---------------------------------------------------------------------------


class TestIsActionable:
    @pytest.mark.parametrize(
        "status", ["New", "Refinement", "To Do", "Open", "Backlog"]
    )
    def test_actionable_statuses(self, status):
        issue = _issue(status=status)
        assert is_actionable(issue) is True

    @pytest.mark.parametrize(
        "status", ["In Review", "Done", "Release Pending", "Closed"]
    )
    def test_non_actionable_statuses(self, status):
        issue = _issue(status=status)
        assert is_actionable(issue) is False

    def test_none_status(self):
        issue = _issue(status=None)
        # jira_status=None -> ""  -> not actionable
        issue.jira_status = None
        assert is_actionable(issue) is False

    def test_empty_status(self):
        issue = _issue(status="")
        assert is_actionable(issue) is False

    def test_case_insensitive(self):
        issue = _issue(status="NEW")
        assert is_actionable(issue) is True

    def test_actionable_statuses_constant(self):
        assert "new" in ACTIONABLE_STATUSES
        assert "refinement" in ACTIONABLE_STATUSES
        assert "backlog" in ACTIONABLE_STATUSES


# ---------------------------------------------------------------------------
# enable_sprint_bot / disable_sprint_bot
# ---------------------------------------------------------------------------


class TestEnableDisable:
    def test_enable(self):
        state = _state(bot_enabled=False)
        with (
            patch(f"{MOD}.load_sprint_state", return_value=state),
            patch(f"{MOD}.save_sprint_state") as mock_save,
        ):
            result = enable_sprint_bot()
        assert result["success"] is True
        assert result["bot_enabled"] is True
        mock_save.assert_called_once()
        assert state.bot_enabled is True

    def test_disable(self):
        state = _state(bot_enabled=True, processing_issue="AAP-1")
        with (
            patch(f"{MOD}.load_sprint_state", return_value=state),
            patch(f"{MOD}.save_sprint_state") as mock_save,
            patch(f"{MOD}.release_lock") as mock_release,
        ):
            result = disable_sprint_bot()
        assert result["success"] is True
        assert result["bot_enabled"] is False
        assert state.processing_issue is None
        mock_save.assert_called_once()
        mock_release.assert_called_once()


# ---------------------------------------------------------------------------
# approve_issue
# ---------------------------------------------------------------------------


class TestApproveIssue:
    def test_approve_actionable(self):
        state = _state(issues=[_issue(key="AAP-1", status="New", approval="pending")])
        with (
            patch(f"{MOD}.load_sprint_state", return_value=state),
            patch(f"{MOD}.update_issue_status", return_value=True) as mock_update,
            patch(f"{MOD}.add_timeline_event"),
        ):
            result = approve_issue("AAP-1")
        assert result["success"] is True
        mock_update.assert_called_once_with("AAP-1", "approved")

    def test_approve_not_found(self):
        state = _state(issues=[])
        with patch(f"{MOD}.load_sprint_state", return_value=state):
            result = approve_issue("AAP-999")
        assert result["success"] is False
        assert "not found" in result["message"]

    def test_approve_not_actionable(self):
        state = _state(issues=[_issue(key="AAP-1", status="Done")])
        with patch(f"{MOD}.load_sprint_state", return_value=state):
            result = approve_issue("AAP-1")
        assert result["success"] is False
        assert "not actionable" in result["message"]

    def test_approve_update_fails(self):
        state = _state(issues=[_issue(key="AAP-1", status="New")])
        with (
            patch(f"{MOD}.load_sprint_state", return_value=state),
            patch(f"{MOD}.update_issue_status", return_value=False),
            patch(f"{MOD}.add_timeline_event"),
        ):
            result = approve_issue("AAP-1")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# skip_issue
# ---------------------------------------------------------------------------


class TestSkipIssue:
    def test_skip_with_reason(self):
        with (
            patch(f"{MOD}.update_issue_status", return_value=True) as mock_update,
            patch(f"{MOD}.add_timeline_event"),
        ):
            result = skip_issue("AAP-1", "Blocked on dependency")
        assert result["success"] is True
        mock_update.assert_called_once_with(
            "AAP-1", "blocked", waiting_reason="Blocked on dependency"
        )

    def test_skip_default_reason(self):
        with (
            patch(f"{MOD}.update_issue_status", return_value=True) as mock_update,
            patch(f"{MOD}.add_timeline_event"),
        ):
            result = skip_issue("AAP-1")
        mock_update.assert_called_once_with(
            "AAP-1", "blocked", waiting_reason="Manually skipped"
        )
        assert result["success"] is True

    def test_skip_not_found(self):
        with (
            patch(f"{MOD}.update_issue_status", return_value=False),
            patch(f"{MOD}.add_timeline_event"),
        ):
            result = skip_issue("AAP-999")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# get_sprint_status
# ---------------------------------------------------------------------------


class TestGetSprintStatus:
    def test_basic_status(self):
        state = _state(
            issues=[
                _issue(key="AAP-1", approval="pending"),
                _issue(key="AAP-2", approval="approved"),
                _issue(key="AAP-3", approval="approved"),
            ],
            bot_enabled=True,
            processing_issue="AAP-2",
        )
        state.current_sprint = {"name": "Sprint 42"}
        with patch(f"{MOD}.load_sprint_state", return_value=state):
            status = get_sprint_status()

        assert status["bot_enabled"] is True
        assert status["total_issues"] == 3
        assert status["processing_issue"] == "AAP-2"
        assert status["status_counts"]["pending"] == 1
        assert status["status_counts"]["approved"] == 2
        assert status["current_sprint"] == {"name": "Sprint 42"}

    def test_empty_sprint(self):
        state = _state(issues=[], bot_enabled=False)
        with patch(f"{MOD}.load_sprint_state", return_value=state):
            status = get_sprint_status()
        assert status["total_issues"] == 0
        assert status["status_counts"] == {}


# ---------------------------------------------------------------------------
# refresh_sprint_state
# ---------------------------------------------------------------------------


class TestRefreshSprintState:
    def test_no_jira_issues(self):
        state = _state(issues=[_issue(key="AAP-OLD")])
        config = SprintBotConfig(working_hours=WorkingHours())

        with (
            patch(f"{MOD}.load_sprint_state", return_value=state),
            patch(f"{MOD}.load_sprint_issues_from_jira_sync", return_value=[]),
        ):
            result = refresh_sprint_state(config)

        # Should return existing state unchanged
        assert result is state

    def test_merges_existing_state(self):
        existing_issue = _issue(key="AAP-1", status="New", approval="approved")
        existing_issue.chat_id = "chat-123"
        existing_issue.timeline = [
            TimelineEvent(
                timestamp="2026-01-01", action="approved", description="Was approved"
            )
        ]
        state = _state(issues=[existing_issue])

        jira_issues = [
            {
                "key": "AAP-1",
                "summary": "Updated summary",
                "storyPoints": 5,
                "assignee": "testuser",
            }
        ]

        config = SprintBotConfig(working_hours=WorkingHours())

        with (
            patch(f"{MOD}.load_sprint_state", return_value=state),
            patch(f"{MOD}.load_sprint_issues_from_jira_sync", return_value=jira_issues),
            patch(f"{MOD}.prioritize_issues", return_value=jira_issues),
            patch(f"{MOD}.to_sprint_issue_format", return_value=jira_issues),
            patch(f"{MOD}.save_sprint_state"),
            patch("server.config.load_config", side_effect=ImportError),
        ):
            result = refresh_sprint_state(config)

        assert len(result.issues) == 1
        merged = result.issues[0]
        assert merged.key == "AAP-1"
        assert merged.summary == "Updated summary"
        assert merged.approval_status == "approved"  # Preserved
        assert merged.chat_id == "chat-123"  # Preserved
        assert len(merged.timeline) == 1  # Preserved

    def test_new_issues_get_pending_status(self):
        state = _state(issues=[])
        jira_issues = [{"key": "AAP-NEW", "summary": "Brand new"}]
        config = SprintBotConfig(working_hours=WorkingHours())

        with (
            patch(f"{MOD}.load_sprint_state", return_value=state),
            patch(f"{MOD}.load_sprint_issues_from_jira_sync", return_value=jira_issues),
            patch(f"{MOD}.prioritize_issues", return_value=jira_issues),
            patch(f"{MOD}.to_sprint_issue_format", return_value=jira_issues),
            patch(f"{MOD}.save_sprint_state"),
            patch("server.config.load_config", side_effect=ImportError),
        ):
            result = refresh_sprint_state(config)

        assert len(result.issues) == 1
        assert result.issues[0].approval_status == "pending"
        assert result.issues[0].chat_id is None

    def test_filter_by_assignee(self):
        state = _state(issues=[])
        jira_issues = [
            {"key": "AAP-1", "summary": "Mine", "assignee": "testuser"},
            {"key": "AAP-2", "summary": "Not mine", "assignee": "other"},
        ]
        config = SprintBotConfig(working_hours=WorkingHours())
        mock_config = {"user": {"jira_username": "testuser", "full_name": ""}}

        with (
            patch(f"{MOD}.load_sprint_state", return_value=state),
            patch(f"{MOD}.load_sprint_issues_from_jira_sync", return_value=jira_issues),
            patch(f"{MOD}.prioritize_issues", return_value=[jira_issues[0]]),
            patch(f"{MOD}.to_sprint_issue_format", return_value=[jira_issues[0]]),
            patch(f"{MOD}.save_sprint_state"),
            patch("server.config.load_config", return_value=mock_config),
        ):
            result = refresh_sprint_state(config)

        assert len(result.issues) == 1
        assert result.issues[0].key == "AAP-1"

    def test_empty_after_assignee_filter(self):
        state = _state(issues=[_issue(key="AAP-OLD")])
        jira_issues = [
            {"key": "AAP-1", "summary": "Not mine", "assignee": "other"},
        ]
        config = SprintBotConfig(working_hours=WorkingHours())
        mock_config = {"user": {"jira_username": "testuser", "full_name": ""}}

        with (
            patch(f"{MOD}.load_sprint_state", return_value=state),
            patch(f"{MOD}.load_sprint_issues_from_jira_sync", return_value=jira_issues),
            patch(f"{MOD}.save_sprint_state") as mock_save,
            patch("server.config.load_config", return_value=mock_config),
        ):
            result = refresh_sprint_state(config)

        assert result.issues == []
        mock_save.assert_called_once()


# ---------------------------------------------------------------------------
# process_next_issue
# ---------------------------------------------------------------------------


class TestProcessNextIssue:
    def test_no_issues(self):
        state = _state(issues=[])
        config = SprintBotConfig(working_hours=WorkingHours())
        with patch(f"{MOD}.get_next_issue_to_process", return_value=None):
            assert process_next_issue(state, config) is False

    def test_processes_issue(self):
        issue = _issue(key="AAP-1", approval="approved")
        state = _state(issues=[issue])
        config = SprintBotConfig(working_hours=WorkingHours())

        with (
            patch(f"{MOD}.get_next_issue_to_process", return_value=issue),
            patch(f"{MOD}.update_issue_status"),
            patch(f"{MOD}.save_sprint_state"),
            patch(f"{MOD}.add_timeline_event"),
            patch(
                f"{MOD}.launch_issue_chat",
                new_callable=AsyncMock,
                return_value="chat-999",
            ),
        ):
            result = process_next_issue(state, config)

        assert result is True
        assert state.processing_issue == "AAP-1"

    def test_processes_issue_no_chat(self):
        issue = _issue(key="AAP-1", approval="approved")
        state = _state(issues=[issue])
        config = SprintBotConfig(working_hours=WorkingHours())

        with (
            patch(f"{MOD}.get_next_issue_to_process", return_value=issue),
            patch(f"{MOD}.update_issue_status"),
            patch(f"{MOD}.save_sprint_state"),
            patch(f"{MOD}.add_timeline_event"),
            patch(
                f"{MOD}.launch_issue_chat", new_callable=AsyncMock, return_value=None
            ),
        ):
            result = process_next_issue(state, config)

        assert result is True


# ---------------------------------------------------------------------------
# run_sprint_bot
# ---------------------------------------------------------------------------


class TestRunSprintBot:
    def test_outside_working_hours(self):
        with patch(f"{MOD}.is_within_working_hours", return_value=False):
            result = run_sprint_bot()
        assert result["success"] is False
        assert "Outside working hours" in result["message"]

    def test_lock_not_acquired(self):
        with (
            patch(f"{MOD}.is_within_working_hours", return_value=True),
            patch(f"{MOD}.acquire_lock", return_value=False),
        ):
            result = run_sprint_bot()
        assert result["success"] is False
        assert "Another instance" in result["message"]

    def test_bot_disabled(self):
        state = _state(bot_enabled=False)
        with (
            patch(f"{MOD}.is_within_working_hours", return_value=True),
            patch(f"{MOD}.acquire_lock", return_value=True),
            patch(f"{MOD}.release_lock"),
            patch(f"{MOD}.load_sprint_state", return_value=state),
        ):
            result = run_sprint_bot()
        assert result["success"] is False
        assert "Bot is disabled" in result["message"]

    def test_processes_issue_success(self):
        state = _state(
            bot_enabled=True,
            last_updated=datetime.now().isoformat(),
            processing_issue="AAP-1",
        )
        with (
            patch(f"{MOD}.is_within_working_hours", return_value=True),
            patch(f"{MOD}.acquire_lock", return_value=True),
            patch(f"{MOD}.release_lock"),
            patch(f"{MOD}.load_sprint_state", return_value=state),
            patch(f"{MOD}.process_next_issue", return_value=True),
        ):
            result = run_sprint_bot()
        assert result["success"] is True
        assert result["issues_processed"] == 1

    def test_no_issues_to_process(self):
        state = _state(bot_enabled=True, last_updated=datetime.now().isoformat())
        with (
            patch(f"{MOD}.is_within_working_hours", return_value=True),
            patch(f"{MOD}.acquire_lock", return_value=True),
            patch(f"{MOD}.release_lock"),
            patch(f"{MOD}.load_sprint_state", return_value=state),
            patch(f"{MOD}.process_next_issue", return_value=False),
        ):
            result = run_sprint_bot()
        assert result["success"] is True
        assert result["issues_processed"] == 0
        assert "No issues" in result["message"]

    def test_stale_state_triggers_refresh(self):
        state = _state(bot_enabled=True, last_updated="2020-01-01T00:00:00")
        with (
            patch(f"{MOD}.is_within_working_hours", return_value=True),
            patch(f"{MOD}.acquire_lock", return_value=True),
            patch(f"{MOD}.release_lock"),
            patch(f"{MOD}.load_sprint_state", return_value=state),
            patch(f"{MOD}.refresh_sprint_state", return_value=state) as mock_refresh,
            patch(f"{MOD}.process_next_issue", return_value=False),
        ):
            result = run_sprint_bot()
        mock_refresh.assert_called_once()
        assert result["success"] is True

    def test_error_handling(self):
        _state(bot_enabled=True, last_updated=datetime.now().isoformat())
        with (
            patch(f"{MOD}.is_within_working_hours", return_value=True),
            patch(f"{MOD}.acquire_lock", return_value=True),
            patch(f"{MOD}.release_lock") as mock_release,
            patch(f"{MOD}.load_sprint_state", side_effect=RuntimeError("DB down")),
        ):
            result = run_sprint_bot()
        assert result["success"] is False
        assert "DB down" in result["message"]
        mock_release.assert_called_once()  # lock always released

    def test_default_config(self):
        with (patch(f"{MOD}.is_within_working_hours", return_value=False),):
            result = run_sprint_bot(config=None)
        assert "Outside working hours" in result["message"]

    def test_lock_released_on_success(self):
        state = _state(bot_enabled=True, last_updated=datetime.now().isoformat())
        with (
            patch(f"{MOD}.is_within_working_hours", return_value=True),
            patch(f"{MOD}.acquire_lock", return_value=True),
            patch(f"{MOD}.release_lock") as mock_release,
            patch(f"{MOD}.load_sprint_state", return_value=state),
            patch(f"{MOD}.process_next_issue", return_value=False),
        ):
            result = run_sprint_bot()
        mock_release.assert_called_once()
        assert result["success"] is True


# ---------------------------------------------------------------------------
# fetch_sprint_issues (async)
# ---------------------------------------------------------------------------


class TestFetchSprintIssues:
    def test_import_error_returns_empty(self):
        """fetch_sprint_issues returns [] when jira tools not importable."""
        import asyncio
        import builtins

        from tool_modules.aa_workflow.src.sprint_bot import fetch_sprint_issues

        config = SprintBotConfig(working_hours=WorkingHours())

        real_import = builtins.__import__

        def blocked_import(name, *args, **kwargs):
            if "tools_basic" in name:
                raise ImportError("blocked in test")
            return real_import(name, *args, **kwargs)

        async def _run():
            with patch("builtins.__import__", side_effect=blocked_import):
                return await fetch_sprint_issues(config)

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(_run())
        finally:
            loop.close()
        assert result == []

    def test_sprint_result_with_issues_list(self):
        """When jira returns list directly."""
        import asyncio

        from tool_modules.aa_workflow.src.sprint_bot import fetch_sprint_issues

        config = SprintBotConfig(working_hours=WorkingHours())

        mock_sprint = AsyncMock(return_value={"id": 42})
        mock_issues = AsyncMock(return_value=[{"key": "AAP-1"}])

        async def _run():
            with patch.dict(
                "sys.modules",
                {
                    "tool_modules.aa_jira.src.tools_basic": MagicMock(
                        jira_get_active_sprint=mock_sprint,
                        jira_get_sprint_issues=mock_issues,
                    )
                },
            ):
                return await fetch_sprint_issues(config)

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(_run())
        finally:
            loop.close()
        assert result == [{"key": "AAP-1"}]

    def test_sprint_result_with_issues_dict(self):
        """When jira returns dict with 'issues' key."""
        import asyncio

        from tool_modules.aa_workflow.src.sprint_bot import fetch_sprint_issues

        config = SprintBotConfig(working_hours=WorkingHours())

        mock_sprint = AsyncMock(return_value={"id": 42})
        mock_issues = AsyncMock(return_value={"issues": [{"key": "AAP-1"}]})

        async def _run():
            with patch.dict(
                "sys.modules",
                {
                    "tool_modules.aa_jira.src.tools_basic": MagicMock(
                        jira_get_active_sprint=mock_sprint,
                        jira_get_sprint_issues=mock_issues,
                    )
                },
            ):
                return await fetch_sprint_issues(config)

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(_run())
        finally:
            loop.close()
        assert result == [{"key": "AAP-1"}]

    def test_no_active_sprint(self):
        """When no active sprint found."""
        import asyncio

        from tool_modules.aa_workflow.src.sprint_bot import fetch_sprint_issues

        config = SprintBotConfig(working_hours=WorkingHours())

        mock_sprint = AsyncMock(return_value={"name": "Sprint"})  # No 'id'

        async def _run():
            with patch.dict(
                "sys.modules",
                {
                    "tool_modules.aa_jira.src.tools_basic": MagicMock(
                        jira_get_active_sprint=mock_sprint,
                    )
                },
            ):
                return await fetch_sprint_issues(config)

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(_run())
        finally:
            loop.close()
        assert result == []

    def test_error_returns_empty(self):
        """General exception returns []."""
        import asyncio

        from tool_modules.aa_workflow.src.sprint_bot import fetch_sprint_issues

        config = SprintBotConfig(working_hours=WorkingHours())

        mock_sprint = AsyncMock(side_effect=RuntimeError("network down"))

        async def _run():
            with patch.dict(
                "sys.modules",
                {
                    "tool_modules.aa_jira.src.tools_basic": MagicMock(
                        jira_get_active_sprint=mock_sprint,
                    )
                },
            ):
                return await fetch_sprint_issues(config)

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(_run())
        finally:
            loop.close()
        assert result == []


# ---------------------------------------------------------------------------
# load_sprint_issues_from_jira_sync
# ---------------------------------------------------------------------------


class TestLoadSprintIssuesSync:
    def test_calls_fetch(self):
        from tool_modules.aa_workflow.src.sprint_bot import (
            load_sprint_issues_from_jira_sync,
        )

        config = SprintBotConfig(working_hours=WorkingHours())
        with patch(
            f"{MOD}.fetch_sprint_issues",
            new_callable=AsyncMock,
            return_value=[{"key": "AAP-1"}],
        ):
            result = load_sprint_issues_from_jira_sync(config)
        assert result == [{"key": "AAP-1"}]


# ---------------------------------------------------------------------------
# launch_issue_chat (async)
# ---------------------------------------------------------------------------


class TestLaunchIssueChat:
    def test_dbus_not_available(self):
        """launch_issue_chat returns None when dbus is unavailable."""
        import asyncio

        from tool_modules.aa_workflow.src.sprint_bot import launch_issue_chat

        issue = _issue(key="AAP-1")

        async def _run():
            return await launch_issue_chat(issue)

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(_run())
        finally:
            loop.close()
        assert result is None
