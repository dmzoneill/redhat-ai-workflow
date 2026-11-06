"""Tests for known-issue lookup and tool registry helpers in meta_tools."""

from unittest.mock import patch

import pytest
import yaml

from tool_modules.aa_workflow.src import meta_tools as mt


@pytest.fixture(name="temp_memory_dir")
def fixture_temp_memory_dir(tmp_path):
    """Create a temporary memory directory for known issues checking."""
    learned_dir = tmp_path / "learned"
    learned_dir.mkdir()
    # Patch PROJECT_ROOT in meta_tools so check_known_issues_sync
    # uses tmp_path/memory/learned/ instead of real memory dir
    with patch.object(mt, "PROJECT_ROOT", tmp_path):
        yield tmp_path


class TestCheckKnownIssuesSync:
    """Tests for check_known_issues_sync."""

    @pytest.mark.usefixtures("temp_memory_dir")
    def test_no_files_returns_empty(self):
        """No files returns empty."""
        result = mt.check_known_issues_sync("some_tool", "some error")
        assert not result

    def test_matches_error_pattern(self, temp_memory_dir):
        """Matches error pattern."""
        patterns_file = temp_memory_dir / "memory" / "learned" / "patterns.yaml"
        patterns_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "error_patterns": [
                {
                    "pattern": "no such host",
                    "meaning": "VPN down",
                    "fix": "Connect VPN",
                    "commands": ["vpn_connect"],
                }
            ]
        }
        with open(patterns_file, "w", encoding="utf-8") as f:
            yaml.dump(data, f)

        result = mt.check_known_issues_sync("gitlab", "dial tcp: no such host")
        assert len(result) == 1
        assert result[0]["fix"] == "Connect VPN"
        assert result[0]["commands"] == ["vpn_connect"]

    def test_matches_tool_name_in_pattern(self, temp_memory_dir):
        """Matches tool name in pattern."""
        patterns_file = temp_memory_dir / "memory" / "learned" / "patterns.yaml"
        patterns_file.parent.mkdir(parents=True, exist_ok=True)
        data = {"auth_patterns": [{"pattern": "bonfire", "meaning": "Bonfire issue", "fix": "Login"}]}
        with open(patterns_file, "w", encoding="utf-8") as f:
            yaml.dump(data, f)

        result = mt.check_known_issues_sync("bonfire_deploy", "")
        assert len(result) == 1
        assert result[0]["source"] == "auth_patterns"

    def test_matches_tool_fixes_by_name(self, temp_memory_dir):
        """Matches tool fixes by name."""
        fixes_file = temp_memory_dir / "memory" / "learned" / "tool_fixes.yaml"
        fixes_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "tool_fixes": [
                {
                    "tool_name": "quay_get_tag",
                    "error_pattern": "not found",
                    "fix_applied": "Use full image path",
                }
            ]
        }
        with open(fixes_file, "w", encoding="utf-8") as f:
            yaml.dump(data, f)

        result = mt.check_known_issues_sync("quay_get_tag", "something")
        assert len(result) == 1
        assert result[0]["source"] == "tool_fixes"

    def test_matches_tool_fixes_by_error(self, temp_memory_dir):
        """Matches tool fixes by error."""
        fixes_file = temp_memory_dir / "memory" / "learned" / "tool_fixes.yaml"
        fixes_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "tool_fixes": [
                {
                    "tool_name": "other_tool",
                    "error_pattern": "manifest unknown",
                    "fix_applied": "Use full SHA",
                }
            ]
        }
        with open(fixes_file, "w", encoding="utf-8") as f:
            yaml.dump(data, f)

        result = mt.check_known_issues_sync("", "error: manifest unknown in quay")
        assert len(result) == 1

    @pytest.mark.usefixtures("temp_memory_dir")
    def test_empty_inputs(self):
        """Empty inputs."""
        result = mt.check_known_issues_sync("", "")
        assert not result

    @pytest.mark.usefixtures("temp_memory_dir")
    def test_handles_exception(self):
        """Test handles file read exceptions gracefully."""
        with patch("builtins.open", side_effect=Exception("disk error")):
            result = mt.check_known_issues_sync("tool", "error")
            assert not result

    def test_multiple_categories(self, temp_memory_dir):
        """Multiple categories."""
        patterns_file = temp_memory_dir / "memory" / "learned" / "patterns.yaml"
        patterns_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "error_patterns": [{"pattern": "error x", "meaning": "m1", "fix": "f1"}],
            "bonfire_patterns": [{"pattern": "error x", "meaning": "m2", "fix": "f2"}],
            "pipeline_patterns": [{"pattern": "error x", "meaning": "m3", "fix": "f3"}],
        }
        with open(patterns_file, "w", encoding="utf-8") as f:
            yaml.dump(data, f)

        result = mt.check_known_issues_sync("", "error x occurred")
        assert len(result) == 3


