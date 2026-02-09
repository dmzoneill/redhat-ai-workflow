"""Tests for tool_modules/aa_workflow/src/working_hours.py"""

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

# Ensure the module is importable
_wh_path = Path(__file__).parent.parent / "tool_modules" / "aa_workflow" / "src"
if str(_wh_path) not in sys.path:
    sys.path.insert(0, str(_wh_path))

from working_hours import (
    WorkingHoursEnforcer,
    get_working_hours_enforcer,
    reset_enforcer,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dt(year=2025, month=1, day=6, hour=10, minute=0, tz="America/New_York"):
    """Create a timezone-aware datetime. 2025-01-06 is a Monday."""
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(tz))


# ---------------------------------------------------------------------------
# Default config
# ---------------------------------------------------------------------------


class TestDefaultConfig:
    def test_default_start_hour(self):
        e = WorkingHoursEnforcer()
        assert e.config["start_hour"] == 9

    def test_default_end_hour(self):
        e = WorkingHoursEnforcer()
        assert e.config["end_hour"] == 17

    def test_default_days(self):
        e = WorkingHoursEnforcer()
        assert "monday" in e.config["days"]
        assert "saturday" not in e.config["days"]

    def test_default_timezone(self):
        e = WorkingHoursEnforcer()
        assert e.config["timezone"] == "America/New_York"

    def test_custom_config_merges(self):
        e = WorkingHoursEnforcer({"start_hour": 8, "end_hour": 18})
        assert e.config["start_hour"] == 8
        assert e.config["end_hour"] == 18
        # Defaults still present
        assert e.config["timezone"] == "America/New_York"


# ---------------------------------------------------------------------------
# enabled property
# ---------------------------------------------------------------------------


class TestEnabled:
    def test_enabled_by_default(self):
        e = WorkingHoursEnforcer()
        assert e.enabled is True

    def test_disabled_via_config(self):
        e = WorkingHoursEnforcer({"enabled": False})
        assert e.enabled is False

    def test_enabled_missing_key(self):
        e = WorkingHoursEnforcer()
        e.config.pop("enabled", None)
        assert e.enabled is True  # default


# ---------------------------------------------------------------------------
# is_working_hours
# ---------------------------------------------------------------------------


class TestIsWorkingHours:
    def test_during_working_hours(self):
        e = WorkingHoursEnforcer()
        # Monday 10:00 AM
        with patch.object(e, "_now", return_value=_make_dt(hour=10)):
            assert e.is_working_hours() is True

    def test_before_start(self):
        e = WorkingHoursEnforcer()
        # Monday 8:00 AM (before 9)
        with patch.object(e, "_now", return_value=_make_dt(hour=8)):
            assert e.is_working_hours() is False

    def test_at_start(self):
        e = WorkingHoursEnforcer()
        # Monday 9:00 AM exactly
        with patch.object(e, "_now", return_value=_make_dt(hour=9)):
            assert e.is_working_hours() is True

    def test_at_end(self):
        e = WorkingHoursEnforcer()
        # Monday 17:00 exactly (end is exclusive)
        with patch.object(e, "_now", return_value=_make_dt(hour=17)):
            assert e.is_working_hours() is False

    def test_after_end(self):
        e = WorkingHoursEnforcer()
        with patch.object(e, "_now", return_value=_make_dt(hour=20)):
            assert e.is_working_hours() is False

    def test_weekend_saturday(self):
        e = WorkingHoursEnforcer()
        # 2025-01-11 is a Saturday
        with patch.object(e, "_now", return_value=_make_dt(day=11, hour=10)):
            assert e.is_working_hours() is False

    def test_weekend_sunday(self):
        e = WorkingHoursEnforcer()
        # 2025-01-12 is a Sunday
        with patch.object(e, "_now", return_value=_make_dt(day=12, hour=10)):
            assert e.is_working_hours() is False

    def test_disabled_always_true(self):
        e = WorkingHoursEnforcer({"enabled": False})
        # Saturday at midnight
        with patch.object(e, "_now", return_value=_make_dt(day=11, hour=0)):
            assert e.is_working_hours() is True

    def test_custom_hours(self):
        e = WorkingHoursEnforcer({"start_hour": 7, "end_hour": 15})
        with patch.object(e, "_now", return_value=_make_dt(hour=7)):
            assert e.is_working_hours() is True
        with patch.object(e, "_now", return_value=_make_dt(hour=15)):
            assert e.is_working_hours() is False

    def test_custom_days_includes_saturday(self):
        e = WorkingHoursEnforcer({"days": ["saturday"]})
        # 2025-01-11 is Saturday
        with patch.object(e, "_now", return_value=_make_dt(day=11, hour=10)):
            assert e.is_working_hours() is True
        # 2025-01-06 is Monday
        with patch.object(e, "_now", return_value=_make_dt(day=6, hour=10)):
            assert e.is_working_hours() is False


