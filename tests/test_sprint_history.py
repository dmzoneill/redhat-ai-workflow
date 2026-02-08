"""Tests for tool_modules.aa_workflow.src.sprint_history."""

import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tool_modules.aa_workflow.src.sprint_history import (
    CompletedSprint,
    SprintIssue,
    SprintState,
    TimelineEvent,
    add_timeline_event,
    complete_current_sprint,
    ensure_storage_dir,
    get_next_issue_to_process,
    load_sprint_history,
    load_sprint_state,
    save_sprint_state,
    save_sprint_to_history,
    update_issue_status,
)
from tool_modules.aa_workflow.src.sprint_tools import is_actionable

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sprint_files(tmp_path):
    """Redirect sprint files to temp dir."""
    state_file = tmp_path / "sprint_state_v2.json"
    history_file = tmp_path / "sprint_history.json"
    with (
        patch(
            "tool_modules.aa_workflow.src.sprint_history.SPRINT_STATE_FILE_V2",
            state_file,
        ),
        patch(
            "tool_modules.aa_workflow.src.sprint_history.SPRINT_HISTORY_FILE",
            history_file,
        ),
    ):
        yield state_file, history_file


def _make_state_json(
    issues=None,
    current_sprint=None,
    bot_enabled=False,
    processing_issue=None,
):
    """Build a sprint state dict for tests."""
    return {
        "currentSprint": current_sprint,
        "issues": issues or [],
        "botEnabled": bot_enabled,
        "lastUpdated": datetime.now().isoformat(),
        "processingIssue": processing_issue,
    }


def _make_issue_json(
    key="AAP-1",
    summary="Test",
    status="New",
    approval="pending",
    points=3,
    timeline=None,
):
    return {
        "key": key,
        "summary": summary,
        "storyPoints": points,
        "priority": "Major",
        "jiraStatus": status,
        "assignee": "alice",
        "approvalStatus": approval,
        "waitingReason": None,
        "priorityReasoning": [],
        "estimatedActions": [],
        "chatId": None,
        "timeline": timeline or [],
        "issueType": "Story",
        "created": "2025-01-01",
    }


# ---------------------------------------------------------------------------
# TimelineEvent
# ---------------------------------------------------------------------------


class TestTimelineEvent:
    def test_creation(self):
        e = TimelineEvent(
            timestamp="2025-01-01T00:00:00",
            action="started",
            description="Work started",
        )
        assert e.action == "started"
        assert e.chat_link is None
        assert e.jira_link is None


# ---------------------------------------------------------------------------
# SprintIssue
# ---------------------------------------------------------------------------


class TestSprintIssue:
    def test_defaults(self):
        issue = SprintIssue(key="AAP-1", summary="Test")
        assert issue.story_points == 0
        assert issue.timeline == []
        assert issue.approval_status == "pending"

    def test_add_timeline_event(self):
        issue = SprintIssue(key="AAP-1", summary="Test")
        event = TimelineEvent(timestamp="now", action="started", description="Begin")
        issue.add_timeline_event(event)
        assert len(issue.timeline) == 1

    def test_timeline_trimming(self):
        issue = SprintIssue(key="AAP-1", summary="Test")
        for i in range(60):
            issue.add_timeline_event(
                TimelineEvent(
                    timestamp=str(i), action="event", description=f"Event {i}"
                )
            )
        assert len(issue.timeline) == SprintIssue.MAX_TIMELINE_ENTRIES


# ---------------------------------------------------------------------------
# ensure_storage_dir
# ---------------------------------------------------------------------------


class TestEnsureStorageDir:
    def test_creates_directories(self, sprint_files):
        state_file, history_file = sprint_files
        ensure_storage_dir()
        assert state_file.parent.exists()
        assert history_file.parent.exists()


# ---------------------------------------------------------------------------
# load_sprint_state
# ---------------------------------------------------------------------------


