"""Tests for server.tool_discovery module.

Tests tool discovery, manifest management, and module-to-tool mapping.
"""

import textwrap
from unittest.mock import patch

import pytest

from server.tool_discovery import (
    TOOL_MANIFEST,
    ToolInfo,
    ToolManifest,
    ToolTier,
    basic_tool,
    build_full_manifest,
    core_tool,
    discover_module_tools,
    discover_tools_from_file,
    extra_tool,
    get_all_tools,
    get_module_for_tool,
    get_module_tool_counts,
    get_module_tools,
    get_tool_info,
    get_tool_module,
    list_modules,
    register_tool,
)

# ============================================================
# Fixtures
# ============================================================


@pytest.fixture(autouse=True)
def clean_manifest():
    """Clear the global manifest before/after each test."""
    TOOL_MANIFEST.clear()
    yield
    TOOL_MANIFEST.clear()


@pytest.fixture
def manifest():
    """Create a fresh ToolManifest for isolated tests."""
    return ToolManifest()


@pytest.fixture
def sample_tool_file(tmp_path):
    """Create a sample Python file with tool registrations."""
    content = textwrap.dedent(
        '''\
        from server.tool_registry import ToolRegistry

        def register_tools(server):
            registry = ToolRegistry(server)

            @registry.tool()
            async def quay_get_tag(image: str) -> str:
                """Get a Quay image tag."""
                return "tag"

            @registry.tool()
            async def quay_list_repos() -> str:
                """List Quay repositories."""
                return "repos"

            return registry.count
    '''
    )
    filepath = tmp_path / "tools_basic.py"
    filepath.write_text(content)
    return filepath


@pytest.fixture
def sample_core_file(tmp_path):
    """Create a sample core tools Python file."""
    content = textwrap.dedent(
        '''\
        from server.tool_registry import ToolRegistry

        def register_tools(server):
            registry = ToolRegistry(server)

            @registry.tool()
            async def git_status() -> str:
                """Get git status."""
                return "status"

            return registry.count
    '''
    )
    filepath = tmp_path / "tools_core.py"
    filepath.write_text(content)
    return filepath


@pytest.fixture
def sample_extra_file(tmp_path):
    """Create a sample extra tools Python file."""
    content = textwrap.dedent(
        '''\
        from server.tool_registry import ToolRegistry

        def register_tools(server):
            registry = ToolRegistry(server)

            @registry.tool()
            async def git_bisect(ref: str) -> str:
                """Run git bisect."""
                return "bisect"

            return registry.count
    '''
    )
    filepath = tmp_path / "tools_extra.py"
    filepath.write_text(content)
    return filepath


# ============================================================
# ToolTier
# ============================================================


class TestToolTier:
    """Tests for ToolTier enum."""

    def test_core_value(self):
        assert ToolTier.CORE == "core"

    def test_basic_value(self):
        assert ToolTier.BASIC == "basic"

    def test_extra_value(self):
        assert ToolTier.EXTRA == "extra"

    def test_from_string(self):
        assert ToolTier("core") == ToolTier.CORE
        assert ToolTier("basic") == ToolTier.BASIC
        assert ToolTier("extra") == ToolTier.EXTRA

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            ToolTier("invalid")


# ============================================================
# ToolInfo
# ============================================================


class TestToolInfo:
    """Tests for ToolInfo dataclass."""

    def test_basic_creation(self):
        info = ToolInfo(name="my_tool", module="my_module", tier=ToolTier.BASIC)
        assert info.name == "my_tool"
        assert info.module == "my_module"
        assert info.tier == ToolTier.BASIC
        assert info.description == ""
        assert info.source_file == ""
        assert info.line_number == 0

    def test_creation_with_all_fields(self):
        info = ToolInfo(
            name="my_tool",
            module="my_module",
            tier=ToolTier.CORE,
            description="A tool",
            source_file="/path/to/file.py",
            line_number=42,
        )
        assert info.description == "A tool"
        assert info.source_file == "/path/to/file.py"
        assert info.line_number == 42


# ============================================================
# ToolManifest
# ============================================================


