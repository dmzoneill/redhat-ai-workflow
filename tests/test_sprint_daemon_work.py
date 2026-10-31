"""Tests for the background-run outcome helpers in services.sprint.daemon_work."""

from unittest.mock import MagicMock

import pytest

from services.sprint.bot.execution_tracer import StepStatus
from services.sprint.daemon_work import notify_safely, resolve_background_outcome


def test_completed_marker_is_success_with_continuation_prompt():
    """COMPLETED: success, notify completed, continuation prompt from the work log."""
    outcome = resolve_background_outcome("AAP-1", {"status": "COMPLETED"}, 0, "")
    assert outcome.status == "completed"
    assert outcome.result == {"success": True, "message": "Completed AAP-1 in background"}
    assert outcome.prompt is None
    assert outcome.notify == "completed"
    assert outcome.trace == {"decision": "completed", "reason": "Bot reported COMPLETED status"}


def test_blocked_marker_records_reason():
    """BLOCKED: failure flagged as blocked, reason stored and traced."""
    outcome = resolve_background_outcome("AAP-1", {"status": "BLOCKED", "reason": "need creds"}, 0, "")
    assert outcome.status == "blocked"
    assert outcome.result == {"success": False, "error": "Blocked: need creds", "blocked": True}
    assert outcome.fields == {"blocked_reason": "need creds"}
    assert outcome.notify == "blocked"
    assert outcome.trace is not None and outcome.trace["status"] is StepStatus.FAILED
    assert outcome.prompt is not None and "need creds" in outcome.prompt


def test_blocked_without_reason_defaults():
    """A BLOCKED marker without a reason reports an unknown reason."""
    outcome = resolve_background_outcome("AAP-1", {"status": "BLOCKED"}, 0, "")
    assert outcome.fields == {"blocked_reason": "Unknown reason"}


@pytest.mark.parametrize(
    ("bot_status", "returncode", "stderr", "reason"),
    [
        ({"status": "FAILED", "error": "no file"}, 0, "ignored", "no file"),
        ({"status": "FAILED"}, 0, "stderr text", "stderr text"),
        ({"status": "UNKNOWN"}, 2, "x" * 600, "x" * 500),
    ],
)
def test_failures_use_marker_error_or_stderr(bot_status, returncode, stderr, reason):
    """FAILED marker or non-zero exit: failure with the marker error, else truncated stderr."""
    outcome = resolve_background_outcome("AAP-1", bot_status, returncode, stderr)
    assert outcome.status == "failed"
    assert outcome.fields == {"error": reason}
    assert outcome.result == {"success": False, "error": f"Failed: {reason[:200]}"}
    assert outcome.notify is None


def test_no_marker_with_clean_exit_counts_as_completed():
    """No status marker and exit 0: completed, no trace step, no notification."""
    outcome = resolve_background_outcome("AAP-1", {"status": "UNKNOWN"}, 0, "")
    assert (outcome.status, outcome.trace, outcome.notify, outcome.prompt) == ("completed", None, None, None)
    assert outcome.result["success"] is True


def test_notify_safely_passes_arguments():
    """The notifier receives the given arguments."""
    notify = MagicMock()
    notify_safely(notify, "AAP-1", "summary")
    notify.assert_called_once_with("AAP-1", "summary")


def test_notify_safely_swallows_recoverable_errors():
    """A failing notifier does not raise."""
    notify_safely(MagicMock(side_effect=OSError("no display")), "AAP-1")


def test_notify_safely_propagates_programming_errors():
    """Non-recoverable errors still surface."""
    with pytest.raises(ZeroDivisionError):
        notify_safely(MagicMock(side_effect=ZeroDivisionError), "AAP-1")
