"""Tests for SprintDaemon D-Bus handlers refactored in services.sprint.daemon_handlers.

Handlers are invoked through the public ``call_handler``; state, Jira, Cursor and Claude collaborators are patched.
"""

import json
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.sprint.daemon import SprintDaemon
from services.sprint.daemon_handlers import find_issue, launch_continuation_chat
from services.sprint.sprint_history_tracker import SprintHistoryTracker


def _issue(key="AAP-1", **extra) -> dict:
    return {"key": key, "summary": "Do it", "approvalStatus": "approved", "jiraStatus": "New", **extra}


@pytest.fixture(name="daemon_with")
def fixture_daemon_with(tmp_path):
    """Build a SprintDaemon over an in-memory state; returns (daemon, state holder, mocks)."""
    with ExitStack() as stack:

        def make(issues, run_result=None, cursor=True, background=True):
            holder = {"state": {"issues": issues, "backgroundTasks": background}}
            tracer = MagicMock(trace_path=tmp_path / "trace.yaml", workflow_type="code_change")
            mocks = {
                "_load_state": MagicMock(side_effect=lambda: holder["state"]),
                "_save_state": MagicMock(side_effect=lambda s: holder.update(state=s)),
                "_get_tracer": MagicMock(return_value=tracer),
                "_is_actionable": MagicMock(return_value=True),
                "_is_cursor_available": AsyncMock(return_value=cursor),
                "_start_jira_work": AsyncMock(),
                "_transition_jira_issue": AsyncMock(return_value=True),
                "_run_issue_in_background_traced": AsyncMock(return_value=run_result or {"success": True}),
                "_process_in_cursor_traced": AsyncMock(return_value={"success": True, "chat_id": "c1"}),
                "_build_work_prompt": MagicMock(return_value="prompt"),
            }
            for name, mock in mocks.items():
                stack.enter_context(patch.object(SprintDaemon, name, mock))
            workflow = MagicMock()
            workflow.get_jira_transition.side_effect = {"in_progress": "In Progress", "in_review": "In Review"}.get
            workflow.classify_issue.return_value = "code_change"
            stack.enter_context(patch.object(SprintDaemon, "workflow_config", new=workflow))
            stack.enter_context(patch("services.sprint.daemon.load_config", return_value={}))
            daemon = SprintDaemon()
            return daemon, holder, mocks, tracer

        yield make


def test_find_issue():
    """find_issue returns the matching issue or None."""
    state = {"issues": [_issue("A"), _issue("B")]}
    assert find_issue(state, "B")["key"] == "B"
    assert find_issue(state, "C") is None
    assert find_issue({}, "A") is None


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        (json.dumps({"success": True, "chatId": "chat-9"}), "chat-9"),
        (json.dumps({"success": False, "error": "x"}), None),
        ("", None),
    ],
)
async def test_launch_continuation_chat(reply, expected):
    """The chat ID is returned only for a successful extension reply; the bus is always disconnected."""
    bus = MagicMock()
    chat = MagicMock(call_launch_issue_chat=AsyncMock(return_value=reply))
    with patch("services.sprint.daemon_handlers.connect_chat_interface", AsyncMock(return_value=(bus, chat))):
        assert await launch_continuation_chat("AAP-1", {"summary": "S"}) == expected
    chat.call_launch_issue_chat.assert_awaited_once_with("AAP-1", "Continue: S", False)
    bus.disconnect.assert_called_once_with()


async def test_start_issue_requires_known_issue(daemon_with):
    """Missing or unknown issue keys are rejected."""
    daemon, *_ = daemon_with([_issue()])
    assert (await daemon.call_handler("start_issue", {}))["error"] == "issue_key required"
    assert "not found" in (await daemon.call_handler("start_issue", {"issue_key": "AAP-404"}))["error"]


async def test_start_issue_background_success_moves_to_review(daemon_with):
    """A successful background run marks the issue completed and in review, and clears processing."""
    daemon, holder, mocks, tracer = daemon_with([_issue()])
    result = await daemon.call_handler("start_issue", {"issue_key": "AAP-1"})
    assert result == {"success": True, "message": "Completed AAP-1", "mode": "background"}
    issue = holder["state"]["issues"][0]
    assert issue["approvalStatus"] == "completed"
    assert issue["jiraStatus"] == daemon.jira_status_in_review
    assert issue["hasWorkLog"] and issue["hasTrace"]
    assert holder["state"]["processingIssue"] is None
    mocks["_transition_jira_issue"].assert_awaited_once_with("AAP-1", daemon.jira_status_in_review)
    tracer.mark_completed.assert_called_once()
    assert [e["action"] for e in issue["timeline"]] == ["force_started", "started", "background_completed"]


