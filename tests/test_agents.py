"""Tests for agent YAML definitions."""

import pytest
import yaml


class TestAgentFiles:
    """Tests for agent YAML file structure."""

    def get_agent_files(self, personas_dir):
        """Get all agent YAML files."""
        return list(personas_dir.glob("*.yaml"))

    def test_personas_directory_exists(self, personas_dir):
        """Agents directory should exist."""
        assert personas_dir.exists()

    def test_agents_exist(self, personas_dir):
        """Should have at least one agent defined."""
        agents = self.get_agent_files(personas_dir)
        assert len(agents) > 0, "No agent files found"

    def test_all_agents_valid_yaml(self, personas_dir):
        """All agent files should be valid YAML."""
        for agent_file in self.get_agent_files(personas_dir):
            content = agent_file.read_text()
            try:
                data = yaml.safe_load(content)
                assert data is not None, f"{agent_file.name} is empty"
            except yaml.YAMLError as e:
                pytest.fail(f"{agent_file.name} has invalid YAML: {e}")

    def test_agents_have_required_fields(self, personas_dir):
        """Agents should have required fields."""
        required = ["name", "tools"]
        for agent_file in self.get_agent_files(personas_dir):
            content = agent_file.read_text()
            data = yaml.safe_load(content)
            for field in required:
                assert field in data, f"{agent_file.name} missing '{field}'"


class TestCoreAgents:
    """Tests for specific important agents."""

    def test_developer_agent_exists(self, personas_dir):
        """The developer agent should exist."""
        developer = personas_dir / "developer.yaml"
        assert developer.exists(), "developer.yaml not found"

    def test_devops_agent_exists(self, personas_dir):
        """The devops agent should exist."""
        devops = personas_dir / "devops.yaml"
        assert devops.exists(), "devops.yaml not found"

    def test_developer_has_git_tools(self, personas_dir):
        """Developer agent should include git tools."""
        developer = personas_dir / "developer.yaml"
        if developer.exists():
            content = developer.read_text()
            data = yaml.safe_load(content)
            tools = data.get("tools", [])
            assert "git" in tools, "Developer should have git tools"

    def test_devops_has_k8s_tools(self, personas_dir):
        """DevOps agent should include k8s tools."""
        devops = personas_dir / "devops.yaml"
        if devops.exists():
            content = devops.read_text()
            data = yaml.safe_load(content)
            tools = data.get("tools", [])
            assert "k8s" in tools, "DevOps should have k8s tools"
