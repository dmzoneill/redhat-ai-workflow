"""Tests for tool_modules/aa_workflow/src/workspace_exporter.py - Workspace state export."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

# ==================== Helper to import with mocked server.paths ====================

# We need to mock server.paths before importing workspace_exporter
_mock_config_dir = Path("/tmp/test_aa_config")
_mock_export_file = _mock_config_dir / "workspace_states.json"

with (
    patch("server.paths.AA_CONFIG_DIR", _mock_config_dir),
    patch("server.paths.WORKSPACE_STATES_FILE", _mock_export_file),
):
    from tool_modules.aa_workflow.src.workspace_exporter import (
        _ensure_export_dir,
        clear_exported_state,
        export_workspace_state,
        export_workspace_state_async,
        export_workspace_state_with_data,
        get_export_file_path,
        read_exported_state,
    )


# ==================== _ensure_export_dir ====================


class TestEnsureExportDir:
    """Tests for _ensure_export_dir."""

    def test_creates_directory(self):
        with patch(
            "tool_modules.aa_workflow.src.workspace_exporter.EXPORT_DIR"
        ) as mock_dir:
            _ensure_export_dir()
            mock_dir.mkdir.assert_called_once_with(parents=True, exist_ok=True)
            assert mock_dir.mkdir.call_count == 1


# ==================== get_export_file_path ====================


class TestGetExportFilePath:
    """Tests for get_export_file_path."""

    def test_returns_path(self):
        result = get_export_file_path()
        assert isinstance(result, Path)


# ==================== read_exported_state ====================


class TestReadExportedState:
    """Tests for read_exported_state."""

    def test_file_not_exists(self):
        with patch(
            "tool_modules.aa_workflow.src.workspace_exporter.EXPORT_FILE"
        ) as mock_file:
            mock_file.exists.return_value = False
            result = read_exported_state()
            assert result is None

    def test_reads_valid_json(self):
        with patch(
            "tool_modules.aa_workflow.src.workspace_exporter.EXPORT_FILE"
        ) as mock_file:
            mock_file.exists.return_value = True
            data = {"version": 3, "workspaces": {}}
            m = mock_open(read_data=json.dumps(data))
            with patch("builtins.open", m):
                result = read_exported_state()
                assert result is not None
                assert result["version"] == 3

    def test_handles_json_error(self):
        with patch(
            "tool_modules.aa_workflow.src.workspace_exporter.EXPORT_FILE"
        ) as mock_file:
            mock_file.exists.return_value = True
            m = mock_open(read_data="not json")
            with patch("builtins.open", m):
                result = read_exported_state()
                assert result is None


# ==================== clear_exported_state ====================


class TestClearExportedState:
    """Tests for clear_exported_state."""

    def test_clears_existing_file(self):
        with patch(
            "tool_modules.aa_workflow.src.workspace_exporter.EXPORT_FILE"
        ) as mock_file:
            mock_file.exists.return_value = True
            result = clear_exported_state()
            assert result is True
            mock_file.unlink.assert_called_once()

    def test_clears_nonexistent_file(self):
        with patch(
            "tool_modules.aa_workflow.src.workspace_exporter.EXPORT_FILE"
        ) as mock_file:
            mock_file.exists.return_value = False
            result = clear_exported_state()
            assert result is True
            mock_file.unlink.assert_not_called()

    def test_handles_unlink_error(self):
        with patch(
            "tool_modules.aa_workflow.src.workspace_exporter.EXPORT_FILE"
        ) as mock_file:
            mock_file.exists.return_value = True
            mock_file.unlink.side_effect = OSError("Permission denied")
            result = clear_exported_state()
            assert result is False


# ==================== export_workspace_state ====================


class TestExportWorkspaceState:
    """Tests for export_workspace_state."""

    def test_preserves_existing_data(self):
        with patch(
            "tool_modules.aa_workflow.src.workspace_exporter.EXPORT_FILE"
        ) as mock_file:
            with patch(
                "tool_modules.aa_workflow.src.workspace_exporter.export_workspace_state_with_data"
            ) as mock_export_with_data:
                mock_file.exists.return_value = True
                existing = {
                    "services": {"slack": {"running": True}},
                    "ollama": {"npu": {"available": True}},
                    "cron": {"enabled": True},
                    "slack_channels": ["general"],
                    "sprint_issues": [{"key": "AAP-1"}],
                    "sprint_issues_updated": "2024-01-01",
                    "meet": {"upcoming": []},
                    "sprint": {"currentSprint": "S1"},
                    "sprint_history": [{"name": "S0"}],
                    "performance": {"quarterly": {}},
                }
                m = mock_open(read_data=json.dumps(existing))
                with patch("builtins.open", m):
                    mock_export_with_data.return_value = {"success": True}
                    export_workspace_state()
                    mock_export_with_data.assert_called_once()
                    call_kwargs = mock_export_with_data.call_args
                    assert call_kwargs.kwargs.get("services") == existing["services"]
                    assert call_kwargs.kwargs.get("ollama") == existing["ollama"]
                    assert call_kwargs.kwargs.get("cron") == existing["cron"]
                    assert (
                        call_kwargs.kwargs.get("performance") == existing["performance"]
                    )

    def test_no_existing_file(self):
        with patch(
            "tool_modules.aa_workflow.src.workspace_exporter.EXPORT_FILE"
        ) as mock_file:
            with patch(
                "tool_modules.aa_workflow.src.workspace_exporter.export_workspace_state_with_data"
            ) as mock_export_with_data:
                mock_file.exists.return_value = False
                mock_export_with_data.return_value = {"success": True}
                result = export_workspace_state()
                assert result == {"success": True}

    def test_existing_file_bad_json(self):
        with patch(
            "tool_modules.aa_workflow.src.workspace_exporter.EXPORT_FILE"
        ) as mock_file:
            with patch(
                "tool_modules.aa_workflow.src.workspace_exporter.export_workspace_state_with_data"
            ) as mock_export_with_data:
                mock_file.exists.return_value = True
                m = mock_open(read_data="broken json")
                with patch("builtins.open", m):
                    mock_export_with_data.return_value = {"success": True}
                    result = export_workspace_state()
                    # Should still call export_with_data with None values
                    assert result == {"success": True}


# ==================== export_workspace_state_with_data ====================


class TestExportWorkspaceStateWithData:
    """Tests for export_workspace_state_with_data."""

    def test_successful_export(self):
        with patch("server.workspace_state.WorkspaceRegistry") as mock_registry:
            with patch(
                "tool_modules.aa_workflow.src.workspace_exporter.EXPORT_DIR"
            ) as mock_dir:
                with patch(
                    "tool_modules.aa_workflow.src.workspace_exporter.EXPORT_FILE"
                ) as mock_file:
                    mock_registry.sync_all_with_cursor.return_value = {
                        "added": 1,
                        "removed": 0,
                        "renamed": 0,
                    }
                    mock_registry.cleanup_stale.return_value = 0
                    mock_registry.get_all_as_dict.return_value = {
                        "ws1": {"project": "test", "sessions": {}}
                    }
                    mock_registry.get_all_sessions.return_value = [
                        {"id": "s1", "name": "session1"}
                    ]
                    mock_file.exists.return_value = False
                    mock_dir.mkdir = MagicMock()

                    with (
                        patch(
                            "tempfile.mkstemp",
                            return_value=(99, "/tmp/test_tmp"),
                        ),
                        patch(
                            "os.fdopen",
                            return_value=MagicMock(
                                __enter__=MagicMock(), __exit__=MagicMock()
                            ),
                        ),
                        patch("os.replace"),
                    ):
                        result = export_workspace_state_with_data(
                            services={"slack": {"running": True}},
                        )
                        assert result["success"] is True
                        assert result["workspace_count"] == 1
                        assert result["session_count"] == 1

    def test_preserves_workspaces_when_registry_empty(self):
        with patch("server.workspace_state.WorkspaceRegistry") as mock_registry:
            with patch(
                "tool_modules.aa_workflow.src.workspace_exporter.EXPORT_DIR"
            ) as mock_dir:
                with patch(
                    "tool_modules.aa_workflow.src.workspace_exporter.EXPORT_FILE"
                ) as mock_file:
                    mock_registry.sync_all_with_cursor.return_value = {
                        "added": 0,
                        "removed": 0,
                        "renamed": 0,
                    }
                    mock_registry.get_all_as_dict.return_value = {}
                    mock_registry.get_all_sessions.return_value = []
                    mock_file.exists.return_value = True
                    mock_dir.mkdir = MagicMock()

                    existing = {
                        "workspaces": {"ws1": {"project": "saved"}},
                        "sessions": [{"id": "s1"}],
                    }
                    m = mock_open(read_data=json.dumps(existing))
                    with (
                        patch("builtins.open", m),
                        patch(
                            "tempfile.mkstemp",
                            return_value=(99, "/tmp/test_tmp"),
                        ),
                        patch(
                            "os.fdopen",
                            return_value=MagicMock(
                                __enter__=MagicMock(), __exit__=MagicMock()
                            ),
                        ),
                        patch("os.replace"),
                    ):
                        result = export_workspace_state_with_data()
                        # Preserved the existing workspace
                        assert result["workspace_count"] == 1

    def test_cleanup_stale(self):
        with patch("server.workspace_state.WorkspaceRegistry") as mock_registry:
            with patch(
                "tool_modules.aa_workflow.src.workspace_exporter.EXPORT_DIR"
            ) as mock_dir:
                with patch(
                    "tool_modules.aa_workflow.src.workspace_exporter.EXPORT_FILE"
                ) as mock_file:
                    mock_registry.sync_all_with_cursor.return_value = {
                        "added": 0,
                        "removed": 0,
                        "renamed": 0,
                    }
                    mock_registry.cleanup_stale.return_value = 2
                    mock_registry.get_all_as_dict.return_value = {
                        "ws1": {"sessions": {}}
                    }
                    mock_registry.get_all_sessions.return_value = []
                    mock_file.exists.return_value = False
                    mock_dir.mkdir = MagicMock()

                    with (
                        patch(
                            "tempfile.mkstemp",
                            return_value=(99, "/tmp/test_tmp"),
                        ),
                        patch(
                            "os.fdopen",
                            return_value=MagicMock(
                                __enter__=MagicMock(), __exit__=MagicMock()
                            ),
                        ),
                        patch("os.replace"),
                    ):
                        result = export_workspace_state_with_data(cleanup_stale=True)
                        mock_registry.cleanup_stale.assert_called_once_with(24)
                        assert result["cleaned_count"] == 2

    def test_write_failure(self):
        with patch("server.workspace_state.WorkspaceRegistry") as mock_registry:
            with patch(
                "tool_modules.aa_workflow.src.workspace_exporter.EXPORT_DIR"
            ) as mock_dir:
                with patch(
                    "tool_modules.aa_workflow.src.workspace_exporter.EXPORT_FILE"
                ) as mock_file:
                    mock_registry.sync_all_with_cursor.return_value = {
                        "added": 0,
                        "removed": 0,
                        "renamed": 0,
                    }
                    mock_registry.get_all_as_dict.return_value = {}
                    mock_registry.get_all_sessions.return_value = []
                    mock_file.exists.return_value = False
                    mock_dir.mkdir = MagicMock()

                    with patch("tempfile.mkstemp", side_effect=OSError("No space")):
                        result = export_workspace_state_with_data()
                        assert result["success"] is False
                        assert "No space" in result["error"]


# ==================== export_workspace_state_async ====================


class TestExportWorkspaceStateAsync:
    """Tests for export_workspace_state_async."""

    @pytest.mark.asyncio
    async def test_without_ctx(self):
        with patch("server.workspace_state.WorkspaceRegistry") as mock_registry:
            with patch(
                "tool_modules.aa_workflow.src.workspace_exporter.export_workspace_state"
            ) as mock_export:
                mock_registry.get_all_as_dict.return_value = {}
                mock_export.return_value = {"success": True}
                result = await export_workspace_state_async()
                assert result["success"] is True

    @pytest.mark.asyncio
    async def test_with_ctx(self):
        with patch("server.workspace_state.WorkspaceRegistry") as mock_registry:
            with patch(
                "tool_modules.aa_workflow.src.workspace_exporter.export_workspace_state"
            ) as mock_export:
                ctx = MagicMock()
                state = MagicMock()
                state.workspace_uri = "file:///test"
                state.project = "test-project"
                mock_registry.get_for_ctx = AsyncMock(return_value=state)
                mock_registry.get_all_as_dict.return_value = {"ws1": {}}
                mock_export.return_value = {
                    "success": True,
                    "workspace_count": 1,
                }
                result = await export_workspace_state_async(ctx=ctx)
                assert result["success"] is True
                mock_registry.get_for_ctx.assert_awaited_once()


# ==================== _on_workspace_change ====================


class TestOnWorkspaceChange:
    """Tests for _on_workspace_change hook."""

    def test_calls_export(self):
        with patch(
            "tool_modules.aa_workflow.src.workspace_exporter.export_workspace_state"
        ) as mock_export:
            from tool_modules.aa_workflow.src.workspace_exporter import (
                _on_workspace_change,
            )

            mock_export.return_value = {"success": True}
            _on_workspace_change()
            mock_export.assert_called_once()
            assert mock_export.call_count == 1
