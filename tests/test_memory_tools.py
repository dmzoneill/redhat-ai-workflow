"""Tests for tool_modules.aa_workflow.src.memory_tools."""

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tool_modules.aa_workflow.src import memory_tools

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_memory_dir(tmp_path):
    """Create a temporary memory directory tree."""
    for sub in ("state", "learned", "sessions", "backups"):
        (tmp_path / sub).mkdir()
    (tmp_path / "state" / "projects").mkdir()
    with patch.object(memory_tools, "MEMORY_DIR", tmp_path):
        yield tmp_path


@pytest.fixture
def _seed_patterns(temp_memory_dir):
    """Write a patterns.yaml with sample data."""
    patterns = {
        "error_patterns": [
            {"pattern": "connection refused", "meaning": "host down", "fix": "restart"},
        ],
        "auth_patterns": [
            {"pattern": "token expired", "meaning": "stale token", "fix": "re-login"},
        ],
        "bonfire_patterns": [],
        "pipeline_patterns": [],
        "jira_cli_patterns": [
            {
                "pattern": "issue not found",
                "description": "bad key",
                "solution": "check key format",
            }
        ],
    }
    with open(temp_memory_dir / "learned" / "patterns.yaml", "w") as f:
        yaml.dump(patterns, f)


@pytest.fixture
def _seed_tool_fixes(temp_memory_dir):
    """Write tool_fixes.yaml with sample data."""
    data = {
        "tool_fixes": [
            {
                "tool_name": "bonfire_deploy",
                "error_pattern": "manifest unknown",
                "root_cause": "Short SHA",
                "fix_applied": "Use full SHA",
                "date_learned": "2025-01-01",
            }
        ]
    }
    with open(temp_memory_dir / "learned" / "tool_fixes.yaml", "w") as f:
        yaml.dump(data, f)


# ---------------------------------------------------------------------------
# _resolve_memory_path (sync)
# ---------------------------------------------------------------------------


class TestResolveMemoryPath:
    def test_global_key_adds_yaml(self, temp_memory_dir):
        p = memory_tools._resolve_memory_path("learned/patterns")
        assert p == temp_memory_dir / "learned" / "patterns.yaml"

    def test_global_key_already_has_yaml(self, temp_memory_dir):
        p = memory_tools._resolve_memory_path("learned/patterns.yaml")
        assert p == temp_memory_dir / "learned" / "patterns.yaml"

    def test_project_specific_key_delegates(self, temp_memory_dir):
        expected = (
            temp_memory_dir / "state" / "projects" / "myproj" / "current_work.yaml"
        )
        with patch(
            "tool_modules.aa_workflow.src.chat_context.get_project_work_state_path",
            return_value=expected,
        ):
            p = memory_tools._resolve_memory_path("state/current_work")
            assert p == expected

    def test_project_specific_fallback_on_import_error(self, temp_memory_dir):
        # Both import attempts fail -> falls through to global path
        with patch.dict(
            "sys.modules",
            {"tool_modules.aa_workflow.src.chat_context": None},
        ):
            p = memory_tools._resolve_memory_path("state/current_work")
            assert p == temp_memory_dir / "state" / "current_work.yaml"


# ---------------------------------------------------------------------------
# _resolve_memory_path_async
# ---------------------------------------------------------------------------


