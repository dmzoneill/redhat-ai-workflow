"""Tests for persona_loader module."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure project root is on sys.path so `server` is importable as a package
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from server.persona_loader import (  # noqa: E402
    CORE_TOOLS,
    PERSONAS_DIR,
    PROJECT_DIR,
    TOOL_MODULES_DIR,
    PersonaLoader,
    discover_tool_modules,
    get_available_modules,
    is_valid_module,
)


class TestPaths:
    """Tests for path constants."""

    def test_servers_dir_exists(self):
        """TOOL_MODULES_DIR should point to tool_modules directory."""
        assert (
            TOOL_MODULES_DIR.exists()
        ), f"TOOL_MODULES_DIR does not exist: {TOOL_MODULES_DIR}"
        assert TOOL_MODULES_DIR.name == "tool_modules"

    def test_project_dir_exists(self):
        """PROJECT_DIR should point to project root."""
        assert PROJECT_DIR.exists(), f"PROJECT_DIR does not exist: {PROJECT_DIR}"

    def test_personas_dir_exists(self):
        """PERSONAS_DIR should point to personas directory."""
        assert PERSONAS_DIR.exists(), f"PERSONAS_DIR does not exist: {PERSONAS_DIR}"
        assert PERSONAS_DIR.name == "personas"


class TestToolModuleDiscovery:
    """Tests for dynamic tool module discovery."""

    def test_discover_tool_modules_not_empty(self):
        """discover_tool_modules should find modules."""
        modules = discover_tool_modules()
        assert len(modules) > 0

    def test_expected_modules_discovered(self):
        """Expected core modules should be discovered."""
        modules = get_available_modules()
        expected = ["git", "jira", "gitlab", "k8s", "workflow"]
        for module in expected:
            assert module in modules, f"Missing module: {module}"

    def test_basic_extra_variants_discovered(self):
        """Should discover _basic and _extra variants."""
        modules = get_available_modules()
        # Check that at least some _basic and _extra variants exist
        basic_modules = [m for m in modules if m.endswith("_basic")]
        extra_modules = [m for m in modules if m.endswith("_extra")]
        assert len(basic_modules) > 0, "No _basic modules found"
        assert len(extra_modules) > 0, "No _extra modules found"

    def test_is_valid_module(self):
        """is_valid_module should correctly validate modules."""
        assert is_valid_module("workflow") is True
        assert is_valid_module("k8s_basic") is True
        assert is_valid_module("nonexistent_module_xyz") is False


class TestCoreTools:
    """Tests for CORE_TOOLS constant."""

    def test_core_tools_not_empty(self):
        """CORE_TOOLS should have entries."""
        assert len(CORE_TOOLS) > 0

    def test_expected_core_tools(self):
        """Expected core tools should be present."""
        expected = ["persona_load", "session_start"]
        for tool in expected:
            assert tool in CORE_TOOLS, f"Missing core tool: {tool}"


class TestPersonaLoaderInit:
    """Tests for PersonaLoader initialization."""

    def test_init_with_server(self):
        """Should initialize with a server instance."""
        mock_server = MagicMock()
        loader = PersonaLoader(mock_server)

        assert loader.server == mock_server
        assert loader.current_persona == ""
        assert loader.loaded_modules == set()
        assert loader._tool_to_module == {}


class TestLoadPersonaConfig:
    """Tests for load_persona_config method."""

    def test_load_existing_persona(self):
        """Should load config for existing persona."""
        mock_server = MagicMock()
        loader = PersonaLoader(mock_server)

        # Check that developer persona exists and can be loaded
        if (PERSONAS_DIR / "developer.yaml").exists():
            config = loader.load_persona_config("developer")
            assert config is not None
            assert isinstance(config, dict)

    def test_load_nonexistent_persona(self):
        """Should return None for nonexistent persona."""
        mock_server = MagicMock()
        loader = PersonaLoader(mock_server)

        config = loader.load_persona_config("nonexistent_persona_xyz")
        assert config is None


class TestPersonaLoaderGetStatus:
    """Tests for get_status method."""

    def test_get_status_empty(self):
        """Should return empty status for fresh loader."""
        mock_server = MagicMock()
        loader = PersonaLoader(mock_server)

        status = loader.get_status()
        assert status["current_persona"] == ""
        assert status["loaded_modules"] == []
        assert status["tool_count"] == 0
        assert status["tools"] == []


class TestPersonaFiles:
    """Tests for persona YAML files."""

    def test_expected_personas_exist(self):
        """Expected persona files should exist."""
        expected_personas = ["developer", "devops", "incident", "release"]
        for persona in expected_personas:
            persona_file = PERSONAS_DIR / f"{persona}.yaml"
            assert persona_file.exists(), f"Missing persona file: {persona}.yaml"

    def test_personas_have_valid_tools(self):
        """Persona configs should reference valid tool modules."""
        import yaml

        available_modules = get_available_modules()

        for persona_file in PERSONAS_DIR.glob("*.yaml"):
            with open(persona_file) as f:
                config = yaml.safe_load(f)

            tools = config.get("tools", [])
            for tool in tools:
                assert (
                    tool in available_modules
                ), f"Persona {persona_file.stem} references unknown module: {tool}"


class TestGlobalLoader:
    """Tests for global loader functions."""

    def test_get_loader_initial(self):
        """get_loader should return None initially."""
        from server.persona_loader import get_loader

        # Note: This could be non-None if other tests ran first
        # Just verify it returns without error
        result = get_loader()
        assert result is None or isinstance(result, PersonaLoader)

    def test_init_loader(self):
        """init_loader should create and return loader."""
        from server.persona_loader import get_loader, init_loader  # noqa: F811

        mock_server = MagicMock()
        loader = init_loader(mock_server)

        assert isinstance(loader, PersonaLoader)
        assert loader.server == mock_server

        # Global should now be set
        assert get_loader() == loader


# ---------------------------------------------------------------------------
# Tests for discover_tool_modules edge cases
# ---------------------------------------------------------------------------


class TestDiscoverToolModulesEdgeCases:
    """Edge case tests for discover_tool_modules."""

    def test_missing_tool_modules_dir(self, tmp_path):
        """Returns empty set when TOOL_MODULES_DIR does not exist."""
        with patch("server.persona_loader.TOOL_MODULES_DIR", tmp_path / "nonexistent"):
            modules = discover_tool_modules()
        assert modules == set()

    def test_skips_non_aa_directories(self, tmp_path):
        """Skips directories not starting with 'aa_'."""
        (tmp_path / "not_aa_module" / "src").mkdir(parents=True)
        (tmp_path / "not_aa_module" / "src" / "tools.py").touch()
        with patch("server.persona_loader.TOOL_MODULES_DIR", tmp_path):
            modules = discover_tool_modules()
        assert len(modules) == 0

    def test_skips_dir_without_src(self, tmp_path):
        """Skips aa_ directories without src subdirectory."""
        (tmp_path / "aa_nosrc").mkdir()
        with patch("server.persona_loader.TOOL_MODULES_DIR", tmp_path):
            modules = discover_tool_modules()
        assert len(modules) == 0

    def test_discovers_all_variants(self, tmp_path):
        """Discovers base, _core, _basic, _extra, and _style variants."""
        src = tmp_path / "aa_test" / "src"
        src.mkdir(parents=True)
        (src / "tools.py").touch()
        (src / "tools_core.py").touch()
        (src / "tools_basic.py").touch()
        (src / "tools_extra.py").touch()
        (src / "tools_style.py").touch()

        with patch("server.persona_loader.TOOL_MODULES_DIR", tmp_path):
            modules = discover_tool_modules()

        assert "test" in modules
        assert "test_core" in modules
        assert "test_basic" in modules
        assert "test_extra" in modules
        assert "test_style" in modules

    def test_base_discovered_from_core_only(self, tmp_path):
        """Base module discovered when only tools_core.py exists."""
        src = tmp_path / "aa_mymod" / "src"
        src.mkdir(parents=True)
        (src / "tools_core.py").touch()

        with patch("server.persona_loader.TOOL_MODULES_DIR", tmp_path):
            modules = discover_tool_modules()

        assert "mymod" in modules
        assert "mymod_core" in modules

    def test_base_discovered_from_basic_only(self, tmp_path):
        """Base module discovered when only tools_basic.py exists."""
        src = tmp_path / "aa_simple" / "src"
        src.mkdir(parents=True)
        (src / "tools_basic.py").touch()

        with patch("server.persona_loader.TOOL_MODULES_DIR", tmp_path):
            modules = discover_tool_modules()

        assert "simple" in modules
        assert "simple_basic" in modules

    def test_skips_files_in_tool_modules_dir(self, tmp_path):
        """Skips regular files (not dirs) in tool_modules directory."""
        (tmp_path / "aa_file.py").touch()
        with patch("server.persona_loader.TOOL_MODULES_DIR", tmp_path):
            modules = discover_tool_modules()
        assert len(modules) == 0


# ---------------------------------------------------------------------------
# Tests for PersonaLoader._load_tool_module
# ---------------------------------------------------------------------------


class TestLoadToolModule:
    """Tests for _load_tool_module."""

    async def test_nonexistent_tools_file(self, tmp_path):
        """Returns empty list for nonexistent tools file."""
        mock_server = MagicMock()
        loader = PersonaLoader(mock_server)

        with patch(
            "server.persona_loader.get_tools_file_path",
            return_value=tmp_path / "nonexistent.py",
        ):
            result = await loader._load_tool_module("fake_module")
        assert result == []

    async def test_spec_is_none(self, tmp_path):
        """Returns empty list when importlib spec is None."""
        tools_file = tmp_path / "tools.py"
        tools_file.write_text("# empty")

        mock_server = MagicMock()
        loader = PersonaLoader(mock_server)

        with patch(
            "server.persona_loader.get_tools_file_path",
            return_value=tools_file,
        ):
            with patch(
                "importlib.util.spec_from_file_location",
                return_value=None,
            ):
                result = await loader._load_tool_module("test_mod")
        assert result == []

    async def test_module_not_tool_module(self, tmp_path):
        """Returns empty list when module does not implement ToolModuleProtocol."""
        tools_file = tmp_path / "tools.py"
        tools_file.write_text("x = 1\n")

        mock_server = MagicMock()
        mock_server.list_tools = AsyncMock(return_value=[])
        loader = PersonaLoader(mock_server)

        mock_spec = MagicMock()
        mock_spec.loader = MagicMock()

        with patch(
            "server.persona_loader.get_tools_file_path",
            return_value=tools_file,
        ):
            with patch(
                "importlib.util.spec_from_file_location",
                return_value=mock_spec,
            ):
                with patch(
                    "importlib.util.module_from_spec",
                    return_value=MagicMock(spec=[]),
                ):
                    with patch(
                        "server.persona_loader.is_tool_module",
                        return_value=False,
                    ):
                        result = await loader._load_tool_module("bad_mod")
        assert result == []

    async def test_successful_module_load(self, tmp_path):
        """Successfully loads module and tracks tools."""
        tools_file = tmp_path / "tools.py"
        tools_file.write_text("def register_tools(server): pass\n")

        mock_server = MagicMock()

        tool_before = MagicMock()
        tool_before.name = "existing_tool"
        tool_after_1 = MagicMock()
        tool_after_1.name = "existing_tool"
        tool_after_2 = MagicMock()
        tool_after_2.name = "new_tool_1"
        tool_after_3 = MagicMock()
        tool_after_3.name = "new_tool_2"

        mock_server.list_tools = AsyncMock(
            side_effect=[
                [tool_before],
                [tool_after_1, tool_after_2, tool_after_3],
            ]
        )
        loader = PersonaLoader(mock_server)

        mock_module = MagicMock()
        mock_module.register_tools = MagicMock()
        mock_spec = MagicMock()
        mock_spec.loader = MagicMock()

        with patch(
            "server.persona_loader.get_tools_file_path",
            return_value=tools_file,
        ):
            with patch(
                "importlib.util.spec_from_file_location",
                return_value=mock_spec,
            ):
                with patch(
                    "importlib.util.module_from_spec",
                    return_value=mock_module,
                ):
                    with patch(
                        "server.persona_loader.is_tool_module",
                        return_value=True,
                    ):
                        with patch(
                            "server.persona_loader.validate_tool_module",
                            return_value=[],
                        ):
                            result = await loader._load_tool_module("test_mod")

        assert sorted(result) == ["new_tool_1", "new_tool_2"]
        assert "test_mod" in loader.loaded_modules
        assert loader._tool_to_module["new_tool_1"] == "test_mod"
        assert loader._tool_to_module["new_tool_2"] == "test_mod"

    async def test_load_module_with_validation_warnings(self, tmp_path):
        """Validation warnings are logged but don't prevent loading."""
        tools_file = tmp_path / "tools.py"
        tools_file.write_text("def register_tools(server): pass\n")

        mock_server = MagicMock()
        mock_server.list_tools = AsyncMock(return_value=[])
        loader = PersonaLoader(mock_server)

        mock_module = MagicMock()
        mock_spec = MagicMock()
        mock_spec.loader = MagicMock()

        with patch(
            "server.persona_loader.get_tools_file_path",
            return_value=tools_file,
        ):
            with patch(
                "importlib.util.spec_from_file_location",
                return_value=mock_spec,
            ):
                with patch(
                    "importlib.util.module_from_spec",
                    return_value=mock_module,
                ):
                    with patch(
                        "server.persona_loader.is_tool_module",
                        return_value=True,
                    ):
                        with patch(
                            "server.persona_loader.validate_tool_module",
                            return_value=["warn: something"],
                        ):
                            await loader._load_tool_module("warn_mod")

        # Module loaded despite warnings
        assert "warn_mod" in loader.loaded_modules

    async def test_load_module_exception(self, tmp_path):
        """Exception during module load returns empty list."""
        tools_file = tmp_path / "tools.py"
        tools_file.write_text("raise RuntimeError('boom')\n")

        mock_server = MagicMock()
        loader = PersonaLoader(mock_server)

        with patch(
            "server.persona_loader.get_tools_file_path",
            return_value=tools_file,
        ):
            with patch(
                "importlib.util.spec_from_file_location",
                side_effect=Exception("import failed"),
            ):
                result = await loader._load_tool_module("broken_mod")
        assert result == []


