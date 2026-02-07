"""Tests for server/workspace_tools.py - Decorators and utilities for workspace-aware tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.workspace_tools import (
    MODULE_TO_PERSONA,
    _suggest_persona,
    check_workspace_access,
    get_workspace_context,
    workspace_aware,
    workspace_tool,
)

# The import path for patching.  workspace_tools.py does
#   from .workspace_state import WorkspaceRegistry
# inside function bodies, so the name resolves at call-time.
# We patch the canonical location.
_WR = "server.workspace_state.WorkspaceRegistry"


# ────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────


def _make_workspace_state(
    workspace_uri="file:///test",
    project="my-project",
    persona="developer",
    issue_key=None,
    branch=None,
    active_tools=None,
):
    """Build a mock WorkspaceState."""
    state = MagicMock()
    state.workspace_uri = workspace_uri
    state.project = project
    state.persona = persona
    state.issue_key = issue_key
    state.branch = branch
    state.active_tools = active_tools if active_tools is not None else set()
    return state


def _mock_ctx():
    """Build a minimal mock MCP Context."""
    return MagicMock()


# ────────────────────────────────────────────────────────────────────
# _suggest_persona
# ────────────────────────────────────────────────────────────────────


class TestSuggestPersona:
    def test_known_module(self):
        assert _suggest_persona("k8s") == "devops"
        assert _suggest_persona("prometheus") == "incident"
        assert _suggest_persona("konflux") == "release"
        assert _suggest_persona("git") == "developer"

    def test_known_basic_variant(self):
        assert _suggest_persona("k8s_basic") == "devops"
        assert _suggest_persona("gitlab_basic") == "developer"

    def test_known_extra_variant(self):
        assert _suggest_persona("k8s_extra") == "devops"

    def test_unknown_module(self):
        assert _suggest_persona("unknown_module") == "developer"

    def test_all_mappings_have_value(self):
        """Every mapping in MODULE_TO_PERSONA returns a non-empty string."""
        for _module, persona in MODULE_TO_PERSONA.items():
            assert isinstance(persona, str)
            assert len(persona) > 0


# ────────────────────────────────────────────────────────────────────
# workspace_tool decorator
# ────────────────────────────────────────────────────────────────────


class TestWorkspaceTool:
    @pytest.mark.asyncio
    async def test_no_required_modules(self):
        """Without required_modules the tool executes unconditionally."""

        @workspace_tool(required_modules=None)
        async def my_tool(ctx, x):
            return f"ok:{x}"

        ctx = _mock_ctx()
        state = _make_workspace_state()
        with patch(_WR) as Reg:
            Reg.get_for_ctx = AsyncMock(return_value=state)
            result = await my_tool(ctx, "hello")

        assert result == "ok:hello"

    @pytest.mark.asyncio
    async def test_required_modules_present(self):
        """Tool runs when the required modules are in active_tools."""

        @workspace_tool(required_modules=["k8s"])
        async def my_tool(ctx):
            return "pods"

        ctx = _mock_ctx()
        state = _make_workspace_state(active_tools={"k8s", "git"})
        with patch(_WR) as Reg:
            Reg.get_for_ctx = AsyncMock(return_value=state)
            result = await my_tool(ctx)

        assert result == "pods"

    @pytest.mark.asyncio
    async def test_required_modules_missing(self):
        """Tool returns error message when required modules are not active."""

        @workspace_tool(required_modules=["k8s"])
        async def my_tool(ctx):
            return "should not reach"

        ctx = _mock_ctx()
        state = _make_workspace_state(active_tools={"git"})
        with patch(_WR) as Reg:
            Reg.get_for_ctx = AsyncMock(return_value=state)
            result = await my_tool(ctx)

        assert "not loaded" in result
        assert "k8s" in result
        assert "persona_load" in result

    @pytest.mark.asyncio
    async def test_no_active_tools_allows_all(self):
        """If active_tools is empty, all tools are considered available."""

        @workspace_tool(required_modules=["k8s"])
        async def my_tool(ctx):
            return "ok"

        ctx = _mock_ctx()
        state = _make_workspace_state(active_tools=set())  # empty -> allow all
        with patch(_WR) as Reg:
            Reg.get_for_ctx = AsyncMock(return_value=state)
            result = await my_tool(ctx)

        assert result == "ok"

    @pytest.mark.asyncio
    async def test_workspace_state_error_fallback(self):
        """When workspace state can't be obtained, tool still executes."""

        @workspace_tool(required_modules=["k8s"])
        async def my_tool(ctx):
            return "fallback"

        ctx = _mock_ctx()
        with patch(_WR) as Reg:
            Reg.get_for_ctx = AsyncMock(side_effect=RuntimeError("no state"))
            result = await my_tool(ctx)

        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_preserves_function_name(self):
        """Decorator preserves original function name via functools.wraps."""

        @workspace_tool(required_modules=None)
        async def original_name(ctx):
            return "x"

        assert original_name.__name__ == "original_name"

    @pytest.mark.asyncio
    async def test_multiple_missing_modules(self):
        """Error message lists all missing modules."""

        @workspace_tool(required_modules=["k8s", "bonfire"])
        async def my_tool(ctx):
            return "no"

        ctx = _mock_ctx()
        state = _make_workspace_state(active_tools={"git"})
        with patch(_WR) as Reg:
            Reg.get_for_ctx = AsyncMock(return_value=state)
            result = await my_tool(ctx)

        assert "k8s" in result
        assert "bonfire" in result

    @pytest.mark.asyncio
    async def test_passes_args_and_kwargs(self):
        """Positional and keyword args are forwarded correctly."""

        @workspace_tool(required_modules=None)
        async def my_tool(ctx, a, b, c=10):
            return a + b + c

        ctx = _mock_ctx()
        state = _make_workspace_state()
        with patch(_WR) as Reg:
            Reg.get_for_ctx = AsyncMock(return_value=state)
            result = await my_tool(ctx, 1, 2, c=3)

        assert result == 6


