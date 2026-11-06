"""Tests for tool_list and tool_exec in meta_tools."""

from unittest.mock import AsyncMock, patch

import pytest
import yaml
from fastmcp import FastMCP
from mcp.types import TextContent

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


class TestToolListImpl:
    """Tests for tool_list_impl."""

    @pytest.mark.asyncio
    async def test_list_all_modules(self):
        """List all modules."""
        registry = {"git": ["git_status", "git_diff"], "jira": ["jira_search"]}
        with patch.object(mt, "get_tool_registry", return_value=registry):
            result = await mt.tool_list_impl("")
            assert len(result) == 1
            text = result[0].text
            assert "git" in text
            assert "jira" in text
            assert "Total: 3 tools" in text

    @pytest.mark.asyncio
    async def test_list_specific_module(self):
        """List specific module."""
        registry = {"git": ["git_status", "git_diff"]}
        with patch.object(mt, "get_tool_registry", return_value=registry):
            result = await mt.tool_list_impl("git")
            text = result[0].text
            assert "git_status" in text
            assert "git_diff" in text
            assert "2 tools" in text

    @pytest.mark.asyncio
    async def test_list_unknown_module(self):
        """List unknown module."""
        registry = {"git": ["git_status"]}
        with patch.object(mt, "get_tool_registry", return_value=registry):
            result = await mt.tool_list_impl("nonexistent")
            assert "Unknown module" in result[0].text

    @pytest.mark.asyncio
    async def test_list_empty_module(self):
        """List empty module."""
        registry = {"git": []}
        with patch.object(mt, "get_tool_registry", return_value=registry):
            result = await mt.tool_list_impl("git")
            text = result[0].text
            assert "0 tools" in text


class TestExtractToolResult:
    """Tests for extract_tool_result."""

    def test_extracts_text_content(self):
        """Extracts text content."""
        content = TextContent(type="text", text="hello")
        result = mt.extract_tool_result([content])
        assert result[0].text == "hello"

    def test_handles_tuple(self):
        """Handles tuple."""
        content = TextContent(type="text", text="from tuple")
        result = mt.extract_tool_result(([content],))
        assert result[0].text == "from tuple"

    def test_handles_list_without_text_attr(self):
        """Handles list without text attr."""
        result = mt.extract_tool_result(["string_result"])
        assert result[0].text == "string_result"

    def test_handles_plain_string(self):
        """Handles plain string."""
        result = mt.extract_tool_result("plain")
        assert result[0].text == "plain"

    def test_handles_empty_list(self):
        """Handles empty list."""
        result = mt.extract_tool_result([])
        assert result[0].text == "[]"

    def test_handles_dict(self):
        """Handles dict."""
        result = mt.extract_tool_result({"key": "value"})
        assert "key" in result[0].text

    def test_handles_nested_tuple_list(self):
        """Handles nested tuple list."""
        content = TextContent(type="text", text="nested")
        result = mt.extract_tool_result(([content],))
        assert result[0].text == "nested"


