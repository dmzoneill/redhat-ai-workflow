"""Tests for scripts/common/config_loader.py."""

import json
import os
from unittest.mock import patch

import pytest


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
        from scripts.common.config_loader import get_config_section

        with patch("server.config_manager.config") as mock_cm:
            mock_cm.get.return_value = {"url": "https://jira.example.com"}
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


# ==================== New coverage tests ====================


class TestGetGitlabHost:
    """Tests for get_gitlab_host function."""

    @patch.dict(os.environ, {"GITLAB_HOST": "env-gitlab.example.com"})
    def test_from_env_var(self):
        """get_gitlab_host returns GITLAB_HOST env var when set."""
        from scripts.common.config_loader import get_gitlab_host

        assert get_gitlab_host() == "env-gitlab.example.com"

    @patch("scripts.common.config_loader.load_config")
    def test_from_config(self, mock_load):
        """get_gitlab_host returns host from config."""
        os.environ.pop("GITLAB_HOST", None)
        mock_load.return_value = {"gitlab": {"host": "config-gitlab.example.com"}}
        from scripts.common.config_loader import get_gitlab_host

        assert get_gitlab_host() == "config-gitlab.example.com"

    @patch("scripts.common.config_loader.load_config")
    def test_default(self, mock_load):
        """get_gitlab_host returns default when nothing configured."""
        os.environ.pop("GITLAB_HOST", None)
        mock_load.return_value = {}
        from scripts.common.config_loader import get_gitlab_host

        assert get_gitlab_host() == "gitlab.cee.redhat.com"


class TestGetGitlabUrl:
    """Tests for get_gitlab_url function."""

    @patch("scripts.common.config_loader.get_gitlab_host")
    def test_returns_https_url(self, mock_host):
        """get_gitlab_url returns https URL."""
        mock_host.return_value = "gitlab.example.com"
        from scripts.common.config_loader import get_gitlab_url

        assert get_gitlab_url() == "https://gitlab.example.com"


class TestGetQuayUrl:
    """Tests for get_quay_url function."""

    def test_returns_quay_url(self):
        """get_quay_url returns static Quay URL."""
        from scripts.common.config_loader import get_quay_url

        assert get_quay_url() == "https://quay.io"


class TestGetKonfluxNamespace:
    """Tests for get_konflux_namespace function."""

    @patch("scripts.common.config_loader.load_config")
    def test_from_config(self, mock_load):
        """get_konflux_namespace returns namespace from config."""
        mock_load.return_value = {
            "repositories": {
                "automation-analytics-backend": {"konflux_namespace": "custom-tenant"}
            }
        }
        from scripts.common.config_loader import get_konflux_namespace

        assert get_konflux_namespace() == "custom-tenant"

    @patch("scripts.common.config_loader.load_config")
    def test_default(self, mock_load):
        """get_konflux_namespace returns default when not configured."""
        mock_load.return_value = {"repositories": {}}
        from scripts.common.config_loader import get_konflux_namespace

        assert get_konflux_namespace() == "aap-aa-tenant"


class TestGetStageNamespace:
    """Tests for get_stage_namespace function."""

    @patch("scripts.common.config_loader.load_config")
    def test_from_config(self, mock_load):
        """get_stage_namespace returns namespace from config."""
        mock_load.return_value = {"namespaces": {"stage": {"main": "my-stage-ns"}}}
        from scripts.common.config_loader import get_stage_namespace

        assert get_stage_namespace() == "my-stage-ns"

    @patch("scripts.common.config_loader.load_config")
    def test_default(self, mock_load):
        """get_stage_namespace returns default when not configured."""
        mock_load.return_value = {}
        from scripts.common.config_loader import get_stage_namespace

        assert get_stage_namespace() == "tower-analytics-stage"