# ---------------------------------------------------------------------------
# Tests for PersonaLoader._unload_module_tools
# ---------------------------------------------------------------------------


class TestUnloadModuleTools:
    """Tests for _unload_module_tools."""

    async def test_removes_module_tools(self):
        """Removes tools belonging to a module."""
        mock_server = MagicMock()
        loader = PersonaLoader(mock_server)
        loader._tool_to_module = {
            "tool_a": "mod1",
            "tool_b": "mod1",
            "tool_c": "mod2",
        }
        loader.loaded_modules = {"mod1", "mod2"}

        count = await loader._unload_module_tools("mod1")
        assert count == 2
        mock_server.remove_tool.assert_any_call("tool_a")
        mock_server.remove_tool.assert_any_call("tool_b")
        assert "tool_a" not in loader._tool_to_module
        assert "tool_b" not in loader._tool_to_module
        assert "tool_c" in loader._tool_to_module
        assert "mod1" not in loader.loaded_modules

    async def test_does_not_remove_core_tools(self):
        """Core tools are never removed."""
        mock_server = MagicMock()
        loader = PersonaLoader(mock_server)
        loader._tool_to_module = {
            "persona_load": "mod1",
            "regular_tool": "mod1",
        }
        loader.loaded_modules = {"mod1"}

        count = await loader._unload_module_tools("mod1")
        assert count == 1  # Only regular_tool removed
        assert "persona_load" in loader._tool_to_module

    async def test_handles_remove_failure(self):
        """Handles failure when removing a tool."""
        mock_server = MagicMock()
        mock_server.remove_tool.side_effect = Exception("remove failed")
        loader = PersonaLoader(mock_server)
        loader._tool_to_module = {"tool_a": "mod1"}
        loader.loaded_modules = {"mod1"}

        count = await loader._unload_module_tools("mod1")
        assert count == 1  # Attempted to remove 1 tool
        assert "mod1" not in loader.loaded_modules


