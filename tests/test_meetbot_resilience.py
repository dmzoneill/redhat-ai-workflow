"""Resilience boundaries in the meet-bot export module: Google errors and the cleanup loop."""

import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("fastmcp")
google_api_errors = pytest.importorskip("googleapiclient.errors")
google_auth_exceptions = pytest.importorskip("google.auth.exceptions")
pytest.importorskip("playwright")

export = importlib.import_module("tool_modules.aa_meet_bot.src.meet_notes_export")


def http_error(status: int = 401) -> Exception:
    """A googleapiclient HttpError with the given status."""
    return google_api_errors.HttpError(SimpleNamespace(status=status, reason="Unauthorized"), b"{}")


def calendars():
    """Two enabled calendars and one disabled one."""
    return [
        SimpleNamespace(name="broken", enabled=True),
        SimpleNamespace(name="skipped", enabled=False),
        SimpleNamespace(name="work", enabled=True),
    ]


@pytest.mark.parametrize(
    "error",
    [http_error(), google_auth_exceptions.RefreshError("token expired")],
    ids=["http-error", "refresh-error"],
)
def test_upcoming_meetings_skips_failing_calendar(error):
    """A Google API or auth error on one calendar skips it; the others are still listed."""
    meeting = {"title": "Standup", "startTime": "2026-11-01T09:00:00+00:00"}
    fetch = MagicMock(side_effect=[error, [meeting]])
    with (
        patch.object(export, "get_calendar_service", return_value=(MagicMock(), None)),
        patch.object(export, "_calendar_meetings", fetch),
    ):
        assert export.fetch_upcoming_meetings(calendars()) == [meeting]
    assert fetch.call_count == 2


@pytest.mark.parametrize(
    "error",
    [
        google_auth_exceptions.RefreshError("token expired"),
        http_error(503),
        OSError("pipewire gone"),
    ],
    ids=["refresh-error", "http-error", "os-error"],
)
async def test_periodic_cleanup_survives_iteration_error(error):
    """An error in one cleanup iteration is logged and the loop carries on to the next one."""
    sleep = AsyncMock(side_effect=[None, None, asyncio.CancelledError()])
    counts = AsyncMock(side_effect=[error, {"module_count": 0}])
    with (
        patch.object(export.asyncio, "sleep", sleep),
        patch.object(export, "active_controller_ids", return_value=[]),
        patch.object(export, "get_meetbot_device_count", counts),
        pytest.raises(asyncio.CancelledError),
    ):
        await export.periodic_cleanup_task()
    assert counts.await_count == 2
    assert sleep.await_count == 3