# ---------------------------------------------------------------------------
# get_next_working_time
# ---------------------------------------------------------------------------


class TestGetNextWorkingTime:
    def test_weekend_gets_monday(self):
        e = WorkingHoursEnforcer()
        # Saturday 10:00 -> next Monday 9:00
        with patch.object(e, "_now", return_value=_make_dt(day=11, hour=10)):
            nxt = e.get_next_working_time()
            assert nxt.weekday() == 0  # Monday
            assert nxt.hour == 9
            assert nxt.day == 13

    def test_after_hours_gets_tomorrow(self):
        e = WorkingHoursEnforcer()
        # Monday 18:00 -> Tuesday 9:00
        with patch.object(e, "_now", return_value=_make_dt(day=6, hour=18)):
            nxt = e.get_next_working_time()
            assert nxt.day == 7
            assert nxt.hour == 9

    def test_before_start_same_day(self):
        e = WorkingHoursEnforcer()
        # Monday 7:00 -> Monday 9:00
        with patch.object(e, "_now", return_value=_make_dt(day=6, hour=7)):
            nxt = e.get_next_working_time()
            assert nxt.day == 6
            assert nxt.hour == 9

    def test_friday_after_hours_gets_monday(self):
        e = WorkingHoursEnforcer()
        # 2025-01-10 is Friday
        with patch.object(e, "_now", return_value=_make_dt(day=10, hour=18)):
            nxt = e.get_next_working_time()
            assert nxt.weekday() == 0  # Monday
            assert nxt.day == 13


# ---------------------------------------------------------------------------
# add_human_delay
# ---------------------------------------------------------------------------


class TestAddHumanDelay:
    def test_returns_int(self):
        e = WorkingHoursEnforcer()
        delay = e.add_human_delay()
        assert isinstance(delay, int)

    def test_delay_within_range(self):
        e = WorkingHoursEnforcer({"randomize_minutes": 10})
        for _ in range(50):
            delay = e.add_human_delay()
            assert 0 <= delay <= 600  # 10 * 60

    def test_no_delay_when_disabled(self):
        e = WorkingHoursEnforcer({"randomize_start": False})
        assert e.add_human_delay() == 0


# ---------------------------------------------------------------------------
# wait_for_delay (async)
# ---------------------------------------------------------------------------


