"""Tests for tool_modules/aa_workflow/src/project_tools.py - Project management tools."""

import json
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from tool_modules.aa_workflow.src.project_tools import (
    OPTIONAL_FIELDS,
    REQUIRED_FIELDS,
    _detect_default_branch,
    _detect_gitlab_remote,
    _detect_language,
    _detect_lint_command,
    _detect_scopes,
    _detect_test_command,
    _generate_test_setup,
    _load_config,
    _project_add_impl,
    _project_detect_impl,
    _project_list_impl,
    _project_remove_impl,
    _project_update_impl,
    _save_config,
    _validate_project_entry,
)

# ==================== _detect_language ====================


class TestDetectLanguage:
    def test_python_pyproject(self, tmp_path):
        (tmp_path / "pyproject.toml").touch()
        assert _detect_language(tmp_path) == "python"

    def test_python_setup_py(self, tmp_path):
        (tmp_path / "setup.py").touch()
        assert _detect_language(tmp_path) == "python"

    def test_javascript(self, tmp_path):
        (tmp_path / "package.json").touch()
        assert _detect_language(tmp_path) == "javascript"

    def test_go(self, tmp_path):
        (tmp_path / "go.mod").touch()
        assert _detect_language(tmp_path) == "go"

    def test_rust(self, tmp_path):
        (tmp_path / "Cargo.toml").touch()
        assert _detect_language(tmp_path) == "rust"

    def test_java(self, tmp_path):
        (tmp_path / "pom.xml").touch()
        assert _detect_language(tmp_path) == "java"

    def test_unknown(self, tmp_path):
        assert _detect_language(tmp_path) == "unknown"


# ==================== _detect_default_branch ====================


class TestDetectDefaultBranch:
    @patch("subprocess.run")
    def test_from_symbolic_ref(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="refs/remotes/origin/main"
        )
        assert _detect_default_branch(Path("/repo")) == "main"

    @patch("subprocess.run")
    def test_fallback_main(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout=""),  # symbolic-ref fails
            MagicMock(returncode=0, stdout="  origin/main\n  origin/feature"),
        ]
        assert _detect_default_branch(Path("/repo")) == "main"

    @patch("subprocess.run")
    def test_fallback_master(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout=""),
            MagicMock(returncode=0, stdout="  origin/master\n  origin/feature"),
        ]
        assert _detect_default_branch(Path("/repo")) == "master"

    @patch("subprocess.run")
    def test_all_fail_default_main(self, mock_run):
        mock_run.side_effect = Exception("git not found")
        assert _detect_default_branch(Path("/repo")) == "main"


# ==================== _detect_gitlab_remote ====================


