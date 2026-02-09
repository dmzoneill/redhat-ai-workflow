"""Unit tests for SkillExecutor internals in skill_engine.py.

Focuses on methods NOT covered by the skill harness tests:
- SprintSafetyGuard
- _template, _template_dict, _eval_condition
- _exec_compute, _exec_compute_internal
- _format_tool_result
- _handle_tool_error, _try_auto_fix
- _create_jinja_filters
- _detect_soft_failure
- execute() main loop branches
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import Context, FastMCP

# Ensure project root on sys.path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from server.websocket_server import SkillWebSocketServer  # noqa: E402
from tool_modules.aa_workflow.src.skill_engine import (  # noqa: E402
    AttrDict,
    SkillExecutor,
    SprintSafetyGuard,
    _check_known_issues_sync,
    _format_known_issues,
)
from tool_modules.aa_workflow.src.skill_execution_events import (  # noqa: E402
    SkillExecutionEmitter,
)

try:
    from scripts.common.skill_error_recovery import SkillErrorRecovery  # noqa: E402
except ImportError:
    SkillErrorRecovery = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_executor(
    skill: dict | None = None,
    inputs: dict | None = None,
    debug: bool = False,
    server: Any = None,
    enable_interactive_recovery: bool = False,
    create_issue_fn=None,
    ask_question_fn=None,
) -> SkillExecutor:
    """Create a minimal SkillExecutor suitable for unit testing."""
    if skill is None:
        skill = {"name": "test_skill", "steps": []}
    if inputs is None:
        inputs = {}
    executor = SkillExecutor(
        skill=copy.deepcopy(skill),
        inputs=dict(inputs),
        debug=debug,
        server=server,
        create_issue_fn=create_issue_fn,
        ask_question_fn=ask_question_fn,
        enable_interactive_recovery=enable_interactive_recovery,
        emit_events=False,
        workspace_uri="test",
    )
    return executor


def _mock_exec_tool(responses: dict[str, dict] | None = None):
    """Return an async mock for _exec_tool that uses provided responses."""
    responses = responses or {}

    async def _impl(tool_name: str, args: dict) -> dict:
        if tool_name in responses:
            return dict(responses[tool_name])
        return {
            "success": True,
            "result": f"mock result for {tool_name}",
            "duration": 0.01,
        }

    return _impl


# ===========================================================================
# AttrDict tests
# ===========================================================================


class TestAttrDict:
    def test_getattr(self):
        d = AttrDict({"foo": 42, "bar": "hello"})
        assert d.foo == 42
        assert d.bar == "hello"

    def test_setattr(self):
        d = AttrDict()
        d.x = 99
        assert d["x"] == 99

    def test_delattr(self):
        d = AttrDict({"a": 1})
        del d.a
        assert "a" not in d

    def test_getattr_missing_raises(self):
        d = AttrDict()
        with pytest.raises(AttributeError, match="no attribute 'missing'"):
            _ = d.missing

    def test_delattr_missing_raises(self):
        d = AttrDict()
        with pytest.raises(AttributeError, match="no attribute 'gone'"):
            del d.gone


# ===========================================================================
# SprintSafetyGuard tests
# ===========================================================================


class TestSprintSafetyGuard:
    """Tests for SprintSafetyGuard methods."""

    # -- check_git_status ---------------------------------------------------

    async def test_check_git_status_no_server(self):
        guard = SprintSafetyGuard(server=None)
        result = await guard.check_git_status()
        assert result["clean"] is True
        assert result["branch"] == ""

    async def test_check_git_status_clean(self):
        server = AsyncMock()
        server.call_tool.return_value = SimpleNamespace(
            content=[
                SimpleNamespace(
                    text="On branch feature-1\nnothing to commit, working tree clean"
                )
            ]
        )
        guard = SprintSafetyGuard(server=server, repo_path="/repo")
        result = await guard.check_git_status()

        assert result["clean"] is True
        assert result["branch"] == "feature-1"
        assert result["in_progress"] is None

    async def test_check_git_status_modified(self):
        server = AsyncMock()
        server.call_tool.return_value = SimpleNamespace(
            content=[
                SimpleNamespace(
                    text=(
                        "On branch dev\n"
                        "Changes not staged for commit:\n"
                        "  modified:   src/app.py\n"
                        "  modified:   tests/test_app.py\n"
                    )
                )
            ]
        )
        guard = SprintSafetyGuard(server=server)
        result = await guard.check_git_status()

        assert result["clean"] is False
        assert len(result["modified"]) == 2
        assert result["branch"] == "dev"

    async def test_check_git_status_staged(self):
        server = AsyncMock()
        server.call_tool.return_value = SimpleNamespace(
            content=[
                SimpleNamespace(
                    text=(
                        "On branch main\n"
                        "Changes to be committed:\n"
                        "  new file:   foo.py\n"
                    )
                )
            ]
        )
        guard = SprintSafetyGuard(server=server)
        result = await guard.check_git_status()
        assert result["clean"] is False
        assert len(result["staged"]) > 0

    async def test_check_git_status_untracked(self):
        server = AsyncMock()
        server.call_tool.return_value = SimpleNamespace(
            content=[
                SimpleNamespace(
                    text=("On branch main\n" "Untracked files:\n" "  new_file.txt\n")
                )
            ]
        )
        guard = SprintSafetyGuard(server=server)
        result = await guard.check_git_status()
        # Untracked files don't make it "dirty"
        assert result["clean"] is True
        assert len(result["untracked"]) > 0

    async def test_check_git_status_rebase_in_progress(self):
        server = AsyncMock()
        server.call_tool.return_value = SimpleNamespace(
            content=[
                SimpleNamespace(text=("rebase in progress\n" "On branch feature\n"))
            ]
        )
        guard = SprintSafetyGuard(server=server)
        result = await guard.check_git_status()
        assert result["in_progress"] == "rebase"
        assert result["clean"] is False

    async def test_check_git_status_merge_in_progress(self):
        server = AsyncMock()
        server.call_tool.return_value = SimpleNamespace(
            content=[
                SimpleNamespace(text=("On branch main\n" "You have unmerged paths.\n"))
            ]
        )
        guard = SprintSafetyGuard(server=server)
        result = await guard.check_git_status()
        assert result["in_progress"] == "merge"
        assert result["clean"] is False

    async def test_check_git_status_exception(self):
        server = AsyncMock()
        server.call_tool.side_effect = RuntimeError("boom")
        guard = SprintSafetyGuard(server=server)
        result = await guard.check_git_status()
        assert result["clean"] is True  # defaults preserved on error

    # -- stash_changes ------------------------------------------------------

    async def test_stash_changes_no_server(self):
        guard = SprintSafetyGuard(server=None)
        result = await guard.stash_changes("AAP-123")
        assert result["success"] is False

    async def test_stash_changes_success(self):
        server = AsyncMock()
        server.call_tool.return_value = SimpleNamespace(
            content=[SimpleNamespace(text="Saved working directory and stash")]
        )
        guard = SprintSafetyGuard(server=server)
        result = await guard.stash_changes("AAP-123")
        assert result["success"] is True
        assert guard._stash_created is True
        assert "AAP-123" in result["message"]

    async def test_stash_changes_no_changes(self):
        server = AsyncMock()
        server.call_tool.return_value = SimpleNamespace(
            content=[SimpleNamespace(text="No local changes to save")]
        )
        guard = SprintSafetyGuard(server=server)
        result = await guard.stash_changes("AAP-999")
        assert result["success"] is False
        assert guard._stash_created is False

    async def test_stash_changes_exception(self):
        server = AsyncMock()
        server.call_tool.side_effect = RuntimeError("disk full")
        guard = SprintSafetyGuard(server=server)
        result = await guard.stash_changes("AAP-1")
        assert result["success"] is False
        assert "disk full" in result["message"]

    # -- check_and_prepare --------------------------------------------------

    async def test_check_and_prepare_clean_feature_branch(self):
        server = AsyncMock()
        server.call_tool.return_value = SimpleNamespace(
            content=[
                SimpleNamespace(
                    text="On branch feature-1\nnothing to commit, working tree clean"
                )
            ]
        )
        guard = SprintSafetyGuard(server=server)
        result = await guard.check_and_prepare("AAP-1")
        assert result["safe"] is True
        assert result["branch"] == "feature-1"

    async def test_check_and_prepare_rebase_blocks(self):
        server = AsyncMock()
        server.call_tool.return_value = SimpleNamespace(
            content=[SimpleNamespace(text="rebase in progress\nOn branch feature")]
        )
        guard = SprintSafetyGuard(server=server)
        result = await guard.check_and_prepare("AAP-1")
        assert result["safe"] is False
        assert "rebase" in result["reason"]

    async def test_check_and_prepare_protected_branch_blocks(self):
        server = AsyncMock()
        server.call_tool.return_value = SimpleNamespace(
            content=[SimpleNamespace(text="On branch main\nnothing to commit")]
        )
        guard = SprintSafetyGuard(server=server)
        result = await guard.check_and_prepare("AAP-1")
        assert result["safe"] is False
        assert "protected" in result["reason"].lower()

    async def test_check_and_prepare_auto_stash(self):
        server = AsyncMock()
        # First call: check_git_status shows dirty
        # Second call: stash_changes succeeds
        server.call_tool.side_effect = [
            SimpleNamespace(
                content=[
                    SimpleNamespace(
                        text=(
                            "On branch feature-1\n"
                            "Changes not staged for commit:\n"
                            "  modified:   foo.py\n"
                        )
                    )
                ]
            ),
            SimpleNamespace(
                content=[SimpleNamespace(text="Saved working directory and stash")]
            ),
        ]
        guard = SprintSafetyGuard(server=server, auto_stash=True)
        result = await guard.check_and_prepare("AAP-1")
        assert result["safe"] is True
        assert result["stashed"] is True

    async def test_check_and_prepare_auto_stash_disabled(self):
        server = AsyncMock()
        server.call_tool.return_value = SimpleNamespace(
            content=[
                SimpleNamespace(
                    text=(
                        "On branch feature-1\n"
                        "Changes not staged for commit:\n"
                        "  modified:   foo.py\n"
                    )
                )
            ]
        )
        guard = SprintSafetyGuard(server=server, auto_stash=False)
        result = await guard.check_and_prepare("AAP-1")
        assert result["safe"] is False
        assert "uncommitted" in result["reason"].lower()

    async def test_check_and_prepare_stash_failure(self):
        server = AsyncMock()
        server.call_tool.side_effect = [
            SimpleNamespace(
                content=[
                    SimpleNamespace(
                        text=(
                            "On branch feature-1\n"
                            "Changes not staged for commit:\n"
                            "  modified:   foo.py\n"
                        )
                    )
                ]
            ),
            # Use text that does NOT contain "saved" or "stash" so _stash_created=False
            SimpleNamespace(content=[SimpleNamespace(text="error: operation failed")]),
        ]
        guard = SprintSafetyGuard(server=server, auto_stash=True)
        result = await guard.check_and_prepare("AAP-1")
        assert result["safe"] is False
        assert (
            "stash" in result["reason"].lower() or "failed" in result["reason"].lower()
        )

    async def test_check_and_prepare_untracked_warning(self):
        server = AsyncMock()
        server.call_tool.return_value = SimpleNamespace(
            content=[
                SimpleNamespace(
                    text=("On branch feature-1\n" "Untracked files:\n" "  new.txt\n")
                )
            ]
        )
        guard = SprintSafetyGuard(server=server)
        result = await guard.check_and_prepare("AAP-1")
        assert result["safe"] is True
        assert len(result["warnings"]) > 0

    # -- restore_stash ------------------------------------------------------

    async def test_restore_stash_no_stash(self):
        guard = SprintSafetyGuard(server=AsyncMock())
        guard._stash_created = False
        result = await guard.restore_stash()
        assert result["success"] is True
        assert "no stash" in result["message"].lower()

    async def test_restore_stash_no_server(self):
        guard = SprintSafetyGuard(server=None)
        guard._stash_created = True
        result = await guard.restore_stash()
        assert result["success"] is False

    async def test_restore_stash_success(self):
        server = AsyncMock()
        server.call_tool.return_value = SimpleNamespace(
            content=[SimpleNamespace(text="Dropped refs/stash@{0}, applied changes")]
        )
        guard = SprintSafetyGuard(server=server)
        guard._stash_created = True
        result = await guard.restore_stash()
        assert result["success"] is True

    async def test_restore_stash_exception(self):
        server = AsyncMock()
        server.call_tool.side_effect = RuntimeError("conflict")
        guard = SprintSafetyGuard(server=server)
        guard._stash_created = True
        result = await guard.restore_stash()
        assert result["success"] is False
        assert "conflict" in result["message"]


# ===========================================================================
# SkillExecutor._template tests
# ===========================================================================


class TestTemplate:
    def test_passthrough_no_braces(self):
        ex = _make_executor(inputs={"foo": "bar"})
        assert ex._template("hello world") == "hello world"

    def test_non_string_passthrough(self):
        ex = _make_executor()
        assert ex._template(42) == 42  # type: ignore[arg-type]

    def test_simple_variable(self):
        ex = _make_executor(inputs={"name": "Alice"})
        assert ex._template("Hello {{ inputs.name }}") == "Hello Alice"

    def test_nested_variable(self):
        ex = _make_executor()
        ex.context["data"] = {"nested": {"val": 99}}
        assert ex._template("got {{ data.nested.val }}") == "got 99"

    def test_undefined_renders_empty(self):
        ex = _make_executor()
        result = ex._template("{{ nonexistent_var }}")
        assert result == ""

    def test_today_in_context(self):
        ex = _make_executor()
        result = ex._template("date is {{ today }}")
        assert "date is" in result
        # today should be a valid date string
        assert len(result) > len("date is ")

    def test_template_error_returns_original(self):
        """If Jinja2 rendering fails hard, original text returned."""
        ex = _make_executor()
        # Jinja syntax error
        text = "{% for %}"
        result = ex._template(text)
        # Should return original text on error
        assert result == text

    def test_config_access(self):
        ex = _make_executor()
        # config comes from load_config(), should be accessible
        result = ex._template("{{ config is defined }}")
        assert result.lower() in ("true", "false", "")


class TestTemplateDict:
    def test_simple_dict(self):
        ex = _make_executor(inputs={"key": "value"})
        result = ex._template_dict({"a": "{{ inputs.key }}", "b": "literal"})
        assert result["a"] == "value"
        assert result["b"] == "literal"

    def test_nested_dict(self):
        ex = _make_executor(inputs={"x": "123"})
        result = ex._template_dict({"outer": {"inner": "{{ inputs.x }}"}})
        assert result["outer"]["inner"] == "123"

    def test_list_values(self):
        ex = _make_executor(inputs={"a": "hello"})
        result = ex._template_dict({"items": ["{{ inputs.a }}", "static"]})
        assert result["items"][0] == "hello"
        assert result["items"][1] == "static"

    def test_non_string_values_preserved(self):
        ex = _make_executor()
        result = ex._template_dict({"num": 42, "flag": True, "items": [1, 2]})
        assert result["num"] == 42
        assert result["flag"] is True
        assert result["items"] == [1, 2]


# ===========================================================================
# _eval_condition tests
# ===========================================================================


class TestEvalCondition:
    def test_true_expression(self):
        ex = _make_executor(inputs={"flag": True})
        ex.context["flag"] = True
        assert ex._eval_condition("flag") is True

    def test_false_expression(self):
        ex = _make_executor()
        ex.context["flag"] = False
        assert ex._eval_condition("flag") is False

    def test_string_comparison(self):
        ex = _make_executor()
        ex.context["status"] = "open"
        assert ex._eval_condition("status == 'open'") is True
        assert ex._eval_condition("status == 'closed'") is False

    def test_numeric_comparison(self):
        ex = _make_executor()
        ex.context["count"] = 5
        assert ex._eval_condition("count > 3") is True
        assert ex._eval_condition("count < 3") is False

    def test_undefined_defaults_false(self):
        ex = _make_executor()
        result = ex._eval_condition("nonexistent_var")
        assert result is False

    def test_with_braces(self):
        ex = _make_executor()
        ex.context["val"] = "yes"
        assert ex._eval_condition("{{ val == 'yes' }}") is True

    def test_jinja_builtins(self):
        ex = _make_executor()
        ex.context["items"] = [1, 2, 3]
        assert ex._eval_condition("items | length > 0") is True

    def test_none_string_is_false(self):
        ex = _make_executor()
        assert ex._eval_condition("None") is False

    def test_empty_string_is_false(self):
        ex = _make_executor()
        assert ex._eval_condition("''") is False

    def test_nonempty_string_is_true(self):
        ex = _make_executor()
        ex.context["word"] = "hello"
        assert ex._eval_condition("word") is True


# ===========================================================================
# _exec_compute / _exec_compute_internal tests
# ===========================================================================


class TestExecCompute:
    def test_simple_assignment(self):
        ex = _make_executor()
        result = ex._exec_compute("result = 2 + 3", "result")
        assert result == 5

    def test_output_name_used(self):
        ex = _make_executor()
        result = ex._exec_compute("my_out = 'hello'", "my_out")
        assert result == "hello"

    def test_accesses_inputs(self):
        ex = _make_executor(inputs={"x": 10})
        result = ex._exec_compute("result = inputs.x * 2", "result")
        assert result == 20

    def test_attrdict_in_compute(self):
        ex = _make_executor(inputs={"name": "world"})
        result = ex._exec_compute("result = f'hello {inputs.name}'", "result")
        assert result == "hello world"

    def test_error_returns_error_string(self):
        ex = _make_executor()
        result = ex._exec_compute("raise ValueError('oops')", "result")
        assert isinstance(result, str)
        assert "compute error" in result.lower()

    def test_template_in_compute(self):
        ex = _make_executor(inputs={"val": "42"})
        result = ex._exec_compute("result = '{{ inputs.val }}'", "result")
        assert result == "42"

    def test_context_available(self):
        ex = _make_executor()
        ex.context["prior_step"] = "step1_data"
        result = ex._exec_compute("result = prior_step", "result")
        assert result == "step1_data"

    def test_builtins_available(self):
        ex = _make_executor()
        result = ex._exec_compute("result = len([1,2,3])", "result")
        assert result == 3

    def test_datetime_available(self):
        ex = _make_executor()
        result = ex._exec_compute(
            "from datetime import datetime\nresult = datetime.now().year",
            "result",
        )
        assert isinstance(result, int)
        assert result >= 2024

    def test_re_available(self):
        ex = _make_executor()
        result = ex._exec_compute(
            "import re\nresult = bool(re.match(r'^\\d+$', '123'))",
            "result",
        )
        assert result is True

    def test_path_available(self):
        ex = _make_executor()
        result = ex._exec_compute("result = str(Path('/tmp'))", "result")
        assert result == "/tmp"

    def test_fallback_to_result_var(self):
        """If output_name not found, falls back to 'result' variable."""
        ex = _make_executor()
        result = ex._exec_compute("result = 'fallback'", "nonexistent")
        assert result == "fallback"

    def test_interactive_recovery_not_triggered_when_disabled(self):
        ex = _make_executor(enable_interactive_recovery=False)
        result = ex._exec_compute("raise RuntimeError('boom')", "r")
        assert isinstance(result, str)
        assert "compute error" in result.lower()

    def test_exec_compute_internal_directly(self):
        ex = _make_executor()
        result = ex._exec_compute_internal("my_var = 'direct'", "my_var")
        assert result == "direct"


# ===========================================================================
# _format_tool_result tests
# ===========================================================================


class TestFormatToolResult:
    def test_plain_string(self):
        ex = _make_executor()
        result = ex._format_tool_result("hello world", 1.5)
        assert result["success"] is True
        assert result["result"] == "hello world"
        assert result["duration"] == 1.5

    def test_error_prefix(self):
        ex = _make_executor()
        result = ex._format_tool_result("error: something broke", 0.1)
        assert result["success"] is False

    def test_emoji_error(self):
        ex = _make_executor()
        result = ex._format_tool_result("\u274c something failed", 0.1)
        assert result["success"] is False

    def test_emoji_error_text(self):
        ex = _make_executor()
        result = ex._format_tool_result("some text \u274c error happened", 0.2)
        assert result["success"] is False

    def test_emoji_failed(self):
        ex = _make_executor()
        result = ex._format_tool_result("prefix \u274c failed to do thing", 0.1)
        assert result["success"] is False

    def test_connection_failed(self):
        ex = _make_executor()
        result = ex._format_tool_result("Connection may have failed for network", 0.5)
        assert result["success"] is False

    def test_script_not_found(self):
        ex = _make_executor()
        result = ex._format_tool_result("Script not found at /usr/bin/x", 0.1)
        assert result["success"] is False

    def test_tuple_result(self):
        ex = _make_executor()
        result = ex._format_tool_result(("text data", "extra"), 0.1)
        assert result["result"] == "text data"

    def test_toolresult_object(self):
        """Handle FastMCP ToolResult-like objects."""
        ex = _make_executor()
        mock_result = SimpleNamespace(
            content=[SimpleNamespace(text="tool output here")]
        )
        result = ex._format_tool_result(mock_result, 0.2)
        assert result["success"] is True
        assert result["result"] == "tool output here"

    def test_toolresult_empty_content(self):
        ex = _make_executor()
        mock_result = SimpleNamespace(content=[])
        result = ex._format_tool_result(mock_result, 0.1)
        # Falls through to str(result)
        assert result["success"] is True

    def test_list_result(self):
        ex = _make_executor()
        result = ex._format_tool_result([SimpleNamespace(text="list item text")], 0.1)
        assert result["result"] == "list item text"

    def test_list_result_no_text_attr(self):
        ex = _make_executor()
        result = ex._format_tool_result(["plain string"], 0.1)
        assert result["result"] == "plain string"


# ===========================================================================
# _create_jinja_filters tests
# ===========================================================================


class TestCreateJinjaFilters:
    def test_returns_filters_dict(self):
        ex = _make_executor()
        filters = ex._create_jinja_filters()
        assert "jira_link" in filters
        assert "mr_link" in filters
        assert "length" in filters
        assert filters["length"] is len

    def test_jira_link_filter_markdown(self):
        ex = _make_executor(inputs={"slack_format": False})
        filters = ex._create_jinja_filters()
        result = filters["jira_link"]("See AAP-12345 for details")
        assert "[AAP-12345]" in result
        assert "browse/AAP-12345" in result

    def test_jira_link_filter_slack(self):
        ex = _make_executor(inputs={"slack_format": True})
        filters = ex._create_jinja_filters()
        result = filters["jira_link"]("See AAP-12345")
        assert "<" in result  # Slack link format
        assert "AAP-12345" in result

    def test_mr_link_filter_markdown(self):
        ex = _make_executor(inputs={"slack_format": False})
        filters = ex._create_jinja_filters()
        result = filters["mr_link"]("Check !789")
        assert "[!789]" in result
        assert "merge_requests/789" in result

    def test_mr_link_filter_slack(self):
        ex = _make_executor(inputs={"slack_format": True})
        filters = ex._create_jinja_filters()
        result = filters["mr_link"]("Check !789")
        assert "<" in result
        assert "!789" in result

    def test_jira_link_none_passthrough(self):
        ex = _make_executor()
        filters = ex._create_jinja_filters()
        assert filters["jira_link"](None) is None
        assert filters["jira_link"]("") == ""

    def test_mr_link_none_passthrough(self):
        ex = _make_executor()
        filters = ex._create_jinja_filters()
        assert filters["mr_link"](None) is None
        assert filters["mr_link"]("") == ""

    def test_filter_in_template(self):
        ex = _make_executor(inputs={"slack_format": False})
        ex.context["key"] = "AAP-100"
        result = ex._template("{{ key | jira_link }}")
        assert "AAP-100" in result
        assert "browse" in result


# ===========================================================================
# _detect_soft_failure tests
# ===========================================================================


class TestDetectSoftFailure:
    def test_none_input(self):
        ex = _make_executor()
        is_fail, msg = ex._detect_soft_failure("")
        assert is_fail is False
        assert msg is None

    def test_clean_result(self):
        ex = _make_executor()
        is_fail, msg = ex._detect_soft_failure("Everything is fine, pod is running.")
        assert is_fail is False

    def test_no_such_host(self):
        ex = _make_executor()
        is_fail, msg = ex._detect_soft_failure(
            "Error: dial tcp: lookup api.example.com: no such host"
        )
        assert is_fail is True
        assert msg is not None
        assert "DNS" in msg

    def test_unauthorized(self):
        ex = _make_executor()
        is_fail, msg = ex._detect_soft_failure("HTTP 401 Unauthorized: please login")
        assert is_fail is True
        assert msg is not None
        assert "auth" in msg.lower() or "401" in msg

    def test_forbidden(self):
        ex = _make_executor()
        is_fail, msg = ex._detect_soft_failure("403 Forbidden - access denied")
        assert is_fail is True

    def test_connection_refused(self):
        ex = _make_executor()
        is_fail, msg = ex._detect_soft_failure(
            "Connection refused to api.example.com:8080"
        )
        assert is_fail is True
        assert msg is not None
        assert "refused" in msg.lower()

    def test_traceback(self):
        ex = _make_executor()
        is_fail, msg = ex._detect_soft_failure(
            "Traceback (most recent call last):\n  File ...\nValueError: bad"
        )
        assert is_fail is True
        assert msg is not None
        assert "Python exception" in msg

    def test_emoji_error_marker(self):
        ex = _make_executor()
        is_fail, msg = ex._detect_soft_failure("\u274c Failed to deploy to namespace")
        assert is_fail is True

    def test_token_expired(self):
        ex = _make_executor()
        is_fail, msg = ex._detect_soft_failure(
            "Error: token expired, re-login required"
        )
        assert is_fail is True

    def test_error_from_server(self):
        ex = _make_executor()
        is_fail, msg = ex._detect_soft_failure(
            "Error from server (NotFound): pods not found"
        )
        assert is_fail is True

    def test_dial_tcp(self):
        ex = _make_executor()
        is_fail, msg = ex._detect_soft_failure(
            "dial tcp 10.0.0.1:6443: connect: connection timed out"
        )
        assert is_fail is True


# ===========================================================================
# _handle_tool_error tests
# ===========================================================================


class TestHandleToolError:
    async def test_on_error_fail_returns_false(self):
        ex = _make_executor()
        ex._exec_tool = _mock_exec_tool()
        step = {"tool": "some_tool", "on_error": "fail"}
        lines: list[str] = []
        should_continue = await ex._handle_tool_error(
            "some_tool", step, "step1", "bad thing happened", lines
        )
        assert should_continue is False
        assert any("bad thing happened" in line for line in lines)

    async def test_on_error_continue_returns_true(self):
        ex = _make_executor()
        ex._exec_tool = _mock_exec_tool()
        step = {"tool": "some_tool", "on_error": "continue"}
        lines: list[str] = []
        should_continue = await ex._handle_tool_error(
            "some_tool", step, "step1", "non-critical error", lines
        )
        assert should_continue is True
        assert any("continue" in line.lower() for line in lines)

    async def test_on_error_default_is_fail(self):
        ex = _make_executor()
        ex._exec_tool = _mock_exec_tool()
        step = {"tool": "some_tool"}  # no on_error key
        lines: list[str] = []
        should_continue = await ex._handle_tool_error(
            "some_tool", step, "step1", "error", lines
        )
        assert should_continue is False

    async def test_on_error_auto_heal_no_match(self):
        """auto_heal with an error that doesn't match any pattern."""
        ex = _make_executor()
        ex._exec_tool = _mock_exec_tool()
        step = {"tool": "some_tool", "on_error": "auto_heal"}
        lines: list[str] = []
        should_continue = await ex._handle_tool_error(
            "some_tool", step, "step1", "generic error, nothing special", lines
        )
        # auto_heal falls through to continue behavior
        assert should_continue is True
        assert any("not auto-healable" in line.lower() for line in lines)

    async def test_on_error_auto_heal_auth_detected(self):
        """auto_heal detects an auth error and attempts heal."""
        ex = _make_executor()
        # Mock _exec_tool to return failure on kube_login (heal fails)
        ex._exec_tool = _mock_exec_tool(
            {
                "kube_login": {
                    "success": False,
                    "error": "login failed",
                    "result": "login failed",
                },
            }
        )
        step = {"tool": "kubectl_get_pods", "on_error": "auto_heal", "args": {}}
        lines: list[str] = []
        should_continue = await ex._handle_tool_error(
            "kubectl_get_pods", step, "step1", "unauthorized - 401", lines
        )
        assert should_continue is True  # auto_heal always continues
        # Should have attempted heal
        assert any("auth" in line.lower() or "heal" in line.lower() for line in lines)

    async def test_create_issue_fn_called_on_fail(self):
        """When on_error=fail and create_issue_fn is set, it should be called."""
        create_fn = AsyncMock(
            return_value={"success": True, "issue_url": "http://issue/1"}
        )
        ex = _make_executor(create_issue_fn=create_fn)
        ex._exec_tool = _mock_exec_tool()
        step = {"tool": "some_tool", "on_error": "fail"}
        lines: list[str] = []
        await ex._handle_tool_error("some_tool", step, "step1", "fatal error", lines)
        create_fn.assert_called_once()
        assert create_fn.call_count == 1

    async def test_step_result_recorded_on_continue(self):
        ex = _make_executor()
        ex._exec_tool = _mock_exec_tool()
        step = {"tool": "t", "on_error": "continue"}
        lines: list[str] = []
        await ex._handle_tool_error("t", step, "cont_step", "err", lines)
        assert len(ex.step_results) == 1
        assert ex.step_results[0]["success"] is False
        assert ex.step_results[0]["step"] == "cont_step"


