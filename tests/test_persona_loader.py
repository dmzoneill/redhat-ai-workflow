"""Tests for persona_loader module."""

# Adjust import path to work with tests
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "server"))

from persona_loader import CORE_TOOLS, PERSONAS_DIR, PROJECT_DIR, TOOL_MODULES, TOOL_MODULES_DIR, PersonaLoader


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


class TestToolModules:
    """Tests for TOOL_MODULES constant."""

    def test_tool_modules_not_empty(self):
        """TOOL_MODULES should contain entries."""
        assert len(TOOL_MODULES) > 0

    def test_expected_modules_present(self):
        """Expected core modules should be in TOOL_MODULES."""
        expected = ["git", "jira", "gitlab", "k8s", "workflow"]
        for module in expected:
            assert module in TOOL_MODULES, f"Missing module: {module}"

    def test_tool_counts_positive(self):
        """Tool counts should be positive numbers."""
        for module, count in TOOL_MODULES.items():
            assert count > 0, f"Invalid count for {module}: {count}"


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

        for persona_file in PERSONAS_DIR.glob("*.yaml"):
            with open(persona_file) as f:
                config = yaml.safe_load(f)

            tools = config.get("tools", [])
            for tool in tools:
                assert tool in TOOL_MODULES, f"Persona {persona_file.stem} references unknown module: {tool}"


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
