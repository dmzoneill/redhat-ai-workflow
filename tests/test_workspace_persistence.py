"""Tests for WorkspaceRegistry persistence: saving, loading and restoring from disk."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import server.workspace_state as ws_module
from server.workspace_state import (
    WorkspaceRegistry,
)


class TestWorkspaceRegistryPersistence:
    """Tests for WorkspaceRegistry persistence (save/load to disk)."""

    def setup_method(self):
        """Clear registry before each test."""
        WorkspaceRegistry.clear()

    def teardown_method(self):
        """Clear registry after each test."""
        WorkspaceRegistry.clear()

    def test_save_and_load_sessions(self, tmp_path):
        """Test that sessions can be saved and loaded from disk."""
        # Use temp path for persistence
        persist_file = tmp_path / "workspace_states.json"

        with (
            patch.object(ws_module, "PERSIST_DIR", tmp_path),
            patch.object(ws_module, "PERSIST_FILE", persist_file),
        ):
            # Create workspaces with sessions (ensure_session=False to avoid auto-create)
            ws1 = WorkspaceRegistry.get_or_create("file:///workspace1", ensure_session=False)
            ws1.project = "project1"
            session1 = ws1.create_session(persona="developer", name="Dev Session")
            session1.issue_key = "AAP-12345"
            session1.branch = "feature-branch"

            ws2 = WorkspaceRegistry.get_or_create("file:///workspace2", ensure_session=False)
            ws2.project = "project2"
            ws2.create_session(persona="devops", name="DevOps Session")

            # Verify sessions exist
            assert WorkspaceRegistry.count() == 2
            assert WorkspaceRegistry.total_session_count() == 2

            # Save should have been called automatically by create_session
            # Verify the file exists and has correct content
            assert persist_file.exists()

            with open(persist_file, encoding="utf-8") as f:
                data = json.load(f)

            assert data["version"] == 2
            assert "file:///workspace1" in data["workspaces"]
            assert "file:///workspace2" in data["workspaces"]

            # Clear registry
            WorkspaceRegistry.clear()
            assert WorkspaceRegistry.count() == 0

            # Load from disk
            restored = WorkspaceRegistry.load_from_disk()
            assert restored == 2  # 2 sessions restored

            # Verify workspaces and sessions restored
            assert WorkspaceRegistry.count() == 2
            assert WorkspaceRegistry.total_session_count() == 2

            # Verify session details
            restored_ws1 = WorkspaceRegistry.get("file:///workspace1")
            assert restored_ws1 is not None
            assert restored_ws1.project == "project1"
            assert len(restored_ws1.sessions) == 1

            restored_session1 = next(iter(restored_ws1.sessions.values()))
            assert restored_session1.persona == "developer"
            assert restored_session1.issue_key == "AAP-12345"
            assert restored_session1.branch == "feature-branch"
            assert restored_session1.name == "Dev Session"

    def test_restore_if_empty_only_loads_when_empty(self, tmp_path):
        """Test that restore_if_empty only loads when registry is empty."""
        persist_file = tmp_path / "workspace_states.json"

        with (
            patch.object(ws_module, "PERSIST_DIR", tmp_path),
            patch.object(ws_module, "PERSIST_FILE", persist_file),
        ):
            # Create a workspace (ensure_session=False to avoid auto-create)
            ws = WorkspaceRegistry.get_or_create("file:///workspace1", ensure_session=False)
            ws.create_session()

            # Try to restore - should do nothing since registry is not empty
            restored = WorkspaceRegistry.restore_if_empty()
            assert restored == 0

            # Clear and try again
            WorkspaceRegistry.clear()
            restored = WorkspaceRegistry.restore_if_empty()
            # Should restore the session we saved earlier
            assert restored == 1

    def test_load_handles_missing_file(self, tmp_path):
        """Test that load_from_disk handles missing file gracefully."""
        persist_file = tmp_path / "workspace_states.json"

        with (
            patch.object(ws_module, "PERSIST_DIR", tmp_path),
            patch.object(ws_module, "PERSIST_FILE", persist_file),
        ):
            # File doesn't exist
            assert not persist_file.exists()

            restored = WorkspaceRegistry.load_from_disk()
            assert restored == 0

    def test_load_handles_invalid_json(self, tmp_path):
        """Test that load_from_disk handles invalid JSON gracefully."""
        persist_file = tmp_path / "workspace_states.json"

        with (
            patch.object(ws_module, "PERSIST_DIR", tmp_path),
            patch.object(ws_module, "PERSIST_FILE", persist_file),
        ):
            # Write invalid JSON
            with open(persist_file, "w", encoding="utf-8") as f:
                f.write("not valid json {{{")

            restored = WorkspaceRegistry.load_from_disk()
            assert restored == 0

    def test_load_handles_old_version(self, tmp_path):
        """Test that load_from_disk skips old format versions."""
        persist_file = tmp_path / "workspace_states.json"

        with (
            patch.object(ws_module, "PERSIST_DIR", tmp_path),
            patch.object(ws_module, "PERSIST_FILE", persist_file),
        ):
            # Write old version format
            with open(persist_file, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "workspaces": {}}, f)

            restored = WorkspaceRegistry.load_from_disk()
            assert restored == 0


class TestTryRestoreWorkspaceFromDisk:
    """Tests for try_restore_workspace_from_disk."""

    def setup_method(self):
        """Start from an empty registry."""
        WorkspaceRegistry.clear()

    def teardown_method(self):
        """Leave an empty registry behind."""
        WorkspaceRegistry.clear()

    def test_no_file(self, tmp_path):
        """Returns False when persist file doesn't exist."""
        with patch.object(ws_module, "PERSIST_FILE", tmp_path / "nonexistent.json"):
            result = WorkspaceRegistry.try_restore_workspace_from_disk("file:///ws1")
            assert result is False

    def test_old_version(self, tmp_path):
        """Returns False for old version format."""
        persist_file = tmp_path / "states.json"
        persist_file.write_text(json.dumps({"version": 1, "workspaces": {}}))
        with patch.object(ws_module, "PERSIST_FILE", persist_file):
            result = WorkspaceRegistry.try_restore_workspace_from_disk("file:///ws1")
            assert result is False

    def test_workspace_not_in_file(self, tmp_path):
        """Returns False when workspace is not in persisted data."""
        persist_file = tmp_path / "states.json"
        persist_file.write_text(
            json.dumps(
                {
                    "version": 2,
                    "workspaces": {"file:///other": {"sessions": {}, "project": "other"}},
                }
            )
        )
        with patch.object(ws_module, "PERSIST_FILE", persist_file):
            result = WorkspaceRegistry.try_restore_workspace_from_disk("file:///ws1")
            assert result is False

    def test_restore_success(self, tmp_path):
        """Successfully restores workspace from disk."""
        persist_file = tmp_path / "states.json"
        persist_file.write_text(
            json.dumps(
                {
                    "version": 2,
                    "workspaces": {
                        "file:///ws1": {
                            "project": "my-proj",
                            "is_auto_detected": True,
                            "active_session_id": "sess1",
                            "created_at": "2025-01-15T10:00:00",
                            "last_activity": "2025-01-15T11:00:00",
                            "sessions": {
                                "sess1": {
                                    "persona": "developer",
                                    "project": "my-proj",
                                    "is_project_auto_detected": False,
                                    "issue_key": "AAP-123",
                                    "branch": "feature",
                                    "name": "Dev Session",
                                    "started_at": "2025-01-15T10:00:00",
                                    "last_activity": "2025-01-15T11:00:00",
                                    "static_tool_count": 25,
                                    "dynamic_tool_count": 5,
                                    "last_filter_message": "check pods",
                                    "last_filter_time": "2025-01-15T10:30:00",
                                    "last_tool": "k8s_pods",
                                    "last_tool_time": "2025-01-15T10:45:00",
                                    "tool_call_count": 12,
                                    "meeting_references": [{"meeting_id": 1, "title": "Sprint"}],
                                }
                            },
                        }
                    },
                }
            )
        )
        with patch.object(ws_module, "PERSIST_FILE", persist_file):
            result = WorkspaceRegistry.try_restore_workspace_from_disk("file:///ws1")
            assert result is True

            ws = WorkspaceRegistry.get("file:///ws1")
            assert ws is not None
            assert ws.project == "my-proj"
            assert ws.active_session_id == "sess1"

            session = ws.get_session("sess1")
            assert session is not None
            assert session.persona == "developer"
            assert session.issue_key == "AAP-123"
            assert session.static_tool_count == 25
            assert session.dynamic_tool_count == 5
            assert session.last_tool == "k8s_pods"
            assert session.tool_call_count == 12

    def test_restore_normalized_uri(self, tmp_path):
        """Restores workspace when URI has trailing slash difference."""
        persist_file = tmp_path / "states.json"
        persist_file.write_text(
            json.dumps(
                {
                    "version": 2,
                    "workspaces": {
                        "file:///ws1/": {
                            "project": "proj",
                            "sessions": {},
                        }
                    },
                }
            )
        )
        with patch.object(ws_module, "PERSIST_FILE", persist_file):
            result = WorkspaceRegistry.try_restore_workspace_from_disk("file:///ws1")
            assert result is True

    def test_restore_exception(self, tmp_path):
        """Returns False on exception during restore."""
        persist_file = tmp_path / "states.json"
        persist_file.write_text("not valid json {{{")
        with patch.object(ws_module, "PERSIST_FILE", persist_file):
            result = WorkspaceRegistry.try_restore_workspace_from_disk("file:///ws1")
            assert result is False

    def test_restore_old_format_tool_count(self, tmp_path):
        """Restores tool_count from old format (tool_count field)."""
        persist_file = tmp_path / "states.json"
        persist_file.write_text(
            json.dumps(
                {
                    "version": 2,
                    "workspaces": {
                        "file:///ws1": {
                            "project": "proj",
                            "sessions": {
                                "s1": {
                                    "persona": "developer",
                                    "tool_count": 30,
                                }
                            },
                        }
                    },
                }
            )
        )
        with patch.object(ws_module, "PERSIST_FILE", persist_file):
            result = WorkspaceRegistry.try_restore_workspace_from_disk("file:///ws1")
            assert result is True
            session = WorkspaceRegistry.get("file:///ws1").get_session("s1")
            assert session.static_tool_count == 30

    def test_restore_old_format_active_tools(self, tmp_path):
        """Restores tool count from old format (active_tools list)."""
        persist_file = tmp_path / "states.json"
        persist_file.write_text(
            json.dumps(
                {
                    "version": 2,
                    "workspaces": {
                        "file:///ws1": {
                            "project": "proj",
                            "sessions": {
                                "s1": {
                                    "persona": "developer",
                                    "active_tools": ["tool_a", "tool_b", "tool_c"],
                                }
                            },
                        }
                    },
                }
            )
        )
        with patch.object(ws_module, "PERSIST_FILE", persist_file):
            result = WorkspaceRegistry.try_restore_workspace_from_disk("file:///ws1")
            assert result is True
            session = WorkspaceRegistry.get("file:///ws1").get_session("s1")
            assert session.static_tool_count == 3

    def test_restore_session_inherits_workspace_project(self, tmp_path):
        """Session with no project inherits from workspace."""
        persist_file = tmp_path / "states.json"
        persist_file.write_text(
            json.dumps(
                {
                    "version": 2,
                    "workspaces": {
                        "file:///ws1": {
                            "project": "ws-project",
                            "is_auto_detected": True,
                            "sessions": {
                                "s1": {
                                    "persona": "devops",
                                    # No project field
                                }
                            },
                        }
                    },
                }
            )
        )
        with patch.object(ws_module, "PERSIST_FILE", persist_file):
            WorkspaceRegistry.try_restore_workspace_from_disk("file:///ws1")
            session = WorkspaceRegistry.get("file:///ws1").get_session("s1")
            assert session.project == "ws-project"
            assert session.is_project_auto_detected is True


