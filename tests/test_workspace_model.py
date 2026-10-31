"""Tests for WorkspaceState: sessions within one workspace."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from server.persona_loader import PersonaLoader
from server.workspace_model import loaded_tool_names
from server.workspace_state import (
    WorkspaceRegistry,
    WorkspaceState,
    get_default_persona,
)
from tests.workspace_patches import offline_registry


class TestWorkspaceState:
    """Tests for WorkspaceState dataclass."""

    def test_default_values(self):
        """Test WorkspaceState has correct defaults."""
        state = WorkspaceState(workspace_uri="file:///test")

        assert state.workspace_uri == "file:///test"
        assert state.project is None
        assert not state.sessions
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


class TestWorkspaceStateAdvanced:
    """Tests for WorkspaceState methods not covered by basic tests."""

    def setup_method(self):
        """Start from an empty registry."""
        WorkspaceRegistry.clear()

    def teardown_method(self):
        """Leave an empty registry behind."""
        WorkspaceRegistry.clear()

    def test_workspace_touch(self):
        """WorkspaceState.touch() updates last_activity."""
        state = WorkspaceState(workspace_uri="file:///test")
        # Set last_activity to a known past time instead of sleeping
        past_time = datetime.now(tz=timezone.utc) - timedelta(seconds=10)
        state.last_activity = past_time
        state.touch()
        assert state.last_activity > past_time

    def test_workspace_is_stale(self):
        """WorkspaceState.is_stale detects old workspaces."""
        state = WorkspaceState(workspace_uri="file:///test")
        assert state.is_stale(max_age_hours=1) is False
        state.last_activity = datetime.now(tz=timezone.utc) - timedelta(hours=5)
        assert state.is_stale(max_age_hours=4) is True
        assert state.is_stale(max_age_hours=6) is False

    def test_get_or_create_session_returns_existing(self):
        """get_or_create_session returns active session if one exists."""
        state = WorkspaceState(workspace_uri="file:///test")
        with offline_registry():
            s1 = state.create_session(persona="developer", name="existing")
            s2 = state.get_or_create_session(persona="devops")
            assert s1.session_id == s2.session_id  # same session

    def test_get_or_create_session_creates_when_none(self):
        """get_or_create_session creates session when none exists."""
        state = WorkspaceState(workspace_uri="file:///test")
        assert state.get_active_session() is None
        with offline_registry():
            s = state.get_or_create_session(persona="developer")
            assert s is not None
            assert s.persona == "developer"

    def test_remove_session_sets_active_to_none(self):
        """Removing the only session sets active to None."""
        state = WorkspaceState(workspace_uri="file:///test")
        with offline_registry():
            session = state.create_session()
            state.remove_session(session.session_id)
            assert state.active_session_id is None
            assert state.session_count() == 0

    def test_cleanup_stale_sessions(self):
        """cleanup_stale_sessions removes stale sessions not in Cursor."""
        state = WorkspaceState(workspace_uri="file:///test")
        with offline_registry():
            s1 = state.create_session(name="stale")
            s1.last_activity = datetime.now(tz=timezone.utc) - timedelta(hours=48)

            s2 = state.create_session(name="fresh")

            with patch("server.cursor_chat_db.get_cursor_chat_ids", return_value=set()):
                removed = state.cleanup_stale_sessions(max_age_hours=24)

            assert removed == 1
            assert state.session_count() == 1
            assert state.get_session(s2.session_id) is not None

    def test_cleanup_stale_sessions_keeps_cursor_sessions(self):
        """cleanup_stale_sessions keeps stale sessions that are still in Cursor."""
        state = WorkspaceState(workspace_uri="file:///test")
        with offline_registry():
            s1 = state.create_session(name="stale-but-in-cursor")
            s1.last_activity = datetime.now(tz=timezone.utc) - timedelta(hours=48)

            # Cursor still has this session
            with patch(
                "server.cursor_chat_db.get_cursor_chat_ids",
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
        """get_loaded_tools returns tools from PersonaLoader."""
        mock_loader = MagicMock(spec=PersonaLoader)
        mock_loader.get_status.return_value = {
            "tools": ["git_status", "git_diff", "k8s_pods"],
            "loaded_modules": ["git", "k8s"],
        }
        with patch("server.persona_loader.get_loader", return_value=mock_loader):
            tools = loaded_tool_names()
            assert tools == {"git_status", "git_diff", "k8s_pods"}

    def test_get_loaded_tools_no_loader(self):
        """get_loaded_tools returns empty set when loader unavailable."""
        with patch("server.persona_loader.get_loader", return_value=None):
            tools = loaded_tool_names()
            assert tools == set()

    def test_get_loaded_tools_exception(self):
        """get_loaded_tools returns empty set on exception."""
        with patch("server.persona_loader.get_loader", side_effect=AttributeError("loader not ready")):
            tools = loaded_tool_names()
            assert tools == set()


class TestWorkspaceStateBackwardCompat:
    """WorkspaceState properties delegating to the active session."""

    def setup_method(self):
        """Start from an empty registry."""
        WorkspaceRegistry.clear()

    def teardown_method(self):
        """Leave an empty registry behind."""
        WorkspaceRegistry.clear()

    def test_backward_compat_started_at_no_session(self):
        """started_at property returns created_at when no session."""
        state = WorkspaceState(workspace_uri="file:///test")
        assert state.started_at == state.created_at

    def test_backward_compat_tool_filter_cache_no_session(self):
        """tool_filter_cache property returns empty dict when no session."""
        state = WorkspaceState(workspace_uri="file:///test")
        assert not state.tool_filter_cache

    def test_backward_compat_clear_filter_cache_no_session(self):
        """clear_filter_cache does nothing when no session."""
        state = WorkspaceState(workspace_uri="file:///test")
        state.clear_filter_cache()  # Test verifies no exception is raised
        assert not state.tool_filter_cache

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
        with offline_registry():
            session = state.create_session()
            state.branch = "my-branch"
            assert session.branch == "my-branch"

    def test_backward_compat_active_tools_setter_with_session(self):
        """active_tools setter on workspace delegates to session."""
        state = WorkspaceState(workspace_uri="file:///test")
        with offline_registry():
            session = state.create_session()
            state.active_tools = {"a", "b"}
            assert session.static_tool_count == 2

    def test_backward_compat_started_at_with_session(self):
        """started_at returns session's started_at when session exists."""
        state = WorkspaceState(workspace_uri="file:///test")
        with offline_registry():
            session = state.create_session()
            assert state.started_at == session.started_at

    def test_backward_compat_tool_filter_cache_with_session(self):
        """tool_filter_cache returns session's cache when session exists."""
        state = WorkspaceState(workspace_uri="file:///test")
        with offline_registry():
            session = state.create_session()
            session.tool_filter_cache["key"] = ["tool"]
            assert state.tool_filter_cache == {"key": ["tool"]}

    def test_backward_compat_clear_filter_cache_with_session(self):
        """clear_filter_cache clears session's cache."""
        state = WorkspaceState(workspace_uri="file:///test")
        with offline_registry():
            session = state.create_session()
            session.tool_filter_cache["key"] = ["tool"]
            state.clear_filter_cache()
            assert not session.tool_filter_cache

    def test_backward_compat_persona_setter_no_session(self):
        """persona setter does nothing when no session."""
        state = WorkspaceState(workspace_uri="file:///test")
        state.persona = "devops"  # Test verifies no exception is raised
        assert True  # Setter does not raise without session

    def test_backward_compat_issue_key_setter_no_session(self):
        """issue_key setter does nothing when no session."""
        state = WorkspaceState(workspace_uri="file:///test")
        state.issue_key = "AAP-123"  # Test verifies no exception is raised
        assert state.issue_key is None  # No session to store issue_key


