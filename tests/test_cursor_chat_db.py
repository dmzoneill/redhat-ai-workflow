"""Tests for Cursor workspace database access (server.cursor_chat_db)."""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from server.workspace_state import (
    get_cursor_chat_content,
    get_cursor_chat_id_from_db,
    get_cursor_chat_ids,
    get_cursor_chat_info_from_db,
    get_cursor_chat_issue_keys,
    get_cursor_chat_names,
    get_cursor_chat_personas,
    get_cursor_chat_projects,
    get_meeting_transcript_issue_keys,
    inject_context_to_cursor_chat,
    list_cursor_chats,
)


class TestCursorChatFunctions:
    """Tests for Cursor chat scanning functions with mocked file system."""

    def test_get_cursor_chat_issue_keys_no_ids(self):
        """get_cursor_chat_issue_keys returns empty when no IDs provided."""
        assert not get_cursor_chat_issue_keys(None)
        assert not get_cursor_chat_issue_keys([])

    def test_get_cursor_chat_issue_keys_no_db(self):
        """get_cursor_chat_issue_keys returns empty when db doesn't exist."""
        with (
            patch("pathlib.Path.home", return_value=Path("/fake/home")),
            patch("pathlib.Path.exists", return_value=False),
        ):
            result = get_cursor_chat_issue_keys(["chat1"])
            assert not result

    def test_get_cursor_chat_personas_no_ids(self):
        """get_cursor_chat_personas returns empty when no IDs provided."""
        assert not get_cursor_chat_personas(None)
        assert not get_cursor_chat_personas([])

    def test_get_cursor_chat_personas_no_db(self):
        """get_cursor_chat_personas returns empty when db doesn't exist."""
        with (
            patch("pathlib.Path.home", return_value=Path("/fake/home")),
            patch("pathlib.Path.exists", return_value=False),
        ):
            result = get_cursor_chat_personas(["chat1"])
            assert not result

    def test_get_cursor_chat_projects_no_ids(self):
        """get_cursor_chat_projects returns empty when no IDs provided."""
        assert not get_cursor_chat_projects(None)
        assert not get_cursor_chat_projects([])

    def test_get_cursor_chat_projects_no_db(self):
        """get_cursor_chat_projects returns empty when db doesn't exist."""
        with (
            patch(
                "server.utils.load_config",
                return_value={"repositories": {"proj": {"path": "/p"}}},
            ),
            patch("pathlib.Path.home", return_value=Path("/fake/home")),
            patch("pathlib.Path.exists", return_value=False),
        ):
            result = get_cursor_chat_projects(["chat1"])
            assert not result

    def test_get_cursor_chat_projects_empty_valid_projects(self):
        """get_cursor_chat_projects returns empty when no valid projects."""
        with patch("server.utils.load_config", return_value={"repositories": {}}):
            result = get_cursor_chat_projects(["chat1"])
            assert not result

    def test_get_cursor_chat_ids(self):
        """get_cursor_chat_ids delegates to list_cursor_chats."""
        mock_chats = [
            {"composerId": "id1", "name": "Chat 1"},
            {"composerId": "id2", "name": "Chat 2"},
        ]
        with patch("server.cursor_chat_db.list_cursor_chats", return_value=(mock_chats, "id1")):
            result = get_cursor_chat_ids("file:///test")
            assert result == {"id1", "id2"}

    def test_get_cursor_chat_names(self):
        """get_cursor_chat_names delegates to list_cursor_chats."""
        mock_chats = [
            {"composerId": "id1", "name": "Chat 1"},
            {"composerId": "id2", "name": "Chat 2"},
        ]
        with patch("server.cursor_chat_db.list_cursor_chats", return_value=(mock_chats, "id1")):
            result = get_cursor_chat_names("file:///test")
            assert result == {"id1": "Chat 1", "id2": "Chat 2"}

    def test_get_cursor_chat_info_no_workspace_storage(self):
        """get_cursor_chat_info_from_db returns None when no workspace storage."""
        with (
            patch("pathlib.Path.home", return_value=Path("/fake/home")),
            patch("pathlib.Path.exists", return_value=False),
        ):
            chat_id, chat_name = get_cursor_chat_info_from_db("file:///test")
            assert chat_id is None
            assert chat_name is None

    def test_get_cursor_chat_info_exception(self):
        """get_cursor_chat_info_from_db returns None on exception."""
        with patch("pathlib.Path.home", side_effect=OSError("boom")):
            chat_id, chat_name = get_cursor_chat_info_from_db("file:///test")
            assert chat_id is None
            assert chat_name is None

    def test_list_cursor_chats_no_workspace_storage(self):
        """list_cursor_chats returns empty when no workspace storage dir."""
        with (
            patch("pathlib.Path.home", return_value=Path("/fake/home")),
            patch("pathlib.Path.exists", return_value=False),
        ):
            chats, active_id = list_cursor_chats("file:///test")
            assert chats == []
            assert active_id is None

    def test_list_cursor_chats_exception(self):
        """list_cursor_chats returns empty on exception."""
        with patch("pathlib.Path.home", side_effect=OSError("boom")):
            chats, active_id = list_cursor_chats("file:///test")
            assert chats == []
            assert active_id is None

    def test_get_cursor_chat_content_invalid_uuid(self):
        """get_cursor_chat_content rejects invalid UUID."""
        result = get_cursor_chat_content("not-a-uuid")
        assert result["chat_id"] == "not-a-uuid"
        assert result["message_count"] == 0

    def test_get_cursor_chat_content_none(self):
        """get_cursor_chat_content handles None chat_id."""
        result = get_cursor_chat_content(None)
        assert result["message_count"] == 0

    def test_get_meeting_transcript_issue_keys_no_db(self):
        """get_meeting_transcript_issue_keys returns empty when db missing."""
        with (
            patch(
                "server.paths.MEETINGS_DB_FILE",
                Path("/fake/nonexistent.db"),
                create=True,
            ),
            patch("pathlib.Path.exists", return_value=False),
        ):
            result = get_meeting_transcript_issue_keys()
            assert not result

    def test_inject_context_no_workspace_storage(self):
        """inject_context_to_cursor_chat returns False when no workspace storage."""
        with (
            patch("pathlib.Path.home", return_value=Path("/fake/home")),
            patch("pathlib.Path.exists", return_value=False),
        ):
            result = inject_context_to_cursor_chat("file:///test")
            assert result is False

    def test_inject_context_exception(self):
        """inject_context_to_cursor_chat returns False on exception."""
        with patch("pathlib.Path.home", side_effect=OSError("boom")):
            result = inject_context_to_cursor_chat("file:///test")
            assert result is False


