"""Tests for WorkspaceState, ChatSession, and WorkspaceRegistry.

Tests workspace and session isolation to ensure different Cursor chats maintain
independent state (project, persona, issue, branch).
"""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.workspace_state import (
    DEFAULT_WORKSPACE,
    MAX_FILTER_CACHE_SIZE,
    SESSION_STALE_HOURS,
    ChatSession,
    WorkspaceRegistry,
    WorkspaceState,
    format_session_context_for_jira,
    get_all_persona_tool_counts,
    get_cursor_chat_content,
    get_cursor_chat_ids,
    get_cursor_chat_info_from_db,
    get_cursor_chat_issue_keys,
    get_cursor_chat_names,
    get_cursor_chat_personas,
    get_cursor_chat_projects,
    get_default_persona,
    get_meeting_transcript_issue_keys,
    get_persona_tool_count,
    get_workspace_state,
    inject_context_to_cursor_chat,
    list_cursor_chats,
    update_persona_tool_count,
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

        state.create_session(persona="developer")
        state.create_session(persona="devops")
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


class TestPersonaToolCounts:
    """Tests for persona tool count cache functions."""

    def setup_method(self):
        """Reset persona tool counts."""
        import server.workspace_state as ws_module

        ws_module._persona_tool_counts.clear()

    def teardown_method(self):
        import server.workspace_state as ws_module

        ws_module._persona_tool_counts.clear()

    def test_get_persona_tool_count_missing(self):
        """get_persona_tool_count returns 0 for unknown persona."""
        assert get_persona_tool_count("nonexistent") == 0

    def test_update_and_get_persona_tool_count(self):
        """update_persona_tool_count stores value retrievable by get."""
        update_persona_tool_count("developer", 42)
        assert get_persona_tool_count("developer") == 42

    def test_get_all_persona_tool_counts(self):
        """get_all_persona_tool_counts returns copy of all counts."""
        update_persona_tool_count("developer", 10)
        update_persona_tool_count("devops", 20)
        counts = get_all_persona_tool_counts()
        assert counts == {"developer": 10, "devops": 20}
        # Verify it's a copy (mutating returned dict shouldn't affect cache)
        counts["developer"] = 999
        assert get_persona_tool_count("developer") == 10

    def test_update_overwrites(self):
        """update_persona_tool_count overwrites previous value."""
        update_persona_tool_count("devops", 5)
        update_persona_tool_count("devops", 15)
        assert get_persona_tool_count("devops") == 15


class TestGetDefaultPersona:
    """Tests for get_default_persona function."""

    def test_returns_from_config(self):
        """get_default_persona reads from config agent.default_persona."""
        mock_cfg = {"agent": {"default_persona": "developer"}}
        with patch("server.workspace_state.load_config", mock_cfg, create=True):
            # We need to patch the import inside the function
            with patch("server.utils.load_config", return_value=mock_cfg):
                result = get_default_persona()
                assert result == "developer"

    def test_fallback_on_exception(self):
        """get_default_persona returns 'researcher' when config fails."""
        with patch("server.utils.load_config", side_effect=Exception("Config missing")):
            result = get_default_persona()
            assert result == "researcher"


class TestChatSessionAdvanced:
    """Tests for ChatSession methods not covered by basic tests."""

    def test_touch_with_tool_name(self):
        """touch() with tool_name tracks tool call info."""
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        assert session.last_tool is None
        assert session.last_tool_time is None
        assert session.tool_call_count == 0

        session.touch(tool_name="git_status")

        assert session.last_tool == "git_status"
        assert session.last_tool_time is not None
        assert session.tool_call_count == 1

        session.touch(tool_name="git_diff")
        assert session.last_tool == "git_diff"
        assert session.tool_call_count == 2

    def test_touch_without_tool_name(self):
        """touch() without tool_name only updates last_activity."""
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        session.touch()
        assert session.last_tool is None
        assert session.tool_call_count == 0

    def test_tool_count_property_dynamic_preferred(self):
        """tool_count returns dynamic_tool_count when > 0."""
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        session.static_tool_count = 50
        session.dynamic_tool_count = 10
        assert session.tool_count == 10

    def test_tool_count_property_static_fallback(self):
        """tool_count returns static_tool_count when dynamic is 0."""
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        session.static_tool_count = 50
        session.dynamic_tool_count = 0
        assert session.tool_count == 50

    def test_active_tools_getter_returns_empty(self):
        """active_tools getter always returns empty set (deprecated)."""
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        session.static_tool_count = 99
        assert session.active_tools == set()

    def test_active_tools_setter_sets_static_count(self):
        """active_tools setter converts set length to static_tool_count."""
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        session.active_tools = {"a", "b", "c"}
        assert session.static_tool_count == 3

    def test_active_tools_setter_empty(self):
        """active_tools setter with empty set sets count to 0."""
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        session.static_tool_count = 5
        session.active_tools = set()
        assert session.static_tool_count == 0

    def test_add_to_filter_cache_basic(self):
        """add_to_filter_cache stores tools."""
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        session.add_to_filter_cache("hash1", ["tool_a", "tool_b"])
        assert session.tool_filter_cache["hash1"] == ["tool_a", "tool_b"]

    def test_add_to_filter_cache_eviction(self):
        """add_to_filter_cache evicts oldest entries when full."""
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        # Fill cache to MAX_FILTER_CACHE_SIZE
        for i in range(MAX_FILTER_CACHE_SIZE):
            session.add_to_filter_cache(f"key_{i}", [f"tool_{i}"])

        assert len(session.tool_filter_cache) == MAX_FILTER_CACHE_SIZE
        assert "key_0" in session.tool_filter_cache

        # Adding one more should evict key_0
        session.add_to_filter_cache("new_key", ["new_tool"])
        assert len(session.tool_filter_cache) == MAX_FILTER_CACHE_SIZE
        assert "key_0" not in session.tool_filter_cache
        assert "new_key" in session.tool_filter_cache

    def test_cache_intent_basic(self):
        """cache_intent stores and retrieves intent."""
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        intent = {"category": "code_search", "confidence": 0.9}
        session.cache_intent("hash_abc", intent)
        assert session.get_cached_intent("hash_abc") == intent

    def test_get_cached_intent_miss(self):
        """get_cached_intent returns None for unknown hash."""
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        assert session.get_cached_intent("unknown") is None

    def test_cache_intent_eviction(self):
        """cache_intent evicts oldest when full."""
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        for i in range(session.MAX_INTENT_CACHE_SIZE):
            session.cache_intent(f"key_{i}", {"index": i})

        assert len(session.intent_cache) == session.MAX_INTENT_CACHE_SIZE

        session.cache_intent("overflow", {"index": "new"})
        assert len(session.intent_cache) == session.MAX_INTENT_CACHE_SIZE
        assert "key_0" not in session.intent_cache
        assert "overflow" in session.intent_cache

    def test_cache_memory_query_basic(self):
        """cache_memory_query stores and retrieves query result."""
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        result = {"data": "some_result"}
        session.cache_memory_query("hash_xyz", result)
        assert session.get_cached_memory_query("hash_xyz") == result

    def test_get_cached_memory_query_miss(self):
        """get_cached_memory_query returns None for unknown hash."""
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        assert session.get_cached_memory_query("unknown") is None

    def test_cache_memory_query_eviction(self):
        """cache_memory_query evicts oldest when full."""
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        for i in range(session.MAX_QUERY_CACHE_SIZE):
            session.cache_memory_query(f"key_{i}", {"index": i})

        assert len(session.memory_query_cache) == session.MAX_QUERY_CACHE_SIZE

        session.cache_memory_query("overflow", {"index": "new"})
        assert len(session.memory_query_cache) == session.MAX_QUERY_CACHE_SIZE
        assert "key_0" not in session.memory_query_cache
        assert "overflow" in session.memory_query_cache

    def test_clear_memory_caches(self):
        """clear_memory_caches clears both caches."""
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        session.cache_intent("h1", {"a": 1})
        session.cache_memory_query("h2", {"b": 2})
        assert len(session.intent_cache) == 1
        assert len(session.memory_query_cache) == 1

        session.clear_memory_caches()
        assert session.intent_cache == {}
        assert session.memory_query_cache == {}

    def test_to_dict_full(self):
        """to_dict includes all fields including tool tracking."""
        session = ChatSession(
            session_id="s1",
            workspace_uri="file:///test",
            persona="devops",
            project="my-project",
            is_project_auto_detected=True,
            issue_key="AAP-111",
            branch="feature",
            name="Test Session",
        )
        session.static_tool_count = 30
        session.dynamic_tool_count = 5
        session.last_filter_message = "deploy to stage"
        session.last_filter_time = datetime(2025, 1, 15, 10, 0)
        session.last_tool = "k8s_get_pods"
        session.last_tool_time = datetime(2025, 1, 15, 10, 5)
        session.tool_call_count = 7
        session.meeting_references = [{"meeting_id": 1, "title": "Sprint"}]

        d = session.to_dict()

        assert d["session_id"] == "s1"
        assert d["persona"] == "devops"
        assert d["project"] == "my-project"
        assert d["is_project_auto_detected"] is True
        assert d["static_tool_count"] == 30
        assert d["dynamic_tool_count"] == 5
        assert d["tool_count"] == 5  # dynamic preferred
        assert d["last_filter_message"] == "deploy to stage"
        assert d["last_filter_time"] is not None
        assert d["last_tool"] == "k8s_get_pods"
        assert d["last_tool_time"] is not None
        assert d["tool_call_count"] == 7
        assert d["meeting_references"] == [{"meeting_id": 1, "title": "Sprint"}]


class TestWorkspaceStateAdvanced:
    """Tests for WorkspaceState methods not covered by basic tests."""

    def setup_method(self):
        WorkspaceRegistry.clear()

    def teardown_method(self):
        WorkspaceRegistry.clear()

    def test_workspace_touch(self):
        """WorkspaceState.touch() updates last_activity."""
        state = WorkspaceState(workspace_uri="file:///test")
        old = state.last_activity
        time.sleep(0.01)
        state.touch()
        assert state.last_activity > old

    def test_workspace_is_stale(self):
        """WorkspaceState.is_stale detects old workspaces."""
        state = WorkspaceState(workspace_uri="file:///test")
        assert state.is_stale(max_age_hours=1) is False
        state.last_activity = datetime.now() - timedelta(hours=5)
        assert state.is_stale(max_age_hours=4) is True
        assert state.is_stale(max_age_hours=6) is False

    def test_get_or_create_session_returns_existing(self):
        """get_or_create_session returns active session if one exists."""
        state = WorkspaceState(workspace_uri="file:///test")
        with patch.object(state, "_get_loaded_tools", return_value=set()):
            with patch.object(WorkspaceRegistry, "save_to_disk"):
                with patch(
                    "server.workspace_state.get_cursor_chat_info_from_db",
                    return_value=(None, None),
                ):
                    s1 = state.create_session(persona="developer", name="existing")
                    s2 = state.get_or_create_session(persona="devops")
                    assert s1.session_id == s2.session_id  # same session

    def test_get_or_create_session_creates_when_none(self):
        """get_or_create_session creates session when none exists."""
        state = WorkspaceState(workspace_uri="file:///test")
        assert state.get_active_session() is None
        with patch.object(state, "_get_loaded_tools", return_value=set()):
            with patch.object(WorkspaceRegistry, "save_to_disk"):
                with patch(
                    "server.workspace_state.get_cursor_chat_info_from_db",
                    return_value=(None, None),
                ):
                    s = state.get_or_create_session(persona="developer")
                    assert s is not None
                    assert s.persona == "developer"

    def test_remove_session_sets_active_to_none(self):
        """Removing the only session sets active to None."""
        state = WorkspaceState(workspace_uri="file:///test")
        with patch.object(state, "_get_loaded_tools", return_value=set()):
            with patch.object(WorkspaceRegistry, "save_to_disk"):
                with patch(
                    "server.workspace_state.get_cursor_chat_info_from_db",
                    return_value=(None, None),
                ):
                    session = state.create_session()
                    state.remove_session(session.session_id)
                    assert state.active_session_id is None
                    assert state.session_count() == 0

    def test_cleanup_stale_sessions(self):
        """cleanup_stale_sessions removes stale sessions not in Cursor."""
        state = WorkspaceState(workspace_uri="file:///test")
        with patch.object(state, "_get_loaded_tools", return_value=set()):
            with patch.object(WorkspaceRegistry, "save_to_disk"):
                with patch(
                    "server.workspace_state.get_cursor_chat_info_from_db",
                    return_value=(None, None),
                ):
                    s1 = state.create_session(name="stale")
                    s1.last_activity = datetime.now() - timedelta(hours=48)

                    s2 = state.create_session(name="fresh")

                    with patch(
                        "server.workspace_state.get_cursor_chat_ids", return_value=set()
                    ):
                        removed = state.cleanup_stale_sessions(max_age_hours=24)

                    assert removed == 1
                    assert state.session_count() == 1
                    assert state.get_session(s2.session_id) is not None

    def test_cleanup_stale_sessions_keeps_cursor_sessions(self):
        """cleanup_stale_sessions keeps stale sessions that are still in Cursor."""
        state = WorkspaceState(workspace_uri="file:///test")
        with patch.object(state, "_get_loaded_tools", return_value=set()):
            with patch.object(WorkspaceRegistry, "save_to_disk"):
                with patch(
                    "server.workspace_state.get_cursor_chat_info_from_db",
                    return_value=(None, None),
                ):
                    s1 = state.create_session(name="stale-but-in-cursor")
                    s1.last_activity = datetime.now() - timedelta(hours=48)

                    # Cursor still has this session
                    with patch(
                        "server.workspace_state.get_cursor_chat_ids",
                        return_value={s1.session_id},
                    ):
                        removed = state.cleanup_stale_sessions(max_age_hours=24)

                    assert removed == 0
                    assert state.session_count() == 1

    def test_sync_session_names_from_cursor_deprecated(self):
        """sync_session_names_from_cursor wraps sync_with_cursor_db."""
        state = WorkspaceState(workspace_uri="file:///test")
        with patch.object(
            state,
            "sync_with_cursor_db",
            return_value={"added": 0, "removed": 0, "renamed": 3, "updated": 0},
        ):
            result = state.sync_session_names_from_cursor()
            assert result == 3

    def test_get_loaded_tools_with_loader(self):
        """_get_loaded_tools returns tools from PersonaLoader."""
        state = WorkspaceState(workspace_uri="file:///test")
        mock_loader = MagicMock()
        mock_loader._tool_to_module = {
            "git_status": "git",
            "git_diff": "git",
            "k8s_pods": "k8s",
        }
        mock_loader.loaded_modules = {"git", "k8s"}
        with patch("server.persona_loader.get_loader", return_value=mock_loader):
            tools = state._get_loaded_tools()
            assert tools == {"git_status", "git_diff", "k8s_pods"}

    def test_get_loaded_tools_no_loader(self):
        """_get_loaded_tools returns empty set when loader unavailable."""
        state = WorkspaceState(workspace_uri="file:///test")
        with patch("server.persona_loader.get_loader", return_value=None):
            tools = state._get_loaded_tools()
            assert tools == set()

    def test_get_loaded_tools_exception(self):
        """_get_loaded_tools returns empty set on exception."""
        state = WorkspaceState(workspace_uri="file:///test")
        with patch(
            "server.persona_loader.get_loader", side_effect=ImportError("No module")
        ):
            tools = state._get_loaded_tools()
            assert tools == set()

    def test_backward_compat_started_at_no_session(self):
        """started_at property returns created_at when no session."""
        state = WorkspaceState(workspace_uri="file:///test")
        assert state.started_at == state.created_at

    def test_backward_compat_tool_filter_cache_no_session(self):
        """tool_filter_cache property returns empty dict when no session."""
        state = WorkspaceState(workspace_uri="file:///test")
        assert state.tool_filter_cache == {}

    def test_backward_compat_clear_filter_cache_no_session(self):
        """clear_filter_cache does nothing when no session."""
        state = WorkspaceState(workspace_uri="file:///test")
        state.clear_filter_cache()  # Should not raise

    def test_backward_compat_branch_setter_no_session(self):
        """branch setter does nothing when no session."""
        state = WorkspaceState(workspace_uri="file:///test")
        state.branch = "new-branch"  # Should not raise
        assert state.branch is None

    def test_backward_compat_active_tools_setter_no_session(self):
        """active_tools setter does nothing when no session."""
        state = WorkspaceState(workspace_uri="file:///test")
        state.active_tools = {"tool1"}  # Should not raise
        assert state.active_tools == set()

    def test_backward_compat_branch_setter_with_session(self):
        """branch setter sets branch on active session."""
        state = WorkspaceState(workspace_uri="file:///test")
        with patch.object(state, "_get_loaded_tools", return_value=set()):
            with patch.object(WorkspaceRegistry, "save_to_disk"):
                with patch(
                    "server.workspace_state.get_cursor_chat_info_from_db",
                    return_value=(None, None),
                ):
                    session = state.create_session()
                    state.branch = "my-branch"
                    assert session.branch == "my-branch"

    def test_backward_compat_active_tools_setter_with_session(self):
        """active_tools setter on workspace delegates to session."""
        state = WorkspaceState(workspace_uri="file:///test")
        with patch.object(state, "_get_loaded_tools", return_value=set()):
            with patch.object(WorkspaceRegistry, "save_to_disk"):
                with patch(
                    "server.workspace_state.get_cursor_chat_info_from_db",
                    return_value=(None, None),
                ):
                    session = state.create_session()
                    state.active_tools = {"a", "b"}
                    assert session.static_tool_count == 2

    def test_backward_compat_started_at_with_session(self):
        """started_at returns session's started_at when session exists."""
        state = WorkspaceState(workspace_uri="file:///test")
        with patch.object(state, "_get_loaded_tools", return_value=set()):
            with patch.object(WorkspaceRegistry, "save_to_disk"):
                with patch(
                    "server.workspace_state.get_cursor_chat_info_from_db",
                    return_value=(None, None),
                ):
                    session = state.create_session()
                    assert state.started_at == session.started_at

    def test_backward_compat_tool_filter_cache_with_session(self):
        """tool_filter_cache returns session's cache when session exists."""
        state = WorkspaceState(workspace_uri="file:///test")
        with patch.object(state, "_get_loaded_tools", return_value=set()):
            with patch.object(WorkspaceRegistry, "save_to_disk"):
                with patch(
                    "server.workspace_state.get_cursor_chat_info_from_db",
                    return_value=(None, None),
                ):
                    session = state.create_session()
                    session.tool_filter_cache["key"] = ["tool"]
                    assert state.tool_filter_cache == {"key": ["tool"]}

    def test_backward_compat_clear_filter_cache_with_session(self):
        """clear_filter_cache clears session's cache."""
        state = WorkspaceState(workspace_uri="file:///test")
        with patch.object(state, "_get_loaded_tools", return_value=set()):
            with patch.object(WorkspaceRegistry, "save_to_disk"):
                with patch(
                    "server.workspace_state.get_cursor_chat_info_from_db",
                    return_value=(None, None),
                ):
                    session = state.create_session()
                    session.tool_filter_cache["key"] = ["tool"]
                    state.clear_filter_cache()
                    assert session.tool_filter_cache == {}

    def test_backward_compat_persona_setter_no_session(self):
        """persona setter does nothing when no session."""
        state = WorkspaceState(workspace_uri="file:///test")
        state.persona = "devops"  # Should not raise

    def test_backward_compat_issue_key_setter_no_session(self):
        """issue_key setter does nothing when no session."""
        state = WorkspaceState(workspace_uri="file:///test")
        state.issue_key = "AAP-123"  # Should not raise


class TestWorkspaceRegistryAdvanced:
    """Tests for WorkspaceRegistry methods not covered by basic tests."""

    def setup_method(self):
        WorkspaceRegistry.clear()

    def teardown_method(self):
        WorkspaceRegistry.clear()

    def test_touch_existing_workspace(self):
        """WorkspaceRegistry.touch() updates workspace last_activity."""
        state = WorkspaceRegistry.get_or_create("file:///ws1", ensure_session=False)
        old = state.last_activity
        time.sleep(0.01)
        WorkspaceRegistry.touch("file:///ws1")
        assert state.last_activity > old

    def test_touch_nonexistent_workspace(self):
        """WorkspaceRegistry.touch() does nothing for unknown workspace."""
        WorkspaceRegistry.touch("file:///unknown")  # Should not raise

    def test_cleanup_stale_removes_empty_stale(self):
        """cleanup_stale removes workspaces with no sessions and stale."""
        state = WorkspaceRegistry.get_or_create(
            "file:///stale-ws", ensure_session=False
        )
        state.last_activity = datetime.now() - timedelta(hours=48)
        assert state.session_count() == 0

        with patch("server.workspace_state.get_cursor_chat_ids", return_value=set()):
            removed = WorkspaceRegistry.cleanup_stale(max_age_hours=24)

        assert removed == 1
        assert WorkspaceRegistry.count() == 0

    def test_cleanup_stale_keeps_active(self):
        """cleanup_stale keeps workspaces with recent activity."""
        WorkspaceRegistry.get_or_create("file:///active-ws", ensure_session=False)
        with patch("server.workspace_state.get_cursor_chat_ids", return_value=set()):
            removed = WorkspaceRegistry.cleanup_stale(max_age_hours=24)
        assert removed == 0
        assert WorkspaceRegistry.count() == 1

    def test_cleanup_stale_keeps_with_sessions(self):
        """cleanup_stale keeps stale workspaces that still have sessions."""
        state = WorkspaceRegistry.get_or_create(
            "file:///ws-sessions", ensure_session=False
        )
        state.last_activity = datetime.now() - timedelta(hours=48)
        with patch.object(state, "_get_loaded_tools", return_value=set()):
            with patch.object(WorkspaceRegistry, "save_to_disk"):
                with patch(
                    "server.workspace_state.get_cursor_chat_info_from_db",
                    return_value=(None, None),
                ):
                    state.create_session(name="still-active")

        with patch("server.workspace_state.get_cursor_chat_ids", return_value=set()):
            with patch.object(state, "cleanup_stale_sessions", return_value=0):
                removed = WorkspaceRegistry.cleanup_stale(max_age_hours=24)

        # Should not be removed because it has sessions
        assert removed == 0

    @pytest.mark.asyncio
    async def test_periodic_cleanup_on_access(self):
        """get_for_ctx triggers periodic cleanup after N accesses."""
        mock_ctx = MagicMock()
        mock_ctx.session = AsyncMock()
        mock_roots = MagicMock()
        mock_roots.roots = [MagicMock(uri="file:///cleanup-test")]
        mock_ctx.session.list_roots = AsyncMock(return_value=mock_roots)

        # Set access count just below threshold
        WorkspaceRegistry._access_count = WorkspaceRegistry._CLEANUP_INTERVAL - 1

        with patch.object(
            WorkspaceRegistry, "cleanup_stale", return_value=0
        ) as mock_cleanup:
            await WorkspaceRegistry.get_for_ctx(mock_ctx)
            mock_cleanup.assert_called_once_with(max_age_hours=SESSION_STALE_HOURS)

    def test_sync_all_with_cursor(self):
        """sync_all_with_cursor syncs all workspaces."""
        state = WorkspaceRegistry.get_or_create("file:///ws1", ensure_session=False)
        with patch.object(
            state,
            "sync_with_cursor_db",
            return_value={"added": 1, "removed": 0, "renamed": 2, "updated": 0},
        ):
            with patch.object(WorkspaceRegistry, "save_to_disk"):
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
            WorkspaceRegistry.sync_all_with_cursor(skip_content_scan=True)
            mock_sync.assert_called_once_with(skip_content_scan=True)

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

    def test_sync_sessions_with_cursor_specific_ids(self):
        """sync_sessions_with_cursor only syncs matching workspaces."""
        state = WorkspaceRegistry.get_or_create("file:///ws1", ensure_session=False)
        with patch.object(state, "_get_loaded_tools", return_value=set()):
            with patch.object(WorkspaceRegistry, "save_to_disk"):
                with patch(
                    "server.workspace_state.get_cursor_chat_info_from_db",
                    return_value=(None, None),
                ):
                    s = state.create_session()

        with patch.object(
            state,
            "sync_with_cursor_db",
            return_value={"added": 0, "removed": 0, "renamed": 1, "updated": 0},
        ):
            with patch.object(WorkspaceRegistry, "save_to_disk"):
                totals = WorkspaceRegistry.sync_sessions_with_cursor(
                    session_ids=[s.session_id]
                )

        assert totals["renamed"] == 1

    def test_sync_sessions_with_cursor_no_match(self):
        """sync_sessions_with_cursor with no matching IDs does nothing."""
        WorkspaceRegistry.get_or_create("file:///ws1", ensure_session=False)
        totals = WorkspaceRegistry.sync_sessions_with_cursor(
            session_ids=["nonexistent"]
        )
        assert totals == {"added": 0, "removed": 0, "renamed": 0, "updated": 0}

    def test_get_all_sessions_fills_project(self):
        """get_all_sessions fills in workspace project when session has none."""
        state = WorkspaceRegistry.get_or_create("file:///ws1", ensure_session=False)
        state.project = "workspace-proj"
        with patch.object(state, "_get_loaded_tools", return_value=set()):
            with patch.object(WorkspaceRegistry, "save_to_disk"):
                with patch(
                    "server.workspace_state.get_cursor_chat_info_from_db",
                    return_value=(None, None),
                ):
                    s = state.create_session()
                    s.project = None  # No per-session project

        sessions = WorkspaceRegistry.get_all_sessions()
        assert len(sessions) == 1
        assert sessions[0]["project"] == "workspace-proj"

    def test_save_to_disk_failure(self, tmp_path):
        """save_to_disk returns False on failure."""
        import server.workspace_state as ws_module

        # Use a directory that won't work for writing
        with patch.object(ws_module, "PERSIST_DIR", tmp_path):
            with patch.object(ws_module, "PERSIST_FILE", tmp_path / "states.json"):
                # Make mkdir raise
                with patch("pathlib.Path.mkdir", side_effect=PermissionError("denied")):
                    result = WorkspaceRegistry.save_to_disk()
                    assert result is False

    def test_remove_nonexistent_workspace(self):
        """remove returns False for unknown workspace."""
        assert WorkspaceRegistry.remove("file:///nonexistent") is False

    def test_remove_session_nonexistent_workspace(self):
        """remove_session returns False for unknown workspace."""
        assert WorkspaceRegistry.remove_session("file:///nonexistent", "sess1") is False


class TestDetectProjectAdvanced:
    """Tests for _detect_project edge cases."""

    def setup_method(self):
        WorkspaceRegistry.clear()

    def teardown_method(self):
        WorkspaceRegistry.clear()

    def test_detect_project_default_workspace(self):
        """_detect_project with DEFAULT_WORKSPACE tries cwd."""
        mock_config = {"repositories": {}}
        with patch("server.utils.load_config", return_value=mock_config):
            result = WorkspaceRegistry._detect_project("default")
            assert result is None

    def test_detect_project_non_file_uri(self):
        """_detect_project with plain path."""
        mock_config = {
            "repositories": {
                "myproject": {"path": "/home/user/myproject"},
            }
        }
        with patch("server.utils.load_config", return_value=mock_config):
            result = WorkspaceRegistry._detect_project("/home/user/myproject")
            assert result == "myproject"

    def test_detect_project_empty_config(self):
        """_detect_project returns None when config is empty."""
        with patch("server.utils.load_config", return_value={}):
            result = WorkspaceRegistry._detect_project("file:///test")
            assert result is None

    def test_detect_project_empty_path_in_config(self):
        """_detect_project skips repos with empty path."""
        mock_config = {
            "repositories": {
                "empty-path": {"path": ""},
                "good": {"path": "/home/user/good"},
            }
        }
        with patch("server.utils.load_config", return_value=mock_config):
            result = WorkspaceRegistry._detect_project("file:///home/user/good")
            assert result == "good"


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
            "summary": {
                "user_messages": 0,
                "assistant_messages": 0,
                "tool_calls": 0,
                "code_changes": 0,
                "issue_keys": [],
            },
            "messages": [
                {
                    "type": "assistant",
                    "text": "Done",
                    "tool_results": [
                        "Successfully deployed to stage environment with pod replicas=3"
                    ],
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
        result = format_session_context_for_jira(
            chat_content, include_transcript=True, max_transcript_chars=500
        )
        assert "... (truncated)" in result

    def test_session_duration_calculation(self):
        """Format calculates session duration."""
        session = ChatSession(
            session_id="abcdef1234567890",
            workspace_uri="file:///test",
        )
        session.started_at = datetime(2025, 1, 15, 10, 0)
        session.last_activity = datetime(2025, 1, 15, 10, 45)

        chat_content = {
            "summary": {
                "user_messages": 0,
                "assistant_messages": 0,
                "tool_calls": 0,
                "code_changes": 0,
                "issue_keys": [],
            },
            "messages": [],
        }
        result = format_session_context_for_jira(chat_content, session=session)
        assert "~45 minutes" in result


class TestCursorChatFunctions:
    """Tests for Cursor chat scanning functions with mocked file system."""

    def test_get_cursor_chat_issue_keys_no_ids(self):
        """get_cursor_chat_issue_keys returns empty when no IDs provided."""
        assert get_cursor_chat_issue_keys(None) == {}
        assert get_cursor_chat_issue_keys([]) == {}

    def test_get_cursor_chat_issue_keys_no_db(self):
        """get_cursor_chat_issue_keys returns empty when db doesn't exist."""
        with patch("pathlib.Path.home", return_value=Path("/fake/home")):
            with patch("pathlib.Path.exists", return_value=False):
                result = get_cursor_chat_issue_keys(["chat1"])
                assert result == {}

    def test_get_cursor_chat_personas_no_ids(self):
        """get_cursor_chat_personas returns empty when no IDs provided."""
        assert get_cursor_chat_personas(None) == {}
        assert get_cursor_chat_personas([]) == {}

    def test_get_cursor_chat_personas_no_db(self):
        """get_cursor_chat_personas returns empty when db doesn't exist."""
        with patch("pathlib.Path.home", return_value=Path("/fake/home")):
            with patch("pathlib.Path.exists", return_value=False):
                result = get_cursor_chat_personas(["chat1"])
                assert result == {}

    def test_get_cursor_chat_projects_no_ids(self):
        """get_cursor_chat_projects returns empty when no IDs provided."""
        assert get_cursor_chat_projects(None) == {}
        assert get_cursor_chat_projects([]) == {}

    def test_get_cursor_chat_projects_no_db(self):
        """get_cursor_chat_projects returns empty when db doesn't exist."""
        with patch(
            "server.utils.load_config",
            return_value={"repositories": {"proj": {"path": "/p"}}},
        ):
            with patch("pathlib.Path.home", return_value=Path("/fake/home")):
                with patch("pathlib.Path.exists", return_value=False):
                    result = get_cursor_chat_projects(["chat1"])
                    assert result == {}

    def test_get_cursor_chat_projects_empty_valid_projects(self):
        """get_cursor_chat_projects returns empty when no valid projects."""
        with patch("server.utils.load_config", return_value={"repositories": {}}):
            result = get_cursor_chat_projects(["chat1"])
            assert result == {}

    def test_get_cursor_chat_ids(self):
        """get_cursor_chat_ids delegates to list_cursor_chats."""
        mock_chats = [
            {"composerId": "id1", "name": "Chat 1"},
            {"composerId": "id2", "name": "Chat 2"},
        ]
        with patch(
            "server.workspace_state.list_cursor_chats", return_value=(mock_chats, "id1")
        ):
            result = get_cursor_chat_ids("file:///test")
            assert result == {"id1", "id2"}

    def test_get_cursor_chat_names(self):
        """get_cursor_chat_names delegates to list_cursor_chats."""
        mock_chats = [
            {"composerId": "id1", "name": "Chat 1"},
            {"composerId": "id2", "name": "Chat 2"},
        ]
        with patch(
            "server.workspace_state.list_cursor_chats", return_value=(mock_chats, "id1")
        ):
            result = get_cursor_chat_names("file:///test")
            assert result == {"id1": "Chat 1", "id2": "Chat 2"}

    def test_get_cursor_chat_info_no_workspace_storage(self):
        """get_cursor_chat_info_from_db returns None when no workspace storage."""
        with patch("pathlib.Path.home", return_value=Path("/fake/home")):
            with patch("pathlib.Path.exists", return_value=False):
                chat_id, chat_name = get_cursor_chat_info_from_db("file:///test")
                assert chat_id is None
                assert chat_name is None

    def test_get_cursor_chat_info_exception(self):
        """get_cursor_chat_info_from_db returns None on exception."""
        with patch("pathlib.Path.home", side_effect=Exception("boom")):
            chat_id, chat_name = get_cursor_chat_info_from_db("file:///test")
            assert chat_id is None
            assert chat_name is None

    def test_list_cursor_chats_no_workspace_storage(self):
        """list_cursor_chats returns empty when no workspace storage dir."""
        with patch("pathlib.Path.home", return_value=Path("/fake/home")):
            with patch("pathlib.Path.exists", return_value=False):
                chats, active_id = list_cursor_chats("file:///test")
                assert chats == []
                assert active_id is None

    def test_list_cursor_chats_exception(self):
        """list_cursor_chats returns empty on exception."""
        with patch("pathlib.Path.home", side_effect=Exception("boom")):
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
        with patch(
            "server.workspace_state.MEETINGS_DB_FILE",
            Path("/fake/nonexistent.db"),
            create=True,
        ):
            with patch("pathlib.Path.exists", return_value=False):
                result = get_meeting_transcript_issue_keys()
                assert result == {}

    def test_inject_context_no_workspace_storage(self):
        """inject_context_to_cursor_chat returns False when no workspace storage."""
        with patch("pathlib.Path.home", return_value=Path("/fake/home")):
            with patch("pathlib.Path.exists", return_value=False):
                result = inject_context_to_cursor_chat("file:///test")
                assert result is False

    def test_inject_context_exception(self):
        """inject_context_to_cursor_chat returns False on exception."""
        with patch("pathlib.Path.home", side_effect=Exception("boom")):
            result = inject_context_to_cursor_chat("file:///test")
            assert result is False


class TestTryRestoreWorkspaceFromDisk:
    """Tests for _try_restore_workspace_from_disk."""

    def setup_method(self):
        WorkspaceRegistry.clear()

    def teardown_method(self):
        WorkspaceRegistry.clear()

    def test_no_file(self, tmp_path):
        """Returns False when persist file doesn't exist."""
        import server.workspace_state as ws_module

        with patch.object(ws_module, "PERSIST_FILE", tmp_path / "nonexistent.json"):
            result = WorkspaceRegistry._try_restore_workspace_from_disk("file:///ws1")
            assert result is False

    def test_old_version(self, tmp_path):
        """Returns False for old version format."""
        import server.workspace_state as ws_module

        persist_file = tmp_path / "states.json"
        persist_file.write_text(json.dumps({"version": 1, "workspaces": {}}))
        with patch.object(ws_module, "PERSIST_FILE", persist_file):
            result = WorkspaceRegistry._try_restore_workspace_from_disk("file:///ws1")
            assert result is False

    def test_workspace_not_in_file(self, tmp_path):
        """Returns False when workspace is not in persisted data."""
        import server.workspace_state as ws_module

        persist_file = tmp_path / "states.json"
        persist_file.write_text(
            json.dumps(
                {
                    "version": 2,
                    "workspaces": {
                        "file:///other": {"sessions": {}, "project": "other"}
                    },
                }
            )
        )
        with patch.object(ws_module, "PERSIST_FILE", persist_file):
            result = WorkspaceRegistry._try_restore_workspace_from_disk("file:///ws1")
            assert result is False

    def test_restore_success(self, tmp_path):
        """Successfully restores workspace from disk."""
        import server.workspace_state as ws_module

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
                                    "meeting_references": [
                                        {"meeting_id": 1, "title": "Sprint"}
                                    ],
                                }
                            },
                        }
                    },
                }
            )
        )
        with patch.object(ws_module, "PERSIST_FILE", persist_file):
            result = WorkspaceRegistry._try_restore_workspace_from_disk("file:///ws1")
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
        import server.workspace_state as ws_module

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
            result = WorkspaceRegistry._try_restore_workspace_from_disk("file:///ws1")
            assert result is True

    def test_restore_exception(self, tmp_path):
        """Returns False on exception during restore."""
        import server.workspace_state as ws_module

        persist_file = tmp_path / "states.json"
        persist_file.write_text("not valid json {{{")
        with patch.object(ws_module, "PERSIST_FILE", persist_file):
            result = WorkspaceRegistry._try_restore_workspace_from_disk("file:///ws1")
            assert result is False

    def test_restore_old_format_tool_count(self, tmp_path):
        """Restores tool_count from old format (tool_count field)."""
        import server.workspace_state as ws_module

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
            result = WorkspaceRegistry._try_restore_workspace_from_disk("file:///ws1")
            assert result is True
            session = WorkspaceRegistry.get("file:///ws1").get_session("s1")
            assert session.static_tool_count == 30

    def test_restore_old_format_active_tools(self, tmp_path):
        """Restores tool count from old format (active_tools list)."""
        import server.workspace_state as ws_module

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
            result = WorkspaceRegistry._try_restore_workspace_from_disk("file:///ws1")
            assert result is True
            session = WorkspaceRegistry.get("file:///ws1").get_session("s1")
            assert session.static_tool_count == 3

    def test_restore_session_inherits_workspace_project(self, tmp_path):
        """Session with no project inherits from workspace."""
        import server.workspace_state as ws_module

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
            WorkspaceRegistry._try_restore_workspace_from_disk("file:///ws1")
            session = WorkspaceRegistry.get("file:///ws1").get_session("s1")
            assert session.project == "ws-project"
            assert session.is_project_auto_detected is True


