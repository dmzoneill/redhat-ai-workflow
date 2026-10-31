"""Tests for WorkspaceRegistry: workspace lookup, project detection and isolation."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import Context
from mcp.shared.exceptions import MCPError
from mcp.types import METHOD_NOT_FOUND, ListRootsResult

import server.workspace_state as ws_module
from server.workspace_state import (
    DEFAULT_WORKSPACE,
    SESSION_STALE_HOURS,
    WorkspaceRegistry,
    detect_project,
    get_default_persona,
    get_workspace_state,
)


class TestWorkspaceRegistry:
    """Tests for WorkspaceRegistry."""

    def setup_method(self):
        """Clear registry before each test."""
        WorkspaceRegistry.clear()

    def teardown_method(self):
        """Clear registry after each test."""
        WorkspaceRegistry.clear()

    @pytest.mark.asyncio
    async def test_get_for_ctx_creates_new_state(self):
        """Test that get_for_ctx creates new state for unknown workspace."""
        mock_ctx = MagicMock(spec=Context)
        mock_ctx.session = AsyncMock()
        mock_roots = MagicMock(spec=ListRootsResult)
        mock_roots.roots = [MagicMock(uri="file:///home/user/project")]
        mock_ctx.session.list_roots = AsyncMock(return_value=mock_roots)

        state = await WorkspaceRegistry.get_for_ctx(mock_ctx)

        assert state.workspace_uri == "file:///home/user/project"
        assert WorkspaceRegistry.count() == 1

    @pytest.mark.asyncio
    async def test_get_for_ctx_returns_existing_state(self):
        """Test that get_for_ctx returns existing state for known workspace."""
        mock_ctx = MagicMock(spec=Context)
        mock_ctx.session = AsyncMock()
        mock_roots = MagicMock(spec=ListRootsResult)
        mock_roots.roots = [MagicMock(uri="file:///home/user/project")]
        mock_ctx.session.list_roots = AsyncMock(return_value=mock_roots)

        state1 = await WorkspaceRegistry.get_for_ctx(mock_ctx)
        state1.project = "modified-project"

        state2 = await WorkspaceRegistry.get_for_ctx(mock_ctx)

        assert state2.project == "modified-project"
        assert state1 is state2
        assert WorkspaceRegistry.count() == 1

    @pytest.mark.asyncio
    async def test_workspace_isolation(self):
        """Test that different workspaces have isolated state."""
        mock_ctx1 = MagicMock(spec=Context)
        mock_ctx1.session = AsyncMock()
        mock_roots1 = MagicMock(spec=ListRootsResult)
        mock_roots1.roots = [MagicMock(uri="file:///workspace1")]
        mock_ctx1.session.list_roots = AsyncMock(return_value=mock_roots1)

        mock_ctx2 = MagicMock(spec=Context)
        mock_ctx2.session = AsyncMock()
        mock_roots2 = MagicMock(spec=ListRootsResult)
        mock_roots2.roots = [MagicMock(uri="file:///workspace2")]
        mock_ctx2.session.list_roots = AsyncMock(return_value=mock_roots2)

        state1 = await WorkspaceRegistry.get_for_ctx(mock_ctx1)
        state2 = await WorkspaceRegistry.get_for_ctx(mock_ctx2)

        # Set different projects
        state1.project = "project1"
        state2.project = "project2"

        # Verify isolation
        assert state1.project == "project1"
        assert state2.project == "project2"
        assert WorkspaceRegistry.count() == 2

    @pytest.mark.asyncio
    async def test_fallback_to_default_workspace(self):
        """Test fallback to default workspace when list_roots fails."""
        mock_ctx = MagicMock(spec=Context)
        mock_ctx.session = AsyncMock()
        mock_ctx.session.list_roots = AsyncMock(side_effect=MCPError(METHOD_NOT_FOUND, "Not supported"))

        state = await WorkspaceRegistry.get_for_ctx(mock_ctx)

        assert state.workspace_uri == DEFAULT_WORKSPACE
        assert WorkspaceRegistry.count() == 1

    @pytest.mark.asyncio
    async def test_fallback_when_no_session(self):
        """Test fallback when context has no session."""
        mock_ctx = MagicMock(spec=Context)
        mock_ctx.session = None

        state = await WorkspaceRegistry.get_for_ctx(mock_ctx)

        assert state.workspace_uri == DEFAULT_WORKSPACE

    def test_get_or_create_sync(self):
        """Test synchronous get_or_create method."""
        state1 = WorkspaceRegistry.get_or_create("file:///test1", ensure_session=False)
        state1.project = "test-project"

        state2 = WorkspaceRegistry.get_or_create("file:///test1", ensure_session=False)

        assert state1 is state2
        assert state2.project == "test-project"

    def test_auto_session_creation_sync(self):
        """Test that ensure_session=True auto-creates a session."""
        state = WorkspaceRegistry.get_or_create("file:///auto-session-test", ensure_session=True)

        # Session should be auto-created
        assert state.session_count() == 1
        assert state.get_active_session() is not None
        assert state.get_active_session().name == "Auto-created"
        assert state.get_active_session().persona == get_default_persona()

    @pytest.mark.asyncio
    async def test_auto_session_creation_async(self):
        """Test that get_for_ctx auto-creates a session by default."""
        mock_ctx = MagicMock(spec=Context)
        mock_ctx.session = AsyncMock()
        mock_roots = MagicMock(spec=ListRootsResult)
        mock_roots.roots = [MagicMock(uri="file:///auto-session-async")]
        mock_ctx.session.list_roots = AsyncMock(return_value=mock_roots)

        # Default behavior: ensure_session=True
        state = await WorkspaceRegistry.get_for_ctx(mock_ctx)

        # Session should be auto-created
        assert state.session_count() == 1
        assert state.get_active_session() is not None
        assert state.get_active_session().name == "Auto-created"

    def test_get_returns_none_for_unknown(self):
        """Test that get returns None for unknown workspace."""
        result = WorkspaceRegistry.get("file:///unknown")
        assert result is None

    def test_get_all(self):
        """Test getting all workspace states."""
        WorkspaceRegistry.get_or_create("file:///ws1", ensure_session=False)
        WorkspaceRegistry.get_or_create("file:///ws2", ensure_session=False)

        all_states = WorkspaceRegistry.get_all()

        assert len(all_states) == 2
        assert "file:///ws1" in all_states
        assert "file:///ws2" in all_states

    def test_get_all_as_dict(self):
        """Test getting all states as serializable dicts."""
        state = WorkspaceRegistry.get_or_create("file:///ws1", ensure_session=False)
        state.project = "test"

        result = WorkspaceRegistry.get_all_as_dict()

        assert "file:///ws1" in result
        assert result["file:///ws1"]["project"] == "test"

    def test_get_all_sessions(self):
        """Test getting all sessions across workspaces."""
        state1 = WorkspaceRegistry.get_or_create("file:///ws1", ensure_session=False)
        state1.project = "project1"
        session1 = state1.create_session(persona="developer")

        state2 = WorkspaceRegistry.get_or_create("file:///ws2", ensure_session=False)
        state2.project = "project2"
        session2a = state2.create_session(persona="devops")
        session2b = state2.create_session(persona="incident")

        sessions = WorkspaceRegistry.get_all_sessions()

        assert len(sessions) == 3
        # Check that project info is included
        session_ids = {s["session_id"] for s in sessions}
        assert session1.session_id in session_ids
        assert session2a.session_id in session_ids
        assert session2b.session_id in session_ids

    def test_total_session_count(self):
        """Test counting total sessions across workspaces."""
        state1 = WorkspaceRegistry.get_or_create("file:///ws1", ensure_session=False)
        state1.create_session()
        state1.create_session()

        state2 = WorkspaceRegistry.get_or_create("file:///ws2", ensure_session=False)
        state2.create_session()

        assert WorkspaceRegistry.total_session_count() == 3

    def test_remove(self):
        """Test removing a workspace state."""
        WorkspaceRegistry.get_or_create("file:///ws1", ensure_session=False)
        assert WorkspaceRegistry.count() == 1

        result = WorkspaceRegistry.remove("file:///ws1")

        assert result is True
        assert WorkspaceRegistry.count() == 0

    def test_remove_session(self):
        """Test removing a specific session."""
        state = WorkspaceRegistry.get_or_create("file:///ws1", ensure_session=False)
        session1 = state.create_session()
        session2 = state.create_session()

        result = WorkspaceRegistry.remove_session("file:///ws1", session1.session_id)

        assert result is True
        assert state.session_count() == 1
        assert state.get_session(session1.session_id) is None
        assert state.get_session(session2.session_id) is not None

    def test_clear(self):
        """Test clearing all workspace states."""
        WorkspaceRegistry.get_or_create("file:///ws1", ensure_session=False)
        WorkspaceRegistry.get_or_create("file:///ws2", ensure_session=False)
        assert WorkspaceRegistry.count() == 2

        WorkspaceRegistry.clear()

        assert WorkspaceRegistry.count() == 0


class TestProjectDetection:
    """Tests for project detection from workspace URI."""

    def setup_method(self):
        """Clear registry before each test."""
        WorkspaceRegistry.clear()

    def teardown_method(self):
        """Clear registry after each test."""
        WorkspaceRegistry.clear()

    @pytest.mark.asyncio
    async def test_detect_project_from_config(self):
        """Test project detection from config.json repositories."""
        mock_config = {
            "repositories": {
                "test-project": {"path": "/home/user/src/test-project"},
                "other-project": {"path": "/home/user/src/other"},
            }
        }

        with patch("server.utils.load_config", return_value=mock_config):
            result = detect_project("file:///home/user/src/test-project")

        assert result == "test-project"

    @pytest.mark.asyncio
    async def test_detect_project_subdirectory(self):
        """Test project detection from subdirectory."""
        mock_config = {
            "repositories": {
                "test-project": {"path": "/home/user/src/test-project"},
            }
        }

        with patch("server.utils.load_config", return_value=mock_config):
            result = detect_project("file:///home/user/src/test-project/src/module")

        assert result == "test-project"

    @pytest.mark.asyncio
    async def test_detect_project_no_match(self):
        """Test project detection returns None when no match."""
        mock_config = {
            "repositories": {
                "test-project": {"path": "/home/user/src/test-project"},
            }
        }

        with patch("server.utils.load_config", return_value=mock_config):
            result = detect_project("file:///home/user/src/unknown")

        assert result is None

    @pytest.mark.asyncio
    async def test_auto_detect_on_create(self):
        """Test that project is auto-detected when workspace is created."""
        mock_config = {
            "repositories": {
                "auto-detected": {"path": "/home/user/src/auto-detected"},
            }
        }

        mock_ctx = MagicMock(spec=Context)
        mock_ctx.session = AsyncMock()
        mock_roots = MagicMock(spec=ListRootsResult)
        mock_roots.roots = [MagicMock(uri="file:///home/user/src/auto-detected")]
        mock_ctx.session.list_roots = AsyncMock(return_value=mock_roots)

        with patch("server.utils.load_config", return_value=mock_config):
            state = await WorkspaceRegistry.get_for_ctx(mock_ctx)

        assert state.project == "auto-detected"
        assert state.is_auto_detected is True


class TestGetWorkspaceState:
    """Tests for the convenience function."""

    def setup_method(self):
        """Clear registry before each test."""
        WorkspaceRegistry.clear()

    def teardown_method(self):
        """Clear registry after each test."""
        WorkspaceRegistry.clear()

    @pytest.mark.asyncio
    async def test_get_workspace_state(self):
        """Test the convenience function."""
        mock_ctx = MagicMock(spec=Context)
        mock_ctx.session = AsyncMock()
        mock_roots = MagicMock(spec=ListRootsResult)
        mock_roots.roots = [MagicMock(uri="file:///test")]
        mock_ctx.session.list_roots = AsyncMock(return_value=mock_roots)

        state = await get_workspace_state(mock_ctx)

        assert state.workspace_uri == "file:///test"


class TestMultiWorkspaceIntegration:
    """Integration tests for multi-workspace scenarios.

    These tests simulate real-world usage where multiple Cursor chats
    are working on different projects simultaneously.
    """

    def setup_method(self):
        """Clear registry before each test."""
        WorkspaceRegistry.clear()

    def teardown_method(self):
        """Clear registry after each test."""
        WorkspaceRegistry.clear()

    def _create_mock_ctx(self, workspace_uri: str) -> MagicMock:
        """Create a mock context for a workspace."""
        mock_ctx = MagicMock(spec=Context)
        mock_ctx.session = AsyncMock()
        mock_roots = MagicMock(spec=ListRootsResult)
        mock_roots.roots = [MagicMock(uri=workspace_uri)]
        mock_ctx.session.list_roots = AsyncMock(return_value=mock_roots)
        return mock_ctx

    @pytest.mark.asyncio
    async def test_concurrent_workspace_sessions(self):
        """Test multiple workspaces can operate concurrently without interference."""
        ctx_backend = self._create_mock_ctx("file:///home/user/src/backend")
        ctx_frontend = self._create_mock_ctx("file:///home/user/src/frontend")
        ctx_infra = self._create_mock_ctx("file:///home/user/src/infrastructure")

        # Initialize all workspaces (ensure_session=False to avoid auto-session)
        state_backend = await WorkspaceRegistry.get_for_ctx(ctx_backend, ensure_session=False)
        state_frontend = await WorkspaceRegistry.get_for_ctx(ctx_frontend, ensure_session=False)
        state_infra = await WorkspaceRegistry.get_for_ctx(ctx_infra, ensure_session=False)

        # Create sessions with different contexts
        session_backend = state_backend.create_session(persona="developer")
        session_backend.issue_key = "AAP-12345"
        session_backend.branch = "aap-12345-fix-api"
        state_backend.project = "automation-analytics-backend"

        session_frontend = state_frontend.create_session(persona="developer")
        session_frontend.issue_key = "AAP-12346"
        session_frontend.branch = "aap-12346-new-dashboard"
        state_frontend.project = "automation-analytics-frontend"

        session_infra = state_infra.create_session(persona="devops")
        session_infra.issue_key = "AAP-12347"
        session_infra.branch = "aap-12347-update-config"
        state_infra.project = "app-interface"

        # Verify all states are isolated
        assert WorkspaceRegistry.count() == 3
        assert WorkspaceRegistry.total_session_count() == 3

        # Re-fetch states and verify they maintained their values
        state_backend_2 = await WorkspaceRegistry.get_for_ctx(ctx_backend)
        state_frontend_2 = await WorkspaceRegistry.get_for_ctx(ctx_frontend)
        state_infra_2 = await WorkspaceRegistry.get_for_ctx(ctx_infra)

        # Backend should still have its values
        assert state_backend_2.project == "automation-analytics-backend"
        assert state_backend_2.get_active_session().persona == "developer"
        assert state_backend_2.get_active_session().issue_key == "AAP-12345"

        # Frontend should still have its values
        assert state_frontend_2.project == "automation-analytics-frontend"
        assert state_frontend_2.get_active_session().issue_key == "AAP-12346"

        # Infra should still have its values (different persona)
        assert state_infra_2.project == "app-interface"
        assert state_infra_2.get_active_session().persona == "devops"

    @pytest.mark.asyncio
    async def test_multiple_sessions_per_workspace(self):
        """Test multiple chat sessions in the same workspace."""
        ctx = self._create_mock_ctx("file:///home/user/project")

        # Use ensure_session=False to avoid auto-session creation
        state = await WorkspaceRegistry.get_for_ctx(ctx, ensure_session=False)
        state.project = "my-project"

        # Create multiple sessions (simulating multiple chats)
        session1 = state.create_session(persona="developer", name="Feature Work")
        session1.issue_key = "AAP-100"
        session1.branch = "feature-100"

        session2 = state.create_session(persona="devops", name="Deployment")
        session2.issue_key = "AAP-200"
        session2.branch = "deploy-200"

        session3 = state.create_session(persona="incident", name="Bug Fix")
        session3.issue_key = "AAP-300"

        # All sessions should exist
        assert state.session_count() == 3

        # Most recent session should be active
        assert state.active_session_id == session3.session_id

        # Can switch between sessions
        state.set_active_session(session1.session_id)
        assert state.get_active_session().issue_key == "AAP-100"

        state.set_active_session(session2.session_id)
        assert state.get_active_session().persona == "devops"

    @pytest.mark.asyncio
    async def test_session_isolation_within_workspace(self):
        """Test that sessions within a workspace are isolated."""
        ctx = self._create_mock_ctx("file:///workspace")

        # Use ensure_session=False to avoid auto-session creation
        state = await WorkspaceRegistry.get_for_ctx(ctx, ensure_session=False)

        session1 = state.create_session(persona="developer")
        session1.issue_key = "AAP-111"
        session1.tool_filter_cache["query1"] = ["git", "gitlab"]

        session2 = state.create_session(persona="devops")
        session2.issue_key = "AAP-222"
        session2.tool_filter_cache["query1"] = ["k8s", "bonfire"]

        # Sessions should have different values
        assert session1.issue_key == "AAP-111"
        assert session2.issue_key == "AAP-222"
        assert session1.persona == "developer"
        assert session2.persona == "devops"
        assert session1.tool_filter_cache["query1"] == ["git", "gitlab"]
        assert session2.tool_filter_cache["query1"] == ["k8s", "bonfire"]

    @pytest.mark.asyncio
    async def test_workspace_state_export(self):
        """Test that all workspace states can be exported for VS Code."""
        ctx_ws1 = self._create_mock_ctx("file:///home/user/project1")
        ctx_ws2 = self._create_mock_ctx("file:///home/user/project2")

        # Use ensure_session=False to avoid auto-session creation
        state1 = await WorkspaceRegistry.get_for_ctx(ctx_ws1, ensure_session=False)
        state1.project = "project1"
        session1 = state1.create_session(persona="developer")
        session1.issue_key = "AAP-100"

        state2 = await WorkspaceRegistry.get_for_ctx(ctx_ws2, ensure_session=False)
        state2.project = "project2"
        session2 = state2.create_session(persona="devops")
        session2.issue_key = "AAP-200"

        # Export all states
        exported = WorkspaceRegistry.get_all_as_dict()

        # Verify export structure
        assert len(exported) == 2
        assert "file:///home/user/project1" in exported
        assert "file:///home/user/project2" in exported

        # Verify exported data includes sessions
        ws1_export = exported["file:///home/user/project1"]
        assert ws1_export["project"] == "project1"
        assert len(ws1_export["sessions"]) == 1
        assert session1.session_id in ws1_export["sessions"]

        ws2_export = exported["file:///home/user/project2"]
        assert ws2_export["project"] == "project2"
        assert len(ws2_export["sessions"]) == 1

    @pytest.mark.asyncio
    async def test_workspace_cleanup(self):
        """Test that workspaces can be cleaned up properly."""
        ctx_ws1 = self._create_mock_ctx("file:///workspace1")
        ctx_ws2 = self._create_mock_ctx("file:///workspace2")
        ctx_ws3 = self._create_mock_ctx("file:///workspace3")

        # Create 3 workspaces with sessions (ensure_session=False, then create manually)
        state1 = await WorkspaceRegistry.get_for_ctx(ctx_ws1, ensure_session=False)
        state1.create_session()

        state2 = await WorkspaceRegistry.get_for_ctx(ctx_ws2, ensure_session=False)
        state2.create_session()

        state3 = await WorkspaceRegistry.get_for_ctx(ctx_ws3, ensure_session=False)
        state3.create_session()

        assert WorkspaceRegistry.count() == 3
        assert WorkspaceRegistry.total_session_count() == 3

        # Remove one workspace
        result = WorkspaceRegistry.remove("file:///workspace2")
        assert result is True
        assert WorkspaceRegistry.count() == 2
        assert WorkspaceRegistry.total_session_count() == 2

        # Verify remaining workspaces
        all_states = WorkspaceRegistry.get_all()
        assert "file:///workspace1" in all_states
        assert "file:///workspace2" not in all_states
        assert "file:///workspace3" in all_states

    @pytest.mark.asyncio
    async def test_workspace_with_auto_detection(self):
        """Test workspace creation with auto-detected project."""
        mock_config = {
            "repositories": {
                "backend": {"path": "/home/user/src/backend"},
                "frontend": {"path": "/home/user/src/frontend"},
            }
        }

        ctx_backend = self._create_mock_ctx("file:///home/user/src/backend")
        ctx_frontend = self._create_mock_ctx("file:///home/user/src/frontend")
        ctx_unknown = self._create_mock_ctx("file:///home/user/src/unknown")

        with patch("server.utils.load_config", return_value=mock_config):
            state_backend = await WorkspaceRegistry.get_for_ctx(ctx_backend)
            state_frontend = await WorkspaceRegistry.get_for_ctx(ctx_frontend)
            state_unknown = await WorkspaceRegistry.get_for_ctx(ctx_unknown)

        # Backend and frontend should be auto-detected
        assert state_backend.project == "backend"
        assert state_backend.is_auto_detected is True

        assert state_frontend.project == "frontend"
        assert state_frontend.is_auto_detected is True

        # Unknown should have no project
        assert state_unknown.project is None
        assert state_unknown.is_auto_detected is False


class TestWorkspaceRegistryAdvanced:
    """Tests for WorkspaceRegistry methods not covered by basic tests."""

    def setup_method(self):
        """Start from an empty registry."""
        WorkspaceRegistry.clear()

    def teardown_method(self):
        """Leave an empty registry behind."""
        WorkspaceRegistry.clear()

    def test_touch_existing_workspace(self):
        """WorkspaceRegistry.touch() updates workspace last_activity."""
        state = WorkspaceRegistry.get_or_create("file:///ws1", ensure_session=False)
        # Set last_activity to a known past time instead of sleeping
        past_time = datetime.now(tz=timezone.utc) - timedelta(seconds=10)
        state.last_activity = past_time
        WorkspaceRegistry.touch("file:///ws1")
        assert state.last_activity > past_time

    def test_touch_nonexistent_workspace(self):
        """WorkspaceRegistry.touch() does nothing for unknown workspace."""
        WorkspaceRegistry.touch("file:///unknown")  # Test verifies no exception is raised
        assert WorkspaceRegistry.get("file:///unknown") is None

    def test_cleanup_stale_removes_empty_stale(self):
        """cleanup_stale removes workspaces with no sessions and stale."""
        state = WorkspaceRegistry.get_or_create("file:///stale-ws", ensure_session=False)
        state.last_activity = datetime.now(tz=timezone.utc) - timedelta(hours=48)
        assert state.session_count() == 0

        with patch("server.cursor_chat_db.get_cursor_chat_ids", return_value=set()):
            removed = WorkspaceRegistry.cleanup_stale(max_age_hours=24)

        assert removed == 1
        assert WorkspaceRegistry.count() == 0

    def test_cleanup_stale_keeps_active(self):
        """cleanup_stale keeps workspaces with recent activity."""
        WorkspaceRegistry.get_or_create("file:///active-ws", ensure_session=False)
        with patch("server.cursor_chat_db.get_cursor_chat_ids", return_value=set()):
            removed = WorkspaceRegistry.cleanup_stale(max_age_hours=24)
        assert removed == 0
        assert WorkspaceRegistry.count() == 1

    def test_cleanup_stale_keeps_with_sessions(self):
        """cleanup_stale keeps stale workspaces that still have sessions."""
        state = WorkspaceRegistry.get_or_create("file:///ws-sessions", ensure_session=False)
        state.last_activity = datetime.now(tz=timezone.utc) - timedelta(hours=48)
        with (
            patch("server.workspace_model.loaded_tool_names", return_value=set()),
            patch.object(WorkspaceRegistry, "save_to_disk"),
            patch(
                "server.cursor_chat_db.get_cursor_chat_info_from_db",
                return_value=(None, None),
            ),
        ):
            state.create_session(name="still-active")

        with (
            patch("server.cursor_chat_db.get_cursor_chat_ids", return_value=set()),
            patch.object(state, "cleanup_stale_sessions", return_value=0),
        ):
            removed = WorkspaceRegistry.cleanup_stale(max_age_hours=24)

        # Should not be removed because it has sessions
        assert removed == 0

    @pytest.mark.asyncio
    async def test_periodic_cleanup_on_access(self):
        """get_for_ctx triggers periodic cleanup after N accesses."""
        mock_ctx = MagicMock(spec=Context)
        mock_ctx.session = AsyncMock()
        mock_roots = MagicMock(spec=ListRootsResult)
        mock_roots.roots = [MagicMock(uri="file:///cleanup-test")]
        mock_ctx.session.list_roots = AsyncMock(return_value=mock_roots)

        # Clean up on every access
        with (
            patch.object(WorkspaceRegistry, "_CLEANUP_INTERVAL", 1),
            patch.object(WorkspaceRegistry, "cleanup_stale", return_value=0) as mock_cleanup,
        ):
            result = await WorkspaceRegistry.get_for_ctx(mock_ctx)
            mock_cleanup.assert_called_once_with(max_age_hours=SESSION_STALE_HOURS)
            assert result is not None

    def test_sync_all_with_cursor(self):
        """sync_all_with_cursor syncs all workspaces."""
        state = WorkspaceRegistry.get_or_create("file:///ws1", ensure_session=False)
        with (
            patch.object(
                state,
                "sync_with_cursor_db",
                return_value={"added": 1, "removed": 0, "renamed": 2, "updated": 0},
            ),
            patch.object(WorkspaceRegistry, "save_to_disk"),
        ):
            totals = WorkspaceRegistry.sync_all_with_cursor()

        assert totals["added"] == 1
        assert totals["renamed"] == 2

    def test_sync_all_with_cursor_skip_content_scan(self):
        """sync_all_with_cursor passes skip_content_scan to workspaces."""
        state = WorkspaceRegistry.get_or_create("file:///ws1", ensure_session=False)
        with patch.object(
            state,
            "sync_with_cursor_db",
            return_value={"added": 0, "removed": 0, "renamed": 0, "updated": 0},
        ) as mock_sync:
            result = WorkspaceRegistry.sync_all_with_cursor(skip_content_scan=True)
            mock_sync.assert_called_once_with(skip_content_scan=True)
            assert isinstance(result, dict)

    def test_sync_all_session_names_deprecated(self):
        """sync_all_session_names is deprecated wrapper."""
        with patch.object(
            WorkspaceRegistry,
            "sync_all_with_cursor",
            return_value={"added": 0, "removed": 0, "renamed": 5, "updated": 0},
        ):
            result = WorkspaceRegistry.sync_all_session_names()
            assert result == 5

    def test_sync_sessions_with_cursor_none_ids(self):
        """sync_sessions_with_cursor with None falls back to full sync."""
        with patch.object(
            WorkspaceRegistry,
            "sync_all_with_cursor",
            return_value={"added": 0, "removed": 0, "renamed": 0, "updated": 0},
        ) as mock_full:
            WorkspaceRegistry.sync_sessions_with_cursor(session_ids=None)
            mock_full.assert_called_once()
            assert mock_full.call_count == 1

    def test_sync_sessions_with_cursor_specific_ids(self):
        """sync_sessions_with_cursor only syncs matching workspaces."""
        state = WorkspaceRegistry.get_or_create("file:///ws1", ensure_session=False)
        with (
            patch("server.workspace_model.loaded_tool_names", return_value=set()),
            patch.object(WorkspaceRegistry, "save_to_disk"),
            patch(
                "server.cursor_chat_db.get_cursor_chat_info_from_db",
                return_value=(None, None),
            ),
        ):
            s = state.create_session()

        with (
            patch.object(
                state,
                "sync_with_cursor_db",
                return_value={"added": 0, "removed": 0, "renamed": 1, "updated": 0},
            ),
            patch.object(WorkspaceRegistry, "save_to_disk"),
        ):
            totals = WorkspaceRegistry.sync_sessions_with_cursor(session_ids=[s.session_id])

        assert totals["renamed"] == 1

    def test_sync_sessions_with_cursor_no_match(self):
        """sync_sessions_with_cursor with no matching IDs does nothing."""
        WorkspaceRegistry.get_or_create("file:///ws1", ensure_session=False)
        totals = WorkspaceRegistry.sync_sessions_with_cursor(session_ids=["nonexistent"])
        assert totals == {"added": 0, "removed": 0, "renamed": 0, "updated": 0}

    def test_get_all_sessions_fills_project(self):
        """get_all_sessions fills in workspace project when session has none."""
        state = WorkspaceRegistry.get_or_create("file:///ws1", ensure_session=False)
        state.project = "workspace-proj"
        with (
            patch("server.workspace_model.loaded_tool_names", return_value=set()),
            patch.object(WorkspaceRegistry, "save_to_disk"),
            patch(
                "server.cursor_chat_db.get_cursor_chat_info_from_db",
                return_value=(None, None),
            ),
        ):
            s = state.create_session()
            s.project = None  # No per-session project

        sessions = WorkspaceRegistry.get_all_sessions()
        assert len(sessions) == 1
        assert sessions[0]["project"] == "workspace-proj"

    def test_save_to_disk_failure(self, tmp_path):
        """save_to_disk returns False on failure."""
        # Use a directory that won't work for writing
        with (
            patch.object(ws_module, "PERSIST_DIR", tmp_path),
            patch.object(ws_module, "PERSIST_FILE", tmp_path / "states.json"),
            patch("pathlib.Path.mkdir", side_effect=PermissionError("denied")),
        ):
            # Make mkdir raise
            result = WorkspaceRegistry.save_to_disk()
            assert result is False

    def test_remove_nonexistent_workspace(self):
        """remove returns False for unknown workspace."""
        assert WorkspaceRegistry.remove("file:///nonexistent") is False

    def test_remove_session_nonexistent_workspace(self):
        """remove_session returns False for unknown workspace."""
        assert WorkspaceRegistry.remove_session("file:///nonexistent", "sess1") is False


class TestDetectProjectAdvanced:
    """Tests for detect_project edge cases."""

    def setup_method(self):
        """Start from an empty registry."""
        WorkspaceRegistry.clear()

    def teardown_method(self):
        """Leave an empty registry behind."""
        WorkspaceRegistry.clear()

    def test_detect_project_default_workspace(self):
        """detect_project with DEFAULT_WORKSPACE tries cwd."""
        mock_config = {"repositories": {}}
        with patch("server.utils.load_config", return_value=mock_config):
            result = detect_project("default")
            assert result is None

    def test_detect_project_non_file_uri(self):
        """detect_project with plain path."""
        mock_config = {
            "repositories": {
                "myproject": {"path": "/home/user/myproject"},
            }
        }
        with patch("server.utils.load_config", return_value=mock_config):
            result = detect_project("/home/user/myproject")
            assert result == "myproject"

    def test_detect_project_empty_config(self):
        """detect_project returns None when config is empty."""
        with patch("server.utils.load_config", return_value={}):
            result = detect_project("file:///test")
            assert result is None

    def test_detect_project_empty_path_in_config(self):
        """detect_project skips repos with empty path."""
        mock_config = {
            "repositories": {
                "empty-path": {"path": ""},
                "good": {"path": "/home/user/good"},
            }
        }
        with patch("server.utils.load_config", return_value=mock_config):
            result = detect_project("file:///home/user/good")
            assert result == "good"