class TestGetCursorChatInfoFromDb:
    """Tests for get_cursor_chat_info_from_db with mocked workspace storage."""

    def test_workspace_storage_not_found(self, tmp_path):
        """Returns (None, None) when workspace storage directory doesn't exist."""
        with patch("pathlib.Path.home", return_value=tmp_path):
            # No .config/Cursor/User/workspaceStorage directory
            chat_id, chat_name = get_cursor_chat_info_from_db("file:///test")
            assert chat_id is None
            assert chat_name is None

    def test_no_matching_workspace(self, tmp_path):
        """Returns (None, None) when no workspace.json matches."""
        ws_storage = tmp_path / ".config" / "Cursor" / "User" / "workspaceStorage"
        ws_dir = ws_storage / "abcdef123"
        ws_dir.mkdir(parents=True)
        workspace_json = ws_dir / "workspace.json"
        workspace_json.write_text(json.dumps({"folder": "file:///other-project"}))

        with patch("pathlib.Path.home", return_value=tmp_path):
            chat_id, chat_name = get_cursor_chat_info_from_db("file:///my-project")
            assert chat_id is None
            assert chat_name is None

    def test_matching_workspace_no_db(self, tmp_path):
        """Returns (None, None) when workspace matches but state.vscdb missing."""
        ws_storage = tmp_path / ".config" / "Cursor" / "User" / "workspaceStorage"
        ws_dir = ws_storage / "abcdef123"
        ws_dir.mkdir(parents=True)
        workspace_json = ws_dir / "workspace.json"
        workspace_json.write_text(json.dumps({"folder": "file:///my-project"}))
        # No state.vscdb file

        with patch("pathlib.Path.home", return_value=tmp_path):
            chat_id, chat_name = get_cursor_chat_info_from_db("file:///my-project")
            assert chat_id is None
            assert chat_name is None

    def test_matching_workspace_db_query_fails(self, tmp_path):
        """Returns (None, None) when sqlite3 query fails."""
        ws_storage = tmp_path / ".config" / "Cursor" / "User" / "workspaceStorage"
        ws_dir = ws_storage / "abcdef123"
        ws_dir.mkdir(parents=True)
        workspace_json = ws_dir / "workspace.json"
        workspace_json.write_text(json.dumps({"folder": "file:///my-project"}))
        db_file = ws_dir / "state.vscdb"
        db_file.write_text("")  # Empty file

        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.returncode = 1
        mock_result.stdout = ""

        with (
            patch("pathlib.Path.home", return_value=tmp_path),
            patch("subprocess.run", return_value=mock_result),
        ):
            chat_id, chat_name = get_cursor_chat_info_from_db("file:///my-project")
            assert chat_id is None
            assert chat_name is None

    def test_matching_workspace_no_composers(self, tmp_path):
        """Returns (None, None) when no composers in data."""
        ws_storage = tmp_path / ".config" / "Cursor" / "User" / "workspaceStorage"
        ws_dir = ws_storage / "abcdef123"
        ws_dir.mkdir(parents=True)
        workspace_json = ws_dir / "workspace.json"
        workspace_json.write_text(json.dumps({"folder": "file:///my-project"}))
        db_file = ws_dir / "state.vscdb"
        db_file.write_text("")

        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({"allComposers": []})

        with (
            patch("pathlib.Path.home", return_value=tmp_path),
            patch("subprocess.run", return_value=mock_result),
        ):
            chat_id, chat_name = get_cursor_chat_info_from_db("file:///my-project")
            assert chat_id is None
            assert chat_name is None

    def test_matching_workspace_all_archived(self, tmp_path):
        """Returns (None, None) when all chats are archived/draft."""
        ws_storage = tmp_path / ".config" / "Cursor" / "User" / "workspaceStorage"
        ws_dir = ws_storage / "abcdef123"
        ws_dir.mkdir(parents=True)
        workspace_json = ws_dir / "workspace.json"
        workspace_json.write_text(json.dumps({"folder": "file:///my-project"}))
        db_file = ws_dir / "state.vscdb"
        db_file.write_text("")

        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(
            {
                "allComposers": [
                    {"composerId": "c1", "isArchived": True, "lastUpdatedAt": 1000},
                    {"composerId": "c2", "isDraft": True, "lastUpdatedAt": 2000},
                ]
            }
        )

        with (
            patch("pathlib.Path.home", return_value=tmp_path),
            patch("subprocess.run", return_value=mock_result),
        ):
            chat_id, chat_name = get_cursor_chat_info_from_db("file:///my-project")
            assert chat_id is None
            assert chat_name is None

    def test_matching_workspace_returns_most_recent(self, tmp_path):
        """Returns the most recently updated active chat."""
        ws_storage = tmp_path / ".config" / "Cursor" / "User" / "workspaceStorage"
        ws_dir = ws_storage / "abcdef123"
        ws_dir.mkdir(parents=True)
        workspace_json = ws_dir / "workspace.json"
        workspace_json.write_text(json.dumps({"folder": "file:///my-project"}))
        db_file = ws_dir / "state.vscdb"
        db_file.write_text("")

        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(
            {
                "allComposers": [
                    {"composerId": "c1", "name": "Old Chat", "lastUpdatedAt": 1000},
                    {"composerId": "c2", "name": "New Chat", "lastUpdatedAt": 3000},
                    {"composerId": "c3", "name": "Middle Chat", "lastUpdatedAt": 2000},
                ]
            }
        )

        with (
            patch("pathlib.Path.home", return_value=tmp_path),
            patch("subprocess.run", return_value=mock_result),
        ):
            chat_id, chat_name = get_cursor_chat_info_from_db("file:///my-project")
            assert chat_id == "c2"
            assert chat_name == "New Chat"

    def test_skips_non_dir_entries(self, tmp_path):
        """Skips files in workspaceStorage that aren't directories."""
        ws_storage = tmp_path / ".config" / "Cursor" / "User" / "workspaceStorage"
        ws_storage.mkdir(parents=True)
        # Create a file (not directory)
        (ws_storage / "some_file.txt").write_text("not a dir")

        with patch("pathlib.Path.home", return_value=tmp_path):
            chat_id, chat_name = get_cursor_chat_info_from_db("file:///my-project")
            assert chat_id is None
            assert chat_name is None

    def test_skips_dirs_without_workspace_json(self, tmp_path):
        """Skips directories without workspace.json."""
        ws_storage = tmp_path / ".config" / "Cursor" / "User" / "workspaceStorage"
        ws_dir = ws_storage / "abcdef123"
        ws_dir.mkdir(parents=True)
        # No workspace.json

        with patch("pathlib.Path.home", return_value=tmp_path):
            chat_id, chat_name = get_cursor_chat_info_from_db("file:///my-project")
            assert chat_id is None
            assert chat_name is None

    def test_handles_invalid_workspace_json(self, tmp_path):
        """Handles corrupt workspace.json gracefully."""
        ws_storage = tmp_path / ".config" / "Cursor" / "User" / "workspaceStorage"
        ws_dir = ws_storage / "abcdef123"
        ws_dir.mkdir(parents=True)
        workspace_json = ws_dir / "workspace.json"
        workspace_json.write_text("{invalid json{{")

        with patch("pathlib.Path.home", return_value=tmp_path):
            chat_id, chat_name = get_cursor_chat_info_from_db("file:///my-project")
            assert chat_id is None
            assert chat_name is None


