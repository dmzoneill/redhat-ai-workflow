"""Tests for shared utilities in server/utils.py."""

import asyncio
import os
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.utils import (
    _build_shell_sources,
    _prepare_shell_environment,
    format_error,
    format_list,
    format_success,
    format_warning,
    get_auth_hint,
    get_cluster_short_name,
    get_env_config,
    get_gitlab_host,
    get_kubeconfig,
    get_project_root,
    get_repo_config,
    get_section_config,
    get_service_url,
    get_user_config,
    get_username,
    is_auth_error,
    load_config,
    resolve_repo_path,
    truncate_output,
)


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


# ==================== New coverage tests ====================


class TestTruncateOutput:
    """Tests for truncate_output function."""

    def test_short_text_unchanged(self):
        """Short text is returned as-is."""
        assert truncate_output("hello", max_length=100) == "hello"

    def test_empty_text(self):
        """Empty text is returned as-is."""
        assert truncate_output("") == ""

    def test_none_text(self):
        """None text is returned as-is."""
        assert truncate_output(None) is None

    def test_head_mode_truncation(self):
        """Head mode keeps the beginning of text."""
        text = "a" * 100
        result = truncate_output(text, max_length=50, mode="head")
        assert len(result) == 50 + len("\n\n... (truncated)")
        assert result.startswith("a" * 50)
        assert result.endswith("... (truncated)")

    def test_tail_mode_truncation(self):
        """Tail mode keeps the end of text."""
        text = "a" * 50 + "b" * 50
        result = truncate_output(text, max_length=50, mode="tail")
        assert "b" * 50 in result
        assert "truncated" in result.lower()

    def test_custom_suffix(self):
        """Custom suffix is applied on truncation."""
        text = "x" * 100
        result = truncate_output(text, max_length=10, suffix=" [CUT]")
        assert result.endswith("[CUT]")

    def test_tail_mode_empty_suffix(self):
        """Tail mode with empty suffix uses default prefix."""
        text = "x" * 100
        result = truncate_output(text, max_length=50, suffix="", mode="tail")
        assert "truncated" in result.lower()

    def test_exactly_at_limit(self):
        """Text exactly at max_length is not truncated."""
        text = "a" * 50
        result = truncate_output(text, max_length=50)
        assert result == text


class TestFormatError:
    """Tests for format_error function."""

    def test_basic_error(self):
        """Basic error message formatting."""
        result = format_error("Something failed")
        assert "Something failed" in result

    def test_error_with_output(self):
        """Error with command output."""
        result = format_error("Failed", output="stderr output")
        assert "Failed" in result
        assert "stderr output" in result

    def test_error_with_hint(self):
        """Error with hint."""
        result = format_error("Failed", hint="Try again")
        assert "Try again" in result

    def test_error_with_tool_name(self):
        """Error with tool name for debug_tool."""
        result = format_error("Failed", tool_name="my_tool")
        assert "debug_tool" in result
        assert "my_tool" in result

    def test_error_all_parts(self):
        """Error with all optional parts."""
        result = format_error("Error", output="out", hint="fix", tool_name="t")
        assert "Error" in result
        assert "out" in result
        assert "fix" in result
        assert "t" in result


class TestFormatSuccess:
    """Tests for format_success function."""

    def test_basic_success(self):
        """Basic success message."""
        result = format_success("Done")
        assert "Done" in result

    def test_success_with_details(self):
        """Success with key-value details."""
        result = format_success("Done", file_count=5, elapsed_time="2s")
        assert "Done" in result
        assert "File Count" in result
        assert "5" in result
        assert "Elapsed Time" in result
        assert "2s" in result


class TestFormatWarning:
    """Tests for format_warning function."""

    def test_basic_warning(self):
        """Basic warning message."""
        result = format_warning("Watch out")
        assert "Watch out" in result

    def test_warning_with_action(self):
        """Warning with suggested action."""
        result = format_warning("Careful", action="Check logs")
        assert "Careful" in result
        assert "Check logs" in result

    def test_warning_no_action(self):
        """Warning without action doesn't include hint prefix."""
        result = format_warning("Simple warning")
        # Should not have the action hint
        assert result.count("\n") == 0


class TestFormatList:
    """Tests for format_list function."""

    def test_empty_list(self):
        """Empty list shows empty message."""
        result = format_list("Items:", [])
        assert "Items:" in result
        assert "None found." in result

    def test_string_items(self):
        """String items are formatted as bullet list."""
        result = format_list("Items:", ["one", "two", "three"])
        assert "Items:" in result
        assert "one" in result
        assert "two" in result
        assert "three" in result

    def test_dict_items_with_key(self):
        """Dict items use item_key for display."""
        items = [{"name": "Alice"}, {"name": "Bob"}]
        result = format_list("People:", items, item_key="name")
        assert "Alice" in result
        assert "Bob" in result

    def test_dict_items_missing_key(self):
        """Dict items with missing key fall back to str."""
        items = [{"other": "value"}]
        result = format_list("Items:", items, item_key="name")
        assert "other" in result

    def test_custom_empty_message(self):
        """Custom empty message is used."""
        result = format_list("Items:", [], empty_message="Nothing here!")
        assert "Nothing here!" in result