class TestLoadSprintState:
    def test_returns_empty_when_no_file(self, sprint_files):
        state = load_sprint_state()
        assert isinstance(state, SprintState)
        assert state.issues == []
        assert state.current_sprint is None

    def test_loads_state_with_issues(self, sprint_files):
        state_file, _ = sprint_files
        data = _make_state_json(
            issues=[_make_issue_json("AAP-1", "Fix bug")],
            current_sprint={"id": "sprint-1", "name": "Sprint 1"},
            bot_enabled=True,
        )
        state_file.write_text(json.dumps(data))

        state = load_sprint_state()
        assert len(state.issues) == 1
        assert state.issues[0].key == "AAP-1"
        assert state.current_sprint["id"] == "sprint-1"
        assert state.bot_enabled is True

    def test_loads_timeline_events(self, sprint_files):
        state_file, _ = sprint_files
        timeline = [
            {
                "timestamp": "2025-01-01",
                "action": "started",
                "description": "Began work",
                "chatLink": "http://chat/1",
            }
        ]
        data = _make_state_json(issues=[_make_issue_json(timeline=timeline)])
        state_file.write_text(json.dumps(data))

        state = load_sprint_state()
        assert len(state.issues[0].timeline) == 1
        assert state.issues[0].timeline[0].chat_link == "http://chat/1"

    def test_handles_empty_file(self, sprint_files):
        state_file, _ = sprint_files
        state_file.write_text("{}")
        state = load_sprint_state()
        assert state.issues == []

    def test_handles_corrupt_json(self, sprint_files):
        state_file, _ = sprint_files
        state_file.write_text("{invalid json")
        state = load_sprint_state()
        assert state.issues == []

    def test_alternate_field_names(self, sprint_files):
        """Test snake_case field names (backward compat)."""
        state_file, _ = sprint_files
        data = {
            "current_sprint": {"id": "s1"},
            "issues": [
                {
                    "key": "AAP-1",
                    "summary": "T",
                    "story_points": 5,
                    "jira_status": "New",
                    "approval_status": "approved",
                    "waiting_reason": None,
                    "priority_reasoning": [],
                    "estimated_actions": [],
                    "chat_id": "c1",
                    "timeline": [],
                    "issue_type": "Bug",
                }
            ],
            "bot_enabled": True,
            "last_updated": "2025-01-01",
            "processing_issue": "AAP-1",
        }
        state_file.write_text(json.dumps(data))
        state = load_sprint_state()
        assert state.issues[0].story_points == 5
        assert state.issues[0].chat_id == "c1"


# ---------------------------------------------------------------------------
# save_sprint_state
# ---------------------------------------------------------------------------


class TestSaveSprintState:
    def test_saves_state(self, sprint_files):
        state_file, _ = sprint_files
        issue = SprintIssue(
            key="AAP-1",
            summary="Test",
            story_points=3,
            jira_status="In Progress",
        )
        state = SprintState(
            current_sprint={"id": "s1", "name": "Sprint 1"},
            issues=[issue],
            bot_enabled=True,
            last_updated=datetime.now().isoformat(),
        )
        save_sprint_state(state)

        data = json.loads(state_file.read_text())
        assert len(data["issues"]) == 1
        assert data["issues"][0]["key"] == "AAP-1"
        assert data["botEnabled"] is True

    def test_preserves_existing_issues_on_empty(self, sprint_files):
        state_file, _ = sprint_files
        # Pre-populate with existing issues
        existing = _make_state_json(issues=[_make_issue_json("AAP-1")])
        state_file.write_text(json.dumps(existing))

        # Save with empty issues
        state = SprintState(
            current_sprint={"id": "s1"},
            issues=[],
            last_updated=datetime.now().isoformat(),
        )
        save_sprint_state(state)

        data = json.loads(state_file.read_text())
        assert len(data["issues"]) == 1  # Preserved

    def test_preserves_current_sprint_on_none(self, sprint_files):
        state_file, _ = sprint_files
        existing = _make_state_json(
            current_sprint={"id": "s1", "name": "Existing Sprint"}
        )
        state_file.write_text(json.dumps(existing))

        state = SprintState(
            current_sprint=None,
            issues=[SprintIssue(key="AAP-1", summary="T")],
            last_updated=datetime.now().isoformat(),
        )
        save_sprint_state(state)

        data = json.loads(state_file.read_text())
        assert data["currentSprint"]["id"] == "s1"

    def test_timeline_serialization(self, sprint_files):
        state_file, _ = sprint_files
        event = TimelineEvent(
            timestamp="2025-01-01",
            action="started",
            description="Began",
            chat_link="http://chat",
            jira_link="http://jira",
        )
        issue = SprintIssue(key="AAP-1", summary="T", timeline=[event])
        state = SprintState(
            issues=[issue],
            last_updated=datetime.now().isoformat(),
        )
        save_sprint_state(state)

        data = json.loads(state_file.read_text())
        tl = data["issues"][0]["timeline"][0]
        assert tl["chatLink"] == "http://chat"
        assert tl["jiraLink"] == "http://jira"