class TestGetCursorChatIdFromDb:
    """Tests for backward compat wrapper."""

    def test_returns_chat_id(self):
        """get_cursor_chat_id_from_db returns just the chat_id."""
        with patch(
            "server.cursor_chat_db.get_cursor_chat_info_from_db",
            return_value=("id123", "Name"),
        ):
            result = get_cursor_chat_id_from_db("file:///test")
            assert result == "id123"

    def test_returns_none(self):
        """get_cursor_chat_id_from_db returns None when no chat found."""
        with patch(
            "server.cursor_chat_db.get_cursor_chat_info_from_db",
            return_value=(None, None),
        ):
            result = get_cursor_chat_id_from_db("file:///test")
            assert result is None


class TestListCursorChats:
    """Tests for list_cursor_chats with mocked workspace storage."""

    def test_workspace_storage_not_found(self, tmp_path):
        """Returns empty when workspace storage doesn't exist."""
        with patch("pathlib.Path.home", return_value=tmp_path):
            chats, active_id = list_cursor_chats("file:///test")
            assert chats == []
            assert active_id is None

    def test_aggregates_chats(self, tmp_path):
        """Aggregates chats from matching workspace dirs."""
        ws_storage = tmp_path / ".config" / "Cursor" / "User" / "workspaceStorage"
        ws_dir = ws_storage / "dir1"
        ws_dir.mkdir(parents=True)
        workspace_json = ws_dir / "workspace.json"
        workspace_json.write_text(json.dumps({"folder": "file:///my-project"}))
        db_file = ws_dir / "state.vscdb"
        db_file.write_text("")

        composer_data = {
            "allComposers": [
                {
                    "composerId": "c1",
                    "name": "Chat 1",
                    "createdAt": 1000,
                    "lastUpdatedAt": 2000,
                },
                {
                    "composerId": "c2",
                    "name": "Chat 2",
                    "createdAt": 1500,
                    "lastUpdatedAt": 3000,
                },
                # Ghost chat (no name, no lastUpdatedAt)
                {"composerId": "c3"},
                # Archived
                {
                    "composerId": "c4",
                    "name": "Archived",
                    "isArchived": True,
                    "lastUpdatedAt": 4000,
                },
            ],
            "lastFocusedComposerIds": ["c2"],
        }
        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(composer_data)

        with (
            patch("pathlib.Path.home", return_value=tmp_path),
            patch("subprocess.run", return_value=mock_result),
        ):
            chats, active_id = list_cursor_chats("file:///my-project")

        assert len(chats) == 2  # c1 and c2 only (c3 ghost, c4 archived)
        assert active_id == "c2"
        # Should be sorted by lastUpdatedAt descending
        assert chats[0]["composerId"] == "c2"
        assert chats[1]["composerId"] == "c1"

    def test_skips_non_matching_workspace(self, tmp_path):
        """Skips workspace directories that don't match URI."""
        ws_storage = tmp_path / ".config" / "Cursor" / "User" / "workspaceStorage"
        ws_dir = ws_storage / "dir1"
        ws_dir.mkdir(parents=True)
        workspace_json = ws_dir / "workspace.json"
        workspace_json.write_text(json.dumps({"folder": "file:///other-project"}))

        with patch("pathlib.Path.home", return_value=tmp_path):
            chats, _active_id = list_cursor_chats("file:///my-project")
            assert chats == []

    def test_handles_db_query_failure(self, tmp_path):
        """Handles sqlite3 query failure gracefully."""
        ws_storage = tmp_path / ".config" / "Cursor" / "User" / "workspaceStorage"
        ws_dir = ws_storage / "dir1"
        ws_dir.mkdir(parents=True)
        workspace_json = ws_dir / "workspace.json"
        workspace_json.write_text(json.dumps({"folder": "file:///my-project"}))
        db_file = ws_dir / "state.vscdb"
        db_file.write_text("")

        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.returncode = 1
        mock_result.stdout = ""

        with (
            patch("pathlib.Path.home", return_value=tmp_path),
            patch("subprocess.run", return_value=mock_result),
        ):
            chats, _active_id = list_cursor_chats("file:///my-project")
            assert chats == []

    def test_handles_invalid_json_in_workspace(self, tmp_path):
        """Handles corrupt workspace.json gracefully."""
        ws_storage = tmp_path / ".config" / "Cursor" / "User" / "workspaceStorage"
        ws_dir = ws_storage / "dir1"
        ws_dir.mkdir(parents=True)
        workspace_json = ws_dir / "workspace.json"
        workspace_json.write_text("not json{{{")

        with patch("pathlib.Path.home", return_value=tmp_path):
            chats, _active_id = list_cursor_chats("file:///my-project")
            assert chats == []

    def test_no_db_file(self, tmp_path):
        """Skips workspace that matches but has no state.vscdb."""
        ws_storage = tmp_path / ".config" / "Cursor" / "User" / "workspaceStorage"
        ws_dir = ws_storage / "dir1"
        ws_dir.mkdir(parents=True)
        workspace_json = ws_dir / "workspace.json"
        workspace_json.write_text(json.dumps({"folder": "file:///my-project"}))
        # No state.vscdb

        with patch("pathlib.Path.home", return_value=tmp_path):
            chats, _active_id = list_cursor_chats("file:///my-project")
            assert chats == []

    def test_deduplicates_across_dirs(self, tmp_path):
        """Deduplicates chats when same ID appears in multiple workspace dirs."""
        ws_storage = tmp_path / ".config" / "Cursor" / "User" / "workspaceStorage"

        for i, _ts in enumerate([1000, 2000]):
            ws_dir = ws_storage / f"dir{i}"
            ws_dir.mkdir(parents=True)
            (ws_dir / "workspace.json").write_text(json.dumps({"folder": "file:///project"}))
            (ws_dir / "state.vscdb").write_text("")

        mock_results = [
            MagicMock(
                returncode=0,
                stdout=json.dumps(
                    {
                        "allComposers": [
                            {
                                "composerId": "c1",
                                "name": "Old",
                                "createdAt": 1000,
                                "lastUpdatedAt": 1000,
                            }
                        ],
                        "lastFocusedComposerIds": [],
                    }
                ),
            ),
            MagicMock(
                returncode=0,
                stdout=json.dumps(
                    {
                        "allComposers": [
                            {
                                "composerId": "c1",
                                "name": "New",
                                "createdAt": 1000,
                                "lastUpdatedAt": 2000,
                            }
                        ],
                        "lastFocusedComposerIds": [],
                    }
                ),
            ),
        ]

        with (
            patch("pathlib.Path.home", return_value=tmp_path),
            patch("subprocess.run", side_effect=mock_results),
        ):
            chats, _active_id = list_cursor_chats("file:///project")

        assert len(chats) == 1
        assert chats[0]["name"] == "New"  # Should keep the newer one