class TestGetToolRegistry:
    """Tests for get_tool_registry."""

    def test_returns_dict(self):
        """Returns dict."""
        with patch.object(mt, "build_full_manifest", return_value={"mod": ["tool1"]}):
            result = mt.get_tool_registry()
            assert isinstance(result, dict)
            assert "mod" in result

    def test_empty_manifest(self):
        """Empty manifest."""
        with patch.object(mt, "build_full_manifest", return_value={}):
            result = mt.get_tool_registry()
            assert not result


class TestGetModuleForTool:
    """Tests for module_for_tool."""

    def test_returns_module(self):
        """Returns module."""
        with patch.object(mt, "get_module_for_tool", return_value="workflow"):
            result = mt.module_for_tool("session_start")
            assert result == "workflow"

    def test_returns_none_for_unknown(self):
        """Returns none for unknown."""
        with patch.object(mt, "get_module_for_tool", return_value=None):
            result = mt.module_for_tool("nonexistent_tool")
            assert result is None


class TestEdgeCases:
    """Edge case tests for meta_tools functions."""

    @pytest.mark.asyncio
    async def test_tool_list_with_empty_tools(self):
        """Test tool_list for module with empty tools list."""
        registry = {"empty_mod": []}
        with patch.object(mt, "get_tool_registry", return_value=registry):
            result = await mt.tool_list_impl("empty_mod")
            assert "0 tools" in result[0].text

    @pytest.mark.asyncio
    async def test_tool_list_all_shows_total(self):
        """Test tool_list all modules shows total count."""
        registry = {"mod1": ["t1", "t2"], "mod2": ["t3"]}
        with patch.object(mt, "get_tool_registry", return_value=registry):
            result = await mt.tool_list_impl("")
            assert "Total: 3 tools" in result[0].text
            assert "mod1" in result[0].text
            assert "mod2" in result[0].text

    @pytest.mark.asyncio
    async def test_tool_list_specific_module_shows_run_hint(self):
        """Test tool_list for a specific module shows run hint."""
        registry = {"git": ["git_status"]}
        with patch.object(mt, "get_tool_registry", return_value=registry):
            result = await mt.tool_list_impl("git")
            assert "tool_exec" in result[0].text

    def test_extract_tool_result_none(self):
        """Test extract_tool_result with None."""
        result = mt.extract_tool_result(None)
        assert result[0].text == "None"

    def test_extract_tool_result_integer(self):
        """Test extract_tool_result with integer."""
        result = mt.extract_tool_result(42)
        assert result[0].text == "42"

    def test_check_known_issues_sync_with_patterns_only(self, temp_memory_dir):
        """Test with patterns file but no fixes file."""
        patterns_file = temp_memory_dir / "memory" / "learned" / "patterns.yaml"
        patterns_file.parent.mkdir(parents=True, exist_ok=True)
        data = {"error_patterns": [{"pattern": "timeout", "meaning": "Slow", "fix": "Wait"}]}
        with open(patterns_file, "w", encoding="utf-8") as f:
            yaml.dump(data, f)

        result = mt.check_known_issues_sync("", "got timeout error")
        assert len(result) == 1

    @pytest.mark.usefixtures("temp_memory_dir")
    def test_check_known_issues_sync_no_error_no_tool(self):
        """Test with both empty strings."""
        result = mt.check_known_issues_sync("", "")
        assert not result