# ---------------------------------------------------------------------------
# load_sprint_history
# ---------------------------------------------------------------------------


class TestLoadSprintHistory:
    def test_returns_empty_when_no_file(self, sprint_files):
        result = load_sprint_history()
        assert result == []

    def test_loads_history(self, sprint_files):
        _, history_file = sprint_files
        data = {
            "sprints": [
                {
                    "id": "s1",
                    "name": "Sprint 1",
                    "startDate": "2025-01-01",
                    "endDate": "2025-01-14",
                    "totalPoints": 20,
                    "completedPoints": 15,
                    "issues": [
                        {
                            "key": "AAP-1",
                            "summary": "Done",
                            "storyPoints": 5,
                            "priority": "Major",
                            "jiraStatus": "Done",
                            "approvalStatus": "completed",
                            "timeline": [],
                        }
                    ],
                    "timeline": [
                        {
                            "timestamp": "2025-01-14",
                            "action": "completed",
                            "description": "Sprint done",
                        }
                    ],
                    "collapsed": True,
                }
            ]
        }
        history_file.write_text(json.dumps(data))

        sprints = load_sprint_history()
        assert len(sprints) == 1
        assert sprints[0].name == "Sprint 1"
        assert sprints[0].completed_points == 15
        assert len(sprints[0].issues) == 1

    def test_respects_limit(self, sprint_files):
        _, history_file = sprint_files
        sprints_data = [
            {
                "id": f"s{i}",
                "name": f"Sprint {i}",
                "startDate": "",
                "endDate": "",
                "totalPoints": 0,
                "completedPoints": 0,
                "issues": [],
                "timeline": [],
            }
            for i in range(20)
        ]
        history_file.write_text(json.dumps({"sprints": sprints_data}))

        result = load_sprint_history(limit=5)
        assert len(result) == 5

    def test_handles_corrupt_json(self, sprint_files):
        _, history_file = sprint_files
        history_file.write_text("{bad json")
        result = load_sprint_history()
        assert result == []


# ---------------------------------------------------------------------------
# save_sprint_to_history
# ---------------------------------------------------------------------------


class TestSaveSprintToHistory:
    def test_saves_new_sprint(self, sprint_files):
        _, history_file = sprint_files
        sprint = CompletedSprint(
            id="s1",
            name="Sprint 1",
            start_date="2025-01-01",
            end_date="2025-01-14",
            total_points=20,
            completed_points=15,
            issues=[SprintIssue(key="AAP-1", summary="Done")],
            timeline=[],
        )
        save_sprint_to_history(sprint)

        data = json.loads(history_file.read_text())
        assert len(data["sprints"]) == 1
        assert data["sprints"][0]["id"] == "s1"

    def test_prepends_to_existing_history(self, sprint_files):
        _, history_file = sprint_files
        # Save first sprint
        s1 = CompletedSprint(
            id="s1",
            name="Sprint 1",
            start_date="",
            end_date="",
            total_points=0,
            completed_points=0,
        )
        save_sprint_to_history(s1)

        # Save second sprint
        s2 = CompletedSprint(
            id="s2",
            name="Sprint 2",
            start_date="",
            end_date="",
            total_points=0,
            completed_points=0,
        )
        save_sprint_to_history(s2)

        data = json.loads(history_file.read_text())
        assert len(data["sprints"]) == 2
        # Most recent should be first
        assert data["sprints"][0]["id"] == "s2"