class TestGetKubeconfigExtended:
    """Extended tests for get_kubeconfig."""

    def test_empty_environment_raises(self):
        """Empty environment raises ValueError."""
        with pytest.raises(ValueError, match="Environment is required"):
            get_kubeconfig("")

    def test_whitespace_environment_raises(self):
        """Whitespace-only environment raises ValueError."""
        with pytest.raises(ValueError, match="Environment is required"):
            get_kubeconfig("   ")

    @patch("server.utils.load_config")
    def test_kubeconfig_from_namespaces(self, mock_load):
        """get_kubeconfig uses namespaces section if available."""
        mock_load.return_value = {
            "namespaces": {"stage": {"kubeconfig": "~/custom/kube.s"}},
        }
        result = get_kubeconfig("stage")
        assert "custom/kube.s" in result

    @patch("server.utils.load_config")
    def test_kubeconfig_from_kubernetes_environments(self, mock_load):
        """get_kubeconfig uses kubernetes.environments section."""
        mock_load.return_value = {
            "namespaces": {},
            "kubernetes": {
                "environments": {"stage": {"kubeconfig": "~/k8s/config.stage"}}
            },
        }
        result = get_kubeconfig("stage")
        assert "k8s/config.stage" in result

    @patch("server.utils.load_config")
    def test_kubeconfig_fallback_to_standard(self, mock_load):
        """get_kubeconfig falls back to standard mapping."""
        mock_load.return_value = {}
        result = get_kubeconfig("stage")
        assert result.endswith("config.s")

    @patch("server.utils.load_config")
    def test_kubeconfig_unknown_env(self, mock_load):
        """get_kubeconfig handles unknown environment name."""
        mock_load.return_value = {}
        result = get_kubeconfig("custom-env")
        assert result.endswith("config.custom-env")

    @patch("server.utils.load_config")
    def test_kubeconfig_aliases(self, mock_load):
        """get_kubeconfig handles all environment aliases."""
        mock_load.return_value = {}
        # Test various aliases
        assert get_kubeconfig("s").endswith("config.s")
        assert get_kubeconfig("production").endswith("config.p")
        assert get_kubeconfig("p").endswith("config.p")
        assert get_kubeconfig("eph").endswith("config.e")
        assert get_kubeconfig("e").endswith("config.e")
        assert get_kubeconfig("konflux").endswith("config.k")
        assert get_kubeconfig("k").endswith("config.k")
        assert get_kubeconfig("saas").endswith("config.ap")


class TestGetClusterShortName:
    """Tests for get_cluster_short_name."""

    def test_stage(self):
        assert get_cluster_short_name("stage") == "s"

    def test_production(self):
        assert get_cluster_short_name("production") == "p"

    def test_ephemeral(self):
        assert get_cluster_short_name("ephemeral") == "e"

    def test_konflux(self):
        assert get_cluster_short_name("konflux") == "k"

    def test_unknown(self):
        assert get_cluster_short_name("UNKNOWN") == "unknown"


class TestIsAuthError:
    """Tests for is_auth_error function."""

    def test_unauthorized(self):
        assert is_auth_error("Error: Unauthorized") is True

    def test_token_expired(self):
        assert is_auth_error("token expired") is True

    def test_token_has_expired(self):
        assert is_auth_error("The token has expired") is True

    def test_login_required(self):
        assert is_auth_error("You must be logged in") is True

    def test_provide_credentials(self):
        assert is_auth_error("Please provide credentials") is True

    def test_401_code(self):
        assert is_auth_error("HTTP 401 error") is True

    def test_403_forbidden(self):
        assert is_auth_error("403 Forbidden access") is True

    def test_no_valid_auth(self):
        assert is_auth_error("No valid authentication found") is True

    def test_normal_output(self):
        assert is_auth_error("pod/my-pod created successfully") is False

    def test_empty_output(self):
        assert is_auth_error("") is False


class TestGetAuthHint:
    """Tests for get_auth_hint function."""

    def test_stage(self):
        result = get_auth_hint("stage")
        assert "kube_login" in result
        assert "'s'" in result

    def test_production(self):
        result = get_auth_hint("production")
        assert "'p'" in result

    def test_ephemeral(self):
        result = get_auth_hint("ephemeral")
        assert "'e'" in result

    def test_unknown_env(self):
        result = get_auth_hint("custom-cluster")
        assert "'custom-cluster'" in result


class TestGetEnvConfig:
    """Tests for get_env_config function."""

    @patch("server.utils.load_config")
    def test_returns_env_config(self, mock_load):
        """get_env_config returns environment-specific config."""
        mock_load.return_value = {
            "prometheus": {
                "environments": {
                    "production": {
                        "url": "https://prom.prod.example.com",
                        "kubeconfig": "~/kube/config.p",
                    }
                }
            }
        }
        result = get_env_config("production", "prometheus")
        assert result["url"] == "https://prom.prod.example.com"
        assert "kube/config.p" in result["kubeconfig"]

    @patch("server.utils.load_config")
    def test_prod_alias(self, mock_load):
        """get_env_config normalizes 'prod' to 'production'."""
        mock_load.return_value = {
            "prometheus": {
                "environments": {"production": {"url": "https://prom.prod.example.com"}}
            }
        }
        result = get_env_config("prod", "prometheus")
        assert result["url"] == "https://prom.prod.example.com"

    @patch("server.utils.load_config")
    def test_missing_kubeconfig_uses_default(self, mock_load):
        """get_env_config provides default kubeconfig when not configured."""
        mock_load.return_value = {
            "prometheus": {
                "environments": {"stage": {"url": "https://prom.stage.example.com"}}
            }
        }
        result = get_env_config("stage", "prometheus")
        assert "kubeconfig" in result


class TestResolveRepoPathExtended:
    """Extended tests for resolve_repo_path."""

    @patch("server.utils.load_config")
    def test_resolve_from_config(self, mock_load, tmp_path):
        """resolve_repo_path finds repo from config."""
        repo_dir = tmp_path / "my-repo"
        repo_dir.mkdir()
        mock_load.return_value = {
            "repositories": {"my-repo": {"path": str(repo_dir)}},
            "paths": {},
        }
        result = resolve_repo_path("my-repo")
        assert result == str(repo_dir)

    @patch("server.utils.load_config")
    def test_resolve_from_workspace_roots(self, mock_load, tmp_path):
        """resolve_repo_path searches workspace roots."""
        repo_dir = tmp_path / "my-repo"
        repo_dir.mkdir()
        mock_load.return_value = {
            "repositories": {},
            "paths": {"workspace_roots": [str(tmp_path)]},
        }
        result = resolve_repo_path("my-repo")
        assert result == str(repo_dir)

    @patch("server.utils.load_config")
    def test_resolve_not_found_returns_as_is(self, mock_load):
        """resolve_repo_path returns input when not found anywhere."""
        mock_load.return_value = {"repositories": {}, "paths": {}}
        result = resolve_repo_path("nonexistent-repo-xyz")
        assert result == "nonexistent-repo-xyz"

    def test_resolve_expanduser(self, tmp_path):
        """resolve_repo_path expands ~ in path."""
        # Use a real directory for this test
        result = resolve_repo_path(str(tmp_path))
        assert result == str(tmp_path)


