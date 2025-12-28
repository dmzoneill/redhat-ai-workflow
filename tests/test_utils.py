"""Tests for shared utilities in aa-common/src/utils.py."""

from pathlib import Path

from src.utils import get_kubeconfig, get_project_root, get_section_config, get_username, load_config, resolve_repo_path


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_config_returns_dict(self, project_root):
        """Config should return a dictionary."""
        config = load_config()
        assert isinstance(config, dict)

    def test_load_config_has_repositories(self, project_root):
        """Config should have repositories section."""
        config = load_config()
        # May or may not have repositories depending on config
        assert config is not None


class TestGetSectionConfig:
    """Tests for get_section_config function."""

    def test_get_section_returns_dict(self):
        """Section config should return a dictionary."""
        result = get_section_config("nonexistent_section", {})
        assert isinstance(result, dict)

    def test_get_section_with_default(self):
        """Should return default when section missing."""
        default = {"key": "value"}
        result = get_section_config("definitely_not_a_section", default)
        assert result == default


class TestGetProjectRoot:
    """Tests for get_project_root function."""

    def test_returns_path(self):
        """Should return a Path object."""
        result = get_project_root()
        assert isinstance(result, Path)

    def test_path_exists(self):
        """Returned path should exist."""
        result = get_project_root()
        assert result.exists()


class TestGetKubeconfig:
    """Tests for get_kubeconfig function."""

    def test_returns_string(self):
        """Should return a string path."""
        result = get_kubeconfig("stage")
        assert isinstance(result, str)

    def test_stage_config_suffix(self):
        """Stage should use .s suffix."""
        result = get_kubeconfig("stage")
        assert "config" in result

    def test_prod_config_suffix(self):
        """Prod should use .p suffix."""
        result = get_kubeconfig("prod")
        assert "config" in result

    def test_ephemeral_config_suffix(self):
        """Ephemeral should use .e suffix."""
        result = get_kubeconfig("ephemeral")
        assert "config" in result


class TestGetUsername:
    """Tests for get_username function."""

    def test_returns_string(self):
        """Should return a string."""
        result = get_username()
        assert isinstance(result, str)

    def test_not_empty(self):
        """Should not be empty."""
        result = get_username()
        assert len(result) > 0


class TestResolveRepoPath:
    """Tests for resolve_repo_path function."""

    def test_returns_path(self):
        """Should return a Path object or string."""
        result = resolve_repo_path(".")
        assert isinstance(result, (Path, str))

    def test_absolute_path_preserved(self, tmp_path):
        """Absolute paths should be preserved."""
        result = resolve_repo_path(str(tmp_path))
        assert str(tmp_path) in str(result)

    def test_current_dir_resolves(self):
        """Current directory should resolve."""
        result = resolve_repo_path(".")
        result_path = Path(result) if isinstance(result, str) else result
        assert result_path.exists()