# ────────────────────────────────────────────────────────────────────
# workspace_aware decorator
# ────────────────────────────────────────────────────────────────────


class TestWorkspaceAware:
    @pytest.mark.asyncio
    async def test_passes_through(self):
        """workspace_aware simply wraps without access checks."""

        @workspace_aware
        async def my_tool(ctx, value):
            return f"got:{value}"

        ctx = _mock_ctx()
        result = await my_tool(ctx, "abc")
        assert result == "got:abc"

    @pytest.mark.asyncio
    async def test_preserves_function_name(self):
        @workspace_aware
        async def cool_tool(ctx):
            pass

        assert cool_tool.__name__ == "cool_tool"


# ────────────────────────────────────────────────────────────────────
# check_workspace_access
# ────────────────────────────────────────────────────────────────────


class TestCheckWorkspaceAccess:
    @pytest.mark.asyncio
    async def test_allowed_when_module_active(self):
        ctx = _mock_ctx()
        state = _make_workspace_state(active_tools={"k8s", "git"})
        with patch(_WR) as Reg:
            Reg.get_for_ctx = AsyncMock(return_value=state)
            allowed, error = await check_workspace_access(ctx, ["k8s"])

        assert allowed is True
        assert error is None

    @pytest.mark.asyncio
    async def test_denied_when_module_missing(self):
        ctx = _mock_ctx()
        state = _make_workspace_state(active_tools={"git"})
        with patch(_WR) as Reg:
            Reg.get_for_ctx = AsyncMock(return_value=state)
            allowed, error = await check_workspace_access(ctx, ["k8s"])

        assert allowed is False
        assert "k8s" in error
        assert "persona_load" in error

    @pytest.mark.asyncio
    async def test_allowed_when_no_active_tools(self):
        """Empty active_tools means all modules available."""
        ctx = _mock_ctx()
        state = _make_workspace_state(active_tools=set())
        with patch(_WR) as Reg:
            Reg.get_for_ctx = AsyncMock(return_value=state)
            allowed, error = await check_workspace_access(ctx, ["k8s"])

        assert allowed is True
        assert error is None

    @pytest.mark.asyncio
    async def test_allowed_on_error(self):
        """If we can't get workspace state, allow access."""
        ctx = _mock_ctx()
        with patch(_WR) as Reg:
            Reg.get_for_ctx = AsyncMock(side_effect=RuntimeError("boom"))
            allowed, error = await check_workspace_access(ctx, ["k8s"])

        assert allowed is True
        assert error is None


# ────────────────────────────────────────────────────────────────────
# get_workspace_context
# ────────────────────────────────────────────────────────────────────


class TestGetWorkspaceContext:
    @pytest.mark.asyncio
    async def test_returns_state_dict(self):
        ctx = _mock_ctx()
        state = _make_workspace_state(
            workspace_uri="file:///proj",
            project="backend",
            persona="devops",
            issue_key="AAP-100",
            branch="feature/x",
            active_tools={"git", "k8s"},
        )
        with patch(_WR) as Reg:
            Reg.get_for_ctx = AsyncMock(return_value=state)
            result = await get_workspace_context(ctx)

        assert result["workspace_uri"] == "file:///proj"
        assert result["project"] == "backend"
        assert result["persona"] == "devops"
        assert result["issue_key"] == "AAP-100"
        assert result["branch"] == "feature/x"
        assert set(result["active_tools"]) == {"git", "k8s"}

    @pytest.mark.asyncio
    async def test_returns_defaults_on_error(self):
        ctx = _mock_ctx()
        with patch(_WR) as Reg:
            Reg.get_for_ctx = AsyncMock(side_effect=RuntimeError("boom"))
            result = await get_workspace_context(ctx)

        assert result["workspace_uri"] == "default"
        assert result["project"] is None
        assert result["persona"] == "developer"
        assert result["active_tools"] == []