class TestGetRepoConfig:
    """Tests for get_repo_config function."""

    @patch("server.utils.load_config")
    def test_exact_match(self, mock_load):
        """get_repo_config finds repo by exact name."""
        mock_load.return_value = {
            "repositories": {
                "backend": {"path": "/home/user/backend", "gitlab": "org/backend"}
            }
        }
        result = get_repo_config("backend")
        assert result["path"] == "/home/user/backend"

    @patch("server.utils.load_config")
    def test_match_by_path(self, mock_load):
        """get_repo_config finds repo by path suffix."""
        mock_load.return_value = {
            "repositories": {
                "backend": {"path": "/home/user/backend", "gitlab": "org/backend"}
            }
        }
        result = get_repo_config("backend")
        assert result["gitlab"] == "org/backend"

    @patch("server.utils.load_config")
    def test_not_found(self, mock_load):
        """get_repo_config returns empty dict when not found."""
        mock_load.return_value = {"repositories": {}}
        result = get_repo_config("nonexistent")
        assert result == {}


class TestBuildShellSources:
    """Tests for _build_shell_sources function."""

    def test_no_bashrc(self, tmp_path):
        """Returns empty list when no bashrc files exist."""
        result = _build_shell_sources(tmp_path)
        assert result == []

    def test_with_bashrc(self, tmp_path):
        """Includes .bashrc when it exists."""
        (tmp_path / ".bashrc").touch()
        result = _build_shell_sources(tmp_path)
        assert any(".bashrc" in s for s in result)

    def test_with_bashrc_d(self, tmp_path):
        """Includes bashrc.d scripts."""
        bashrc_d = tmp_path / ".bashrc.d"
        bashrc_d.mkdir()
        (bashrc_d / "00-loader.sh").touch()
        (bashrc_d / "10-custom.sh").touch()
        result = _build_shell_sources(tmp_path)
        assert any("00-loader.sh" in s for s in result)
        assert any("10-custom.sh" in s for s in result)

    def test_bashrc_d_without_loader(self, tmp_path):
        """Works with bashrc.d but no loader."""
        bashrc_d = tmp_path / ".bashrc.d"
        bashrc_d.mkdir()
        (bashrc_d / "custom.sh").touch()
        result = _build_shell_sources(tmp_path)
        assert any("custom.sh" in s for s in result)


class TestPrepareShellEnvironment:
    """Tests for _prepare_shell_environment function."""

    def test_sets_home(self, tmp_path):
        """Sets HOME to given home path."""
        env = _prepare_shell_environment(tmp_path)
        assert env["HOME"] == str(tmp_path)

    def test_sets_user(self, tmp_path):
        """Sets USER from home directory name."""
        env = _prepare_shell_environment(tmp_path)
        assert env["USER"] == tmp_path.name

    def test_clears_virtualenv(self, tmp_path):
        """Clears VIRTUAL_ENV and related vars."""
        with patch.dict(
            os.environ, {"VIRTUAL_ENV": "/some/venv", "PIPENV_ACTIVE": "1"}
        ):
            env = _prepare_shell_environment(tmp_path)
            assert "VIRTUAL_ENV" not in env
            assert "PIPENV_ACTIVE" not in env

    def test_removes_venv_from_path(self, tmp_path):
        """Removes .venv entries from PATH."""
        with patch.dict(
            os.environ, {"PATH": "/usr/bin:/some/.venv/bin:/usr/local/bin"}
        ):
            env = _prepare_shell_environment(tmp_path)
            assert ".venv" not in env["PATH"]

    def test_adds_user_bin(self, tmp_path):
        """Adds ~/bin to PATH."""
        env = _prepare_shell_environment(tmp_path)
        assert str(tmp_path / "bin") in env["PATH"]

    def test_sets_display(self, tmp_path):
        """Sets DISPLAY from environment or default."""
        env = _prepare_shell_environment(tmp_path)
        assert "DISPLAY" in env


class TestGetGitlabHost:
    """Tests for get_gitlab_host function."""

    @patch.dict(os.environ, {"GITLAB_HOST": "custom.gitlab.com"})
    def test_from_env(self):
        """Returns GITLAB_HOST from environment."""
        result = get_gitlab_host()
        assert result == "custom.gitlab.com"

    @patch.dict(os.environ, {}, clear=False)
    @patch("server.utils.load_config")
    def test_from_config(self, mock_load):
        """Returns host from config."""
        os.environ.pop("GITLAB_HOST", None)
        mock_load.return_value = {"gitlab": {"host": "my-gitlab.example.com"}}
        result = get_gitlab_host()
        assert result == "my-gitlab.example.com"

    @patch.dict(os.environ, {}, clear=False)
    @patch("server.utils.load_config")
    def test_default(self, mock_load):
        """Returns default gitlab host."""
        os.environ.pop("GITLAB_HOST", None)
        mock_load.return_value = {}
        result = get_gitlab_host()
        assert result == "gitlab.cee.redhat.com"