# ---------------------------------------------------------------------------
# Tests for PersonaLoader._clear_non_core_tools
# ---------------------------------------------------------------------------


class TestClearNonCoreTools:
    """Tests for _clear_non_core_tools."""

    async def test_clears_all_non_core(self):
        """Removes all tools except core ones."""
        mock_server = MagicMock()

        tool_core = MagicMock()
        tool_core.name = "persona_load"
        tool_regular = MagicMock()
        tool_regular.name = "custom_tool"
        tool_regular2 = MagicMock()
        tool_regular2.name = "another_tool"

        mock_server.list_tools = AsyncMock(
            return_value=[tool_core, tool_regular, tool_regular2]
        )
        loader = PersonaLoader(mock_server)
        loader._tool_to_module = {"custom_tool": "mod1", "another_tool": "mod2"}
        loader.loaded_modules = {"mod1", "mod2"}

        removed = await loader._clear_non_core_tools()
        assert removed == 2
        assert loader._tool_to_module == {}
        assert loader.loaded_modules == set()

    async def test_handles_tool_without_name_attr(self):
        """Handles tool objects without .name attribute."""
        mock_server = MagicMock()

        tool_str = "some_tool_string"
        mock_server.list_tools = AsyncMock(return_value=[tool_str])
        loader = PersonaLoader(mock_server)

        removed = await loader._clear_non_core_tools()
        assert removed == 1

    async def test_handles_remove_exception(self):
        """Handles exception when removing tools."""
        mock_server = MagicMock()

        tool = MagicMock()
        tool.name = "bad_tool"
        mock_server.list_tools = AsyncMock(return_value=[tool])
        mock_server.remove_tool.side_effect = Exception("oops")
        loader = PersonaLoader(mock_server)

        removed = await loader._clear_non_core_tools()
        assert removed == 0  # Failed to remove


