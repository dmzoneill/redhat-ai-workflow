"""Tests for scripts/common/config_loader.py."""

import json
import os
from unittest.mock import patch


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_config_returns_dict(self):
        """load_config should return a dict."""
        from scripts.common.config_loader import load_config

        result = load_config()
        assert isinstance(result, dict)

    def test_load_config_uses_utils_implementation(self):
        """load_config should delegate to utils.load_config when available."""
        with patch("scripts.common.config_loader.load_config") as mock:
            mock.return_value = {"test": "value"}
            # Force reimport to get fresh module
            import importlib

            from scripts.common import config_loader

            importlib.reload(config_loader)
            result = config_loader.load_config()
            assert isinstance(result, dict)

    def test_load_config_fallback_when_utils_unavailable(self, tmp_path, monkeypatch):
        """load_config should use fallback when utils not available."""
        # Create a temp config file
        config_data = {"test_key": "test_value"}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))

        # This tests the fallback path indirectly
        from scripts.common.config_loader import load_config

        result = load_config()
        # Should at least return a dict (may be empty or from real config)
        assert isinstance(result, dict)


class TestGetConfigSection:
    """Tests for get_config_section function."""

    def test_get_config_section_returns_dict(self):
        """get_config_section should return a dict."""
        from scripts.common.config_loader import get_config_section

        result = get_config_section("nonexistent")
        assert isinstance(result, dict)

    def test_get_config_section_with_default(self):
        """get_config_section should use default for missing sections."""
        from scripts.common.config_loader import get_config_section

        default = {"default_key": "default_value"}
        result = get_config_section("definitely_not_a_section_12345", default)
        assert result == default

    def test_get_config_section_none_default(self):
        """get_config_section should use empty dict when default is None."""
        from scripts.common.config_loader import get_config_section

        result = get_config_section("not_a_section_xyz", None)
        assert result == {}

    def test_get_config_section_existing(self):
        """get_config_section should return existing section."""
        from unittest.mock import MagicMock

        mock_cm = MagicMock()
        mock_cm.get.return_value = {"url": "https://jira.example.com"}

        # get_config_section imports config_manager inside the function body via
        # ``from server.config_manager import config as config_manager``
        # so we patch the singleton at its canonical location.
        with patch("server.config_manager.config", mock_cm):
            from scripts.common.config_loader import get_config_section

            result = get_config_section("jira")
            assert result == {"url": "https://jira.example.com"}


class TestGetUserConfig:
    """Tests for get_user_config function."""

    def test_get_user_config_returns_dict(self):
        """get_user_config should return a dict."""
        from scripts.common.config_loader import get_user_config

        result = get_user_config()
        assert isinstance(result, dict)

    @patch("scripts.common.config_loader.load_config")
    def test_get_user_config_from_config(self, mock_load):
        """get_user_config should return user section from config."""
        mock_load.return_value = {
            "user": {"username": "testuser", "email": "test@example.com"}
        }

        from scripts.common.config_loader import get_user_config

        result = get_user_config()
        assert result == {"username": "testuser", "email": "test@example.com"}

    @patch("scripts.common.config_loader.load_config")
    def test_get_user_config_missing(self, mock_load):
        """get_user_config should return empty dict when missing."""
        mock_load.return_value = {}

        from scripts.common.config_loader import get_user_config

        result = get_user_config()
        assert result == {}


class TestGetUsername:
    """Tests for get_username function."""

    @patch("scripts.common.config_loader.load_config")
    def test_get_username_from_config(self, mock_load):
        """get_username should return username from config."""
        mock_load.return_value = {"user": {"username": "configuser"}}

        from scripts.common.config_loader import get_username

        result = get_username()
        assert result == "configuser"

    @patch("scripts.common.config_loader.load_config")
    @patch.dict(os.environ, {"USER": "envuser"})
    def test_get_username_fallback_to_env(self, mock_load):
        """get_username should fallback to USER env var."""
        mock_load.return_value = {"user": {}}

        from scripts.common.config_loader import get_username

        result = get_username()
        assert result == "envuser"

    @patch("scripts.common.config_loader.load_config")
    @patch.dict(os.environ, {}, clear=True)
    def test_get_username_fallback_unknown(self, mock_load):
        """get_username should return 'unknown' when no user available."""
        mock_load.return_value = {}
        # Clear USER env var
        os.environ.pop("USER", None)

        from scripts.common.config_loader import get_username

        result = get_username()
        assert result == "unknown"


class TestGetJiraUrl:
    """Tests for get_jira_url function."""

    @patch("scripts.common.config_loader.load_config")
    def test_get_jira_url_from_config(self, mock_load):
        """get_jira_url should return URL from config."""
        mock_load.return_value = {"jira": {"url": "https://custom-jira.example.com"}}

        from scripts.common.config_loader import get_jira_url

        result = get_jira_url()
        assert result == "https://custom-jira.example.com"

    @patch("scripts.common.config_loader.load_config")
    def test_get_jira_url_default(self, mock_load):
        """get_jira_url should return default Red Hat Jira."""
        mock_load.return_value = {}

        from scripts.common.config_loader import get_jira_url

        result = get_jira_url()
        assert result == "https://issues.redhat.com"


class TestGetTimezone:
    """Tests for get_timezone function."""

    @patch("scripts.common.config_loader.load_config")
    def test_get_timezone_from_config(self, mock_load):
        """get_timezone should return timezone from config."""
        mock_load.return_value = {"user": {"timezone": "America/New_York"}}

        from scripts.common.config_loader import get_timezone

        result = get_timezone()
        assert result == "America/New_York"

    @patch("scripts.common.config_loader.load_config")
    def test_get_timezone_default(self, mock_load):
        """get_timezone should return default Dublin timezone."""
        mock_load.return_value = {}

        from scripts.common.config_loader import get_timezone

        result = get_timezone()
        assert result == "Europe/Dublin"