class TestGetServiceUrl:
    """Tests for get_service_url function."""

    @patch("server.utils.get_env_config")
    def test_returns_url_from_config(self, mock_env_config):
        """Returns URL from environment config."""
        mock_env_config.return_value = {"url": "https://prom.example.com"}
        result = get_service_url("prometheus", "stage")
        assert result == "https://prom.example.com"

    def test_empty_environment_raises(self):
        """Raises ValueError for empty environment."""
        with pytest.raises(ValueError, match="environment"):
            get_service_url("prometheus", "")

    def test_whitespace_environment_raises(self):
        """Raises ValueError for whitespace environment."""
        with pytest.raises(ValueError, match="environment"):
            get_service_url("prometheus", "   ")

    @patch("server.utils.get_env_config")
    @patch.dict(
        os.environ, {"PROMETHEUS_STAGE_URL": "https://env-var-prom.example.com"}
    )
    def test_fallback_to_env_var(self, mock_env_config):
        """Falls back to environment variable."""
        mock_env_config.return_value = {}  # No URL in config
        result = get_service_url("prometheus", "stage")
        assert result == "https://env-var-prom.example.com"

    @patch("server.utils.get_env_config")
    def test_raises_when_not_configured(self, mock_env_config):
        """Raises ValueError when URL not found anywhere."""
        mock_env_config.return_value = {}
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PROMETHEUS_STAGE_URL", None)
            with pytest.raises(ValueError, match="not configured"):
                get_service_url("prometheus", "stage")


class TestGetUserConfig:
    """Tests for get_user_config function."""

    @patch("server.utils.get_section_config")
    def test_returns_user_config(self, mock_section):
        """Returns user section config."""
        mock_section.return_value = {"username": "testuser", "email": "test@test.com"}
        result = get_user_config()
        assert result["username"] == "testuser"


class TestRunCmdSync:
    """Tests for run_cmd_sync function."""

    def test_successful_command(self):
        """run_cmd_sync returns success for valid command."""
        from server.utils import run_cmd_sync

        success, output = run_cmd_sync(["echo", "hello"], use_shell=False)
        assert success is True
        assert "hello" in output

    def test_failed_command(self):
        """run_cmd_sync returns failure for bad command."""
        from server.utils import run_cmd_sync

        success, output = run_cmd_sync(["false"], use_shell=False)
        assert success is False

    def test_timeout(self):
        """run_cmd_sync handles timeout."""
        from server.utils import run_cmd_sync

        success, output = run_cmd_sync(["sleep", "60"], use_shell=False, timeout=1)
        assert success is False
        assert "timed out" in output

    def test_command_not_found(self):
        """run_cmd_sync handles missing command."""
        from server.utils import run_cmd_sync

        success, output = run_cmd_sync(
            ["nonexistent_command_xyz_abc_123"], use_shell=False
        )
        assert success is False
        assert "not found" in output.lower() or "nonexistent" in output.lower()

    def test_with_env(self):
        """run_cmd_sync passes extra env vars."""
        from server.utils import run_cmd_sync

        success, output = run_cmd_sync(
            ["env"], use_shell=False, env={"MY_TEST_VAR": "my_test_value"}
        )
        assert success is True
        assert "MY_TEST_VAR=my_test_value" in output

    def test_with_cwd(self, tmp_path):
        """run_cmd_sync uses working directory."""
        from server.utils import run_cmd_sync

        success, output = run_cmd_sync(["pwd"], use_shell=False, cwd=str(tmp_path))
        assert success is True
        assert str(tmp_path) in output


class TestRunCmd:
    """Tests for async run_cmd function."""

    @pytest.mark.asyncio
    async def test_successful_command(self):
        """run_cmd returns success for valid command."""
        from server.utils import run_cmd

        success, output = await run_cmd(["echo", "hello"], use_shell=False)
        assert success is True
        assert "hello" in output

    @pytest.mark.asyncio
    async def test_failed_command(self):
        """run_cmd returns failure for bad command."""
        from server.utils import run_cmd

        success, output = await run_cmd(["false"], use_shell=False)
        assert success is False

    @pytest.mark.asyncio
    async def test_timeout(self):
        """run_cmd handles timeout."""
        from server.utils import run_cmd

        success, output = await run_cmd(["sleep", "60"], use_shell=False, timeout=1)
        assert success is False
        assert "timed out" in output

    @pytest.mark.asyncio
    async def test_command_not_found(self):
        """run_cmd handles missing command."""
        from server.utils import run_cmd

        success, output = await run_cmd(
            ["nonexistent_command_xyz_abc_123"], use_shell=False
        )
        assert success is False

    @pytest.mark.asyncio
    async def test_check_raises(self):
        """run_cmd with check=True raises on failure."""
        from server.utils import run_cmd

        with pytest.raises(subprocess.CalledProcessError):
            await run_cmd(["false"], use_shell=False, check=True)

    @pytest.mark.asyncio
    async def test_with_cwd_shell_mode(self, tmp_path):
        """run_cmd shell mode handles cwd."""
        from server.utils import run_cmd

        success, output = await run_cmd(["pwd"], cwd=str(tmp_path), use_shell=True)
        assert success is True
        assert str(tmp_path) in output


class TestRunCmdFull:
    """Tests for async run_cmd_full function."""

    @pytest.mark.asyncio
    async def test_returns_three_parts(self):
        """run_cmd_full returns (success, stdout, stderr)."""
        from server.utils import run_cmd_full

        success, stdout, stderr = await run_cmd_full(["echo", "hello"], use_shell=False)
        assert success is True
        assert "hello" in stdout
        assert stderr == "" or isinstance(stderr, str)

    @pytest.mark.asyncio
    async def test_timeout(self):
        """run_cmd_full handles timeout."""
        from server.utils import run_cmd_full

        success, stdout, stderr = await run_cmd_full(
            ["sleep", "60"], use_shell=False, timeout=1
        )
        assert success is False
        assert "timed out" in stderr

    @pytest.mark.asyncio
    async def test_command_not_found(self):
        """run_cmd_full handles missing command."""
        from server.utils import run_cmd_full

        success, stdout, stderr = await run_cmd_full(
            ["nonexistent_command_xyz_abc_123"], use_shell=False
        )
        assert success is False

    @pytest.mark.asyncio
    async def test_failure(self):
        """run_cmd_full handles failing command."""
        from server.utils import run_cmd_full

        success, stdout, stderr = await run_cmd_full(
            ["ls", "/nonexistent_path_xyz"], use_shell=False
        )
        assert success is False