class TestDetectGitlabRemote:
    @patch("subprocess.run")
    def test_ssh_url(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="git@gitlab.cee.redhat.com:org/repo.git",
        )
        assert _detect_gitlab_remote(Path("/repo")) == "org/repo"

    @patch("subprocess.run")
    def test_https_url(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="https://gitlab.cee.redhat.com/org/repo.git",
        )
        assert _detect_gitlab_remote(Path("/repo")) == "org/repo"

    @patch("subprocess.run")
    def test_no_dot_git_suffix(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="git@gitlab.cee.redhat.com:org/repo",
        )
        assert _detect_gitlab_remote(Path("/repo")) == "org/repo"

    @patch("subprocess.run")
    def test_non_gitlab(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="https://github.com/org/repo.git",
        )
        assert _detect_gitlab_remote(Path("/repo")) is None

    @patch("subprocess.run")
    def test_command_fails(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert _detect_gitlab_remote(Path("/repo")) is None

    @patch("subprocess.run")
    def test_exception(self, mock_run):
        mock_run.side_effect = Exception("timeout")
        assert _detect_gitlab_remote(Path("/repo")) is None


# ==================== _detect_lint_command ====================


class TestDetectLintCommand:
    def test_python_with_ruff(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.ruf]\n")
        result = _detect_lint_command(tmp_path, "python")
        assert "ruff check" in result

    def test_python_with_black_and_flake8(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.black]\n[tool.flake8]\n")
        result = _detect_lint_command(tmp_path, "python")
        assert "black --check" in result
        assert "flake8" in result

    def test_python_default(self, tmp_path):
        result = _detect_lint_command(tmp_path, "python")
        assert "black --check" in result

    def test_javascript_npm_lint(self, tmp_path):
        pkg = {"scripts": {"lint": "eslint ."}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        assert _detect_lint_command(tmp_path, "javascript") == "npm run lint"

    def test_javascript_npm_eslint(self, tmp_path):
        pkg = {"scripts": {"eslint": "eslint ."}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        assert _detect_lint_command(tmp_path, "javascript") == "npm run eslint"

    def test_javascript_default(self, tmp_path):
        assert _detect_lint_command(tmp_path, "javascript") == "npm run lint"

    def test_go(self, tmp_path):
        result = _detect_lint_command(tmp_path, "go")
        assert "go fmt" in result
        assert "go vet" in result

    def test_unknown_language(self, tmp_path):
        assert _detect_lint_command(tmp_path, "unknown") == ""

    def test_javascript_bad_json(self, tmp_path):
        (tmp_path / "package.json").write_text("bad-json")
        result = _detect_lint_command(tmp_path, "javascript")
        assert result == "npm run lint"


# ==================== _detect_test_command ====================


class TestDetectTestCommand:
    def test_python_with_pytest(self, tmp_path):
        (tmp_path / "pyproject.toml").touch()
        assert _detect_test_command(tmp_path, "python") == "pytest tests/ -v"

    def test_python_with_pytest_ini(self, tmp_path):
        (tmp_path / "pytest.ini").touch()
        assert _detect_test_command(tmp_path, "python") == "pytest tests/ -v"

    def test_python_default(self, tmp_path):
        assert _detect_test_command(tmp_path, "python") == "python -m pytest"

    def test_javascript_npm_test(self, tmp_path):
        pkg = {"scripts": {"test": "jest"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        assert _detect_test_command(tmp_path, "javascript") == "npm test"

    def test_javascript_default(self, tmp_path):
        assert _detect_test_command(tmp_path, "javascript") == "npm test"

    def test_go(self, tmp_path):
        assert _detect_test_command(tmp_path, "go") == "go test ./..."

    def test_unknown(self, tmp_path):
        assert _detect_test_command(tmp_path, "unknown") == ""

    def test_javascript_bad_json(self, tmp_path):
        (tmp_path / "package.json").write_text("bad")
        assert _detect_test_command(tmp_path, "javascript") == "npm test"


# ==================== _detect_scopes ====================


class TestDetectScopes:
    def test_finds_standard_dirs(self, tmp_path):
        (tmp_path / "api").mkdir()
        (tmp_path / "tests").mkdir()
        (tmp_path / "docs").mkdir()
        result = _detect_scopes(tmp_path)
        assert "api" in result
        assert "tests" in result
        assert "docs" in result

    def test_finds_src_subdirs(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "billing").mkdir()
        (src / "auth").mkdir()
        (src / "_private").mkdir()  # Should be skipped
        result = _detect_scopes(tmp_path)
        assert "billing" in result
        assert "auth" in result
        assert "_private" not in result

    def test_limits_to_10(self, tmp_path):
        for i in range(15):
            (tmp_path / f"dir{i}").mkdir()
        # Only important_dirs that exist count for standard dirs
        src = tmp_path / "src"
        src.mkdir()
        for i in range(15):
            (src / f"sub{i}").mkdir()
        result = _detect_scopes(tmp_path)
        assert len(result) <= 10


# ==================== _generate_test_setup ====================


class TestGenerateTestSetup:
    def test_python_setup(self, tmp_path):
        result = _generate_test_setup(tmp_path, "python")
        assert "venv" in result
        assert "pip install" in result
        assert "pytest" in result

    def test_python_with_docker(self, tmp_path):
        (tmp_path / "docker-compose.yml").touch()
        result = _generate_test_setup(tmp_path, "python")
        assert "docker-compose" in result

    def test_javascript_setup(self, tmp_path):
        result = _generate_test_setup(tmp_path, "javascript")
        assert "npm install" in result
        assert "npm test" in result

    def test_go_setup(self, tmp_path):
        result = _generate_test_setup(tmp_path, "go")
        assert "go mod download" in result
        assert "go test" in result


# ==================== _validate_project_entry ====================


class TestValidateProjectEntry:
    def test_valid_entry(self, tmp_path):
        entry = {
            "path": str(tmp_path),
            "gitlab": "org/repo",
            "jira_project": "AAP",
            "default_branch": "main",
        }
        errors = _validate_project_entry(entry)
        assert errors == []

    def test_missing_required_field(self):
        entry = {"path": "/some/path"}
        errors = _validate_project_entry(entry)
        assert len(errors) > 0
        assert any("gitlab" in e for e in errors)

    def test_empty_required_field(self, tmp_path):
        entry = {
            "path": str(tmp_path),
            "gitlab": "",
            "jira_project": "AAP",
            "default_branch": "main",
        }
        errors = _validate_project_entry(entry)
        assert any("gitlab" in e for e in errors)

    def test_path_not_exists(self):
        entry = {
            "path": "/nonexistent/path",
            "gitlab": "org/repo",
            "jira_project": "AAP",
            "default_branch": "main",
        }
        errors = _validate_project_entry(entry)
        assert any("does not exist" in e for e in errors)

    def test_path_not_dir(self, tmp_path):
        f = tmp_path / "afile.txt"
        f.write_text("hello")
        entry = {
            "path": str(f),
            "gitlab": "org/repo",
            "jira_project": "AAP",
            "default_branch": "main",
        }
        errors = _validate_project_entry(entry)
        assert any("not a directory" in e for e in errors)


# ==================== _load_config / _save_config ====================


class TestLoadSaveConfig:
    @patch("tool_modules.aa_workflow.src.project_tools.config_manager")
    def test_load_config(self, mock_cm):
        mock_cm.get_all.return_value = {"repositories": {"x": {}}}
        result = _load_config()
        assert "repositories" in result

    @patch("tool_modules.aa_workflow.src.project_tools.config_manager")
    def test_save_config_success(self, mock_cm):
        assert _save_config({"repositories": {}}) is True
        mock_cm.flush.assert_called_once()

    @patch("tool_modules.aa_workflow.src.project_tools.config_manager")
    def test_save_config_failure(self, mock_cm):
        mock_cm.update_section.side_effect = Exception("disk full")
        assert _save_config({"repositories": {}}) is False


# ==================== _project_list_impl ====================


class TestProjectListImpl:
    @pytest.mark.asyncio
    @patch("tool_modules.aa_workflow.src.project_tools._load_config")
    async def test_empty_repos(self, mock_load):
        mock_load.return_value = {"repositories": {}}
        result = await _project_list_impl()
        assert len(result) == 1
        assert "No projects" in result[0].text

    @pytest.mark.asyncio
    @patch("tool_modules.aa_workflow.src.project_tools._load_config")
    async def test_with_repos(self, mock_load):
        mock_load.return_value = {
            "repositories": {
                "myproject": {
                    "path": "/tmp/myproject",
                    "gitlab": "org/myproject",
                    "jira_project": "AAP",
                    "default_branch": "main",
                    "konflux_namespace": "tenant-ns",
                    "scopes": ["api", "core"],
                }
            }
        }
        with patch.object(Path, "exists", return_value=True):
            result = await _project_list_impl()
        text = result[0].text
        assert "myproject" in text
        assert "org/myproject" in text
        assert "AAP" in text
        assert "tenant-ns" in text
        assert "api, core" in text

    @pytest.mark.asyncio
    @patch("tool_modules.aa_workflow.src.project_tools._load_config")
    async def test_no_repositories_key(self, mock_load):
        mock_load.return_value = {}
        result = await _project_list_impl()
        assert "No projects" in result[0].text


# ==================== _project_detect_impl ====================


class TestProjectDetectImpl:
    @pytest.mark.asyncio
    async def test_path_not_exists(self):
        result = await _project_detect_impl("/nonexistent/path")
        assert "does not exist" in result[0].text

    @pytest.mark.asyncio
    async def test_path_is_file(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("hi")
        result = await _project_detect_impl(str(f))
        assert "not a directory" in result[0].text

    @pytest.mark.asyncio
    @patch("tool_modules.aa_workflow.src.project_tools._detect_gitlab_remote")
    @patch("tool_modules.aa_workflow.src.project_tools._detect_default_branch")
    async def test_detect_success(self, mock_branch, mock_gitlab, tmp_path):
        (tmp_path / "pyproject.toml").touch()
        mock_branch.return_value = "main"
        mock_gitlab.return_value = "org/myrepo"

        result = await _project_detect_impl(str(tmp_path))
        text = result[0].text
        assert "python" in text.lower()
        assert "main" in text
        assert "org/myrepo" in text


# ==================== _project_add_impl ====================


class TestProjectAddImpl:
    @pytest.mark.asyncio
    @patch("tool_modules.aa_workflow.src.project_tools._save_config")
    @patch("tool_modules.aa_workflow.src.project_tools._load_config")
    async def test_project_already_exists(self, mock_load, mock_save):
        mock_load.return_value = {"repositories": {"existing": {}}}
        result = await _project_add_impl("existing", "/tmp", "g", "j")
        assert "already exists" in result[0].text

    @pytest.mark.asyncio
    @patch("tool_modules.aa_workflow.src.project_tools._save_config")
    @patch("tool_modules.aa_workflow.src.project_tools._load_config")
    async def test_add_with_auto_detect(self, mock_load, mock_save, tmp_path):
        mock_load.return_value = {"repositories": {}}
        mock_save.return_value = True

        # Create a Python project
        (tmp_path / "pyproject.toml").touch()
        (tmp_path / "api").mkdir()

        result = await _project_add_impl(
            "newproj", str(tmp_path), "org/repo", "AAP", auto_detect=True
        )
        text = result[0].text
        assert "added" in text.lower()

    @pytest.mark.asyncio
    @patch("tool_modules.aa_workflow.src.project_tools._save_config")
    @patch("tool_modules.aa_workflow.src.project_tools._load_config")
    async def test_add_no_auto_detect(self, mock_load, mock_save, tmp_path):
        mock_load.return_value = {"repositories": {}}
        mock_save.return_value = True

        result = await _project_add_impl(
            "newproj",
            str(tmp_path),
            "org/repo",
            "AAP",
            lint_command="ruff check",
            test_command="pytest",
            jira_component="UI",
            konflux_namespace="ns",
            scopes="api,core",
            auto_detect=False,
        )
        assert "added" in result[0].text.lower()

    @pytest.mark.asyncio
    @patch("tool_modules.aa_workflow.src.project_tools._save_config")
    @patch("tool_modules.aa_workflow.src.project_tools._load_config")
    async def test_add_validation_error(self, mock_load, mock_save):
        mock_load.return_value = {"repositories": {}}
        result = await _project_add_impl(
            "newproj", "/nonexistent", "org/repo", "AAP", auto_detect=False
        )
        assert "Validation" in result[0].text or "does not exist" in result[0].text

    @pytest.mark.asyncio
    @patch("tool_modules.aa_workflow.src.project_tools._save_config")
    @patch("tool_modules.aa_workflow.src.project_tools._load_config")
    async def test_add_save_fails(self, mock_load, mock_save, tmp_path):
        mock_load.return_value = {"repositories": {}}
        mock_save.return_value = False

        result = await _project_add_impl(
            "newproj", str(tmp_path), "org/repo", "AAP", auto_detect=False
        )
        assert "Failed to save" in result[0].text

    @pytest.mark.asyncio
    @patch("tool_modules.aa_workflow.src.project_tools._save_config")
    @patch("tool_modules.aa_workflow.src.project_tools._load_config")
    async def test_add_creates_repositories_key(self, mock_load, mock_save, tmp_path):
        mock_load.return_value = {}  # No repositories key
        mock_save.return_value = True

        result = await _project_add_impl(
            "newproj", str(tmp_path), "org/repo", "AAP", auto_detect=False
        )
        assert "added" in result[0].text.lower()

    @pytest.mark.asyncio
    @patch("tool_modules.aa_workflow.src.project_tools._save_config")
    @patch("tool_modules.aa_workflow.src.project_tools._load_config")
    async def test_add_with_test_setup(self, mock_load, mock_save, tmp_path):
        mock_load.return_value = {"repositories": {}}
        mock_save.return_value = True

        result = await _project_add_impl(
            "newproj",
            str(tmp_path),
            "org/repo",
            "AAP",
            test_setup="custom setup",
            auto_detect=False,
        )
        assert "added" in result[0].text.lower()


# ==================== _project_remove_impl ====================


class TestProjectRemoveImpl:
    @pytest.mark.asyncio
    @patch("tool_modules.aa_workflow.src.project_tools._load_config")
    async def test_project_not_found(self, mock_load):
        mock_load.return_value = {"repositories": {"other": {}}}
        result = await _project_remove_impl("missing")
        assert "not found" in result[0].text

    @pytest.mark.asyncio
    @patch("tool_modules.aa_workflow.src.project_tools._load_config")
    async def test_confirm_prompt(self, mock_load):
        mock_load.return_value = {"repositories": {"myproj": {"path": "/x"}}}
        result = await _project_remove_impl("myproj", confirm=False)
        text = result[0].text
        assert "Confirm" in text
        assert "myproj" in text

    @pytest.mark.asyncio
    @patch("tool_modules.aa_workflow.src.project_tools._save_config")
    @patch("tool_modules.aa_workflow.src.project_tools._load_config")
    async def test_remove_success(self, mock_load, mock_save):
        mock_load.return_value = {"repositories": {"myproj": {"path": "/x"}}}
        mock_save.return_value = True
        result = await _project_remove_impl("myproj", confirm=True)
        assert "removed" in result[0].text.lower()

    @pytest.mark.asyncio
    @patch("tool_modules.aa_workflow.src.project_tools._save_config")
    @patch("tool_modules.aa_workflow.src.project_tools._load_config")
    async def test_remove_also_cleans_quay(self, mock_load, mock_save):
        mock_load.return_value = {
            "repositories": {"myproj": {"path": "/x"}},
            "quay": {"repositories": {"myproj": {}}},
        }
        mock_save.return_value = True
        result = await _project_remove_impl("myproj", confirm=True)
        assert "quay.repositories" in result[0].text

    @pytest.mark.asyncio
    @patch("tool_modules.aa_workflow.src.project_tools._save_config")
    @patch("tool_modules.aa_workflow.src.project_tools._load_config")
    async def test_remove_also_cleans_saas(self, mock_load, mock_save):
        mock_load.return_value = {
            "repositories": {"myproj": {"path": "/x"}},
            "saas_pipelines": {"namespaces": {"myproj": {}}},
        }
        mock_save.return_value = True
        result = await _project_remove_impl("myproj", confirm=True)
        assert "saas_pipelines" in result[0].text

    @pytest.mark.asyncio
    @patch("tool_modules.aa_workflow.src.project_tools._save_config")
    @patch("tool_modules.aa_workflow.src.project_tools._load_config")
    async def test_remove_save_fails(self, mock_load, mock_save):
        mock_load.return_value = {"repositories": {"myproj": {"path": "/x"}}}
        mock_save.return_value = False
        result = await _project_remove_impl("myproj", confirm=True)
        assert "Failed to save" in result[0].text

    @pytest.mark.asyncio
    @patch("tool_modules.aa_workflow.src.project_tools._load_config")
    async def test_remove_no_repos_key(self, mock_load):
        mock_load.return_value = {}
        result = await _project_remove_impl("missing")
        assert "not found" in result[0].text


# ==================== _project_update_impl ====================


class TestProjectUpdateImpl:
    @pytest.mark.asyncio
    @patch("tool_modules.aa_workflow.src.project_tools._load_config")
    async def test_project_not_found(self, mock_load):
        mock_load.return_value = {"repositories": {}}
        result = await _project_update_impl("missing")
        assert "not found" in result[0].text

    @pytest.mark.asyncio
    @patch("tool_modules.aa_workflow.src.project_tools._save_config")
    @patch("tool_modules.aa_workflow.src.project_tools._load_config")
    async def test_no_fields_provided(self, mock_load, mock_save):
        mock_load.return_value = {
            "repositories": {
                "myproj": {
                    "path": "/tmp",
                    "gitlab": "org/repo",
                    "jira_project": "AAP",
                    "default_branch": "main",
                }
            }
        }
        result = await _project_update_impl("myproj")
        assert "No fields" in result[0].text

    @pytest.mark.asyncio
    @patch("tool_modules.aa_workflow.src.project_tools._save_config")
    @patch("tool_modules.aa_workflow.src.project_tools._load_config")
    async def test_update_fields(self, mock_load, mock_save, tmp_path):
        mock_load.return_value = {
            "repositories": {
                "myproj": {
                    "path": str(tmp_path),
                    "gitlab": "org/repo",
                    "jira_project": "AAP",
                    "default_branch": "main",
                }
            }
        }
        mock_save.return_value = True

        result = await _project_update_impl(
            "myproj",
            gitlab="org/newrepo",
            jira_project="NEWP",
            jira_component="UI",
            lint_command="ruff check",
            test_command="pytest -v",
            default_branch="develop",
            konflux_namespace="ns",
            scopes="api,core",
        )
        text = result[0].text
        assert "updated" in text.lower()
        assert "gitlab" in text
        assert "jira_project" in text

    @pytest.mark.asyncio
    @patch("tool_modules.aa_workflow.src.project_tools._save_config")
    @patch("tool_modules.aa_workflow.src.project_tools._load_config")
    async def test_update_path(self, mock_load, mock_save, tmp_path):
        mock_load.return_value = {
            "repositories": {
                "myproj": {
                    "path": "/old",
                    "gitlab": "org/repo",
                    "jira_project": "AAP",
                    "default_branch": "main",
                }
            }
        }
        mock_save.return_value = True

        result = await _project_update_impl("myproj", path=str(tmp_path))
        assert "updated" in result[0].text.lower()

    @pytest.mark.asyncio
    @patch("tool_modules.aa_workflow.src.project_tools._save_config")
    @patch("tool_modules.aa_workflow.src.project_tools._load_config")
    async def test_update_save_fails(self, mock_load, mock_save, tmp_path):
        mock_load.return_value = {
            "repositories": {
                "myproj": {
                    "path": str(tmp_path),
                    "gitlab": "org/repo",
                    "jira_project": "AAP",
                    "default_branch": "main",
                }
            }
        }
        mock_save.return_value = False

        result = await _project_update_impl("myproj", gitlab="org/new")
        assert "Failed to save" in result[0].text

    @pytest.mark.asyncio
    @patch("tool_modules.aa_workflow.src.project_tools._save_config")
    @patch("tool_modules.aa_workflow.src.project_tools._load_config")
    async def test_update_validation_fails(self, mock_load, mock_save):
        mock_load.return_value = {
            "repositories": {
                "myproj": {
                    "path": "/nonexistent",
                    "gitlab": "",
                    "jira_project": "",
                    "default_branch": "main",
                }
            }
        }
        # Updating gitlab to empty value triggers validation error
        result = await _project_update_impl("myproj", jira_component="comp")
        # The validation should fail because of empty gitlab, missing jira_project, and bad path
        assert "Validation" in result[0].text or "does not exist" in result[0].text


# ==================== Constants ====================


class TestConstants:
    def test_required_fields(self):
        assert "path" in REQUIRED_FIELDS
        assert "gitlab" in REQUIRED_FIELDS
        assert "jira_project" in REQUIRED_FIELDS
        assert "default_branch" in REQUIRED_FIELDS

    def test_optional_fields(self):
        assert "jira_component" in OPTIONAL_FIELDS
        assert "lint_command" in OPTIONAL_FIELDS
        assert "test_command" in OPTIONAL_FIELDS