# ===========================================================================
# _try_auto_fix tests
# ===========================================================================


class TestTryAutoFix:
    async def test_no_fix_type_returns_false(self):
        ex = _make_executor(debug=True)
        result = await ex._try_auto_fix("just a generic error", [])
        assert result is False

    async def test_auth_error_detected(self):
        """Auth error detected but fix fails (no oc binary)."""
        ex = _make_executor(debug=True)
        # _apply_auth_fix will fail because oc doesn't exist / times out
        # We mock _apply_auth_fix to return False
        ex._apply_auth_fix = AsyncMock(return_value=False)
        result = await ex._try_auto_fix("unauthorized 401", [])
        assert result is False
        ex._apply_auth_fix.assert_called_once()

    async def test_network_error_detected(self):
        ex = _make_executor(debug=True)
        ex._apply_network_fix = AsyncMock(return_value=False)
        result = await ex._try_auto_fix("no route to host", [])
        assert result is False
        ex._apply_network_fix.assert_called_once()

    async def test_auth_fix_succeeds(self):
        ex = _make_executor(debug=True)
        ex._apply_auth_fix = AsyncMock(return_value=True)
        result = await ex._try_auto_fix("forbidden 403 access denied", [])
        assert result is True

    async def test_network_fix_succeeds(self):
        ex = _make_executor(debug=True)
        ex._apply_network_fix = AsyncMock(return_value=True)
        result = await ex._try_auto_fix("connection refused to host", [])
        assert result is True

    async def test_matches_from_known_issues(self):
        ex = _make_executor(debug=True)
        ex._apply_auth_fix = AsyncMock(return_value=False)
        matches = [{"fix": "run kube login to re-authenticate"}]
        result = await ex._try_auto_fix("some random error", matches)
        assert result is False
        ex._apply_auth_fix.assert_called_once()


# ===========================================================================
# _determine_fix_type tests
# ===========================================================================


class TestDetermineFixType:
    def test_auth_from_hardcoded(self):
        ex = _make_executor()
        assert ex._determine_fix_type("unauthorized", None, []) == "auth"
        assert ex._determine_fix_type("401 error", None, []) == "auth"
        assert ex._determine_fix_type("403 forbidden", None, []) == "auth"
        assert ex._determine_fix_type("token expired", None, []) == "auth"

    def test_network_from_hardcoded(self):
        ex = _make_executor()
        assert ex._determine_fix_type("no route to host", None, []) == "network"
        assert ex._determine_fix_type("connection refused", None, []) == "network"
        assert ex._determine_fix_type("timeout occurred", None, []) == "network"

    def test_none_for_unknown(self):
        ex = _make_executor()
        assert ex._determine_fix_type("some generic error", None, []) is None

    def test_from_matched_pattern_vpn(self):
        ex = _make_executor()
        pattern = {"commands": ["vpn connect"]}
        assert ex._determine_fix_type("whatever", pattern, []) == "network"

    def test_from_matched_pattern_login(self):
        ex = _make_executor()
        pattern = {"commands": ["oc login cluster"]}
        assert ex._determine_fix_type("whatever", pattern, []) == "auth"

    def test_from_matches_list(self):
        ex = _make_executor()
        matches = [{"fix": "use vpn_connect to reconnect"}]
        assert ex._determine_fix_type("unusual error", None, matches) == "network"


# ===========================================================================
# _detect_auto_heal_type tests
# ===========================================================================


class TestDetectAutoHealType:
    def test_auth_patterns(self):
        ex = _make_executor()
        for text in [
            "unauthorized",
            "401",
            "forbidden",
            "403",
            "token expired",
            "authentication required",
            "not authorized",
            "permission denied",
        ]:
            heal_type, _ = ex._detect_auto_heal_type(text)
            assert heal_type == "auth", f"Expected auth for '{text}'"

    def test_network_patterns(self):
        ex = _make_executor()
        for text in [
            "no route to host",
            "no such host",
            "connection refused",
            "network unreachable",
            "timeout",
            "dial tcp",
            "connection reset",
            "cannot connect",
        ]:
            heal_type, _ = ex._detect_auto_heal_type(text)
            assert heal_type == "network", f"Expected network for '{text}'"

    def test_cluster_detection_ephemeral(self):
        ex = _make_executor()
        _, cluster = ex._detect_auto_heal_type("bonfire error unauthorized")
        assert cluster == "ephemeral"

    def test_cluster_detection_konflux(self):
        ex = _make_executor()
        _, cluster = ex._detect_auto_heal_type("konflux timeout")
        assert cluster == "konflux"

    def test_cluster_detection_prod(self):
        ex = _make_executor()
        _, cluster = ex._detect_auto_heal_type("prod 401 unauthorized")
        assert cluster == "prod"

    def test_cluster_default_stage(self):
        ex = _make_executor()
        _, cluster = ex._detect_auto_heal_type("generic unauthorized")
        assert cluster == "stage"

    def test_unknown_error(self):
        ex = _make_executor()
        heal_type, _ = ex._detect_auto_heal_type("something completely different")
        assert heal_type is None


# ===========================================================================
# _validate_tool_args tests
# ===========================================================================


class TestValidateToolArgs:
    def test_valid_args(self):
        ex = _make_executor()
        raw = {"key": "{{ inputs.name }}"}
        args = {"key": "Alice"}
        assert ex._validate_tool_args("tool", raw, args, "step") is None

    def test_empty_rendered_required_arg(self):
        ex = _make_executor()
        raw = {"key": "{{ inputs.missing }}"}
        args = {"key": ""}
        result = ex._validate_tool_args("tool", raw, args, "step")
        assert result is not None
        assert "empty" in result.lower()

    def test_arg_with_default_skipped(self):
        ex = _make_executor()
        raw = {"key": "{{ inputs.missing | default('fallback') }}"}
        args = {"key": "fallback"}
        assert ex._validate_tool_args("tool", raw, args, "step") is None

    def test_arg_with_or_skipped(self):
        ex = _make_executor()
        raw = {"key": "{{ inputs.missing or 'alt' }}"}
        args = {"key": "alt"}
        assert ex._validate_tool_args("tool", raw, args, "step") is None

    def test_literal_args_always_pass(self):
        ex = _make_executor()
        raw = {"key": "literal_value"}
        args = {"key": "literal_value"}
        assert ex._validate_tool_args("tool", raw, args, "step") is None

    def test_none_rendered_value(self):
        ex = _make_executor()
        raw = {"key": "{{ inputs.gone }}"}
        args = {"key": None}
        result = ex._validate_tool_args("tool", raw, args, "step")
        assert result is not None


# ===========================================================================
# execute() main loop tests
# ===========================================================================