class TestResolveMemoryPathAsync:
    @pytest.mark.asyncio
    async def test_with_ctx_workspace(self, temp_memory_dir):
        ctx = AsyncMock()
        with patch(
            "server.workspace_utils.get_workspace_project",
            new_callable=AsyncMock,
            return_value="backend",
        ):
            p = await memory_tools._resolve_memory_path_async("state/current_work", ctx)
            assert (
                p
                == temp_memory_dir
                / "state"
                / "projects"
                / "backend"
                / "current_work.yaml"
            )

    @pytest.mark.asyncio
    async def test_without_ctx_falls_back(self, temp_memory_dir):
        expected = temp_memory_dir / "state" / "projects" / "proj" / "current_work.yaml"
        with patch(
            "tool_modules.aa_workflow.src.chat_context.get_project_work_state_path",
            return_value=expected,
        ):
            p = await memory_tools._resolve_memory_path_async("state/current_work")
            assert p == expected

    @pytest.mark.asyncio
    async def test_global_key_no_ctx(self, temp_memory_dir):
        p = await memory_tools._resolve_memory_path_async("learned/patterns")
        assert p == temp_memory_dir / "learned" / "patterns.yaml"


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestCheckPatternMatches:
    def test_match_by_error(self):
        patterns = [{"pattern": "timeout", "meaning": "slow", "fix": "retry"}]
        result = memory_tools._check_pattern_matches(
            patterns, "error_patterns", "timeout occurred"
        )
        assert len(result) == 1
        assert result[0]["source"] == "error_patterns"
        assert result[0]["fix"] == "retry"

    def test_no_match(self):
        patterns = [{"pattern": "timeout", "meaning": "slow", "fix": "retry"}]
        result = memory_tools._check_pattern_matches(
            patterns, "error_patterns", "something else"
        )
        assert len(result) == 0

    def test_empty_pattern_skipped(self):
        patterns = [{"pattern": "", "meaning": "x", "fix": "y"}]
        result = memory_tools._check_pattern_matches(
            patterns, "error_patterns", "anything"
        )
        assert len(result) == 0

    def test_jira_cli_pattern_fields(self):
        patterns = [
            {
                "pattern": "issue not found",
                "description": "bad key",
                "solution": "fix it",
            }
        ]
        result = memory_tools._check_pattern_matches(
            patterns, "jira_cli_patterns", "issue not found"
        )
        assert len(result) == 1
        assert result[0]["description"] == "bad key"
        assert result[0]["solution"] == "fix it"

    def test_match_by_tool_name(self):
        patterns = [{"pattern": "bonfire", "meaning": "deploy tool", "fix": "update"}]
        result = memory_tools._check_pattern_matches(
            patterns, "bonfire_patterns", "", "bonfire_deploy"
        )
        assert len(result) == 1


class TestLoadPatternsFromMemory:
    def test_loads_existing(self, temp_memory_dir, _seed_patterns):
        result = memory_tools._load_patterns_from_memory()
        assert "error_patterns" in result

    def test_returns_empty_when_missing(self, temp_memory_dir):
        result = memory_tools._load_patterns_from_memory()
        assert result == {}

    def test_returns_empty_on_corrupt_file(self, temp_memory_dir):
        (temp_memory_dir / "learned" / "patterns.yaml").write_text(": invalid: yaml: [")
        result = memory_tools._load_patterns_from_memory()
        assert result == {}


class TestLoadToolFixesFromMemory:
    def test_loads_existing(self, temp_memory_dir, _seed_tool_fixes):
        result = memory_tools._load_tool_fixes_from_memory()
        assert len(result) == 1
        assert result[0]["tool_name"] == "bonfire_deploy"

    def test_returns_empty_when_missing(self, temp_memory_dir):
        result = memory_tools._load_tool_fixes_from_memory()
        assert result == []

    def test_returns_empty_on_corrupt_file(self, temp_memory_dir):
        (temp_memory_dir / "learned" / "tool_fixes.yaml").write_text(": bad yaml [")
        result = memory_tools._load_tool_fixes_from_memory()
        assert result == []