# ---------------------------------------------------------------------------
# Tests for PersonaLoader.switch_persona
# ---------------------------------------------------------------------------


class TestSwitchPersona:
    """Tests for switch_persona method."""

    async def test_persona_not_found(self, tmp_path):
        """Returns error when persona config not found."""
        mock_server = MagicMock()
        loader = PersonaLoader(mock_server)

        mock_ctx = MagicMock()

        with patch.object(loader, "load_persona_config", return_value=None):
            with patch(
                "server.persona_loader.PERSONAS_DIR",
                tmp_path,
            ):
                result = await loader.switch_persona("nonexistent", mock_ctx)

        assert result["success"] is False
        assert "not found" in result["error"].lower()

    async def test_switch_persona_loads_valid_modules(self):
        """Loads tools for valid modules in persona config."""
        mock_server = MagicMock()
        mock_server.list_tools = AsyncMock(return_value=[])
        loader = PersonaLoader(mock_server)

        config = {
            "tools": ["valid_mod"],
            "description": "Test persona",
            "persona": "",
        }

        mock_ctx = MagicMock()
        mock_ctx.session = MagicMock()
        mock_ctx.session.send_tool_list_changed = AsyncMock()

        with patch.object(loader, "load_persona_config", return_value=config):
            with patch.object(
                loader, "_clear_non_core_tools", new_callable=AsyncMock, return_value=0
            ):
                with patch(
                    "server.persona_loader.is_valid_module",
                    side_effect=lambda m: m == "valid_mod",
                ):
                    with patch.object(
                        loader,
                        "_load_tool_module",
                        new_callable=AsyncMock,
                        return_value=["tool1", "tool2"],
                    ):
                        with patch(
                            "server.workspace_state.WorkspaceRegistry",
                        ) as mock_ws:
                            mock_ws_state = MagicMock()
                            mock_session = MagicMock()
                            mock_session.session_id = "abc12345"
                            mock_session.persona = "old"
                            mock_ws_state.get_active_session.return_value = mock_session
                            mock_ws_state.workspace_uri = "file:///test"
                            mock_ws.get_for_ctx = AsyncMock(return_value=mock_ws_state)

                            with patch(
                                "server.workspace_state.update_persona_tool_count",
                            ):
                                result = await loader.switch_persona(
                                    "test_persona", mock_ctx
                                )

        assert result["success"] is True
        assert result["persona"] == "test_persona"
        assert result["tool_count"] == 2
        assert loader.current_persona == "test_persona"

    async def test_switch_persona_skips_invalid_modules(self):
        """Skips modules not in available modules."""
        mock_server = MagicMock()
        mock_server.list_tools = AsyncMock(return_value=[])
        loader = PersonaLoader(mock_server)

        config = {
            "tools": ["invalid_mod", "also_invalid"],
            "description": "Bad persona",
            "persona": "",
        }

        mock_ctx = MagicMock()
        mock_ctx.session = MagicMock()
        mock_ctx.session.send_tool_list_changed = AsyncMock()

        with patch.object(loader, "load_persona_config", return_value=config):
            with patch.object(
                loader, "_clear_non_core_tools", new_callable=AsyncMock, return_value=0
            ):
                with patch("server.persona_loader.is_valid_module", return_value=False):
                    with patch(
                        "server.workspace_state.WorkspaceRegistry",
                    ) as mock_ws:
                        mock_ws_state = MagicMock()
                        mock_ws_state.get_active_session.return_value = None
                        mock_session = MagicMock()
                        mock_session.session_id = "xyz"
                        mock_ws_state.create_session.return_value = mock_session
                        mock_ws_state.workspace_uri = "file:///test"
                        mock_ws.get_for_ctx = AsyncMock(return_value=mock_ws_state)

                        with patch(
                            "server.workspace_state.update_persona_tool_count",
                        ):
                            result = await loader.switch_persona(
                                "bad_persona", mock_ctx
                            )

        assert result["success"] is True
        assert result["tool_count"] == 0

    async def test_switch_persona_md_file_persona(self, tmp_path):
        """Loads persona text from .md file reference."""
        mock_server = MagicMock()
        mock_server.list_tools = AsyncMock(return_value=[])
        loader = PersonaLoader(mock_server)

        # Create the .md file relative to PERSONAS_DIR parent
        md_file = tmp_path / "personas" / "test.md"
        md_file.parent.mkdir(parents=True)
        md_file.write_text("You are a test persona.")

        config = {
            "tools": [],
            "description": "MD persona",
            "persona": "personas/test.md",
        }

        mock_ctx = MagicMock()
        mock_ctx.session = MagicMock()
        mock_ctx.session.send_tool_list_changed = AsyncMock()

        with patch.object(loader, "load_persona_config", return_value=config):
            with patch.object(
                loader, "_clear_non_core_tools", new_callable=AsyncMock, return_value=0
            ):
                with patch("server.persona_loader.PERSONAS_DIR", tmp_path / "personas"):
                    with patch(
                        "server.workspace_state.WorkspaceRegistry",
                    ) as mock_ws:
                        mock_ws.get_for_ctx = AsyncMock(side_effect=Exception("no ws"))
                        result = await loader.switch_persona("test", mock_ctx)

        assert result["success"] is True
        assert "test persona" in result["persona_context"]

    async def test_switch_persona_inline_persona(self):
        """Uses inline persona text."""
        mock_server = MagicMock()
        mock_server.list_tools = AsyncMock(return_value=[])
        loader = PersonaLoader(mock_server)

        config = {
            "tools": [],
            "description": "Inline",
            "persona": "You are inline.",
        }

        mock_ctx = MagicMock()
        mock_ctx.session = MagicMock()
        mock_ctx.session.send_tool_list_changed = AsyncMock()

        with patch.object(loader, "load_persona_config", return_value=config):
            with patch.object(
                loader, "_clear_non_core_tools", new_callable=AsyncMock, return_value=0
            ):
                with patch(
                    "server.workspace_state.WorkspaceRegistry",
                ) as mock_ws:
                    mock_ws.get_for_ctx = AsyncMock(side_effect=Exception("skip"))
                    result = await loader.switch_persona("inline_test", mock_ctx)

        assert result["persona_context"] == "You are inline."

    async def test_switch_persona_with_persona_append(self):
        """Appends persona_append text."""
        mock_server = MagicMock()
        mock_server.list_tools = AsyncMock(return_value=[])
        loader = PersonaLoader(mock_server)

        config = {
            "tools": [],
            "description": "Appended",
            "persona": "Base persona.",
            "persona_append": "Extra instructions.",
        }

        mock_ctx = MagicMock()
        mock_ctx.session = MagicMock()
        mock_ctx.session.send_tool_list_changed = AsyncMock()

        with patch.object(loader, "load_persona_config", return_value=config):
            with patch.object(
                loader, "_clear_non_core_tools", new_callable=AsyncMock, return_value=0
            ):
                with patch(
                    "server.workspace_state.WorkspaceRegistry",
                ) as mock_ws:
                    mock_ws.get_for_ctx = AsyncMock(side_effect=Exception("skip"))
                    result = await loader.switch_persona("append_test", mock_ctx)

        assert "Base persona." in result["persona_context"]
        assert "Extra instructions." in result["persona_context"]

    async def test_switch_persona_fallback_md_file(self, tmp_path):
        """Falls back to {persona_name}.md when persona ref is empty."""
        mock_server = MagicMock()
        mock_server.list_tools = AsyncMock(return_value=[])
        loader = PersonaLoader(mock_server)

        # Create fallback md file
        personas_dir = tmp_path / "personas"
        personas_dir.mkdir()
        (personas_dir / "fallback_test.md").write_text("Fallback content.")

        config = {
            "tools": [],
            "description": "Fallback",
            "persona": "",
        }

        mock_ctx = MagicMock()
        mock_ctx.session = MagicMock()
        mock_ctx.session.send_tool_list_changed = AsyncMock()

        with patch.object(loader, "load_persona_config", return_value=config):
            with patch.object(
                loader, "_clear_non_core_tools", new_callable=AsyncMock, return_value=0
            ):
                with patch("server.persona_loader.PERSONAS_DIR", personas_dir):
                    with patch(
                        "server.workspace_state.WorkspaceRegistry",
                    ) as mock_ws:
                        mock_ws.get_for_ctx = AsyncMock(side_effect=Exception("skip"))
                        result = await loader.switch_persona("fallback_test", mock_ctx)

        assert result["persona_context"] == "Fallback content."

    async def test_switch_persona_notification_failure_ignored(self):
        """Notification failure does not block persona switch."""
        mock_server = MagicMock()
        mock_server.list_tools = AsyncMock(return_value=[])
        loader = PersonaLoader(mock_server)

        config = {
            "tools": [],
            "description": "Notif test",
            "persona": "test",
        }

        mock_ctx = MagicMock()
        mock_ctx.session = MagicMock()
        mock_ctx.session.send_tool_list_changed = AsyncMock(
            side_effect=Exception("notification failed")
        )

        with patch.object(loader, "load_persona_config", return_value=config):
            with patch.object(
                loader, "_clear_non_core_tools", new_callable=AsyncMock, return_value=0
            ):
                with patch(
                    "server.workspace_state.WorkspaceRegistry",
                ) as mock_ws:
                    mock_ws.get_for_ctx = AsyncMock(side_effect=Exception("skip"))
                    result = await loader.switch_persona("notif_test", mock_ctx)

        assert result["success"] is True


