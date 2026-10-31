"""Tests for the SprintDaemon main loop and D-Bus handler registration.

Everything is exercised through the public ``SprintDaemon()`` constructor and ``run_daemon()``; the daemon's
collaborators (state file, Jira, working hours, shutdown wait) are patched on the class.
"""

from contextlib import ExitStack
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.sprint.daemon import SprintDaemon


@dataclass
class Loop:
    """A constructed daemon plus the mocks standing in for its collaborators."""

    daemon: SprintDaemon
    mocks: dict[str, MagicMock] = field(default_factory=dict)

    def __getitem__(self, name: str) -> MagicMock:
        return self.mocks[name]


@pytest.fixture(name="make_loop")
def fixture_make_loop():
    """Build a SprintDaemon whose loop stops after ``waits`` shutdown waits."""
    with ExitStack() as stack:

        def make(**opts) -> Loop:
            """Options: states, within_hours, elapsed, waits, check_interval, error (raised by the first load)."""
            states = list(opts.get("states") or [{"issues": []}])
            errors = [opts["error"]] if opts.get("error") else []
            within_hours = opts.get("within_hours", True)
            elapsed = opts.get("elapsed", float("inf"))
            waits = opts.get("waits", 1)
            check_interval = opts.get("check_interval", 300)

            def load_state(*_args) -> dict:
                if errors:
                    raise errors.pop()
                return states.pop(0) if len(states) > 1 else states[0]

            mocks = {
                "register_handler": MagicMock(),
                "_load_state": MagicMock(side_effect=load_state),
                "_save_state": MagicMock(),
                "_is_within_working_hours": MagicMock(return_value=within_hours),
                "_is_actionable": MagicMock(return_value=True),
                "_elapsed_seconds": MagicMock(return_value=elapsed),
                "_refresh_from_jira": AsyncMock(),
                "_check_review_issues": AsyncMock(),
                "_process_next_issue": AsyncMock(),
                "_wait_with_shutdown": AsyncMock(side_effect=[False] * (waits - 1) + [True]),
            }
            for name, mock in mocks.items():
                stack.enter_context(patch.object(SprintDaemon, name, mock))
            config = {"sprint": {"scheduling": {"issue_processing": {"interval_seconds": check_interval}}}}
            stack.enter_context(patch("services.sprint.daemon.load_config", return_value=config))
            return Loop(SprintDaemon(), mocks)

        yield make


def test_init_registers_every_dbus_method(make_loop):
    """Each DBUS_METHODS entry is registered with its _handle_<name> coroutine (base handlers may add more)."""
    loop = make_loop()
    registered = {call.args[0]: call.args[1] for call in loop["register_handler"].call_args_list}
    assert len(set(SprintDaemon.DBUS_METHODS)) == len(SprintDaemon.DBUS_METHODS)
    for method_name in SprintDaemon.DBUS_METHODS:
        assert registered[method_name].__name__ == f"_handle_{method_name}"


@pytest.mark.parametrize(
    ("state", "within_hours"),
    [({"automaticMode": True}, False), ({}, True)],
)
async def test_inactive_bot_waits_a_minute_and_does_nothing(make_loop, state, within_hours):
    """Automatic mode outside hours, or not started at all: wait 60s, no Jira work, no save."""
    loop = make_loop(states=[state], within_hours=within_hours)
    await loop.daemon.run_daemon()
    loop["_wait_with_shutdown"].assert_awaited_once_with(60)
    loop["_refresh_from_jira"].assert_not_awaited()
    loop["_save_state"].assert_not_called()


@pytest.mark.parametrize(
    ("state", "within_hours"),
    [({"manuallyStarted": True}, False), ({"automaticMode": True}, True)],
)
async def test_active_bot_runs_due_checks_saves_and_waits_interval(make_loop, state, within_hours):
    """Manual start (any time) or automatic mode in hours: due checks run, state saved, interval wait."""
    loop = make_loop(states=[{**state, "issues": []}], within_hours=within_hours, check_interval=42)
    await loop.daemon.run_daemon()
    loop["_refresh_from_jira"].assert_awaited_once()
    loop["_check_review_issues"].assert_awaited_once()
    loop["_save_state"].assert_called_once()
    loop["_wait_with_shutdown"].assert_awaited_once_with(42)


async def test_checks_skipped_before_intervals_elapse(make_loop):
    """Recent refresh/review: neither runs again."""
    loop = make_loop(states=[{"manuallyStarted": True, "issues": []}], elapsed=1.0)
    await loop.daemon.run_daemon()
    loop["_refresh_from_jira"].assert_not_awaited()
    loop["_check_review_issues"].assert_not_awaited()


async def test_idle_bot_processes_approved_issue(make_loop):
    """An approved actionable issue is processed when nothing is in progress."""
    issues = [{"key": "AAP-1", "approvalStatus": "approved"}]
    loop = make_loop(states=[{"manuallyStarted": True, "issues": issues}], elapsed=1.0)
    await loop.daemon.run_daemon()
    loop["_process_next_issue"].assert_awaited_once()


@pytest.mark.parametrize(
    "extra",
    [
        {"processingIssue": "AAP-2", "issues": [{"key": "AAP-1", "approvalStatus": "approved"}]},
        {"issues": [{"key": "AAP-1", "approvalStatus": "pending"}]},
    ],
)
async def test_busy_or_unapproved_issue_is_not_processed(make_loop, extra):
    """An issue already in progress, or no approved issue: nothing new starts."""
    loop = make_loop(states=[{"manuallyStarted": True, **extra}], elapsed=1.0)
    await loop.daemon.run_daemon()
    loop["_process_next_issue"].assert_not_awaited()


async def test_recoverable_error_waits_a_minute_then_continues(make_loop):
    """A recoverable error is logged, the loop waits 60s and runs again."""
    loop = make_loop(error=OSError("disk"), waits=2)
    await loop.daemon.run_daemon()
    assert [call.args[0] for call in loop["_wait_with_shutdown"].await_args_list] == [60, 60]
    assert loop["_load_state"].call_count == 2
