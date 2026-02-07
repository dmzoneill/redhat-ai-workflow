"""Integration tests for MCP tools.

These tests verify that MCP tool modules load correctly and register tools.
They don't test actual tool execution (which requires external services).
"""

import sys
from pathlib import Path

import pytest

# Add paths for imports
PROJECT_ROOT = Path(__file__).parent.parent
TOOL_MODULES_DIR = PROJECT_ROOT / "tool_modules"
sys.path.insert(0, str(PROJECT_ROOT))


class TestMCPServerCreation:
    """Test that MCP servers can be created."""

    def test_common_server_imports(self):
        """Common server module should import successfully."""
        from server.main import create_mcp_server, setup_logging

        assert callable(create_mcp_server)
        assert callable(setup_logging)

    def test_create_workflow_server(self):
        """Workflow server should create successfully."""
        from server.main import create_mcp_server

        server = create_mcp_server(name="aa_workflow", tools=["workflow"])
        assert server is not None

    def test_utils_import(self):
        """Common utils should import."""
        from server.utils import (
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

        # Try tools_basic.py first (new structure), then tools.py (legacy)
        tools_file = TOOL_MODULES_DIR / f"aa_{module_name}" / "src" / "tools_basic.py"
        if not tools_file.exists():
            tools_file = TOOL_MODULES_DIR / f"aa_{module_name}" / "src" / "tools.py"
        if not tools_file.exists():
            pytest.skip(f"Module aa_{module_name} not found")

        # Add server to path for imports
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
        sys.path.insert(0, str(TOOL_MODULES_DIR / "aa_workflow"))

        try:
            import importlib.util

            spec = importlib.util.spec_from_file_location(
                "constants",
                TOOL_MODULES_DIR / "aa_workflow" / "src" / "constants.py",
            )
            constants = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(constants)

            assert hasattr(constants, "MEMORY_DIR")
            assert hasattr(constants, "PERSONAS_DIR")
            assert hasattr(constants, "SKILLS_DIR")
            assert constants.MEMORY_DIR.name == "memory"
            assert constants.PERSONAS_DIR.name == "personas"
            assert constants.SKILLS_DIR.name == "skills"
        finally:
            # Clean up path
            if str(TOOL_MODULES_DIR / "aa_workflow") in sys.path:
                sys.path.remove(str(TOOL_MODULES_DIR / "aa_workflow"))

    def test_memory_tools_loadable(self):
        """Memory tools module should be loadable."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "memory_tools",
            TOOL_MODULES_DIR / "aa_workflow" / "src" / "memory_tools.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert hasattr(module, "register_memory_tools")
        assert callable(module.register_memory_tools)

    def test_persona_tools_loadable(self):
        """Persona tools module should be loadable."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "persona_tools",
            TOOL_MODULES_DIR / "aa_workflow" / "src" / "persona_tools.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert hasattr(module, "register_persona_tools")
        assert callable(module.register_persona_tools)

    def test_lint_tools_loadable(self):
        """Lint tools module should be loadable."""
        import importlib.util

        # Try tools_basic.py first (new structure), fallback to tools.py (legacy)
        tools_file = TOOL_MODULES_DIR / "aa_lint" / "src" / "tools_basic.py"
        if not tools_file.exists():
            tools_file = TOOL_MODULES_DIR / "aa_lint" / "src" / "tools.py"

        spec = importlib.util.spec_from_file_location(
            "lint_tools",
            tools_file,
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert hasattr(module, "register_tools")
        assert callable(module.register_tools)

    def test_infra_tools_loadable(self):
        """Infrastructure tools module should be loadable."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "infra_tools",
            TOOL_MODULES_DIR / "aa_workflow" / "src" / "infra_tools.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert hasattr(module, "register_infra_tools")
        assert callable(module.register_infra_tools)

    def test_dev_workflow_tools_loadable(self):
        """Dev workflow tools module should be loadable."""
        import importlib.util

        # Try tools_extra.py first (since dev_workflow has only unused tools)
        # Fallback to tools_basic.py or tools.py (legacy)
        tools_file = TOOL_MODULES_DIR / "aa_dev_workflow" / "src" / "tools_extra.py"
        if not tools_file.exists():
            tools_file = TOOL_MODULES_DIR / "aa_dev_workflow" / "src" / "tools_basic.py"
        if not tools_file.exists():
            tools_file = TOOL_MODULES_DIR / "aa_dev_workflow" / "src" / "tools.py"

        spec = importlib.util.spec_from_file_location(
            "dev_workflow_tools",
            tools_file,
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert hasattr(module, "register_tools")
        assert callable(module.register_tools)


class TestConfigLoading:
    """Test configuration loading functionality."""

    def test_load_config_returns_dict(self):
        """load_config should return a dict."""
        from server.utils import load_config

        config = load_config()
        assert isinstance(config, dict)

    def test_config_has_repositories(self):
        """Config should have repositories section."""
        from server.utils import load_config

        config = load_config(reload=True)
        assert "repositories" in config or isinstance(config.get("repositories"), dict)

    def test_get_section_config(self):
        """get_section_config should return section or default."""
        from server.utils import get_section_config

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
        from server.utils import get_kubeconfig

        path = get_kubeconfig("stage")
        assert path.endswith(".s") or "stage" in path.lower() or path.endswith("config")

    def test_get_kubeconfig_prod(self):
        """Should return prod kubeconfig path."""
        from server.utils import get_kubeconfig

        path = get_kubeconfig("prod")
        assert path.endswith(".p") or "prod" in path.lower() or path.endswith("config")

    def test_get_kubeconfig_ephemeral(self):
        """Should return ephemeral kubeconfig path."""
        from server.utils import get_kubeconfig

        path = get_kubeconfig("ephemeral")
        assert (
            path.endswith(".e")
            or "ephemeral" in path.lower()
            or path.endswith("config")
        )