# ---------------------------------------------------------------------------
# Tests for PersonaLoader.get_workspace_persona
# ---------------------------------------------------------------------------


class TestGetWorkspacePersona:
    """Tests for get_workspace_persona."""

    async def test_returns_workspace_persona(self):
        """Returns persona from workspace state."""
        mock_server = MagicMock()
        loader = PersonaLoader(mock_server)
        mock_ctx = MagicMock()

        mock_ws_state = MagicMock()
        mock_ws_state.persona = "devops"

        with patch(
            "server.workspace_state.WorkspaceRegistry",
        ) as mock_ws:
            mock_ws.get_for_ctx = AsyncMock(return_value=mock_ws_state)
            result = await loader.get_workspace_persona(mock_ctx)

        assert result == "devops"

    async def test_fallback_to_current_persona(self):
        """Falls back to current_persona when workspace fails."""
        mock_server = MagicMock()
        loader = PersonaLoader(mock_server)
        loader.current_persona = "developer"
        mock_ctx = MagicMock()

        with patch(
            "server.workspace_state.WorkspaceRegistry",
        ) as mock_ws:
            mock_ws.get_for_ctx = AsyncMock(side_effect=Exception("no ws"))
            result = await loader.get_workspace_persona(mock_ctx)

        assert result == "developer"

    async def test_fallback_to_config_default(self):
        """Falls back to config default when everything else fails."""
        mock_server = MagicMock()
        loader = PersonaLoader(mock_server)
        loader.current_persona = ""
        mock_ctx = MagicMock()

        with patch(
            "server.workspace_state.WorkspaceRegistry",
        ) as mock_ws:
            mock_ws.get_for_ctx = AsyncMock(side_effect=Exception("no ws"))
            with patch(
                "server.utils.load_config",
                return_value={"agent": {"default_persona": "incident"}},
            ):
                result = await loader.get_workspace_persona(mock_ctx)

        assert result == "incident"

    async def test_fallback_to_researcher(self):
        """Falls back to 'researcher' when all else fails."""
        mock_server = MagicMock()
        loader = PersonaLoader(mock_server)
        loader.current_persona = ""
        mock_ctx = MagicMock()

        with patch(
            "server.workspace_state.WorkspaceRegistry",
        ) as mock_ws:
            mock_ws.get_for_ctx = AsyncMock(side_effect=Exception("no ws"))
            with patch(
                "server.utils.load_config",
                side_effect=Exception("no config"),
            ):
                result = await loader.get_workspace_persona(mock_ctx)

        assert result == "researcher"