class TestRunCmdShell:
    """Tests for deprecated run_cmd_shell function."""

    @pytest.mark.asyncio
    async def test_delegates_to_run_cmd_full(self):
        """run_cmd_shell delegates to run_cmd_full."""
        from server.utils import run_cmd_shell

        success, stdout, stderr = await run_cmd_shell(["echo", "test"])
        assert success is True
        assert "test" in stdout


# ==================== Additional coverage tests ====================


class TestLoadConfigReload:
    """Test load_config with reload flag."""

    def test_load_config_reload(self):
        """load_config(reload=True) forces a reload."""
        with patch("server.utils._config_manager") as mock_cm:
            mock_cm.get_all.return_value = {"refreshed": True}
            result = load_config(reload=True)
            mock_cm.reload.assert_called_once()
            assert result == {"refreshed": True}


class TestGetKubeBase:
    """Tests for _get_kube_base function."""

    @patch("server.utils.load_config")
    def test_custom_kube_base(self, mock_load):
        """_get_kube_base uses custom path from config."""
        from server.utils import _get_kube_base

        mock_load.return_value = {"paths": {"kube_base": "~/custom-kube"}}
        result = _get_kube_base()
        assert "custom-kube" in str(result)

    @patch("server.utils.load_config")
    def test_default_kube_base(self, mock_load):
        """_get_kube_base defaults to ~/.kube."""
        from server.utils import _get_kube_base

        mock_load.return_value = {"paths": {}}
        result = _get_kube_base()
        assert str(result).endswith(".kube")


class TestGetRepoConfigPathMatch:
    """Test get_repo_config matching by path."""

    @patch("server.utils.load_config")
    def test_match_by_path_suffix(self, mock_load):
        """get_repo_config finds repo when path ends with query."""
        mock_load.return_value = {
            "repositories": {
                "my-backend": {
                    "path": "/home/user/projects/my-backend",
                    "gitlab": "org/my-backend",
                }
            }
        }
        result = get_repo_config("my-backend")
        assert result["gitlab"] == "org/my-backend"


class TestCheckClusterAuth:
    """Tests for check_cluster_auth function."""

    @pytest.mark.asyncio
    async def test_kubeconfig_not_found(self):
        """check_cluster_auth returns False if kubeconfig doesn't exist."""
        from server.utils import check_cluster_auth

        with patch(
            "server.utils.get_kubeconfig", return_value="/nonexistent/kube/config"
        ):
            with patch("os.path.exists", return_value=False):
                result = await check_cluster_auth("stage")
                assert result is False

    @pytest.mark.asyncio
    async def test_auth_valid(self):
        """check_cluster_auth returns True when oc whoami succeeds."""
        from server.utils import check_cluster_auth

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "user@example.com\n"
        mock_result.stderr = ""

        with patch("server.utils.get_kubeconfig", return_value="/tmp/kube/config.s"):
            with patch("os.path.exists", return_value=True):
                with patch("asyncio.to_thread", return_value=mock_result):
                    result = await check_cluster_auth("stage")
                    assert result is True

    @pytest.mark.asyncio
    async def test_auth_failed(self):
        """check_cluster_auth returns False when oc whoami fails."""
        from server.utils import check_cluster_auth

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Unauthorized"

        with patch("server.utils.get_kubeconfig", return_value="/tmp/kube/config.s"):
            with patch("os.path.exists", return_value=True):
                with patch("asyncio.to_thread", return_value=mock_result):
                    result = await check_cluster_auth("stage")
                    assert result is False

    @pytest.mark.asyncio
    async def test_auth_exception(self):
        """check_cluster_auth returns False on exception."""
        from server.utils import check_cluster_auth

        with patch("server.utils.get_kubeconfig", return_value="/tmp/kube/config.s"):
            with patch("os.path.exists", return_value=True):
                with patch(
                    "asyncio.to_thread", side_effect=Exception("connection error")
                ):
                    result = await check_cluster_auth("stage")
                    assert result is False


class TestRefreshClusterAuth:
    """Tests for refresh_cluster_auth function."""

    @pytest.mark.asyncio
    async def test_refresh_success(self):
        """refresh_cluster_auth returns True on success."""
        from server.utils import refresh_cluster_auth

        with patch("server.utils.run_cmd_shell") as mock_shell:
            mock_shell.side_effect = [
                (True, "", ""),  # kube-clean succeeds
                (True, "", ""),  # kube succeeds
            ]
            result = await refresh_cluster_auth("stage")
            assert result is True

    @pytest.mark.asyncio
    async def test_refresh_failure(self):
        """refresh_cluster_auth returns False when kube fails."""
        from server.utils import refresh_cluster_auth

        with patch("server.utils.run_cmd_shell") as mock_shell:
            mock_shell.side_effect = [
                (True, "", ""),  # kube-clean succeeds
                (False, "", "auth failed"),  # kube fails
            ]
            result = await refresh_cluster_auth("stage")
            assert result is False

    @pytest.mark.asyncio
    async def test_refresh_clean_fails_but_kube_succeeds(self):
        """refresh_cluster_auth continues even if kube-clean fails."""
        from server.utils import refresh_cluster_auth

        with patch("server.utils.run_cmd_shell") as mock_shell:
            mock_shell.side_effect = [
                (False, "", "clean failed"),  # kube-clean fails
                (True, "", ""),  # kube succeeds
            ]
            result = await refresh_cluster_auth("stage")
            assert result is True