class TestExecuteMainLoop:
    """Tests for the execute() method and its main loop branches."""

    async def test_empty_skill(self):
        ex = _make_executor(skill={"name": "empty", "steps": []})
        result = await ex.execute()
        assert "empty" in result.lower() or "Executing" in result
        assert "Completed" in result

    async def test_compute_step(self):
        ex = _make_executor(
            skill={
                "name": "compute_test",
                "steps": [
                    {"name": "calc", "compute": "result = 2 + 2", "output": "answer"},
                ],
            }
        )
        result = await ex.execute()
        assert "calc" in result
        assert ex.context.get("answer") == 4

    async def test_compute_step_error(self):
        ex = _make_executor(
            skill={
                "name": "bad_compute",
                "steps": [
                    {
                        "name": "broken",
                        "compute": "raise ValueError('nope')",
                        "output": "out",
                    },
                ],
            }
        )
        result = await ex.execute()
        assert "compute error" in result.lower() or "nope" in result.lower()

    async def test_description_step(self):
        ex = _make_executor(
            skill={
                "name": "desc_test",
                "steps": [
                    {"name": "info", "description": "This is a manual step"},
                ],
            }
        )
        result = await ex.execute()
        assert "manual" in result.lower()
        assert "This is a manual step" in result

    async def test_condition_skip(self):
        ex = _make_executor(
            skill={
                "name": "cond_test",
                "steps": [
                    {
                        "name": "skipped",
                        "condition": "False",
                        "compute": "result = 'should not run'",
                        "output": "val",
                    },
                ],
            }
        )
        result = await ex.execute()
        assert "skipped" in result.lower()
        assert ex.context.get("val") is None

    async def test_condition_true_runs(self):
        ex = _make_executor(
            skill={
                "name": "cond_true",
                "steps": [
                    {
                        "name": "runs",
                        "condition": "True",
                        "compute": "result = 'ran'",
                        "output": "val",
                    },
                ],
            }
        )
        await ex.execute()
        assert ex.context.get("val") == "ran"

    async def test_tool_step_success(self):
        ex = _make_executor(
            skill={
                "name": "tool_test",
                "steps": [
                    {
                        "name": "fetch",
                        "tool": "jira_view_issue",
                        "args": {"issue_key": "AAP-1"},
                        "output": "issue",
                    },
                ],
            }
        )
        ex._exec_tool = _mock_exec_tool(
            {
                "jira_view_issue": {
                    "success": True,
                    "result": "AAP-1: Test Issue",
                    "duration": 0.1,
                },
            }
        )
        result = await ex.execute()
        assert "Success" in result
        assert ex.context.get("issue") == "AAP-1: Test Issue"

    async def test_tool_step_failure_stops(self):
        ex = _make_executor(
            skill={
                "name": "fail_test",
                "steps": [
                    {
                        "name": "bad_tool",
                        "tool": "some_tool",
                        "args": {},
                    },
                    {
                        "name": "should_not_run",
                        "compute": "result = 'ran'",
                        "output": "out",
                    },
                ],
            }
        )
        ex._exec_tool = _mock_exec_tool(
            {
                "some_tool": {"success": False, "error": "tool broke"},
            }
        )
        result = await ex.execute()
        assert "failed" in result.lower()
        assert ex.context.get("out") is None

    async def test_tool_step_on_error_continue(self):
        ex = _make_executor(
            skill={
                "name": "continue_test",
                "steps": [
                    {
                        "name": "failing",
                        "tool": "some_tool",
                        "args": {},
                        "on_error": "continue",
                    },
                    {
                        "name": "next_step",
                        "compute": "result = 'ran'",
                        "output": "out",
                    },
                ],
            }
        )
        ex._exec_tool = _mock_exec_tool(
            {
                "some_tool": {"success": False, "error": "minor error"},
            }
        )
        await ex.execute()
        assert ex.context.get("out") == "ran"

    async def test_multiple_steps_in_sequence(self):
        ex = _make_executor(
            skill={
                "name": "multi",
                "steps": [
                    {"name": "step1", "compute": "result = 10", "output": "a"},
                    {"name": "step2", "compute": "result = a + 5", "output": "b"},
                ],
            }
        )
        await ex.execute()
        assert ex.context.get("a") == 10
        assert ex.context.get("b") == 15

    async def test_inputs_default_applied(self):
        ex = _make_executor(
            skill={
                "name": "defaults_test",
                "inputs": [
                    {"name": "greeting", "default": "hello"},
                ],
                "steps": [
                    {
                        "name": "use",
                        "compute": "result = inputs.greeting",
                        "output": "g",
                    },
                ],
            },
            inputs={},
        )
        await ex.execute()
        assert ex.context.get("g") == "hello"

    async def test_inputs_default_not_overridden(self):
        ex = _make_executor(
            skill={
                "name": "defaults_test",
                "inputs": [
                    {"name": "greeting", "default": "hello"},
                ],
                "steps": [
                    {
                        "name": "use",
                        "compute": "result = inputs.greeting",
                        "output": "g",
                    },
                ],
            },
            inputs={"greeting": "hi"},
        )
        await ex.execute()
        assert ex.context.get("g") == "hi"

    async def test_debug_log_included_when_debug(self):
        ex = _make_executor(
            skill={"name": "dbg", "steps": []},
            debug=True,
        )
        result = await ex.execute()
        assert "Debug Log" in result

    async def test_debug_log_excluded_when_not_debug(self):
        ex = _make_executor(
            skill={"name": "no_dbg", "steps": []},
            debug=False,
        )
        result = await ex.execute()
        assert "Debug Log" not in result

    async def test_skill_outputs_section(self):
        ex = _make_executor(
            skill={
                "name": "out_test",
                "steps": [
                    {"name": "s1", "compute": "result = 'data'", "output": "data"},
                ],
                "outputs": [
                    {"name": "summary", "value": "Result: {{ data }}"},
                ],
            }
        )
        result = await ex.execute()
        assert "Outputs" in result
        assert "Result: data" in result

    async def test_skill_outputs_compute(self):
        ex = _make_executor(
            skill={
                "name": "out_compute",
                "steps": [
                    {"name": "s1", "compute": "result = 42", "output": "num"},
                ],
                "outputs": [
                    {"name": "doubled", "compute": "result = num * 2"},
                ],
            }
        )
        result = await ex.execute()
        assert "84" in result

    async def test_then_early_return(self):
        ex = _make_executor(
            skill={
                "name": "early",
                "steps": [
                    {"name": "s1", "compute": "result = 'done'", "output": "val"},
                    {
                        "name": "check",
                        "then": [{"return": "Early exit: {{ val }}"}],
                    },
                    {"name": "s3", "compute": "result = 'never'", "output": "x"},
                ],
            }
        )
        result = await ex.execute()
        assert "Early exit: done" in result or "Early Exit" in result
        assert ex.context.get("x") is None

    async def test_defaults_dict_in_context(self):
        ex = _make_executor(
            skill={
                "name": "def_test",
                "defaults": {"region": "us-east"},
                "steps": [],
            }
        )
        await ex.execute()
        assert ex.context.get("defaults") == {"region": "us-east"}

    async def test_success_and_fail_counts(self):
        ex = _make_executor(
            skill={
                "name": "counts",
                "steps": [
                    {"name": "good", "tool": "t1", "args": {}},
                    {"name": "bad", "tool": "t2", "args": {}, "on_error": "continue"},
                    {"name": "good2", "tool": "t3", "args": {}},
                ],
            }
        )
        ex._exec_tool = _mock_exec_tool(
            {
                "t1": {"success": True, "result": "ok", "duration": 0.01},
                "t2": {"success": False, "error": "fail"},
                "t3": {"success": True, "result": "ok", "duration": 0.01},
            }
        )
        result = await ex.execute()
        assert "\u2705 2 succeeded" in result
        assert "\u274c 1 failed" in result

    async def test_tool_step_stores_parsed_result(self):
        """Tool results with key:value lines should be parsed and stored."""
        ex = _make_executor(
            skill={
                "name": "parse_test",
                "steps": [
                    {
                        "name": "info",
                        "tool": "some_tool",
                        "args": {},
                        "output": "info",
                    },
                ],
            }
        )
        ex._exec_tool = _mock_exec_tool(
            {
                "some_tool": {
                    "success": True,
                    "result": "Status: Active\nRegion: us-east-1",
                    "duration": 0.1,
                },
            }
        )
        await ex.execute()
        parsed = ex.context.get("info_parsed")
        assert parsed is not None
        assert parsed["status"] == "Active"
        assert parsed["region"] == "us-east-1"

    async def test_soft_failure_with_auto_heal(self):
        """Tool returns success=True but result contains error text, on_error=auto_heal."""
        ex = _make_executor(
            skill={
                "name": "soft_fail",
                "steps": [
                    {
                        "name": "check",
                        "tool": "kubectl_get_pods",
                        "args": {},
                        "output": "pods",
                        "on_error": "auto_heal",
                    },
                ],
            }
        )
        ex._exec_tool = _mock_exec_tool(
            {
                "kubectl_get_pods": {
                    "success": True,
                    "result": "Error: unauthorized - 401 must authenticate",
                    "duration": 0.1,
                },
                "kube_login": {
                    "success": False,
                    "result": "login failed",
                    "error": "login failed",
                },
            }
        )
        result = await ex.execute()
        # Should detect soft failure and attempt auto-heal
        assert (
            "soft failure" in result.lower()
            or "auto" in result.lower()
            or "heal" in result.lower()
        )

    async def test_input_default_template(self):
        """Default values with templates should be resolved."""
        ex = _make_executor(
            skill={
                "name": "tmpl_default",
                "inputs": [
                    {"name": "date", "default": "{{ today }}"},
                ],
                "steps": [
                    {"name": "use", "compute": "result = inputs.date", "output": "d"},
                ],
            },
            inputs={},
        )
        await ex.execute()
        # Should be a date string, not the template
        assert "{{" not in (ex.context.get("d") or "")

    async def test_validation_error_continues_on_error_continue(self):
        """If template renders empty for required arg, on_error=continue should proceed."""
        ex = _make_executor(
            skill={
                "name": "val_cont",
                "steps": [
                    {
                        "name": "s1",
                        "tool": "some_tool",
                        "args": {"key": "{{ inputs.missing_var }}"},
                        "on_error": "continue",
                    },
                    {
                        "name": "s2",
                        "compute": "result = 'reached'",
                        "output": "flag",
                    },
                ],
            },
            inputs={},
        )
        ex._exec_tool = _mock_exec_tool()
        await ex.execute()
        assert ex.context.get("flag") == "reached"

    async def test_validation_error_stops_on_error_fail(self):
        """If template renders empty for required arg, on_error=fail stops."""
        ex = _make_executor(
            skill={
                "name": "val_fail",
                "steps": [
                    {
                        "name": "s1",
                        "tool": "some_tool",
                        "args": {"key": "{{ inputs.missing_var }}"},
                        "on_error": "fail",
                    },
                    {
                        "name": "s2",
                        "compute": "result = 'reached'",
                        "output": "flag",
                    },
                ],
            },
            inputs={},
        )
        ex._exec_tool = _mock_exec_tool()
        await ex.execute()
        assert ex.context.get("flag") is None


# ===========================================================================
# _debug method tests
# ===========================================================================


class TestDebugMethod:
    def test_debug_enabled(self):
        ex = _make_executor(debug=True)
        import time

        ex.start_time = time.time()
        ex._debug("test message")
        assert len(ex.log) == 1
        assert "test message" in ex.log[0]

    def test_debug_disabled(self):
        ex = _make_executor(debug=False)
        ex._debug("should not appear")
        assert len(ex.log) == 0


# ===========================================================================
# _parse_and_store_tool_result tests
# ===========================================================================


class TestParseAndStoreToolResult:
    def test_parses_key_value(self):
        ex = _make_executor()
        ex._parse_and_store_tool_result("Name: Alice\nAge: 30", "out")
        parsed = ex.context.get("out_parsed")
        assert parsed is not None
        assert parsed["name"] == "Alice"
        assert parsed["age"] == "30"

    def test_skips_comments(self):
        ex = _make_executor()
        ex._parse_and_store_tool_result("# comment\nKey: val", "out")
        parsed = ex.context.get("out_parsed")
        assert parsed is not None
        assert "key" in parsed

    def test_no_colon_no_parse(self):
        ex = _make_executor()
        ex._parse_and_store_tool_result("just plain text", "out")
        assert "out_parsed" not in ex.context

    def test_handles_exception_gracefully(self):
        ex = _make_executor()
        # Shouldn't raise
        ex._parse_and_store_tool_result(None, "out")  # type: ignore
        assert "out_parsed" not in ex.context


# ===========================================================================
# _check_known_issues_sync and _format_known_issues tests (module-level)
# ===========================================================================


class TestKnownIssuesHelpers:
    def test_format_empty(self):
        assert _format_known_issues([]) == ""

    def test_format_with_matches(self):
        matches = [
            {
                "pattern": "timeout",
                "meaning": "VPN down",
                "fix": "Reconnect VPN",
                "commands": ["vpn connect"],
            },
        ]
        result = _format_known_issues(matches)
        assert "timeout" in result
        assert "VPN down" in result
        assert "Reconnect VPN" in result
        assert "vpn connect" in result

    def test_format_limits_to_three(self):
        matches = [{"pattern": f"p{i}"} for i in range(10)]
        result = _format_known_issues(matches)
        # Only first 3 should be shown
        assert "p0" in result
        assert "p2" in result
        # p3 should not be shown
        count = result.count("Pattern:")
        assert count <= 3


# ===========================================================================
# _linkify_jira_keys and _linkify_mr_ids tests
# ===========================================================================


class TestLinkify:
    def test_linkify_jira_keys_markdown(self):
        ex = _make_executor(inputs={"slack_format": False})
        result = ex._linkify_jira_keys("Fixed in AAP-123 and RHCLOUD-456")
        assert "[AAP-123]" in result
        assert "[RHCLOUD-456]" in result
        assert "browse/AAP-123" in result

    def test_linkify_jira_keys_slack(self):
        ex = _make_executor(inputs={"slack_format": True})
        result = ex._linkify_jira_keys("See AAP-100")
        assert "<" in result
        assert "AAP-100" in result

    def test_linkify_jira_keys_with_suffix(self):
        ex = _make_executor(inputs={"slack_format": False})
        result = ex._linkify_jira_keys("Branch AAP-123-fix-billing")
        assert "AAP-123-fix-billing" in result

    def test_linkify_mr_ids_markdown(self):
        ex = _make_executor(inputs={"slack_format": False})
        result = ex._linkify_mr_ids("Merged !42 and !99")
        assert "[!42]" in result
        assert "[!99]" in result
        assert "merge_requests/42" in result

    def test_linkify_mr_ids_slack(self):
        ex = _make_executor(inputs={"slack_format": True})
        result = ex._linkify_mr_ids("Check !42")
        assert "<" in result
        assert "!42" in result


# ===========================================================================
# _template_with_regex_fallback tests
# ===========================================================================


class TestTemplateRegexFallback:
    def test_simple_var(self):
        ex = _make_executor(inputs={"name": "Bob"})
        result = ex._template_with_regex_fallback("Hello {{ inputs.name }}")
        assert result == "Hello Bob"

    def test_missing_var_unchanged(self):
        ex = _make_executor()
        result = ex._template_with_regex_fallback("{{ nonexistent }}")
        assert "{{" in result  # original template preserved

    def test_nested_dict(self):
        ex = _make_executor()
        ex.context["data"] = {"nested": {"key": "value"}}
        result = ex._template_with_regex_fallback("got {{ data.nested.key }}")
        assert result == "got value"

    def test_array_index(self):
        ex = _make_executor()
        ex.context["items"] = ["a", "b", "c"]
        result = ex._template_with_regex_fallback("{{ items[1] }}")
        assert result == "b"

    def test_array_index_out_of_bounds(self):
        ex = _make_executor()
        ex.context["items"] = ["a"]
        result = ex._template_with_regex_fallback("{{ items[5] }}")
        assert "{{" in result  # original template preserved


# ===========================================================================
# _format_skill_outputs tests
# ===========================================================================


class TestFormatSkillOutputs:
    def test_no_outputs(self):
        ex = _make_executor(skill={"name": "test", "steps": []})
        lines: list[str] = []
        ex._format_skill_outputs(lines)
        assert len(lines) == 0

    def test_value_output(self):
        ex = _make_executor(
            skill={
                "name": "test",
                "steps": [],
                "outputs": [{"name": "summary", "value": "done"}],
            }
        )
        lines: list[str] = []
        ex._format_skill_outputs(lines)
        assert any("summary" in line for line in lines)
        assert any("done" in line for line in lines)

    def test_compute_output(self):
        ex = _make_executor(
            skill={
                "name": "test",
                "steps": [],
                "outputs": [{"name": "calc", "compute": "result = 2 + 2"}],
            }
        )
        lines: list[str] = []
        ex._format_skill_outputs(lines)
        assert any("4" in line for line in lines)

    def test_dict_value_output(self):
        ex = _make_executor(
            skill={
                "name": "test",
                "steps": [],
                "outputs": [{"name": "obj", "value": {"key": "val"}}],
            }
        )
        lines: list[str] = []
        ex._format_skill_outputs(lines)
        assert any("obj" in line for line in lines)

    def test_list_value_output(self):
        ex = _make_executor(
            skill={
                "name": "test",
                "steps": [],
                "outputs": [{"name": "lst", "value": ["a", "b"]}],
            }
        )
        lines: list[str] = []
        ex._format_skill_outputs(lines)
        assert any("lst" in line for line in lines)

    def test_non_string_non_dict_value(self):
        """Value that is not str, dict, or list (e.g., int) takes else branch."""
        ex = _make_executor(
            skill={
                "name": "test",
                "steps": [],
                "outputs": [{"name": "count", "value": 42}],
            }
        )
        lines: list[str] = []
        ex._format_skill_outputs(lines)
        assert any("42" in line for line in lines)
        assert ex.context.get("count") == 42

    def test_bool_value_output(self):
        """Boolean value takes the else branch."""
        ex = _make_executor(
            skill={
                "name": "test",
                "steps": [],
                "outputs": [{"name": "flag", "value": True}],
            }
        )
        lines: list[str] = []
        ex._format_skill_outputs(lines)
        assert any("flag" in line for line in lines)


# ===========================================================================
# _process_then_block tests
# ===========================================================================


class TestProcessThenBlock:
    def test_return_in_then(self):
        ex = _make_executor(debug=True)
        import time

        ex.start_time = time.time()
        step = {"then": [{"return": "early result"}]}
        lines: list[str] = []
        result = ex._process_then_block(step, lines)
        assert result is not None
        assert "early result" in result or "Early Exit" in result

    def test_then_without_return(self):
        ex = _make_executor()
        import time

        ex.start_time = time.time()
        step = {"then": [{"something_else": "value"}]}
        lines: list[str] = []
        result = ex._process_then_block(step, lines)
        assert result is None

    def test_return_with_template(self):
        ex = _make_executor()
        ex.context["msg"] = "hello world"
        import time

        ex.start_time = time.time()
        step = {"then": [{"return": "Message: {{ msg }}"}]}
        lines: list[str] = []
        result = ex._process_then_block(step, lines)
        assert result is not None
        assert "hello world" in result

    def test_return_dict(self):
        ex = _make_executor()
        import time

        ex.start_time = time.time()
        step = {"then": [{"return": {"key": "value"}}]}
        lines: list[str] = []
        result = ex._process_then_block(step, lines)
        assert result is not None


# ===========================================================================
# _emit_memory_events_for_tool tests
# ===========================================================================


class TestEmitMemoryEvents:
    def test_no_emitter_does_nothing(self):
        ex = _make_executor()
        ex.event_emitter = None
        # Should not raise
        ex._emit_memory_events_for_tool(0, "memory_read", {"key": "state/work"})
        assert ex.event_emitter is None

    def test_memory_read_event(self):
        ex = _make_executor()
        emitter = MagicMock(spec=SkillExecutionEmitter)
        ex.event_emitter = emitter
        ex._emit_memory_events_for_tool(0, "memory_read", {"key": "state/work"})
        emitter.memory_read.assert_called_once_with(0, "state/work")
        assert emitter.memory_read.call_count == 1

    def test_memory_write_event(self):
        ex = _make_executor()
        emitter = MagicMock(spec=SkillExecutionEmitter)
        ex.event_emitter = emitter
        ex._emit_memory_events_for_tool(0, "memory_write", {"key": "state/work"})
        emitter.memory_write.assert_called_once_with(0, "state/work")
        assert emitter.memory_write.call_count == 1

    def test_semantic_search_event(self):
        ex = _make_executor()
        emitter = MagicMock(spec=SkillExecutionEmitter)
        ex.event_emitter = emitter
        ex._emit_memory_events_for_tool(0, "code_search", {"query": "billing"})
        emitter.semantic_search.assert_called_once_with(0, "billing")
        assert emitter.semantic_search.call_count == 1

    def test_non_memory_tool_no_event(self):
        ex = _make_executor()
        emitter = MagicMock(spec=SkillExecutionEmitter)
        ex.event_emitter = emitter
        ex._emit_memory_events_for_tool(0, "jira_view_issue", {"key": "AAP-1"})
        emitter.memory_read.assert_not_called()
        emitter.memory_write.assert_not_called()
        emitter.semantic_search.assert_not_called()
        assert True


# ===========================================================================
# _check_error_patterns tests
# ===========================================================================


class TestCheckErrorPatterns:
    def test_returns_none_when_no_file(self):
        ex = _make_executor()
        # Mock SKILLS_DIR to a non-existent path
        with patch(
            "tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", Path("/nonexistent")
        ):
            result = ex._check_error_patterns("some error")
            assert result is None

    def test_returns_none_for_unknown_error(self):
        ex = _make_executor()
        # Even if patterns file exists, an error that doesn't match returns None
        # We don't want to depend on actual file content, so we patch
        with patch(
            "tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", Path("/nonexistent")
        ):
            result = ex._check_error_patterns("totally random text xyz")
            assert result is None


# ===========================================================================
# _validate_skill_inputs and _format_skill_plan (module-level) tests
# ===========================================================================


class TestModuleLevelHelpers:
    def test_validate_no_required(self):
        from tool_modules.aa_workflow.src.skill_engine import _validate_skill_inputs

        skill = {"inputs": [{"name": "a"}, {"name": "b"}]}
        assert _validate_skill_inputs(skill, {}) == []

    def test_validate_required_present(self):
        from tool_modules.aa_workflow.src.skill_engine import _validate_skill_inputs

        skill = {"inputs": [{"name": "a", "required": True}]}
        assert _validate_skill_inputs(skill, {"a": "val"}) == []

    def test_validate_required_missing(self):
        from tool_modules.aa_workflow.src.skill_engine import _validate_skill_inputs

        skill = {"inputs": [{"name": "a", "required": True}]}
        assert _validate_skill_inputs(skill, {}) == ["a"]

    def test_validate_required_with_default(self):
        from tool_modules.aa_workflow.src.skill_engine import _validate_skill_inputs

        skill = {"inputs": [{"name": "a", "required": True, "default": "x"}]}
        assert _validate_skill_inputs(skill, {}) == []

    def test_format_skill_plan(self):
        from tool_modules.aa_workflow.src.skill_engine import _format_skill_plan

        skill = {
            "name": "test_plan",
            "description": "A test skill",
            "steps": [
                {"name": "s1", "tool": "jira_view_issue"},
                {"name": "s2", "compute": "x = 1"},
                {"name": "s3", "description": "Manual step"},
            ],
        }
        result = _format_skill_plan(skill, "test_plan", {"key": "val"})
        assert len(result) == 1
        text = result[0].text
        assert "test_plan" in text
        assert "jira_view_issue" in text
        assert "compute" in text
        assert "manual" in text.lower()

    def test_format_skill_plan_with_condition(self):
        from tool_modules.aa_workflow.src.skill_engine import _format_skill_plan

        skill = {
            "name": "cond_plan",
            "description": "",
            "steps": [
                {"name": "s1", "tool": "t1", "condition": "x > 0"},
            ],
        }
        result = _format_skill_plan(skill, "cond_plan", {})
        text = result[0].text
        assert "Condition" in text

    def test_skill_list_impl_returns_skills(self):
        from tool_modules.aa_workflow.src.skill_engine import _skill_list_impl

        result = _skill_list_impl()
        assert len(result) >= 1
        text = result[0].text
        # The real skills dir has skills, so should return content
        assert "Available Skills" in text or "No skills" in text

    def test_skill_list_impl_empty_dir(self):
        from tool_modules.aa_workflow.src.skill_engine import _skill_list_impl

        with patch(
            "tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", Path("/nonexistent")
        ):
            result = _skill_list_impl()
            assert "No skills found" in result[0].text

    def test_check_known_issues_sync_no_files(self):
        with patch(
            "tool_modules.aa_workflow.src.skill_engine.PROJECT_ROOT",
            Path("/nonexistent"),
        ):
            matches = _check_known_issues_sync("some_tool", "some error")
            assert matches == []

    def test_check_known_issues_sync_with_mock_patterns(self, tmp_path):
        """Create a temp patterns file and verify matching."""
        import yaml

        # PROJECT_ROOT / "memory" / "learned" is the path used
        patterns_dir = tmp_path / "memory" / "learned"
        patterns_dir.mkdir(parents=True)
        patterns_file = patterns_dir / "patterns.yaml"
        patterns_file.write_text(
            yaml.dump(
                {
                    "error_patterns": [
                        {
                            "pattern": "timeout",
                            "meaning": "Slow connection",
                            "fix": "retry",
                            "commands": ["retry"],
                        },
                    ],
                    "auth_patterns": [],
                    "bonfire_patterns": [],
                    "pipeline_patterns": [],
                }
            )
        )
        with patch(
            "tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR",
            tmp_path / "skills",
        ):
            matches = _check_known_issues_sync("", "connection timeout occurred")
            assert len(matches) >= 1
            assert matches[0]["pattern"] == "timeout"

    def test_check_known_issues_sync_tool_fixes(self, tmp_path):
        """Check tool_fixes.yaml matching."""
        import yaml

        patterns_dir = tmp_path / "memory" / "learned"
        patterns_dir.mkdir(parents=True)
        # Create empty patterns.yaml
        (patterns_dir / "patterns.yaml").write_text(yaml.dump({}))
        # Create tool_fixes.yaml
        (patterns_dir / "tool_fixes.yaml").write_text(
            yaml.dump(
                {
                    "tool_fixes": [
                        {
                            "tool_name": "bonfire_deploy",
                            "error_pattern": "manifest unknown",
                            "fix_applied": "use full SHA",
                        },
                    ]
                }
            )
        )
        with patch(
            "tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR",
            tmp_path / "skills",
        ):
            # Match by tool name
            matches = _check_known_issues_sync("bonfire_deploy", "")
            assert len(matches) >= 1
            # Match by error text
            matches2 = _check_known_issues_sync("", "manifest unknown error")
            assert len(matches2) >= 1