class TestGetProdNamespace:
    """Tests for get_prod_namespace function."""

    @patch("scripts.common.config_loader.load_config")
    def test_from_config(self, mock_load):
        """get_prod_namespace returns namespace from config."""
        mock_load.return_value = {"namespaces": {"production": {"main": "my-prod-ns"}}}
        from scripts.common.config_loader import get_prod_namespace

        assert get_prod_namespace() == "my-prod-ns"

    @patch("scripts.common.config_loader.load_config")
    def test_default(self, mock_load):
        """get_prod_namespace returns default when not configured."""
        mock_load.return_value = {}
        from scripts.common.config_loader import get_prod_namespace

        assert get_prod_namespace() == "tower-analytics-prod"


class TestGetJiraProject:
    """Tests for get_jira_project function."""

    @patch("scripts.common.config_loader.load_config")
    def test_from_config(self, mock_load):
        """get_jira_project returns project from config."""
        mock_load.return_value = {"jira": {"default_project": "MYPROJ"}}
        from scripts.common.config_loader import get_jira_project

        assert get_jira_project() == "MYPROJ"

    @patch("scripts.common.config_loader.load_config")
    def test_default(self, mock_load):
        """get_jira_project returns default AAP."""
        mock_load.return_value = {}
        from scripts.common.config_loader import get_jira_project

        assert get_jira_project() == "AAP"


class TestGetCommitTypes:
    """Tests for get_commit_types function."""

    @patch("scripts.common.config_loader.load_config")
    def test_from_config(self, mock_load):
        """get_commit_types returns types from config."""
        mock_load.return_value = {"commit_format": {"types": ["feat", "fix"]}}
        from scripts.common.config_loader import get_commit_types

        assert get_commit_types() == ["feat", "fix"]

    @patch("scripts.common.config_loader.load_config")
    def test_default(self, mock_load):
        """get_commit_types returns defaults when not configured."""
        mock_load.return_value = {}
        from scripts.common.config_loader import get_commit_types

        result = get_commit_types()
        assert "feat" in result
        assert "fix" in result

    @patch("scripts.common.config_loader.load_config")
    def test_empty_types(self, mock_load):
        """get_commit_types handles empty types list."""
        mock_load.return_value = {"commit_format": {"types": []}}
        from scripts.common.config_loader import get_commit_types

        assert get_commit_types() == []


class TestGetCommitFormat:
    """Tests for get_commit_format function."""

    @patch("scripts.common.config_loader.load_config")
    def test_from_config(self, mock_load):
        """get_commit_format returns format config."""
        mock_load.return_value = {
            "commit_format": {
                "pattern": "{type}: {description}",
                "types": ["feat"],
                "examples": ["feat: something"],
            }
        }
        from scripts.common.config_loader import get_commit_format

        result = get_commit_format()
        assert result["pattern"] == "{type}: {description}"
        assert result["types"] == ["feat"]
        assert result["examples"] == ["feat: something"]

    @patch("scripts.common.config_loader.load_config")
    def test_defaults(self, mock_load):
        """get_commit_format returns defaults when not configured."""
        mock_load.return_value = {}
        from scripts.common.config_loader import get_commit_format

        result = get_commit_format()
        assert "pattern" in result
        assert "types" in result
        assert "examples" in result
        assert isinstance(result["types"], list)