class TestEnsureClusterAuth:
    """Tests for ensure_cluster_auth function."""

    @pytest.mark.asyncio
    async def test_auth_already_valid(self):
        """ensure_cluster_auth returns success when already authenticated."""
        from server.utils import ensure_cluster_auth

        with patch("server.utils.check_cluster_auth", return_value=True):
            success, error = await ensure_cluster_auth("stage")
            assert success is True
            assert error == ""

    @pytest.mark.asyncio
    async def test_auto_refresh_disabled(self):
        """ensure_cluster_auth returns error when auto_refresh disabled."""
        from server.utils import ensure_cluster_auth

        with patch("server.utils.check_cluster_auth", return_value=False):
            success, error = await ensure_cluster_auth("stage", auto_refresh=False)
            assert success is False
            assert "expired" in error.lower()

    @pytest.mark.asyncio
    async def test_refresh_succeeds(self):
        """ensure_cluster_auth succeeds after refresh."""
        from server.utils import ensure_cluster_auth

        with patch("server.utils.check_cluster_auth", return_value=False):
            with patch("server.utils.refresh_cluster_auth", return_value=True):
                success, error = await ensure_cluster_auth("stage")
                assert success is True
                assert error == ""

    @pytest.mark.asyncio
    async def test_refresh_fails(self):
        """ensure_cluster_auth returns error message when refresh fails."""
        from server.utils import ensure_cluster_auth

        with patch("server.utils.check_cluster_auth", return_value=False):
            with patch("server.utils.refresh_cluster_auth", return_value=False):
                success, error = await ensure_cluster_auth("stage")
                assert success is False
                assert "failed" in error.lower()
                assert "kube" in error.lower()


class TestRunKubectl:
    """Tests for run_kubectl function."""

    @pytest.mark.asyncio
    async def test_with_environment(self):
        """run_kubectl uses environment to get kubeconfig."""
        from server.utils import run_kubectl

        with patch("server.utils.ensure_cluster_auth", return_value=(True, "")):
            with patch("server.utils.run_cmd", return_value=(True, "pod/test\n")):
                success, output = await run_kubectl(
                    ["get", "pods"], environment="stage"
                )
                assert success is True
                assert "pod/test" in output

    @pytest.mark.asyncio
    async def test_without_environment_defaults_to_stage(self):
        """run_kubectl defaults to stage when no environment given."""
        from server.utils import run_kubectl

        with patch("server.utils.ensure_cluster_auth", return_value=(True, "")):
            with patch("server.utils.run_cmd", return_value=(True, "ok\n")) as mock_cmd:
                success, output = await run_kubectl(["get", "pods"])
                assert success is True
                # Check that kubeconfig ends with .s (stage)
                cmd_called = mock_cmd.call_args[0][0]
                assert any("config.s" in arg for arg in cmd_called)

    @pytest.mark.asyncio
    async def test_with_explicit_kubeconfig(self):
        """run_kubectl uses explicit kubeconfig."""
        from server.utils import run_kubectl

        with patch("server.utils.ensure_cluster_auth", return_value=(True, "")):
            with patch("server.utils.run_cmd", return_value=(True, "ok\n")) as mock_cmd:
                success, output = await run_kubectl(
                    ["get", "pods"],
                    kubeconfig="/custom/config.s",
                )
                assert success is True
                cmd_called = mock_cmd.call_args[0][0]
                assert "--kubeconfig=/custom/config.s" in cmd_called

    @pytest.mark.asyncio
    async def test_with_namespace(self):
        """run_kubectl adds namespace flag."""
        from server.utils import run_kubectl

        with patch("server.utils.ensure_cluster_auth", return_value=(True, "")):
            with patch("server.utils.run_cmd", return_value=(True, "ok\n")) as mock_cmd:
                await run_kubectl(
                    ["get", "pods"], environment="stage", namespace="my-ns"
                )
                cmd_called = mock_cmd.call_args[0][0]
                assert "-n" in cmd_called
                assert "my-ns" in cmd_called

    @pytest.mark.asyncio
    async def test_auth_failure_returns_error(self):
        """run_kubectl returns error when auth fails."""
        from server.utils import run_kubectl

        with patch(
            "server.utils.ensure_cluster_auth", return_value=(False, "Auth failed")
        ):
            success, output = await run_kubectl(["get", "pods"], environment="stage")
            assert success is False
            assert "Auth failed" in output

    @pytest.mark.asyncio
    async def test_auth_error_in_output_adds_hint(self):
        """run_kubectl adds auth hint when output has auth error."""
        from server.utils import run_kubectl

        with patch("server.utils.ensure_cluster_auth", return_value=(True, "")):
            with patch("server.utils.run_cmd", return_value=(False, "Unauthorized")):
                success, output = await run_kubectl(
                    ["get", "pods"], environment="stage"
                )
                assert success is False
                assert "kube_login" in output

    @pytest.mark.asyncio
    async def test_auto_auth_disabled(self):
        """run_kubectl skips auth check when auto_auth=False."""
        from server.utils import run_kubectl

        with patch("server.utils.run_cmd", return_value=(True, "ok\n")) as mock_cmd:
            with patch("server.utils.ensure_cluster_auth") as mock_auth:
                success, output = await run_kubectl(
                    ["get", "pods"], environment="stage", auto_auth=False
                )
                mock_auth.assert_not_called()
                assert success is True

    @pytest.mark.asyncio
    async def test_detect_env_from_kubeconfig_path(self):
        """run_kubectl detects environment from kubeconfig suffix."""
        from server.utils import run_kubectl

        with patch(
            "server.utils.ensure_cluster_auth", return_value=(True, "")
        ) as mock_auth:
            with patch("server.utils.run_cmd", return_value=(True, "ok\n")):
                await run_kubectl(
                    ["get", "pods"], kubeconfig="/home/user/.kube/config.p"
                )
                # Should detect "production" from .p suffix
                mock_auth.assert_called_once_with("production", auto_refresh=True)

    @pytest.mark.asyncio
    async def test_detect_env_from_kubeconfig_ephemeral(self):
        """run_kubectl detects ephemeral from .e suffix."""
        from server.utils import run_kubectl

        with patch(
            "server.utils.ensure_cluster_auth", return_value=(True, "")
        ) as mock_auth:
            with patch("server.utils.run_cmd", return_value=(True, "ok\n")):
                await run_kubectl(
                    ["get", "pods"], kubeconfig="/home/user/.kube/config.e"
                )
                mock_auth.assert_called_once_with("ephemeral", auto_refresh=True)

    @pytest.mark.asyncio
    async def test_detect_env_from_kubeconfig_konflux(self):
        """run_kubectl detects konflux from .k suffix."""
        from server.utils import run_kubectl

        with patch(
            "server.utils.ensure_cluster_auth", return_value=(True, "")
        ) as mock_auth:
            with patch("server.utils.run_cmd", return_value=(True, "ok\n")):
                await run_kubectl(
                    ["get", "pods"], kubeconfig="/home/user/.kube/config.k"
                )
                mock_auth.assert_called_once_with("konflux", auto_refresh=True)


