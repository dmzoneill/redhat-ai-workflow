"""Tests for WorkspaceState, ChatSession, and WorkspaceRegistry.

Tests workspace and session isolation to ensure different Cursor chats maintain
independent state (project, persona, issue, branch).
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.workspace_state import (
    DEFAULT_PROJECT,
    DEFAULT_WORKSPACE,
    ChatSession,
    WorkspaceRegistry,
    WorkspaceState,
    get_default_persona,
    get_workspace_state,
)


class TestChatSession:
    """Tests for ChatSession dataclass."""

    def test_default_values(self):
        """Test ChatSession has correct defaults."""
        session = ChatSession(
            session_id="abc123",
            workspace_uri="file:///test",
        )

        assert session.session_id == "abc123"
        assert session.workspace_uri == "file:///test"
        assert session.persona == get_default_persona()
        assert session.issue_key is None
        assert session.branch is None
        assert session.active_tools == set()
        assert session.started_at is not None
        assert session.last_activity is not None
        assert session.tool_filter_cache == {}

    def test_to_dict(self):
        """Test ChatSession serialization."""
        session = ChatSession(
            session_id="abc123",
            workspace_uri="file:///test",
            persona="devops",
            issue_key="AAP-12345",
            branch="feature-branch",
            name="My Session",
        )
        session.active_tools = {"git", "gitlab"}

        result = session.to_dict()

        assert result["session_id"] == "abc123"
        assert result["workspace_uri"] == "file:///test"
        assert result["persona"] == "devops"
        assert result["issue_key"] == "AAP-12345"
        assert result["branch"] == "feature-branch"
        assert result["name"] == "My Session"
        # active_tools setter converts to static_tool_count
        assert result["static_tool_count"] == 2
        assert result["tool_count"] == 2

    def test_touch_updates_last_activity(self):
        """Test that touch updates last_activity."""
        session = ChatSession(session_id="abc", workspace_uri="file:///test")
        old_activity = session.last_activity

        # Small delay to ensure time difference
        import time

        time.sleep(0.01)

        session.touch()

        assert session.last_activity > old_activity

    def test_is_stale(self):
        """Test stale session detection."""
        session = ChatSession(session_id="abc", workspace_uri="file:///test")

        # Fresh session should not be stale
        assert session.is_stale(max_age_hours=1) is False

        # Manually set old last_activity
        session.last_activity = datetime.now() - timedelta(hours=5)
        assert session.is_stale(max_age_hours=4) is True
        assert session.is_stale(max_age_hours=6) is False

    def test_clear_filter_cache(self):
        """Test clearing the tool filter cache."""
        session = ChatSession(session_id="abc", workspace_uri="file:///test")
        session.tool_filter_cache = {"key1": ["tool1"], "key2": ["tool2"]}

        session.clear_filter_cache()

        assert session.tool_filter_cache == {}


class TestWorkspaceState:
    """Tests for WorkspaceState dataclass."""

    def test_default_values(self):
        """Test WorkspaceState has correct defaults."""
        state = WorkspaceState(workspace_uri="file:///test")

        assert state.workspace_uri == "file:///test"
        assert state.project is None
        assert state.sessions == {}
        assert state.active_session_id is None
        assert state.is_auto_detected is False

    def test_create_session(self):
        """Test creating a new session in workspace."""
        state = WorkspaceState(workspace_uri="file:///test")

        session = state.create_session(persona="devops", name="DevOps Session")

        assert session.session_id is not None
        assert session.persona == "devops"
        assert session.name == "DevOps Session"
        assert session.workspace_uri == "file:///test"
        assert state.active_session_id == session.session_id
        assert state.session_count() == 1

    def test_multiple_sessions(self):
        """Test creating multiple sessions in workspace."""
        state = WorkspaceState(workspace_uri="file:///test")

        session1 = state.create_session(persona="developer")
        session2 = state.create_session(persona="devops")
        session3 = state.create_session(persona="incident")

        assert state.session_count() == 3
        # Most recent session should be active
        assert state.active_session_id == session3.session_id

    def test_get_active_session(self):
        """Test getting the active session."""
        state = WorkspaceState(workspace_uri="file:///test")

        # No sessions yet
        assert state.get_active_session() is None

        session = state.create_session()
        assert state.get_active_session() is session

    def test_set_active_session(self):
        """Test setting the active session."""
        state = WorkspaceState(workspace_uri="file:///test")

        session1 = state.create_session()
        session2 = state.create_session()

        # session2 is active (most recent)
        assert state.active_session_id == session2.session_id

        # Switch back to session1
        result = state.set_active_session(session1.session_id)
        assert result is True
        assert state.active_session_id == session1.session_id

        # Try to set unknown session
        result = state.set_active_session("unknown")
        assert result is False

    def test_remove_session(self):
        """Test removing a session."""
        state = WorkspaceState(workspace_uri="file:///test")

        session1 = state.create_session()
        session2 = state.create_session()

        # Remove session2 (active)
        result = state.remove_session(session2.session_id)
        assert result is True
        assert state.session_count() == 1
        # session1 should now be active
        assert state.active_session_id == session1.session_id

        # Remove unknown session
        result = state.remove_session("unknown")
        assert result is False

    def test_backward_compat_properties(self):
        """Test backward compatibility properties delegate to active session."""
        state = WorkspaceState(workspace_uri="file:///test")

        # No session - should return defaults
        assert state.persona == get_default_persona()
        assert state.issue_key is None
        assert state.branch is None
        assert state.active_tools == set()

        # Create session and set values
        session = state.create_session(persona="devops")
        session.issue_key = "AAP-123"
        session.branch = "feature"
        session.active_tools = {"git", "k8s"}

        # Properties should reflect session values
        assert state.persona == "devops"
        assert state.issue_key == "AAP-123"
        assert state.branch == "feature"
        # active_tools getter is deprecated and returns empty set;
        # the setter converts to static_tool_count
        assert state.active_tools == set()
        assert session.static_tool_count == 2

        # Setting via properties should update session
        state.persona = "incident"
        state.issue_key = "AAP-456"
        assert session.persona == "incident"
        assert session.issue_key == "AAP-456"

    def test_to_dict(self):
        """Test WorkspaceState serialization."""
        state = WorkspaceState(workspace_uri="file:///test", project="test-project")
        session = state.create_session(persona="devops")
        session.issue_key = "AAP-123"

        result = state.to_dict()

        assert result["workspace_uri"] == "file:///test"
        assert result["project"] == "test-project"
        assert len(result["sessions"]) == 1
        assert result["active_session_id"] == session.session_id
        assert session.session_id in result["sessions"]


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
        mock_ctx = MagicMock()
        mock_ctx.session = AsyncMock()
        mock_roots = MagicMock()
        mock_roots.roots = [MagicMock(uri="file:///home/user/project")]
        mock_ctx.session.list_roots = AsyncMock(return_value=mock_roots)

        state = await WorkspaceRegistry.get_for_ctx(mock_ctx)

        assert state.workspace_uri == "file:///home/user/project"
        assert WorkspaceRegistry.count() == 1

    @pytest.mark.asyncio
    async def test_get_for_ctx_returns_existing_state(self):
        """Test that get_for_ctx returns existing state for known workspace."""
        mock_ctx = MagicMock()
        mock_ctx.session = AsyncMock()
        mock_roots = MagicMock()
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
        mock_ctx1 = MagicMock()
        mock_ctx1.session = AsyncMock()
        mock_roots1 = MagicMock()
        mock_roots1.roots = [MagicMock(uri="file:///workspace1")]
        mock_ctx1.session.list_roots = AsyncMock(return_value=mock_roots1)

        mock_ctx2 = MagicMock()
        mock_ctx2.session = AsyncMock()
        mock_roots2 = MagicMock()
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
        mock_ctx = MagicMock()
        mock_ctx.session = AsyncMock()
        mock_ctx.session.list_roots = AsyncMock(side_effect=Exception("Not supported"))

        state = await WorkspaceRegistry.get_for_ctx(mock_ctx)

        assert state.workspace_uri == DEFAULT_WORKSPACE
        assert WorkspaceRegistry.count() == 1

    @pytest.mark.asyncio
    async def test_fallback_when_no_session(self):
        """Test fallback when context has no session."""
        mock_ctx = MagicMock()
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
        state = WorkspaceRegistry.get_or_create(
            "file:///auto-session-test", ensure_session=True
        )

        # Session should be auto-created
        assert state.session_count() == 1
        assert state.get_active_session() is not None
        assert state.get_active_session().name == "Auto-created"
        assert state.get_active_session().persona == get_default_persona()

    @pytest.mark.asyncio
    async def test_auto_session_creation_async(self):
        """Test that get_for_ctx auto-creates a session by default."""
        mock_ctx = MagicMock()
        mock_ctx.session = AsyncMock()
        mock_roots = MagicMock()
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
            result = WorkspaceRegistry._detect_project(
                "file:///home/user/src/test-project"
            )

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
            result = WorkspaceRegistry._detect_project(
                "file:///home/user/src/test-project/src/module"
            )

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
            result = WorkspaceRegistry._detect_project("file:///home/user/src/unknown")

        assert result is None

    @pytest.mark.asyncio
    async def test_auto_detect_on_create(self):
        """Test that project is auto-detected when workspace is created."""
        mock_config = {
            "repositories": {
                "auto-detected": {"path": "/home/user/src/auto-detected"},
            }
        }

        mock_ctx = MagicMock()
        mock_ctx.session = AsyncMock()
        mock_roots = MagicMock()
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
        mock_ctx = MagicMock()
        mock_ctx.session = AsyncMock()
        mock_roots = MagicMock()
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
        mock_ctx = MagicMock()
        mock_ctx.session = AsyncMock()
        mock_roots = MagicMock()
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
        state_backend = await WorkspaceRegistry.get_for_ctx(
            ctx_backend, ensure_session=False
        )
        state_frontend = await WorkspaceRegistry.get_for_ctx(
            ctx_frontend, ensure_session=False
        )
        state_infra = await WorkspaceRegistry.get_for_ctx(
            ctx_infra, ensure_session=False
        )

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
        import json

        import server.workspace_state as ws_module

        # Use temp path for persistence
        persist_file = tmp_path / "workspace_states.json"

        with (
            patch.object(ws_module, "PERSIST_DIR", tmp_path),
            patch.object(ws_module, "PERSIST_FILE", persist_file),
        ):

            # Create workspaces with sessions (ensure_session=False to avoid auto-create)
            ws1 = WorkspaceRegistry.get_or_create(
                "file:///workspace1", ensure_session=False
            )
            ws1.project = "project1"
            session1 = ws1.create_session(persona="developer", name="Dev Session")
            session1.issue_key = "AAP-12345"
            session1.branch = "feature-branch"

            ws2 = WorkspaceRegistry.get_or_create(
                "file:///workspace2", ensure_session=False
            )
            ws2.project = "project2"
            ws2.create_session(persona="devops", name="DevOps Session")

            # Verify sessions exist
            assert WorkspaceRegistry.count() == 2
            assert WorkspaceRegistry.total_session_count() == 2

            # Save should have been called automatically by create_session
            # Verify the file exists and has correct content
            assert persist_file.exists()

            with open(persist_file) as f:
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

            restored_session1 = list(restored_ws1.sessions.values())[0]
            assert restored_session1.persona == "developer"
            assert restored_session1.issue_key == "AAP-12345"
            assert restored_session1.branch == "feature-branch"
            assert restored_session1.name == "Dev Session"

    def test_restore_if_empty_only_loads_when_empty(self, tmp_path):
        """Test that restore_if_empty only loads when registry is empty."""
        import server.workspace_state as ws_module

        persist_file = tmp_path / "workspace_states.json"

        with (
            patch.object(ws_module, "PERSIST_DIR", tmp_path),
            patch.object(ws_module, "PERSIST_FILE", persist_file),
        ):

            # Create a workspace (ensure_session=False to avoid auto-create)
            ws = WorkspaceRegistry.get_or_create(
                "file:///workspace1", ensure_session=False
            )
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
        import server.workspace_state as ws_module

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
        import server.workspace_state as ws_module

        persist_file = tmp_path / "workspace_states.json"

        with (
            patch.object(ws_module, "PERSIST_DIR", tmp_path),
            patch.object(ws_module, "PERSIST_FILE", persist_file),
        ):

            # Write invalid JSON
            with open(persist_file, "w") as f:
                f.write("not valid json {{{")

            restored = WorkspaceRegistry.load_from_disk()
            assert restored == 0

    def test_load_handles_old_version(self, tmp_path):
        """Test that load_from_disk skips old format versions."""
        import json

        import server.workspace_state as ws_module

        persist_file = tmp_path / "workspace_states.json"

        with (
            patch.object(ws_module, "PERSIST_DIR", tmp_path),
            patch.object(ws_module, "PERSIST_FILE", persist_file),
        ):

            # Write old version format
            with open(persist_file, "w") as f:
                json.dump({"version": 1, "workspaces": {}}, f)

            restored = WorkspaceRegistry.load_from_disk()
            assert restored == 0
