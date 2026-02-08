"""Tests for tool_modules.aa_workflow.src.chat_context."""

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tool_modules.aa_workflow.src import chat_context

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_chat_state():
    """Reset the module-level chat state between tests."""
    original = chat_context._chat_state.copy()
    chat_context._chat_state.update(
        {"project": None, "started_at": None, "issue_key": None, "branch": None}
    )
    yield
    chat_context._chat_state.update(original)


@pytest.fixture
def mock_config():
    """Provide a mock config with repositories."""
    config = {
        "repositories": {
            "backend": {
                "path": "/home/user/src/backend",
                "description": "Backend project",
                "jira_project": "AAP",
            },
            "frontend": {
                "path": "/home/user/src/frontend",
                "description": "Frontend project",
                "jira_project": "AAP",
            },
        }
    }
    with patch(
        "tool_modules.aa_workflow.src.chat_context.load_config",
        return_value=config,
    ):
        yield config


# ---------------------------------------------------------------------------
# Async functions
# ---------------------------------------------------------------------------


class TestGetChatProjectAsync:
    @pytest.mark.asyncio
    async def test_delegates_to_workspace_utils(self):
        ctx = AsyncMock()
        with patch(
            "server.workspace_utils.get_workspace_project",
            new_callable=AsyncMock,
            return_value="backend",
        ) as mock_fn:
            result = await chat_context.get_chat_project_async(ctx)
        assert result == "backend"
        mock_fn.assert_awaited_once_with(ctx)