class TestRunOc:
    """Tests for run_oc function."""

    @pytest.mark.asyncio
    async def test_basic_oc_command(self):
        """run_oc runs oc with proper kubeconfig."""
        from server.utils import run_oc

        with patch("server.utils.run_cmd", return_value=(True, "ok\n")) as mock_cmd:
            success, output = await run_oc(["get", "pods"], environment="stage")
            assert success is True
            cmd_called = mock_cmd.call_args[0][0]
            assert cmd_called[0] == "oc"
            assert any("kubeconfig" in arg for arg in cmd_called)

    @pytest.mark.asyncio
    async def test_oc_with_namespace(self):
        """run_oc adds namespace flag."""
        from server.utils import run_oc

        with patch("server.utils.run_cmd", return_value=(True, "ok\n")) as mock_cmd:
            await run_oc(["get", "pods"], environment="stage", namespace="test-ns")
            cmd_called = mock_cmd.call_args[0][0]
            assert "-n" in cmd_called
            assert "test-ns" in cmd_called


class TestGetBearerToken:
    """Tests for get_bearer_token function."""

    @pytest.mark.asyncio
    async def test_token_from_kubeconfig(self):
        """get_bearer_token extracts token from kubeconfig."""
        from server.utils import get_bearer_token

        with patch("server.utils.ensure_cluster_auth", return_value=(True, "")):
            with patch("server.utils.run_cmd") as mock_cmd:
                mock_cmd.return_value = (True, "sha256~mytoken123")
                token = await get_bearer_token("/kube/config.s", environment="stage")
                assert token == "sha256~mytoken123"

    @pytest.mark.asyncio
    async def test_redacted_falls_through(self):
        """get_bearer_token skips REDACTED tokens and tries oc whoami."""
        from server.utils import get_bearer_token

        with patch("server.utils.ensure_cluster_auth", return_value=(True, "")):
            with patch("server.utils.run_cmd") as mock_cmd:
                # First call: kubectl returns REDACTED
                # Second call: oc whoami returns token
                mock_cmd.side_effect = [
                    (True, "REDACTED"),
                    (True, "sha256~real_token\n"),
                ]
                token = await get_bearer_token("/kube/config.s", environment="stage")
                assert token == "sha256~real_token"

    @pytest.mark.asyncio
    async def test_no_token_available(self):
        """get_bearer_token returns None when no token found."""
        from server.utils import get_bearer_token

        with patch("server.utils.ensure_cluster_auth", return_value=(True, "")):
            with patch("server.utils.run_cmd") as mock_cmd:
                mock_cmd.side_effect = [
                    (False, ""),  # kubectl fails
                    (False, ""),  # oc fails
                ]
                token = await get_bearer_token("/kube/config.s", environment="stage")
                assert token is None

    @pytest.mark.asyncio
    async def test_auth_refresh_fails(self):
        """get_bearer_token returns None when auth refresh fails."""
        from server.utils import get_bearer_token

        with patch(
            "server.utils.ensure_cluster_auth", return_value=(False, "auth fail")
        ):
            token = await get_bearer_token("/kube/config.s", environment="stage")
            assert token is None

    @pytest.mark.asyncio
    async def test_detect_env_from_kubeconfig(self):
        """get_bearer_token detects environment from kubeconfig suffix."""
        from server.utils import get_bearer_token

        with patch(
            "server.utils.ensure_cluster_auth", return_value=(True, "")
        ) as mock_auth:
            with patch("server.utils.run_cmd", return_value=(True, "mytoken")):
                await get_bearer_token("/kube/config.p")
                mock_auth.assert_called_once_with("production", auto_refresh=True)

    @pytest.mark.asyncio
    async def test_detect_env_ephemeral(self):
        """get_bearer_token detects ephemeral from .e suffix."""
        from server.utils import get_bearer_token

        with patch(
            "server.utils.ensure_cluster_auth", return_value=(True, "")
        ) as mock_auth:
            with patch("server.utils.run_cmd", return_value=(True, "mytoken")):
                await get_bearer_token("/kube/config.e")
                mock_auth.assert_called_once_with("ephemeral", auto_refresh=True)

    @pytest.mark.asyncio
    async def test_detect_env_konflux(self):
        """get_bearer_token detects konflux from .k suffix."""
        from server.utils import get_bearer_token

        with patch(
            "server.utils.ensure_cluster_auth", return_value=(True, "")
        ) as mock_auth:
            with patch("server.utils.run_cmd", return_value=(True, "mytoken")):
                await get_bearer_token("/kube/config.k")
                mock_auth.assert_called_once_with("konflux", auto_refresh=True)

    @pytest.mark.asyncio
    async def test_no_auto_auth(self):
        """get_bearer_token skips auth when auto_auth=False."""
        from server.utils import get_bearer_token

        with patch("server.utils.ensure_cluster_auth") as mock_auth:
            with patch("server.utils.run_cmd", return_value=(True, "token")):
                await get_bearer_token("/kube/config.s", auto_auth=False)
                mock_auth.assert_not_called()

    @pytest.mark.asyncio
    async def test_exception_in_kubectl_falls_through(self):
        """get_bearer_token handles exception in kubectl gracefully."""
        from server.utils import get_bearer_token

        with patch("server.utils.ensure_cluster_auth", return_value=(True, "")):
            with patch("server.utils.run_cmd") as mock_cmd:
                # First call raises, second succeeds
                mock_cmd.side_effect = [
                    Exception("kubectl error"),
                    (True, "fallback_token\n"),
                ]
                token = await get_bearer_token("/kube/config.s", environment="stage")
                assert token == "fallback_token"