class TestFormatKnownIssueMatches:
    def test_tool_fixes_format(self):
        matches = [
            {
                "source": "tool_fixes",
                "tool_name": "deploy",
                "error_pattern": "fail",
                "root_cause": "bad",
                "fix_applied": "fix it",
                "date_learned": "2025-01-01",
            }
        ]
        lines = memory_tools._format_known_issue_matches(matches)
        text = "\n".join(lines)
        assert "deploy" in text
        assert "fix it" in text
        assert "2025-01-01" in text

    def test_jira_cli_format(self):
        matches = [
            {
                "source": "jira_cli_patterns",
                "pattern": "not found",
                "description": "desc",
                "solution": "sol",
            }
        ]
        lines = memory_tools._format_known_issue_matches(matches)
        text = "\n".join(lines)
        assert "sol" in text
        assert "desc" in text

    def test_generic_format(self):
        matches = [
            {
                "source": "error_patterns",
                "pattern": "timeout",
                "meaning": "slow",
                "fix": "retry",
                "commands": ["cmd1", "cmd2"],
            }
        ]
        lines = memory_tools._format_known_issue_matches(matches)
        text = "\n".join(lines)
        assert "retry" in text
        assert "cmd1, cmd2" in text

    def test_limits_to_five(self):
        matches = [{"source": "error_patterns", "pattern": f"p{i}"} for i in range(8)]
        lines = memory_tools._format_known_issue_matches(matches)
        text = "\n".join(lines)
        assert "3 more matches" in text


class TestCollectFileStats:
    def test_collects_yaml_files(self, temp_memory_dir):
        (temp_memory_dir / "state" / "test.yaml").write_text("key: value")
        stats, total = memory_tools._collect_file_stats()
        assert "state/test.yaml" in stats
        assert total > 0

    def test_empty_directory(self, temp_memory_dir):
        stats, total = memory_tools._collect_file_stats()
        assert stats == {}
        assert total == 0


class TestCollectAutohealStats:
    def test_no_file(self, temp_memory_dir):
        result = memory_tools._collect_autoheal_stats()
        assert result == {}

    def test_with_data(self, temp_memory_dir):
        data = {
            "stats": {
                "total_failures": 10,
                "auto_fixed": 7,
                "manual_required": 3,
            },
            "failures": [{"id": 1}, {"id": 2}],
        }
        with open(temp_memory_dir / "learned" / "tool_failures.yaml", "w") as f:
            yaml.dump(data, f)

        result = memory_tools._collect_autoheal_stats()
        assert result["total_failures"] == 10
        assert result["success_rate"] == 0.7
        assert result["recent_count"] == 2

    def test_zero_failures(self, temp_memory_dir):
        data = {
            "stats": {"total_failures": 0, "auto_fixed": 0, "manual_required": 0},
            "failures": [],
        }
        with open(temp_memory_dir / "learned" / "tool_failures.yaml", "w") as f:
            yaml.dump(data, f)
        result = memory_tools._collect_autoheal_stats()
        assert result["success_rate"] == 0


class TestCollectPatternStats:
    def test_no_file(self, temp_memory_dir):
        result = memory_tools._collect_pattern_stats()
        assert result == {}

    def test_with_data(self, temp_memory_dir, _seed_patterns):
        result = memory_tools._collect_pattern_stats()
        assert result["total"] == 3  # 1 error + 1 auth + 1 jira_cli (others empty)
        assert "by_category" in result


class TestFormatMemoryStats:
    def test_healthy_system(self):
        stats = {
            "files": {"state/test.yaml": {"size_kb": 1.5, "modified": "2025-01-01"}},
            "storage": {"state": 1.5, "total_kb": 1.5},
            "auto_heal": {
                "success_rate": 0.9,
                "total_failures": 5,
                "auto_fixed": 4,
                "manual_required": 1,
                "recent_count": 2,
            },
            "patterns": {
                "total": 3,
                "by_category": {"error_patterns": 2, "auth_patterns": 1},
            },
            "sessions": {
                "total_session_files": 5,
                "today_actions": 10,
                "today_date": "2025-01-01",
            },
        }
        lines = memory_tools._format_memory_stats(stats)
        text = "\n".join(lines)
        assert "Statistics" in text
        assert "All checks passed" in text

    def test_warnings(self):
        stats = {
            "files": {"big.yaml": {"size_kb": 100, "modified": "2025-01-01"}},
            "storage": {"total_kb": 2048},
            "auto_heal": {
                "success_rate": 0.3,
                "total_failures": 10,
                "auto_fixed": 3,
                "manual_required": 7,
                "recent_count": 5,
            },
        }
        lines = memory_tools._format_memory_stats(stats)
        text = "\n".join(lines)
        assert "over 50 KB" in text
        assert "over 1 MB" in text
        assert "success rate low" in text