class TestWaitForDelay:
    @pytest.mark.asyncio
    async def test_waits_for_delay(self):
        e = WorkingHoursEnforcer({"randomize_minutes": 1})
        with patch.object(e, "add_human_delay", return_value=0):
            result = await e.wait_for_delay()
            assert result == 0

    @pytest.mark.asyncio
    async def test_nonzero_delay(self):
        e = WorkingHoursEnforcer()
        with (
            patch.object(e, "add_human_delay", return_value=5),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            result = await e.wait_for_delay()
            assert result == 5
            mock_sleep.assert_awaited_once_with(5)


# ---------------------------------------------------------------------------
# wait_for_working_hours (async)
# ---------------------------------------------------------------------------


class TestWaitForWorkingHours:
    @pytest.mark.asyncio
    async def test_disabled_returns_immediately(self):
        e = WorkingHoursEnforcer({"enabled": False})
        result = await e.wait_for_working_hours()
        assert isinstance(result, datetime)

    @pytest.mark.asyncio
    async def test_during_hours_adds_delay(self):
        e = WorkingHoursEnforcer()
        with (
            patch.object(e, "is_working_hours", return_value=True),
            patch.object(e, "wait_for_delay", new_callable=AsyncMock, return_value=0),
        ):
            result = await e.wait_for_working_hours()
            assert isinstance(result, datetime)

    @pytest.mark.asyncio
    async def test_waits_until_working_hours(self):
        e = WorkingHoursEnforcer()
        call_count = 0

        def mock_is_working():
            nonlocal call_count
            call_count += 1
            # First call: not working, second: working (after loop re-check)
            return call_count >= 3

        next_time = _make_dt(day=7, hour=9)

        with (
            patch.object(e, "is_working_hours", side_effect=mock_is_working),
            patch.object(e, "get_next_working_time", return_value=next_time),
            patch.object(e, "_now", return_value=_make_dt(day=6, hour=20)),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch.object(e, "wait_for_delay", new_callable=AsyncMock, return_value=0),
        ):
            result = await e.wait_for_working_hours()
            assert result is not None


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


class TestGetStatus:
    def test_status_during_working_hours(self):
        e = WorkingHoursEnforcer()
        with patch.object(e, "_now", return_value=_make_dt(hour=10)):
            status = e.get_status()
            assert status["enabled"] is True
            assert status["is_working_hours"] is True
            assert "next_working_time" not in status
            assert status["timezone"] == "America/New_York"

    def test_status_outside_working_hours(self):
        e = WorkingHoursEnforcer()
        with patch.object(e, "_now", return_value=_make_dt(hour=20)):
            status = e.get_status()
            assert status["is_working_hours"] is False
            assert "next_working_time" in status
            assert "wait_hours" in status

    def test_status_disabled(self):
        e = WorkingHoursEnforcer({"enabled": False})
        status = e.get_status()
        assert status["enabled"] is False
        assert status["is_working_hours"] is True

    def test_working_hours_format(self):
        e = WorkingHoursEnforcer({"start_hour": 9, "end_hour": 17})
        with patch.object(e, "_now", return_value=_make_dt(hour=10)):
            status = e.get_status()
            assert status["working_hours"] == "09:00 - 17:00"


# ---------------------------------------------------------------------------
# format_status
# ---------------------------------------------------------------------------


class TestFormatStatus:
    def test_disabled_message(self):
        e = WorkingHoursEnforcer({"enabled": False})
        result = e.format_status()
        assert "DISABLED" in result

    def test_active_message(self):
        e = WorkingHoursEnforcer()
        with patch.object(e, "_now", return_value=_make_dt(hour=10)):
            result = e.format_status()
            assert "ACTIVE" in result
            assert "09:00 - 17:00" in result

    def test_outside_message(self):
        e = WorkingHoursEnforcer()
        with patch.object(e, "_now", return_value=_make_dt(hour=20)):
            result = e.format_status()
            assert "OUTSIDE" in result
            assert "hours" in result


# ---------------------------------------------------------------------------
# Singleton functions
# ---------------------------------------------------------------------------


class TestSingleton:
    def setup_method(self):
        reset_enforcer()

    def teardown_method(self):
        reset_enforcer()

    def test_get_creates_instance(self):
        e = get_working_hours_enforcer()
        assert isinstance(e, WorkingHoursEnforcer)

    def test_get_returns_same_instance(self):
        e1 = get_working_hours_enforcer()
        e2 = get_working_hours_enforcer()
        assert e1 is e2

    def test_config_only_on_first_call(self):
        e1 = get_working_hours_enforcer({"start_hour": 7})
        assert e1.config["start_hour"] == 7
        # Second call ignores config
        e2 = get_working_hours_enforcer({"start_hour": 11})
        assert e2.config["start_hour"] == 7

    def test_reset_allows_new_config(self):
        e1 = get_working_hours_enforcer({"start_hour": 7})
        reset_enforcer()
        e2 = get_working_hours_enforcer({"start_hour": 11})
        assert e2.config["start_hour"] == 11
        assert e1 is not e2

    def test_reset_sets_to_none(self):
        get_working_hours_enforcer()
        reset_enforcer()
        # Next call creates fresh instance
        e = get_working_hours_enforcer({"end_hour": 20})
        assert e.config["end_hour"] == 20


# ---------------------------------------------------------------------------
# Working days parsing
# ---------------------------------------------------------------------------


class TestWorkingDaysParsing:
    def test_default_working_days(self):
        e = WorkingHoursEnforcer()
        assert e._working_days == {0, 1, 2, 3, 4}

    def test_custom_days(self):
        e = WorkingHoursEnforcer({"days": ["monday", "wednesday", "friday"]})
        assert e._working_days == {0, 2, 4}

    def test_case_insensitive(self):
        e = WorkingHoursEnforcer({"days": ["Monday", "TUESDAY"]})
        assert e._working_days == {0, 1}

    def test_invalid_day_ignored(self):
        e = WorkingHoursEnforcer({"days": ["monday", "funday"]})
        assert e._working_days == {0}

    def test_all_seven_days(self):
        all_days = [
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        ]
        e = WorkingHoursEnforcer({"days": all_days})
        assert e._working_days == {0, 1, 2, 3, 4, 5, 6}