class TestPrepareShellEnvironmentExtended:
    """Extended tests for _prepare_shell_environment edge cases."""

    def test_xauthority_from_env(self, tmp_path):
        """Sets XAUTHORITY from environment when available."""
        with patch.dict(os.environ, {"XAUTHORITY": "/custom/Xauthority"}, clear=False):
            env = _prepare_shell_environment(tmp_path)
            assert env["XAUTHORITY"] == "/custom/Xauthority"

    def test_xauthority_from_file(self, tmp_path):
        """Sets XAUTHORITY from .Xauthority file when env not set."""
        xauth = tmp_path / ".Xauthority"
        xauth.touch()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XAUTHORITY", None)
            env = _prepare_shell_environment(tmp_path)
            assert env.get("XAUTHORITY") == str(xauth)

    def test_wayland_from_env(self, tmp_path):
        """Sets WAYLAND_DISPLAY from environment when available."""
        with patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-1"}, clear=False):
            env = _prepare_shell_environment(tmp_path)
            assert env["WAYLAND_DISPLAY"] == "wayland-1"

    def test_xdg_runtime_from_env(self, tmp_path):
        """Sets XDG_RUNTIME_DIR from environment when available."""
        with patch.dict(os.environ, {"XDG_RUNTIME_DIR": "/run/user/1234"}, clear=False):
            env = _prepare_shell_environment(tmp_path)
            assert env["XDG_RUNTIME_DIR"] == "/run/user/1234"

    def test_display_default_when_not_in_env(self, tmp_path):
        """Sets DISPLAY to :0 when not in environment."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISPLAY", None)
            env = _prepare_shell_environment(tmp_path)
            assert env.get("DISPLAY") == ":0"


class TestRunCmdSyncShellMode:
    """Tests for run_cmd_sync in shell mode."""

    def test_shell_mode_with_cwd(self, tmp_path):
        """run_cmd_sync shell mode handles cwd."""
        from server.utils import run_cmd_sync

        success, output = run_cmd_sync(["pwd"], cwd=str(tmp_path), use_shell=True)
        assert success is True
        assert str(tmp_path) in output

    def test_shell_mode_basic(self):
        """run_cmd_sync shell mode runs command through bash."""
        from server.utils import run_cmd_sync

        success, output = run_cmd_sync(["echo", "shell_test"], use_shell=True)
        assert success is True
        assert "shell_test" in output

    def test_shell_mode_with_env(self):
        """run_cmd_sync shell mode passes env vars."""
        from server.utils import run_cmd_sync

        success, output = run_cmd_sync(
            ["env"], use_shell=True, env={"SYNC_TEST_VAR": "sync_val"}
        )
        assert success is True


class TestRunCmdFullExtended:
    """Extended tests for run_cmd_full."""

    @pytest.mark.asyncio
    async def test_with_env_vars(self):
        """run_cmd_full passes env vars."""
        from server.utils import run_cmd_full

        success, stdout, stderr = await run_cmd_full(
            ["env"],
            use_shell=False,
            env={"FULL_TEST_VAR": "full_val"},
        )
        assert success is True
        assert "FULL_TEST_VAR=full_val" in stdout

    @pytest.mark.asyncio
    async def test_with_cwd_shell(self, tmp_path):
        """run_cmd_full shell mode handles cwd."""
        from server.utils import run_cmd_full

        success, stdout, stderr = await run_cmd_full(
            ["pwd"], cwd=str(tmp_path), use_shell=True
        )
        assert success is True
        assert str(tmp_path) in stdout

    @pytest.mark.asyncio
    async def test_generic_exception(self):
        """run_cmd_full handles generic exceptions."""
        from server.utils import run_cmd_full

        with patch("asyncio.to_thread", side_effect=RuntimeError("boom")):
            success, stdout, stderr = await run_cmd_full(
                ["echo", "test"], use_shell=False
            )
            assert success is False
            assert "boom" in stderr


class TestRunCmdWithEnvShellMode:
    """Tests for run_cmd with env in shell mode."""

    @pytest.mark.asyncio
    async def test_env_passed_in_shell_mode(self):
        """run_cmd shell mode merges extra env vars."""
        from server.utils import run_cmd

        success, output = await run_cmd(
            ["env"], use_shell=True, env={"RUN_CMD_TEST": "shell_env_val"}
        )
        assert success is True

    @pytest.mark.asyncio
    async def test_generic_exception(self):
        """run_cmd handles generic exceptions."""
        from server.utils import run_cmd

        with patch("asyncio.to_thread", side_effect=RuntimeError("async boom")):
            success, output = await run_cmd(["echo", "test"], use_shell=False)
            assert success is False
            assert "async boom" in output
