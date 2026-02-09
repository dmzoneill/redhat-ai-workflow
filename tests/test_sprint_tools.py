"""Tests for tool_modules/aa_workflow/src/sprint_tools.py."""

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tool_modules.aa_workflow.src.sprint_history import (
    CompletedSprint,
    SprintIssue,
    SprintState,
    TimelineEvent,
)
from tool_modules.aa_workflow.src.sprint_tools import (
    ACTIONABLE_STATUSES,
    is_actionable,
    register_sprint_tools,
    sprint_approve,
    sprint_approve_all,
    sprint_disable,
    sprint_enable,
    sprint_history,
    sprint_load,
    sprint_skip,
    sprint_status,
    sprint_timeline,
)

# Shared module path prefix for patching
MOD = "tool_modules.aa_workflow.src.sprint_tools"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _issue(
    key="AAP-1",
    status="New",
    approval="pending",
    summary="Test issue summary here",
    points=3,
    reasoning=None,
    timeline=None,
):
    return SprintIssue(
        key=key,
        summary=summary,
        story_points=points,
        jira_status=status,
        approval_status=approval,
        priority_reasoning=reasoning or [],
        timeline=timeline or [],
    )


def _state(issues=None, bot_enabled=False, processing_issue=None, last_updated=""):
    return SprintState(
        issues=issues or [],
        bot_enabled=bot_enabled,
        processing_issue=processing_issue,
        last_updated=last_updated or datetime.now().isoformat(),
    )


# ---------------------------------------------------------------------------
# ACTIONABLE_STATUSES constant
# ---------------------------------------------------------------------------


class TestActionableStatuses:
    def test_contains_expected(self):
        assert "new" in ACTIONABLE_STATUSES
        assert "refinement" in ACTIONABLE_STATUSES
        assert "to do" in ACTIONABLE_STATUSES
        assert "open" in ACTIONABLE_STATUSES
        assert "backlog" in ACTIONABLE_STATUSES

    def test_count(self):
        assert len(ACTIONABLE_STATUSES) == 5


# ---------------------------------------------------------------------------
# is_actionable
# ---------------------------------------------------------------------------


class TestIsActionable:
    @pytest.mark.parametrize(
        "status", ["New", "Refinement", "To Do", "Open", "Backlog"]
    )
    def test_actionable(self, status):
        assert is_actionable(_issue(status=status)) is True

    @pytest.mark.parametrize(
        "status", ["In Review", "Done", "Release Pending", "Closed"]
    )
    def test_not_actionable(self, status):
        assert is_actionable(_issue(status=status)) is False

    def test_none_status(self):
        issue = _issue()
        issue.jira_status = None
        assert is_actionable(issue) is False

    def test_empty_status(self):
        assert is_actionable(_issue(status="")) is False


# ---------------------------------------------------------------------------
# sprint_load
# ---------------------------------------------------------------------------