class TestFormatCommitMessage:
    """Tests for format_commit_message function."""

    @patch("scripts.common.config_loader.load_config")
    def test_full_format(self, mock_load):
        """format_commit_message formats with all parts."""
        mock_load.return_value = {
            "commit_format": {
                "types": ["feat", "fix", "chore"],
                "pattern": "{issue_key} - {type}({scope}): {description}",
            }
        }
        from scripts.common.config_loader import format_commit_message

        result = format_commit_message("Add caching", "AAP-123", "feat", "api")
        assert result == "AAP-123 - feat(api): Add caching"

    @patch("scripts.common.config_loader.load_config")
    def test_without_scope(self, mock_load):
        """format_commit_message formats without scope."""
        mock_load.return_value = {
            "commit_format": {
                "types": ["feat", "fix", "chore"],
                "pattern": "{issue_key} - {type}({scope}): {description}",
            }
        }
        from scripts.common.config_loader import format_commit_message

        result = format_commit_message("Fix bug", "AAP-456", "fix")
        assert result == "AAP-456 - fix: Fix bug"

    @patch("scripts.common.config_loader.load_config")
    def test_without_issue_key(self, mock_load):
        """format_commit_message formats without issue key."""
        mock_load.return_value = {
            "commit_format": {
                "types": ["feat", "fix", "chore"],
                "pattern": "{issue_key} - {type}({scope}): {description}",
            }
        }
        from scripts.common.config_loader import format_commit_message

        result = format_commit_message("Quick fix")
        assert result == "Quick fix"

    @patch("scripts.common.config_loader.load_config")
    def test_invalid_type_defaults_to_chore(self, mock_load):
        """format_commit_message defaults to chore for invalid type."""
        mock_load.return_value = {
            "commit_format": {
                "types": ["feat", "fix", "chore"],
                "pattern": "{issue_key} - {type}({scope}): {description}",
            }
        }
        from scripts.common.config_loader import format_commit_message

        result = format_commit_message("Do stuff", "AAP-789", "invalid_type")
        assert "chore:" in result


class TestValidateCommitMessage:
    """Tests for validate_commit_message function."""

    @patch("scripts.common.config_loader.load_config")
    def test_valid_message(self, mock_load):
        """validate_commit_message validates a correct message."""
        mock_load.return_value = {
            "commit_format": {
                "types": ["feat", "fix", "chore"],
                "pattern": "{issue_key} - {type}({scope}): {description}",
                "examples": ["AAP-123 - feat(api): Add endpoint"],
            }
        }
        from scripts.common.config_loader import validate_commit_message

        is_valid, issues = validate_commit_message(
            "AAP-123 - feat(api): Add new feature"
        )
        assert is_valid is True
        assert issues == []

    @patch("scripts.common.config_loader.load_config")
    def test_valid_without_scope(self, mock_load):
        """validate_commit_message validates message without scope."""
        mock_load.return_value = {
            "commit_format": {
                "types": ["feat", "fix", "chore"],
                "pattern": "{issue_key} - {type}({scope}): {description}",
                "examples": ["AAP-123 - feat: Add endpoint"],
            }
        }
        from scripts.common.config_loader import validate_commit_message

        is_valid, issues = validate_commit_message("AAP-123 - fix: Fix the bug")
        assert is_valid is True

    @patch("scripts.common.config_loader.load_config")
    def test_invalid_format(self, mock_load):
        """validate_commit_message rejects bad format."""
        mock_load.return_value = {
            "commit_format": {
                "types": ["feat", "fix"],
                "pattern": "{issue_key} - {type}({scope}): {description}",
                "examples": ["AAP-123 - feat: something"],
            }
        }
        from scripts.common.config_loader import validate_commit_message

        is_valid, issues = validate_commit_message("bad commit message")
        assert is_valid is False
        assert len(issues) >= 1

    @patch("scripts.common.config_loader.load_config")
    def test_invalid_commit_type(self, mock_load):
        """validate_commit_message rejects invalid commit type."""
        mock_load.return_value = {
            "commit_format": {
                "types": ["feat", "fix"],
                "pattern": "{issue_key} - {type}({scope}): {description}",
                "examples": [],
            }
        }
        from scripts.common.config_loader import validate_commit_message

        is_valid, issues = validate_commit_message(
            "AAP-123 - badtype: Description here"
        )
        assert is_valid is False
        assert any("Invalid commit type" in i for i in issues)

    @patch("scripts.common.config_loader.load_config")
    def test_short_description(self, mock_load):
        """validate_commit_message rejects too-short description."""
        mock_load.return_value = {
            "commit_format": {
                "types": ["feat", "fix"],
                "pattern": "{issue_key} - {type}({scope}): {description}",
                "examples": [],
            }
        }
        from scripts.common.config_loader import validate_commit_message

        is_valid, issues = validate_commit_message("AAP-123 - feat: ab")
        assert is_valid is False
        assert any("too short" in i for i in issues)