class TestCreateSessionAdvanced:
    """Tests for create_session with Cursor chat info."""

    def setup_method(self):
        """Start from an empty registry."""
        WorkspaceRegistry.clear()

    def teardown_method(self):
        """Leave an empty registry behind."""
        WorkspaceRegistry.clear()

    def test_create_session_uses_cursor_chat_id(self):
        """create_session uses Cursor's chat ID when available."""
        state = WorkspaceState(workspace_uri="file:///test")
        with offline_registry(("cursor-uuid-123", "My Chat")):
            session = state.create_session()

        assert session.session_id == "cursor-uuid-123"
        assert session.name == "My Chat"

    def test_create_session_uses_cursor_name_no_explicit_name(self):
        """create_session uses Cursor chat name when no explicit name given."""
        state = WorkspaceState(workspace_uri="file:///test")
        with offline_registry(("id1", "Cursor Name")):
            session = state.create_session()

        assert session.name == "Cursor Name"

    def test_create_session_explicit_name_overrides_cursor(self):
        """create_session explicit name overrides Cursor name."""
        state = WorkspaceState(workspace_uri="file:///test")
        with offline_registry(("id1", "Cursor Name")):
            session = state.create_session(name="My Explicit Name")

        assert session.name == "My Explicit Name"

    def test_create_session_fallback_id_when_cursor_unavailable(self):
        """create_session generates fallback ID when Cursor info unavailable."""
        state = WorkspaceState(workspace_uri="file:///test")
        with offline_registry():
            session = state.create_session()

        assert session.session_id is not None
        assert len(session.session_id) > 0

    def test_create_session_explicit_session_id(self):
        """create_session uses explicit session_id when provided."""
        state = WorkspaceState(workspace_uri="file:///test")
        with (
            patch("server.workspace_model.loaded_tool_names", return_value=set()),
            patch.object(WorkspaceRegistry, "save_to_disk"),
        ):
            session = state.create_session(session_id="my-custom-id")

        assert session.session_id == "my-custom-id"

    def test_create_session_inherits_workspace_project(self):
        """create_session uses workspace project when none specified."""
        state = WorkspaceState(workspace_uri="file:///test")
        state.project = "ws-project"
        state.is_auto_detected = True
        with offline_registry():
            session = state.create_session()

        assert session.project == "ws-project"
        assert session.is_project_auto_detected is True

    def test_create_session_explicit_project_overrides(self):
        """create_session uses explicit project over workspace project."""
        state = WorkspaceState(workspace_uri="file:///test")
        state.project = "ws-project"
        with offline_registry():
            session = state.create_session(project="explicit-project", is_project_auto_detected=False)

        assert session.project == "explicit-project"
        assert session.is_project_auto_detected is False

    def test_get_active_session_refreshes_tools(self):
        """get_active_session refreshes static_tool_count when zero."""
        state = WorkspaceState(workspace_uri="file:///test")
        with offline_registry():
            session = state.create_session()
            session.static_tool_count = 0

        with patch("server.workspace_model.loaded_tool_names", return_value={"t1", "t2", "t3"}):
            active = state.get_active_session(refresh_tools=True)
            assert active.static_tool_count == 3

    def test_get_active_session_no_refresh(self):
        """get_active_session with refresh_tools=False doesn't update count."""
        state = WorkspaceState(workspace_uri="file:///test")
        with offline_registry():
            session = state.create_session()
            session.static_tool_count = 0

        active = state.get_active_session(refresh_tools=False)
        assert active.static_tool_count == 0