class TestLoadFromDiskAdvanced:
    """Additional tests for load_from_disk covering edge cases."""

    def setup_method(self):
        WorkspaceRegistry.clear()

    def teardown_method(self):
        WorkspaceRegistry.clear()

    def test_load_restores_session_with_old_tool_count(self, tmp_path):
        """load_from_disk handles old-format tool_count field."""
        import server.workspace_state as ws_module

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

            with patch(
                "server.workspace_state.list_cursor_chats", return_value=([], None)
            ):
                with patch.object(
                    WorkspaceRegistry, "_detect_project", return_value=None
                ):
                    restored = WorkspaceRegistry.load_from_disk()

            assert restored == 1
            ws = WorkspaceRegistry.get("file:///ws1")
            assert ws is not None
            session = ws.get_session("s1")
            assert session.static_tool_count == 20

    def test_load_restores_session_with_active_tools(self, tmp_path):
        """load_from_disk handles old-format active_tools list."""
        import server.workspace_state as ws_module

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

            with patch(
                "server.workspace_state.list_cursor_chats", return_value=([], None)
            ):
                with patch.object(
                    WorkspaceRegistry, "_detect_project", return_value=None
                ):
                    restored = WorkspaceRegistry.load_from_disk()

            assert restored == 1
            session = WorkspaceRegistry.get("file:///ws1").get_session("s1")
            assert session.static_tool_count == 2

    def test_load_re_detects_project(self, tmp_path):
        """load_from_disk re-detects project from URI."""
        import server.workspace_state as ws_module

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

            with patch(
                "server.workspace_state.list_cursor_chats", return_value=([], None)
            ):
                with patch.object(
                    WorkspaceRegistry, "_detect_project", return_value="new-name"
                ):
                    restored = WorkspaceRegistry.load_from_disk()

            assert restored == 1
            ws = WorkspaceRegistry.get("file:///ws1")
            assert ws.project == "new-name"
            assert ws.is_auto_detected is True

    def test_load_skips_stale_empty_workspaces(self, tmp_path):
        """load_from_disk skips stale workspaces with no sessions."""
        import server.workspace_state as ws_module

        persist_file = tmp_path / "workspace_states.json"

        stale_time = (datetime.now() - timedelta(hours=48)).isoformat()

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

            with patch(
                "server.workspace_state.list_cursor_chats", return_value=([], None)
            ):
                with patch.object(
                    WorkspaceRegistry, "_detect_project", return_value=None
                ):
                    restored = WorkspaceRegistry.load_from_disk()

            assert restored == 0
            # Stale empty workspace should not be added
            assert WorkspaceRegistry.count() == 0

    def test_load_general_exception(self, tmp_path):
        """load_from_disk handles general exceptions gracefully."""
        import server.workspace_state as ws_module

        persist_file = tmp_path / "workspace_states.json"
        persist_file.write_text('{"version": 2, "workspaces": {}}')

        with (
            patch.object(ws_module, "PERSIST_DIR", tmp_path),
            patch.object(ws_module, "PERSIST_FILE", persist_file),
        ):
            with patch("builtins.open", side_effect=IOError("disk error")):
                restored = WorkspaceRegistry.load_from_disk()
                assert restored == 0

    def test_load_updates_names_from_cursor(self, tmp_path):
        """load_from_disk updates session names from Cursor DB."""
        import server.workspace_state as ws_module

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
            with patch(
                "server.workspace_state.list_cursor_chats",
                return_value=(cursor_chats, "s1"),
            ):
                with patch.object(
                    WorkspaceRegistry, "_detect_project", return_value=None
                ):
                    restored = WorkspaceRegistry.load_from_disk()

            assert restored == 1
            ws = WorkspaceRegistry.get("file:///ws1")
            session = ws.get_session("s1")
            assert session.name == "New Name"
            assert ws.active_session_id == "s1"

    def test_load_restores_full_session_data(self, tmp_path):
        """load_from_disk restores all session fields properly."""
        import server.workspace_state as ws_module

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
                                        "meeting_references": [
                                            {"meeting_id": 2, "title": "Retro"}
                                        ],
                                    }
                                },
                            }
                        },
                    }
                )
            )

            with patch(
                "server.workspace_state.list_cursor_chats", return_value=([], None)
            ):
                with patch.object(
                    WorkspaceRegistry, "_detect_project", return_value=None
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


class TestSyncWithCursorDb:
    """Tests for WorkspaceState.sync_with_cursor_db."""

    def setup_method(self):
        WorkspaceRegistry.clear()

    def teardown_method(self):
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
        with patch(
            "server.workspace_state.list_cursor_chats",
            return_value=(cursor_chats, "chat1"),
        ):
            with patch(
                "server.workspace_state.get_cursor_chat_issue_keys", return_value={}
            ):
                with patch(
                    "server.workspace_state.get_cursor_chat_personas", return_value={}
                ):
                    with patch(
                        "server.workspace_state.get_cursor_chat_projects",
                        return_value={},
                    ):
                        with patch(
                            "server.workspace_state.get_meeting_transcript_issue_keys",
                            return_value={},
                        ):
                            with patch.object(
                                state, "_get_loaded_tools", return_value=set()
                            ):
                                result = state.sync_with_cursor_db(
                                    skip_content_scan=True
                                )

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
        with patch("server.workspace_state.list_cursor_chats", return_value=([], None)):
            with patch.object(state, "_get_loaded_tools", return_value=set()):
                result = state.sync_with_cursor_db(skip_content_scan=True)

        assert result["removed"] == 1
        assert state.get_session("old-session") is None
        assert state.active_session_id is None

    def test_sync_renames_sessions(self):
        """sync_with_cursor_db updates names when Cursor's name changes."""
        state = WorkspaceState(workspace_uri="file:///test")
        session = ChatSession(
            session_id="s1", workspace_uri="file:///test", name="Old Name"
        )
        state.sessions["s1"] = session
        state.active_session_id = "s1"

        cursor_chats = [
            {"composerId": "s1", "name": "New Name", "lastUpdatedAt": None},
        ]
        with patch(
            "server.workspace_state.list_cursor_chats",
            return_value=(cursor_chats, None),
        ):
            with patch.object(state, "_get_loaded_tools", return_value=set()):
                result = state.sync_with_cursor_db(skip_content_scan=True)

        assert result["renamed"] == 1
        assert session.name == "New Name"

    def test_sync_clears_unnamed_placeholder(self):
        """sync_with_cursor_db clears 'unnamed' placeholder name."""
        state = WorkspaceState(workspace_uri="file:///test")
        session = ChatSession(
            session_id="s1", workspace_uri="file:///test", name="unnamed"
        )
        state.sessions["s1"] = session

        cursor_chats = [
            {"composerId": "s1", "name": None, "lastUpdatedAt": None},
        ]
        with patch(
            "server.workspace_state.list_cursor_chats",
            return_value=(cursor_chats, None),
        ):
            with patch.object(state, "_get_loaded_tools", return_value=set()):
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
        with patch(
            "server.workspace_state.list_cursor_chats",
            return_value=(cursor_chats, "s2"),
        ):
            with patch.object(state, "_get_loaded_tools", return_value=set()):
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
        with patch(
            "server.workspace_state.list_cursor_chats",
            return_value=(cursor_chats, None),
        ):
            with patch(
                "server.workspace_state.get_meeting_transcript_issue_keys",
                return_value={},
            ):
                with patch.object(state, "_get_loaded_tools", return_value=set()):
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
        with patch(
            "server.workspace_state.list_cursor_chats",
            return_value=(cursor_chats, None),
        ):
            with patch(
                "server.workspace_state.get_cursor_chat_issue_keys",
                return_value={"s1": "AAP-100"},
            ) as mock_issues:
                with patch(
                    "server.workspace_state.get_cursor_chat_personas",
                    return_value={"s1": "developer"},
                ) as mock_personas:
                    with patch(
                        "server.workspace_state.get_cursor_chat_projects",
                        return_value={},
                    ) as mock_projects:
                        with patch(
                            "server.workspace_state.get_meeting_transcript_issue_keys",
                            return_value={},
                        ):
                            with patch.object(
                                state, "_get_loaded_tools", return_value=set()
                            ):
                                state.sync_with_cursor_db(session_ids=["s1"])

        # Content scanning functions should be called
        mock_issues.assert_called_once_with(["s1"])
        mock_personas.assert_called_once_with(["s1"])
        mock_projects.assert_called_once_with(["s1"])

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
        with patch(
            "server.workspace_state.list_cursor_chats",
            return_value=(cursor_chats, None),
        ):
            with patch(
                "server.workspace_state.get_meeting_transcript_issue_keys",
                return_value={},
            ):
                # Return 30 tools (simulating more tools loaded)
                with patch.object(
                    state, "_get_loaded_tools", return_value=set(range(30))
                ):
                    state.sync_with_cursor_db(skip_content_scan=True)

        assert session.static_tool_count == 30

    def test_sync_updates_persona_from_content(self):
        """sync_with_cursor_db updates persona from chat content."""
        state = WorkspaceState(workspace_uri="file:///test")
        default_persona = get_default_persona()
        session = ChatSession(
            session_id="s1", workspace_uri="file:///test", persona=default_persona
        )
        state.sessions["s1"] = session

        cursor_chats = [
            {"composerId": "s1", "name": None, "lastUpdatedAt": None},
        ]
        with patch(
            "server.workspace_state.list_cursor_chats",
            return_value=(cursor_chats, None),
        ):
            with patch(
                "server.workspace_state.get_cursor_chat_issue_keys", return_value={}
            ):
                with patch(
                    "server.workspace_state.get_cursor_chat_personas",
                    return_value={"s1": "developer"},
                ):
                    with patch(
                        "server.workspace_state.get_cursor_chat_projects",
                        return_value={},
                    ):
                        with patch(
                            "server.workspace_state.get_meeting_transcript_issue_keys",
                            return_value={},
                        ):
                            with patch(
                                "server.workspace_state.get_persona_tool_count",
                                return_value=25,
                            ):
                                with patch.object(
                                    state, "_get_loaded_tools", return_value=set()
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
        with patch(
            "server.workspace_state.list_cursor_chats",
            return_value=(cursor_chats, None),
        ):
            with patch(
                "server.workspace_state.get_cursor_chat_issue_keys", return_value={}
            ):
                with patch(
                    "server.workspace_state.get_cursor_chat_personas", return_value={}
                ):
                    with patch(
                        "server.workspace_state.get_cursor_chat_projects",
                        return_value={"s1": "specific-proj"},
                    ):
                        with patch(
                            "server.workspace_state.get_meeting_transcript_issue_keys",
                            return_value={},
                        ):
                            with patch.object(
                                state, "_get_loaded_tools", return_value=set()
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
        with patch(
            "server.workspace_state.list_cursor_chats",
            return_value=(cursor_chats, None),
        ):
            with patch(
                "server.workspace_state.get_meeting_transcript_issue_keys",
                return_value=meeting_refs,
            ):
                with patch.object(state, "_get_loaded_tools", return_value=set()):
                    state.sync_with_cursor_db(skip_content_scan=True)

        assert len(session.meeting_references) == 1
        assert session.meeting_references[0]["meeting_id"] == 1


class TestCreateSessionAdvanced:
    """Tests for create_session with Cursor chat info."""

    def setup_method(self):
        WorkspaceRegistry.clear()

    def teardown_method(self):
        WorkspaceRegistry.clear()

    def test_create_session_uses_cursor_chat_id(self):
        """create_session uses Cursor's chat ID when available."""
        state = WorkspaceState(workspace_uri="file:///test")
        with patch.object(state, "_get_loaded_tools", return_value=set()):
            with patch.object(WorkspaceRegistry, "save_to_disk"):
                with patch(
                    "server.workspace_state.get_cursor_chat_info_from_db",
                    return_value=("cursor-uuid-123", "My Chat"),
                ):
                    session = state.create_session()

        assert session.session_id == "cursor-uuid-123"
        assert session.name == "My Chat"

    def test_create_session_uses_cursor_name_no_explicit_name(self):
        """create_session uses Cursor chat name when no explicit name given."""
        state = WorkspaceState(workspace_uri="file:///test")
        with patch.object(state, "_get_loaded_tools", return_value=set()):
            with patch.object(WorkspaceRegistry, "save_to_disk"):
                with patch(
                    "server.workspace_state.get_cursor_chat_info_from_db",
                    return_value=("id1", "Cursor Name"),
                ):
                    session = state.create_session()

        assert session.name == "Cursor Name"

    def test_create_session_explicit_name_overrides_cursor(self):
        """create_session explicit name overrides Cursor name."""
        state = WorkspaceState(workspace_uri="file:///test")
        with patch.object(state, "_get_loaded_tools", return_value=set()):
            with patch.object(WorkspaceRegistry, "save_to_disk"):
                with patch(
                    "server.workspace_state.get_cursor_chat_info_from_db",
                    return_value=("id1", "Cursor Name"),
                ):
                    session = state.create_session(name="My Explicit Name")

        assert session.name == "My Explicit Name"

    def test_create_session_fallback_id_when_cursor_unavailable(self):
        """create_session generates fallback ID when Cursor info unavailable."""
        state = WorkspaceState(workspace_uri="file:///test")
        with patch.object(state, "_get_loaded_tools", return_value=set()):
            with patch.object(WorkspaceRegistry, "save_to_disk"):
                with patch(
                    "server.workspace_state.get_cursor_chat_info_from_db",
                    return_value=(None, None),
                ):
                    session = state.create_session()

        assert session.session_id is not None
        assert len(session.session_id) > 0

    def test_create_session_explicit_session_id(self):
        """create_session uses explicit session_id when provided."""
        state = WorkspaceState(workspace_uri="file:///test")
        with patch.object(state, "_get_loaded_tools", return_value=set()):
            with patch.object(WorkspaceRegistry, "save_to_disk"):
                session = state.create_session(session_id="my-custom-id")

        assert session.session_id == "my-custom-id"

    def test_create_session_inherits_workspace_project(self):
        """create_session uses workspace project when none specified."""
        state = WorkspaceState(workspace_uri="file:///test")
        state.project = "ws-project"
        state.is_auto_detected = True
        with patch.object(state, "_get_loaded_tools", return_value=set()):
            with patch.object(WorkspaceRegistry, "save_to_disk"):
                with patch(
                    "server.workspace_state.get_cursor_chat_info_from_db",
                    return_value=(None, None),
                ):
                    session = state.create_session()

        assert session.project == "ws-project"
        assert session.is_project_auto_detected is True

    def test_create_session_explicit_project_overrides(self):
        """create_session uses explicit project over workspace project."""
        state = WorkspaceState(workspace_uri="file:///test")
        state.project = "ws-project"
        with patch.object(state, "_get_loaded_tools", return_value=set()):
            with patch.object(WorkspaceRegistry, "save_to_disk"):
                with patch(
                    "server.workspace_state.get_cursor_chat_info_from_db",
                    return_value=(None, None),
                ):
                    session = state.create_session(
                        project="explicit-project", is_project_auto_detected=False
                    )

        assert session.project == "explicit-project"
        assert session.is_project_auto_detected is False

    def test_get_active_session_refreshes_tools(self):
        """get_active_session refreshes static_tool_count when zero."""
        state = WorkspaceState(workspace_uri="file:///test")
        with patch.object(state, "_get_loaded_tools", return_value=set()):
            with patch.object(WorkspaceRegistry, "save_to_disk"):
                with patch(
                    "server.workspace_state.get_cursor_chat_info_from_db",
                    return_value=(None, None),
                ):
                    session = state.create_session()
                    session.static_tool_count = 0

        with patch.object(state, "_get_loaded_tools", return_value={"t1", "t2", "t3"}):
            active = state.get_active_session(refresh_tools=True)
            assert active.static_tool_count == 3

    def test_get_active_session_no_refresh(self):
        """get_active_session with refresh_tools=False doesn't update count."""
        state = WorkspaceState(workspace_uri="file:///test")
        with patch.object(state, "_get_loaded_tools", return_value=set()):
            with patch.object(WorkspaceRegistry, "save_to_disk"):
                with patch(
                    "server.workspace_state.get_cursor_chat_info_from_db",
                    return_value=(None, None),
                ):
                    session = state.create_session()
                    session.static_tool_count = 0

        active = state.get_active_session(refresh_tools=False)
        assert active.static_tool_count == 0


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

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with patch("pathlib.Path.home", return_value=tmp_path):
            with patch("subprocess.run", return_value=mock_result):
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

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({"allComposers": []})

        with patch("pathlib.Path.home", return_value=tmp_path):
            with patch("subprocess.run", return_value=mock_result):
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

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(
            {
                "allComposers": [
                    {"composerId": "c1", "isArchived": True, "lastUpdatedAt": 1000},
                    {"composerId": "c2", "isDraft": True, "lastUpdatedAt": 2000},
                ]
            }
        )

        with patch("pathlib.Path.home", return_value=tmp_path):
            with patch("subprocess.run", return_value=mock_result):
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

        mock_result = MagicMock()
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

        with patch("pathlib.Path.home", return_value=tmp_path):
            with patch("subprocess.run", return_value=mock_result):
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
        from server.workspace_state import get_cursor_chat_id_from_db

        with patch(
            "server.workspace_state.get_cursor_chat_info_from_db",
            return_value=("id123", "Name"),
        ):
            result = get_cursor_chat_id_from_db("file:///test")
            assert result == "id123"

    def test_returns_none(self):
        """get_cursor_chat_id_from_db returns None when no chat found."""
        from server.workspace_state import get_cursor_chat_id_from_db

        with patch(
            "server.workspace_state.get_cursor_chat_info_from_db",
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
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(composer_data)

        with patch("pathlib.Path.home", return_value=tmp_path):
            with patch("subprocess.run", return_value=mock_result):
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
            chats, active_id = list_cursor_chats("file:///my-project")
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

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with patch("pathlib.Path.home", return_value=tmp_path):
            with patch("subprocess.run", return_value=mock_result):
                chats, active_id = list_cursor_chats("file:///my-project")
                assert chats == []

    def test_handles_invalid_json_in_workspace(self, tmp_path):
        """Handles corrupt workspace.json gracefully."""
        ws_storage = tmp_path / ".config" / "Cursor" / "User" / "workspaceStorage"
        ws_dir = ws_storage / "dir1"
        ws_dir.mkdir(parents=True)
        workspace_json = ws_dir / "workspace.json"
        workspace_json.write_text("not json{{{")

        with patch("pathlib.Path.home", return_value=tmp_path):
            chats, active_id = list_cursor_chats("file:///my-project")
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
            chats, active_id = list_cursor_chats("file:///my-project")
            assert chats == []

    def test_deduplicates_across_dirs(self, tmp_path):
        """Deduplicates chats when same ID appears in multiple workspace dirs."""
        ws_storage = tmp_path / ".config" / "Cursor" / "User" / "workspaceStorage"

        for i, _ts in enumerate([1000, 2000]):
            ws_dir = ws_storage / f"dir{i}"
            ws_dir.mkdir(parents=True)
            (ws_dir / "workspace.json").write_text(
                json.dumps({"folder": "file:///project"})
            )
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

        with patch("pathlib.Path.home", return_value=tmp_path):
            with patch("subprocess.run", side_effect=mock_results):
                chats, active_id = list_cursor_chats("file:///project")

        assert len(chats) == 1
        assert chats[0]["name"] == "New"  # Should keep the newer one


class TestGetCursorChatIssueKeysDetailed:
    """Detailed tests for get_cursor_chat_issue_keys with mocked sqlite3."""

    def test_finds_issue_keys_in_chat(self):
        """Finds AAP-XXXXX patterns in chat content."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
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

        with patch("pathlib.Path.exists", return_value=True):
            with patch("sqlite3.connect", return_value=mock_conn):
                result = get_cursor_chat_issue_keys(["chat1"])

        assert "chat1" in result
        assert "AAP-12345" in result["chat1"]
        assert "AAP-12346" in result["chat1"]
        assert "AAP-12347" in result["chat1"]

    def test_handles_sqlite_error(self):
        """Handles sqlite3 connection error gracefully."""
        import sqlite3

        with patch("pathlib.Path.exists", return_value=True):
            with patch("sqlite3.connect", side_effect=sqlite3.Error("DB locked")):
                result = get_cursor_chat_issue_keys(["chat1"])
                assert result == {}

    def test_handles_invalid_json_in_value(self):
        """Handles invalid JSON in database values."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("bubbleId:chat1:1", "not valid json"),
        ]

        with patch("pathlib.Path.exists", return_value=True):
            with patch("sqlite3.connect", return_value=mock_conn):
                result = get_cursor_chat_issue_keys(["chat1"])
                assert result == {}

    def test_sorts_issue_keys_numerically(self):
        """Issue keys are sorted by numeric part."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            (
                "bubbleId:chat1:1",
                json.dumps({"text": "AAP-99999 and AAP-10000 and AAP-50000"}),
            ),
        ]

        with patch("pathlib.Path.exists", return_value=True):
            with patch("sqlite3.connect", return_value=mock_conn):
                result = get_cursor_chat_issue_keys(["chat1"])
                assert result["chat1"] == "AAP-10000, AAP-50000, AAP-99999"

    def test_handles_per_chat_sqlite_error(self):
        """Handles sqlite3 error for individual chat query."""
        import sqlite3

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = sqlite3.Error("query failed")

        with patch("pathlib.Path.exists", return_value=True):
            with patch("sqlite3.connect", return_value=mock_conn):
                result = get_cursor_chat_issue_keys(["chat1"])
                assert result == {}


class TestGetCursorChatContentDetailed:
    """Tests for get_cursor_chat_content with mocked subprocess."""

    def test_valid_uuid_no_db(self):
        """Returns empty result when global DB doesn't exist."""
        with patch("pathlib.Path.exists", return_value=False):
            result = get_cursor_chat_content("12345678-1234-5678-1234-567812345678")
            assert result["message_count"] == 0

    def test_valid_uuid_db_query_fails(self):
        """Returns empty result when DB query fails."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "error"

        with patch("pathlib.Path.exists", return_value=True):
            with patch("subprocess.run", return_value=mock_result):
                result = get_cursor_chat_content("12345678-1234-5678-1234-567812345678")
                assert result["message_count"] == 0

    def test_parses_messages(self):
        """Parses user and assistant messages from DB output."""
        bid = "bubbleId:12345678-1234-5678-1234-567812345678"
        msg1 = json.dumps({"type": 1, "text": "Hello", "createdAt": 1700000000000})
        msg2 = json.dumps(
            {"type": 2, "text": "Hi there! AAP-12345", "createdAt": 1700000001000}
        )
        lines = [f"{bid}:1|{msg1}", f"{bid}:2|{msg2}"]
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "\n".join(lines)

        with patch("pathlib.Path.exists", return_value=True):
            with patch("subprocess.run", return_value=mock_result):
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
        line = f"bubbleId:12345678-1234-5678-1234-567812345678:1|{json.dumps(msg_data)}"
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = line

        with patch("pathlib.Path.exists", return_value=True):
            with patch("subprocess.run", return_value=mock_result):
                result = get_cursor_chat_content("12345678-1234-5678-1234-567812345678")

        assert result["summary"]["tool_calls"] == 1
        assert result["summary"]["code_changes"] == 1

    def test_handles_timeout(self):
        """Handles subprocess timeout gracefully."""
        import subprocess as sp

        with patch("pathlib.Path.exists", return_value=True):
            with patch("subprocess.run", side_effect=sp.TimeoutExpired("sqlite3", 30)):
                result = get_cursor_chat_content("12345678-1234-5678-1234-567812345678")
                assert result["message_count"] == 0

    def test_handles_malformed_lines(self):
        """Handles lines without pipe separator."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "no pipe here\n\nsome-key-only"

        with patch("pathlib.Path.exists", return_value=True):
            with patch("subprocess.run", return_value=mock_result):
                result = get_cursor_chat_content("12345678-1234-5678-1234-567812345678")
                assert result["message_count"] == 0

    def test_max_messages_limit(self):
        """Respects max_messages limit."""
        lines = []
        for i in range(10):
            msg = json.dumps(
                {"type": 1, "text": f"msg {i}", "createdAt": 1700000000000 + i * 1000}
            )
            lines.append(f"bubbleId:12345678-1234-5678-1234-567812345678:{i}|{msg}")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "\n".join(lines)

        with patch("pathlib.Path.exists", return_value=True):
            with patch("subprocess.run", return_value=mock_result):
                result = get_cursor_chat_content(
                    "12345678-1234-5678-1234-567812345678", max_messages=3
                )
                assert len(result["messages"]) == 3
                assert result["message_count"] == 10

    def test_handles_general_exception(self):
        """Handles general exception."""
        with patch("pathlib.Path.exists", return_value=True):
            with patch("subprocess.run", side_effect=RuntimeError("unexpected")):
                result = get_cursor_chat_content("12345678-1234-5678-1234-567812345678")
                assert result["message_count"] == 0


class TestGetCursorChatPersonasDetailed:
    """Tests for get_cursor_chat_personas with mocked sqlite3."""

    def test_detects_persona_load_call(self):
        """Detects persona from persona_load('developer') call."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("bubbleId:chat1:5", json.dumps({"text": 'persona_load("developer")'})),
        ]

        with patch("pathlib.Path.exists", return_value=True):
            with patch("sqlite3.connect", return_value=mock_conn):
                result = get_cursor_chat_personas(["chat1"])

        assert result.get("chat1") == "developer"

    def test_detects_agent_parameter(self):
        """Detects persona from agent='devops' in session_start."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("bubbleId:chat1:3", json.dumps({"text": 'session_start(agent="devops")'})),
        ]

        with patch("pathlib.Path.exists", return_value=True):
            with patch("sqlite3.connect", return_value=mock_conn):
                result = get_cursor_chat_personas(["chat1"])

        assert result.get("chat1") == "devops"

    def test_returns_last_persona(self):
        """Returns the last persona loaded (highest bubble_id)."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("bubbleId:chat1:1", json.dumps({"text": 'persona_load("developer")'})),
            ("bubbleId:chat1:5", json.dumps({"text": 'persona_load("devops")'})),
        ]

        with patch("pathlib.Path.exists", return_value=True):
            with patch("sqlite3.connect", return_value=mock_conn):
                result = get_cursor_chat_personas(["chat1"])

        assert result.get("chat1") == "devops"

    def test_ignores_invalid_personas(self):
        """Ignores persona names not in VALID_PERSONAS."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            (
                "bubbleId:chat1:1",
                json.dumps({"text": 'persona_load("invalidpersona")'}),
            ),
        ]

        with patch("pathlib.Path.exists", return_value=True):
            with patch("sqlite3.connect", return_value=mock_conn):
                result = get_cursor_chat_personas(["chat1"])

        assert "chat1" not in result

    def test_handles_sqlite_error(self):
        """Handles sqlite3 connection error."""
        import sqlite3

        with patch("pathlib.Path.exists", return_value=True):
            with patch("sqlite3.connect", side_effect=sqlite3.Error("locked")):
                result = get_cursor_chat_personas(["chat1"])
                assert result == {}

    def test_handles_empty_text(self):
        """Handles entries with empty text field."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("bubbleId:chat1:1", json.dumps({"text": ""})),
        ]

        with patch("pathlib.Path.exists", return_value=True):
            with patch("sqlite3.connect", return_value=mock_conn):
                result = get_cursor_chat_personas(["chat1"])
                assert "chat1" not in result

    def test_handles_per_chat_sqlite_error(self):
        """Handles sqlite3 error for individual chat query."""
        import sqlite3

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = sqlite3.Error("query failed")

        with patch("pathlib.Path.exists", return_value=True):
            with patch("sqlite3.connect", return_value=mock_conn):
                result = get_cursor_chat_personas(["chat1"])
                assert result == {}


class TestGetCursorChatProjectsDetailed:
    """Tests for get_cursor_chat_projects with mocked sqlite3."""

    def test_detects_project_from_session_start(self):
        """Detects project from session_start(project='backend') call."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
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

        with patch("server.utils.load_config", return_value=mock_config):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("sqlite3.connect", return_value=mock_conn):
                    result = get_cursor_chat_projects(["chat1"])

        assert result.get("chat1") == "automation-analytics-backend"

    def test_skips_redhat_ai_workflow(self):
        """Skips 'redhat-ai-workflow' as it's the default workspace."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
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

        with patch("server.utils.load_config", return_value=mock_config):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("sqlite3.connect", return_value=mock_conn):
                    result = get_cursor_chat_projects(["chat1"])

        assert "chat1" not in result

    def test_handles_sqlite_error(self):
        """Handles sqlite3 connection error."""
        import sqlite3

        mock_config = {"repositories": {"proj": {"path": "/p"}}}
        with patch("server.utils.load_config", return_value=mock_config):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("sqlite3.connect", side_effect=sqlite3.Error("locked")):
                    result = get_cursor_chat_projects(["chat1"])
                    assert result == {}

    def test_config_load_failure_uses_fallback(self):
        """Falls back to hardcoded project list when config fails."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("bubbleId:chat1:1", json.dumps({"text": 'project="pdf-generator"'})),
        ]

        with patch("server.utils.load_config", side_effect=Exception("config error")):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("sqlite3.connect", return_value=mock_conn):
                    result = get_cursor_chat_projects(["chat1"])

        assert result.get("chat1") == "pdf-generator"


