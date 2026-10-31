"""Tests for Cursor chat content scanning (server.cursor_chat_scan)."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from server.workspace_state import (
    ChatSession,
    format_session_context_for_jira,
    get_cursor_chat_content,
    get_cursor_chat_issue_keys,
    get_cursor_chat_personas,
    get_cursor_chat_projects,
    get_meeting_transcript_issue_keys,
)


def _conn_returning(rows: list[tuple]) -> MagicMock:
    """A mock sqlite3 connection whose execute().fetchall() returns ``rows``."""
    conn = MagicMock(spec=sqlite3.Connection)
    conn.execute.return_value.fetchall.return_value = rows
    return conn


@contextmanager
def _meetings_db(rows_or_error: list[tuple] | sqlite3.Error) -> Iterator[None]:
    """Point the meet bot DB at an existing file backed by a mocked connection."""
    if isinstance(rows_or_error, sqlite3.Error):
        connect = patch("sqlite3.connect", side_effect=rows_or_error)
    else:
        connect = patch("sqlite3.connect", return_value=_conn_returning(rows_or_error))
    db_file = MagicMock(spec=Path)
    db_file.exists.return_value = True
    with patch("server.paths.MEETINGS_DB_FILE", new=db_file), connect:
        yield


class TestFormatSessionContextForJira:
    """Tests for format_session_context_for_jira function."""

    def test_minimal_content(self):
        """Format with minimal chat content and no session."""
        chat_content = {
            "summary": {
                "user_messages": 2,
                "assistant_messages": 3,
                "tool_calls": 1,
                "code_changes": 0,
                "issue_keys": [],
            },
            "messages": [],
        }
        result = format_session_context_for_jira(chat_content)
        assert "{panel:" in result
        assert "Messages:*" in result
        assert "{panel}" in result

    def test_with_session_metadata(self):
        """Format includes session metadata."""
        session = ChatSession(
            session_id="abcdef1234567890",
            workspace_uri="file:///test",
            persona="developer",
            project="my-project",
            branch="feature-123",
        )
        chat_content = {
            "summary": {
                "user_messages": 5,
                "assistant_messages": 5,
                "tool_calls": 3,
                "code_changes": 2,
                "issue_keys": ["AAP-12345"],
            },
            "messages": [],
        }
        result = format_session_context_for_jira(chat_content, session=session)
        assert "Session ID:*" in result
        assert "developer" in result
        assert "my-project" in result
        assert "feature-123" in result
        assert "AAP-12345" in result

    def test_with_key_actions(self):
        """Format extracts key actions from assistant tool results."""
        chat_content = {
            "summary": dict.fromkeys(("user_messages", "assistant_messages", "tool_calls", "code_changes"), 0)
            | {"issue_keys": []},
            "messages": [
                {
                    "type": "assistant",
                    "text": "Done",
                    "tool_results": ["Successfully deployed to stage environment with pod replicas=3"],
                },
            ],
        }
        result = format_session_context_for_jira(chat_content)
        assert "Key Actions" in result
        assert "Successfully deployed" in result

    def test_with_transcript(self):
        """Format includes transcript when requested."""
        chat_content = {
            "summary": {
                "user_messages": 1,
                "assistant_messages": 1,
                "tool_calls": 0,
                "code_changes": 0,
                "issue_keys": [],
            },
            "messages": [
                {
                    "type": "user",
                    "text": "Check the pods",
                    "timestamp": "2025-01-15T10:00:00",
                },
                {
                    "type": "assistant",
                    "text": "Checking pods now",
                    "timestamp": "2025-01-15T10:00:05",
                },
            ],
        }
        result = format_session_context_for_jira(chat_content, include_transcript=True)
        assert "{expand:Full Transcript}" in result
        assert "USER:" in result
        assert "ASSISTANT:" in result

    def test_transcript_truncation(self):
        """Transcript is truncated at max_transcript_chars."""
        messages = [
            {
                "type": "user",
                "text": "x" * 400,
                "timestamp": f"2025-01-15T10:{i:02d}:00",
            }
            for i in range(20)
        ]
        chat_content = {
            "summary": {
                "user_messages": 20,
                "assistant_messages": 0,
                "tool_calls": 0,
                "code_changes": 0,
                "issue_keys": [],
            },
            "messages": messages,
        }
        result = format_session_context_for_jira(chat_content, include_transcript=True, max_transcript_chars=500)
        assert "... (truncated)" in result

    def test_session_duration_calculation(self):
        """Format calculates session duration."""
        session = ChatSession(
            session_id="abcdef1234567890",
            workspace_uri="file:///test",
        )
        session.started_at = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        session.last_activity = datetime(2025, 1, 15, 10, 45, tzinfo=timezone.utc)

        chat_content = {
            "summary": dict.fromkeys(("user_messages", "assistant_messages", "tool_calls", "code_changes"), 0)
            | {"issue_keys": []},
            "messages": [],
        }
        result = format_session_context_for_jira(chat_content, session=session)
        assert "~45 minutes" in result


class TestGetCursorChatIssueKeysDetailed:
    """Detailed tests for get_cursor_chat_issue_keys with mocked sqlite3."""

    def test_finds_issue_keys_in_chat(self):
        """Finds AAP-XXXXX patterns in chat content."""
        mock_conn = MagicMock(spec=sqlite3.Connection)
        mock_cursor = MagicMock(spec=sqlite3.Cursor)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            (
                "bubbleId:chat1:1",
                json.dumps({"text": "Working on AAP-12345 and AAP-12346"}),
            ),
            ("bubbleId:chat1:2", json.dumps({"text": "Also see aap-12347"})),
        ]

        with patch("pathlib.Path.exists", return_value=True), patch("sqlite3.connect", return_value=mock_conn):
            result = get_cursor_chat_issue_keys(["chat1"])

        assert "chat1" in result
        assert "AAP-12345" in result["chat1"]
        assert "AAP-12346" in result["chat1"]
        assert "AAP-12347" in result["chat1"]

    def test_handles_sqlite_error(self):
        """Handles sqlite3 connection error gracefully."""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("sqlite3.connect", side_effect=sqlite3.Error("DB locked")),
        ):
            result = get_cursor_chat_issue_keys(["chat1"])
            assert not result

    def test_handles_invalid_json_in_value(self):
        """Handles invalid JSON in database values."""
        mock_conn = MagicMock(spec=sqlite3.Connection)
        mock_cursor = MagicMock(spec=sqlite3.Cursor)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("bubbleId:chat1:1", "not valid json"),
        ]

        with patch("pathlib.Path.exists", return_value=True), patch("sqlite3.connect", return_value=mock_conn):
            result = get_cursor_chat_issue_keys(["chat1"])
            assert not result

    def test_sorts_issue_keys_numerically(self):
        """Issue keys are sorted by numeric part."""
        mock_conn = MagicMock(spec=sqlite3.Connection)
        mock_cursor = MagicMock(spec=sqlite3.Cursor)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            (
                "bubbleId:chat1:1",
                json.dumps({"text": "AAP-99999 and AAP-10000 and AAP-50000"}),
            ),
        ]

        with patch("pathlib.Path.exists", return_value=True), patch("sqlite3.connect", return_value=mock_conn):
            result = get_cursor_chat_issue_keys(["chat1"])
            assert result["chat1"] == "AAP-10000, AAP-50000, AAP-99999"

    def test_handles_per_chat_sqlite_error(self):
        """Handles sqlite3 error for individual chat query."""
        mock_conn = MagicMock(spec=sqlite3.Connection)
        mock_cursor = MagicMock(spec=sqlite3.Cursor)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = sqlite3.Error("query failed")

        with patch("pathlib.Path.exists", return_value=True), patch("sqlite3.connect", return_value=mock_conn):
            result = get_cursor_chat_issue_keys(["chat1"])
            assert not result


class TestGetCursorChatContentDetailed:
    """Tests for get_cursor_chat_content with a mocked sqlite3 connection."""

    def test_valid_uuid_no_db(self):
        """Returns empty result when global DB doesn't exist."""
        with patch("pathlib.Path.exists", return_value=False):
            result = get_cursor_chat_content("12345678-1234-5678-1234-567812345678")
            assert result["message_count"] == 0

    def test_valid_uuid_db_query_fails(self):
        """Returns empty result when DB query fails."""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("sqlite3.connect", side_effect=sqlite3.OperationalError("no such table: cursorDiskKV")),
        ):
            result = get_cursor_chat_content("12345678-1234-5678-1234-567812345678")
            assert result["message_count"] == 0

    def test_query_is_parameterised(self):
        """The chat id is bound as a LIKE parameter, never formatted into the SQL."""
        conn = _conn_returning([])
        with patch("pathlib.Path.exists", return_value=True), patch("sqlite3.connect", return_value=conn):
            get_cursor_chat_content("12345678-1234-5678-1234-567812345678")
        sql, params = conn.execute.call_args.args
        assert "?" in sql
        assert "12345678" not in sql
        assert params == ("bubbleId:12345678-1234-5678-1234-567812345678:%",)
        conn.close.assert_called_once()

    def test_parses_messages(self):
        """Parses user and assistant messages from DB rows."""
        bid = "bubbleId:12345678-1234-5678-1234-567812345678"
        msg1 = json.dumps({"type": 1, "text": "Hello", "createdAt": 1700000000000})
        msg2 = json.dumps({"type": 2, "text": "Hi there! AAP-12345", "createdAt": 1700000001000})
        conn = _conn_returning([(f"{bid}:1", msg1), (f"{bid}:2", msg2)])

        with patch("pathlib.Path.exists", return_value=True), patch("sqlite3.connect", return_value=conn):
            result = get_cursor_chat_content("12345678-1234-5678-1234-567812345678")

        assert result["message_count"] == 2
        assert result["summary"]["user_messages"] == 1
        assert result["summary"]["assistant_messages"] == 1
        assert "AAP-12345" in result["summary"]["issue_keys"]

    def test_handles_tool_results_and_code_chunks(self):
        """Parses tool results and code chunks from messages."""
        msg_data = {
            "type": 2,
            "text": "Done",
            "createdAt": 1700000000000,
            "toolResults": [{"result": "Success: deployed to stage"}],
            "attachedCodeChunks": [{"filePath": "/src/main.py"}],
        }
        conn = _conn_returning([("bubbleId:12345678-1234-5678-1234-567812345678:1", json.dumps(msg_data))])

        with patch("pathlib.Path.exists", return_value=True), patch("sqlite3.connect", return_value=conn):
            result = get_cursor_chat_content("12345678-1234-5678-1234-567812345678")

        assert result["summary"]["tool_calls"] == 1
        assert result["summary"]["code_changes"] == 1

    def test_handles_locked_db(self):
        """Handles a locked database gracefully."""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("sqlite3.connect", side_effect=sqlite3.OperationalError("database is locked")),
        ):
            result = get_cursor_chat_content("12345678-1234-5678-1234-567812345678")
            assert result["message_count"] == 0

    def test_handles_malformed_rows(self):
        """Skips rows with empty or non-JSON values."""
        conn = _conn_returning([("bubbleId:x:1", ""), ("bubbleId:x:2", "not json")])

        with patch("pathlib.Path.exists", return_value=True), patch("sqlite3.connect", return_value=conn):
            result = get_cursor_chat_content("12345678-1234-5678-1234-567812345678")
            assert result["message_count"] == 0

    def test_max_messages_limit(self):
        """Respects max_messages limit."""
        rows = []
        for i in range(10):
            msg = json.dumps({"type": 1, "text": f"msg {i}", "createdAt": 1700000000000 + i * 1000})
            rows.append((f"bubbleId:12345678-1234-5678-1234-567812345678:{i}", msg))
        conn = _conn_returning(rows)

        with patch("pathlib.Path.exists", return_value=True), patch("sqlite3.connect", return_value=conn):
            result = get_cursor_chat_content("12345678-1234-5678-1234-567812345678", max_messages=3)
            assert len(result["messages"]) == 3
            assert result["message_count"] == 10

    def test_handles_general_db_error(self):
        """Handles a generic sqlite3 error."""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("sqlite3.connect", side_effect=sqlite3.DatabaseError("file is not a database")),
        ):
            result = get_cursor_chat_content("12345678-1234-5678-1234-567812345678")
            assert result["message_count"] == 0