# ---------------------------------------------------------------------------
# Async tool implementations
# ---------------------------------------------------------------------------


class TestMemoryReadImpl:
    @pytest.mark.asyncio
    async def test_list_available_when_no_key(self, temp_memory_dir):
        (temp_memory_dir / "state" / "env.yaml").write_text("x: 1")
        with patch("tool_modules.aa_workflow.src.agent_stats.record_memory_read"):
            result = await memory_tools._memory_read_impl("")
        assert len(result) == 1
        assert "Available Memory" in result[0].text

    @pytest.mark.asyncio
    async def test_reads_existing_file(self, temp_memory_dir):
        (temp_memory_dir / "learned" / "patterns.yaml").write_text("foo: bar")
        with patch("tool_modules.aa_workflow.src.agent_stats.record_memory_read"):
            result = await memory_tools._memory_read_impl("learned/patterns")
        assert "foo: bar" in result[0].text

    @pytest.mark.asyncio
    async def test_file_not_found(self, temp_memory_dir):
        with patch("tool_modules.aa_workflow.src.agent_stats.record_memory_read"):
            result = await memory_tools._memory_read_impl("nonexistent/file")
        assert "not found" in result[0].text

    @pytest.mark.asyncio
    async def test_project_specific_not_found(self, temp_memory_dir):
        # Ensure the resolved path is within temp_memory_dir but does not exist
        missing_path = (
            temp_memory_dir / "state" / "projects" / "testproj" / "current_work.yaml"
        )
        with (
            patch("tool_modules.aa_workflow.src.agent_stats.record_memory_read"),
            patch(
                "tool_modules.aa_workflow.src.memory_tools._resolve_memory_path_async",
                new_callable=AsyncMock,
                return_value=missing_path,
            ),
        ):
            result = await memory_tools._memory_read_impl("state/current_work")
        assert "No work state" in result[0].text or "not found" in result[0].text

    @pytest.mark.asyncio
    async def test_read_error_handled(self, temp_memory_dir):
        file_path = temp_memory_dir / "state" / "bad.yaml"
        file_path.write_text("content")
        with patch("tool_modules.aa_workflow.src.agent_stats.record_memory_read"):
            with patch.object(Path, "read_text", side_effect=PermissionError("no")):
                result = await memory_tools._memory_read_impl("state/bad")
        assert "Error" in result[0].text


class TestMemoryWriteImpl:
    @pytest.mark.asyncio
    async def test_write_valid_yaml(self, temp_memory_dir):
        with patch("tool_modules.aa_workflow.src.agent_stats.record_memory_write"):
            result = await memory_tools._memory_write_impl("learned/new", "key: value")
        assert "saved" in result[0].text
        assert (temp_memory_dir / "learned" / "new.yaml").exists()

    @pytest.mark.asyncio
    async def test_write_invalid_yaml(self, temp_memory_dir):
        with patch("tool_modules.aa_workflow.src.agent_stats.record_memory_write"):
            result = await memory_tools._memory_write_impl(
                "learned/bad", ": invalid [yaml{"
            )
        assert "Invalid YAML" in result[0].text

    @pytest.mark.asyncio
    async def test_write_creates_dirs(self, temp_memory_dir):
        with patch("tool_modules.aa_workflow.src.agent_stats.record_memory_write"):
            result = await memory_tools._memory_write_impl(
                "new_dir/sub/file", "data: ok"
            )
        assert "saved" in result[0].text