class TestSetChatProjectAsync:
    @pytest.mark.asyncio
    async def test_delegates_to_workspace_utils(self):
        ctx = AsyncMock()
        with patch(
            "server.workspace_utils.set_workspace_project",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_fn:
            result = await chat_context.set_chat_project_async(ctx, "backend")
        assert result is True
        mock_fn.assert_awaited_once_with(ctx, "backend")


class TestGetChatIssueAsync:
    @pytest.mark.asyncio
    async def test_delegates_to_workspace_utils(self):
        ctx = AsyncMock()
        with patch(
            "server.workspace_utils.get_workspace_issue",
            new_callable=AsyncMock,
            return_value="AAP-123",
        ):
            result = await chat_context.get_chat_issue_async(ctx)
        assert result == "AAP-123"


class TestSetChatIssueAsync:
    @pytest.mark.asyncio
    async def test_delegates_to_workspace_utils(self):
        ctx = AsyncMock()
        with patch(
            "server.workspace_utils.set_workspace_issue",
            new_callable=AsyncMock,
        ) as mock_fn:
            await chat_context.set_chat_issue_async(ctx, "AAP-456")
        mock_fn.assert_awaited_once_with(ctx, "AAP-456")


class TestGetChatBranchAsync:
    @pytest.mark.asyncio
    async def test_delegates_to_workspace_utils(self):
        ctx = AsyncMock()
        with patch(
            "server.workspace_utils.get_workspace_branch",
            new_callable=AsyncMock,
            return_value="feature/test",
        ):
            result = await chat_context.get_chat_branch_async(ctx)
        assert result == "feature/test"


class TestSetChatBranchAsync:
    @pytest.mark.asyncio
    async def test_delegates_to_workspace_utils(self):
        ctx = AsyncMock()
        with patch(
            "server.workspace_utils.set_workspace_branch",
            new_callable=AsyncMock,
        ) as mock_fn:
            await chat_context.set_chat_branch_async(ctx, "feature/x")
        mock_fn.assert_awaited_once_with(ctx, "feature/x")


class TestGetChatStateAsync:
    @pytest.mark.asyncio
    async def test_returns_workspace_state(self):
        ctx = AsyncMock()
        mock_state = MagicMock()
        mock_state.project = "backend"
        mock_state.issue_key = "AAP-1"
        mock_state.branch = "main"
        mock_state.started_at = datetime(2025, 1, 1)
        mock_state.is_auto_detected = False
        mock_state.workspace_uri = "ws://test"
        mock_state.persona = "developer"
        with patch(
            "server.workspace_utils.get_workspace_from_ctx",
            new_callable=AsyncMock,
            return_value=mock_state,
        ):
            result = await chat_context.get_chat_state_async(ctx)
        assert result["project"] == "backend"
        assert result["issue_key"] == "AAP-1"
        assert result["branch"] == "main"
        assert result["persona"] == "developer"


class TestGetProjectWorkStatePathAsync:
    @pytest.mark.asyncio
    async def test_with_explicit_project(self):
        ctx = AsyncMock()
        with patch(
            "tool_modules.aa_workflow.src.constants.MEMORY_DIR",
            Path("/tmp/memory"),
        ):
            result = await chat_context.get_project_work_state_path_async(
                ctx, "backend"
            )
        assert result == Path("/tmp/memory/state/projects/backend/current_work.yaml")

    @pytest.mark.asyncio
    async def test_auto_detects_project(self):
        ctx = AsyncMock()
        with (
            patch(
                "server.workspace_utils.get_workspace_project",
                new_callable=AsyncMock,
                return_value="auto-proj",
            ),
            patch(
                "tool_modules.aa_workflow.src.constants.MEMORY_DIR",
                Path("/tmp/memory"),
            ),
        ):
            result = await chat_context.get_project_work_state_path_async(ctx)
        assert "auto-proj" in str(result)


# ---------------------------------------------------------------------------
# Sync functions
# ---------------------------------------------------------------------------


class TestDetectProjectFromCwd:
    def test_detects_matching_project(self, mock_config):
        with patch("pathlib.Path.cwd", return_value=Path("/home/user/src/backend")):
            result = chat_context._detect_project_from_cwd()
        assert result == "backend"

    def test_returns_none_for_unmatched(self, mock_config):
        with patch("pathlib.Path.cwd", return_value=Path("/some/other/dir")):
            result = chat_context._detect_project_from_cwd()
        assert result is None

    def test_returns_none_when_no_config(self):
        with patch(
            "tool_modules.aa_workflow.src.chat_context.load_config",
            return_value=None,
        ):
            result = chat_context._detect_project_from_cwd()
        assert result is None

    def test_handles_cwd_exception(self, mock_config):
        with patch("pathlib.Path.cwd", side_effect=OSError("no cwd")):
            result = chat_context._detect_project_from_cwd()
        assert result is None


class TestGetProjectInfo:
    def test_known_project(self, mock_config):
        result = chat_context._get_project_info("backend")
        assert result is not None
        assert result["jira_project"] == "AAP"

    def test_unknown_project(self, mock_config):
        result = chat_context._get_project_info("nonexistent")
        assert result is None

    def test_default_project(self, mock_config):
        result = chat_context._get_project_info("redhat-ai-workflow")
        assert result is not None
        assert "jira_project" in result

    def test_no_config(self):
        with patch(
            "tool_modules.aa_workflow.src.chat_context.load_config",
            return_value=None,
        ):
            result = chat_context._get_project_info("backend")
        assert result is None


class TestGetChatProject:
    def test_returns_explicit_project(self, mock_config):
        chat_context._chat_state["project"] = "backend"
        result = chat_context.get_chat_project()
        assert result == "backend"

    def test_detects_from_cwd(self, mock_config):
        with patch("pathlib.Path.cwd", return_value=Path("/home/user/src/backend")):
            result = chat_context.get_chat_project()
        assert result == "backend"

    def test_returns_default(self, mock_config):
        with (
            patch("pathlib.Path.cwd", return_value=Path("/some/other/dir")),
            patch(
                "server.workspace_utils.get_project_sync",
                side_effect=Exception,
            ),
        ):
            result = chat_context.get_chat_project()
        assert result == chat_context.DEFAULT_PROJECT

    def test_workspace_registry_priority(self, mock_config):
        with patch(
            "server.workspace_utils.get_project_sync",
            return_value="ws-project",
        ):
            result = chat_context.get_chat_project()
        assert result == "ws-project"

    def test_workspace_registry_exception(self, mock_config):
        chat_context._chat_state["project"] = "explicit"
        with patch(
            "server.workspace_utils.get_project_sync",
            side_effect=Exception("no registry"),
        ):
            result = chat_context.get_chat_project()
        assert result == "explicit"


class TestSetChatProject:
    def test_sets_valid_project(self, mock_config):
        result = chat_context.set_chat_project("backend")
        assert result is True
        assert chat_context._chat_state["project"] == "backend"
        assert chat_context._chat_state["started_at"] is not None

    def test_rejects_invalid_project(self, mock_config):
        result = chat_context.set_chat_project("nonexistent")
        assert result is False
        assert chat_context._chat_state["project"] is None

    def test_updates_workspace_registry(self, mock_config):
        mock_state = MagicMock()
        with patch("server.workspace_state.WorkspaceRegistry") as mock_registry:
            mock_registry.get_or_create.return_value = mock_state
            chat_context.set_chat_project("backend")
        mock_state.project = "backend"


class TestSetChatIssue:
    def test_sets_issue(self):
        chat_context.set_chat_issue("AAP-123")
        assert chat_context._chat_state["issue_key"] == "AAP-123"

    def test_updates_workspace_registry(self):
        mock_state = MagicMock()
        with patch("server.workspace_state.WorkspaceRegistry") as mock_registry:
            mock_registry.get_or_create.return_value = mock_state
            chat_context.set_chat_issue("AAP-456")
        mock_state.issue_key = "AAP-456"


class TestGetChatIssue:
    def test_from_legacy_state(self):
        chat_context._chat_state["issue_key"] = "AAP-789"
        with patch("server.workspace_state.WorkspaceRegistry") as mock_registry:
            mock_registry.get.return_value = None
            result = chat_context.get_chat_issue()
        assert result == "AAP-789"

    def test_from_workspace_registry(self):
        mock_state = MagicMock()
        mock_state.issue_key = "AAP-100"
        with patch("server.workspace_state.WorkspaceRegistry") as mock_registry:
            mock_registry.get.return_value = mock_state
            result = chat_context.get_chat_issue()
        assert result == "AAP-100"

    def test_returns_none_when_no_issue(self):
        with patch("server.workspace_state.WorkspaceRegistry") as mock_registry:
            mock_registry.get.return_value = None
            result = chat_context.get_chat_issue()
        assert result is None


class TestSetChatBranch:
    def test_sets_branch(self):
        chat_context.set_chat_branch("feature/test")
        assert chat_context._chat_state["branch"] == "feature/test"


class TestGetChatBranch:
    def test_from_legacy_state(self):
        chat_context._chat_state["branch"] = "main"
        with patch("server.workspace_state.WorkspaceRegistry") as mock_registry:
            mock_registry.get.return_value = None
            result = chat_context.get_chat_branch()
        assert result == "main"


class TestGetChatState:
    def test_from_workspace_registry(self, mock_config):
        mock_state = MagicMock()
        mock_state.project = "backend"
        mock_state.issue_key = "AAP-1"
        mock_state.branch = "main"
        mock_state.started_at = datetime(2025, 1, 1)
        mock_state.is_auto_detected = False
        with patch("server.workspace_state.WorkspaceRegistry") as mock_registry:
            mock_registry.get.return_value = mock_state
            result = chat_context.get_chat_state()
        assert result["project"] == "backend"
        assert result["issue_key"] == "AAP-1"

    def test_from_legacy_state(self, mock_config):
        chat_context._chat_state["project"] = "backend"
        with patch("server.workspace_state.WorkspaceRegistry") as mock_registry:
            mock_registry.get.return_value = None
            mock_registry.get_or_create.return_value = MagicMock(
                project="backend",
                issue_key=None,
                branch=None,
                started_at=None,
                is_auto_detected=False,
            )
            result = chat_context.get_chat_state()
        assert result["project"] == "backend"

    def test_auto_detected(self, mock_config):
        with (
            patch(
                "pathlib.Path.cwd",
                return_value=Path("/home/user/src/backend"),
            ),
            patch("server.workspace_state.WorkspaceRegistry") as mock_registry,
        ):
            mock_registry.get.side_effect = Exception
            result = chat_context.get_chat_state()
        assert result["is_auto_detected"] is True
        assert result["is_default"] is False


class TestGetProjectWorkStatePath:
    def test_explicit_project(self):
        with patch(
            "tool_modules.aa_workflow.src.constants.MEMORY_DIR",
            Path("/tmp/memory"),
        ):
            result = chat_context.get_project_work_state_path("myproj")
        assert result == Path("/tmp/memory/state/projects/myproj/current_work.yaml")

    def test_auto_project(self, mock_config):
        chat_context._chat_state["project"] = "backend"
        with (
            patch(
                "tool_modules.aa_workflow.src.constants.MEMORY_DIR",
                Path("/tmp/memory"),
            ),
            patch("server.workspace_state.WorkspaceRegistry") as mock_reg,
        ):
            mock_reg.get.return_value = None
            mock_reg.get_or_create.return_value = MagicMock(project="backend")
            result = chat_context.get_project_work_state_path()
        assert "backend" in str(result)


class TestGetProjectStateDir:
    def test_explicit_project(self):
        with patch(
            "tool_modules.aa_workflow.src.constants.MEMORY_DIR",
            Path("/tmp/memory"),
        ):
            result = chat_context.get_project_state_dir("myproj")
        assert result == Path("/tmp/memory/state/projects/myproj")

    def test_auto_project(self, mock_config):
        chat_context._chat_state["project"] = "backend"
        with (
            patch(
                "tool_modules.aa_workflow.src.constants.MEMORY_DIR",
                Path("/tmp/memory"),
            ),
            patch("server.workspace_state.WorkspaceRegistry") as mock_reg,
        ):
            mock_reg.get.return_value = None
            mock_reg.get_or_create.return_value = MagicMock(project="backend")
            result = chat_context.get_project_state_dir()
        assert "backend" in str(result)


# ---------------------------------------------------------------------------
# _project_context_impl
# ---------------------------------------------------------------------------


class TestProjectContextImpl:
    @pytest.mark.asyncio
    async def test_get_context(self, mock_config):
        ctx = AsyncMock()
        mock_state = MagicMock()
        mock_state.project = "backend"
        mock_state.issue_key = None
        mock_state.branch = None
        mock_state.started_at = None
        mock_state.is_auto_detected = False
        mock_state.workspace_uri = "default"
        mock_state.persona = None

        with patch(
            "server.workspace_utils.get_workspace_from_ctx",
            new_callable=AsyncMock,
            return_value=mock_state,
        ):
            result = await chat_context._project_context_impl(ctx)
        assert len(result) == 1
        assert "backend" in result[0].text

    @pytest.mark.asyncio
    async def test_set_project(self, mock_config):
        ctx = AsyncMock()
        mock_state = MagicMock()
        mock_state.project = "backend"
        mock_state.issue_key = None
        mock_state.branch = None
        mock_state.started_at = None
        mock_state.is_auto_detected = False
        mock_state.workspace_uri = "default"
        mock_state.persona = None

        with (
            patch(
                "server.workspace_utils.set_workspace_project",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "server.workspace_utils.get_workspace_from_ctx",
                new_callable=AsyncMock,
                return_value=mock_state,
            ),
        ):
            result = await chat_context._project_context_impl(ctx, project="backend")
        assert "Project set to" in result[0].text

    @pytest.mark.asyncio
    async def test_invalid_project(self, mock_config):
        ctx = AsyncMock()
        with patch(
            "server.workspace_utils.set_workspace_project",
            new_callable=AsyncMock,
            return_value=False,
        ):
            result = await chat_context._project_context_impl(
                ctx, project="nonexistent"
            )
        assert "Unknown project" in result[0].text

    @pytest.mark.asyncio
    async def test_set_issue_and_branch(self, mock_config):
        ctx = AsyncMock()
        mock_state = MagicMock()
        mock_state.project = "backend"
        mock_state.issue_key = "AAP-1"
        mock_state.branch = "feature/x"
        mock_state.started_at = None
        mock_state.is_auto_detected = False
        mock_state.workspace_uri = "default"
        mock_state.persona = None

        with (
            patch(
                "server.workspace_utils.set_workspace_issue",
                new_callable=AsyncMock,
            ),
            patch(
                "server.workspace_utils.set_workspace_branch",
                new_callable=AsyncMock,
            ),
            patch(
                "server.workspace_utils.get_workspace_from_ctx",
                new_callable=AsyncMock,
                return_value=mock_state,
            ),
        ):
            result = await chat_context._project_context_impl(
                ctx, issue_key="AAP-1", branch="feature/x"
            )
        assert "AAP-1" in result[0].text
        assert "feature/x" in result[0].text