class TestGetMeetingTranscriptIssueKeys:
    """Tests for get_meeting_transcript_issue_keys."""

    def test_db_not_found(self):
        """Returns empty when meet bot DB doesn't exist."""
        with patch(
            "server.workspace_state.MEETINGS_DB_FILE",
            new=Path("/nonexistent/db.sqlite"),
            create=True,
        ):
            result = get_meeting_transcript_issue_keys()
            assert result == {}

    def test_finds_standard_pattern(self):
        """Finds AAP-XXXXX pattern in transcripts."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = (
            "1|||Discussing AAP-12345 today|||Sprint Planning|||2025-01-20T10:00:00"
        )

        with patch(
            "server.paths.MEETINGS_DB_FILE",
            new=MagicMock(exists=MagicMock(return_value=True)),
        ):
            with patch("subprocess.run", return_value=mock_result):
                result = get_meeting_transcript_issue_keys()

        assert "AAP-12345" in result
        assert result["AAP-12345"][0]["meeting_id"] == 1
        assert result["AAP-12345"][0]["title"] == "Sprint Planning"

    def test_finds_spoken_pattern(self):
        """Finds spoken patterns like 'issue 12345' or 'ticket 12345'."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = (
            "1|||Let's talk about issue 12345|||Standup|||2025-01-20\n"
            "2|||ticket 67890 is blocked|||Standup|||2025-01-21"
        )

        with patch(
            "server.paths.MEETINGS_DB_FILE",
            new=MagicMock(exists=MagicMock(return_value=True)),
        ):
            with patch("subprocess.run", return_value=mock_result):
                result = get_meeting_transcript_issue_keys()

        assert "AAP-12345" in result
        assert "AAP-67890" in result

    def test_filters_by_issue_keys(self):
        """Filters results to specific issue keys when provided."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "1|||AAP-12345 and AAP-99999|||Meeting|||2025-01-20"

        with patch(
            "server.paths.MEETINGS_DB_FILE",
            new=MagicMock(exists=MagicMock(return_value=True)),
        ):
            with patch("subprocess.run", return_value=mock_result):
                result = get_meeting_transcript_issue_keys(issue_keys=["AAP-12345"])

        assert "AAP-12345" in result
        assert "AAP-99999" not in result

    def test_handles_query_failure(self):
        """Handles subprocess failure gracefully."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "error"

        with patch(
            "server.paths.MEETINGS_DB_FILE",
            new=MagicMock(exists=MagicMock(return_value=True)),
        ):
            with patch("subprocess.run", return_value=mock_result):
                result = get_meeting_transcript_issue_keys()
                assert result == {}

    def test_handles_timeout(self):
        """Handles subprocess timeout."""
        import subprocess as sp

        with patch(
            "server.paths.MEETINGS_DB_FILE",
            new=MagicMock(exists=MagicMock(return_value=True)),
        ):
            with patch("subprocess.run", side_effect=sp.TimeoutExpired("sqlite3", 30)):
                result = get_meeting_transcript_issue_keys()
                assert result == {}

    def test_handles_malformed_lines(self):
        """Handles lines with insufficient parts."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "1|||only two parts\n\ninvalid"

        with patch(
            "server.paths.MEETINGS_DB_FILE",
            new=MagicMock(exists=MagicMock(return_value=True)),
        ):
            with patch("subprocess.run", return_value=mock_result):
                result = get_meeting_transcript_issue_keys()
                assert result == {}

    def test_aggregates_matches_across_entries(self):
        """Aggregates match counts across transcript entries."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = (
            "1|||AAP-12345 mentioned here|||Sprint|||2025-01-20\n"
            "1|||AAP-12345 mentioned again|||Sprint|||2025-01-20"
        )

        with patch(
            "server.paths.MEETINGS_DB_FILE",
            new=MagicMock(exists=MagicMock(return_value=True)),
        ):
            with patch("subprocess.run", return_value=mock_result):
                result = get_meeting_transcript_issue_keys()

        assert "AAP-12345" in result
        assert result["AAP-12345"][0]["matches"] == 2


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

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "error"

        with patch("pathlib.Path.home", return_value=tmp_path):
            with patch("subprocess.run", return_value=mock_result):
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

        with patch("pathlib.Path.home", return_value=tmp_path):
            with patch("subprocess.run", side_effect=[read_result, write_result]):
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

        with patch("pathlib.Path.home", return_value=tmp_path):
            with patch("subprocess.run", side_effect=[read_result, write_result]):
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

        with patch("pathlib.Path.home", return_value=tmp_path):
            with patch("subprocess.run", return_value=read_result):
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

        with patch("pathlib.Path.home", return_value=tmp_path):
            with patch("subprocess.run", side_effect=[read_result, write_result]):
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