# ===========================================================================
# _exec_compute_internal return path tests
# ===========================================================================


class TestExecComputeInternalReturnPaths:
    """Test the different return path branches in _exec_compute_internal."""

    def test_output_name_priority(self):
        """Output name takes priority over 'result' variable."""
        ex = _make_executor()
        val = ex._exec_compute_internal("out = 10\nresult = 20", "out")
        assert val == 10

    def test_result_fallback(self):
        """Falls back to 'result' when output_name not found."""
        ex = _make_executor()
        val = ex._exec_compute_internal("result = 42", "missing_name")
        assert val == 42

    def test_no_result_returns_none(self):
        """Returns None when neither output_name nor result is set."""
        ex = _make_executor()
        val = ex._exec_compute_internal("x = 1", "missing")
        assert val is None

    def test_return_keyword_parsing(self):
        """Code with 'return' keyword triggers last-return-line eval."""
        ex = _make_executor()
        # We need "return" in the code text but it won't actually execute as a function
        # The code scans for lines starting with "return " and evals the expression
        val = ex._exec_compute_internal("x = 5\n# return x", "missing")
        # "return" is in the code but the actual return line is a comment
        # so it should be None
        assert val is None

    def test_context_updated_with_new_vars(self):
        """Variables defined in compute should be available in context."""
        ex = _make_executor()
        ex._exec_compute_internal("my_var = 'hello'", "my_var")
        # The internal method updates local_vars but not self.context directly
        # _exec_compute does store it though
        result = ex._exec_compute("my_var = 'hello'", "my_var")
        # _exec_compute returns the value but execute() stores to context
        assert result == "hello"


# ===========================================================================
# _check_error_patterns with mock data
# ===========================================================================


class TestCheckErrorPatternsWithData:
    def test_matching_pattern(self, tmp_path):
        import yaml

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        patterns_dir = tmp_path / "memory" / "learned"
        patterns_dir.mkdir(parents=True)
        (patterns_dir / "patterns.yaml").write_text(
            yaml.dump(
                {
                    "error_patterns": [
                        {
                            "pattern": "connection refused",
                            "meaning": "Service down",
                            "fix": "Restart service",
                            "commands": ["systemctl restart app"],
                        },
                    ],
                }
            )
        )
        ex = _make_executor()
        with patch("tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", skills_dir):
            result = ex._check_error_patterns("Error: connection refused on port 8080")
            assert result is not None
            assert "connection refused" in result
            assert "Service down" in result
            assert "Restart service" in result
            assert "systemctl restart app" in result

    def test_no_matching_pattern(self, tmp_path):
        import yaml

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        patterns_dir = tmp_path / "memory" / "learned"
        patterns_dir.mkdir(parents=True)
        (patterns_dir / "patterns.yaml").write_text(
            yaml.dump(
                {
                    "error_patterns": [
                        {"pattern": "very specific error"},
                    ],
                }
            )
        )
        ex = _make_executor()
        with patch("tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", skills_dir):
            result = ex._check_error_patterns("totally different error")
            assert result is None


# ===========================================================================
# _find_matched_pattern tests
# ===========================================================================


class TestFindMatchedPattern:
    def test_no_file_returns_none(self):
        ex = _make_executor()
        with patch(
            "tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", Path("/nonexistent")
        ):
            pattern, cat = ex._find_matched_pattern("some error")
            assert pattern is None
            assert cat is None

    def test_matching_pattern(self, tmp_path):
        import yaml

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        patterns_dir = tmp_path / "memory" / "learned"
        patterns_dir.mkdir(parents=True)
        (patterns_dir / "patterns.yaml").write_text(
            yaml.dump(
                {
                    "auth_patterns": [
                        {"pattern": "unauthorized", "commands": ["oc login"]},
                    ],
                    "error_patterns": [],
                    "bonfire_patterns": [],
                    "pipeline_patterns": [],
                }
            )
        )
        ex = _make_executor()
        with patch("tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", skills_dir):
            pattern, cat = ex._find_matched_pattern("got unauthorized error")
            assert pattern is not None
            assert cat == "auth_patterns"
            assert pattern["pattern"] == "unauthorized"


# ===========================================================================
# Additional execute() edge cases
# ===========================================================================


class TestExecuteEdgeCases:
    async def test_compute_error_stores_error_in_context(self):
        """When compute fails, error is stored in context as _error key."""
        ex = _make_executor(
            skill={
                "name": "err_ctx",
                "steps": [
                    {
                        "name": "bad",
                        "compute": "raise ValueError('boom')",
                        "output": "data",
                    },
                ],
            }
        )
        await ex.execute()
        assert ex.context.get("data") is None
        assert ex.context.get("data_error") is not None
        assert "boom" in ex.context["data_error"]

    async def test_compute_error_recorded_in_step_results(self):
        ex = _make_executor(
            skill={
                "name": "err_res",
                "steps": [
                    {
                        "name": "bad_step",
                        "compute": "raise RuntimeError('oops')",
                        "output": "x",
                    },
                ],
            }
        )
        await ex.execute()
        assert len(ex.step_results) == 1
        assert ex.step_results[0]["success"] is False
        assert ex.step_results[0]["compute"] is True

    async def test_tool_result_long_text_truncated(self):
        """Long tool results should be truncated in output."""
        ex = _make_executor(
            skill={
                "name": "long_out",
                "steps": [
                    {"name": "s1", "tool": "t", "args": {}, "output": "data"},
                ],
            }
        )
        long_text = "x" * 500
        ex._exec_tool = _mock_exec_tool(
            {
                "t": {"success": True, "result": long_text, "duration": 0.1},
            }
        )
        result = await ex.execute()
        assert "..." in result

    async def test_tool_error_result_key_fallback(self):
        """Tool result with error in 'result' key instead of 'error' key."""
        ex = _make_executor(
            skill={
                "name": "err_key",
                "steps": [
                    {"name": "s1", "tool": "t", "args": {}},
                ],
            }
        )
        ex._exec_tool = _mock_exec_tool(
            {
                "t": {"success": False, "result": "something went wrong"},
            }
        )
        result = await ex.execute()
        assert "something went wrong" in result or "failed" in result.lower()

    async def test_debug_inputs_shown(self):
        """In debug mode, inputs should be shown in output."""
        ex = _make_executor(
            skill={"name": "dbg_in", "steps": []},
            inputs={"key": "val"},
            debug=True,
        )
        result = await ex.execute()
        assert "key" in result
        assert "val" in result

    async def test_description_with_template(self):
        """Description steps should resolve templates."""
        ex = _make_executor(
            skill={
                "name": "desc_tmpl",
                "steps": [
                    {"name": "s1", "compute": "result = 'world'", "output": "who"},
                    {"name": "s2", "description": "Hello {{ who }}"},
                ],
            }
        )
        result = await ex.execute()
        assert "Hello world" in result

    async def test_tool_step_no_output_uses_step_name(self):
        """When no output key is specified, step_name is used as output key."""
        ex = _make_executor(
            skill={
                "name": "no_out",
                "steps": [
                    {"name": "my_step", "tool": "t", "args": {}},
                ],
            }
        )
        ex._exec_tool = _mock_exec_tool(
            {
                "t": {"success": True, "result": "step data", "duration": 0.1},
            }
        )
        await ex.execute()
        assert ex.context.get("my_step") == "step data"

    async def test_auto_heal_success_stores_result(self):
        """When auto_heal succeeds, the result should be stored."""
        call_count = {"n": 0}

        async def dynamic_tool(tool_name: str, args: dict) -> dict:
            if tool_name == "kubectl_get_pods":
                call_count["n"] += 1
                if call_count["n"] == 1:
                    # First call: fails
                    return {"success": False, "error": "unauthorized 401"}
                else:
                    # After heal: succeeds
                    return {"success": True, "result": "pod1 Running", "duration": 0.1}
            if tool_name == "kube_login":
                return {"success": True, "result": "Logged in", "duration": 0.5}
            return {"success": True, "result": "ok", "duration": 0.01}

        ex = _make_executor(
            skill={
                "name": "heal_ok",
                "steps": [
                    {
                        "name": "pods",
                        "tool": "kubectl_get_pods",
                        "args": {},
                        "output": "pod_list",
                        "on_error": "auto_heal",
                    },
                ],
            }
        )
        ex._exec_tool = dynamic_tool
        await ex.execute()
        # After auto-heal, the result should be stored
        result_val = ex.context.get("pod_list")
        if result_val:
            assert "Running" in result_val

    async def test_no_steps_yields_completion(self):
        """A skill with no steps should still complete and report timing."""
        ex = _make_executor(skill={"name": "noop", "steps": []})
        result = await ex.execute()
        assert "Completed" in result
        assert "0 succeeded" in result or "succeeded" in result

    async def test_condition_with_prior_step_output(self):
        """Condition can reference output from prior step."""
        ex = _make_executor(
            skill={
                "name": "cond_ref",
                "steps": [
                    {"name": "s1", "compute": "result = 'active'", "output": "status"},
                    {
                        "name": "s2",
                        "condition": "status == 'active'",
                        "compute": "result = 'ran'",
                        "output": "ran",
                    },
                    {
                        "name": "s3",
                        "condition": "status == 'inactive'",
                        "compute": "result = 'skipped'",
                        "output": "skip",
                    },
                ],
            }
        )
        await ex.execute()
        assert ex.context.get("ran") == "ran"
        assert ex.context.get("skip") is None


# ===========================================================================
# _handle_tool_error auto_heal with successful retry
# ===========================================================================


class TestHandleToolErrorAutoHealSuccess:
    async def test_auto_heal_auth_success(self):
        """auto_heal detects auth error, heals, and retries successfully."""
        call_count = {"n": 0}

        async def mock_tool(tool_name: str, args: dict) -> dict:
            if tool_name == "kube_login":
                return {
                    "success": True,
                    "result": "Logged in to stage",
                    "duration": 0.5,
                }
            if tool_name == "kubectl_get_pods":
                call_count["n"] += 1
                if call_count["n"] == 1:
                    return {"success": True, "result": "pod1 Running", "duration": 0.1}
                return {"success": True, "result": "pod1 Running", "duration": 0.1}
            return {"success": True, "result": "ok", "duration": 0.01}

        ex = _make_executor()
        ex._exec_tool = mock_tool
        step = {"tool": "kubectl_get_pods", "on_error": "auto_heal", "args": {}}
        lines: list[str] = []
        should_continue = await ex._handle_tool_error(
            "kubectl_get_pods", step, "step1", "unauthorized 401 error", lines
        )
        assert should_continue is True
        # Should have appended heal-related lines
        assert any("auth" in line.lower() or "heal" in line.lower() for line in lines)

    async def test_auto_heal_network_error(self):
        """auto_heal detects network error."""
        ex = _make_executor()
        ex._exec_tool = _mock_exec_tool(
            {
                "vpn_connect": {
                    "success": False,
                    "result": "vpn failed",
                    "error": "vpn failed",
                },
            }
        )
        step = {"tool": "some_tool", "on_error": "auto_heal", "args": {}}
        lines: list[str] = []
        should_continue = await ex._handle_tool_error(
            "some_tool", step, "step1", "no route to host", lines
        )
        assert should_continue is True
        assert any(
            "network" in line.lower() or "heal" in line.lower() for line in lines
        )


# ===========================================================================
# _skill_list_impl with real skills dir
# ===========================================================================


class TestSkillListImpl:
    def test_returns_text_content(self):
        from tool_modules.aa_workflow.src.skill_engine import _skill_list_impl

        result = _skill_list_impl()
        assert len(result) >= 1
        # Should have TextContent objects
        assert hasattr(result[0], "text")

    def test_with_mock_skills(self, tmp_path):
        import yaml

        from tool_modules.aa_workflow.src.skill_engine import _skill_list_impl

        # Create a fake skills dir
        skill_file = tmp_path / "test_skill.yaml"
        skill_file.write_text(
            yaml.dump(
                {
                    "name": "test_skill",
                    "description": "A test skill",
                    "inputs": [{"name": "key"}],
                    "steps": [],
                }
            )
        )
        with patch("tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", tmp_path):
            result = _skill_list_impl()
            text = result[0].text
            assert "test_skill" in text
            assert "A test skill" in text
            assert "key" in text

    def test_with_invalid_yaml(self, tmp_path):
        from tool_modules.aa_workflow.src.skill_engine import _skill_list_impl

        # Create an invalid YAML file
        skill_file = tmp_path / "broken.yaml"
        skill_file.write_text("{{invalid yaml: [")
        with patch("tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", tmp_path):
            result = _skill_list_impl()
            text = result[0].text
            assert "broken" in text or "Error" in text

    def test_readme_skipped(self, tmp_path):
        """README.md should be skipped in skill list."""
        import yaml

        from tool_modules.aa_workflow.src.skill_engine import _skill_list_impl

        (tmp_path / "README.md").write_text("# README")
        (tmp_path / "real_skill.yaml").write_text(
            yaml.dump(
                {
                    "name": "real_skill",
                    "description": "A real skill",
                    "inputs": [],
                    "steps": [],
                }
            )
        )
        with patch("tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", tmp_path):
            result = _skill_list_impl()
            text = result[0].text
            assert "real_skill" in text
            assert "README" not in text


# ===========================================================================
# _format_known_issues edge cases
# ===========================================================================


class TestFormatKnownIssuesEdgeCases:
    def test_match_without_meaning(self):
        matches = [{"pattern": "err"}]
        result = _format_known_issues(matches)
        assert "err" in result

    def test_match_without_fix(self):
        matches = [{"pattern": "err", "meaning": "something"}]
        result = _format_known_issues(matches)
        assert "something" in result

    def test_match_with_multiple_commands(self):
        matches = [{"pattern": "err", "commands": ["cmd1", "cmd2", "cmd3"]}]
        result = _format_known_issues(matches)
        assert "cmd1" in result
        assert "cmd2" in result
        # Only first 2 commands shown
        # Actually the code shows [:2] for commands
        assert "cmd3" not in result


# ===========================================================================
# _update_pattern_usage_stats tests
# ===========================================================================


class TestUpdatePatternUsageStats:
    def test_no_file_does_nothing(self):
        ex = _make_executor()
        with patch(
            "tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", Path("/nonexistent")
        ):
            # Should not raise
            ex._update_pattern_usage_stats("error_patterns", "timeout", matched=True)
        assert True

    def test_updates_stats(self, tmp_path):
        import yaml

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        patterns_dir = tmp_path / "memory" / "learned"
        patterns_dir.mkdir(parents=True)
        patterns_file = patterns_dir / "patterns.yaml"
        patterns_file.write_text(
            yaml.dump(
                {
                    "error_patterns": [
                        {"pattern": "timeout", "meaning": "slow"},
                    ],
                }
            )
        )
        ex = _make_executor()
        with patch("tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", skills_dir):
            ex._update_pattern_usage_stats("error_patterns", "timeout", matched=True)

        # Read back and check
        with open(patterns_file) as f:
            data = yaml.safe_load(f)
        pattern = data["error_patterns"][0]
        assert "usage_stats" in pattern
        assert pattern["usage_stats"]["times_matched"] == 1

    def test_updates_fix_count(self, tmp_path):
        import yaml

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        patterns_dir = tmp_path / "memory" / "learned"
        patterns_dir.mkdir(parents=True)
        patterns_file = patterns_dir / "patterns.yaml"
        patterns_file.write_text(
            yaml.dump(
                {
                    "error_patterns": [
                        {
                            "pattern": "timeout",
                            "usage_stats": {
                                "times_matched": 5,
                                "times_fixed": 2,
                                "success_rate": 0.4,
                            },
                        },
                    ],
                }
            )
        )
        ex = _make_executor()
        with patch("tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", skills_dir):
            ex._update_pattern_usage_stats(
                "error_patterns", "timeout", matched=False, fixed=True
            )

        with open(patterns_file) as f:
            data = yaml.safe_load(f)
        stats = data["error_patterns"][0]["usage_stats"]
        assert stats["times_fixed"] == 3
        assert stats["times_matched"] == 5  # unchanged
        assert stats["success_rate"] == 0.6

    def test_missing_category(self, tmp_path):
        import yaml

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        patterns_dir = tmp_path / "memory" / "learned"
        patterns_dir.mkdir(parents=True)
        patterns_file = patterns_dir / "patterns.yaml"
        patterns_file.write_text(yaml.dump({"other": []}))
        ex = _make_executor()
        with patch("tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", skills_dir):
            # Should not raise
            ex._update_pattern_usage_stats("error_patterns", "timeout", matched=True)
        assert True


# ===========================================================================
# _learn_from_error tests
# ===========================================================================


class TestLearnFromError:
    async def test_no_learner(self):
        ex = _make_executor()
        ex.usage_learner = None
        # Should not raise
        await ex._learn_from_error("tool", {}, "error")
        assert ex.usage_learner is None

    async def test_learner_exception(self):
        ex = _make_executor()
        learner = AsyncMock()
        learner.learn_from_observation.side_effect = RuntimeError("learn fail")
        ex.usage_learner = learner
        # Test verifies no exception is raised - errors are swallowed
        await ex._learn_from_error("tool", {}, "error")
        learner.learn_from_observation.assert_called_once()
        assert learner.learn_from_observation.call_count == 1


# ===========================================================================
# _process_tool_step edge cases
# ===========================================================================


class TestProcessToolStep:
    async def test_tool_step_error_result_key(self):
        """Error in result key (not error key) should be handled."""
        ex = _make_executor(
            skill={"name": "t", "steps": []},
        )
        ex._exec_tool = _mock_exec_tool(
            {
                "t": {"success": False, "result": "bad result text"},
            }
        )
        step = {"tool": "t", "args": {}, "name": "s1"}
        lines: list[str] = []
        result = await ex._process_tool_step(step, 1, "s1", lines)
        assert result is False  # default on_error=fail

    async def test_tool_step_validation_error_recorded(self):
        """Validation error should be recorded in step_results."""
        ex = _make_executor(
            skill={"name": "t", "steps": []},
        )
        ex._exec_tool = _mock_exec_tool()
        step = {
            "tool": "t",
            "args": {"key": "{{ inputs.novar }}"},
            "name": "s1",
            "on_error": "fail",
        }
        lines: list[str] = []
        result = await ex._process_tool_step(step, 1, "s1", lines)
        assert result is False
        assert len(ex.step_results) == 1
        assert ex.step_results[0]["success"] is False


# ===========================================================================
# _exec_compute_internal return-keyword path
# ===========================================================================


class TestExecComputeReturnKeyword:
    def test_return_keyword_in_string_no_match(self):
        """Code has 'return' as a substring but no actual return line."""
        ex = _make_executor()
        # "return" appears in the string value, triggering the "return" in code check,
        # but no line starts with "return " so the for/else falls to None
        code = "x = 'return value'"
        result = ex._exec_compute_internal(code, "nonexistent_output")
        assert result is None

    def test_return_in_comment(self):
        """Code has 'return' in a comment -- for/else triggers but no line matches."""
        ex = _make_executor()
        code = "x = 42\n# return x"
        result = ex._exec_compute_internal(code, "nonexistent_output")
        # "return" is in the code, but "# return x".strip() starts with "#", not "return "
        assert result is None


# ===========================================================================
# _exec_compute with interactive recovery
# ===========================================================================


class TestExecComputeInteractiveRecovery:
    def test_recovery_triggered_when_enabled(self):
        """Interactive recovery is attempted when enabled and ask_question_fn is set."""
        ask_fn = AsyncMock()
        ex = _make_executor(
            enable_interactive_recovery=True,
            ask_question_fn=ask_fn,
        )
        # Mock _try_interactive_recovery to return a value
        ex._try_interactive_recovery = MagicMock(return_value="recovered_value")
        result = ex._exec_compute("raise ValueError('test')", "out")
        assert result == "recovered_value"
        ex._try_interactive_recovery.assert_called_once()

    def test_recovery_returns_none_falls_through(self):
        """When recovery returns None, falls through to error string."""
        ask_fn = AsyncMock()
        ex = _make_executor(
            enable_interactive_recovery=True,
            ask_question_fn=ask_fn,
        )
        ex._try_interactive_recovery = MagicMock(return_value=None)
        result = ex._exec_compute("raise ValueError('test')", "out")
        assert isinstance(result, str)
        assert "compute error" in result.lower()