class TestToolManifest:
    """Tests for ToolManifest class."""

    def test_register_tool(self, manifest):
        """Should register a tool and track it by module."""
        info = ToolInfo(name="test_tool", module="test", tier=ToolTier.BASIC)
        manifest.register(info)

        assert "test_tool" in manifest.tools
        assert "test" in manifest.modules
        assert "test_tool" in manifest.modules["test"]

    def test_register_multiple_tools_same_module(self, manifest):
        """Multiple tools in the same module should be grouped."""
        manifest.register(ToolInfo(name="tool_a", module="mod", tier=ToolTier.BASIC))
        manifest.register(ToolInfo(name="tool_b", module="mod", tier=ToolTier.CORE))

        assert len(manifest.modules["mod"]) == 2
        assert "tool_a" in manifest.modules["mod"]
        assert "tool_b" in manifest.modules["mod"]

    def test_register_duplicate_tool_same_module(self, manifest):
        """Registering the same tool name twice should not duplicate in modules."""
        info = ToolInfo(name="dup_tool", module="mod", tier=ToolTier.BASIC)
        manifest.register(info)
        manifest.register(info)

        assert manifest.modules["mod"].count("dup_tool") == 1

    def test_freeze_prevents_registration(self, manifest):
        """After freeze(), no new tools should be registered."""
        manifest.freeze()

        info = ToolInfo(name="new_tool", module="mod", tier=ToolTier.BASIC)
        manifest.register(info)

        assert "new_tool" not in manifest.tools

    def test_clear_resets_everything(self, manifest):
        """clear() should reset tools, modules, and frozen state."""
        manifest.register(ToolInfo(name="t", module="m", tier=ToolTier.BASIC))
        manifest.freeze()
        manifest.clear()

        assert manifest.tools == {}
        assert manifest.modules == {}
        assert manifest._frozen is False

    def test_get_module_tools_no_filter(self, manifest):
        """get_module_tools without tier filter returns all tools."""
        manifest.register(ToolInfo(name="a", module="mod", tier=ToolTier.CORE))
        manifest.register(ToolInfo(name="b", module="mod", tier=ToolTier.BASIC))
        manifest.register(ToolInfo(name="c", module="mod", tier=ToolTier.EXTRA))

        tools = manifest.get_module_tools("mod")
        assert len(tools) == 3

    def test_get_module_tools_with_tier_filter(self, manifest):
        """get_module_tools with tier filter returns only matching tools."""
        manifest.register(ToolInfo(name="core_t", module="mod", tier=ToolTier.CORE))
        manifest.register(ToolInfo(name="basic_t", module="mod", tier=ToolTier.BASIC))
        manifest.register(ToolInfo(name="extra_t", module="mod", tier=ToolTier.EXTRA))

        core_tools = manifest.get_module_tools("mod", tier=ToolTier.CORE)
        assert core_tools == ["core_t"]

        basic_tools = manifest.get_module_tools("mod", tier=ToolTier.BASIC)
        assert basic_tools == ["basic_t"]

    def test_get_module_tools_unknown_module(self, manifest):
        """get_module_tools for unknown module returns empty list."""
        assert manifest.get_module_tools("nonexistent") == []

    def test_get_tool_module(self, manifest):
        """get_tool_module returns the module name for a tool."""
        manifest.register(
            ToolInfo(name="my_tool", module="my_mod", tier=ToolTier.BASIC)
        )
        assert manifest.get_tool_module("my_tool") == "my_mod"

    def test_get_tool_module_unknown(self, manifest):
        """get_tool_module returns None for unknown tool."""
        assert manifest.get_tool_module("nonexistent") is None

    def test_list_modules(self, manifest):
        """list_modules returns all modules with tools."""
        manifest.register(ToolInfo(name="a", module="mod_a", tier=ToolTier.BASIC))
        manifest.register(ToolInfo(name="b", module="mod_b", tier=ToolTier.BASIC))

        modules = manifest.list_modules()
        assert "mod_a" in modules
        assert "mod_b" in modules


# ============================================================
# register_tool decorator
# ============================================================


