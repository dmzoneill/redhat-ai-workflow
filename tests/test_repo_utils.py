"""Tests for scripts/common/repo_utils.py"""

import os
from unittest.mock import patch

import pytest

from scripts.common.repo_utils import (
    ResolvedRepo,
    _resolve_by_cwd,
    _resolve_by_issue_key,
    _resolve_by_name,
    _resolve_by_path,
    resolve_repo,
)

# ---------------------------------------------------------------------------
# ResolvedRepo dataclass
# ---------------------------------------------------------------------------


class TestResolvedRepo:
    def test_fields(self):
        r = ResolvedRepo(
            path="/tmp/repo",
            gitlab_project="org/repo",
            default_branch="main",
            jira_project="AAP",
            name="my-repo",
        )
        assert r.path == "/tmp/repo"
        assert r.gitlab_project == "org/repo"
        assert r.default_branch == "main"
        assert r.jira_project == "AAP"
        assert r.name == "my-repo"

    def test_to_dict(self):
        r = ResolvedRepo(
            path="/a",
            gitlab_project="g",
            default_branch="dev",
            jira_project="J",
            name="n",
        )
        d = r.to_dict()
        assert d == {
            "path": "/a",
            "gitlab_project": "g",
            "default_branch": "dev",
            "jira_project": "J",
            "name": "n",
        }


# ---------------------------------------------------------------------------
# _resolve_by_path
# ---------------------------------------------------------------------------


class TestResolveByPath:
    def test_match(self):
        repos = {"backend": {"path": "/home/user/backend"}}
        path, name, cfg = _resolve_by_path("/home/user/backend", repos)
        assert path == "/home/user/backend"
        assert name == "backend"
        assert cfg["path"] == "/home/user/backend"

    def test_no_match(self):
        repos = {"backend": {"path": "/home/user/backend"}}
        path, name, cfg = _resolve_by_path("/home/user/frontend", repos)
        assert path == "/home/user/frontend"
        assert name == ""
        assert cfg == {}


# ---------------------------------------------------------------------------
# _resolve_by_name
# ---------------------------------------------------------------------------


class TestResolveByName:
    def test_match(self):
        repos = {"backend": {"path": "/home/user/backend", "gitlab": "org/backend"}}
        path, name, cfg = _resolve_by_name("backend", repos)
        assert path == "/home/user/backend"
        assert name == "backend"

    def test_no_path_key(self):
        repos = {"backend": {"gitlab": "org/backend"}}
        path, name, cfg = _resolve_by_name("backend", repos)
        assert path == ""
        assert name == "backend"

    def test_no_match(self):
        repos = {"backend": {"path": "/home/user/backend"}}
        path, name, cfg = _resolve_by_name("frontend", repos)
        assert path is None
        assert name == ""
        assert cfg == {}


# ---------------------------------------------------------------------------
# _resolve_by_issue_key
# ---------------------------------------------------------------------------


class TestResolveByIssueKey:
    def test_single_match(self):
        repos = {
            "backend": {"path": "/repo", "jira_project": "AAP"},
            "frontend": {"path": "/fe", "jira_project": "FE"},
        }
        path, name, cfg = _resolve_by_issue_key("AAP-12345", repos)
        assert path == "/repo"
        assert name == "backend"

    def test_no_match(self):
        repos = {"backend": {"path": "/repo", "jira_project": "AAP"}}
        path, name, cfg = _resolve_by_issue_key("XYZ-999", repos)
        assert path is None
        assert name == ""

    def test_multiple_matches_raises(self):
        repos = {
            "backend1": {"path": "/repo1", "jira_project": "AAP"},
            "backend2": {"path": "/repo2", "jira_project": "AAP"},
        }
        with pytest.raises(ValueError, match="Multiple repos"):
            _resolve_by_issue_key("AAP-123", repos)

    def test_case_insensitive_prefix(self):
        repos = {"backend": {"path": "/repo", "jira_project": "AAP"}}
        path, name, cfg = _resolve_by_issue_key("aap-123", repos)
        assert name == "backend"


# ---------------------------------------------------------------------------
# _resolve_by_cwd
# ---------------------------------------------------------------------------