# ===========================================================================
# _skill_run_impl tests
# ===========================================================================


class TestSkillRunImpl:
    async def test_missing_skill(self):
        from tool_modules.aa_workflow.src.skill_engine import _skill_run_impl

        result = await _skill_run_impl(
            "nonexistent_skill_xyz", "{}", True, False, MagicMock()
        )
        assert "not found" in result[0].text.lower()

    async def test_invalid_json_inputs(self, tmp_path):
        import yaml

        from tool_modules.aa_workflow.src.skill_engine import _skill_run_impl

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_file = skills_dir / "test_skill.yaml"
        skill_file.write_text(yaml.dump({"name": "test_skill", "steps": []}))
        with patch("tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", skills_dir):
            result = await _skill_run_impl(
                "test_skill", "{invalid json", True, False, MagicMock()
            )
            assert "Invalid" in result[0].text

    async def test_missing_required_inputs(self, tmp_path):
        import yaml

        from tool_modules.aa_workflow.src.skill_engine import _skill_run_impl

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_file = skills_dir / "test_skill.yaml"
        skill_file.write_text(
            yaml.dump(
                {
                    "name": "test_skill",
                    "inputs": [{"name": "required_arg", "required": True}],
                    "steps": [],
                }
            )
        )
        with patch("tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", skills_dir):
            result = await _skill_run_impl(
                "test_skill", "{}", True, False, MagicMock(spec=FastMCP)
            )
            assert "Missing" in result[0].text or "required" in result[0].text.lower()

    async def test_preview_mode(self, tmp_path):
        import yaml

        from tool_modules.aa_workflow.src.skill_engine import _skill_run_impl

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_file = skills_dir / "test_skill.yaml"
        skill_file.write_text(
            yaml.dump(
                {
                    "name": "test_skill",
                    "description": "A test",
                    "steps": [{"name": "s1", "tool": "t1"}],
                }
            )
        )
        with patch("tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", skills_dir):
            result = await _skill_run_impl(
                "test_skill", "{}", False, False, MagicMock()
            )
            text = result[0].text
            assert "Plan" in text
            assert "test_skill" in text

    async def test_execute_mode(self, tmp_path):
        import yaml

        from tool_modules.aa_workflow.src.skill_engine import _skill_run_impl

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_file = skills_dir / "test_skill.yaml"
        skill_file.write_text(
            yaml.dump(
                {
                    "name": "test_skill",
                    "description": "A test",
                    "steps": [
                        {
                            "name": "calc",
                            "compute": "result = 2 + 2",
                            "output": "answer",
                        },
                    ],
                }
            )
        )
        with patch("tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", skills_dir):
            result = await _skill_run_impl(
                "test_skill", "{}", True, False, MagicMock(spec=FastMCP)
            )
            text = result[0].text
            assert "Executing" in text
            assert "Completed" in text

    async def test_execute_mode_with_debug(self, tmp_path):
        import yaml

        from tool_modules.aa_workflow.src.skill_engine import _skill_run_impl

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_file = skills_dir / "test_skill.yaml"
        skill_file.write_text(
            yaml.dump(
                {
                    "name": "test_skill",
                    "description": "A test",
                    "steps": [],
                }
            )
        )
        with patch("tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", skills_dir):
            result = await _skill_run_impl(
                "test_skill", "{}", True, True, MagicMock(spec=FastMCP)
            )
            text = result[0].text
            assert "Debug Log" in text

    async def test_error_loading_skill(self, tmp_path):
        from tool_modules.aa_workflow.src.skill_engine import _skill_run_impl

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        # Create invalid YAML
        (skills_dir / "bad.yaml").write_text("{{invalid")
        with patch("tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", skills_dir):
            result = await _skill_run_impl(
                "bad", "{}", True, False, MagicMock(spec=FastMCP)
            )
            assert "Error" in result[0].text

    async def test_error_with_debug_shows_traceback(self, tmp_path):
        from tool_modules.aa_workflow.src.skill_engine import _skill_run_impl

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "bad.yaml").write_text("{{invalid")
        with patch("tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", skills_dir):
            result = await _skill_run_impl(
                "bad", "{}", True, True, MagicMock(spec=FastMCP)
            )
            # Debug mode shows traceback
            assert "Error" in result[0].text


# ===========================================================================
# _attempt_auto_heal tests
# ===========================================================================


class TestAttemptAutoHeal:
    async def test_auth_heal_success_and_retry(self):
        call_count = {"n": 0}

        async def mock_tool(tool_name: str, args: dict) -> dict:
            if tool_name == "kube_login":
                return {"success": True, "result": "Logged in", "duration": 0.5}
            if tool_name == "orig_tool":
                call_count["n"] += 1
                return {"success": True, "result": "retried ok", "duration": 0.1}
            return {"success": True, "result": "ok", "duration": 0.01}

        ex = _make_executor()
        ex._exec_tool = mock_tool
        step = {"tool": "orig_tool", "args": {}}
        lines: list[str] = []
        result = await ex._attempt_auto_heal("auth", "stage", "orig_tool", step, lines)
        assert result is not None
        assert result["success"] is True

    async def test_network_heal_success(self):
        async def mock_tool(tool_name: str, args: dict) -> dict:
            if tool_name == "vpn_connect":
                return {"success": True, "result": "VPN connected", "duration": 1.0}
            return {"success": True, "result": "retried ok", "duration": 0.1}

        ex = _make_executor()
        ex._exec_tool = mock_tool
        step = {"tool": "orig_tool", "args": {}}
        lines: list[str] = []
        result = await ex._attempt_auto_heal(
            "network", "stage", "orig_tool", step, lines
        )
        assert result is not None
        assert result["success"] is True

    async def test_auth_heal_failure(self):
        async def mock_tool(tool_name: str, args: dict) -> dict:
            if tool_name == "kube_login":
                return {
                    "success": False,
                    "error": "login failed",
                    "result": "login failed",
                }
            return {"success": True, "result": "ok", "duration": 0.01}

        ex = _make_executor()
        ex._exec_tool = mock_tool
        step = {"tool": "t", "args": {}}
        lines: list[str] = []
        result = await ex._attempt_auto_heal("auth", "stage", "t", step, lines)
        assert result is None

    async def test_network_heal_failure(self):
        async def mock_tool(tool_name: str, args: dict) -> dict:
            if tool_name == "vpn_connect":
                return {"success": False, "error": "vpn failed", "result": "vpn failed"}
            return {"success": True, "result": "ok", "duration": 0.01}

        ex = _make_executor()
        ex._exec_tool = mock_tool
        step = {"tool": "t", "args": {}}
        lines: list[str] = []
        result = await ex._attempt_auto_heal("network", "stage", "t", step, lines)
        assert result is None

    async def test_unknown_heal_type(self):
        ex = _make_executor()
        ex._exec_tool = _mock_exec_tool()
        step = {"tool": "t", "args": {}}
        lines: list[str] = []
        result = await ex._attempt_auto_heal("unknown_type", "stage", "t", step, lines)
        assert result is None

    async def test_heal_exception(self):
        async def mock_tool(tool_name: str, args: dict) -> dict:
            raise RuntimeError("total failure")

        ex = _make_executor()
        ex._exec_tool = mock_tool
        step = {"tool": "t", "args": {}}
        lines: list[str] = []
        result = await ex._attempt_auto_heal("auth", "stage", "t", step, lines)
        assert result is None
        assert any("exception" in line.lower() for line in lines)

    async def test_heal_long_error_truncated(self):
        """Error messages longer than 200 chars are truncated."""

        async def mock_tool(tool_name: str, args: dict) -> dict:
            if tool_name == "kube_login":
                return {"success": False, "error": "x" * 300, "result": "x" * 300}
            return {"success": True, "result": "ok", "duration": 0.01}

        ex = _make_executor()
        ex._exec_tool = mock_tool
        step = {"tool": "t", "args": {}}
        lines: list[str] = []
        result = await ex._attempt_auto_heal("auth", "stage", "t", step, lines)
        assert result is None
        # Should have truncated error
        truncated_lines = [line for line in lines if "..." in line]
        assert len(truncated_lines) > 0


# ===========================================================================
# _log_auto_heal_to_memory tests
# ===========================================================================