class TestInjectContextToCursorChat:
    """Tests for inject_context_to_cursor_chat."""

    def test_no_workspace_storage(self, tmp_path):
        """Returns False when workspace storage directory doesn't exist."""
        with patch("pathlib.Path.home", return_value=tmp_path):
            result = inject_context_to_cursor_chat("file:///test")
            assert result is False

    def test_no_matching_workspace(self, tmp_path):
        """Returns False when no matching workspace found."""
        ws_storage = tmp_path / ".config" / "Cursor" / "User" / "workspaceStorage"
        ws_dir = ws_storage / "dir1"
        ws_dir.mkdir(parents=True)
        (ws_dir / "workspace.json").write_text(json.dumps({"folder": "file:///other"}))

        with patch("pathlib.Path.home", return_value=tmp_path):
            result = inject_context_to_cursor_chat("file:///test")
            assert result is False

    def test_no_db_file(self, tmp_path):
        """Returns False when state.vscdb is missing."""
        ws_storage = tmp_path / ".config" / "Cursor" / "User" / "workspaceStorage"
        ws_dir = ws_storage / "dir1"
        ws_dir.mkdir(parents=True)
        (ws_dir / "workspace.json").write_text(json.dumps({"folder": "file:///test"}))
        # No state.vscdb

        with patch("pathlib.Path.home", return_value=tmp_path):
            result = inject_context_to_cursor_chat("file:///test")
            assert result is False

    def test_read_failure(self, tmp_path):
        """Returns False when reading composer data fails."""
        ws_storage = tmp_path / ".config" / "Cursor" / "User" / "workspaceStorage"
        ws_dir = ws_storage / "dir1"
        ws_dir.mkdir(parents=True)
        (ws_dir / "workspace.json").write_text(json.dumps({"folder": "file:///test"}))
        (ws_dir / "state.vscdb").write_text("")

        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.returncode = 1
        mock_result.stderr = "error"

        with (
            patch("pathlib.Path.home", return_value=tmp_path),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = inject_context_to_cursor_chat("file:///test")
            assert result is False

    def test_creates_new_chat(self, tmp_path):
        """Successfully creates a new chat entry."""
        ws_storage = tmp_path / ".config" / "Cursor" / "User" / "workspaceStorage"
        ws_dir = ws_storage / "dir1"
        ws_dir.mkdir(parents=True)
        (ws_dir / "workspace.json").write_text(json.dumps({"folder": "file:///test"}))
        (ws_dir / "state.vscdb").write_text("")

        # First call: read composer data (empty)
        read_result = MagicMock(returncode=0, stdout="")
        # Second call: write update (success)
        write_result = MagicMock(returncode=0)

        with (
            patch("pathlib.Path.home", return_value=tmp_path),
            patch("subprocess.run", side_effect=[read_result, write_result]),
        ):
            result = inject_context_to_cursor_chat(
                "file:///test",
                context={"persona": "developer", "name": "Test Chat"},
                system_message="You are a developer",
            )
            assert result is True

    def test_updates_existing_chat(self, tmp_path):
        """Updates an existing chat entry."""
        ws_storage = tmp_path / ".config" / "Cursor" / "User" / "workspaceStorage"
        ws_dir = ws_storage / "dir1"
        ws_dir.mkdir(parents=True)
        (ws_dir / "workspace.json").write_text(json.dumps({"folder": "file:///test"}))
        (ws_dir / "state.vscdb").write_text("")

        existing_data = {
            "allComposers": [
                {
                    "composerId": "12345678-1234-5678-1234-567812345678",
                    "name": "Old Name",
                }
            ],
            "lastFocusedComposerIds": [],
        }
        read_result = MagicMock(returncode=0, stdout=json.dumps(existing_data))
        write_result = MagicMock(returncode=0)

        with (
            patch("pathlib.Path.home", return_value=tmp_path),
            patch("subprocess.run", side_effect=[read_result, write_result]),
        ):
            result = inject_context_to_cursor_chat(
                "file:///test",
                chat_id="12345678-1234-5678-1234-567812345678",
                context={"persona": "devops"},
            )
            assert result is True

    def test_rejects_invalid_chat_id(self, tmp_path):
        """Returns False for non-UUID chat_id."""
        ws_storage = tmp_path / ".config" / "Cursor" / "User" / "workspaceStorage"
        ws_dir = ws_storage / "dir1"
        ws_dir.mkdir(parents=True)
        (ws_dir / "workspace.json").write_text(json.dumps({"folder": "file:///test"}))
        (ws_dir / "state.vscdb").write_text("")

        read_result = MagicMock(
            returncode=0,
            stdout=json.dumps({"allComposers": [], "lastFocusedComposerIds": []}),
        )

        with (
            patch("pathlib.Path.home", return_value=tmp_path),
            patch("subprocess.run", return_value=read_result),
        ):
            result = inject_context_to_cursor_chat(
                "file:///test",
                chat_id="not-a-valid-uuid",
            )
            assert result is False

    def test_write_failure(self, tmp_path):
        """Returns False when writing to DB fails."""
        ws_storage = tmp_path / ".config" / "Cursor" / "User" / "workspaceStorage"
        ws_dir = ws_storage / "dir1"
        ws_dir.mkdir(parents=True)
        (ws_dir / "workspace.json").write_text(json.dumps({"folder": "file:///test"}))
        (ws_dir / "state.vscdb").write_text("")

        read_result = MagicMock(returncode=0, stdout="")
        write_result = MagicMock(returncode=1, stderr="write error")

        with (
            patch("pathlib.Path.home", return_value=tmp_path),
            patch("subprocess.run", side_effect=[read_result, write_result]),
        ):
            result = inject_context_to_cursor_chat("file:///test")
            assert result is False

    def test_handles_corrupt_workspace_json(self, tmp_path):
        """Handles corrupt workspace.json and continues."""
        ws_storage = tmp_path / ".config" / "Cursor" / "User" / "workspaceStorage"
        # First dir has corrupt JSON
        ws_dir1 = ws_storage / "dir1"
        ws_dir1.mkdir(parents=True)
        (ws_dir1 / "workspace.json").write_text("{invalid json{{")

        with patch("pathlib.Path.home", return_value=tmp_path):
            result = inject_context_to_cursor_chat("file:///test")
            assert result is False