class TestRegisterToolDecorator:
    """Tests for the register_tool() decorator."""

    def test_register_with_string_tier(self):
        """register_tool with string tier should convert to ToolTier."""

        @register_tool(module="test", tier="core")
        async def my_tool():
            """My tool docstring."""
            pass

        info = TOOL_MANIFEST.tools.get("my_tool")
        assert info is not None
        assert info.tier == ToolTier.CORE
        assert info.module == "test"

    def test_register_with_enum_tier(self):
        """register_tool with ToolTier enum should work."""

        @register_tool(module="test", tier=ToolTier.EXTRA)
        async def extra_func():
            """An extra tool."""
            pass

        info = TOOL_MANIFEST.tools.get("extra_func")
        assert info is not None
        assert info.tier == ToolTier.EXTRA

    def test_register_extracts_docstring(self):
        """register_tool should extract first line of docstring."""

        @register_tool(module="test", tier="basic")
        async def documented_tool():
            """This is the first line.

            This is additional detail.
            """
            pass

        info = TOOL_MANIFEST.tools.get("documented_tool")
        assert info.description == "This is the first line."

    def test_register_with_explicit_description(self):
        """Explicit description should override docstring."""

        @register_tool(module="test", tier="basic", description="Custom desc")
        async def my_tool():
            """Docstring ignored."""
            pass

        info = TOOL_MANIFEST.tools.get("my_tool")
        assert info.description == "Custom desc"

    def test_register_preserves_function(self):
        """Decorator should return the original function unchanged."""

        @register_tool(module="test", tier="basic")
        async def my_tool():
            return "hello"

        assert callable(my_tool)

    def test_register_records_source_info(self):
        """Decorator should record source file and line number."""

        @register_tool(module="test", tier="basic")
        async def my_tool():
            """A tool."""
            pass

        info = TOOL_MANIFEST.tools.get("my_tool")
        assert info.source_file != ""
        assert info.line_number > 0


# ============================================================
# Convenience decorators
# ============================================================


class TestConvenienceDecorators:
    """Tests for core_tool, basic_tool, extra_tool."""

    def test_core_tool(self):

        @core_tool(module="git")
        async def git_status():
            """Get status."""
            pass

        info = TOOL_MANIFEST.tools.get("git_status")
        assert info.tier == ToolTier.CORE
        assert info.module == "git"

    def test_basic_tool(self):

        @basic_tool(module="git")
        async def git_log():
            """Show log."""
            pass

        info = TOOL_MANIFEST.tools.get("git_log")
        assert info.tier == ToolTier.BASIC

    def test_extra_tool(self):

        @extra_tool(module="git")
        async def git_bisect():
            """Bisect."""
            pass

        info = TOOL_MANIFEST.tools.get("git_bisect")
        assert info.tier == ToolTier.EXTRA

    def test_convenience_with_description(self):

        @core_tool(module="k8s", description="Custom desc")
        async def k8s_pods():
            """Ignored docstring."""
            pass

        info = TOOL_MANIFEST.tools.get("k8s_pods")
        assert info.description == "Custom desc"


# ============================================================
# Query functions
# ============================================================


class TestQueryFunctions:
    """Tests for module-level query functions."""

    def test_get_module_tools_no_tier(self):
        """get_module_tools without tier returns all module tools."""
        TOOL_MANIFEST.register(ToolInfo(name="a", module="mod", tier=ToolTier.CORE))
        TOOL_MANIFEST.register(ToolInfo(name="b", module="mod", tier=ToolTier.BASIC))

        result = get_module_tools("mod")
        assert len(result) == 2

    def test_get_module_tools_with_tier(self):
        """get_module_tools with tier filters properly."""
        TOOL_MANIFEST.register(ToolInfo(name="a", module="mod", tier=ToolTier.CORE))
        TOOL_MANIFEST.register(ToolInfo(name="b", module="mod", tier=ToolTier.BASIC))

        result = get_module_tools("mod", tier="core")
        assert result == ["a"]

    def test_get_tool_module_found(self):
        """get_tool_module returns module name for registered tool."""
        TOOL_MANIFEST.register(
            ToolInfo(name="my_tool", module="my_mod", tier=ToolTier.BASIC)
        )
        assert get_tool_module("my_tool") == "my_mod"

    def test_get_tool_module_not_found(self):
        """get_tool_module returns None for unknown tool."""
        assert get_tool_module("nonexistent") is None

    def test_get_all_tools(self):
        """get_all_tools returns dict of module -> tool names."""
        TOOL_MANIFEST.register(ToolInfo(name="a", module="mod1", tier=ToolTier.BASIC))
        TOOL_MANIFEST.register(ToolInfo(name="b", module="mod2", tier=ToolTier.BASIC))

        result = get_all_tools()
        assert "mod1" in result
        assert "mod2" in result
        assert result["mod1"] == ["a"]

    def test_get_tool_info(self):
        """get_tool_info returns ToolInfo for registered tool."""
        info = ToolInfo(
            name="my_tool",
            module="mod",
            tier=ToolTier.CORE,
            description="desc",
        )
        TOOL_MANIFEST.register(info)

        result = get_tool_info("my_tool")
        assert result is not None
        assert result.name == "my_tool"
        assert result.description == "desc"

    def test_get_tool_info_not_found(self):
        """get_tool_info returns None for unknown tool."""
        assert get_tool_info("nonexistent") is None

    def test_list_modules(self):
        """list_modules returns all module names."""
        TOOL_MANIFEST.register(ToolInfo(name="a", module="alpha", tier=ToolTier.BASIC))
        TOOL_MANIFEST.register(ToolInfo(name="b", module="beta", tier=ToolTier.BASIC))

        modules = list_modules()
        assert "alpha" in modules
        assert "beta" in modules


