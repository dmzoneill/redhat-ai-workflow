"""Tests for server/workspace_utils.py - Helper functions for workspace-aware tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.workspace_state import DEFAULT_PROJECT

# All async functions in workspace_utils call WorkspaceRegistry.get_for_ctx(ctx).
# We patch at the class method level on the canonical module.
_GET_FOR_CTX = "server.workspace_state.WorkspaceRegistry.get_for_ctx"
_GET_OR_CREATE = "server.workspace_state.WorkspaceRegistry.get_or_create"
_SAVE_TO_DISK = "server.workspace_state.WorkspaceRegistry.save_to_disk"
_LOAD_CONFIG = "server.utils.load_config"


# ────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────


def _make_state_mock(
    workspace_uri="file:///test",
    project=None,
    persona="developer",
    issue_key=None,
    branch=None,
    active_session_id="sess-1",
    has_session=True,
):
    """Build a MagicMock that behaves like WorkspaceState."""
    state = MagicMock()
    state.workspace_uri = workspace_uri
    state.project = project
    state.persona = persona
    state.issue_key = issue_key
    state.branch = branch
    state.active_session_id = active_session_id if has_session else None

    session = None
    if has_session:
        session = MagicMock()
        session.session_id = active_session_id
        session.project = project
        session.persona = persona
        session.issue_key = issue_key
        session.branch = branch
        session.is_project_auto_detected = False
        session.tool_count = 0
        session.name = None
        session.clear_filter_cache = MagicMock()

    state.get_active_session.return_value = session
    state.to_dict.return_value = {
        "workspace_uri": workspace_uri,
        "project": project,
        "persona": persona,
        "issue_key": issue_key,
        "branch": branch,
        "active_session_id": active_session_id,
    }

    # create_session should return a new mock session
    new_session = MagicMock()
    new_session.session_id = "new-sess"
    new_session.name = "Auto-created"
    state.create_session.return_value = new_session

    state.clear_filter_cache = MagicMock()

    return state, session


def _mock_ctx():
    return MagicMock()


# ────────────────────────────────────────────────────────────────────
# get_workspace_from_ctx
# ────────────────────────────────────────────────────────────────────


class TestGetWorkspaceFromCtx:
    @pytest.mark.asyncio
    async def test_delegates_to_registry(self):
        from server.workspace_utils import get_workspace_from_ctx

        ctx = _mock_ctx()
        state, _ = _make_state_mock()
        with patch(_GET_FOR_CTX, new_callable=AsyncMock, return_value=state):
            result = await get_workspace_from_ctx(ctx)

        assert result is state


# ────────────────────────────────────────────────────────────────────
# get_workspace_project
# ────────────────────────────────────────────────────────────────────


class TestGetWorkspaceProject:
    @pytest.mark.asyncio
    async def test_returns_session_project(self):
        from server.workspace_utils import get_workspace_project

        state, session = _make_state_mock(project="my-backend")
        session.project = "my-backend"
        ctx = _mock_ctx()
        with patch(_GET_FOR_CTX, new_callable=AsyncMock, return_value=state):
            result = await get_workspace_project(ctx)

        assert result == "my-backend"

    @pytest.mark.asyncio
    async def test_falls_back_to_workspace_project(self):
        from server.workspace_utils import get_workspace_project

        state, session = _make_state_mock(project="workspace-proj")
        session.project = None  # Session has no project
        state.project = "workspace-proj"
        ctx = _mock_ctx()
        with patch(_GET_FOR_CTX, new_callable=AsyncMock, return_value=state):
            result = await get_workspace_project(ctx)

        assert result == "workspace-proj"

    @pytest.mark.asyncio
    async def test_falls_back_to_default_project(self):
        from server.workspace_utils import get_workspace_project

        state, session = _make_state_mock(project=None)
        session.project = None
        state.project = None
        ctx = _mock_ctx()
        with patch(_GET_FOR_CTX, new_callable=AsyncMock, return_value=state):
            result = await get_workspace_project(ctx)

        assert result == DEFAULT_PROJECT

    @pytest.mark.asyncio
    async def test_no_session_falls_back(self):
        from server.workspace_utils import get_workspace_project

        state, _ = _make_state_mock(project="ws-proj", has_session=False)
        state.project = "ws-proj"
        ctx = _mock_ctx()
        with patch(_GET_FOR_CTX, new_callable=AsyncMock, return_value=state):
            result = await get_workspace_project(ctx)

        assert result == "ws-proj"


# ────────────────────────────────────────────────────────────────────
# get_workspace_persona
# ────────────────────────────────────────────────────────────────────


class TestGetWorkspacePersona:
    @pytest.mark.asyncio
    async def test_returns_persona(self):
        from server.workspace_utils import get_workspace_persona

        state, _ = _make_state_mock(persona="devops")
        ctx = _mock_ctx()
        with patch(_GET_FOR_CTX, new_callable=AsyncMock, return_value=state):
            result = await get_workspace_persona(ctx)

        assert result == "devops"


# ────────────────────────────────────────────────────────────────────
# get_workspace_issue
# ────────────────────────────────────────────────────────────────────


class TestGetWorkspaceIssue:
    @pytest.mark.asyncio
    async def test_returns_issue_key(self):
        from server.workspace_utils import get_workspace_issue

        state, _ = _make_state_mock(issue_key="AAP-999")
        ctx = _mock_ctx()
        with patch(_GET_FOR_CTX, new_callable=AsyncMock, return_value=state):
            result = await get_workspace_issue(ctx)

        assert result == "AAP-999"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_issue(self):
        from server.workspace_utils import get_workspace_issue

        state, _ = _make_state_mock(issue_key=None)
        ctx = _mock_ctx()
        with patch(_GET_FOR_CTX, new_callable=AsyncMock, return_value=state):
            result = await get_workspace_issue(ctx)

        assert result is None


# ────────────────────────────────────────────────────────────────────
# get_workspace_branch
# ────────────────────────────────────────────────────────────────────


class TestGetWorkspaceBranch:
    @pytest.mark.asyncio
    async def test_returns_branch(self):
        from server.workspace_utils import get_workspace_branch

        state, _ = _make_state_mock(branch="feature/x")
        ctx = _mock_ctx()
        with patch(_GET_FOR_CTX, new_callable=AsyncMock, return_value=state):
            result = await get_workspace_branch(ctx)

        assert result == "feature/x"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_branch(self):
        from server.workspace_utils import get_workspace_branch

        state, _ = _make_state_mock(branch=None)
        ctx = _mock_ctx()
        with patch(_GET_FOR_CTX, new_callable=AsyncMock, return_value=state):
            result = await get_workspace_branch(ctx)

        assert result is None


# ────────────────────────────────────────────────────────────────────
# get_workspace_uri
# ────────────────────────────────────────────────────────────────────


class TestGetWorkspaceUri:
    @pytest.mark.asyncio
    async def test_returns_uri(self):
        from server.workspace_utils import get_workspace_uri

        state, _ = _make_state_mock(workspace_uri="file:///proj")
        ctx = _mock_ctx()
        with patch(_GET_FOR_CTX, new_callable=AsyncMock, return_value=state):
            result = await get_workspace_uri(ctx)

        assert result == "file:///proj"


# ────────────────────────────────────────────────────────────────────
# set_workspace_project
# ────────────────────────────────────────────────────────────────────


class TestSetWorkspaceProject:
    @pytest.mark.asyncio
    async def test_sets_session_project(self):
        from server.workspace_utils import set_workspace_project

        state, session = _make_state_mock(project="old")
        ctx = _mock_ctx()

        with (
            patch(_GET_FOR_CTX, new_callable=AsyncMock, return_value=state),
            patch(_LOAD_CONFIG, return_value={"repositories": {"new-proj": {}}}),
            patch(_SAVE_TO_DISK),
        ):
            result = await set_workspace_project(ctx, "new-proj")

        assert result is True
        assert session.project == "new-proj"
        assert session.is_project_auto_detected is False

    @pytest.mark.asyncio
    async def test_invalid_project_returns_false(self):
        from server.workspace_utils import set_workspace_project

        state, session = _make_state_mock(project="old")
        ctx = _mock_ctx()

        with (
            patch(_GET_FOR_CTX, new_callable=AsyncMock, return_value=state),
            patch(_LOAD_CONFIG, return_value={"repositories": {"valid": {}}}),
        ):
            result = await set_workspace_project(ctx, "nonexistent")

        assert result is False

    @pytest.mark.asyncio
    async def test_sets_workspace_project_when_no_session(self):
        from server.workspace_utils import set_workspace_project

        state, _ = _make_state_mock(project="old", has_session=False)
        ctx = _mock_ctx()

        with (
            patch(_GET_FOR_CTX, new_callable=AsyncMock, return_value=state),
            patch(_LOAD_CONFIG, return_value={"repositories": {"new-proj": {}}}),
            patch(_SAVE_TO_DISK),
        ):
            result = await set_workspace_project(ctx, "new-proj")

        assert result is True
        assert state.project == "new-proj"
        assert state.is_auto_detected is False

    @pytest.mark.asyncio
    async def test_default_project_accepted_without_config(self):
        from server.workspace_utils import set_workspace_project

        state, session = _make_state_mock()
        ctx = _mock_ctx()

        with (
            patch(_GET_FOR_CTX, new_callable=AsyncMock, return_value=state),
            patch(_LOAD_CONFIG, return_value={"repositories": {}}),
            patch(_SAVE_TO_DISK),
        ):
            result = await set_workspace_project(ctx, DEFAULT_PROJECT)

        assert result is True

    @pytest.mark.asyncio
    async def test_empty_config_allows_set(self):
        from server.workspace_utils import set_workspace_project

        state, session = _make_state_mock()
        ctx = _mock_ctx()

        with (
            patch(_GET_FOR_CTX, new_callable=AsyncMock, return_value=state),
            patch(_LOAD_CONFIG, return_value=None),
            patch(_SAVE_TO_DISK),
        ):
            result = await set_workspace_project(ctx, "anything")

        assert result is True


# ────────────────────────────────────────────────────────────────────
# set_workspace_persona
# ────────────────────────────────────────────────────────────────────


class TestSetWorkspacePersona:
    @pytest.mark.asyncio
    async def test_sets_persona(self):
        from server.workspace_utils import set_workspace_persona

        state, _ = _make_state_mock(persona="developer")
        ctx = _mock_ctx()
        with patch(_GET_FOR_CTX, new_callable=AsyncMock, return_value=state):
            await set_workspace_persona(ctx, "devops")

        assert state.persona == "devops"


# ────────────────────────────────────────────────────────────────────
# set_workspace_issue / set_workspace_branch
# ────────────────────────────────────────────────────────────────────


class TestSetWorkspaceIssueAndBranch:
    @pytest.mark.asyncio
    async def test_set_issue(self):
        from server.workspace_utils import set_workspace_issue

        state, _ = _make_state_mock()
        ctx = _mock_ctx()
        with patch(_GET_FOR_CTX, new_callable=AsyncMock, return_value=state):
            await set_workspace_issue(ctx, "AAP-123")

        assert state.issue_key == "AAP-123"

    @pytest.mark.asyncio
    async def test_clear_issue(self):
        from server.workspace_utils import set_workspace_issue

        state, _ = _make_state_mock(issue_key="AAP-123")
        ctx = _mock_ctx()
        with patch(_GET_FOR_CTX, new_callable=AsyncMock, return_value=state):
            await set_workspace_issue(ctx, None)

        assert state.issue_key is None

    @pytest.mark.asyncio
    async def test_set_branch(self):
        from server.workspace_utils import set_workspace_branch

        state, _ = _make_state_mock()
        ctx = _mock_ctx()
        with patch(_GET_FOR_CTX, new_callable=AsyncMock, return_value=state):
            await set_workspace_branch(ctx, "fix/bug")

        assert state.branch == "fix/bug"


# ────────────────────────────────────────────────────────────────────
# set_workspace_tool_count
# ────────────────────────────────────────────────────────────────────


class TestSetWorkspaceToolCount:
    @pytest.mark.asyncio
    async def test_sets_tool_count_on_session(self):
        from server.workspace_utils import set_workspace_tool_count

        state, session = _make_state_mock()
        ctx = _mock_ctx()
        with patch(_GET_FOR_CTX, new_callable=AsyncMock, return_value=state):
            await set_workspace_tool_count(ctx, 42)

        assert session.tool_count == 42

    @pytest.mark.asyncio
    async def test_no_session_does_not_crash(self):
        from server.workspace_utils import set_workspace_tool_count

        state, _ = _make_state_mock(has_session=False)
        ctx = _mock_ctx()
        with patch(_GET_FOR_CTX, new_callable=AsyncMock, return_value=state):
            await set_workspace_tool_count(ctx, 10)  # should not raise


# ────────────────────────────────────────────────────────────────────
# get_workspace_state_dict
# ────────────────────────────────────────────────────────────────────


class TestGetWorkspaceStateDict:
    @pytest.mark.asyncio
    async def test_returns_dict(self):
        from server.workspace_utils import get_workspace_state_dict

        state, _ = _make_state_mock(workspace_uri="file:///x", project="p")
        ctx = _mock_ctx()
        with patch(_GET_FOR_CTX, new_callable=AsyncMock, return_value=state):
            result = await get_workspace_state_dict(ctx)

        assert isinstance(result, dict)
        assert result["workspace_uri"] == "file:///x"


# ────────────────────────────────────────────────────────────────────
# is_tool_active_for_workspace
# ────────────────────────────────────────────────────────────────────


class TestIsToolActiveForWorkspace:
    @pytest.mark.asyncio
    async def test_always_returns_true_with_deprecation_warning(self):
        from server.workspace_utils import is_tool_active_for_workspace

        ctx = _mock_ctx()
        import warnings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = await is_tool_active_for_workspace(ctx, "k8s")
            assert result is True
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "always returns True" in str(w[0].message)


# ────────────────────────────────────────────────────────────────────
# ensure_session_exists
# ────────────────────────────────────────────────────────────────────


class TestEnsureSessionExists:
    @pytest.mark.asyncio
    async def test_returns_existing_session(self):
        from server.workspace_utils import ensure_session_exists

        state, session = _make_state_mock()
        session.session_id = "existing"
        ctx = _mock_ctx()
        with patch(_GET_FOR_CTX, new_callable=AsyncMock, return_value=state):
            result = await ensure_session_exists(ctx)

        assert result.session_id == "existing"

    @pytest.mark.asyncio
    async def test_creates_session_when_none(self):
        from server.workspace_utils import ensure_session_exists

        state, _ = _make_state_mock(has_session=False)
        ctx = _mock_ctx()
        with patch(_GET_FOR_CTX, new_callable=AsyncMock, return_value=state):
            result = await ensure_session_exists(ctx)

        assert result is not None
        assert result.name == "Auto-created"
        state.create_session.assert_called_once_with(name="Auto-created")


# ────────────────────────────────────────────────────────────────────
# get_active_session / get_session_id
# ────────────────────────────────────────────────────────────────────


class TestGetActiveSession:
    @pytest.mark.asyncio
    async def test_returns_session(self):
        from server.workspace_utils import get_active_session

        state, session = _make_state_mock()
        session.session_id = "s1"
        ctx = _mock_ctx()
        with patch(_GET_FOR_CTX, new_callable=AsyncMock, return_value=state):
            result = await get_active_session(ctx)

        assert result.session_id == "s1"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_session(self):
        from server.workspace_utils import get_active_session

        state, _ = _make_state_mock(has_session=False)
        ctx = _mock_ctx()
        with patch(_GET_FOR_CTX, new_callable=AsyncMock, return_value=state):
            result = await get_active_session(ctx)

        assert result is None


class TestGetSessionId:
    @pytest.mark.asyncio
    async def test_returns_id(self):
        from server.workspace_utils import get_session_id

        state, _ = _make_state_mock(active_session_id="sid-42")
        ctx = _mock_ctx()
        with patch(_GET_FOR_CTX, new_callable=AsyncMock, return_value=state):
            result = await get_session_id(ctx)

        assert result == "sid-42"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_session(self):
        from server.workspace_utils import get_session_id

        state, _ = _make_state_mock(has_session=False, active_session_id=None)
        state.active_session_id = None
        ctx = _mock_ctx()
        with patch(_GET_FOR_CTX, new_callable=AsyncMock, return_value=state):
            result = await get_session_id(ctx)

        assert result is None


# ────────────────────────────────────────────────────────────────────
# Synchronous helpers
# ────────────────────────────────────────────────────────────────────


class TestSyncHelpers:
    def test_get_default_workspace(self):
        from server.workspace_utils import get_default_workspace

        mock_state = MagicMock()
        with patch(_GET_OR_CREATE, return_value=mock_state):
            result = get_default_workspace()

        assert result is mock_state

    def test_get_project_sync(self):
        from server.workspace_utils import get_project_sync

        mock_state = MagicMock()
        mock_state.project = "proj-1"
        with patch(_GET_OR_CREATE, return_value=mock_state):
            result = get_project_sync()

        assert result == "proj-1"

    def test_get_project_sync_falls_back_to_default(self):
        from server.workspace_utils import get_project_sync

        mock_state = MagicMock()
        mock_state.project = None
        with patch(_GET_OR_CREATE, return_value=mock_state):
            result = get_project_sync()

        assert result == DEFAULT_PROJECT

    def test_get_persona_sync(self):
        from server.workspace_utils import get_persona_sync

        mock_state = MagicMock()
        mock_state.persona = "incident"
        with patch(_GET_OR_CREATE, return_value=mock_state):
            result = get_persona_sync()

        assert result == "incident"