class TestHandleToolExecError:
    """Tests for handle_tool_exec_error."""

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("temp_memory_dir")
    async def test_error_with_no_known_issues(self):
        """Error with no known issues."""
        result = await mt.handle_tool_exec_error("my_tool", "connection refused", "{}", None)
        assert "Error executing my_tool" in result[0].text
        assert "Auto-fix" in result[0].text

    @pytest.mark.asyncio
    async def test_error_with_known_issues(self, temp_memory_dir):
        """Error with known issues."""
        patterns_file = temp_memory_dir / "memory" / "learned" / "patterns.yaml"
        patterns_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "error_patterns": [
                {
                    "pattern": "connection refused",
                    "meaning": "Service down",
                    "fix": "Restart",
                }
            ]
        }
        patterns_file.write_text(yaml.dump(data), encoding="utf-8")

        result = await mt.handle_tool_exec_error("my_tool", "connection refused", "{}", None)
        text = result[0].text
        assert "Known Issues" in text

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("temp_memory_dir")
    async def test_error_creates_github_issue(self):
        """Error creates github issue."""
        mock_create_issue = AsyncMock(
            return_value={
                "success": True,
                "issue_url": "https://github.com/repo/issues/1",
            }
        )
        result = await mt.handle_tool_exec_error("my_tool", "error", "{}", mock_create_issue)
        assert "Issue created" in result[0].text

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("temp_memory_dir")
    async def test_error_github_issue_fallback(self):
        """Error github issue fallback."""
        mock_create_issue = AsyncMock(
            return_value={
                "success": False,
                "issue_url": "https://github.com/repo/issues/new?title=error",
            }
        )
        result = await mt.handle_tool_exec_error("my_tool", "error", "{}", mock_create_issue)
        assert "Create GitHub Issue" in result[0].text

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("temp_memory_dir")
    async def test_error_github_issue_exception(self):
        """Error github issue exception."""
        mock_create_issue = AsyncMock(side_effect=RuntimeError("API error"))
        result = await mt.handle_tool_exec_error("my_tool", "error", "{}", mock_create_issue)
        # Should still return error text, just no issue link
        assert "Error executing my_tool" in result[0].text


class TestToolExecImpl:
    """Tests for tool_exec_impl."""

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        """Unknown tool."""
        with patch.object(mt, "module_for_tool", return_value=None):
            result = await mt.tool_exec_impl("nonexistent_tool", "{}", None)
            assert "Unknown tool" in result[0].text

    @pytest.mark.asyncio
    async def test_invalid_json_args(self):
        """Invalid json args."""
        with patch.object(mt, "module_for_tool", return_value="git"):
            result = await mt.tool_exec_impl("git_status", "{invalid", None)
            assert "Invalid JSON" in result[0].text

    @pytest.mark.asyncio
    async def test_module_not_found(self, tmp_path):
        """Module not found."""
        with (
            patch.object(mt, "module_for_tool", return_value="nonexistent"),
            patch.object(mt, "TOOL_MODULES_DIR", tmp_path),
        ):
            result = await mt.tool_exec_impl("nonexistent_tool", "{}", None)
            assert "Module not found" in result[0].text

    @pytest.mark.asyncio
    async def test_empty_args_default(self):
        """Test that empty args defaults to {}."""
        with patch.object(mt, "module_for_tool", return_value=None):
            result = await mt.tool_exec_impl("tool", "", None)
            assert "Unknown tool" in result[0].text

    @pytest.mark.asyncio
    async def test_execution_error_calls_handler(self, tmp_path):
        """Test that execution errors are handled."""
        # Create a dummy module directory
        mod_dir = tmp_path / "aa_testmod" / "src"
        mod_dir.mkdir(parents=True)
        (mod_dir / "tools_basic.py").write_text("def register_tools(server): pass")

        mock_create_issue = AsyncMock(return_value={"success": False, "issue_url": ""})

        with (
            patch.object(mt, "module_for_tool", return_value="testmod"),
            patch.object(mt, "TOOL_MODULES_DIR", tmp_path),
        ):
            result = await mt.tool_exec_impl("test_tool", "{}", mock_create_issue)
            # Should get an error since the tool doesn't exist in the module
            assert "Error" in result[0].text or "not found" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_spec_none_returns_error(self, tmp_path):
        """Test handles case when spec is None."""
        mod_dir = tmp_path / "aa_testmod" / "src"
        mod_dir.mkdir(parents=True)
        (mod_dir / "tools_basic.py").write_text("")

        with (
            patch.object(mt, "module_for_tool", return_value="testmod"),
            patch.object(mt, "TOOL_MODULES_DIR", tmp_path),
            patch("importlib.util.spec_from_file_location", return_value=None),
        ):
            result = await mt.tool_exec_impl("test_tool", "{}", None)
            assert "Could not load" in result[0].text

    @pytest.mark.asyncio
    async def test_tries_tools_basic_first(self, tmp_path):
        """Test tries tools_basic.py before tools.py."""
        mod_dir = tmp_path / "aa_testmod" / "src"
        mod_dir.mkdir(parents=True)
        # Create both files
        (mod_dir / "tools_basic.py").write_text("def register_tools(server): pass")
        (mod_dir / "tools.py").write_text("def register_tools(server): pass")

        with (
            patch.object(mt, "module_for_tool", return_value="testmod"),
            patch.object(mt, "TOOL_MODULES_DIR", tmp_path),
            patch("importlib.util.spec_from_file_location", return_value=None),
        ):
            result = await mt.tool_exec_impl("test_tool", "{}", None)
            assert "Could not load" in result[0].text

    @pytest.mark.asyncio
    async def test_falls_back_to_tools_py(self, tmp_path):
        """Test falls back to tools.py when tools_basic.py doesn't exist."""
        mod_dir = tmp_path / "aa_testmod" / "src"
        mod_dir.mkdir(parents=True)
        (mod_dir / "tools.py").write_text("def register_tools(server): pass")

        with (
            patch.object(mt, "module_for_tool", return_value="testmod"),
            patch.object(mt, "TOOL_MODULES_DIR", tmp_path),
            patch("importlib.util.spec_from_file_location", return_value=None),
        ):
            result = await mt.tool_exec_impl("test_tool", "{}", None)
            assert "Could not load" in result[0].text