class TestMemoryUpdateImpl:
    @pytest.mark.asyncio
    async def test_update_existing_field(self, temp_memory_dir):
        (temp_memory_dir / "state" / "test.yaml").write_text("status: old")
        with patch("tool_modules.aa_workflow.src.agent_stats.record_memory_write"):
            result = await memory_tools._memory_update_impl(
                "state/test", "status", "new"
            )
        assert "Updated" in result[0].text
        data = yaml.safe_load((temp_memory_dir / "state" / "test.yaml").read_text())
        assert data["status"] == "new"

    @pytest.mark.asyncio
    async def test_update_nested_field(self, temp_memory_dir):
        (temp_memory_dir / "state" / "test.yaml").write_text("a:\n  b: old")
        with patch("tool_modules.aa_workflow.src.agent_stats.record_memory_write"):
            await memory_tools._memory_update_impl("state/test", "a.b", "new")
        data = yaml.safe_load((temp_memory_dir / "state" / "test.yaml").read_text())
        assert data["a"]["b"] == "new"

    @pytest.mark.asyncio
    async def test_update_missing_file_non_project(self, temp_memory_dir):
        with patch("tool_modules.aa_workflow.src.agent_stats.record_memory_write"):
            result = await memory_tools._memory_update_impl(
                "nonexistent/key", "x", "val"
            )
        assert "not found" in result[0].text

    @pytest.mark.asyncio
    async def test_update_creates_project_specific_file(self, temp_memory_dir):
        proj_dir = temp_memory_dir / "state" / "projects" / "testproj"
        proj_dir.mkdir(parents=True)
        expected_path = proj_dir / "current_work.yaml"
        with (
            patch("tool_modules.aa_workflow.src.agent_stats.record_memory_write"),
            patch(
                "tool_modules.aa_workflow.src.memory_tools._resolve_memory_path_async",
                new_callable=AsyncMock,
                return_value=expected_path,
            ),
        ):
            result = await memory_tools._memory_update_impl(
                "state/current_work", "active", "true"
            )
        assert "Updated" in result[0].text


class TestMemoryAppendImpl:
    @pytest.mark.asyncio
    async def test_append_to_existing_list(self, temp_memory_dir):
        (temp_memory_dir / "state" / "test.yaml").write_text("items:\n  - first")
        with patch("tool_modules.aa_workflow.src.agent_stats.record_memory_write"):
            result = await memory_tools._memory_append_impl(
                "state/test", "items", "second"
            )
        assert "Appended" in result[0].text
        data = yaml.safe_load((temp_memory_dir / "state" / "test.yaml").read_text())
        assert len(data["items"]) == 2

    @pytest.mark.asyncio
    async def test_append_creates_list(self, temp_memory_dir):
        (temp_memory_dir / "state" / "test.yaml").write_text("other: val")
        with patch("tool_modules.aa_workflow.src.agent_stats.record_memory_write"):
            result = await memory_tools._memory_append_impl(
                "state/test", "new_list", "item1"
            )
        assert "Appended" in result[0].text
        data = yaml.safe_load((temp_memory_dir / "state" / "test.yaml").read_text())
        assert data["new_list"] == ["item1"]

    @pytest.mark.asyncio
    async def test_append_not_a_list_error(self, temp_memory_dir):
        (temp_memory_dir / "state" / "test.yaml").write_text("field: value")
        with patch("tool_modules.aa_workflow.src.agent_stats.record_memory_write"):
            result = await memory_tools._memory_append_impl(
                "state/test", "field", "new"
            )
        assert "not a list" in result[0].text

    @pytest.mark.asyncio
    async def test_append_missing_file_non_project(self, temp_memory_dir):
        with patch("tool_modules.aa_workflow.src.agent_stats.record_memory_write"):
            result = await memory_tools._memory_append_impl(
                "nonexistent/key", "items", "val"
            )
        assert "not found" in result[0].text