# ---------------------------------------------------------------------------
# add_timeline_event
# ---------------------------------------------------------------------------


class TestAddTimelineEvent:
    def test_adds_event_to_existing_issue(self, sprint_files):
        state_file, _ = sprint_files
        data = _make_state_json(issues=[_make_issue_json("AAP-1")])
        state_file.write_text(json.dumps(data))

        event = TimelineEvent(
            timestamp="2025-01-01",
            action="started",
            description="Work began",
        )
        result = add_timeline_event("AAP-1", event)
        assert result is True

        # Verify event was added
        loaded = json.loads(state_file.read_text())
        assert len(loaded["issues"][0]["timeline"]) == 1

    def test_returns_false_for_missing_issue(self, sprint_files):
        state_file, _ = sprint_files
        data = _make_state_json(issues=[_make_issue_json("AAP-1")])
        state_file.write_text(json.dumps(data))

        event = TimelineEvent(timestamp="now", action="test", description="Test")
        result = add_timeline_event("AAP-999", event)
        assert result is False


# ---------------------------------------------------------------------------
# update_issue_status
# ---------------------------------------------------------------------------


class TestUpdateIssueStatus:
    def test_updates_status(self, sprint_files):
        state_file, _ = sprint_files
        data = _make_state_json(issues=[_make_issue_json("AAP-1")])
        state_file.write_text(json.dumps(data))

        result = update_issue_status("AAP-1", "approved")
        assert result is True

        loaded = json.loads(state_file.read_text())
        assert loaded["issues"][0]["approvalStatus"] == "approved"

    def test_updates_waiting_reason(self, sprint_files):
        state_file, _ = sprint_files
        data = _make_state_json(issues=[_make_issue_json("AAP-1")])
        state_file.write_text(json.dumps(data))

        result = update_issue_status("AAP-1", "waiting", waiting_reason="Need review")
        assert result is True

        loaded = json.loads(state_file.read_text())
        assert loaded["issues"][0]["waitingReason"] == "Need review"

    def test_updates_chat_id(self, sprint_files):
        state_file, _ = sprint_files
        data = _make_state_json(issues=[_make_issue_json("AAP-1")])
        state_file.write_text(json.dumps(data))

        result = update_issue_status("AAP-1", "in_progress", chat_id="chat-123")
        assert result is True

        loaded = json.loads(state_file.read_text())
        assert loaded["issues"][0]["chatId"] == "chat-123"

    def test_adds_timeline_event(self, sprint_files):
        state_file, _ = sprint_files
        data = _make_state_json(issues=[_make_issue_json("AAP-1")])
        state_file.write_text(json.dumps(data))

        update_issue_status("AAP-1", "approved")
        loaded = json.loads(state_file.read_text())
        assert len(loaded["issues"][0]["timeline"]) >= 1
        assert "approved" in loaded["issues"][0]["timeline"][-1]["description"]

    def test_returns_false_for_missing_issue(self, sprint_files):
        state_file, _ = sprint_files
        data = _make_state_json(issues=[_make_issue_json("AAP-1")])
        state_file.write_text(json.dumps(data))

        result = update_issue_status("AAP-999", "approved")
        assert result is False


# ---------------------------------------------------------------------------
# is_actionable
# ---------------------------------------------------------------------------


