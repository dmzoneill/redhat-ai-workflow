"""Tests for tool_modules/aa_workflow/src/meta_tool_handlers.py."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from server.workspace_state import ChatSession, WorkspaceState
from tool_modules.aa_workflow.src import meta_tool_handlers as mth

FILTER_RESULT = {
    "persona": "developer",
    "persona_auto_detected": True,
    "persona_detection_reason": "keyword",
    "tools": ["git_status", "git_log", "jira_view", "k8s_a", "k8s_b", "k8s_c", "k8s_d", "k8s_e", "k8s_f"],
    "reduction_pct": 42.5,
    "latency_ms": 12,
    "context": {
        "skill": {
            "name": "deploy",
            "description": "Deploy things",
            "tools": ["k8s_a"],
            "memory_ops": {"reads": [1], "writes": [1, 2]},
        },
        "memory_state": {"current_repo": "repo", "current_branch": "main", "active_issues": [{"key": "AAP-1"}]},
        "learned_patterns": [{"pattern": "timeout", "fix": "retry"}],
        "semantic_knowledge": [{"file": "a.py", "content": "code"}],
    },
}


def text_of(result):
    """The text of a single-block tool result."""
    assert len(result) == 1
    return result[0].text


@pytest.fixture(name="filter_on")
def fixture_filter_on():
    """Pretend the optional tool filter stack is installed."""
    detect = MagicMock(return_value="deploy")
    run = MagicMock(return_value=FILTER_RESULT)
    with (
        patch.object(mth, "TOOL_FILTER_AVAILABLE", True),
        patch.object(mth, "detect_skill", detect),
        patch.object(mth, "filter_tools_detailed", run),
    ):
        yield detect, run


@pytest.fixture(name="workspace")
def fixture_workspace():
    """A workspace with two sessions, patched in as the registry's current workspace."""
    state = WorkspaceState(workspace_uri="file:///ws")
    now = datetime.now(tz=timezone.utc)
    first = ChatSession(session_id="s1", workspace_uri="file:///ws", name="First", issue_key="AAP-1", branch="b")
    first.last_activity = now - timedelta(hours=2)
    first.last_tool = "git_status"
    first.last_tool_time = now - timedelta(minutes=5)
    second = ChatSession(session_id="s2", workspace_uri="file:///ws")
    second.last_activity = now
    state.sessions = {"s1": first, "s2": second}
    state.active_session_id = "s1"
    registry = MagicMock()
    registry.get_for_ctx = AsyncMock(return_value=state)
    registry.get_all.return_value = {"file:///ws": state}
    with (
        patch("server.workspace_state.WorkspaceRegistry", registry),
        patch.object(mth.workspace_exporter, "export_workspace_state_async", AsyncMock(return_value={})),
    ):
        yield state, registry


class TestTimeHelpers:
    """seconds_since accepts both aware and naive datetimes."""

    def test_aware(self):
        """Aware times are compared directly."""
        elapsed = mth.seconds_since(datetime.now(tz=timezone.utc) - timedelta(minutes=2))
        assert 119 <= elapsed < 130

    def test_naive_is_local(self):
        """Naive times are read as local time."""
        naive_local = (datetime.now(tz=timezone.utc) - timedelta(hours=1)).astimezone().replace(tzinfo=None)
        assert 3599 <= mth.seconds_since(naive_local) < 3610