class TestSprintLoad:
    def test_load_with_refresh(self):
        state = _state(
            issues=[
                _issue(key="AAP-1", status="New", approval="pending", points=5),
                _issue(key="AAP-2", status="Done", approval="completed", points=3),
            ]
        )

        with patch(f"{MOD}.refresh_sprint_state", return_value=state):
            result = sprint_load(project="AAP", refresh=True)

        assert "Current Sprint" in result
        assert "AAP-1" in result
        assert "AAP-2" in result
        assert "Actionable" in result
        assert "Not Actionable" in result

    def test_load_without_refresh(self):
        state = _state(issues=[_issue(key="AAP-1", status="New")])
        with patch(f"{MOD}.load_sprint_state", return_value=state):
            result = sprint_load(refresh=False)
        assert "AAP-1" in result

    def test_load_no_issues(self):
        state = _state(issues=[])
        with patch(f"{MOD}.refresh_sprint_state", return_value=state):
            result = sprint_load()
        assert "No sprint issues found" in result

    def test_load_shows_processing_issue(self):
        state = _state(
            issues=[_issue(key="AAP-1", status="New")],
            processing_issue="AAP-1",
        )
        with patch(f"{MOD}.refresh_sprint_state", return_value=state):
            result = sprint_load()
        assert "Currently Processing" in result
        assert "AAP-1" in result

    def test_load_shows_story_points(self):
        state = _state(issues=[_issue(key="AAP-1", status="New", points=8)])
        with patch(f"{MOD}.refresh_sprint_state", return_value=state):
            result = sprint_load()
        assert "[8pts]" in result

    def test_load_unknown_points(self):
        state = _state(issues=[_issue(key="AAP-1", status="New", points=0)])
        with patch(f"{MOD}.refresh_sprint_state", return_value=state):
            result = sprint_load()
        assert "[?pts]" in result

    def test_load_approval_status_icons(self):
        state = _state(
            issues=[
                _issue(key="AAP-1", status="New", approval="pending"),
                _issue(key="AAP-2", status="New", approval="approved"),
                _issue(key="AAP-3", status="New", approval="in_progress"),
                _issue(key="AAP-4", status="New", approval="blocked"),
            ]
        )
        with patch(f"{MOD}.refresh_sprint_state", return_value=state):
            result = sprint_load()
        # Each should have its icon
        assert "AAP-1" in result
        assert "AAP-2" in result
        assert "AAP-3" in result
        assert "AAP-4" in result

    def test_load_shows_priority_reasoning(self):
        state = _state(
            issues=[
                _issue(
                    key="AAP-1",
                    status="New",
                    reasoning=["High priority", "Old issue", "Extra"],
                ),
            ]
        )
        with patch(f"{MOD}.refresh_sprint_state", return_value=state):
            result = sprint_load()
        assert "High priority" in result
        assert "Old issue" in result
        # Only first 2 shown
        assert "Extra" not in result

    def test_load_bot_enabled_shown(self):
        state = _state(issues=[_issue(status="New")], bot_enabled=True)
        with patch(f"{MOD}.refresh_sprint_state", return_value=state):
            result = sprint_load()
        assert "Yes" in result

    def test_load_bot_disabled_shown(self):
        state = _state(issues=[_issue(status="New")], bot_enabled=False)
        with patch(f"{MOD}.refresh_sprint_state", return_value=state):
            result = sprint_load()
        assert "No" in result

    def test_load_error_handling(self):
        with patch(
            f"{MOD}.refresh_sprint_state", side_effect=RuntimeError("Jira down")
        ):
            result = sprint_load()
        assert "Error" in result
        assert "Jira down" in result

    def test_load_summary_truncated(self):
        long_summary = "A" * 100
        state = _state(issues=[_issue(key="AAP-1", status="New", summary=long_summary)])
        with patch(f"{MOD}.refresh_sprint_state", return_value=state):
            result = sprint_load()
        # Summary truncated to 50 chars + "..."
        assert "A" * 50 + "..." in result

    def test_load_only_actionable(self):
        state = _state(
            issues=[
                _issue(key="AAP-1", status="New"),
            ]
        )
        with patch(f"{MOD}.refresh_sprint_state", return_value=state):
            result = sprint_load()
        assert "Actionable Issues (1)" in result
        assert "Not Actionable" not in result

    def test_load_only_not_actionable(self):
        state = _state(
            issues=[
                _issue(key="AAP-1", status="Done"),
            ]
        )
        with patch(f"{MOD}.refresh_sprint_state", return_value=state):
            result = sprint_load()
        assert "Actionable Issues" not in result
        assert "Not Actionable (1)" in result


# ---------------------------------------------------------------------------
# sprint_enable / sprint_disable
# ---------------------------------------------------------------------------


class TestSprintEnableDisable:
    def test_enable_success(self):
        with patch(f"{MOD}.enable_sprint_bot", return_value={"success": True}):
            result = sprint_enable()
        assert "enabled" in result.lower()

    def test_enable_failure(self):
        with patch(
            f"{MOD}.enable_sprint_bot",
            return_value={"success": False, "message": "Auth fail"},
        ):
            result = sprint_enable()
        assert "Auth fail" in result

    def test_enable_failure_no_message(self):
        with patch(f"{MOD}.enable_sprint_bot", return_value={"success": False}):
            result = sprint_enable()
        assert "Unknown error" in result

    def test_disable_success(self):
        with patch(f"{MOD}.disable_sprint_bot", return_value={"success": True}):
            result = sprint_disable()
        assert "disabled" in result.lower()

    def test_disable_failure(self):
        with patch(
            f"{MOD}.disable_sprint_bot",
            return_value={"success": False, "message": "Err"},
        ):
            result = sprint_disable()
        assert "Err" in result

    def test_disable_failure_no_message(self):
        with patch(f"{MOD}.disable_sprint_bot", return_value={"success": False}):
            result = sprint_disable()
        assert "Unknown error" in result


# ---------------------------------------------------------------------------
# sprint_approve
# ---------------------------------------------------------------------------