class TestSyncWithCursorDbAdvanced:
    """Additional sync_with_cursor_db tests for branch coverage."""

    def setup_method(self):
        WorkspaceRegistry.clear()

    def teardown_method(self):
        WorkspaceRegistry.clear()

    def test_sync_updates_last_activity_from_cursor(self):
        """sync_with_cursor_db updates session last_activity from Cursor timestamp."""
        state = WorkspaceState(workspace_uri="file:///test")
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        session.last_activity = datetime(2020, 1, 1)
        state.sessions["s1"] = session

        cursor_chats = [
            {"composerId": "s1", "name": None, "lastUpdatedAt": 1700000000000},
        ]
        with patch(
            "server.workspace_state.list_cursor_chats",
            return_value=(cursor_chats, None),
        ):
            with patch(
                "server.workspace_state.get_meeting_transcript_issue_keys",
                return_value={},
            ):
                with patch.object(state, "_get_loaded_tools", return_value=set()):
                    result = state.sync_with_cursor_db(skip_content_scan=True)

        assert result["updated"] == 1
        assert session.last_activity > datetime(2020, 1, 1)

    def test_sync_updates_zero_tool_count_from_cache(self):
        """sync_with_cursor_db updates tool count from persona cache when zero."""
        state = WorkspaceState(workspace_uri="file:///test")
        session = ChatSession(
            session_id="s1", workspace_uri="file:///test", persona="devops"
        )
        session.static_tool_count = 0
        state.sessions["s1"] = session
        # Not active session
        state.active_session_id = None

        cursor_chats = [
            {"composerId": "s1", "name": None, "lastUpdatedAt": None},
        ]
        with patch(
            "server.workspace_state.list_cursor_chats",
            return_value=(cursor_chats, None),
        ):
            with patch(
                "server.workspace_state.get_meeting_transcript_issue_keys",
                return_value={},
            ):
                with patch(
                    "server.workspace_state.get_persona_tool_count", return_value=15
                ):
                    with patch.object(state, "_get_loaded_tools", return_value=set()):
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
            "AAP-100": [
                {"meeting_id": 1, "title": "Sprint", "date": "2025-01-20", "matches": 2}
            ],
            "AAP-200": [
                {"meeting_id": 1, "title": "Sprint", "date": "2025-01-20", "matches": 3}
            ],
        }
        with patch(
            "server.workspace_state.list_cursor_chats",
            return_value=(cursor_chats, None),
        ):
            with patch(
                "server.workspace_state.get_meeting_transcript_issue_keys",
                return_value=meeting_refs,
            ):
                with patch.object(state, "_get_loaded_tools", return_value=set()):
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
        with patch(
            "server.workspace_state.list_cursor_chats",
            return_value=(cursor_chats, None),
        ):
            with patch(
                "server.workspace_state.get_cursor_chat_issue_keys", return_value={}
            ):
                with patch(
                    "server.workspace_state.get_cursor_chat_personas",
                    return_value={"c1": "developer"},
                ):
                    with patch(
                        "server.workspace_state.get_cursor_chat_projects",
                        return_value={"c1": "my-proj"},
                    ):
                        with patch(
                            "server.workspace_state.get_meeting_transcript_issue_keys",
                            return_value={},
                        ):
                            with patch(
                                "server.workspace_state.get_persona_tool_count",
                                return_value=30,
                            ):
                                with patch.object(
                                    state, "_get_loaded_tools", return_value=set()
                                ):
                                    state.sync_with_cursor_db(session_ids=["c1"])

        session = state.get_session("c1")
        assert session.persona == "developer"
        assert session.project == "my-proj"
        assert session.static_tool_count == 30

    def test_sync_no_changes(self):
        """sync_with_cursor_db returns zeros when nothing changed."""
        state = WorkspaceState(workspace_uri="file:///test")
        session = ChatSession(
            session_id="s1", workspace_uri="file:///test", name="Same Name"
        )
        state.sessions["s1"] = session
        state.active_session_id = "s1"

        cursor_chats = [
            {"composerId": "s1", "name": "Same Name", "lastUpdatedAt": None},
        ]
        with patch(
            "server.workspace_state.list_cursor_chats",
            return_value=(cursor_chats, "s1"),
        ):
            with patch(
                "server.workspace_state.get_meeting_transcript_issue_keys",
                return_value={},
            ):
                with patch.object(state, "_get_loaded_tools", return_value=set()):
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
        with patch(
            "server.workspace_state.list_cursor_chats",
            return_value=(cursor_chats, None),
        ):
            with patch(
                "server.workspace_state.get_cursor_chat_issue_keys",
                return_value={"c1": "AAP-22222"},
            ):
                with patch(
                    "server.workspace_state.get_cursor_chat_personas", return_value={}
                ):
                    with patch(
                        "server.workspace_state.get_cursor_chat_projects",
                        return_value={},
                    ):
                        with patch(
                            "server.workspace_state.get_meeting_transcript_issue_keys",
                            return_value={},
                        ):
                            with patch.object(
                                state, "_get_loaded_tools", return_value=set()
                            ):
                                state.sync_with_cursor_db(session_ids=["c1"])

        session = state.get_session("c1")
        assert "AAP-11111" in session.issue_key
        assert "AAP-22222" in session.issue_key