# ---------------------------------------------------------------------------
# Tests for PersonaLoader.set_workspace_persona
# ---------------------------------------------------------------------------


class TestSetWorkspacePersona:
    """Tests for set_workspace_persona."""

    async def test_sets_persona_on_workspace(self):
        """Sets persona and clears filter cache."""
        mock_server = MagicMock()
        loader = PersonaLoader(mock_server)
        mock_ctx = MagicMock()

        mock_ws_state = MagicMock()

        with patch(
            "server.workspace_state.WorkspaceRegistry",
        ) as mock_ws:
            mock_ws.get_for_ctx = AsyncMock(return_value=mock_ws_state)
            await loader.set_workspace_persona(mock_ctx, "devops")

        assert mock_ws_state.persona == "devops"
        mock_ws_state.clear_filter_cache.assert_called_once()

    async def test_handles_exception(self):
        """Handles exception without raising."""
        mock_server = MagicMock()
        loader = PersonaLoader(mock_server)
        mock_ctx = MagicMock()

        with patch(
            "server.workspace_state.WorkspaceRegistry",
        ) as mock_ws:
            mock_ws.get_for_ctx = AsyncMock(side_effect=Exception("boom"))
            await loader.set_workspace_persona(mock_ctx, "devops")
            # Should not raise