class TestSprintApprove:
    def test_empty_key(self):
        result = sprint_approve("")
        assert "Please provide" in result

    def test_issue_not_found(self):
        state = _state(issues=[])
        with patch(f"{MOD}.load_sprint_state", return_value=state):
            result = sprint_approve("AAP-999")
        assert "not found" in result

    def test_not_actionable(self):
        state = _state(issues=[_issue(key="AAP-1", status="Done")])
        with patch(f"{MOD}.load_sprint_state", return_value=state):
            result = sprint_approve("AAP-1")
        assert "not actionable" in result
        assert "Done" in result

    def test_approve_success(self):
        state = _state(issues=[_issue(key="AAP-1", status="New")])
        with (
            patch(f"{MOD}.load_sprint_state", return_value=state),
            patch(f"{MOD}.approve_issue", return_value={"success": True}),
        ):
            result = sprint_approve("AAP-1")
        assert "approved" in result.lower()

    def test_approve_failure(self):
        state = _state(issues=[_issue(key="AAP-1", status="New")])
        with (
            patch(f"{MOD}.load_sprint_state", return_value=state),
            patch(
                f"{MOD}.approve_issue",
                return_value={"success": False, "message": "Conflict"},
            ),
        ):
            result = sprint_approve("AAP-1")
        assert "Conflict" in result

    def test_approve_failure_no_message(self):
        state = _state(issues=[_issue(key="AAP-1", status="New")])
        with (
            patch(f"{MOD}.load_sprint_state", return_value=state),
            patch(f"{MOD}.approve_issue", return_value={"success": False}),
        ):
            result = sprint_approve("AAP-1")
        assert "Failed to approve" in result


# ---------------------------------------------------------------------------
# sprint_skip
# ---------------------------------------------------------------------------


class TestSprintSkip:
    def test_empty_key(self):
        result = sprint_skip("")
        assert "Please provide" in result

    def test_skip_with_reason(self):
        with patch(f"{MOD}.skip_issue", return_value={"success": True}):
            result = sprint_skip("AAP-1", reason="Blocked")
        assert "skipped" in result.lower()
        assert "Blocked" in result

    def test_skip_default_reason(self):
        with patch(f"{MOD}.skip_issue", return_value={"success": True}) as mock_skip:
            result = sprint_skip("AAP-1")
        mock_skip.assert_called_once_with("AAP-1", "Manually skipped")
        assert "Manually skipped" in result

    def test_skip_failure(self):
        with patch(
            f"{MOD}.skip_issue", return_value={"success": False, "message": "Not found"}
        ):
            result = sprint_skip("AAP-1")
        assert "Not found" in result

    def test_skip_failure_no_message(self):
        with patch(f"{MOD}.skip_issue", return_value={"success": False}):
            result = sprint_skip("AAP-1")
        assert "Failed to skip" in result


# ---------------------------------------------------------------------------
# sprint_status
# ---------------------------------------------------------------------------


class TestSprintStatus:
    def test_basic_status(self):
        status_data = {
            "bot_enabled": True,
            "processing_issue": "AAP-1",
            "total_issues": 5,
            "status_counts": {
                "pending": 2,
                "approved": 1,
                "in_progress": 1,
                "completed": 1,
            },
            "last_updated": "2026-02-01T10:00:00",
        }
        state = _state(
            issues=[
                _issue(key="AAP-1", status="New"),
                _issue(key="AAP-2", status="New"),
                _issue(key="AAP-3", status="Done"),
            ]
        )

        with (
            patch(f"{MOD}.get_sprint_status", return_value=status_data),
            patch(f"{MOD}.load_sprint_state", return_value=state),
            patch(f"{MOD}.is_within_working_hours", return_value=True),
        ):
            result = sprint_status()

        assert "Sprint Bot Status" in result
        assert "Yes" in result  # bot enabled
        assert "Active" in result  # within working hours
        assert "AAP-1" in result  # processing issue
        assert "Pending" in result
        assert "Approved" in result

    def test_status_outside_hours(self):
        status_data = {
            "bot_enabled": False,
            "processing_issue": None,
            "total_issues": 0,
            "status_counts": {},
            "last_updated": "2026-02-01T10:00:00",
        }
        state = _state(issues=[])

        with (
            patch(f"{MOD}.get_sprint_status", return_value=status_data),
            patch(f"{MOD}.load_sprint_state", return_value=state),
            patch(f"{MOD}.is_within_working_hours", return_value=False),
        ):
            result = sprint_status()

        assert "No" in result  # bot disabled
        assert "Outside hours" in result

    def test_status_no_processing_issue(self):
        status_data = {
            "bot_enabled": True,
            "processing_issue": None,
            "total_issues": 1,
            "status_counts": {"pending": 1},
            "last_updated": "2026-02-01",
        }
        state = _state(issues=[_issue(status="New")])

        with (
            patch(f"{MOD}.get_sprint_status", return_value=status_data),
            patch(f"{MOD}.load_sprint_state", return_value=state),
            patch(f"{MOD}.is_within_working_hours", return_value=True),
        ):
            result = sprint_status()

        assert "Currently Processing" not in result

    def test_status_actionable_counts(self):
        status_data = {
            "bot_enabled": True,
            "processing_issue": None,
            "total_issues": 3,
            "status_counts": {"pending": 3},
            "last_updated": "2026-02-01",
        }
        state = _state(
            issues=[
                _issue(key="AAP-1", status="New"),
                _issue(key="AAP-2", status="New"),
                _issue(key="AAP-3", status="Done"),
            ]
        )

        with (
            patch(f"{MOD}.get_sprint_status", return_value=status_data),
            patch(f"{MOD}.load_sprint_state", return_value=state),
            patch(f"{MOD}.is_within_working_hours", return_value=True),
        ):
            result = sprint_status()

        assert "Actionable (New/Refinement): 2" in result
        assert "Not Actionable (Review/Done): 1" in result