class TestGetCursorChatPersonasDetailed:
    """Tests for get_cursor_chat_personas with mocked sqlite3."""

    def test_detects_persona_load_call(self):
        """Detects persona from persona_load('developer') call."""
        mock_conn = MagicMock(spec=sqlite3.Connection)
        mock_cursor = MagicMock(spec=sqlite3.Cursor)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("bubbleId:chat1:5", json.dumps({"text": 'persona_load("developer")'})),
        ]

        with patch("pathlib.Path.exists", return_value=True), patch("sqlite3.connect", return_value=mock_conn):
            result = get_cursor_chat_personas(["chat1"])

        assert result.get("chat1") == "developer"

    def test_detects_agent_parameter(self):
        """Detects persona from agent='devops' in session_start."""
        mock_conn = MagicMock(spec=sqlite3.Connection)
        mock_cursor = MagicMock(spec=sqlite3.Cursor)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("bubbleId:chat1:3", json.dumps({"text": 'session_start(agent="devops")'})),
        ]

        with patch("pathlib.Path.exists", return_value=True), patch("sqlite3.connect", return_value=mock_conn):
            result = get_cursor_chat_personas(["chat1"])

        assert result.get("chat1") == "devops"

    def test_returns_last_persona(self):
        """Returns the last persona loaded (highest bubble_id)."""
        mock_conn = MagicMock(spec=sqlite3.Connection)
        mock_cursor = MagicMock(spec=sqlite3.Cursor)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("bubbleId:chat1:1", json.dumps({"text": 'persona_load("developer")'})),
            ("bubbleId:chat1:5", json.dumps({"text": 'persona_load("devops")'})),
        ]

        with patch("pathlib.Path.exists", return_value=True), patch("sqlite3.connect", return_value=mock_conn):
            result = get_cursor_chat_personas(["chat1"])

        assert result.get("chat1") == "devops"

    def test_ignores_invalid_personas(self):
        """Ignores persona names not in VALID_PERSONAS."""
        mock_conn = MagicMock(spec=sqlite3.Connection)
        mock_cursor = MagicMock(spec=sqlite3.Cursor)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            (
                "bubbleId:chat1:1",
                json.dumps({"text": 'persona_load("invalidpersona")'}),
            ),
        ]

        with patch("pathlib.Path.exists", return_value=True), patch("sqlite3.connect", return_value=mock_conn):
            result = get_cursor_chat_personas(["chat1"])

        assert "chat1" not in result

    def test_handles_sqlite_error(self):
        """Handles sqlite3 connection error."""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("sqlite3.connect", side_effect=sqlite3.Error("locked")),
        ):
            result = get_cursor_chat_personas(["chat1"])
            assert not result

    def test_handles_empty_text(self):
        """Handles entries with empty text field."""
        mock_conn = MagicMock(spec=sqlite3.Connection)
        mock_cursor = MagicMock(spec=sqlite3.Cursor)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("bubbleId:chat1:1", json.dumps({"text": ""})),
        ]

        with patch("pathlib.Path.exists", return_value=True), patch("sqlite3.connect", return_value=mock_conn):
            result = get_cursor_chat_personas(["chat1"])
            assert "chat1" not in result

    def test_handles_per_chat_sqlite_error(self):
        """Handles sqlite3 error for individual chat query."""
        mock_conn = MagicMock(spec=sqlite3.Connection)
        mock_cursor = MagicMock(spec=sqlite3.Cursor)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = sqlite3.Error("query failed")

        with patch("pathlib.Path.exists", return_value=True), patch("sqlite3.connect", return_value=mock_conn):
            result = get_cursor_chat_personas(["chat1"])
            assert not result


