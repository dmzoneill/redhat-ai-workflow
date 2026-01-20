"""Tests for persona_loader module."""

# Adjust import path to work with tests
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "server"))

from persona_loader import (
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
        assert TOOL_MODULES_DIR.exists(), f"TOOL_MODULES_DIR does not exist: {TOOL_MODULES_DIR}"
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
                assert tool in available_modules, f"Persona {persona_file.stem} references unknown module: {tool}"


class TestGlobalLoader:
    """Tests for global loader functions."""

    def test_get_loader_initial(self):
        """get_loader should return None initially."""
        from persona_loader import get_loader

        # Note: This could be non-None if other tests ran first
        # Just verify it returns without error
        result = get_loader()
        assert result is None or isinstance(result, PersonaLoader)

    def test_init_loader(self):
        """init_loader should create and return loader."""
        from persona_loader import get_loader, init_loader

        mock_server = MagicMock()
        loader = init_loader(mock_server)

        assert isinstance(loader, PersonaLoader)
        assert loader.server == mock_server

        # Global should now be set
        assert get_loader() == loader