# ---------------------------------------------------------------------------
# sprint_history
# ---------------------------------------------------------------------------


class TestSprintHistory:
    def test_no_history(self):
        with patch(f"{MOD}.load_sprint_history", return_value=[]):
            result = sprint_history()
        assert "No sprint history found" in result

    def test_with_history(self):
        sprints = [
            CompletedSprint(
                id="1",
                name="Sprint 42",
                start_date="2026-01-01T00:00:00",
                end_date="2026-01-14T00:00:00",
                total_points=20,
                completed_points=15,
                issues=[_issue()],
            ),
            CompletedSprint(
                id="2",
                name="Sprint 43",
                start_date="2026-01-15T00:00:00",
                end_date="2026-01-28T00:00:00",
                total_points=25,
                completed_points=25,
                issues=[_issue(), _issue(key="AAP-2")],
            ),
        ]

        with patch(f"{MOD}.load_sprint_history", return_value=sprints):
            result = sprint_history(limit=5)

        assert "Sprint History" in result
        assert "Sprint 42" in result
        assert "Sprint 43" in result
        assert "15/20" in result
        assert "75%" in result
        assert "25/25" in result
        assert "100%" in result

    def test_history_respects_limit(self):
        with patch(f"{MOD}.load_sprint_history") as mock_load:
            mock_load.return_value = []
            result = sprint_history(limit=3)
        mock_load.assert_called_once_with(limit=3)
        assert "No sprint history" in result

    def test_history_zero_total_points(self):
        sprints = [
            CompletedSprint(
                id="1",
                name="Sprint Empty",
                start_date="2026-01-01T00:00:00",
                end_date="2026-01-14T00:00:00",
                total_points=0,
                completed_points=0,
                issues=[],
            ),
        ]
        with patch(f"{MOD}.load_sprint_history", return_value=sprints):
            result = sprint_history()
        assert "0/0" in result
        assert "0%" in result


# ---------------------------------------------------------------------------
# sprint_timeline
# ---------------------------------------------------------------------------


class TestSprintTimeline:
    def test_issue_not_found(self):
        state = _state(issues=[])
        with patch(f"{MOD}.load_sprint_state", return_value=state):
            result = sprint_timeline("AAP-999")
        assert "not found" in result

    def test_no_timeline(self):
        state = _state(issues=[_issue(key="AAP-1")])
        with patch(f"{MOD}.load_sprint_state", return_value=state):
            result = sprint_timeline("AAP-1")
        assert "Timeline: AAP-1" in result
        assert "No timeline events" in result

    def test_with_timeline_events(self):
        events = [
            TimelineEvent(
                timestamp="2026-02-01T10:30:00",
                action="approved",
                description="Issue approved",
                chat_link="chat-123",
                jira_link="https://jira.example.com/AAP-1",
            ),
            TimelineEvent(
                timestamp="2026-02-01T11:00:00",
                action="started",
                description="Work started",
                chat_link=None,
                jira_link=None,
            ),
        ]
        state = _state(issues=[_issue(key="AAP-1", timeline=events)])
        with patch(f"{MOD}.load_sprint_state", return_value=state):
            result = sprint_timeline("AAP-1")

        assert "Timeline: AAP-1" in result
        assert "2026-02-01 10:30" in result
        assert "[approved]" in result
        assert "Issue approved" in result
        assert "chat-123" in result
        assert "jira.example.com" in result
        assert "[started]" in result
        assert "Work started" in result

    def test_timeline_shows_status(self):
        state = _state(issues=[_issue(key="AAP-1", approval="in_progress")])
        with patch(f"{MOD}.load_sprint_state", return_value=state):
            result = sprint_timeline("AAP-1")
        assert "in_progress" in result


