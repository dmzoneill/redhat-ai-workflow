"""Tests for WorkspaceState.sync_with_cursor_db."""

from datetime import datetime, timezone
from unittest.mock import patch

from server.workspace_state import (
    ChatSession,
    WorkspaceRegistry,
    WorkspaceState,
    get_default_persona,
)


class TestSyncWithCursorDb:
    """Tests for WorkspaceState.sync_with_cursor_db."""

    def setup_method(self):
        """Start from an empty registry."""
        WorkspaceRegistry.clear()

    def teardown_method(self):
        """Leave an empty registry behind."""
        WorkspaceRegistry.clear()

    def test_sync_adds_new_sessions(self):
        """sync_with_cursor_db adds sessions from Cursor not in our registry."""
        state = WorkspaceState(workspace_uri="file:///test")

        cursor_chats = [
            {
                "composerId": "chat1",
                "name": "Chat One",
                "lastUpdatedAt": 1700000000000,
                "createdAt": 1700000000000,
            },
        ]
        with (
            patch(
                "server.cursor_chat_db.list_cursor_chats",
                return_value=(cursor_chats, "chat1"),
            ),
            patch("server.cursor_chat_scan.get_cursor_chat_issue_keys", return_value={}),
            patch("server.cursor_chat_scan.get_cursor_chat_personas", return_value={}),
            patch(
                "server.cursor_chat_scan.get_cursor_chat_projects",
                return_value={},
            ),
            patch(
                "server.cursor_chat_scan.get_meeting_transcript_issue_keys",
                return_value={},
            ),
            patch("server.workspace_model.loaded_tool_names", return_value=set()),
        ):
            result = state.sync_with_cursor_db(skip_content_scan=True)

        assert result["added"] == 1
        assert state.get_session("chat1") is not None
        assert state.get_session("chat1").name == "Chat One"

    def test_sync_removes_deleted_sessions(self):
        """sync_with_cursor_db removes sessions no longer in Cursor."""
        state = WorkspaceState(workspace_uri="file:///test")
        # Add a session manually
        session = ChatSession(session_id="old-session", workspace_uri="file:///test")
        state.sessions["old-session"] = session
        state.active_session_id = "old-session"

        # Cursor has no chats
        with (
            patch("server.cursor_chat_db.list_cursor_chats", return_value=([], None)),
            patch("server.workspace_model.loaded_tool_names", return_value=set()),
        ):
            result = state.sync_with_cursor_db(skip_content_scan=True)

        assert result["removed"] == 1
        assert state.get_session("old-session") is None
        assert state.active_session_id is None

    def test_sync_renames_sessions(self):
        """sync_with_cursor_db updates names when Cursor's name changes."""
        state = WorkspaceState(workspace_uri="file:///test")
        session = ChatSession(session_id="s1", workspace_uri="file:///test", name="Old Name")
        state.sessions["s1"] = session
        state.active_session_id = "s1"

        cursor_chats = [
            {"composerId": "s1", "name": "New Name", "lastUpdatedAt": None},
        ]
        with (
            patch(
                "server.cursor_chat_db.list_cursor_chats",
                return_value=(cursor_chats, None),
            ),
            patch("server.workspace_model.loaded_tool_names", return_value=set()),
        ):
            result = state.sync_with_cursor_db(skip_content_scan=True)

        assert result["renamed"] == 1
        assert session.name == "New Name"

    def test_sync_clears_unnamed_placeholder(self):
        """sync_with_cursor_db clears 'unnamed' placeholder name."""
        state = WorkspaceState(workspace_uri="file:///test")
        session = ChatSession(session_id="s1", workspace_uri="file:///test", name="unnamed")
        state.sessions["s1"] = session

        cursor_chats = [
            {"composerId": "s1", "name": None, "lastUpdatedAt": None},
        ]
        with (
            patch(
                "server.cursor_chat_db.list_cursor_chats",
                return_value=(cursor_chats, None),
            ),
            patch("server.workspace_model.loaded_tool_names", return_value=set()),
        ):
            result = state.sync_with_cursor_db(skip_content_scan=True)

        assert result["renamed"] == 1
        assert session.name is None

    def test_sync_updates_active_from_cursor(self):
        """sync_with_cursor_db updates active session from Cursor."""
        state = WorkspaceState(workspace_uri="file:///test")
        s1 = ChatSession(session_id="s1", workspace_uri="file:///test")
        s2 = ChatSession(session_id="s2", workspace_uri="file:///test")
        state.sessions["s1"] = s1
        state.sessions["s2"] = s2
        state.active_session_id = "s1"

        cursor_chats = [
            {"composerId": "s1", "name": None, "lastUpdatedAt": None},
            {"composerId": "s2", "name": None, "lastUpdatedAt": None},
        ]
        with (
            patch(
                "server.cursor_chat_db.list_cursor_chats",
                return_value=(cursor_chats, "s2"),
            ),
            patch("server.workspace_model.loaded_tool_names", return_value=set()),
        ):
            state.sync_with_cursor_db(skip_content_scan=True)

        assert state.active_session_id == "s2"

    def test_sync_extracts_issue_from_name(self):
        """sync_with_cursor_db extracts issue keys from chat names."""
        state = WorkspaceState(workspace_uri="file:///test")

        cursor_chats = [
            {
                "composerId": "c1",
                "name": "Fix AAP-12345 billing bug",
                "lastUpdatedAt": 1700000000000,
                "createdAt": 1700000000000,
            },
        ]
        with (
            patch(
                "server.cursor_chat_db.list_cursor_chats",
                return_value=(cursor_chats, None),
            ),
            patch(
                "server.cursor_chat_scan.get_meeting_transcript_issue_keys",
                return_value={},
            ),
            patch("server.workspace_model.loaded_tool_names", return_value=set()),
        ):
            state.sync_with_cursor_db(skip_content_scan=True)

        session = state.get_session("c1")
        assert session.issue_key == "AAP-12345"

    def test_sync_with_content_scan(self):
        """sync_with_cursor_db runs content scan when session_ids provided."""
        state = WorkspaceState(workspace_uri="file:///test")
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        state.sessions["s1"] = session

        cursor_chats = [
            {"composerId": "s1", "name": None, "lastUpdatedAt": None},
        ]
        with (
            patch(
                "server.cursor_chat_db.list_cursor_chats",
                return_value=(cursor_chats, None),
            ),
            patch(
                "server.cursor_chat_scan.get_cursor_chat_issue_keys",
                return_value={"s1": "AAP-100"},
            ) as mock_issues,
            patch(
                "server.cursor_chat_scan.get_cursor_chat_personas",
                return_value={"s1": "developer"},
            ) as mock_personas,
            patch(
                "server.cursor_chat_scan.get_cursor_chat_projects",
                return_value={},
            ) as mock_projects,
            patch(
                "server.cursor_chat_scan.get_meeting_transcript_issue_keys",
                return_value={},
            ),
            patch("server.workspace_model.loaded_tool_names", return_value=set()),
        ):
            state.sync_with_cursor_db(session_ids=["s1"])

        # Content scanning functions should be called
        mock_issues.assert_called_once_with(["s1"])
        mock_personas.assert_called_once_with(["s1"])
        mock_projects.assert_called_once_with(["s1"])
        assert True

    def test_sync_updates_tool_count_for_active(self):
        """sync_with_cursor_db updates tool count for active session."""
        state = WorkspaceState(workspace_uri="file:///test")
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        session.static_tool_count = 5
        state.sessions["s1"] = session
        state.active_session_id = "s1"

        cursor_chats = [
            {"composerId": "s1", "name": None, "lastUpdatedAt": None},
        ]
        with (
            patch(
                "server.cursor_chat_db.list_cursor_chats",
                return_value=(cursor_chats, None),
            ),
            patch(
                "server.cursor_chat_scan.get_meeting_transcript_issue_keys",
                return_value={},
            ),
            patch("server.workspace_model.loaded_tool_names", return_value=set(range(30))),
        ):
            # Return 30 tools (simulating more tools loaded)
            state.sync_with_cursor_db(skip_content_scan=True)

        assert session.static_tool_count == 30

    def test_sync_updates_persona_from_content(self):
        """sync_with_cursor_db updates persona from chat content."""
        state = WorkspaceState(workspace_uri="file:///test")
        default_persona = get_default_persona()
        session = ChatSession(session_id="s1", workspace_uri="file:///test", persona=default_persona)
        state.sessions["s1"] = session

        cursor_chats = [
            {"composerId": "s1", "name": None, "lastUpdatedAt": None},
        ]
        with (
            patch(
                "server.cursor_chat_db.list_cursor_chats",
                return_value=(cursor_chats, None),
            ),
            patch("server.cursor_chat_scan.get_cursor_chat_issue_keys", return_value={}),
            patch(
                "server.cursor_chat_scan.get_cursor_chat_personas",
                return_value={"s1": "developer"},
            ),
            patch(
                "server.cursor_chat_scan.get_cursor_chat_projects",
                return_value={},
            ),
            patch(
                "server.cursor_chat_scan.get_meeting_transcript_issue_keys",
                return_value={},
            ),
            patch(
                "server.workspace_defaults.get_persona_tool_count",
                return_value=25,
            ),
            patch("server.workspace_model.loaded_tool_names", return_value=set()),
        ):
            state.sync_with_cursor_db(session_ids=["s1"])

        assert session.persona == "developer"

    def test_sync_updates_project_from_content(self):
        """sync_with_cursor_db updates project from chat content."""
        state = WorkspaceState(workspace_uri="file:///test")
        session = ChatSession(
            session_id="s1",
            workspace_uri="file:///test",
            project="default-proj",
            is_project_auto_detected=True,
        )
        state.sessions["s1"] = session

        cursor_chats = [
            {"composerId": "s1", "name": None, "lastUpdatedAt": None},
        ]
        with (
            patch(
                "server.cursor_chat_db.list_cursor_chats",
                return_value=(cursor_chats, None),
            ),
            patch("server.cursor_chat_scan.get_cursor_chat_issue_keys", return_value={}),
            patch("server.cursor_chat_scan.get_cursor_chat_personas", return_value={}),
            patch(
                "server.cursor_chat_scan.get_cursor_chat_projects",
                return_value={"s1": "specific-proj"},
            ),
            patch(
                "server.cursor_chat_scan.get_meeting_transcript_issue_keys",
                return_value={},
            ),
            patch("server.workspace_model.loaded_tool_names", return_value=set()),
        ):
            state.sync_with_cursor_db(session_ids=["s1"])

        assert session.project == "specific-proj"
        assert session.is_project_auto_detected is False

    def test_sync_meeting_references(self):
        """sync_with_cursor_db updates meeting references for sessions."""
        state = WorkspaceState(workspace_uri="file:///test")
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        session.issue_key = "AAP-123"
        state.sessions["s1"] = session

        cursor_chats = [
            {"composerId": "s1", "name": None, "lastUpdatedAt": None},
        ]
        meeting_refs = {
            "AAP-123": [
                {
                    "meeting_id": 1,
                    "title": "Sprint Planning",
                    "date": "2025-01-20",
                    "matches": 3,
                },
            ]
        }
        with (
            patch(
                "server.cursor_chat_db.list_cursor_chats",
                return_value=(cursor_chats, None),
            ),
            patch(
                "server.cursor_chat_scan.get_meeting_transcript_issue_keys",
                return_value=meeting_refs,
            ),
            patch("server.workspace_model.loaded_tool_names", return_value=set()),
        ):
            state.sync_with_cursor_db(skip_content_scan=True)

        assert len(session.meeting_references) == 1
        assert session.meeting_references[0]["meeting_id"] == 1