class TestContextFilter:
    """context_filter_impl."""

    async def test_unavailable(self):
        """Without the filter stack the install hint is returned."""
        with patch.object(mth, "TOOL_FILTER_AVAILABLE", False):
            assert "not available" in text_of(await mth.context_filter_impl("hi"))

    async def test_report(self, filter_on):
        """The report includes every section."""
        _, run = filter_on
        text = text_of(await mth.context_filter_impl("deploy MR", "devops"))
        run.assert_called_once_with(message="deploy MR", persona="devops", detected_skill="deploy")
        for fragment in (
            "auto-detected via keyword",
            "🎯 deploy",
            "Memory writes: 2",
            "Active repo: `repo`",
            "AAP-1",
            "Fix: retry",
            "`a.py`",
            "Recommended Tools (9 tools)",
            "**k8s**: k8s_a, k8s_b, k8s_c, k8s_d, k8s_e +1 more",
        ):
            assert fragment in text

    async def test_no_context(self, filter_on):
        """An empty context reports no skill and no work context."""
        _, run = filter_on
        run.return_value = {"persona": "other", "tools": []}
        text = text_of(await mth.context_filter_impl("x"))
        assert "👤 other" in text
        assert "None (will use general tools)" in text
        assert "No active work context" in text

    async def test_error(self, filter_on):
        """Filter failures are reported, not raised."""
        _, run = filter_on
        run.side_effect = RuntimeError("npu down")
        assert "npu down" in text_of(await mth.context_filter_impl("x"))


def _server(tool_names):
    """A fake FastMCP server exposing ``tool_names``."""
    server = MagicMock()
    server.list_tools = AsyncMock(return_value=[SimpleNamespace(name=n) for n in tool_names])
    return server


def _remove_only(removable):
    """remove_tool side effect that only knows ``removable``."""

    def remove(name):
        if name != removable:
            raise KeyError(name)

    return remove


class TestApplyToolFilter:
    """apply_tool_filter_impl."""

    async def test_unavailable(self):
        """Without the filter stack the install hint is returned."""
        with patch.object(mth, "TOOL_FILTER_AVAILABLE", False):
            assert "not available" in text_of(await mth.apply_tool_filter_impl(MagicMock(), "x"))

    async def test_no_ctx(self, filter_on):
        """A missing context is reported."""
        assert filter_on
        assert "Context not available" in text_of(await mth.apply_tool_filter_impl(None, "x"))

    async def test_server_gone(self, filter_on):
        """A context whose server is gone is reported."""
        assert filter_on
        ctx = MagicMock()
        type(ctx).fastmcp = property(MagicMock(side_effect=RuntimeError("gone")))
        assert "Server not available" in text_of(await mth.apply_tool_filter_impl(ctx, "x"))

    async def test_hides_irrelevant_tools(self, filter_on):
        """Irrelevant tools are removed, core and relevant ones kept, and the client notified."""
        assert filter_on
        server = _server(["git_status", "persona_load", "quay_list", "slack_send"])
        server.remove_tool.side_effect = _remove_only("quay_list")
        ctx = MagicMock(fastmcp=server)
        ctx.session.send_tool_list_changed = AsyncMock()
        text = text_of(await mth.apply_tool_filter_impl(ctx, "deploy " * 20))
        assert "**Tools hidden**: 1" in text
        assert "**Tools available**: 2" in text
        assert "**Skill**: deploy" in text
        assert "..." in text
        ctx.session.send_tool_list_changed.assert_awaited_once()

    @pytest.mark.parametrize("error", [ValueError("test"), RuntimeError("closed")])
    async def test_notify_failures_ignored(self, filter_on, error):
        """Notification failures do not fail the filter."""
        assert filter_on
        ctx = MagicMock(fastmcp=_server(["slack_send"]))
        ctx.session.send_tool_list_changed = AsyncMock(side_effect=error)
        assert "Tool Filter Applied" in text_of(await mth.apply_tool_filter_impl(ctx, "x"))

    async def test_filter_error(self, filter_on):
        """Filter failures are reported."""
        _, run = filter_on
        run.side_effect = KeyError("tools")
        ctx = MagicMock(fastmcp=_server([]))
        assert "Error applying tool filter" in text_of(await mth.apply_tool_filter_impl(ctx, "x"))