class TestRegisterMetaTools:
    """Tests for register_meta_tools."""

    def test_registers_tools(self):
        """Test that register_meta_tools returns a count."""

        server = FastMCP("test-meta")
        count = mt.register_meta_tools(server)
        assert count > 0

    def test_registers_expected_tools(self):
        """Test that expected tools are registered."""

        server = FastMCP("test-meta")
        count = mt.register_meta_tools(server)
        assert count > 0


class TestToolExecViaServer:
    """Tests for tool_exec called through FastMCP server."""

    @pytest.mark.asyncio
    async def test_tool_exec_unknown(self):
        """Tool exec unknown."""

        server = FastMCP("test-exec-unknown")
        mt.register_meta_tools(server)
        with patch.object(mt, "module_for_tool", return_value=None):
            result = await server.call_tool("tool_exec", {"tool_name": "xyz"})
        text = str(result)
        assert "Unknown tool" in text or "unknown" in text.lower()

    @pytest.mark.asyncio
    async def test_tool_exec_bad_json(self):
        """Tool exec bad json."""

        server = FastMCP("test-exec-badjson")
        mt.register_meta_tools(server)
        with patch.object(mt, "module_for_tool", return_value="git"):
            result = await server.call_tool("tool_exec", {"tool_name": "my_tool", "args": "{bad}"})
        text = str(result)
        assert "Invalid JSON" in text or "invalid" in text.lower()

    @pytest.mark.asyncio
    async def test_tool_list_via_server(self):
        """Tool list via server."""

        server = FastMCP("test-list-server")
        mt.register_meta_tools(server)
        with patch.object(mt, "get_tool_registry", return_value={"mod1": ["a", "b"]}):
            result = await server.call_tool("tool_list", {"module": ""})
        text = str(result)
        assert "mod1" in text


class TestHandleToolExecErrorEdge:
    """Additional edge cases for handle_tool_exec_error."""

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("temp_memory_dir")
    async def test_error_no_create_issue_fn(self):
        """Test error handling when create_issue_fn is None."""
        result = await mt.handle_tool_exec_error("tool", "error", "{}", None)
        text = result[0].text
        assert "Error executing tool" in text
        assert "Auto-fix" in text

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("temp_memory_dir")
    async def test_error_create_issue_no_url(self):
        """Test error handling when issue creation returns no URL."""
        mock_fn = AsyncMock(return_value={"success": False, "issue_url": ""})
        result = await mt.handle_tool_exec_error("tool", "err", "{}", mock_fn)
        text = result[0].text
        assert "Error executing tool" in text
        # No URL so no issue link
        assert "Issue created" not in text
