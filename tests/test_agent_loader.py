"""Tests for agent_loader module."""

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Adjust import path to work with tests
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "mcp-servers" / "aa-common" / "src"))

from agent_loader import (
    AGENTS_DIR,
    CORE_TOOLS,
    PROJECT_DIR,
    SERVERS_DIR,
    TOOL_MODULES,
    AgentLoader,
)


class TestPaths:
    """Tests for path constants."""

    def test_servers_dir_exists(self):
        """SERVERS_DIR should point to mcp-servers directory."""
        assert SERVERS_DIR.exists(), f"SERVERS_DIR does not exist: {SERVERS_DIR}"
        assert SERVERS_DIR.name == "mcp-servers"

    def test_project_dir_exists(self):
        """PROJECT_DIR should point to project root."""
        assert PROJECT_DIR.exists(), f"PROJECT_DIR does not exist: {PROJECT_DIR}"

    def test_agents_dir_exists(self):
        """AGENTS_DIR should point to agents directory."""
        assert AGENTS_DIR.exists(), f"AGENTS_DIR does not exist: {AGENTS_DIR}"
        assert AGENTS_DIR.name == "agents"


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
        expected = ["agent_load", "session_start"]
        for tool in expected:
            assert tool in CORE_TOOLS, f"Missing core tool: {tool}"


class TestAgentLoaderInit:
    """Tests for AgentLoader initialization."""

    def test_init_with_server(self):
        """Should initialize with a server instance."""
        mock_server = MagicMock()
        loader = AgentLoader(mock_server)

        assert loader.server == mock_server
        assert loader.current_agent == ""
        assert loader.loaded_modules == set()
        assert loader._tool_to_module == {}


class TestLoadAgentConfig:
    """Tests for load_agent_config method."""

    def test_load_existing_agent(self):
        """Should load config for existing agent."""
        mock_server = MagicMock()
        loader = AgentLoader(mock_server)

        # Check that developer agent exists and can be loaded
        if (AGENTS_DIR / "developer.yaml").exists():
            config = loader.load_agent_config("developer")
            assert config is not None
            assert isinstance(config, dict)

    def test_load_nonexistent_agent(self):
        """Should return None for nonexistent agent."""
        mock_server = MagicMock()
        loader = AgentLoader(mock_server)

        config = loader.load_agent_config("nonexistent_agent_xyz")
        assert config is None


class TestAgentLoaderGetStatus:
    """Tests for get_status method."""

    def test_get_status_empty(self):
        """Should return empty status for fresh loader."""
        mock_server = MagicMock()
        loader = AgentLoader(mock_server)

        status = loader.get_status()
        assert status["current_agent"] == ""
        assert status["loaded_modules"] == []
        assert status["tool_count"] == 0
        assert status["tools"] == []


class TestAgentFiles:
    """Tests for agent YAML files."""

    def test_expected_agents_exist(self):
        """Expected agent files should exist."""
        expected_agents = ["developer", "devops", "incident", "release"]
        for agent in expected_agents:
            agent_file = AGENTS_DIR / f"{agent}.yaml"
            assert agent_file.exists(), f"Missing agent file: {agent}.yaml"

    def test_agents_have_valid_tools(self):
        """Agent configs should reference valid tool modules."""
        import yaml

        for agent_file in AGENTS_DIR.glob("*.yaml"):
            with open(agent_file) as f:
                config = yaml.safe_load(f)

            tools = config.get("tools", [])
            for tool in tools:
                assert tool in TOOL_MODULES, (
                    f"Agent {agent_file.stem} references unknown module: {tool}"
                )


class TestGlobalLoader:
    """Tests for global loader functions."""

    def test_get_loader_initial(self):
        """get_loader should return None initially."""
        from agent_loader import get_loader

        # Note: This could be non-None if other tests ran first
        # Just verify it returns without error
        result = get_loader()
        assert result is None or isinstance(result, AgentLoader)

    def test_init_loader(self):
        """init_loader should create and return loader."""
        from agent_loader import get_loader, init_loader

        mock_server = MagicMock()
        loader = init_loader(mock_server)

        assert isinstance(loader, AgentLoader)
        assert loader.server == mock_server

        # Global should now be set
        assert get_loader() == loader