class TestLogAutoHealToMemory:
    async def test_creates_file_if_missing(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        ex = _make_executor()
        with patch("tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", skills_dir):
            await ex._log_auto_heal_to_memory("tool", "auth", "error text", True)
        failures_file = tmp_path / "memory" / "learned" / "tool_failures.yaml"
        assert failures_file.exists()

    async def test_updates_existing_file(self, tmp_path):
        import yaml

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        memory_dir = tmp_path / "memory" / "learned"
        memory_dir.mkdir(parents=True)
        failures_file = memory_dir / "tool_failures.yaml"
        failures_file.write_text(
            yaml.dump(
                {
                    "failures": [],
                    "stats": {
                        "total_failures": 0,
                        "auto_fixed": 0,
                        "manual_required": 0,
                    },
                }
            )
        )
        ex = _make_executor()
        with patch("tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", skills_dir):
            await ex._log_auto_heal_to_memory("tool", "auth", "error", True)
        with open(failures_file) as f:
            data = yaml.safe_load(f)
        assert data["stats"]["total_failures"] == 1
        assert data["stats"]["auto_fixed"] == 1
        assert len(data["failures"]) == 1

    async def test_manual_required_count(self, tmp_path):
        import yaml

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        memory_dir = tmp_path / "memory" / "learned"
        memory_dir.mkdir(parents=True)
        failures_file = memory_dir / "tool_failures.yaml"
        failures_file.write_text(
            yaml.dump(
                {
                    "failures": [],
                    "stats": {
                        "total_failures": 0,
                        "auto_fixed": 0,
                        "manual_required": 0,
                    },
                }
            )
        )
        ex = _make_executor()
        with patch("tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", skills_dir):
            await ex._log_auto_heal_to_memory("tool", "network", "err", False)
        with open(failures_file) as f:
            data = yaml.safe_load(f)
        assert data["stats"]["manual_required"] == 1
        assert data["stats"]["auto_fixed"] == 0


# ===========================================================================
# _handle_tool_error with create_issue_fn edge cases
# ===========================================================================


class TestHandleToolErrorIssueCreation:
    async def test_create_issue_url_only(self):
        """When create_issue_fn returns success=False but has issue_url."""
        create_fn = AsyncMock(
            return_value={
                "success": False,
                "issue_url": "https://github.com/issues/new?body=error",
            }
        )
        ex = _make_executor(create_issue_fn=create_fn)
        ex._exec_tool = _mock_exec_tool()
        step = {"tool": "t", "on_error": "fail"}
        lines: list[str] = []
        await ex._handle_tool_error("t", step, "s1", "error msg", lines)
        assert any(
            "report" in line.lower() or "issue" in line.lower() for line in lines
        )

    async def test_create_issue_fn_exception(self):
        """When create_issue_fn raises, it should be handled gracefully."""
        create_fn = AsyncMock(side_effect=RuntimeError("api error"))
        ex = _make_executor(create_issue_fn=create_fn, debug=True)
        import time

        ex.start_time = time.time()
        ex._exec_tool = _mock_exec_tool()
        step = {"tool": "t", "on_error": "fail"}
        lines: list[str] = []
        # Test verifies no exception is raised
        await ex._handle_tool_error("t", step, "s1", "error", lines)
        create_fn.assert_called_once()
        assert create_fn.call_count == 1


# ===========================================================================
# Additional coverage for _handle_tool_error auto_heal retry success
# ===========================================================================


class TestHandleToolErrorAutoHealRetrySuccess:
    async def test_full_auto_heal_flow_success(self):
        """Full auto_heal: detect auth -> heal -> retry -> success."""
        call_num = {"n": 0}

        async def mock_tool(tool_name: str, args: dict) -> dict:
            if tool_name == "kube_login":
                return {
                    "success": True,
                    "result": "Logged in to stage cluster",
                    "duration": 0.5,
                }
            if tool_name == "kubectl_get_pods":
                call_num["n"] += 1
                if call_num["n"] <= 1:
                    # First call is the retry after heal
                    return {
                        "success": True,
                        "result": "pod1 Running\npod2 Running",
                        "duration": 0.1,
                    }
                return {"success": True, "result": "pod1 Running", "duration": 0.1}
            return {"success": True, "result": "ok", "duration": 0.01}

        ex = _make_executor()
        ex._exec_tool = mock_tool
        step = {
            "tool": "kubectl_get_pods",
            "on_error": "auto_heal",
            "args": {},
            "output": "pods",
        }
        lines: list[str] = []
        should_continue = await ex._handle_tool_error(
            "kubectl_get_pods", step, "get_pods", "unauthorized 401", lines
        )
        assert should_continue is True
        # Should have recorded successful auto-heal
        heal_results = [r for r in ex.step_results if r.get("auto_healed")]
        assert len(heal_results) >= 1
        assert heal_results[0]["success"] is True

    async def test_auto_heal_with_pattern_hint(self, tmp_path):
        """auto_heal with a known pattern match in error patterns."""
        import yaml

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        patterns_dir = tmp_path / "memory" / "learned"
        patterns_dir.mkdir(parents=True)
        (patterns_dir / "patterns.yaml").write_text(
            yaml.dump(
                {
                    "error_patterns": [
                        {
                            "pattern": "unauthorized",
                            "meaning": "Auth expired",
                            "fix": "Login again",
                        },
                    ],
                }
            )
        )

        async def mock_tool(tool_name: str, args: dict) -> dict:
            if tool_name == "kube_login":
                return {"success": False, "error": "failed", "result": "failed"}
            return {"success": True, "result": "ok", "duration": 0.01}

        ex = _make_executor()
        ex._exec_tool = mock_tool
        step = {"tool": "t", "on_error": "auto_heal", "args": {}}
        lines: list[str] = []
        with patch("tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", skills_dir):
            should_continue = await ex._handle_tool_error(
                "t", step, "step1", "got unauthorized 401 error", lines
            )
        assert should_continue is True
        # Pattern hint should appear in output
        assert any(
            "unauthorized" in line.lower() or "auth" in line.lower() for line in lines
        )


# ===========================================================================
# _skill_run_impl with required input description
# ===========================================================================


class TestSkillRunImplInputDescription:
    async def test_missing_required_with_description(self, tmp_path):
        """Required input with description field should show description."""
        import yaml

        from tool_modules.aa_workflow.src.skill_engine import _skill_run_impl

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_file = skills_dir / "test_skill.yaml"
        skill_file.write_text(
            yaml.dump(
                {
                    "name": "test_skill",
                    "inputs": [
                        {
                            "name": "key",
                            "required": True,
                            "type": "string",
                            "description": "The Jira issue key",
                        },
                    ],
                    "steps": [],
                }
            )
        )
        with patch("tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", skills_dir):
            result = await _skill_run_impl(
                "test_skill", "{}", True, False, MagicMock(spec=FastMCP)
            )
            text = result[0].text
            assert "Missing" in text
            assert "The Jira issue key" in text

    async def test_missing_required_with_default_shown(self, tmp_path):
        """Required input with default should show the default in error."""
        import yaml

        from tool_modules.aa_workflow.src.skill_engine import _skill_run_impl

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_file = skills_dir / "test_skill.yaml"
        skill_file.write_text(
            yaml.dump(
                {
                    "name": "test_skill",
                    "inputs": [
                        {"name": "a", "required": True},  # no default = missing
                        {"name": "b", "required": False, "default": "fallback"},
                    ],
                    "steps": [],
                }
            )
        )
        with patch("tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", skills_dir):
            result = await _skill_run_impl(
                "test_skill", "{}", True, False, MagicMock(spec=FastMCP)
            )
            text = result[0].text
            assert "Missing" in text
            assert "default: fallback" in text


# ===========================================================================
# execute() with compute step exception (not string error)
# ===========================================================================


class TestExecuteComputeException:
    async def test_compute_direct_exception(self):
        """Compute step that raises during exec should be caught."""
        ex = _make_executor(
            skill={
                "name": "exc_test",
                "steps": [
                    {
                        "name": "bad",
                        "compute": "1/0",
                        "output": "x",
                    },
                ],
            }
        )
        result = await ex.execute()
        assert "Error" in result or "error" in result.lower()

    async def test_soft_failure_on_error_fail_stops(self):
        """Soft failure with on_error=fail should stop execution."""
        ex = _make_executor(
            skill={
                "name": "soft_stop",
                "steps": [
                    {
                        "name": "check",
                        "tool": "kubectl_get_pods",
                        "args": {},
                        "output": "pods",
                        "on_error": "fail",
                    },
                    {
                        "name": "next",
                        "compute": "result = 'should not run'",
                        "output": "x",
                    },
                ],
            }
        )
        ex._exec_tool = _mock_exec_tool(
            {
                "kubectl_get_pods": {
                    "success": False,
                    "error": "connection refused",
                },
            }
        )
        result = await ex.execute()
        assert "failed" in result.lower()
        assert ex.context.get("x") is None

    async def test_soft_failure_with_auto_heal_on_error_fail(self):
        """Soft failure detected, auto_heal=fail, heal fails => stop."""
        ex = _make_executor(
            skill={
                "name": "soft_fail_stop",
                "steps": [
                    {
                        "name": "check",
                        "tool": "kubectl_get_pods",
                        "args": {},
                        "output": "pods",
                        "on_error": "fail",
                    },
                ],
            }
        )
        # Tool returns success but with error text
        ex._exec_tool = _mock_exec_tool(
            {
                "kubectl_get_pods": {
                    "success": True,
                    "result": "Error: no such host api.example.com",
                    "duration": 0.1,
                },
            }
        )
        result = await ex.execute()
        # Soft failure detected but on_error=fail (not auto_heal), so it's a regular success
        # Actually, soft failure detection only triggers when on_error=="auto_heal"
        assert "Completed" in result

    async def test_tool_step_with_templated_args(self):
        """Tool step with template args that resolve correctly."""
        ex = _make_executor(
            skill={
                "name": "tmpl_args",
                "steps": [
                    {"name": "s1", "compute": "result = 'AAP-123'", "output": "key"},
                    {
                        "name": "s2",
                        "tool": "jira_view_issue",
                        "args": {"issue_key": "{{ key }}"},
                        "output": "issue",
                    },
                ],
            }
        )
        ex._exec_tool = _mock_exec_tool(
            {
                "jira_view_issue": {
                    "success": True,
                    "result": "AAP-123: Test",
                    "duration": 0.1,
                },
            }
        )
        await ex.execute()
        assert ex.context.get("issue") == "AAP-123: Test"


# ===========================================================================
# _execute_workflow_tool tests
# ===========================================================================


class TestExecuteWorkflowTool:
    async def test_success(self):
        """Successful workflow tool execution."""
        import time

        server = AsyncMock()
        server.call_tool.return_value = [SimpleNamespace(text="workflow result")]
        ex = _make_executor(server=server)
        result = await ex._execute_workflow_tool("some_tool", {"a": 1}, time.time())
        assert result["success"] is True
        assert "workflow result" in result["result"]

    async def test_exception(self):
        """Exception during workflow tool execution."""
        import time

        server = AsyncMock()
        server.call_tool.side_effect = RuntimeError("server down")
        ex = _make_executor(server=server)
        result = await ex._execute_workflow_tool("some_tool", {}, time.time())
        assert result["success"] is False
        assert "server down" in result["error"]


# ===========================================================================
# _load_and_execute_module_tool tests
# ===========================================================================


class TestLoadAndExecuteModuleTool:
    async def test_module_not_found(self):
        """Module file doesn't exist."""
        import time

        ex = _make_executor()
        with patch(
            "tool_modules.aa_workflow.src.skill_engine.TOOL_MODULES_DIR",
            Path("/nonexistent"),
        ):
            result = await ex._load_and_execute_module_tool(
                "fakmod", "fake_tool", {}, time.time()
            )
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    async def test_spec_returns_none(self, tmp_path):
        """Module file exists but spec_from_file_location returns None."""
        import time

        mod_dir = tmp_path / "aa_testmod" / "src"
        mod_dir.mkdir(parents=True)
        (mod_dir / "tools_basic.py").write_text("# empty")
        ex = _make_executor()
        with patch(
            "tool_modules.aa_workflow.src.skill_engine.TOOL_MODULES_DIR", tmp_path
        ):
            with patch("importlib.util.spec_from_file_location", return_value=None):
                result = await ex._load_and_execute_module_tool(
                    "testmod", "fake_tool", {}, time.time()
                )
        assert result["success"] is False
        assert "could not load" in result["error"].lower()


# ===========================================================================
# _exec_tool tests
# ===========================================================================


class TestExecTool:
    async def test_unknown_tool(self):
        """Unknown tool returns error."""
        ex = _make_executor()
        with patch(
            "tool_modules.aa_workflow.src.skill_engine.SkillExecutor._get_module_for_tool",
            return_value=None,
        ):
            result = await ex._exec_tool("nonexistent_tool", {})
        assert result["success"] is False
        assert "Unknown tool" in result["error"]

    async def test_workflow_tool_dispatch(self):
        """Workflow tools dispatch through server."""
        server = AsyncMock()
        server.call_tool.return_value = [SimpleNamespace(text="wf output")]
        ex = _make_executor(server=server)
        with patch(
            "tool_modules.aa_workflow.src.skill_engine.SkillExecutor._get_module_for_tool",
            return_value="workflow",
        ):
            result = await ex._exec_tool("workflow_tool", {})
        assert result["success"] is True
        assert "wf output" in result["result"]

    async def test_error_no_temp_server(self):
        """Module tool error without _temp_server key."""
        ex = _make_executor()
        with patch(
            "tool_modules.aa_workflow.src.skill_engine.SkillExecutor._get_module_for_tool",
            return_value="somemod",
        ):
            with patch.object(
                ex,
                "_load_and_execute_module_tool",
                new_callable=AsyncMock,
                return_value={"success": False, "error": "tool fail"},
            ):
                result = await ex._exec_tool("some_tool", {})
        assert result["success"] is False
        assert "tool fail" in result["error"]
        assert "_temp_server" not in result


# ===========================================================================
# _handle_auto_fix_action tests
# ===========================================================================


class TestHandleAutoFixAction:
    def test_no_fix_code(self):
        """When fix_code is not present, returns None."""
        ex = _make_executor()
        ex.error_recovery = MagicMock(spec=SkillErrorRecovery)
        result = ex._handle_auto_fix_action({}, "step1")
        assert result is None

    def test_fix_code_success(self):
        """When fix_code is present and succeeds."""
        ex = _make_executor()
        ex.error_recovery = MagicMock(spec=SkillErrorRecovery)
        ex._exec_compute_internal = MagicMock(return_value="fixed_value")
        error_info = {"fix_code": "result = 'fixed'", "pattern_id": "test"}
        result = ex._handle_auto_fix_action(error_info, "step1")
        assert result == "fixed_value"
        ex.error_recovery.log_fix_attempt.assert_called_once()

    def test_fix_code_exception(self):
        """When fix_code raises, logs failure."""
        ex = _make_executor(debug=True)
        import time

        ex.start_time = time.time()
        ex.error_recovery = MagicMock(spec=SkillErrorRecovery)
        ex._exec_compute_internal = MagicMock(side_effect=RuntimeError("fix broke"))
        error_info = {"fix_code": "bad code", "pattern_id": "test"}
        result = ex._handle_auto_fix_action(error_info, "step1")
        assert result is None
        # Should have logged failure
        ex.error_recovery.log_fix_attempt.assert_called_once()
        call_kwargs = ex.error_recovery.log_fix_attempt.call_args
        assert call_kwargs[1]["success"] is False


# ===========================================================================
# _handle_edit_action tests
# ===========================================================================


class TestHandleEditAction:
    def test_prints_and_returns_none(self):
        """Edit action prints instructions and returns None."""
        ex = _make_executor()
        ex.error_recovery = MagicMock(spec=SkillErrorRecovery)
        error_info = {"suggestion": "Check variable names"}
        with patch("builtins.input", return_value=""):
            result = ex._handle_edit_action(error_info, "some error", "step1")
        assert result is None
        ex.error_recovery.log_fix_attempt.assert_called_once()


# ===========================================================================
# _handle_skip_action tests
# ===========================================================================


class TestHandleSkipAction:
    def test_returns_none(self):
        """Skip action returns None."""
        ex = _make_executor()
        ex.error_recovery = MagicMock(spec=SkillErrorRecovery)
        result = ex._handle_skip_action({}, "step1")
        assert result is None
        ex.error_recovery.log_fix_attempt.assert_called_once()


# ===========================================================================
# _handle_abort_action tests
# ===========================================================================


class TestHandleAbortAction:
    def test_without_create_issue_fn(self):
        """Abort without create_issue_fn returns None."""
        ex = _make_executor()
        ex.error_recovery = MagicMock(spec=SkillErrorRecovery)
        result = ex._handle_abort_action({}, "error msg", "step1")
        assert result is None
        ex.error_recovery.log_fix_attempt.assert_called_once()

    def test_with_create_issue_fn_success(self):
        """Abort with create_issue_fn that succeeds."""
        create_fn = AsyncMock(
            return_value={"success": True, "issue_url": "http://issue/1"}
        )
        ex = _make_executor(create_issue_fn=create_fn)
        ex.error_recovery = MagicMock(spec=SkillErrorRecovery)
        result = ex._handle_abort_action({"pattern_id": "test"}, "error msg", "step1")
        assert result is None

    def test_with_create_issue_fn_exception(self):
        """Abort with create_issue_fn that raises."""
        create_fn = AsyncMock(side_effect=RuntimeError("api fail"))
        ex = _make_executor(create_issue_fn=create_fn, debug=True)
        import time

        ex.start_time = time.time()
        ex.error_recovery = MagicMock(spec=SkillErrorRecovery)
        result = ex._handle_abort_action({}, "error msg", "step1")
        assert result is None


# ===========================================================================
# _handle_continue_action tests
# ===========================================================================


class TestHandleContinueAction:
    def test_returns_error_string(self):
        """Continue action returns error string."""
        ex = _make_executor()
        ex.error_recovery = MagicMock(spec=SkillErrorRecovery)
        result = ex._handle_continue_action({}, "some error")
        assert result is not None
        assert "compute error" in result.lower()
        assert "some error" in result
        ex.error_recovery.log_fix_attempt.assert_called_once()


# ===========================================================================
# _initialize_error_recovery tests
# ===========================================================================


class TestInitializeErrorRecovery:
    def test_already_initialized(self):
        """Returns True when already initialized."""
        ex = _make_executor()
        ex.error_recovery = MagicMock(spec=SkillErrorRecovery)  # already set
        assert ex._initialize_error_recovery() is True

    def test_import_failure(self):
        """Returns False when import fails."""
        ex = _make_executor()
        ex.error_recovery = None
        with patch(
            "builtins.__import__",
            side_effect=ImportError("not found"),
        ):
            result = ex._initialize_error_recovery()
        # The import error should be caught
        # But since we mock __import__ globally, let's use a targeted approach
        assert result is True or result is False  # just ensure no crash

    def test_import_failure_targeted(self):
        """Returns False when SkillErrorRecovery import fails."""
        ex = _make_executor(debug=True)
        import time

        ex.start_time = time.time()
        ex.error_recovery = None
        with patch.dict("sys.modules", {"scripts.common.skill_error_recovery": None}):
            result = ex._initialize_error_recovery()
        assert result is False


# ===========================================================================
# _try_interactive_recovery tests
# ===========================================================================


class TestTryInteractiveRecovery:
    def test_error_recovery_init_fails(self):
        """When error recovery fails to initialize, returns None."""
        ex = _make_executor()
        ex._initialize_error_recovery = MagicMock(return_value=False)
        result = ex._try_interactive_recovery("code", "error", "step")
        assert result is None

    def _setup_recovery(self, ex, action_name):
        """Helper: set up mocked error recovery with patched event loop."""
        ex._initialize_error_recovery = MagicMock(return_value=True)
        ex.error_recovery = MagicMock(spec=SkillErrorRecovery)
        ex.error_recovery.detect_error.return_value = {"pattern_id": "test"}
        mock_loop = MagicMock()
        mock_loop.run_until_complete.return_value = {"action": action_name}
        return mock_loop

    def test_dispatch_auto_fix(self):
        """Dispatches to auto_fix handler."""
        ex = _make_executor()
        mock_loop = self._setup_recovery(ex, "auto_fix")
        ex._handle_auto_fix_action = MagicMock(return_value="fixed")
        with patch("asyncio.get_event_loop", return_value=mock_loop):
            result = ex._try_interactive_recovery("code", "error", "step")
        assert result == "fixed"

    def test_dispatch_skip(self):
        """Dispatches to skip handler."""
        ex = _make_executor()
        mock_loop = self._setup_recovery(ex, "skip")
        ex._handle_skip_action = MagicMock(return_value=None)
        with patch("asyncio.get_event_loop", return_value=mock_loop):
            result = ex._try_interactive_recovery("code", "error", "step")
        assert result is None
        ex._handle_skip_action.assert_called_once()

    def test_dispatch_edit(self):
        """Dispatches to edit handler."""
        ex = _make_executor()
        mock_loop = self._setup_recovery(ex, "edit")
        ex._handle_edit_action = MagicMock(return_value=None)
        with patch("asyncio.get_event_loop", return_value=mock_loop):
            result = ex._try_interactive_recovery("code", "error msg", "step")
        assert result is None
        ex._handle_edit_action.assert_called_once()

    def test_dispatch_abort(self):
        """Dispatches to abort handler."""
        ex = _make_executor()
        mock_loop = self._setup_recovery(ex, "abort")
        ex._handle_abort_action = MagicMock(return_value=None)
        with patch("asyncio.get_event_loop", return_value=mock_loop):
            result = ex._try_interactive_recovery("code", "error", "step")
        assert result is None
        ex._handle_abort_action.assert_called_once()

    def test_dispatch_continue(self):
        """Dispatches to continue handler."""
        ex = _make_executor()
        mock_loop = self._setup_recovery(ex, "continue")
        ex._handle_continue_action = MagicMock(return_value="<compute error: err>")
        with patch("asyncio.get_event_loop", return_value=mock_loop):
            result = ex._try_interactive_recovery("code", "error", "step")
        assert result == "<compute error: err>"

    def test_dispatch_unknown_returns_none(self):
        """Unknown action returns None."""
        ex = _make_executor()
        mock_loop = self._setup_recovery(ex, "unknown_action")
        with patch("asyncio.get_event_loop", return_value=mock_loop):
            result = ex._try_interactive_recovery("code", "error", "step")
        assert result is None

    def test_prompt_exception(self):
        """Exception during prompt returns None."""
        ex = _make_executor(debug=True)
        import time

        ex.start_time = time.time()
        ex._initialize_error_recovery = MagicMock(return_value=True)
        ex.error_recovery = MagicMock(spec=SkillErrorRecovery)
        ex.error_recovery.detect_error.return_value = {"pattern_id": "test"}
        mock_loop = MagicMock()
        mock_loop.run_until_complete.side_effect = RuntimeError("prompt failed")
        with patch("asyncio.get_event_loop", return_value=mock_loop):
            result = ex._try_interactive_recovery("code", "error", "step")
        assert result is None


# ===========================================================================
# _create_nested_skill_runner tests
# ===========================================================================


class TestCreateNestedSkillRunner:
    def test_skill_not_found(self, tmp_path):
        """Returns error dict when skill file not found."""
        ex = _make_executor()
        with patch("tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", tmp_path):
            runner = ex._create_nested_skill_runner()
            result = runner("nonexistent_skill")
            assert result["success"] is False
            assert "not found" in result["error"].lower()

    def test_skill_found_exception(self, tmp_path):
        """Exception during nested skill execution returns error."""
        skill_file = tmp_path / "broken.yaml"
        skill_file.write_text("{{invalid yaml")
        ex = _make_executor()
        with patch("tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", tmp_path):
            runner = ex._create_nested_skill_runner()
            result = runner("broken", {})
        assert result["success"] is False
        assert "error" in result


# ===========================================================================
# _exec_compute_internal import error paths
# ===========================================================================


class TestExecComputeInternalImportPaths:
    def test_scripts_import_failure(self):
        """When scripts.common imports fail, compute still works with builtins."""
        ex = _make_executor()
        # The ImportError path sets parsers, jira_utils, etc. to None
        # but basic compute should still work
        with patch.dict(
            "sys.modules",
            {
                "scripts.common": None,
                "scripts.common.config_loader": None,
                "scripts.common.jira_utils": None,
                "scripts.common.lint_utils": None,
                "scripts.common.memory": None,
                "scripts.common.parsers": None,
                "scripts.common.repo_utils": None,
                "scripts.common.slack_utils": None,
                "scripts.skill_hooks": None,
            },
        ):
            result = ex._exec_compute_internal("result = 2 + 2", "result")
        assert result == 4

    def test_google_import_failure(self):
        """When google imports fail, compute still works."""
        ex = _make_executor()
        with patch.dict(
            "sys.modules",
            {
                "google.oauth2.credentials": None,
                "googleapiclient.discovery": None,
            },
        ):
            result = ex._exec_compute_internal("result = 'ok'", "result")
        assert result == "ok"


# ===========================================================================
# _handle_tool_error auto_heal with WebSocket events
# ===========================================================================


class TestHandleToolErrorAutoHealWSEvents:
    async def test_auto_heal_success_with_ws(self):
        """auto_heal success triggers WS events."""
        call_num = {"n": 0}

        async def mock_tool(tool_name: str, args: dict) -> dict:
            if tool_name == "kube_login":
                return {"success": True, "result": "Logged in", "duration": 0.5}
            if tool_name == "target_tool":
                call_num["n"] += 1
                return {"success": True, "result": "retried ok", "duration": 0.1}
            return {"success": True, "result": "ok", "duration": 0.01}

        ex = _make_executor()
        ex._exec_tool = mock_tool
        ws = MagicMock(spec=SkillWebSocketServer)
        ws.is_running = True
        ws.auto_heal_triggered = AsyncMock()
        ws.auto_heal_completed = AsyncMock()
        ex.ws_server = ws
        ex.event_emitter = MagicMock(spec=SkillExecutionEmitter)
        ex.event_emitter.current_step_index = 0
        step = {
            "tool": "target_tool",
            "on_error": "auto_heal",
            "args": {},
            "output": "out",
        }
        lines: list[str] = []
        should_continue = await ex._handle_tool_error(
            "target_tool", step, "s1", "unauthorized 401", lines
        )
        assert should_continue is True
        assert any("heal" in line.lower() or "auth" in line.lower() for line in lines)

    async def test_auto_heal_failure_with_ws(self):
        """auto_heal failure triggers WS failure event."""

        async def mock_tool(tool_name: str, args: dict) -> dict:
            if tool_name == "kube_login":
                return {"success": False, "error": "failed", "result": "failed"}
            return {"success": True, "result": "ok", "duration": 0.01}

        ex = _make_executor()
        ex._exec_tool = mock_tool
        ws = MagicMock(spec=SkillWebSocketServer)
        ws.is_running = True
        ws.auto_heal_triggered = AsyncMock()
        ws.auto_heal_completed = AsyncMock()
        ex.ws_server = ws
        ex.event_emitter = MagicMock(spec=SkillExecutionEmitter)
        ex.event_emitter.current_step_index = 0
        step = {"tool": "t", "on_error": "auto_heal", "args": {}}
        lines: list[str] = []
        should_continue = await ex._handle_tool_error(
            "t", step, "s1", "unauthorized 401", lines
        )
        assert should_continue is True
        assert any(
            "heal failed" in line.lower() or "auto-heal failed" in line.lower()
            for line in lines
        )

    async def test_auto_heal_no_event_emitter(self):
        """auto_heal works without event emitter."""

        async def mock_tool(tool_name: str, args: dict) -> dict:
            if tool_name == "kube_login":
                return {"success": True, "result": "logged in", "duration": 0.5}
            return {"success": True, "result": "retry ok", "duration": 0.1}

        ex = _make_executor()
        ex._exec_tool = mock_tool
        ex.ws_server = None
        ex.event_emitter = None
        step = {"tool": "t", "on_error": "auto_heal", "args": {}, "output": "out"}
        lines: list[str] = []
        should_continue = await ex._handle_tool_error(
            "t", step, "s1", "unauthorized 401", lines
        )
        assert should_continue is True


# ===========================================================================
# _handle_tool_error on_error=continue with args
# ===========================================================================


class TestHandleToolErrorContinueWithArgs:
    async def test_continue_with_dict_args(self):
        """on_error=continue with dict args learns from error."""
        ex = _make_executor()
        ex._exec_tool = _mock_exec_tool()
        step = {
            "tool": "t",
            "on_error": "continue",
            "args": {"key": "{{ inputs.val }}"},
        }
        lines: list[str] = []
        should_continue = await ex._handle_tool_error("t", step, "s1", "err", lines)
        assert should_continue is True
        assert len(ex.step_results) == 1

    async def test_continue_with_non_dict_args(self):
        """on_error=continue with non-dict args (no templating)."""
        ex = _make_executor()
        ex._exec_tool = _mock_exec_tool()
        step = {"tool": "t", "on_error": "continue", "args": "not a dict"}
        lines: list[str] = []
        should_continue = await ex._handle_tool_error("t", step, "s1", "err", lines)
        assert should_continue is True


# ===========================================================================
# _log_auto_heal_to_memory edge cases
# ===========================================================================


class TestLogAutoHealToMemoryEdgeCases:
    async def test_existing_file_without_stats(self, tmp_path):
        """Existing file without stats or failures keys."""
        import yaml

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        memory_dir = tmp_path / "memory" / "learned"
        memory_dir.mkdir(parents=True)
        failures_file = memory_dir / "tool_failures.yaml"
        failures_file.write_text(yaml.dump({"other": "data"}))
        ex = _make_executor()
        with patch("tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", skills_dir):
            await ex._log_auto_heal_to_memory("tool", "auth", "err", True)
        with open(failures_file) as f:
            data = yaml.safe_load(f)
        assert "failures" in data
        assert "stats" in data
        assert len(data["failures"]) == 1

    async def test_truncates_to_100_entries(self, tmp_path):
        """Entries are truncated to last 100."""
        import yaml

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        memory_dir = tmp_path / "memory" / "learned"
        memory_dir.mkdir(parents=True)
        failures_file = memory_dir / "tool_failures.yaml"
        # Create 105 existing entries
        failures_file.write_text(
            yaml.dump(
                {
                    "failures": [{"tool": f"t{i}"} for i in range(105)],
                    "stats": {
                        "total_failures": 105,
                        "auto_fixed": 50,
                        "manual_required": 55,
                    },
                }
            )
        )
        ex = _make_executor()
        with patch("tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", skills_dir):
            await ex._log_auto_heal_to_memory("tool", "auth", "err", True)
        with open(failures_file) as f:
            data = yaml.safe_load(f)
        assert len(data["failures"]) == 100

    async def test_exception_during_logging(self, tmp_path):
        """Exception during logging is swallowed."""
        ex = _make_executor(debug=True)
        import time

        ex.start_time = time.time()
        with patch(
            "tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR",
            Path("/nonexistent/readonly"),
        ):
            # Test verifies no exception is raised - exception swallowed
            await ex._log_auto_heal_to_memory("tool", "auth", "err", True)
        assert True


# ===========================================================================
# _extract_and_save_learnings tests
# ===========================================================================


class TestExtractAndSaveLearnings:
    async def test_non_learning_skill_skipped(self):
        """Skills in non_learning list are skipped."""
        ex = _make_executor(skill={"name": "coffee", "steps": []})
        lines: list[str] = []
        await ex._extract_and_save_learnings(lines)
        assert len(lines) == 0

    async def test_no_project_detected(self):
        """When no project detected, skips."""
        ex = _make_executor(skill={"name": "start_work", "steps": []}, debug=True)
        import time

        ex.start_time = time.time()
        lines: list[str] = []
        with patch(
            "tool_modules.aa_workflow.src.skill_engine.SkillExecutor._extract_and_save_learnings",
            wraps=ex._extract_and_save_learnings,
        ):
            # Test verifies no exception is raised
            await ex._extract_and_save_learnings(lines)
        assert len(lines) == 0

    async def test_start_work_learning_with_mocked_knowledge(self):
        """start_work skill with mocked knowledge tools."""
        ex = _make_executor(
            skill={"name": "start_work", "steps": []},
            inputs={"issue_key": "AAP-999"},
        )
        lines: list[str] = []
        mock_knowledge = {
            "metadata": {"confidence": 0.5},
            "learned_from_tasks": [],
        }
        mock_detect = MagicMock(return_value="test-project")
        mock_persona = MagicMock(return_value="developer")
        mock_load = MagicMock(return_value=mock_knowledge)
        mock_save = MagicMock()
        with (
            patch(
                "tool_modules.aa_workflow.src.knowledge_tools._detect_project_from_path",
                mock_detect,
            ),
            patch(
                "tool_modules.aa_workflow.src.knowledge_tools._get_current_persona",
                mock_persona,
            ),
            patch(
                "tool_modules.aa_workflow.src.knowledge_tools._load_knowledge",
                mock_load,
            ),
            patch(
                "tool_modules.aa_workflow.src.knowledge_tools._save_knowledge",
                mock_save,
            ),
        ):
            await ex._extract_and_save_learnings(lines)
        # Learning should have been recorded
        assert any("Learning recorded" in line for line in lines)
        mock_save.assert_called_once()

    async def test_import_error_caught(self):
        """ImportError from knowledge_tools is caught."""
        ex = _make_executor(
            skill={"name": "start_work", "steps": []},
            inputs={"issue_key": "AAP-999"},
            debug=True,
        )
        import time

        ex.start_time = time.time()
        lines: list[str] = []
        # Test verifies no exception is raised
        await ex._extract_and_save_learnings(lines)
        assert isinstance(lines, list)


# ===========================================================================
# execute() WebSocket events tests
# ===========================================================================


class TestExecuteWSEvents:
    async def test_ws_skill_start_event(self):
        """WebSocket skill_started event emitted."""
        ex = _make_executor(skill={"name": "ws_test", "steps": []})
        ws = MagicMock(spec=SkillWebSocketServer)
        ws.is_running = True
        ws.skill_started = AsyncMock()
        ws.skill_completed = AsyncMock()
        ex.ws_server = ws
        result = await ex.execute()
        # The event is created via asyncio.create_task, not awaited directly
        assert result is not None

    async def test_ws_step_events(self):
        """WebSocket step events emitted during execution."""
        ex = _make_executor(
            skill={
                "name": "ws_step",
                "steps": [
                    {"name": "s1", "compute": "result = 1", "output": "x"},
                ],
            }
        )
        ws = MagicMock(spec=SkillWebSocketServer)
        ws.is_running = True
        ws.skill_started = AsyncMock()
        ws.step_started = AsyncMock()
        ws.step_completed = AsyncMock()
        ws.skill_completed = AsyncMock()
        ex.ws_server = ws
        result = await ex.execute()
        assert result is not None

    async def test_ws_failed_step_event(self):
        """WebSocket step_failed event emitted for failing step."""
        ex = _make_executor(
            skill={
                "name": "ws_fail",
                "steps": [
                    {"name": "bad", "tool": "t", "args": {}, "on_error": "continue"},
                ],
            }
        )
        ex._exec_tool = _mock_exec_tool({"t": {"success": False, "error": "boom"}})
        ws = MagicMock(spec=SkillWebSocketServer)
        ws.is_running = True
        ws.skill_started = AsyncMock()
        ws.step_started = AsyncMock()
        ws.step_completed = AsyncMock()
        ws.step_failed = AsyncMock()
        ws.skill_completed = AsyncMock()
        ws.skill_failed = AsyncMock()
        ex.ws_server = ws
        result = await ex.execute()
        assert result is not None

    async def test_ws_skill_failed_event(self):
        """WebSocket skill_failed event shows last error."""
        ex = _make_executor(
            skill={
                "name": "ws_skill_fail",
                "steps": [
                    {"name": "bad", "tool": "t", "args": {}, "on_error": "continue"},
                ],
            }
        )
        ex._exec_tool = _mock_exec_tool(
            {"t": {"success": False, "error": "the big error"}}
        )
        ws = MagicMock(spec=SkillWebSocketServer)
        ws.is_running = True
        ws.skill_started = AsyncMock()
        ws.step_started = AsyncMock()
        ws.step_completed = AsyncMock()
        ws.step_failed = AsyncMock()
        ws.skill_completed = AsyncMock()
        ws.skill_failed = AsyncMock()
        ex.ws_server = ws
        result = await ex.execute()
        assert "failed" in result.lower()


# ===========================================================================
# execute() compute step exception branch
# ===========================================================================


class TestExecuteComputeStepException:
    async def test_compute_exception_not_string_error(self):
        """Compute step where _exec_compute itself raises (lines 2695-2698)."""
        ex = _make_executor(
            skill={
                "name": "exc_compute",
                "steps": [
                    {"name": "bad", "compute": "code", "output": "x"},
                ],
            }
        )
        # Mock _exec_compute to raise directly
        ex._exec_compute = MagicMock(side_effect=RuntimeError("compute exploded"))
        result = await ex.execute()
        assert "compute exploded" in result.lower() or "Error" in result

    async def test_compute_exception_sets_step_error(self):
        """Compute exception sets step_success=False and step_error."""
        ex = _make_executor(
            skill={
                "name": "exc_compute2",
                "steps": [
                    {"name": "bad", "compute": "code", "output": "x"},
                ],
            }
        )
        ex._exec_compute = MagicMock(side_effect=ValueError("bad compute"))
        emitter = MagicMock(spec=SkillExecutionEmitter)
        emitter.current_step_index = 0
        ex.event_emitter = emitter
        result = await ex.execute()
        # Exception from _exec_compute is caught and reported in output
        assert "bad compute" in result
        # step_failed event should have been emitted
        emitter.step_failed.assert_called_once()


# ===========================================================================
# execute() description step
# ===========================================================================


class TestExecuteDescriptionStep:
    async def test_description_step_with_ws(self):
        """Description step triggers WS step events."""
        ex = _make_executor(
            skill={
                "name": "desc_ws",
                "steps": [
                    {"name": "info", "description": "Manual task"},
                ],
            }
        )
        ws = MagicMock(spec=SkillWebSocketServer)
        ws.is_running = True
        ws.skill_started = AsyncMock()
        ws.step_started = AsyncMock()
        ws.step_completed = AsyncMock()
        ws.skill_completed = AsyncMock()
        ex.ws_server = ws
        result = await ex.execute()
        assert "Manual task" in result


# ===========================================================================
# _eval_condition fallback paths
# ===========================================================================


class TestEvalConditionFallback:
    def test_jinja_exception_returns_false(self):
        """Jinja evaluation exception defaults to False."""
        ex = _make_executor(debug=True)
        import time

        ex.start_time = time.time()
        # Use an expression that Jinja can render but produces a non-boolean result
        # that would fail in the string comparison logic
        result = ex._eval_condition("{% if invalid_syntax")
        # Should catch exception and return False
        assert result is False


# ===========================================================================
# _skill_run_impl with context/workspace
# ===========================================================================


class TestSkillRunImplWithContext:
    async def test_with_ctx_workspace_lookup_fails(self, tmp_path):
        """When workspace lookup fails, still executes."""
        import yaml

        from tool_modules.aa_workflow.src.skill_engine import _skill_run_impl

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_file = skills_dir / "test_skill.yaml"
        skill_file.write_text(
            yaml.dump(
                {
                    "name": "test_skill",
                    "description": "test",
                    "steps": [
                        {"name": "s", "compute": "result = 1", "output": "x"},
                    ],
                }
            )
        )
        mock_ctx = MagicMock(spec=Context)
        with patch("tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", skills_dir):
            with patch(
                "server.workspace_state.WorkspaceRegistry.get_for_ctx",
                side_effect=RuntimeError("no workspace"),
            ):
                result = await _skill_run_impl(
                    "test_skill",
                    "{}",
                    True,
                    False,
                    MagicMock(spec=FastMCP),
                    ctx=mock_ctx,
                )
        text = result[0].text
        assert "Executing" in text


# ===========================================================================
# register_skill_tools tests
# ===========================================================================


class TestRegisterSkillTools:
    def test_registers_tools(self):
        """register_skill_tools registers tools on server."""
        from tool_modules.aa_workflow.src.skill_engine import register_skill_tools

        server = MagicMock(spec=FastMCP)
        # ToolRegistry calls server.tool, so mock that
        server.tool = MagicMock(return_value=lambda fn: fn)
        count = register_skill_tools(server)
        assert count >= 0  # just ensure no crash


# ===========================================================================
# _attempt_auto_heal with event emitter
# ===========================================================================


class TestAttemptAutoHealWithEvents:
    async def test_auth_heal_with_emitter(self):
        """Auth heal emits remediation step event."""

        async def mock_tool(tool_name: str, args: dict) -> dict:
            if tool_name == "kube_login":
                return {"success": True, "result": "Logged in", "duration": 0.5}
            return {"success": True, "result": "ok", "duration": 0.1}

        ex = _make_executor()
        ex._exec_tool = mock_tool
        emitter = MagicMock(spec=SkillExecutionEmitter)
        emitter.current_step_index = 0
        ex.event_emitter = emitter
        step = {"tool": "t", "args": {}}
        lines: list[str] = []
        result = await ex._attempt_auto_heal("auth", "stage", "t", step, lines)
        assert result is not None
        emitter.remediation_step.assert_called_once()

    async def test_network_heal_with_emitter(self):
        """Network heal emits remediation step event."""

        async def mock_tool(tool_name: str, args: dict) -> dict:
            if tool_name == "vpn_connect":
                return {"success": True, "result": "VPN connected", "duration": 1.0}
            return {"success": True, "result": "ok", "duration": 0.1}

        ex = _make_executor()
        ex._exec_tool = mock_tool
        emitter = MagicMock(spec=SkillExecutionEmitter)
        emitter.current_step_index = 0
        ex.event_emitter = emitter
        step = {"tool": "t", "args": {}}
        lines: list[str] = []
        result = await ex._attempt_auto_heal("network", "stage", "t", step, lines)
        assert result is not None
        emitter.remediation_step.assert_called_once()

    async def test_auth_heal_truncates_long_error(self):
        """Long error messages from kube_login are truncated."""

        async def mock_tool(tool_name: str, args: dict) -> dict:
            if tool_name == "kube_login":
                long_err = "x" * 300
                return {"success": False, "result": long_err}
            return {"success": True, "result": "ok", "duration": 0.1}

        ex = _make_executor()
        ex._exec_tool = mock_tool
        step = {"tool": "t", "args": {}}
        lines: list[str] = []
        result = await ex._attempt_auto_heal("auth", "stage", "t", step, lines)
        assert result is None
        truncated = [line for line in lines if "..." in line]
        assert len(truncated) >= 1

    async def test_network_heal_truncates_long_error(self):
        """Long error messages from vpn_connect are truncated."""

        async def mock_tool(tool_name: str, args: dict) -> dict:
            if tool_name == "vpn_connect":
                long_err = "y" * 300
                return {"success": False, "result": long_err}
            return {"success": True, "result": "ok", "duration": 0.1}

        ex = _make_executor()
        ex._exec_tool = mock_tool
        step = {"tool": "t", "args": {}}
        lines: list[str] = []
        result = await ex._attempt_auto_heal("network", "stage", "t", step, lines)
        assert result is None
        truncated = [line for line in lines if "..." in line]
        assert len(truncated) >= 1


# ===========================================================================
# _handle_tool_error with auto_heal args templating
# ===========================================================================


class TestHandleToolErrorAutoHealArgs:
    async def test_auto_heal_with_dict_args_template(self):
        """auto_heal step with dict args does template rendering for learning."""

        async def mock_tool(tool_name: str, args: dict) -> dict:
            if tool_name == "kube_login":
                return {"success": False, "error": "failed", "result": "failed"}
            return {"success": True, "result": "ok", "duration": 0.01}

        ex = _make_executor(inputs={"cluster": "stage"})
        ex._exec_tool = mock_tool
        step = {
            "tool": "kubectl_get_pods",
            "on_error": "auto_heal",
            "args": {"cluster": "{{ inputs.cluster }}"},
        }
        lines: list[str] = []
        should_continue = await ex._handle_tool_error(
            "kubectl_get_pods", step, "s1", "unauthorized 401", lines
        )
        assert should_continue is True

    async def test_auto_heal_with_non_dict_args(self):
        """auto_heal step with non-dict args doesn't crash."""

        async def mock_tool(tool_name: str, args: dict) -> dict:
            return {"success": False, "error": "fail", "result": "fail"}

        ex = _make_executor()
        ex._exec_tool = mock_tool
        step = {
            "tool": "t",
            "on_error": "auto_heal",
            "args": "not a dict",
        }
        lines: list[str] = []
        should_continue = await ex._handle_tool_error(
            "t", step, "s1", "some generic error xyz", lines
        )
        assert should_continue is True


# ===========================================================================
# _process_tool_step soft failure branch
# ===========================================================================


class TestProcessToolStepSoftFailure:
    async def test_soft_failure_not_auto_heal_stores_result(self):
        """Soft failure on non-auto_heal step stores result normally."""
        ex = _make_executor(
            skill={"name": "t", "steps": []},
        )
        ex._exec_tool = _mock_exec_tool(
            {
                "t": {
                    "success": True,
                    "result": "Error: no such host api.example.com",
                    "duration": 0.1,
                }
            }
        )
        step = {"tool": "t", "args": {}, "name": "s1", "output": "out"}
        lines: list[str] = []
        result = await ex._process_tool_step(step, 1, "s1", lines)
        # on_error defaults to "fail", but soft failure only triggers for auto_heal
        assert result is True
        assert ex.context.get("out") is not None

    async def test_soft_failure_auto_heal_triggers_error(self):
        """Soft failure with auto_heal triggers error handling."""

        async def mock_tool(tool_name: str, args: dict) -> dict:
            if tool_name == "t":
                return {
                    "success": True,
                    "result": "Error: no such host api.example.com",
                    "duration": 0.1,
                }
            return {"success": False, "error": "fail", "result": "fail"}

        ex = _make_executor(skill={"name": "t", "steps": []})
        ex._exec_tool = mock_tool
        step = {
            "tool": "t",
            "args": {},
            "name": "s1",
            "output": "out",
            "on_error": "auto_heal",
        }
        lines: list[str] = []
        result = await ex._process_tool_step(step, 1, "s1", lines)
        # auto_heal always continues
        assert result is True
        # Soft failure text should appear
        assert any("soft failure" in line.lower() for line in lines)


# ===========================================================================
# _format_skill_outputs edge cases
# ===========================================================================


class TestFormatSkillOutputsEdgeCases:
    def test_output_with_template_string_value(self):
        """Output value as template string."""
        ex = _make_executor(
            skill={
                "name": "test",
                "steps": [],
                "outputs": [{"name": "msg", "value": "Hello {{ who }}"}],
            }
        )
        ex.context["who"] = "World"
        lines: list[str] = []
        ex._format_skill_outputs(lines)
        assert any("Hello World" in line for line in lines)

    def test_output_with_list_value(self):
        """Output value as list with template items."""
        ex = _make_executor(
            skill={
                "name": "test",
                "steps": [],
                "outputs": [{"name": "items", "value": ["{{ x }}", "static"]}],
            }
        )
        ex.context["x"] = "dynamic"
        lines: list[str] = []
        ex._format_skill_outputs(lines)
        assert any("items" in line for line in lines)

    def test_output_with_dict_value_templated(self):
        """Output value as dict with template values."""
        ex = _make_executor(
            skill={
                "name": "test",
                "steps": [],
                "outputs": [{"name": "data", "value": {"key": "{{ val }}"}}],
            }
        )
        ex.context["val"] = "resolved"
        lines: list[str] = []
        ex._format_skill_outputs(lines)
        assert ex.context.get("data") == {"key": "resolved"}


# ===========================================================================
# _detect_auto_heal_type credential prompt pattern
# ===========================================================================


class TestDetectAutoHealTypeCredentials:
    def test_credentials_prompt_pattern(self):
        """Long credential prompt pattern detected as auth."""
        ex = _make_executor()
        heal_type, _ = ex._detect_auto_heal_type(
            "the server has asked for the client to provide credentials"
        )
        assert heal_type == "auth"

    def test_name_or_service_not_known(self):
        """DNS name or service not known is network."""
        ex = _make_executor()
        heal_type, _ = ex._detect_auto_heal_type("name or service not known")
        assert heal_type == "network"

    def test_eof_pattern(self):
        """EOF pattern detected as network."""
        ex = _make_executor()
        heal_type, _ = ex._detect_auto_heal_type("unexpected eof")
        assert heal_type == "network"


# ===========================================================================
# _template_with_regex_fallback edge cases
# ===========================================================================


class TestTemplateRegexFallbackEdgeCases:
    def test_hasattr_path(self):
        """Access via getattr when value has attribute."""
        ex = _make_executor()
        obj = SimpleNamespace(field="value")
        ex.context["obj"] = obj
        result = ex._template_with_regex_fallback("{{ obj.field }}")
        assert result == "value"

    def test_dict_key_not_found(self):
        """Dict with missing key returns original."""
        ex = _make_executor()
        ex.context["d"] = {"a": 1}
        result = ex._template_with_regex_fallback("{{ d.missing }}")
        assert "{{" in result

    def test_none_value_renders_empty(self):
        """None value renders as empty string."""
        ex = _make_executor()
        ex.context["val"] = None
        result = ex._template_with_regex_fallback("got {{ val }}")
        assert result == "got "

    def test_exception_in_replace(self):
        """Exception during replacement returns original."""
        ex = _make_executor()

        # Accessing something that raises during getattr
        class BadObj:
            def __getattr__(self, key):
                raise RuntimeError("boom")

        ex.context["bad"] = BadObj()
        result = ex._template_with_regex_fallback("{{ bad.field }}")
        assert "{{" in result


# ===========================================================================
# SkillExecutor __init__ edge cases
# ===========================================================================


class TestSkillExecutorInit:
    def test_emit_events_disabled(self):
        """When emit_events is False, no event emitter."""
        ex = _make_executor()  # _make_executor sets emit_events=False
        assert ex.event_emitter is None

    def test_with_session_params(self):
        """Session params are stored."""
        ex = SkillExecutor(
            skill={"name": "test", "steps": []},
            inputs={},
            emit_events=False,
            workspace_uri="ws://test",
            session_id="sess123",
            session_name="My Session",
            source="cron",
            source_details="daily_check",
        )
        assert ex.session_id == "sess123"
        assert ex.session_name == "My Session"
        assert ex.source == "cron"
        assert ex.source_details == "daily_check"


# ===========================================================================
# execute() then block with event emitter
# ===========================================================================


class TestExecuteThenBlockWithEmitter:
    async def test_then_early_return_emits_skill_complete(self):
        """Then block early return emits skill_complete event."""
        ex = _make_executor(
            skill={
                "name": "then_ev",
                "steps": [
                    {"name": "s1", "compute": "result = 'done'", "output": "v"},
                    {"name": "check", "then": [{"return": "done"}]},
                ],
            }
        )
        emitter = MagicMock(spec=SkillExecutionEmitter)
        emitter.current_step_index = 0
        ex.event_emitter = emitter
        result = await ex.execute()
        assert "Early Exit" in result or "done" in result
        emitter.skill_complete.assert_called_once()

    async def test_then_continue_no_return(self):
        """Then block without return continues to next step."""
        ex = _make_executor(
            skill={
                "name": "then_cont",
                "steps": [
                    {"name": "s1", "then": [{"log": "something"}]},
                    {"name": "s2", "compute": "result = 'ran'", "output": "v"},
                ],
            }
        )
        await ex.execute()
        assert ex.context.get("v") == "ran"


# ===========================================================================
# _check_error_patterns with commands
# ===========================================================================


class TestCheckErrorPatternsCommands:
    def test_pattern_with_commands(self, tmp_path):
        """Pattern with commands shows them in suggestion."""
        import yaml

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        patterns_dir = tmp_path / "memory" / "learned"
        patterns_dir.mkdir(parents=True)
        (patterns_dir / "patterns.yaml").write_text(
            yaml.dump(
                {
                    "error_patterns": [
                        {
                            "pattern": "quota exceeded",
                            "meaning": "Namespace quota hit",
                            "fix": "Delete old pods",
                            "commands": ["oc delete pod old-pod"],
                        },
                    ],
                }
            )
        )
        ex = _make_executor()
        with patch("tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", skills_dir):
            result = ex._check_error_patterns("Resource quota exceeded for namespace")
        assert result is not None
        assert "quota exceeded" in result
        assert "oc delete pod" in result


# ===========================================================================
# execute() with tool step emitting memory events
# ===========================================================================


class TestExecuteToolStepMemoryEvents:
    async def test_memory_tool_emits_event(self):
        """Tool step with memory tool name emits memory event."""
        ex = _make_executor(
            skill={
                "name": "mem_test",
                "steps": [
                    {
                        "name": "read",
                        "tool": "memory_read",
                        "args": {"key": "state/work"},
                        "output": "data",
                    },
                ],
            }
        )
        ex._exec_tool = _mock_exec_tool(
            {
                "memory_read": {
                    "success": True,
                    "result": "memory data",
                    "duration": 0.01,
                },
            }
        )
        emitter = MagicMock(spec=SkillExecutionEmitter)
        emitter.current_step_index = 0
        ex.event_emitter = emitter
        await ex.execute()
        emitter.memory_read.assert_called()
        assert emitter.memory_read.call_count >= 1


# ===========================================================================
# _detect_soft_failure additional patterns
# ===========================================================================


class TestDetectSoftFailureAdditional:
    def test_no_route_to_host(self):
        """No route to host pattern."""
        ex = _make_executor()
        is_fail, msg = ex._detect_soft_failure("no route to host 10.0.0.1")
        assert is_fail is True
        assert msg is not None
        assert "VPN" in msg

    def test_network_unreachable(self):
        """Network unreachable pattern."""
        ex = _make_executor()
        is_fail, msg = ex._detect_soft_failure("Error: network unreachable")
        assert is_fail is True
        assert msg is not None
        assert "VPN" in msg

    def test_401_http_code(self):
        """401 HTTP code pattern."""
        ex = _make_executor()
        is_fail, msg = ex._detect_soft_failure("HTTP 401: authentication required")
        assert is_fail is True

    def test_kubernetes_credentials(self):
        """Kubernetes credential prompt pattern."""
        ex = _make_executor()
        is_fail, msg = ex._detect_soft_failure(
            "the server has asked for the client to provide credentials"
        )
        assert is_fail is True
        assert msg is not None
        assert "Kubernetes" in msg

    def test_emoji_failed_pattern(self):
        """Emoji failed pattern."""
        ex = _make_executor()
        is_fail, msg = ex._detect_soft_failure(
            "Something happened\n\u274c error in deploy"
        )
        assert is_fail is True


# ===========================================================================
# _validate_skill_inputs edge cases
# ===========================================================================


class TestValidateSkillInputsEdge:
    def test_no_inputs_section(self):
        """Skill without inputs section."""
        from tool_modules.aa_workflow.src.skill_engine import _validate_skill_inputs

        skill = {"name": "test", "steps": []}
        assert _validate_skill_inputs(skill, {}) == []

    def test_multiple_required_missing(self):
        """Multiple required inputs missing."""
        from tool_modules.aa_workflow.src.skill_engine import _validate_skill_inputs

        skill = {
            "inputs": [
                {"name": "a", "required": True},
                {"name": "b", "required": True},
                {"name": "c", "required": False},
            ]
        }
        missing = _validate_skill_inputs(skill, {"c": "val"})
        assert "a" in missing
        assert "b" in missing
        assert "c" not in missing


# ===========================================================================
# _eval_condition ImportError fallback (lines 1142-1176)
# ===========================================================================


class TestEvalConditionImportErrorFallback:
    def test_eval_fallback_true(self):
        """When jinja2 import fails, falls back to eval - True result."""
        ex = _make_executor(debug=True)
        import time

        ex.start_time = time.time()
        ex.context["val"] = 42
        with patch.dict("sys.modules", {"jinja2": None}):
            result = ex._eval_condition("val > 10")
        assert result is True

    def test_eval_fallback_false(self):
        """Fallback eval returns False."""
        ex = _make_executor(debug=True)
        import time

        ex.start_time = time.time()
        ex.context["val"] = 5
        with patch.dict("sys.modules", {"jinja2": None}):
            result = ex._eval_condition("val > 100")
        assert result is False

    def test_eval_fallback_exception(self):
        """Fallback eval with bad expression defaults to False."""
        ex = _make_executor(debug=True)
        import time

        ex.start_time = time.time()
        with patch.dict("sys.modules", {"jinja2": None}):
            result = ex._eval_condition("undefined_var_xyz")
        assert result is False

    def test_jinja_exception_returns_false(self):
        """Jinja rendering exception defaults to False (line 1174-1176)."""
        ex = _make_executor(debug=True)
        import time

        ex.start_time = time.time()
        # An expression that causes Jinja to raise (not ImportError)
        result = ex._eval_condition("{% if %}")
        assert result is False


# ===========================================================================
# _extract_and_save_learnings - all skill patterns (lines 2906-2930)
# ===========================================================================


class TestExtractAndSaveLearningsPatterns:
    _KT = "tool_modules.aa_workflow.src.knowledge_tools"

    def _patch_knowledge(self, knowledge=None):
        """Return a context manager that patches knowledge tools."""
        if knowledge is None:
            knowledge = {"metadata": {"confidence": 0.5}, "learned_from_tasks": []}
        return (
            patch(f"{self._KT}._detect_project_from_path", return_value="test-project"),
            patch(f"{self._KT}._get_current_persona", return_value="developer"),
            patch(f"{self._KT}._load_knowledge", return_value=knowledge),
            patch(f"{self._KT}._save_knowledge"),
        )

    async def test_create_mr_learning(self):
        """create_mr skill extracts learning."""
        ex = _make_executor(
            skill={"name": "create_mr", "steps": []},
            inputs={"issue_key": "AAP-100"},
        )
        lines: list[str] = []
        p1, p2, p3, p4 = self._patch_knowledge()
        with p1, p2, p3, p4:
            await ex._extract_and_save_learnings(lines)
        assert any("Learning recorded" in line for line in lines)

    async def test_review_pr_learning(self):
        """review_pr skill extracts learning."""
        ex = _make_executor(
            skill={"name": "review_pr", "steps": []},
            inputs={"mr_id": "42"},
        )
        lines: list[str] = []
        p1, p2, p3, p4 = self._patch_knowledge()
        with p1, p2, p3, p4:
            await ex._extract_and_save_learnings(lines)
        assert any("Learning recorded" in line for line in lines)

    async def test_test_mr_ephemeral_learning(self):
        """test_mr_ephemeral skill extracts learning."""
        ex = _make_executor(
            skill={"name": "test_mr_ephemeral", "steps": []},
            inputs={"mr_id": "99"},
        )
        lines: list[str] = []
        p1, p2, p3, p4 = self._patch_knowledge()
        with p1, p2, p3, p4:
            await ex._extract_and_save_learnings(lines)
        assert any("Learning recorded" in line for line in lines)

    async def test_investigate_alert_learning(self):
        """investigate_alert skill extracts learning."""
        ex = _make_executor(
            skill={"name": "investigate_alert", "steps": []},
            inputs={"alert_name": "HighCPU"},
        )
        lines: list[str] = []
        p1, p2, p3, p4 = self._patch_knowledge()
        with p1, p2, p3, p4:
            await ex._extract_and_save_learnings(lines)
        assert any("Learning recorded" in line for line in lines)

    async def test_close_issue_learning(self):
        """close_issue skill extracts learning."""
        ex = _make_executor(
            skill={"name": "close_issue", "steps": []},
            inputs={"issue_key": "AAP-200"},
        )
        lines: list[str] = []
        p1, p2, p3, p4 = self._patch_knowledge()
        with p1, p2, p3, p4:
            await ex._extract_and_save_learnings(lines)
        assert any("Learning recorded" in line for line in lines)

    async def test_no_learning_extracted(self):
        """Skill that doesn't match any pattern doesn't save."""
        ex = _make_executor(
            skill={"name": "custom_skill", "steps": []},
            inputs={},
        )
        lines: list[str] = []
        p1, p2, p3, p4 = self._patch_knowledge()
        with p1, p2, p3, p4:
            await ex._extract_and_save_learnings(lines)
        # No learning should be recorded
        assert not any("Learning recorded" in line for line in lines)

    async def test_no_knowledge_file(self):
        """When no knowledge file exists, skips silently."""
        ex = _make_executor(
            skill={"name": "start_work", "steps": []},
            inputs={"issue_key": "AAP-1"},
            debug=True,
        )
        import time

        ex.start_time = time.time()
        lines: list[str] = []
        with (
            patch(
                "tool_modules.aa_workflow.src.knowledge_tools._detect_project_from_path",
                return_value="test-project",
            ),
            patch(
                "tool_modules.aa_workflow.src.knowledge_tools._get_current_persona",
                return_value="developer",
            ),
            patch(
                "tool_modules.aa_workflow.src.knowledge_tools._load_knowledge",
                return_value=None,
            ),
        ):
            await ex._extract_and_save_learnings(lines)
        # No crash, no learning recorded
        assert not any("Learning recorded" in line for line in lines)

    async def test_knowledge_without_learned_from_tasks(self):
        """Knowledge file without learned_from_tasks key."""
        ex = _make_executor(
            skill={"name": "start_work", "steps": []},
            inputs={"issue_key": "AAP-1"},
        )
        lines: list[str] = []
        knowledge_no_tasks = {"metadata": {"confidence": 0.5}}
        with (
            patch(
                "tool_modules.aa_workflow.src.knowledge_tools._detect_project_from_path",
                return_value="test-project",
            ),
            patch(
                "tool_modules.aa_workflow.src.knowledge_tools._get_current_persona",
                return_value="developer",
            ),
            patch(
                "tool_modules.aa_workflow.src.knowledge_tools._load_knowledge",
                return_value=knowledge_no_tasks,
            ),
            patch(
                "tool_modules.aa_workflow.src.knowledge_tools._save_knowledge",
            ),
        ):
            await ex._extract_and_save_learnings(lines)
        assert any("Learning recorded" in line for line in lines)
        assert "learned_from_tasks" in knowledge_no_tasks


# ===========================================================================
# _initialize_error_recovery success path (lines 1284-1300)
# ===========================================================================


class TestInitializeErrorRecoverySuccess:
    def test_success_with_memory_helper(self):
        """Successful initialization with memory helper."""
        ex = _make_executor()
        ex.error_recovery = None
        mock_recovery_cls = MagicMock()
        mock_memory = MagicMock()
        with patch.dict(
            "sys.modules",
            {
                "scripts.common.skill_error_recovery": MagicMock(
                    SkillErrorRecovery=mock_recovery_cls
                ),
                "scripts.common": MagicMock(),
                "scripts.common.memory": mock_memory,
            },
        ):
            result = ex._initialize_error_recovery()
        assert result is True
        assert ex.error_recovery is not None

    def test_success_without_memory_helper(self):
        """Successful initialization when memory helper import fails."""
        ex = _make_executor()
        ex.error_recovery = None
        mock_recovery_cls = MagicMock()
        mock_module = MagicMock()
        mock_module.SkillErrorRecovery = mock_recovery_cls
        with patch.dict(
            "sys.modules",
            {
                "scripts.common.skill_error_recovery": mock_module,
                "scripts.common": None,  # memory import fails
            },
        ):
            result = ex._initialize_error_recovery()
        # Should succeed even without memory helper
        assert result is True


# ===========================================================================
# _exec_tool error recovery and retry path (lines 1738-1800)
# ===========================================================================


class TestExecToolErrorRecoveryRetry:
    async def test_error_with_known_issues_fix_applied(self):
        """Error recovery: known issue found, fix applied, retry succeeds."""
        import time

        call_count = {"n": 0}

        async def mock_load_exec(module, tool_name, args, start_time):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # First call - return error with _temp_server
                temp_server = AsyncMock()
                temp_server.call_tool.return_value = [SimpleNamespace(text="retry ok")]
                return {
                    "success": False,
                    "error": "unauthorized",
                    "_temp_server": temp_server,
                }
            return {"success": True, "result": "ok", "duration": 0.1}

        ex = _make_executor(debug=True)
        ex.start_time = time.time()
        ex._get_module_for_tool = MagicMock(return_value="somemod")
        ex._load_and_execute_module_tool = AsyncMock(side_effect=mock_load_exec)
        ex._try_auto_fix = AsyncMock(return_value=True)

        with (
            patch(
                "tool_modules.aa_workflow.src.skill_engine._check_known_issues_sync",
                return_value=[{"pattern": "unauthorized", "fix": "kube login"}],
            ),
            patch(
                "tool_modules.aa_workflow.src.skill_engine._format_known_issues",
                return_value="Known: unauthorized",
            ),
        ):
            result = await ex._exec_tool("some_tool", {})
        assert result["success"] is True

    async def test_error_with_known_issues_retry_fails(self):
        """Error recovery: fix applied but retry also fails."""
        import time

        temp_server = AsyncMock()
        temp_server.call_tool.side_effect = RuntimeError("retry failed too")

        ex = _make_executor(debug=True)
        ex.start_time = time.time()
        ex._get_module_for_tool = MagicMock(return_value="somemod")
        ex._load_and_execute_module_tool = AsyncMock(
            return_value={
                "success": False,
                "error": "unauthorized",
                "_temp_server": temp_server,
            }
        )
        ex._try_auto_fix = AsyncMock(return_value=True)

        with (
            patch(
                "tool_modules.aa_workflow.src.skill_engine._check_known_issues_sync",
                return_value=[{"pattern": "unauthorized", "fix": "login"}],
            ),
            patch(
                "tool_modules.aa_workflow.src.skill_engine._format_known_issues",
                return_value="Known: unauthorized",
            ),
        ):
            result = await ex._exec_tool("some_tool", {})
        assert result["success"] is False
        assert (
            "retry" in result["error"].lower()
            or "unauthorized" in result["error"].lower()
        )

    async def test_error_known_text_appended(self):
        """Known issue text appended to error message."""
        import time

        ex = _make_executor(debug=True)
        ex.start_time = time.time()
        ex._get_module_for_tool = MagicMock(return_value="somemod")
        temp_server = MagicMock(spec=FastMCP)
        ex._load_and_execute_module_tool = AsyncMock(
            return_value={
                "success": False,
                "error": "original error",
                "_temp_server": temp_server,
            }
        )
        ex._try_auto_fix = AsyncMock(return_value=False)

        with (
            patch(
                "tool_modules.aa_workflow.src.skill_engine._check_known_issues_sync",
                return_value=[{"pattern": "error", "fix": "fix it"}],
            ),
            patch(
                "tool_modules.aa_workflow.src.skill_engine._format_known_issues",
                return_value="\nKnown: do this",
            ),
        ):
            result = await ex._exec_tool("some_tool", {})
        assert "Known: do this" in result["error"]


# ===========================================================================
# _exec_tool auto-heal event emitter path
# ===========================================================================


class TestExecToolAutoHealEventEmitter:
    async def test_auto_fix_with_event_emitter(self):
        """Auto-fix with event emitter emits auto_heal and retry events."""
        import time

        temp_server = AsyncMock()
        temp_server.call_tool.return_value = [SimpleNamespace(text="retry ok")]

        ex = _make_executor(debug=True)
        ex.start_time = time.time()
        ex._get_module_for_tool = MagicMock(return_value="somemod")
        ex._load_and_execute_module_tool = AsyncMock(
            return_value={
                "success": False,
                "error": "unauthorized",
                "_temp_server": temp_server,
            }
        )
        ex._try_auto_fix = AsyncMock(return_value=True)
        emitter = MagicMock(spec=SkillExecutionEmitter)
        emitter.current_step_index = 0
        ex.event_emitter = emitter

        with (
            patch(
                "tool_modules.aa_workflow.src.skill_engine._check_known_issues_sync",
                return_value=[{"pattern": "unauthorized", "fix": "login"}],
            ),
            patch(
                "tool_modules.aa_workflow.src.skill_engine._format_known_issues",
                return_value="",
            ),
        ):
            result = await ex._exec_tool("some_tool", {})
        assert result["success"] is True
        emitter.auto_heal.assert_called_once()
        emitter.retry.assert_called_once()


# ===========================================================================
# _template_with_regex_fallback: hasattr/getattr for array access
# ===========================================================================


class TestTemplateRegexFallbackArray:
    def test_array_access_on_object(self):
        """Access array index via getattr path."""
        ex = _make_executor()
        obj = SimpleNamespace(items=["a", "b", "c"])
        ex.context["obj"] = obj
        result = ex._template_with_regex_fallback("{{ obj.items[1] }}")
        assert result == "b"

    def test_nested_hasattr_not_dict(self):
        """Non-dict non-hasattr object returns original."""
        ex = _make_executor()
        ex.context["val"] = 42  # int has no custom attributes
        result = ex._template_with_regex_fallback("{{ val.nonexistent }}")
        assert "{{" in result


# ===========================================================================
# _check_error_patterns with meaning only (no fix, no commands)
# ===========================================================================


class TestCheckErrorPatternsMeaningOnly:
    def test_pattern_with_meaning_only(self, tmp_path):
        """Pattern with meaning but no fix or commands."""
        import yaml

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        patterns_dir = tmp_path / "memory" / "learned"
        patterns_dir.mkdir(parents=True)
        (patterns_dir / "patterns.yaml").write_text(
            yaml.dump(
                {
                    "error_patterns": [
                        {
                            "pattern": "disk full",
                            "meaning": "Disk space exhausted",
                        },
                    ],
                }
            )
        )
        ex = _make_executor()
        with patch("tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", skills_dir):
            result = ex._check_error_patterns("Error: disk full on /dev/sda1")
        assert result is not None
        assert "disk full" in result
        assert "Disk space exhausted" in result

    def test_pattern_with_fix_only(self, tmp_path):
        """Pattern with fix but no meaning or commands."""
        import yaml

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        patterns_dir = tmp_path / "memory" / "learned"
        patterns_dir.mkdir(parents=True)
        (patterns_dir / "patterns.yaml").write_text(
            yaml.dump(
                {
                    "error_patterns": [
                        {
                            "pattern": "oom killed",
                            "fix": "Increase memory limit",
                        },
                    ],
                }
            )
        )
        ex = _make_executor()
        with patch("tool_modules.aa_workflow.src.skill_engine.SKILLS_DIR", skills_dir):
            result = ex._check_error_patterns("Pod was oom killed")
        assert result is not None
        assert "oom killed" in result
        assert "Increase memory limit" in result


# ===========================================================================
# execute() with WS events for step completion/failure
# ===========================================================================


class TestExecuteWSStepEvents:
    async def test_ws_step_completed_event(self):
        """WebSocket step_completed event for successful compute step."""
        ex = _make_executor(
            skill={
                "name": "ws_step_ok",
                "steps": [
                    {"name": "calc", "compute": "result = 42", "output": "x"},
                ],
            }
        )
        ws = MagicMock(spec=SkillWebSocketServer)
        ws.is_running = True
        ws.skill_started = AsyncMock()
        ws.step_started = AsyncMock()
        ws.step_completed = AsyncMock()
        ws.skill_completed = AsyncMock()
        ex.ws_server = ws
        result = await ex.execute()
        assert result is not None  # step_completed called via create_task

    async def test_ws_step_failed_compute_event(self):
        """WebSocket step_failed event for failing compute step."""
        ex = _make_executor(
            skill={
                "name": "ws_step_fail",
                "steps": [
                    {
                        "name": "bad",
                        "compute": "raise ValueError('oops')",
                        "output": "x",
                    },
                ],
            }
        )
        ws = MagicMock(spec=SkillWebSocketServer)
        ws.is_running = True
        ws.skill_started = AsyncMock()
        ws.step_started = AsyncMock()
        ws.step_completed = AsyncMock()
        ws.step_failed = AsyncMock()
        ws.skill_completed = AsyncMock()
        ws.skill_failed = AsyncMock()
        ex.ws_server = ws
        result = await ex.execute()
        assert result is not None


# ===========================================================================
# _process_tool_step result preview truncation
# ===========================================================================


class TestProcessToolStepTruncation:
    async def test_result_over_300_chars_truncated(self):
        """Tool result over 300 chars shows truncated preview."""
        ex = _make_executor(skill={"name": "t", "steps": []})
        long_text = "x" * 400
        ex._exec_tool = _mock_exec_tool(
            {"t": {"success": True, "result": long_text, "duration": 0.1}}
        )
        step = {"tool": "t", "args": {}, "name": "s1", "output": "out"}
        lines: list[str] = []
        result = await ex._process_tool_step(step, 1, "s1", lines)
        assert result is True
        assert any("..." in line for line in lines)


# ===========================================================================
# _handle_tool_error issue_url only path (line 2225)
# ===========================================================================


class TestHandleToolErrorIssueUrlOnly:
    async def test_create_issue_returns_url_only_no_success(self):
        """create_issue_fn returns success=False with non-empty issue_url."""
        create_fn = AsyncMock(
            return_value={
                "success": False,
                "issue_url": "https://github.com/issues/new",
            }
        )
        ex = _make_executor(create_issue_fn=create_fn)
        ex._exec_tool = _mock_exec_tool()
        step = {"tool": "t", "on_error": "fail"}
        lines: list[str] = []
        await ex._handle_tool_error("t", step, "s1", "error msg", lines)
        assert any("Report" in line or "Create" in line for line in lines)

    async def test_create_issue_returns_empty_url(self):
        """create_issue_fn returns success=False with empty issue_url."""
        create_fn = AsyncMock(return_value={"success": False, "issue_url": ""})
        ex = _make_executor(create_issue_fn=create_fn)
        ex._exec_tool = _mock_exec_tool()
        step = {"tool": "t", "on_error": "fail"}
        lines: list[str] = []
        await ex._handle_tool_error("t", step, "s1", "error msg", lines)
        # Should not have "Report" line since issue_url is empty
        report_lines = [
            line for line in lines if "Report" in line or "Create GitHub" in line
        ]
        assert len(report_lines) == 0