# ---------------------------------------------------------------------------
# sprint_approve_all
# ---------------------------------------------------------------------------


class TestSprintApproveAll:
    def test_no_pending(self):
        state = _state(
            issues=[
                _issue(key="AAP-1", status="New", approval="approved"),
            ]
        )
        with patch(f"{MOD}.load_sprint_state", return_value=state):
            result = sprint_approve_all()
        assert "No pending issues" in result

    def test_approve_actionable(self):
        state = _state(
            issues=[
                _issue(key="AAP-1", status="New", approval="pending"),
                _issue(key="AAP-2", status="New", approval="pending"),
            ]
        )
        with (
            patch(f"{MOD}.load_sprint_state", return_value=state),
            patch(f"{MOD}.save_sprint_state"),
        ):
            result = sprint_approve_all()
        assert "Approved 2" in result
        assert state.issues[0].approval_status == "approved"
        assert state.issues[1].approval_status == "approved"

    def test_skip_non_actionable(self):
        state = _state(
            issues=[
                _issue(key="AAP-1", status="New", approval="pending"),
                _issue(key="AAP-2", status="Done", approval="pending"),
            ]
        )
        with (
            patch(f"{MOD}.load_sprint_state", return_value=state),
            patch(f"{MOD}.save_sprint_state"),
        ):
            result = sprint_approve_all()
        assert "Approved 1" in result
        assert "Skipped 1" in result
        assert state.issues[0].approval_status == "approved"
        assert state.issues[1].approval_status == "completed"

    def test_timeline_event_added(self):
        state = _state(
            issues=[
                _issue(key="AAP-1", status="New", approval="pending"),
            ]
        )
        with (
            patch(f"{MOD}.load_sprint_state", return_value=state),
            patch(f"{MOD}.save_sprint_state"),
        ):
            sprint_approve_all()
        assert len(state.issues[0].timeline) == 1
        assert state.issues[0].timeline[0].action == "approved"
        assert "Bulk approved" in state.issues[0].timeline[0].description

    def test_state_saved(self):
        state = _state(
            issues=[
                _issue(key="AAP-1", status="New", approval="pending"),
            ]
        )
        with (
            patch(f"{MOD}.load_sprint_state", return_value=state),
            patch(f"{MOD}.save_sprint_state") as mock_save,
        ):
            result = sprint_approve_all()
        mock_save.assert_called_once_with(state)
        assert "approved" in result.lower() or "Approved" in result

    def test_last_updated_set(self):
        state = _state(
            issues=[
                _issue(key="AAP-1", status="New", approval="pending"),
            ]
        )
        old_updated = state.last_updated
        with (
            patch(f"{MOD}.load_sprint_state", return_value=state),
            patch(f"{MOD}.save_sprint_state"),
        ):
            sprint_approve_all()
        assert state.last_updated != old_updated

    def test_mixed_statuses_ignored(self):
        """Only pending issues are touched."""
        state = _state(
            issues=[
                _issue(key="AAP-1", status="New", approval="approved"),
                _issue(key="AAP-2", status="New", approval="blocked"),
                _issue(key="AAP-3", status="New", approval="in_progress"),
            ]
        )
        with patch(f"{MOD}.load_sprint_state", return_value=state):
            result = sprint_approve_all()
        assert "No pending issues" in result


# ---------------------------------------------------------------------------
# register_sprint_tools
# ---------------------------------------------------------------------------


class TestRegisterSprintTools:
    def test_registers_9_tools(self):
        mock_mcp = MagicMock()
        # mcp.tool() returns a decorator
        mock_mcp.tool.return_value = lambda f: f
        count = register_sprint_tools(mock_mcp)
        assert count == 9
        assert mock_mcp.tool.call_count == 9

    def test_registers_correct_functions(self):
        mock_mcp = MagicMock()
        registered = []
        mock_mcp.tool.return_value = lambda f: registered.append(f.__name__) or f
        register_sprint_tools(mock_mcp)

        expected = {
            "sprint_load",
            "sprint_enable",
            "sprint_disable",
            "sprint_approve",
            "sprint_skip",
            "sprint_status",
            "sprint_history",
            "sprint_timeline",
            "sprint_approve_all",
        }
        assert set(registered) == expected
