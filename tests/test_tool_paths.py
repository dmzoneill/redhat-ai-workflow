"""Tests for server.tool_paths module."""

from pathlib import Path
from unittest.mock import patch

from server.tool_paths import (
    PROJECT_DIR,
    TOOL_MODULES_DIR,
    TOOLS_BASIC_FILE,
    TOOLS_CORE_FILE,
    TOOLS_EXTRA_FILE,
    TOOLS_FILE,
    TOOLS_STYLE_FILE,
    get_module_dir,
    get_tools_file_path,
)


class TestModuleConstants:
    """Tests for module-level constants."""

    def test_project_dir_is_absolute(self):
        assert PROJECT_DIR.is_absolute()

    def test_tool_modules_dir_is_child_of_project(self):
        assert TOOL_MODULES_DIR.parent == PROJECT_DIR

    def test_tool_modules_dir_name(self):
        assert TOOL_MODULES_DIR.name == "tool_modules"

    def test_tools_file_constant(self):
        assert TOOLS_FILE == "tools.py"

    def test_tools_core_file_constant(self):
        assert TOOLS_CORE_FILE == "tools_core.py"

    def test_tools_basic_file_constant(self):
        assert TOOLS_BASIC_FILE == "tools_basic.py"

    def test_tools_extra_file_constant(self):
        assert TOOLS_EXTRA_FILE == "tools_extra.py"

    def test_tools_style_file_constant(self):
        assert TOOLS_STYLE_FILE == "tools_style.py"


class TestGetToolsFilePath:
    """Tests for get_tools_file_path function."""

    def test_core_suffix(self):
        result = get_tools_file_path("k8s_core")
        expected = TOOL_MODULES_DIR / "aa_k8s" / "src" / "tools_core.py"
        assert result == expected

    def test_basic_suffix(self):
        result = get_tools_file_path("k8s_basic")
        expected = TOOL_MODULES_DIR / "aa_k8s" / "src" / "tools_basic.py"
        assert result == expected

    def test_extra_suffix(self):
        result = get_tools_file_path("k8s_extra")
        expected = TOOL_MODULES_DIR / "aa_k8s" / "src" / "tools_extra.py"
        assert result == expected

    def test_style_suffix(self):
        result = get_tools_file_path("slack_style")
        expected = TOOL_MODULES_DIR / "aa_slack" / "src" / "tools_style.py"
        assert result == expected

    def test_no_suffix_prefers_tools_core_when_exists(self, tmp_path):
        """When no suffix, if tools_core.py exists, return it."""
        # Use a module that has tools_core.py
        with patch.object(Path, "exists", return_value=True):
            result = get_tools_file_path("workflow")
        expected = TOOL_MODULES_DIR / "aa_workflow" / "src" / "tools_core.py"
        assert result == expected

    def test_no_suffix_falls_back_to_basic_when_core_missing(self):
        """When no suffix, if tools_core.py doesn't exist but basic does."""

        def exists_side_effect(self_path):
            return "tools_basic.py" in str(self_path)

        with patch.object(Path, "exists", side_effect=lambda: False) as mock_exists:
            # Need a more careful approach: tools_core doesn't exist, tools_basic does
            call_count = 0

            def mock_exists_func(path_self=None):
                nonlocal call_count
                call_count += 1
                # First call is for tools_core.py (not exist), second for tools_basic.py (exists)
                return call_count >= 2

            with patch.object(Path, "exists", mock_exists_func):
                result = get_tools_file_path("mymod")
            expected = TOOL_MODULES_DIR / "aa_mymod" / "src" / "tools_basic.py"
            assert result == expected

    def test_no_suffix_falls_back_to_tools_py(self):
        """When no suffix and neither core nor basic exist, use tools.py."""
        with patch.object(Path, "exists", return_value=False):
            result = get_tools_file_path("mymod")
        expected = TOOL_MODULES_DIR / "aa_mymod" / "src" / "tools.py"
        assert result == expected

    def test_git_core_module(self):
        result = get_tools_file_path("git_core")
        expected = TOOL_MODULES_DIR / "aa_git" / "src" / "tools_core.py"
        assert result == expected

    def test_git_basic_module(self):
        result = get_tools_file_path("git_basic")
        expected = TOOL_MODULES_DIR / "aa_git" / "src" / "tools_basic.py"
        assert result == expected

    def test_jira_extra_module(self):
        result = get_tools_file_path("jira_extra")
        expected = TOOL_MODULES_DIR / "aa_jira" / "src" / "tools_extra.py"
        assert result == expected

    def test_result_is_path_object(self):
        result = get_tools_file_path("git_core")
        assert isinstance(result, Path)


class TestGetModuleDir:
    """Tests for get_module_dir function."""

    def test_base_name_no_suffix(self):
        result = get_module_dir("git")
        expected = TOOL_MODULES_DIR / "aa_git"
        assert result == expected

    def test_strips_core_suffix(self):
        result = get_module_dir("git_core")
        expected = TOOL_MODULES_DIR / "aa_git"
        assert result == expected

    def test_strips_basic_suffix(self):
        result = get_module_dir("git_basic")
        expected = TOOL_MODULES_DIR / "aa_git"
        assert result == expected

    def test_strips_extra_suffix(self):
        result = get_module_dir("jira_extra")
        expected = TOOL_MODULES_DIR / "aa_jira"
        assert result == expected

    def test_strips_style_suffix(self):
        result = get_module_dir("slack_style")
        expected = TOOL_MODULES_DIR / "aa_slack"
        assert result == expected

    def test_workflow_module(self):
        result = get_module_dir("workflow")
        expected = TOOL_MODULES_DIR / "aa_workflow"
        assert result == expected

    def test_k8s_module(self):
        result = get_module_dir("k8s")
        expected = TOOL_MODULES_DIR / "aa_k8s"
        assert result == expected

    def test_result_is_path_object(self):
        result = get_module_dir("git")
        assert isinstance(result, Path)

    def test_no_double_strip(self):
        """Only the first matching suffix is stripped."""
        result = get_module_dir("test_core")
        expected = TOOL_MODULES_DIR / "aa_test"
        assert result == expected