# ---------------------------------------------------------------------------
# Tests for PersonaLoader.get_workspace_status
# ---------------------------------------------------------------------------


class TestGetWorkspaceStatus:
    """Tests for get_workspace_status."""

    async def test_returns_workspace_status(self):
        """Returns workspace-specific status."""
        mock_server = MagicMock()
        loader = PersonaLoader(mock_server)
        loader.current_persona = "global_persona"
        loader.loaded_modules = {"mod1", "mod2"}
        loader._tool_to_module = {"t1": "mod1", "t2": "mod2"}
        mock_ctx = MagicMock()

        mock_ws_state = MagicMock()
        mock_ws_state.workspace_uri = "file:///workspace"
        mock_ws_state.persona = "devops"
        mock_ws_state.project = "my-project"
        mock_ws_state.active_tools = {"tool_a", "tool_b"}

        with patch(
            "server.workspace_state.WorkspaceRegistry",
        ) as mock_ws:
            mock_ws.get_for_ctx = AsyncMock(return_value=mock_ws_state)
            status = await loader.get_workspace_status(mock_ctx)

        assert status["workspace_uri"] == "file:///workspace"
        assert status["persona"] == "devops"
        assert status["project"] == "my-project"
        assert status["global_persona"] == "global_persona"
        assert status["tool_count"] == 2

    async def test_fallback_to_get_status(self):
        """Falls back to get_status() on exception."""
        mock_server = MagicMock()
        loader = PersonaLoader(mock_server)
        loader.current_persona = "fallback"
        mock_ctx = MagicMock()

        with patch(
            "server.workspace_state.WorkspaceRegistry",
        ) as mock_ws:
            mock_ws.get_for_ctx = AsyncMock(side_effect=Exception("no ws"))
            status = await loader.get_workspace_status(mock_ctx)

        assert status["current_persona"] == "fallback"
        assert "workspace_uri" not in status