class TestWorkspaceStateTools:
    """workspace_state_export_impl and workspace_state_list_impl."""

    @pytest.mark.parametrize(
        ("export", "expected"),
        [
            (AsyncMock(return_value={"success": True, "workspace_count": 2, "file": "/f"}), "Exported 2"),
            (AsyncMock(return_value={"success": False, "error": "nope"}), "Export failed: nope"),
            (AsyncMock(side_effect=OSError("disk")), "Export error: disk"),
        ],
    )
    async def test_outcomes(self, export, expected):
        """Success, failure and errors are reported."""
        with patch.object(mth.workspace_exporter, "export_workspace_state_async", export):
            assert expected in text_of(await mth.workspace_state_export_impl(MagicMock()))

    async def test_lists_sessions(self, workspace):
        """Every session is listed with markers."""
        _, registry = workspace
        loader = MagicMock()
        loader.get_status.return_value = {"tools": ["a", "b", "c"]}
        with patch.object(mth.persona_loader, "get_loader", return_value=loader):
            text = text_of(await mth.workspace_state_list_impl(MagicMock()))
        assert "← *current*" in text
        assert "`s1` ✓ *active* ← *this chat*" in text
        assert "Issue: AAP-1" in text
        assert "Tools: 3 loaded" in text
        assert "1 workspace(s), 2 session(s)" in text
        registry.get_all.assert_called_once()

    async def test_empty(self, workspace):
        """No workspaces is reported."""
        _, registry = workspace
        registry.get_all.return_value = {}
        assert text_of(await mth.workspace_state_list_impl(MagicMock())) == "No active workspaces."

    async def test_export_failure_ignored(self, workspace):
        """A failing auto-export does not fail the listing."""
        assert workspace
        with patch.object(mth.workspace_exporter, "export_workspace_state_async", AsyncMock(side_effect=OSError)):
            assert "Active Workspaces" in text_of(await mth.workspace_state_list_impl(MagicMock()))


class TestSessionInfo:
    """session_info_impl."""

    async def test_active_session(self, workspace):
        """The active session is described."""
        assert workspace
        text = text_of(await mth.session_info_impl(MagicMock()))
        assert "`s1`" in text
        assert "| **Issue** | AAP-1 |" in text
        assert "(5 min ago)" in text

    @pytest.mark.parametrize(
        ("age", "expected"), [(timedelta(seconds=5), "just now"), (timedelta(hours=3), "3 hours ago")]
    )
    async def test_naive_last_tool_time(self, workspace, age, expected):
        """Naive (local) last_tool_time values still work."""
        state, _ = workspace
        state.sessions["s1"].last_tool_time = (datetime.now(tz=timezone.utc) - age).astimezone().replace(tzinfo=None)
        assert expected in text_of(await mth.session_info_impl(MagicMock()))

    async def test_named_session(self, workspace):
        """A named session becomes active."""
        state, _ = workspace
        await mth.session_info_impl(MagicMock(), "s2")
        assert state.active_session_id == "s2"

    async def test_unknown_session(self, workspace):
        """An unknown session lists the available ones."""
        assert workspace
        assert "Available sessions: `s1`, `s2`" in text_of(await mth.session_info_impl(MagicMock(), "zz"))

    async def test_no_session(self, workspace):
        """No active session is reported."""
        state, _ = workspace
        state.sessions = {}
        state.active_session_id = None
        assert "No active session" in text_of(await mth.session_info_impl(MagicMock()))


class TestSessionList:
    """session_list_impl."""

    async def test_mixed_aware_and_naive(self, workspace):
        """Aware and naive activity times sort together, newest first."""
        state, _ = workspace
        older = (datetime.now(tz=timezone.utc) - timedelta(days=3)).astimezone().replace(tzinfo=None)
        state.sessions["s1"].last_activity = older
        text = text_of(await mth.session_list_impl(MagicMock()))
        assert text.index("`s2`") < text.index("`s1`")
        assert "3 days ago" in text
        assert "Active: just now" in text
        assert "Last: `git_status`" in text

    @pytest.mark.parametrize(
        ("age", "expected"),
        [(timedelta(minutes=10), "10 min ago"), (timedelta(hours=5), "5 hours ago")],
    )
    async def test_time_ago(self, workspace, age, expected):
        """Ages are humanised."""
        state, _ = workspace
        state.sessions["s1"].last_activity = datetime.now(tz=timezone.utc) - age
        assert expected in text_of(await mth.session_list_impl(MagicMock()))

    async def test_empty(self, workspace):
        """No sessions is reported."""
        state, _ = workspace
        state.sessions = {}
        assert "No sessions" in text_of(await mth.session_list_impl(MagicMock()))