async def test_start_issue_background_failure_blocks(daemon_with):
    """A failed background run blocks the issue with the reason and leaves Jira untouched."""
    daemon, holder, mocks, tracer = daemon_with([_issue()], run_result={"success": False, "error": "no MR"})
    result = await daemon.call_handler("start_issue", {"issue_key": "AAP-1"})
    assert result == {"success": False, "error": "no MR", "mode": "background"}
    issue = holder["state"]["issues"][0]
    assert (issue["approvalStatus"], issue["waitingReason"]) == ("blocked", "no MR")
    mocks["_transition_jira_issue"].assert_not_awaited()
    tracer.mark_blocked.assert_called_once_with("no MR")


async def test_start_issue_foreground_without_cursor_blocks(daemon_with):
    """Foreground start without Cursor blocks the issue."""
    daemon, holder, mocks, _ = daemon_with([_issue()], cursor=False)
    result = await daemon.call_handler("start_issue", {"issue_key": "AAP-1", "background": False})
    assert result["success"] is False and "Cursor is not available" in result["error"]
    assert holder["state"]["issues"][0]["approvalStatus"] == "blocked"
    mocks["_process_in_cursor_traced"].assert_not_awaited()


async def test_start_issue_foreground_with_cursor_opens_chat(daemon_with):
    """Foreground start with Cursor hands over to the Cursor chat flow."""
    daemon, _, mocks, _ = daemon_with([_issue()])
    assert (await daemon.call_handler("start_issue", {"issue_key": "AAP-1", "background": False}))["chat_id"] == "c1"
    mocks["_process_in_cursor_traced"].assert_awaited_once()


async def test_process_next_without_approved_issue(daemon_with):
    """Nothing approved: nothing to process."""
    daemon, *_ = daemon_with([_issue(approvalStatus="pending")])
    assert (await daemon.call_handler("process_next"))["message"] == "No approved actionable issues to process"


async def test_process_next_background_runs_and_records(daemon_with):
    """The next approved issue runs in background and is moved to review."""
    daemon, holder, mocks, tracer = daemon_with([_issue()])
    daemon.workflow_config.classify_issue = MagicMock(return_value="spike")
    assert (await daemon.call_handler("process_next"))["success"] is True
    assert holder["state"]["issues"][0]["approvalStatus"] == "completed"
    mocks["_start_jira_work"].assert_awaited_once()
    tracer.set_workflow_type.assert_called_once()


async def test_process_next_foreground_waits_for_cursor(daemon_with):
    """Foreground mode without Cursor waits instead of starting."""
    daemon, _, mocks, _ = daemon_with([_issue()], cursor=False, background=False)
    result = await daemon.call_handler("process_next")
    assert result == {"success": False, "waiting": True, "message": "Waiting for Cursor to be available"}
    mocks["_process_in_cursor_traced"].assert_not_awaited()


async def test_open_in_cursor_records_chat(daemon_with):
    """Opening background work in Cursor stores the chat ID and a timeline event."""
    daemon, holder, _, _ = daemon_with([_issue()])
    with (
        patch.object(SprintHistoryTracker, "load_work_log", return_value={"summary": "S"}),
        patch.object(SprintHistoryTracker, "build_cursor_context_prompt", return_value="ctx"),
        patch("services.sprint.daemon_handlers.launch_continuation_chat", AsyncMock(return_value="chat-1")),
    ):
        result = await daemon.call_handler("open_in_cursor", {"issue_key": "AAP-1"})
    assert result == {
        "success": True,
        "message": "Opened AAP-1 in Cursor",
        "chat_id": "chat-1",
        "context_prompt": "ctx",
    }
    issue = holder["state"]["issues"][0]
    assert issue["chatId"] == "chat-1"
    assert issue["timeline"][-1]["action"] == "opened_in_cursor"