class TestMemoryQueryImpl:
    @staticmethod
    def _make_mock_jsonpath_ng(data, query, results):
        """Create a mock jsonpath_ng module that returns the given results."""
        mock_match = MagicMock()
        mock_match.value = None  # will be set per match

        mock_matches = []
        for r in results:
            m = MagicMock()
            m.value = r
            mock_matches.append(m)

        mock_expr = MagicMock()
        mock_expr.find.return_value = mock_matches

        mock_parse = MagicMock(return_value=mock_expr)

        mock_module = MagicMock()
        mock_module.parse = mock_parse
        return mock_module, mock_parse

    @pytest.mark.asyncio
    async def test_query_success(self, temp_memory_dir):
        (temp_memory_dir / "state" / "test.yaml").write_text(
            "items:\n  - name: alpha\n  - name: beta"
        )
        mock_module, mock_parse = self._make_mock_jsonpath_ng(
            None, None, ["alpha", "beta"]
        )
        with (
            patch("tool_modules.aa_workflow.src.agent_stats.record_memory_read"),
            patch.dict("sys.modules", {"jsonpath_ng": mock_module}),
        ):
            result = await memory_tools._memory_query_impl(
                "state/test", "$.items[*].name"
            )
        assert "alpha" in result[0].text

    @pytest.mark.asyncio
    async def test_query_no_matches(self, temp_memory_dir):
        (temp_memory_dir / "state" / "test.yaml").write_text("items: []")
        mock_module, mock_parse = self._make_mock_jsonpath_ng(None, None, [])
        with (
            patch("tool_modules.aa_workflow.src.agent_stats.record_memory_read"),
            patch.dict("sys.modules", {"jsonpath_ng": mock_module}),
        ):
            result = await memory_tools._memory_query_impl("state/test", "$.missing")
        assert "No matches" in result[0].text

    @pytest.mark.asyncio
    async def test_query_file_not_found(self, temp_memory_dir):
        mock_module, mock_parse = self._make_mock_jsonpath_ng(None, None, [])
        with (
            patch("tool_modules.aa_workflow.src.agent_stats.record_memory_read"),
            patch.dict("sys.modules", {"jsonpath_ng": mock_module}),
        ):
            result = await memory_tools._memory_query_impl("nonexistent/file", "$.x")
        assert "not found" in result[0].text

    @pytest.mark.asyncio
    async def test_query_import_error(self, temp_memory_dir):
        """When jsonpath_ng is not installed, should return a helpful error."""
        with (
            patch("tool_modules.aa_workflow.src.agent_stats.record_memory_read"),
            patch.dict("sys.modules", {"jsonpath_ng": None}),
        ):
            result = await memory_tools._memory_query_impl("state/test", "$.x")
        assert len(result) == 1
        assert "jsonpath_ng not installed" in result[0].text


class TestMemorySessionLogImpl:
    @pytest.mark.asyncio
    async def test_logs_action(self, temp_memory_dir):
        with patch("tool_modules.aa_workflow.src.agent_stats.record_memory_write"):
            result = await memory_tools._memory_session_log_impl(
                "Started work", "details here"
            )
        assert "Logged" in result[0].text

        # Verify file was created
        today = datetime.now().strftime("%Y-%m-%d")
        session_file = temp_memory_dir / "sessions" / f"{today}.yaml"
        assert session_file.exists()
        data = yaml.safe_load(session_file.read_text())
        assert len(data["entries"]) == 1
        assert data["entries"][0]["action"] == "Started work"
        assert data["entries"][0]["details"] == "details here"

    @pytest.mark.asyncio
    async def test_logs_without_details(self, temp_memory_dir):
        with patch("tool_modules.aa_workflow.src.agent_stats.record_memory_write"):
            await memory_tools._memory_session_log_impl("Just action")
        today = datetime.now().strftime("%Y-%m-%d")
        session_file = temp_memory_dir / "sessions" / f"{today}.yaml"
        data = yaml.safe_load(session_file.read_text())
        assert "details" not in data["entries"][0]

    @pytest.mark.asyncio
    async def test_appends_to_existing_session(self, temp_memory_dir):
        today = datetime.now().strftime("%Y-%m-%d")
        session_file = temp_memory_dir / "sessions" / f"{today}.yaml"
        session_file.write_text(
            yaml.dump(
                {"date": today, "entries": [{"time": "00:00:00", "action": "old"}]}
            )
        )
        with patch("tool_modules.aa_workflow.src.agent_stats.record_memory_write"):
            await memory_tools._memory_session_log_impl("new action")
        data = yaml.safe_load(session_file.read_text())
        assert len(data["entries"]) == 2