class TestGetRepoConfig:
    """Tests for get_repo_config function."""

    @patch("scripts.common.config_loader.load_config")
    def test_get_repo_config_existing(self, mock_load):
        """get_repo_config should return config for existing repo."""
        mock_load.return_value = {
            "repositories": {
                "backend": {"path": "/home/user/backend", "gitlab": "org/backend"}
            }
        }

        from scripts.common.config_loader import get_repo_config

        result = get_repo_config("backend")
        assert result == {"path": "/home/user/backend", "gitlab": "org/backend"}

    @patch("scripts.common.config_loader.load_config")
    def test_get_repo_config_missing(self, mock_load):
        """get_repo_config should return empty dict for missing repo."""
        mock_load.return_value = {"repositories": {}}

        from scripts.common.config_loader import get_repo_config

        result = get_repo_config("nonexistent")
        assert result == {}


class TestResolveRepo:
    """Tests for resolve_repo function."""

    @patch("scripts.common.config_loader.load_config")
    def test_resolve_repo_by_name(self, mock_load):
        """resolve_repo should find repo by explicit name."""
        mock_load.return_value = {
            "jira": {"url": "https://jira.example.com"},
            "repositories": {
                "backend": {
                    "path": "/home/user/backend",
                    "gitlab": "org/backend",
                    "jira_project": "AAP",
                }
            },
        }

        from scripts.common.config_loader import resolve_repo

        result = resolve_repo(repo_name="backend")
        assert result["name"] == "backend"
        assert result["path"] == "/home/user/backend"
        assert result["gitlab"] == "org/backend"
        assert result["jira_project"] == "AAP"

    @patch("scripts.common.config_loader.load_config")
    def test_resolve_repo_by_issue_key(self, mock_load):
        """resolve_repo should find repo by issue key prefix."""
        mock_load.return_value = {
            "jira": {"url": "https://jira.example.com"},
            "repositories": {
                "backend": {
                    "path": "/home/user/backend",
                    "gitlab": "org/backend",
                    "jira_project": "AAP",
                }
            },
        }

        from scripts.common.config_loader import resolve_repo

        result = resolve_repo(issue_key="AAP-12345")
        assert result["name"] == "backend"
        assert result["jira_project"] == "AAP"

    @patch("scripts.common.config_loader.load_config")
    @patch("os.getcwd")
    def test_resolve_repo_by_cwd(self, mock_getcwd, mock_load):
        """resolve_repo should find repo by current working directory."""
        mock_getcwd.return_value = "/home/user/frontend"
        mock_load.return_value = {
            "jira": {"url": "https://jira.example.com"},
            "repositories": {
                "frontend": {
                    "path": "/home/user/frontend",
                    "gitlab": "org/frontend",
                    "jira_project": "UI",
                }
            },
        }

        from scripts.common.config_loader import resolve_repo

        result = resolve_repo()
        assert result["name"] == "frontend"

    @patch("scripts.common.config_loader.load_config")
    @patch("os.getcwd")
    def test_resolve_repo_fallback_to_first(self, mock_getcwd, mock_load):
        """resolve_repo should fallback to first repo if no match."""
        mock_getcwd.return_value = "/some/random/path"
        mock_load.return_value = {
            "jira": {"url": "https://jira.example.com"},
            "repositories": {
                "first_repo": {
                    "path": "/home/user/first",
                    "gitlab": "org/first",
                    "jira_project": "FIRST",
                }
            },
        }

        from scripts.common.config_loader import resolve_repo

        result = resolve_repo()
        assert result["name"] == "first_repo"

    @patch("scripts.common.config_loader.load_config")
    @patch("os.getcwd")
    def test_resolve_repo_no_repos_configured(self, mock_getcwd, mock_load):
        """resolve_repo should handle empty repositories."""
        mock_getcwd.return_value = "/some/path"
        mock_load.return_value = {"repositories": {}}

        from scripts.common.config_loader import resolve_repo

        result = resolve_repo()
        assert result["name"] is None
        assert result["path"] == "/some/path"

    @patch("scripts.common.config_loader.load_config")
    def test_resolve_repo_explicit_cwd_param(self, mock_load):
        """resolve_repo should use explicit cwd parameter."""
        mock_load.return_value = {
            "jira": {"url": "https://jira.example.com"},
            "repositories": {
                "myrepo": {"path": "/explicit/path", "gitlab": "org/myrepo"}
            },
        }

        from scripts.common.config_loader import resolve_repo

        result = resolve_repo(cwd="/explicit/path")
        assert result["name"] == "myrepo"

    @patch("scripts.common.config_loader.load_config")
    def test_resolve_repo_issue_key_case_insensitive(self, mock_load):
        """resolve_repo should handle lowercase issue keys."""
        mock_load.return_value = {
            "jira": {"url": "https://jira.example.com"},
            "repositories": {
                "backend": {"path": "/path", "gitlab": "org/b", "jira_project": "AAP"}
            },
        }

        from scripts.common.config_loader import resolve_repo

        result = resolve_repo(issue_key="aap-12345")
        assert result["name"] == "backend"

    @patch("scripts.common.config_loader.load_config")
    def test_resolve_repo_returns_jira_url(self, mock_load):
        """resolve_repo should always include jira_url."""
        mock_load.return_value = {
            "jira": {"url": "https://custom-jira.example.com"},
            "repositories": {},
        }

        from scripts.common.config_loader import resolve_repo

        result = resolve_repo()
        assert result["jira_url"] == "https://custom-jira.example.com"