class TestLoadFromDiskAdvanced:
    """Additional tests for load_from_disk covering edge cases."""

    def setup_method(self):
        """Start from an empty registry."""
        WorkspaceRegistry.clear()

    def teardown_method(self):
        """Leave an empty registry behind."""
        WorkspaceRegistry.clear()

    def test_load_restores_session_with_old_tool_count(self, tmp_path):
        """load_from_disk handles old-format tool_count field."""
        persist_file = tmp_path / "workspace_states.json"

        with (
            patch.object(ws_module, "PERSIST_DIR", tmp_path),
            patch.object(ws_module, "PERSIST_FILE", persist_file),
        ):
            persist_file.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "workspaces": {
                            "file:///ws1": {
                                "project": "proj",
                                "active_session_id": "s1",
                                "sessions": {
                                    "s1": {
                                        "persona": "developer",
                                        "tool_count": 20,
                                    }
                                },
                            }
                        },
                    }
                )
            )

            with (
                patch("server.cursor_chat_db.list_cursor_chats", return_value=([], None)),
                patch("server.workspace_state.detect_project", return_value=None),
            ):
                restored = WorkspaceRegistry.load_from_disk()

            assert restored == 1
            ws = WorkspaceRegistry.get("file:///ws1")
            assert ws is not None
            session = ws.get_session("s1")
            assert session.static_tool_count == 20

    def test_load_restores_session_with_active_tools(self, tmp_path):
        """load_from_disk handles old-format active_tools list."""
        persist_file = tmp_path / "workspace_states.json"

        with (
            patch.object(ws_module, "PERSIST_DIR", tmp_path),
            patch.object(ws_module, "PERSIST_FILE", persist_file),
        ):
            persist_file.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "workspaces": {
                            "file:///ws1": {
                                "project": "proj",
                                "sessions": {
                                    "s1": {
                                        "persona": "developer",
                                        "active_tools": ["a", "b"],
                                    }
                                },
                            }
                        },
                    }
                )
            )

            with (
                patch("server.cursor_chat_db.list_cursor_chats", return_value=([], None)),
                patch("server.workspace_state.detect_project", return_value=None),
            ):
                restored = WorkspaceRegistry.load_from_disk()

            assert restored == 1
            session = WorkspaceRegistry.get("file:///ws1").get_session("s1")
            assert session.static_tool_count == 2

    def test_load_re_detects_project(self, tmp_path):
        """load_from_disk re-detects project from URI."""
        persist_file = tmp_path / "workspace_states.json"

        with (
            patch.object(ws_module, "PERSIST_DIR", tmp_path),
            patch.object(ws_module, "PERSIST_FILE", persist_file),
        ):
            persist_file.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "workspaces": {
                            "file:///ws1": {
                                "project": "old-name",
                                "sessions": {"s1": {"persona": "developer"}},
                            }
                        },
                    }
                )
            )

            with (
                patch("server.cursor_chat_db.list_cursor_chats", return_value=([], None)),
                patch("server.workspace_state.detect_project", return_value="new-name"),
            ):
                restored = WorkspaceRegistry.load_from_disk()

            assert restored == 1
            ws = WorkspaceRegistry.get("file:///ws1")
            assert ws.project == "new-name"
            assert ws.is_auto_detected is True

    def test_load_skips_stale_empty_workspaces(self, tmp_path):
        """load_from_disk skips stale workspaces with no sessions."""
        persist_file = tmp_path / "workspace_states.json"

        stale_time = (datetime.now(tz=timezone.utc) - timedelta(hours=48)).isoformat()

        with (
            patch.object(ws_module, "PERSIST_DIR", tmp_path),
            patch.object(ws_module, "PERSIST_FILE", persist_file),
        ):
            persist_file.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "workspaces": {
                            "file:///stale-ws": {
                                "project": "proj",
                                "last_activity": stale_time,
                                "sessions": {},
                            }
                        },
                    }
                )
            )

            with (
                patch("server.cursor_chat_db.list_cursor_chats", return_value=([], None)),
                patch("server.workspace_state.detect_project", return_value=None),
            ):
                restored = WorkspaceRegistry.load_from_disk()

            assert restored == 0
            # Stale empty workspace should not be added
            assert WorkspaceRegistry.count() == 0

    def test_load_general_exception(self, tmp_path):
        """load_from_disk handles general exceptions gracefully."""
        persist_file = tmp_path / "workspace_states.json"
        persist_file.write_text('{"version": 2, "workspaces": {}}')

        with (
            patch.object(ws_module, "PERSIST_DIR", tmp_path),
            patch.object(ws_module, "PERSIST_FILE", persist_file),
            patch("builtins.open", side_effect=OSError("disk error")),
        ):
            restored = WorkspaceRegistry.load_from_disk()
            assert restored == 0

    def test_load_updates_names_from_cursor(self, tmp_path):
        """load_from_disk updates session names from Cursor DB."""
        persist_file = tmp_path / "workspace_states.json"

        with (
            patch.object(ws_module, "PERSIST_DIR", tmp_path),
            patch.object(ws_module, "PERSIST_FILE", persist_file),
        ):
            persist_file.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "workspaces": {
                            "file:///ws1": {
                                "project": "proj",
                                "sessions": {
                                    "s1": {
                                        "persona": "developer",
                                        "name": "Old Name",
                                    }
                                },
                            }
                        },
                    }
                )
            )

            cursor_chats = [{"composerId": "s1", "name": "New Name"}]
            with (
                patch(
                    "server.cursor_chat_db.list_cursor_chats",
                    return_value=(cursor_chats, "s1"),
                ),
                patch("server.workspace_state.detect_project", return_value=None),
            ):
                restored = WorkspaceRegistry.load_from_disk()

            assert restored == 1
            ws = WorkspaceRegistry.get("file:///ws1")
            session = ws.get_session("s1")
            assert session.name == "New Name"
            assert ws.active_session_id == "s1"

    def test_load_restores_full_session_data(self, tmp_path):
        """load_from_disk restores all session fields properly."""
        persist_file = tmp_path / "workspace_states.json"

        with (
            patch.object(ws_module, "PERSIST_DIR", tmp_path),
            patch.object(ws_module, "PERSIST_FILE", persist_file),
        ):
            persist_file.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "workspaces": {
                            "file:///ws1": {
                                "project": "proj",
                                "created_at": "2025-01-10T08:00:00",
                                "last_activity": "2025-01-15T12:00:00",
                                "sessions": {
                                    "s1": {
                                        "persona": "devops",
                                        "project": "my-proj",
                                        "issue_key": "AAP-100",
                                        "branch": "fix-100",
                                        "name": "Fix Session",
                                        "started_at": "2025-01-15T10:00:00",
                                        "last_activity": "2025-01-15T11:00:00",
                                        "static_tool_count": 40,
                                        "dynamic_tool_count": 8,
                                        "last_filter_message": "check status",
                                        "last_filter_time": "2025-01-15T10:30:00",
                                        "last_tool": "git_status",
                                        "last_tool_time": "2025-01-15T10:50:00",
                                        "tool_call_count": 15,
                                        "meeting_references": [{"meeting_id": 2, "title": "Retro"}],
                                    }
                                },
                            }
                        },
                    }
                )
            )

            with (
                patch("server.cursor_chat_db.list_cursor_chats", return_value=([], None)),
                patch("server.workspace_state.detect_project", return_value=None),
            ):
                restored = WorkspaceRegistry.load_from_disk()

            assert restored == 1
            ws = WorkspaceRegistry.get("file:///ws1")
            assert ws.created_at == datetime.fromisoformat("2025-01-10T08:00:00")
            assert ws.last_activity == datetime.fromisoformat("2025-01-15T12:00:00")

            s = ws.get_session("s1")
            assert s.persona == "devops"
            assert s.project == "my-proj"
            assert s.issue_key == "AAP-100"
            assert s.branch == "fix-100"
            assert s.started_at == datetime.fromisoformat("2025-01-15T10:00:00")
            assert s.last_activity == datetime.fromisoformat("2025-01-15T11:00:00")
            assert s.static_tool_count == 40
            assert s.dynamic_tool_count == 8
            assert s.last_filter_message == "check status"
            assert s.last_filter_time == datetime.fromisoformat("2025-01-15T10:30:00")
            assert s.last_tool == "git_status"
            assert s.last_tool_time == datetime.fromisoformat("2025-01-15T10:50:00")
            assert s.tool_call_count == 15
            assert s.meeting_references == [{"meeting_id": 2, "title": "Retro"}]