class TestCheckKnownIssuesImpl:
    @pytest.mark.asyncio
    async def test_no_matches(self, temp_memory_dir):
        result = await memory_tools._check_known_issues_impl(
            "unknown_tool", "unknown error"
        )
        assert "No known issues" in result[0].text

    @pytest.mark.asyncio
    async def test_matches_pattern(self, temp_memory_dir, _seed_patterns):
        result = await memory_tools._check_known_issues_impl(
            "", "connection refused by server"
        )
        assert "Known Issues Found" in result[0].text

    @pytest.mark.asyncio
    async def test_matches_tool_fix_by_name(self, temp_memory_dir, _seed_tool_fixes):
        result = await memory_tools._check_known_issues_impl("bonfire_deploy", "")
        assert "Known Issues Found" in result[0].text

    @pytest.mark.asyncio
    async def test_matches_tool_fix_by_error(self, temp_memory_dir, _seed_tool_fixes):
        result = await memory_tools._check_known_issues_impl(
            "", "manifest unknown in registry"
        )
        assert "Known Issues Found" in result[0].text


class TestLearnToolFixImpl:
    @pytest.mark.asyncio
    async def test_saves_new_fix(self, temp_memory_dir):
        result = await memory_tools._learn_tool_fix_impl(
            "my_tool", "error pattern", "root cause", "the fix"
        )
        assert "Saved tool fix" in result[0].text
        fixes_file = temp_memory_dir / "learned" / "tool_fixes.yaml"
        data = yaml.safe_load(fixes_file.read_text())
        assert len(data["tool_fixes"]) == 1
        assert data["tool_fixes"][0]["tool_name"] == "my_tool"

    @pytest.mark.asyncio
    async def test_updates_existing_fix(self, temp_memory_dir, _seed_tool_fixes):
        result = await memory_tools._learn_tool_fix_impl(
            "bonfire_deploy", "manifest unknown", "new cause", "new fix"
        )
        assert "Updated existing fix" in result[0].text
        data = yaml.safe_load(
            (temp_memory_dir / "learned" / "tool_fixes.yaml").read_text()
        )
        assert len(data["tool_fixes"]) == 1
        assert data["tool_fixes"][0]["root_cause"] == "new cause"

    @pytest.mark.asyncio
    async def test_error_handling(self, temp_memory_dir):
        with patch("builtins.open", side_effect=PermissionError("denied")):
            result = await memory_tools._learn_tool_fix_impl(
                "tool", "pattern", "cause", "fix"
            )
        assert "Error" in result[0].text


class TestMemoryStatsImpl:
    @pytest.mark.asyncio
    async def test_returns_stats(self, temp_memory_dir):
        (temp_memory_dir / "state" / "env.yaml").write_text("status: ok")
        result = await memory_tools._memory_stats_impl()
        assert "Statistics" in result[0].text

    @pytest.mark.asyncio
    async def test_handles_error(self, temp_memory_dir):
        with patch.object(
            memory_tools,
            "_collect_file_stats",
            side_effect=RuntimeError("boom"),
        ):
            result = await memory_tools._memory_stats_impl()
        assert "Error" in result[0].text
