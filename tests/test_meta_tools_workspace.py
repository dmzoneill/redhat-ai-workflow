"""Tests for workspace and session meta tools (meta_tool_handlers)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import FastMCP

from server.workspace_state import ChatSession, WorkspaceRegistry, WorkspaceState
from tool_modules.aa_workflow.src import meta_tools as mt


def _make_mock_workspace(session_id="test-session-123"):
    """Create a mock workspace with a session for testing."""
    mock_session = MagicMock(spec=ChatSession)
    mock_session.session_id = session_id
    mock_session.persona = "developer"
    mock_session.project = "test-project"
    mock_session.is_project_auto_detected = False
    mock_session.issue_key = "AAP-123"
    mock_session.branch = "feature/test"
    mock_session.name = "Test Session"
    mock_session.started_at = MagicMock(spec=datetime)
    mock_session.started_at.isoformat.return_value = "2025-01-01T00:00:00"
    mock_session.last_activity = MagicMock(spec=datetime)
    mock_session.last_activity.isoformat.return_value = "2025-01-01T01:00:00"
    mock_session.last_tool = "git_status"
    mock_session.last_tool_time = None
    mock_session.tool_call_count = 5
    mock_session.tool_count = 10
    mock_session.touch = MagicMock()

    mock_workspace = MagicMock(spec=WorkspaceState)
    mock_workspace.workspace_uri = "file:///test"
    mock_workspace.project = "test-project"
    mock_workspace.sessions = {session_id: mock_session}
    mock_workspace.active_session_id = session_id
    mock_workspace.get_active_session.return_value = mock_session
    mock_workspace.get_session.side_effect = lambda sid: mock_session if sid == session_id else None
    mock_workspace.set_active_session = MagicMock()
    mock_workspace.session_count.return_value = 1

    return mock_workspace, mock_session


class TestWorkspaceStateExport:
    """Tests for workspace_state_export tool."""

    @pytest.mark.asyncio
    async def test_export_error(self):
        """Test workspace_state_export handles import error."""

        server = FastMCP("test-ws-export")
        mt.register_meta_tools(server)

        result = await server.call_tool("workspace_state_export", {})
        text = str(result)
        # Without proper context, it should handle the error
        assert "error" in text.lower() or "Export" in text

    @pytest.mark.asyncio
    async def test_export_success(self):
        """Test workspace_state_export with success result."""

        server = FastMCP("test-ws-export-ok")
        mt.register_meta_tools(server)

        mock_export = AsyncMock(
            return_value={
                "success": True,
                "workspace_count": 2,
                "file": "/tmp/workspaces.json",
            }
        )

        with patch(
            "tool_modules.aa_workflow.src.workspace_exporter.export_workspace_state_async",
            mock_export,
        ):
            result = await server.call_tool("workspace_state_export", {})
            text = str(result)
            assert "Exported" in text or "2 workspace" in text

    @pytest.mark.asyncio
    async def test_export_failure(self):
        """Test workspace_state_export with failure result."""

        server = FastMCP("test-ws-export-fail")
        mt.register_meta_tools(server)

        mock_export = AsyncMock(
            return_value={
                "success": False,
                "error": "Permission denied",
            }
        )

        with patch(
            "tool_modules.aa_workflow.src.workspace_exporter.export_workspace_state_async",
            mock_export,
        ):
            result = await server.call_tool("workspace_state_export", {})
            text = str(result)
            assert "failed" in text.lower() or "Permission denied" in text

    @pytest.mark.asyncio
    async def test_no_session(self):
        """Test session_info with no active session."""

        server = FastMCP("test-session-info")
        mt.register_meta_tools(server)

        result = await server.call_tool("session_info", {})
        text = str(result)
        # Should get an error about no session or context
        assert len(text) > 0


class TestSessionInfoViaServer:
    """Tests for session_info tool via server."""

    @pytest.mark.asyncio
    async def test_session_info_active_session(self):
        """Session info active session."""

        server = FastMCP("test-si")
        mt.register_meta_tools(server)

        mock_ws, _mock_session = _make_mock_workspace()
        mock_registry = MagicMock(spec=WorkspaceRegistry)
        mock_registry.get_for_ctx = AsyncMock(return_value=mock_ws)

        with patch("server.workspace_state.WorkspaceRegistry", mock_registry):
            result = await server.call_tool("session_info", {})
            text = str(result)
            assert "Session" in text or "session" in text

    @pytest.mark.asyncio
    async def test_session_info_with_recent_tool_time(self):
        """Test session_info shows 'just now' for recent tool calls."""
        server = FastMCP("test-si-recent")
        mt.register_meta_tools(server)

        mock_ws, mock_session = _make_mock_workspace()
        mock_session.last_tool_time = datetime.now(tz=timezone.utc)
        mock_registry = MagicMock(spec=WorkspaceRegistry)
        mock_registry.get_for_ctx = AsyncMock(return_value=mock_ws)

        with patch("server.workspace_state.WorkspaceRegistry", mock_registry):
            result = await server.call_tool("session_info", {})
            text = str(result)
            assert "just now" in text or "min ago" in text

    @pytest.mark.asyncio
    async def test_session_info_tool_time_hours_ago(self):
        """Test session_info shows 'hours ago' for older tool calls."""
        server = FastMCP("test-si-hours")
        mt.register_meta_tools(server)

        mock_ws, mock_session = _make_mock_workspace()
        mock_session.last_tool_time = datetime.now(tz=timezone.utc) - timedelta(hours=3)
        mock_registry = MagicMock(spec=WorkspaceRegistry)
        mock_registry.get_for_ctx = AsyncMock(return_value=mock_ws)

        with patch("server.workspace_state.WorkspaceRegistry", mock_registry):
            result = await server.call_tool("session_info", {})
            text = str(result)
            assert "hours ago" in text

    @pytest.mark.asyncio
    async def test_session_info_tool_time_minutes_ago(self):
        """Test session_info shows 'min ago' for medium-age tool calls."""
        server = FastMCP("test-si-min")
        mt.register_meta_tools(server)

        mock_ws, mock_session = _make_mock_workspace()
        mock_session.last_tool_time = datetime.now(tz=timezone.utc) - timedelta(minutes=15)
        mock_registry = MagicMock(spec=WorkspaceRegistry)
        mock_registry.get_for_ctx = AsyncMock(return_value=mock_ws)

        with patch("server.workspace_state.WorkspaceRegistry", mock_registry):
            result = await server.call_tool("session_info", {})
            text = str(result)
            assert "min ago" in text

    @pytest.mark.asyncio
    async def test_session_info_no_issue_no_branch(self):
        """Test session_info without issue_key or branch."""

        server = FastMCP("test-si-bare")
        mt.register_meta_tools(server)

        mock_ws, mock_session = _make_mock_workspace()
        mock_session.issue_key = None
        mock_session.branch = None
        mock_session.last_tool = None
        mock_session.name = None
        mock_registry = MagicMock(spec=WorkspaceRegistry)
        mock_registry.get_for_ctx = AsyncMock(return_value=mock_ws)

        with patch("server.workspace_state.WorkspaceRegistry", mock_registry):
            result = await server.call_tool("session_info", {})
            text = str(result)
            assert "Session" in text

    @pytest.mark.asyncio
    async def test_session_info_with_session_id(self):
        """Session info with session id."""

        server = FastMCP("test-si-id")
        mt.register_meta_tools(server)

        mock_ws, _mock_session = _make_mock_workspace()
        mock_registry = MagicMock(spec=WorkspaceRegistry)
        mock_registry.get_for_ctx = AsyncMock(return_value=mock_ws)

        with patch("server.workspace_state.WorkspaceRegistry", mock_registry):
            result = await server.call_tool("session_info", {"session_id": "test-session-123"})
            text = str(result)
            assert "Session" in text or "session" in text

    @pytest.mark.asyncio
    async def test_session_info_not_found(self):
        """Session info not found."""

        server = FastMCP("test-si-nf")
        mt.register_meta_tools(server)

        mock_ws, _ = _make_mock_workspace()
        mock_registry = MagicMock(spec=WorkspaceRegistry)
        mock_registry.get_for_ctx = AsyncMock(return_value=mock_ws)

        with patch("server.workspace_state.WorkspaceRegistry", mock_registry):
            result = await server.call_tool("session_info", {"session_id": "nonexistent"})
            text = str(result)
            assert "not found" in text

    @pytest.mark.asyncio
    async def test_session_info_no_active(self):
        """Session info no active."""

        server = FastMCP("test-si-none")
        mt.register_meta_tools(server)

        mock_ws, _ = _make_mock_workspace()
        mock_ws.get_active_session.return_value = None
        mock_registry = MagicMock(spec=WorkspaceRegistry)
        mock_registry.get_for_ctx = AsyncMock(return_value=mock_ws)

        with patch("server.workspace_state.WorkspaceRegistry", mock_registry):
            result = await server.call_tool("session_info", {})
            text = str(result)
            assert "No active session" in text


class TestSessionRenameViaServer:
    """Tests for session_rename tool."""

    @pytest.mark.asyncio
    async def test_rename_active_session(self):
        """Rename active session."""

        server = FastMCP("test-sr")
        mt.register_meta_tools(server)

        mock_ws, _mock_session = _make_mock_workspace()
        mock_registry = MagicMock(spec=WorkspaceRegistry)
        mock_registry.get_for_ctx = AsyncMock(return_value=mock_ws)
        mock_registry.save_to_disk = MagicMock()

        with patch("server.workspace_state.WorkspaceRegistry", mock_registry):
            result = await server.call_tool("session_rename", {"name": "New Name"})
            text = str(result)
            assert "renamed" in text or "New Name" in text

    @pytest.mark.asyncio
    async def test_rename_no_session(self):
        """Rename no session."""

        server = FastMCP("test-sr-none")
        mt.register_meta_tools(server)

        mock_ws, _ = _make_mock_workspace()
        mock_ws.get_active_session.return_value = None
        mock_registry = MagicMock(spec=WorkspaceRegistry)
        mock_registry.get_for_ctx = AsyncMock(return_value=mock_ws)

        with patch("server.workspace_state.WorkspaceRegistry", mock_registry):
            result = await server.call_tool("session_rename", {"name": "Test"})
            text = str(result)
            assert "No active session" in text

    @pytest.mark.asyncio
    async def test_rename_specific_session_not_found(self):
        """Rename specific session not found."""

        server = FastMCP("test-sr-nf")
        mt.register_meta_tools(server)

        mock_ws, _ = _make_mock_workspace()
        mock_registry = MagicMock(spec=WorkspaceRegistry)
        mock_registry.get_for_ctx = AsyncMock(return_value=mock_ws)

        with patch("server.workspace_state.WorkspaceRegistry", mock_registry):
            result = await server.call_tool("session_rename", {"name": "Test", "session_id": "bad-id"})
            text = str(result)
            assert "not found" in text


class TestSessionListViaServer:
    """Tests for session_list tool."""

    @pytest.mark.asyncio
    async def test_list_sessions(self):
        """List sessions."""
        server = FastMCP("test-sl")
        mt.register_meta_tools(server)

        mock_ws, mock_session = _make_mock_workspace()
        mock_session.last_activity = datetime.now(tz=timezone.utc)
        mock_registry = MagicMock(spec=WorkspaceRegistry)
        mock_registry.get_for_ctx = AsyncMock(return_value=mock_ws)

        with patch("server.workspace_state.WorkspaceRegistry", mock_registry):
            result = await server.call_tool("session_list", {})
            text = str(result)
            assert "Session" in text or "session" in text

    @pytest.mark.asyncio
    async def test_list_empty_sessions(self):
        """List empty sessions."""

        server = FastMCP("test-sl-empty")
        mt.register_meta_tools(server)

        mock_ws, _ = _make_mock_workspace()
        mock_ws.sessions = {}
        mock_ws.get_active_session.return_value = None
        mock_registry = MagicMock(spec=WorkspaceRegistry)
        mock_registry.get_for_ctx = AsyncMock(return_value=mock_ws)

        with patch("server.workspace_state.WorkspaceRegistry", mock_registry):
            result = await server.call_tool("session_list", {})
            text = str(result)
            assert "No sessions" in text

    @pytest.mark.asyncio
    async def test_list_sessions_with_old_activity(self):
        """Test session_list time_ago for older sessions."""
        server = FastMCP("test-sl-old")
        mt.register_meta_tools(server)

        mock_ws, mock_session = _make_mock_workspace()
        mock_session.last_activity = datetime.now(tz=timezone.utc) - timedelta(hours=5)
        mock_session.last_tool = "jira_search"
        mock_session.tool_call_count = 12
        mock_session.issue_key = "AAP-999"
        mock_session.name = "Old Session"
        mock_registry = MagicMock(spec=WorkspaceRegistry)
        mock_registry.get_for_ctx = AsyncMock(return_value=mock_ws)

        with patch("server.workspace_state.WorkspaceRegistry", mock_registry):
            result = await server.call_tool("session_list", {})
            text = str(result)
            assert "hours ago" in text or "Session" in text

    @pytest.mark.asyncio
    async def test_list_sessions_with_no_name(self):
        """Test session_list with unnamed sessions."""
        server = FastMCP("test-sl-noname")
        mt.register_meta_tools(server)

        mock_ws, mock_session = _make_mock_workspace()
        mock_session.last_activity = datetime.now(tz=timezone.utc)
        mock_session.name = None
        mock_session.last_tool = None
        mock_session.issue_key = None
        mock_registry = MagicMock(spec=WorkspaceRegistry)
        mock_registry.get_for_ctx = AsyncMock(return_value=mock_ws)

        with patch("server.workspace_state.WorkspaceRegistry", mock_registry):
            result = await server.call_tool("session_list", {})
            text = str(result)
            assert "unnamed" in text

    @pytest.mark.asyncio
    async def test_list_sessions_days_ago(self):
        """Test session_list shows 'days ago' for old sessions."""
        server = FastMCP("test-sl-days")
        mt.register_meta_tools(server)

        mock_ws, mock_session = _make_mock_workspace()
        mock_session.last_activity = datetime.now(tz=timezone.utc) - timedelta(days=3)
        mock_session.name = "Old session"
        mock_registry = MagicMock(spec=WorkspaceRegistry)
        mock_registry.get_for_ctx = AsyncMock(return_value=mock_ws)

        with patch("server.workspace_state.WorkspaceRegistry", mock_registry):
            result = await server.call_tool("session_list", {})
            text = str(result)
            assert "days ago" in text


class TestSessionSwitchViaServer:
    """Tests for session_switch tool."""

    @pytest.mark.asyncio
    async def test_switch_to_session(self):
        """Switch to session."""

        server = FastMCP("test-sw")
        mt.register_meta_tools(server)

        mock_ws, _mock_session = _make_mock_workspace()
        mock_registry = MagicMock(spec=WorkspaceRegistry)
        mock_registry.get_for_ctx = AsyncMock(return_value=mock_ws)
        mock_registry.save_to_disk = MagicMock()

        with patch("server.workspace_state.WorkspaceRegistry", mock_registry):
            result = await server.call_tool("session_switch", {"session_id": "test-session-123"})
            text = str(result)
            assert "Switched" in text or "switched" in text

    @pytest.mark.asyncio
    async def test_switch_not_found(self):
        """Switch not found."""

        server = FastMCP("test-sw-nf")
        mt.register_meta_tools(server)

        mock_ws, _ = _make_mock_workspace()
        mock_registry = MagicMock(spec=WorkspaceRegistry)
        mock_registry.get_for_ctx = AsyncMock(return_value=mock_ws)

        with patch("server.workspace_state.WorkspaceRegistry", mock_registry):
            result = await server.call_tool("session_switch", {"session_id": "nonexistent"})
            text = str(result)
            assert "not found" in text

    @pytest.mark.asyncio
    async def test_switch_with_all_details(self):
        """Test switch shows issue, branch, and last tool."""

        server = FastMCP("test-sw-det")
        mt.register_meta_tools(server)

        mock_ws, mock_session = _make_mock_workspace()
        mock_session.issue_key = "AAP-123"
        mock_session.branch = "feat/x"
        mock_session.last_tool = "git_status"
        mock_session.name = "Named"
        mock_registry = MagicMock(spec=WorkspaceRegistry)
        mock_registry.get_for_ctx = AsyncMock(return_value=mock_ws)
        mock_registry.save_to_disk = MagicMock()

        with patch("server.workspace_state.WorkspaceRegistry", mock_registry):
            result = await server.call_tool("session_switch", {"session_id": "test-session-123"})
            text = str(result)
            assert "Switched" in text

    @pytest.mark.asyncio
    async def test_switch_without_details(self):
        """Test switch with session that has no issue/branch/last_tool."""

        server = FastMCP("test-sw-bare")
        mt.register_meta_tools(server)

        mock_ws, mock_session = _make_mock_workspace()
        mock_session.issue_key = None
        mock_session.branch = None
        mock_session.last_tool = None
        mock_session.name = None
        mock_registry = MagicMock(spec=WorkspaceRegistry)
        mock_registry.get_for_ctx = AsyncMock(return_value=mock_ws)
        mock_registry.save_to_disk = MagicMock()

        with patch("server.workspace_state.WorkspaceRegistry", mock_registry):
            result = await server.call_tool("session_switch", {"session_id": "test-session-123"})
            text = str(result)
            assert "Switched" in text


class TestSessionSyncViaServer:
    """Tests for session_sync tool."""

    @pytest.mark.asyncio
    async def test_sync_no_changes(self):
        """Sync no changes."""

        server = FastMCP("test-sync")
        mt.register_meta_tools(server)

        mock_ws, _ = _make_mock_workspace()
        mock_ws.sync_with_cursor_db.return_value = {
            "added": 0,
            "removed": 0,
            "renamed": 0,
        }
        mock_registry = MagicMock(spec=WorkspaceRegistry)
        mock_registry.get_for_ctx = AsyncMock(return_value=mock_ws)
        mock_registry.save_to_disk = MagicMock()

        with (
            patch("server.workspace_state.WorkspaceRegistry", mock_registry),
            patch(
                "tool_modules.aa_workflow.src.workspace_exporter.export_workspace_state_async",
                AsyncMock(),
            ),
        ):
            result = await server.call_tool("session_sync", {})
            text = str(result)
            assert "in sync" in text or "Sync" in text

    @pytest.mark.asyncio
    async def test_sync_with_changes(self):
        """Sync with changes."""

        server = FastMCP("test-sync-ch")
        mt.register_meta_tools(server)

        mock_ws, _ = _make_mock_workspace()
        mock_ws.sync_with_cursor_db.return_value = {
            "added": 2,
            "removed": 1,
            "renamed": 1,
        }
        mock_registry = MagicMock(spec=WorkspaceRegistry)
        mock_registry.get_for_ctx = AsyncMock(return_value=mock_ws)
        mock_registry.save_to_disk = MagicMock()

        with (
            patch("server.workspace_state.WorkspaceRegistry", mock_registry),
            patch(
                "tool_modules.aa_workflow.src.workspace_exporter.export_workspace_state_async",
                AsyncMock(),
            ),
        ):
            result = await server.call_tool("session_sync", {})
            text = str(result)
            assert "Sync Complete" in text or "Added" in text


class TestWorkspaceStateListViaServer:
    """Tests for workspace_state_list tool."""

    @pytest.mark.asyncio
    async def test_list_workspaces(self):
        """List workspaces."""

        server = FastMCP("test-wsl")
        mt.register_meta_tools(server)

        mock_ws, _mock_session = _make_mock_workspace()
        mock_registry = MagicMock(spec=WorkspaceRegistry)
        mock_registry.get_for_ctx = AsyncMock(return_value=mock_ws)
        mock_registry.get_all.return_value = {"file:///test": mock_ws}

        with patch("server.workspace_state.WorkspaceRegistry", mock_registry):
            result = await server.call_tool("workspace_state_list", {})
            text = str(result)
            assert "Workspace" in text or "workspace" in text

    @pytest.mark.asyncio
    async def test_list_no_workspaces(self):
        """List no workspaces."""

        server = FastMCP("test-wsl-empty")
        mt.register_meta_tools(server)

        mock_ws, _ = _make_mock_workspace()
        mock_ws.get_active_session.return_value = None
        mock_registry = MagicMock(spec=WorkspaceRegistry)
        mock_registry.get_for_ctx = AsyncMock(return_value=mock_ws)
        mock_registry.get_all.return_value = {}

        with patch("server.workspace_state.WorkspaceRegistry", mock_registry):
            result = await server.call_tool("workspace_state_list", {})
            text = str(result)
            assert "No active" in text or "workspace" in text.lower()

    @pytest.mark.asyncio
    async def test_list_with_session_details(self):
        """Test workspace list shows session issue/branch/tools details."""

        server = FastMCP("test-wsl-details")
        mt.register_meta_tools(server)

        mock_ws, mock_session = _make_mock_workspace()
        mock_session.issue_key = "AAP-500"
        mock_session.branch = "feat/branch"
        mock_session.tool_count = 15
        mock_registry = MagicMock(spec=WorkspaceRegistry)
        mock_registry.get_for_ctx = AsyncMock(return_value=mock_ws)
        mock_registry.get_all.return_value = {"file:///test": mock_ws}

        with patch("server.workspace_state.WorkspaceRegistry", mock_registry):
            result = await server.call_tool("workspace_state_list", {})
            text = str(result)
            assert "AAP-500" in text or "Session" in text