# ============================================================
# discover_tools_from_file
# ============================================================


class TestDiscoverToolsFromFile:
    """Tests for discover_tools_from_file function."""

    def test_discover_basic_tools(self, sample_tool_file):
        """Should discover async functions with @registry.tool()."""
        tools = discover_tools_from_file(sample_tool_file, "quay")

        tool_names = [t.name for t in tools]
        assert "quay_get_tag" in tool_names
        assert "quay_list_repos" in tool_names

    def test_discover_extracts_docstrings(self, sample_tool_file):
        """Should extract first line of docstring as description."""
        tools = discover_tools_from_file(sample_tool_file, "quay")
        tag_tool = next(t for t in tools if t.name == "quay_get_tag")
        assert tag_tool.description == "Get a Quay image tag."

    def test_discover_sets_tier_from_filename(
        self, sample_tool_file, sample_core_file, sample_extra_file
    ):
        """Tier should be determined from filename."""
        basic_tools = discover_tools_from_file(sample_tool_file, "quay")
        assert all(t.tier == ToolTier.BASIC for t in basic_tools)

        core_tools = discover_tools_from_file(sample_core_file, "git")
        assert all(t.tier == ToolTier.CORE for t in core_tools)

        extra_tools = discover_tools_from_file(sample_extra_file, "git")
        assert all(t.tier == ToolTier.EXTRA for t in extra_tools)

    def test_discover_nonexistent_file(self, tmp_path):
        """Should return empty list for non-existent file."""
        result = discover_tools_from_file(tmp_path / "nonexistent.py", "mod")
        assert result == []

    def test_discover_invalid_syntax(self, tmp_path):
        """Should return empty list for file with syntax errors."""
        bad_file = tmp_path / "tools_basic.py"
        bad_file.write_text("def broken(\n")

        result = discover_tools_from_file(bad_file, "mod")
        assert result == []

    def test_discover_no_tools(self, tmp_path):
        """Should return empty list for file with no tool decorators."""
        no_tools_file = tmp_path / "tools_basic.py"
        no_tools_file.write_text(
            textwrap.dedent(
                """\
            def regular_function():
                pass

            async def async_but_no_decorator():
                pass
        """
            )
        )

        result = discover_tools_from_file(no_tools_file, "mod")
        assert result == []

    def test_discover_records_source_info(self, sample_tool_file):
        """Should record source file path and line number."""
        tools = discover_tools_from_file(sample_tool_file, "quay")
        for tool in tools:
            assert tool.source_file == str(sample_tool_file)
            assert tool.line_number > 0

    def test_discover_sets_module(self, sample_tool_file):
        """Should set the module name on discovered tools."""
        tools = discover_tools_from_file(sample_tool_file, "my_module")
        for tool in tools:
            assert tool.module == "my_module"


# ============================================================
# discover_module_tools
# ============================================================


class TestDiscoverModuleTools:
    """Tests for discover_module_tools function."""

    def test_discover_core_basic_extra(self, tmp_path):
        """Should discover tools from core, basic, and extra files."""
        src_dir = tmp_path / "aa_test" / "src"
        src_dir.mkdir(parents=True)

        (src_dir / "tools_core.py").write_text(
            textwrap.dedent(
                '''\
            async def core_tool():
                @registry.tool()
                async def core_func():
                    """Core."""
                    pass
        '''
            )
        )
        # The discover function looks for @registry.tool() on AsyncFunctionDef
        # Let's write valid tool patterns
        (src_dir / "tools_core.py").write_text(
            textwrap.dedent(
                '''\
            @registry.tool()
            async def core_func():
                """Core tool."""
                pass
        '''
            )
        )
        (src_dir / "tools_basic.py").write_text(
            textwrap.dedent(
                '''\
            @registry.tool()
            async def basic_func():
                """Basic tool."""
                pass
        '''
            )
        )
        (src_dir / "tools_extra.py").write_text(
            textwrap.dedent(
                '''\
            @registry.tool()
            async def extra_func():
                """Extra tool."""
                pass
        '''
            )
        )

        with patch("server.tool_discovery.TOOL_MODULES_DIR", tmp_path):
            result = discover_module_tools("test")

        assert "core_func" in result["core"]
        assert "basic_func" in result["basic"]
        assert "extra_func" in result["extra"]

    def test_discover_legacy_tools_file(self, tmp_path):
        """Should fall back to tools.py when no tiered files exist."""
        src_dir = tmp_path / "aa_legacy" / "src"
        src_dir.mkdir(parents=True)

        (src_dir / "tools.py").write_text(
            textwrap.dedent(
                '''\
            @registry.tool()
            async def legacy_func():
                """Legacy tool."""
                pass
        '''
            )
        )

        with patch("server.tool_discovery.TOOL_MODULES_DIR", tmp_path):
            result = discover_module_tools("legacy")

        assert "legacy_func" in result["basic"]
        assert result["core"] == []
        assert result["extra"] == []

    def test_discover_no_module_dir(self, tmp_path):
        """Should return empty results when module dir doesn't exist."""
        with patch("server.tool_discovery.TOOL_MODULES_DIR", tmp_path):
            result = discover_module_tools("nonexistent")

        assert result == {"core": [], "basic": [], "extra": []}