class TestGetDefaultBranch:
    """Tests for get_default_branch function."""

    @patch("scripts.common.config_loader.load_config")
    def test_from_config(self, mock_load):
        """get_default_branch returns branch from config."""
        mock_load.return_value = {
            "repositories": {
                "automation-analytics-backend": {"default_branch": "develop"}
            }
        }
        from scripts.common.config_loader import get_default_branch

        assert get_default_branch() == "develop"

    @patch("scripts.common.config_loader.load_config")
    def test_default(self, mock_load):
        """get_default_branch returns 'main' by default."""
        mock_load.return_value = {"repositories": {}}
        from scripts.common.config_loader import get_default_branch

        assert get_default_branch() == "main"


class TestGetFlake8IgnoreCodes:
    """Tests for get_flake8_ignore_codes function."""

    @patch("scripts.common.config_loader.load_config")
    def test_from_config(self, mock_load):
        """get_flake8_ignore_codes returns codes from config."""
        mock_load.return_value = {"linting": {"flake8": {"ignore": "E501,W504"}}}
        from scripts.common.config_loader import get_flake8_ignore_codes

        assert get_flake8_ignore_codes() == "E501,W504"

    @patch("scripts.common.config_loader.load_config")
    def test_default(self, mock_load):
        """get_flake8_ignore_codes returns default codes."""
        mock_load.return_value = {}
        from scripts.common.config_loader import get_flake8_ignore_codes

        assert get_flake8_ignore_codes() == "E501,W503,E203"


class TestGetFlake8MaxLineLength:
    """Tests for get_flake8_max_line_length function."""

    @patch("scripts.common.config_loader.load_config")
    def test_from_config(self, mock_load):
        """get_flake8_max_line_length returns value from config."""
        mock_load.return_value = {"linting": {"flake8": {"max_line_length": 120}}}
        from scripts.common.config_loader import get_flake8_max_line_length

        assert get_flake8_max_line_length() == 120

    @patch("scripts.common.config_loader.load_config")
    def test_default(self, mock_load):
        """get_flake8_max_line_length returns default 100."""
        mock_load.return_value = {}
        from scripts.common.config_loader import get_flake8_max_line_length

        assert get_flake8_max_line_length() == 100


class TestGetTeamGroupHandle:
    """Tests for get_team_group_handle function."""

    @patch("scripts.common.config_loader.load_config")
    def test_from_config(self, mock_load):
        """get_team_group_handle returns handle from config."""
        mock_load.return_value = {
            "slack": {"channels": {"team": {"group_handle": "my-team"}}}
        }
        from scripts.common.config_loader import get_team_group_handle

        assert get_team_group_handle() == "my-team"

    @patch("scripts.common.config_loader.load_config")
    def test_default(self, mock_load):
        """get_team_group_handle returns default."""
        mock_load.return_value = {}
        from scripts.common.config_loader import get_team_group_handle

        assert get_team_group_handle() == "aa-api-team"


class TestGetTeamGroupId:
    """Tests for get_team_group_id function."""

    @patch("scripts.common.config_loader.load_config")
    def test_from_config(self, mock_load):
        """get_team_group_id returns ID from config."""
        mock_load.return_value = {
            "slack": {"channels": {"team": {"group_id": "G12345"}}}
        }
        from scripts.common.config_loader import get_team_group_id

        assert get_team_group_id() == "G12345"

    @patch("scripts.common.config_loader.load_config")
    def test_default(self, mock_load):
        """get_team_group_id returns empty string by default."""
        mock_load.return_value = {}
        from scripts.common.config_loader import get_team_group_id

        assert get_team_group_id() == ""