class TestSyncWithCursorDbAdvanced:
    """Additional sync_with_cursor_db tests for branch coverage."""

    def setup_method(self):
        """Start from an empty registry."""
        WorkspaceRegistry.clear()

    def teardown_method(self):
        """Leave an empty registry behind."""
        WorkspaceRegistry.clear()

    def test_sync_updates_last_activity_from_cursor(self):
        """sync_with_cursor_db updates session last_activity from Cursor timestamp."""
        state = WorkspaceState(workspace_uri="file:///test")
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        session.last_activity = datetime(2020, 1, 1, tzinfo=timezone.utc)
        state.sessions["s1"] = session

        cursor_chats = [
            {"composerId": "s1", "name": None, "lastUpdatedAt": 1700000000000},
        ]
        with (
            patch(
                "server.cursor_chat_db.list_cursor_chats",
                return_value=(cursor_chats, None),
            ),
            patch(
                "server.cursor_chat_scan.get_meeting_transcript_issue_keys",
                return_value={},
            ),
            patch("server.workspace_model.loaded_tool_names", return_value=set()),
        ):
            result = state.sync_with_cursor_db(skip_content_scan=True)

        assert result["updated"] == 1
        assert session.last_activity > datetime(2020, 1, 1, tzinfo=timezone.utc)

    def test_sync_updates_zero_tool_count_from_cache(self):
        """sync_with_cursor_db updates tool count from persona cache when zero."""
        state = WorkspaceState(workspace_uri="file:///test")
        session = ChatSession(session_id="s1", workspace_uri="file:///test", persona="devops")
        session.static_tool_count = 0
        state.sessions["s1"] = session
        # Not active session
        state.active_session_id = None

        cursor_chats = [
            {"composerId": "s1", "name": None, "lastUpdatedAt": None},
        ]
        with (
            patch(
                "server.cursor_chat_db.list_cursor_chats",
                return_value=(cursor_chats, None),
            ),
            patch(
                "server.cursor_chat_scan.get_meeting_transcript_issue_keys",
                return_value={},
            ),
            patch("server.workspace_defaults.get_persona_tool_count", return_value=15),
            patch("server.workspace_model.loaded_tool_names", return_value=set()),
        ):
            result = state.sync_with_cursor_db(skip_content_scan=True)

        assert session.static_tool_count == 15
        assert result["updated"] == 1

    def test_sync_aggregates_meeting_matches(self):
        """sync_with_cursor_db aggregates match counts when same meeting appears for multiple issue keys."""
        state = WorkspaceState(workspace_uri="file:///test")
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        session.issue_key = "AAP-100, AAP-200"
        state.sessions["s1"] = session

        cursor_chats = [{"composerId": "s1", "name": None, "lastUpdatedAt": None}]
        meeting_refs = {
            "AAP-100": [{"meeting_id": 1, "title": "Sprint", "date": "2025-01-20", "matches": 2}],
            "AAP-200": [{"meeting_id": 1, "title": "Sprint", "date": "2025-01-20", "matches": 3}],
        }
        with (
            patch(
                "server.cursor_chat_db.list_cursor_chats",
                return_value=(cursor_chats, None),
            ),
            patch(
                "server.cursor_chat_scan.get_meeting_transcript_issue_keys",
                return_value=meeting_refs,
            ),
            patch("server.workspace_model.loaded_tool_names", return_value=set()),
        ):
            state.sync_with_cursor_db(skip_content_scan=True)

        assert len(session.meeting_references) == 1
        assert session.meeting_references[0]["matches"] == 5  # 2 + 3

    def test_sync_adds_session_with_detected_persona_and_project(self):
        """sync_with_cursor_db detects persona and project for new sessions."""
        state = WorkspaceState(workspace_uri="file:///test")

        cursor_chats = [
            {
                "composerId": "c1",
                "name": "Chat",
                "lastUpdatedAt": 1700000000000,
                "createdAt": 1700000000000,
            },
        ]
        with (
            patch(
                "server.cursor_chat_db.list_cursor_chats",
                return_value=(cursor_chats, None),
            ),
            patch("server.cursor_chat_scan.get_cursor_chat_issue_keys", return_value={}),
            patch(
                "server.cursor_chat_scan.get_cursor_chat_personas",
                return_value={"c1": "developer"},
            ),
            patch(
                "server.cursor_chat_scan.get_cursor_chat_projects",
                return_value={"c1": "my-proj"},
            ),
            patch(
                "server.cursor_chat_scan.get_meeting_transcript_issue_keys",
                return_value={},
            ),
            patch(
                "server.workspace_defaults.get_persona_tool_count",
                return_value=30,
            ),
            patch("server.workspace_model.loaded_tool_names", return_value=set()),
        ):
            state.sync_with_cursor_db(session_ids=["c1"])

        session = state.get_session("c1")
        assert session.persona == "developer"
        assert session.project == "my-proj"
        assert session.static_tool_count == 30

    def test_sync_no_changes(self):
        """sync_with_cursor_db returns zeros when nothing changed."""
        state = WorkspaceState(workspace_uri="file:///test")
        session = ChatSession(session_id="s1", workspace_uri="file:///test", name="Same Name")
        state.sessions["s1"] = session
        state.active_session_id = "s1"

        cursor_chats = [
            {"composerId": "s1", "name": "Same Name", "lastUpdatedAt": None},
        ]
        with (
            patch(
                "server.cursor_chat_db.list_cursor_chats",
                return_value=(cursor_chats, "s1"),
            ),
            patch(
                "server.cursor_chat_scan.get_meeting_transcript_issue_keys",
                return_value={},
            ),
            patch("server.workspace_model.loaded_tool_names", return_value=set()),
        ):
            result = state.sync_with_cursor_db(skip_content_scan=True)

        assert result == {"added": 0, "removed": 0, "renamed": 0, "updated": 0}

    def test_sync_merges_issue_keys_from_name_and_content(self):
        """sync_with_cursor_db merges issue keys from both name and content scan."""
        state = WorkspaceState(workspace_uri="file:///test")

        cursor_chats = [
            {
                "composerId": "c1",
                "name": "Fix AAP-11111",
                "lastUpdatedAt": 1700000000000,
                "createdAt": 1700000000000,
            },
        ]
        with (
            patch(
                "server.cursor_chat_db.list_cursor_chats",
                return_value=(cursor_chats, None),
            ),
            patch(
                "server.cursor_chat_scan.get_cursor_chat_issue_keys",
                return_value={"c1": "AAP-22222"},
            ),
            patch("server.cursor_chat_scan.get_cursor_chat_personas", return_value={}),
            patch(
                "server.cursor_chat_scan.get_cursor_chat_projects",
                return_value={},
            ),
            patch(
                "server.cursor_chat_scan.get_meeting_transcript_issue_keys",
                return_value={},
            ),
            patch("server.workspace_model.loaded_tool_names", return_value=set()),
        ):
            state.sync_with_cursor_db(session_ids=["c1"])

        session = state.get_session("c1")
        assert "AAP-11111" in session.issue_key
        assert "AAP-22222" in session.issue_key