class TestGetCursorChatProjectsDetailed:
    """Tests for get_cursor_chat_projects with mocked sqlite3."""

    def test_detects_project_from_session_start(self):
        """Detects project from session_start(project='backend') call."""
        mock_conn = MagicMock(spec=sqlite3.Connection)
        mock_cursor = MagicMock(spec=sqlite3.Cursor)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            (
                "bubbleId:chat1:1",
                json.dumps({"text": 'project="automation-analytics-backend"'}),
            ),
        ]

        mock_config = {
            "repositories": {
                "automation-analytics-backend": {"path": "/home/user/aab"},
            }
        }

        with (
            patch("server.utils.load_config", return_value=mock_config),
            patch("pathlib.Path.exists", return_value=True),
            patch("sqlite3.connect", return_value=mock_conn),
        ):
            result = get_cursor_chat_projects(["chat1"])

        assert result.get("chat1") == "automation-analytics-backend"

    def test_skips_redhat_ai_workflow(self):
        """Skips 'redhat-ai-workflow' as it's the default workspace."""
        mock_conn = MagicMock(spec=sqlite3.Connection)
        mock_cursor = MagicMock(spec=sqlite3.Cursor)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("bubbleId:chat1:1", json.dumps({"text": 'project="redhat-ai-workflow"'})),
        ]

        mock_config = {
            "repositories": {
                "redhat-ai-workflow": {"path": "/home/user/raw"},
            }
        }

        with (
            patch("server.utils.load_config", return_value=mock_config),
            patch("pathlib.Path.exists", return_value=True),
            patch("sqlite3.connect", return_value=mock_conn),
        ):
            result = get_cursor_chat_projects(["chat1"])

        assert "chat1" not in result

    def test_handles_sqlite_error(self):
        """Handles sqlite3 connection error."""
        mock_config = {"repositories": {"proj": {"path": "/p"}}}
        with (
            patch("server.utils.load_config", return_value=mock_config),
            patch("pathlib.Path.exists", return_value=True),
            patch("sqlite3.connect", side_effect=sqlite3.Error("locked")),
        ):
            result = get_cursor_chat_projects(["chat1"])
            assert not result

    def test_config_load_failure_uses_fallback(self):
        """Falls back to hardcoded project list when config fails."""
        mock_conn = MagicMock(spec=sqlite3.Connection)
        mock_cursor = MagicMock(spec=sqlite3.Cursor)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("bubbleId:chat1:1", json.dumps({"text": 'project="pdf-generator"'})),
        ]

        with (
            patch("server.utils.load_config", side_effect=OSError("config error")),
            patch("pathlib.Path.exists", return_value=True),
            patch("sqlite3.connect", return_value=mock_conn),
        ):
            result = get_cursor_chat_projects(["chat1"])

        assert result.get("chat1") == "pdf-generator"