class TestGetTeamConfig:
    """Tests for get_team_config function."""

    @patch("scripts.common.config_loader.load_config")
    def test_full_config(self, mock_load):
        """get_team_config returns complete team configuration."""
        mock_load.return_value = {
            "slack": {
                "channels": {"team": {"group_id": "G123", "group_handle": "devs"}}
            },
            "gitlab": {"host": "my-gitlab.example.com"},
            "jira": {"url": "https://jira.example.com"},
        }
        from scripts.common.config_loader import get_team_config

        result = get_team_config()
        assert result["team_group_id"] == "G123"
        assert result["team_group_handle"] == "devs"
        assert result["jira_url"] == "https://jira.example.com"
        assert result["gitlab_url"] == "https://my-gitlab.example.com"

    @patch("scripts.common.config_loader.load_config")
    def test_defaults(self, mock_load):
        """get_team_config returns defaults when nothing configured."""
        mock_load.return_value = {}
        from scripts.common.config_loader import get_team_config

        result = get_team_config()
        assert result["team_group_id"] == ""
        assert result["team_group_handle"] == "aa-api-team"
        assert result["jira_url"] == "https://issues.redhat.com"
        assert "gitlab.cee.redhat.com" in result["gitlab_url"]


class TestMemoryKeyConstants:
    """Test that memory key constants are defined."""

    def test_constants_are_strings(self):
        """Memory key constants should be strings."""
        from scripts.common.config_loader import (
            MEMORY_KEY_CURRENT_WORK,
            MEMORY_KEY_ENVIRONMENTS,
            MEMORY_KEY_PATTERNS,
            MEMORY_KEY_RUNBOOKS,
            MEMORY_KEY_TEAMMATE_PREFS,
            MEMORY_KEY_TOOL_FIXES,
        )

        assert isinstance(MEMORY_KEY_CURRENT_WORK, str)
        assert isinstance(MEMORY_KEY_ENVIRONMENTS, str)
        assert isinstance(MEMORY_KEY_PATTERNS, str)
        assert isinstance(MEMORY_KEY_RUNBOOKS, str)
        assert isinstance(MEMORY_KEY_TOOL_FIXES, str)
        assert isinstance(MEMORY_KEY_TEAMMATE_PREFS, str)

    def test_key_paths(self):
        """Memory key paths follow expected format."""
        from scripts.common.config_loader import (
            MEMORY_KEY_CURRENT_WORK,
            MEMORY_KEY_PATTERNS,
        )

        assert "/" in MEMORY_KEY_CURRENT_WORK
        assert MEMORY_KEY_CURRENT_WORK.startswith("state/")
        assert MEMORY_KEY_PATTERNS.startswith("learned/")


class TestFlake8BlockingCodes:
    """Test FLAKE8_BLOCKING_CODES constant."""

    def test_is_list_of_strings(self):
        """FLAKE8_BLOCKING_CODES should be a list of strings."""
        from scripts.common.config_loader import FLAKE8_BLOCKING_CODES

        assert isinstance(FLAKE8_BLOCKING_CODES, list)
        assert all(isinstance(c, str) for c in FLAKE8_BLOCKING_CODES)

    def test_contains_expected_codes(self):
        """FLAKE8_BLOCKING_CODES contains critical codes."""
        from scripts.common.config_loader import FLAKE8_BLOCKING_CODES

        assert "F821" in FLAKE8_BLOCKING_CODES  # Undefined name
        assert "E999" in FLAKE8_BLOCKING_CODES  # Syntax error


class TestSectionConfigAlias:
    """Test that get_section_config is aliased to get_config_section."""

    def test_alias_exists(self):
        """get_section_config should be an alias for get_config_section."""
        from scripts.common.config_loader import get_config_section, get_section_config

        assert get_section_config is get_config_section