# ============================================================
# build_full_manifest
# ============================================================


class TestBuildFullManifest:
    """Tests for build_full_manifest function."""

    def test_returns_manifest_when_populated(self):
        """Should return existing manifest data when populated."""
        TOOL_MANIFEST.register(ToolInfo(name="a", module="mod", tier=ToolTier.BASIC))

        result = build_full_manifest()
        assert "mod" in result
        assert "a" in result["mod"]

    def test_scans_files_when_empty(self, tmp_path):
        """Should scan tool module files when manifest is empty."""
        # Create a module directory structure
        mod_dir = tmp_path / "aa_testmod" / "src"
        mod_dir.mkdir(parents=True)
        (mod_dir / "tools_basic.py").write_text(
            textwrap.dedent(
                '''\
            @registry.tool()
            async def testmod_func():
                """A test tool."""
                pass
        '''
            )
        )

        with patch("server.tool_discovery.TOOL_MODULES_DIR", tmp_path):
            result = build_full_manifest()

        assert "testmod" in result
        assert "testmod_func" in result["testmod"]

    def test_ignores_non_aa_directories(self, tmp_path):
        """Should skip directories not starting with aa_."""
        # Create a non-aa directory
        (tmp_path / "not_aa_mod").mkdir()
        (tmp_path / "not_aa_mod" / "src").mkdir()

        with patch("server.tool_discovery.TOOL_MODULES_DIR", tmp_path):
            result = build_full_manifest()

        assert "not_aa_mod" not in result


# ============================================================
# get_module_for_tool
# ============================================================


class TestGetModuleForTool:
    """Tests for get_module_for_tool function."""

    def test_finds_tool_in_manifest(self):
        """Should find tool from the global manifest."""
        TOOL_MANIFEST.register(
            ToolInfo(name="my_tool", module="my_mod", tier=ToolTier.BASIC)
        )
        assert get_module_for_tool("my_tool") == "my_mod"

    def test_returns_none_for_unknown_tool(self, tmp_path):
        """Should return None when tool is not found anywhere."""
        with patch("server.tool_discovery.TOOL_MODULES_DIR", tmp_path):
            # Reset prefix map cache
            import server.tool_discovery as td

            td._MODULE_PREFIXES = None
            result = get_module_for_tool("completely_unknown_tool_xyz")

        assert result is None


# ============================================================
# get_module_tool_counts
# ============================================================


class TestGetModuleToolCounts:
    """Tests for get_module_tool_counts function."""

    def test_counts_by_tier(self, tmp_path):
        """Should return counts for each tier."""
        src_dir = tmp_path / "aa_counted" / "src"
        src_dir.mkdir(parents=True)

        (src_dir / "tools_core.py").write_text(
            textwrap.dedent(
                '''\
            @registry.tool()
            async def c1():
                """Core 1."""
                pass

            @registry.tool()
            async def c2():
                """Core 2."""
                pass
        '''
            )
        )
        (src_dir / "tools_basic.py").write_text(
            textwrap.dedent(
                '''\
            @registry.tool()
            async def b1():
                """Basic 1."""
                pass
        '''
            )
        )

        with patch("server.tool_discovery.TOOL_MODULES_DIR", tmp_path):
            result = get_module_tool_counts("counted")

        assert result["core"] == 2
        assert result["basic"] == 1
        assert result["extra"] == 0
        assert result["total"] == 3
