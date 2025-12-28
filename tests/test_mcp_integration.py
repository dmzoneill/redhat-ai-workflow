"""Integration tests for MCP tools.

These tests verify that MCP tool modules load correctly and register tools.
They don't test actual tool execution (which requires external services).
"""

import sys
from pathlib import Path

import pytest

# Add paths for imports
PROJECT_ROOT = Path(__file__).parent.parent
SERVERS_DIR = PROJECT_ROOT / "mcp-servers"
sys.path.insert(0, str(SERVERS_DIR / "aa-common"))


class TestMCPServerCreation:
    """Test that MCP servers can be created."""

    def test_common_server_imports(self):
        """Common server module should import successfully."""
        from src.server import create_mcp_server, setup_logging

        assert callable(create_mcp_server)
        assert callable(setup_logging)

    def test_create_workflow_server(self):
        """Workflow server should create successfully."""
        from src.server import create_mcp_server

        server = create_mcp_server(name="aa-workflow", tools=["workflow"])
        assert server is not None

    def test_utils_import(self):
        """Common utils should import."""
        from src.utils import (
            get_kubeconfig,
            get_project_root,
            load_config,
            resolve_repo_path,
        )

        assert callable(load_config)
        assert callable(get_project_root)
        assert callable(get_kubeconfig)
        assert callable(resolve_repo_path)


class TestToolModuleLoading:
    """Test that individual tool modules load correctly."""

    def _load_module(self, module_name: str):
        """Load a tool module using importlib."""
        import importlib.util

        tools_file = SERVERS_DIR / f"aa-{module_name}" / "src" / "tools.py"
        if not tools_file.exists():
            pytest.skip(f"Module aa-{module_name} not found")

        # Add aa-common to path for imports
        spec = importlib.util.spec_from_file_location(
            f"aa_{module_name}_tools", tools_file
        )
        if spec is None or spec.loader is None:
            pytest.fail(f"Could not create spec for {module_name}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_load_workflow_module(self):
        """Workflow tools module should load."""
        module = self._load_module("workflow")
        assert hasattr(module, "register_tools")

    def test_load_git_module(self):
        """Git tools module should load."""
        module = self._load_module("git")
        assert hasattr(module, "register_tools")

    def test_load_jira_module(self):
        """Jira tools module should load."""
        module = self._load_module("jira")
        assert hasattr(module, "register_tools")

    def test_load_gitlab_module(self):
        """GitLab tools module should load."""
        module = self._load_module("gitlab")
        assert hasattr(module, "register_tools")


class TestWorkflowExtractedModules:
    """Test that extracted workflow sub-modules work correctly."""

    def test_constants_import(self):
        """Constants module should define key paths."""
        # Add workflow to path
        sys.path.insert(0, str(SERVERS_DIR / "aa-workflow"))

        try:
            import importlib.util

            spec = importlib.util.spec_from_file_location(
                "constants",
                SERVERS_DIR / "aa-workflow" / "src" / "constants.py",
            )
            constants = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(constants)

            assert hasattr(constants, "MEMORY_DIR")
            assert hasattr(constants, "AGENTS_DIR")
            assert hasattr(constants, "SKILLS_DIR")
            assert constants.MEMORY_DIR.name == "memory"
            assert constants.AGENTS_DIR.name == "agents"
            assert constants.SKILLS_DIR.name == "skills"
        finally:
            # Clean up path
            if str(SERVERS_DIR / "aa-workflow") in sys.path:
                sys.path.remove(str(SERVERS_DIR / "aa-workflow"))

    def test_memory_tools_loadable(self):
        """Memory tools module should be loadable."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "memory_tools",
            SERVERS_DIR / "aa-workflow" / "src" / "memory_tools.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert hasattr(module, "register_memory_tools")
        assert callable(module.register_memory_tools)

    def test_agent_tools_loadable(self):
        """Agent tools module should be loadable."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "agent_tools",
            SERVERS_DIR / "aa-workflow" / "src" / "agent_tools.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert hasattr(module, "register_agent_tools")
        assert callable(module.register_agent_tools)

    def test_lint_tools_loadable(self):
        """Lint tools module should be loadable."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "lint_tools",
            SERVERS_DIR / "aa-workflow" / "src" / "lint_tools.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert hasattr(module, "register_lint_tools")
        assert callable(module.register_lint_tools)

    def test_infra_tools_loadable(self):
        """Infrastructure tools module should be loadable."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "infra_tools",
            SERVERS_DIR / "aa-workflow" / "src" / "infra_tools.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert hasattr(module, "register_infra_tools")
        assert callable(module.register_infra_tools)

    def test_workflow_tools_loadable(self):
        """Workflow tools module should be loadable."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "workflow_tools",
            SERVERS_DIR / "aa-workflow" / "src" / "workflow_tools.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert hasattr(module, "register_workflow_tools")
        assert callable(module.register_workflow_tools)


class TestConfigLoading:
    """Test configuration loading functionality."""

    def test_load_config_returns_dict(self):
        """load_config should return a dict."""
        from src.utils import load_config

        config = load_config()
        assert isinstance(config, dict)

    def test_config_has_repositories(self):
        """Config should have repositories section."""
        from src.utils import load_config

        config = load_config()
        assert "repositories" in config or isinstance(config.get("repositories"), dict)

    def test_get_section_config(self):
        """get_section_config should return section or default."""
        from src.utils import get_section_config

        result = get_section_config("nonexistent_section_xyz")
        assert result == {}

        result_with_default = get_section_config(
            "nonexistent_section_xyz", {"default": "value"}
        )
        assert result_with_default == {"default": "value"}


class TestKubeconfig:
    """Test kubeconfig path resolution."""

    def test_get_kubeconfig_stage(self):
        """Should return stage kubeconfig path."""
        from src.utils import get_kubeconfig

        path = get_kubeconfig("stage")
        assert path.endswith(".s") or "stage" in path.lower() or path.endswith("config")

    def test_get_kubeconfig_prod(self):
        """Should return prod kubeconfig path."""
        from src.utils import get_kubeconfig

        path = get_kubeconfig("prod")
        assert path.endswith(".p") or "prod" in path.lower() or path.endswith("config")

    def test_get_kubeconfig_ephemeral(self):
        """Should return ephemeral kubeconfig path."""
        from src.utils import get_kubeconfig

        path = get_kubeconfig("ephemeral")
        assert path.endswith(".e") or "ephemeral" in path.lower() or path.endswith("config")