class TestGetMeetingTranscriptIssueKeys:
    """Tests for get_meeting_transcript_issue_keys."""

    def test_db_not_found(self):
        """Returns empty when meet bot DB doesn't exist."""
        with patch(
            "server.paths.MEETINGS_DB_FILE",
            new=Path("/nonexistent/db.sqlite"),
            create=True,
        ):
            result = get_meeting_transcript_issue_keys()
            assert not result

    def test_finds_standard_pattern(self):
        """Finds AAP-XXXXX pattern in transcripts."""
        with _meetings_db([(1, "Discussing AAP-12345 today", "Sprint Planning", "2025-01-20T10:00:00")]):
            result = get_meeting_transcript_issue_keys()

        assert "AAP-12345" in result
        assert result["AAP-12345"][0]["meeting_id"] == 1
        assert result["AAP-12345"][0]["title"] == "Sprint Planning"
        assert result["AAP-12345"][0]["date"] == "2025-01-20"

    def test_finds_spoken_pattern(self):
        """Finds spoken patterns like 'issue 12345' or 'ticket 12345'."""
        rows = [
            (1, "Let's talk about issue 12345", "Standup", "2025-01-20"),
            (2, "ticket 67890 is blocked", "Standup", "2025-01-21"),
        ]
        with _meetings_db(rows):
            result = get_meeting_transcript_issue_keys()

        assert "AAP-12345" in result
        assert "AAP-67890" in result

    def test_filters_by_issue_keys(self):
        """Filters results to specific issue keys when provided."""
        with _meetings_db([(1, "AAP-12345 and AAP-99999", "Meeting", "2025-01-20")]):
            result = get_meeting_transcript_issue_keys(issue_keys=["AAP-12345"])

        assert "AAP-12345" in result
        assert "AAP-99999" not in result

    def test_handles_query_failure(self):
        """Handles a sqlite3 query failure gracefully."""
        with _meetings_db(sqlite3.OperationalError("no such table: transcripts")):
            result = get_meeting_transcript_issue_keys()
            assert not result

    def test_handles_locked_db(self):
        """Handles a locked database."""
        with _meetings_db(sqlite3.OperationalError("database is locked")):
            result = get_meeting_transcript_issue_keys()
            assert not result

    def test_handles_malformed_rows(self):
        """Skips rows with too few columns or a non-numeric meeting id."""
        with _meetings_db([(1, "only two parts"), ("abc", "AAP-12345", "T", "2025-01-20")]):
            result = get_meeting_transcript_issue_keys()
            assert not result

    def test_handles_null_columns(self):
        """NULL text/title/start columns are treated as empty."""
        with _meetings_db([(1, None, None, None), (2, "AAP-12345", None, None)]):
            result = get_meeting_transcript_issue_keys()
        assert result["AAP-12345"][0] == {"meeting_id": 2, "title": "", "date": "", "matches": 1}

    def test_aggregates_matches_across_entries(self):
        """Aggregates match counts across transcript entries."""
        rows = [
            (1, "AAP-12345 mentioned here", "Sprint", "2025-01-20"),
            (1, "AAP-12345 mentioned again", "Sprint", "2025-01-20"),
        ]
        with _meetings_db(rows):
            result = get_meeting_transcript_issue_keys()

        assert "AAP-12345" in result
        assert result["AAP-12345"][0]["matches"] == 2