class TestResolveByCwd:
    def test_in_git_repo_matching_config(self, tmp_path):
        # Create a fake .git directory
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        repos = {"myrepo": {"path": str(tmp_path)}}
        with patch("os.getcwd", return_value=str(tmp_path)):
            path, name, cfg = _resolve_by_cwd(repos)
            assert path == str(tmp_path)
            assert name == "myrepo"

    def test_in_git_repo_not_in_config(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        repos = {"other": {"path": "/somewhere/else"}}
        with patch("os.getcwd", return_value=str(tmp_path)):
            path, name, cfg = _resolve_by_cwd(repos)
            assert path == str(tmp_path)
            assert name == ""

    def test_not_a_git_repo(self, tmp_path):
        repos = {"myrepo": {"path": str(tmp_path)}}
        with patch("os.getcwd", return_value=str(tmp_path)):
            path, name, cfg = _resolve_by_cwd(repos)
            assert path is None


# ---------------------------------------------------------------------------
# resolve_repo (integration of strategies)
# ---------------------------------------------------------------------------


class TestResolveRepo:
    MOCK_CONFIG = {
        "repositories": {
            "backend": {
                "path": "/home/user/backend",
                "gitlab": "org/backend",
                "default_branch": "main",
                "jira_project": "AAP",
            },
            "frontend": {
                "path": "/home/user/frontend",
                "gitlab": "org/frontend",
                "default_branch": "develop",
                "jira_project": "FE",
            },
        }
    }

    @patch("scripts.common.repo_utils.load_config")
    def test_by_path(self, mock_config):
        mock_config.return_value = self.MOCK_CONFIG
        with patch("os.path.exists", return_value=True):
            r = resolve_repo(repo_path="/home/user/backend")
            assert r.name == "backend"
            assert r.gitlab_project == "org/backend"

    @patch("scripts.common.repo_utils.load_config")
    def test_by_name(self, mock_config):
        mock_config.return_value = self.MOCK_CONFIG
        with patch("os.path.exists", return_value=True):
            r = resolve_repo(repo_name="frontend")
            assert r.name == "frontend"
            assert r.default_branch == "develop"

    @patch("scripts.common.repo_utils.load_config")
    def test_by_issue_key(self, mock_config):
        mock_config.return_value = self.MOCK_CONFIG
        with patch("os.path.exists", return_value=True):
            r = resolve_repo(issue_key="AAP-555")
            assert r.name == "backend"
            assert r.jira_project == "AAP"

    @patch("scripts.common.repo_utils.load_config")
    def test_target_branch_overrides_default(self, mock_config):
        mock_config.return_value = self.MOCK_CONFIG
        with patch("os.path.exists", return_value=True):
            r = resolve_repo(repo_name="backend", target_branch="feature-x")
            assert r.default_branch == "feature-x"

    @patch("scripts.common.repo_utils.load_config")
    def test_path_not_found_raises(self, mock_config):
        mock_config.return_value = {"repositories": {}}
        with (
            patch("os.path.exists", return_value=False),
            patch("os.getcwd", return_value="/nonexistent"),
        ):
            with pytest.raises(ValueError, match="not found"):
                resolve_repo()

    @patch("scripts.common.repo_utils.load_config")
    def test_empty_path_is_skipped(self, mock_config):
        mock_config.return_value = self.MOCK_CONFIG
        # Empty string or "." should fall through to name resolution
        with patch("os.path.exists", return_value=True):
            r = resolve_repo(repo_path="", repo_name="backend")
            assert r.name == "backend"

    @patch("scripts.common.repo_utils.load_config")
    def test_dot_path_is_skipped(self, mock_config):
        mock_config.return_value = self.MOCK_CONFIG
        with patch("os.path.exists", return_value=True):
            r = resolve_repo(repo_path=".", repo_name="backend")
            assert r.name == "backend"

    @patch("scripts.common.repo_utils.load_config")
    def test_fallback_to_cwd(self, mock_config, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        config = {
            "repositories": {
                "myrepo": {
                    "path": str(tmp_path),
                    "gitlab": "org/r",
                    "jira_project": "X",
                },
            }
        }
        mock_config.return_value = config
        with (
            patch("os.getcwd", return_value=str(tmp_path)),
            patch("os.path.exists", return_value=True),
        ):
            r = resolve_repo()
            assert r.path == str(tmp_path)

    @patch("scripts.common.repo_utils.load_config")
    def test_unknown_path_by_path_returns_empty_metadata(self, mock_config):
        mock_config.return_value = {"repositories": {}}
        with patch("os.path.exists", return_value=True):
            r = resolve_repo(repo_path="/some/unknown/path")
            assert r.path == "/some/unknown/path"
            assert r.gitlab_project == ""
            assert r.name == ""