class TestSessionChanges:
    """session_rename_impl, session_sync_impl and session_switch_impl."""

    async def test_rename(self, workspace):
        """Renaming saves to disk."""
        state, registry = workspace
        text = text_of(await mth.session_rename_impl(MagicMock(), "New"))
        assert "`First` → `New`" in text
        assert state.sessions["s1"].name == "New"
        registry.save_to_disk.assert_called_once()

    async def test_rename_missing(self, workspace):
        """Renaming an unknown session is reported."""
        assert workspace
        assert "not found" in text_of(await mth.session_rename_impl(MagicMock(), "New", "zz"))

    async def test_sync(self, workspace):
        """Sync reports what changed."""
        state, _ = workspace
        with patch.object(state, "sync_with_cursor_db", return_value={"added": 1, "removed": 2, "renamed": 3}):
            text = text_of(await mth.session_sync_impl(MagicMock()))
        assert "Added:** 1" in text
        assert "Removed:** 2" in text
        assert "Renamed:** 3" in text

    async def test_sync_nothing(self, workspace):
        """A no-op sync is reported."""
        state, _ = workspace
        with patch.object(state, "sync_with_cursor_db", return_value={"added": 0, "removed": 0, "renamed": 0}):
            assert "already in sync" in text_of(await mth.session_sync_impl(MagicMock()))

    async def test_switch(self, workspace):
        """Switching activates and describes the session."""
        state, registry = workspace
        text = text_of(await mth.session_switch_impl(MagicMock(), "s1"))
        assert "Switched to session `s1`" in text
        assert "| **Last Tool** | `git_status` |" in text
        assert state.active_session_id == "s1"
        registry.save_to_disk.assert_called_once()

    async def test_switch_missing(self, workspace):
        """Switching to an unknown session lists the available ones."""
        assert workspace
        assert "Available sessions" in text_of(await mth.session_switch_impl(MagicMock(), "zz"))


class TestToolGaps:
    """tool_gaps_list_impl and tool_gap_update_impl."""

    async def test_list(self):
        """Gaps are listed with their details."""
        gap = {
            "suggested_tool_name": "quay_scan",
            "vote_count": 3,
            "requesting_skills": ["deploy"],
            "context": "ctx",
            "workaround_used": "manual",
            "suggested_args": "image",
        }
        with patch.object(mth.tool_gap_detector, "tool_gap") as tool_gap:
            tool_gap.get_gaps.return_value = [gap]
            text = text_of(await mth.tool_gaps_list_impl("open", 5))
        tool_gap.get_gaps.assert_called_once_with(status="open", limit=5)
        for fragment in ("`quay_scan`", "**Votes:** 3", "deploy", "manual", "`image`", "1 gap(s)"):
            assert fragment in text

    async def test_list_empty_and_error(self):
        """No gaps and load errors are reported."""
        with patch.object(mth.tool_gap_detector, "tool_gap") as tool_gap:
            tool_gap.get_gaps.return_value = []
            assert "No tool gaps" in text_of(await mth.tool_gaps_list_impl())
            tool_gap.get_gaps.side_effect = yaml.YAMLError("bad")
            assert "Error loading tool gaps" in text_of(await mth.tool_gaps_list_impl())

    async def test_update(self):
        """Updates validate the status and report the result."""
        with patch.object(mth.tool_gap_detector, "tool_gap") as tool_gap:
            assert "Invalid status" in text_of(await mth.tool_gap_update_impl("g", "bogus"))
            tool_gap.update_status.return_value = True
            assert "Updated gap `g`" in text_of(await mth.tool_gap_update_impl("g", "rejected"))
            tool_gap.update_status.return_value = False
            assert "not found" in text_of(await mth.tool_gap_update_impl("g", "open"))
            tool_gap.update_status.side_effect = OSError("ro")
            assert "Error updating tool gap: ro" in text_of(await mth.tool_gap_update_impl("g", "open"))