# ---------------------------------------------------------------------------
# Tests for PersonaLoader.load_persona_config error handling
# ---------------------------------------------------------------------------


class TestLoadPersonaConfigErrors:
    """Tests for load_persona_config error handling."""

    def test_yaml_parse_error(self, tmp_path):
        """Returns None on YAML parse error."""
        mock_server = MagicMock()
        loader = PersonaLoader(mock_server)

        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text("{{invalid yaml:::")

        with patch("server.persona_loader.PERSONAS_DIR", tmp_path):
            result = loader.load_persona_config("bad")

        assert result is None


# ---------------------------------------------------------------------------
# Tests for get_status with populated state
# ---------------------------------------------------------------------------


class TestGetStatusPopulated:
    """Tests for get_status with populated state."""

    def test_status_reflects_loaded_state(self):
        """Status reflects loaded modules and tools."""
        mock_server = MagicMock()
        loader = PersonaLoader(mock_server)
        loader.current_persona = "devops"
        loader.loaded_modules = {"mod1", "mod2"}
        loader._tool_to_module = {"tool_a": "mod1", "tool_b": "mod2", "tool_c": "mod1"}

        status = loader.get_status()
        assert status["current_persona"] == "devops"
        assert len(status["loaded_modules"]) == 2
        assert status["tool_count"] == 3
        assert sorted(status["tools"]) == ["tool_a", "tool_b", "tool_c"]