class TestIsActionable:
    @pytest.mark.parametrize(
        "status,expected",
        [
            ("New", True),
            ("Refinement", True),
            ("To Do", True),
            ("Open", True),
            ("Backlog", True),
            ("In Review", False),
            ("Done", False),
            ("Release Pending", False),
            ("Closed", False),
        ],
    )
    def test_status_check(self, status, expected):
        issue = SprintIssue(key="AAP-1", summary="T", jira_status=status)
        assert is_actionable(issue) == expected

    def test_empty_status(self):
        issue = SprintIssue(key="AAP-1", summary="T", jira_status="")
        assert is_actionable(issue) is False

    def test_none_status(self):
        issue = SprintIssue(key="AAP-1", summary="T", jira_status=None)
        assert is_actionable(issue) is False


# ---------------------------------------------------------------------------
# get_next_issue_to_process
# ---------------------------------------------------------------------------


class TestGetNextIssueToProcess:
    def test_returns_approved_actionable(self, sprint_files):
        state_file, _ = sprint_files
        data = _make_state_json(
            issues=[
                _make_issue_json("AAP-1", approval="approved", status="New"),
            ]
        )
        state_file.write_text(json.dumps(data))

        result = get_next_issue_to_process()
        assert result is not None
        assert result.key == "AAP-1"

    def test_skips_pending(self, sprint_files):
        state_file, _ = sprint_files
        data = _make_state_json(
            issues=[
                _make_issue_json("AAP-1", approval="pending", status="New"),
            ]
        )
        state_file.write_text(json.dumps(data))

        result = get_next_issue_to_process()
        assert result is None

    def test_skips_non_actionable(self, sprint_files):
        state_file, _ = sprint_files
        data = _make_state_json(
            issues=[
                _make_issue_json("AAP-1", approval="approved", status="Done"),
            ]
        )
        state_file.write_text(json.dumps(data))

        result = get_next_issue_to_process()
        assert result is None

    def test_returns_in_progress_if_processing(self, sprint_files):
        state_file, _ = sprint_files
        data = _make_state_json(
            issues=[
                _make_issue_json("AAP-1", approval="in_progress", status="New"),
            ],
            processing_issue="AAP-1",
        )
        state_file.write_text(json.dumps(data))

        state = load_sprint_state()
        result = get_next_issue_to_process(state)
        assert result is not None
        assert result.key == "AAP-1"

    def test_returns_none_when_empty(self, sprint_files):
        state_file, _ = sprint_files
        state_file.write_text(json.dumps(_make_state_json()))
        result = get_next_issue_to_process()
        assert result is None

    def test_accepts_preloaded_state(self, sprint_files):
        state = SprintState(
            issues=[
                SprintIssue(
                    key="AAP-1",
                    summary="T",
                    approval_status="approved",
                    jira_status="New",
                )
            ]
        )
        result = get_next_issue_to_process(state)
        assert result is not None


# ---------------------------------------------------------------------------
# complete_current_sprint
# ---------------------------------------------------------------------------


class TestCompleteCurrentSprint:
    def test_completes_sprint(self, sprint_files):
        state_file, history_file = sprint_files
        data = _make_state_json(
            current_sprint={"id": "s1", "name": "Sprint 1", "startDate": "2025-01-01"},
            issues=[
                _make_issue_json("AAP-1", approval="completed", points=5),
                _make_issue_json("AAP-2", approval="pending", points=3),
            ],
        )
        state_file.write_text(json.dumps(data))

        result = complete_current_sprint()
        assert result is not None
        assert result.total_points == 8
        assert result.completed_points == 5
        assert len(result.issues) == 2

        # Verify history was saved
        history = json.loads(history_file.read_text())
        assert len(history["sprints"]) == 1

        # Verify state was cleared
        json.loads(state_file.read_text())
        # The safety check preserves issues, so we check the sprint was archived
        assert history["sprints"][0]["id"] == "s1"

    def test_returns_none_when_no_sprint(self, sprint_files):
        state_file, _ = sprint_files
        data = _make_state_json(current_sprint=None)
        state_file.write_text(json.dumps(data))

        result = complete_current_sprint()
        assert result is None
