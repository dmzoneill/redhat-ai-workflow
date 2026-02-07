"""Tests for shared utilities in server/utils.py."""

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

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
    def test_load_config_returns_dict(self, project_root):
        config = load_config()
        assert isinstance(config, dict)

    def test_load_config_has_repositories(self, project_root):
        config = load_config()
        assert config is not None


class TestGetSectionConfig:
    def test_get_section_returns_dict(self):
        result = get_section_config("nonexistent_section", {})
        assert isinstance(result, dict)

    def test_get_section_with_default(self):
        default = {"key": "value"}
        result = get_section_config("definitely_not_a_section", default)
        assert result == default


class TestGetProjectRoot:
    def test_returns_path(self):
        result = get_project_root()
        assert isinstance(result, Path)

    def test_path_exists(self):
        result = get_project_root()
        assert result.exists()


class TestGetKubeconfig:
    def test_returns_string(self):
        result = get_kubeconfig("stage")
        assert isinstance(result, str)

    def test_stage_config_suffix(self):
        result = get_kubeconfig("stage")
        assert "config" in result

    def test_prod_config_suffix(self):
        result = get_kubeconfig("prod")
        assert "config" in result

    def test_ephemeral_config_suffix(self):
        result = get_kubeconfig("ephemeral")
        assert "config" in result


class TestGetUsername:
    def test_returns_string(self):
        result = get_username()
        assert isinstance(result, str)

    def test_not_empty(self):
        result = get_username()
        assert len(result) > 0


class TestResolveRepoPath:
    def test_returns_path(self):
        result = resolve_repo_path(".")
        assert isinstance(result, (Path, str))

    def test_absolute_path_preserved(self, tmp_path):
        result = resolve_repo_path(str(tmp_path))
        assert str(tmp_path) in str(result)

    def test_current_dir_resolves(self):
        result = resolve_repo_path(".")
        result_path = Path(result) if isinstance(result, str) else result
        assert result_path.exists()


class TestTruncateOutput:
    def test_short_text_unchanged(self):
        assert truncate_output("hello", max_length=100) == "hello"

    def test_empty_text(self):
        assert truncate_output("") == ""

    def test_none_text(self):
        assert truncate_output(None) is None

    def test_head_mode_truncation(self):
        text = "a" * 100
        result = truncate_output(text, max_length=50, mode="head")
        assert len(result) == 50 + len("\n\n... (truncated)")
        assert result.startswith("a" * 50)
        assert result.endswith("... (truncated)")

    def test_tail_mode_truncation(self):
        text = "a" * 50 + "b" * 50
        result = truncate_output(text, max_length=50, mode="tail")
        assert "b" * 50 in result
        assert "truncated" in result.lower()

    def test_custom_suffix(self):
        text = "x" * 100
        result = truncate_output(text, max_length=10, suffix=" [CUT]")
        assert result.endswith("[CUT]")

    def test_tail_mode_empty_suffix(self):
        text = "x" * 100
        result = truncate_output(text, max_length=50, suffix="", mode="tail")
        assert "truncated" in result.lower()

    def test_exactly_at_limit(self):
        text = "a" * 50
        result = truncate_output(text, max_length=50)
        assert result == text


class TestFormatError:
    def test_basic_error(self):
        result = format_error("Something failed")
        assert "Something failed" in result

    def test_error_with_output(self):
        result = format_error("Failed", output="stderr output")
        assert "Failed" in result
        assert "stderr output" in result

    def test_error_with_hint(self):
        result = format_error("Failed", hint="Try again")
        assert "Try again" in result

    def test_error_with_tool_name(self):
        result = format_error("Failed", tool_name="my_tool")
        assert "debug_tool" in result
        assert "my_tool" in result

    def test_error_all_parts(self):
        result = format_error("Error", output="out", hint="fix", tool_name="t")
        assert "Error" in result
        assert "out" in result
        assert "fix" in result
        assert "t" in result


class TestFormatSuccess:
    def test_basic_success(self):
        result = format_success("Done")
        assert "Done" in result

    def test_success_with_details(self):
        result = format_success("Done", file_count=5, elapsed_time="2s")
        assert "Done" in result
        assert "File Count" in result
        assert "5" in result
        assert "Elapsed Time" in result
        assert "2s" in result


class TestFormatWarning:
    def test_basic_warning(self):
        result = format_warning("Watch out")
        assert "Watch out" in result

    def test_warning_with_action(self):
        result = format_warning("Careful", action="Check logs")
        assert "Careful" in result
        assert "Check logs" in result

    def test_warning_no_action(self):
        result = format_warning("Simple warning")
        assert result.count("\n") == 0


class TestFormatList:
    def test_empty_list(self):
        result = format_list("Items:", [])
        assert "Items:" in result
        assert "None found." in result

    def test_string_items(self):
        result = format_list("Items:", ["one", "two", "three"])
        assert "Items:" in result
        assert "one" in result
        assert "two" in result
        assert "three" in result

    def test_dict_items_with_key(self):
        items = [{"name": "Alice"}, {"name": "Bob"}]
        result = format_list("People:", items, item_key="name")
        assert "Alice" in result
        assert "Bob" in result

    def test_dict_items_missing_key(self):
        items = [{"other": "value"}]
        result = format_list("Items:", items, item_key="name")
        assert "other" in result

    def test_custom_empty_message(self):
        result = format_list("Items:", [], empty_message="Nothing here!")
        assert "Nothing here!" in result


class TestGetKubeconfigExtended:
    def test_empty_environment_raises(self):
        with pytest.raises(ValueError, match="Environment is required"):
            get_kubeconfig("")

    def test_whitespace_environment_raises(self):
        with pytest.raises(ValueError, match="Environment is required"):
            get_kubeconfig("   ")

    def test_kubeconfig_from_namespaces(self):
        with patch("server.utils.load_config") as mock_load:
            mock_load.return_value = {
                "namespaces": {"stage": {"kubeconfig": "~/custom/kube.s"}},
            }
            result = get_kubeconfig("stage")
            assert "custom/kube.s" in result

    def test_kubeconfig_from_kubernetes_environments(self):
        with patch("server.utils.load_config") as mock_load:
            mock_load.return_value = {
                "namespaces": {},
                "kubernetes": {
                    "environments": {"stage": {"kubeconfig": "~/k8s/config.stage"}}
                },
            }
            result = get_kubeconfig("stage")
            assert "k8s/config.stage" in result

    def test_kubeconfig_fallback_to_standard(self):
        with patch("server.utils.load_config") as mock_load:
            mock_load.return_value = {}
            result = get_kubeconfig("stage")
            assert result.endswith("config.s")

    def test_kubeconfig_unknown_env(self):
        with patch("server.utils.load_config") as mock_load:
            mock_load.return_value = {}
            result = get_kubeconfig("custom-env")
            assert result.endswith("config.custom-env")

    def test_kubeconfig_aliases(self):
        with patch("server.utils.load_config") as mock_load:
            mock_load.return_value = {}
            assert get_kubeconfig("s").endswith("config.s")
            assert get_kubeconfig("production").endswith("config.p")
            assert get_kubeconfig("p").endswith("config.p")
            assert get_kubeconfig("eph").endswith("config.e")
            assert get_kubeconfig("e").endswith("config.e")
            assert get_kubeconfig("konflux").endswith("config.k")
            assert get_kubeconfig("k").endswith("config.k")
            assert get_kubeconfig("saas").endswith("config.ap")


class TestGetClusterShortName:
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
    def test_returns_env_config(self):
        with patch("server.utils.load_config") as mock_load:
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

    def test_prod_alias(self):
        with patch("server.utils.load_config") as mock_load:
            mock_load.return_value = {
                "prometheus": {
                    "environments": {
                        "production": {"url": "https://prom.prod.example.com"}
                    }
                }
            }
            result = get_env_config("prod", "prometheus")
            assert result["url"] == "https://prom.prod.example.com"

    def test_missing_kubeconfig_uses_default(self):
        with patch("server.utils.load_config") as mock_load:
            mock_load.return_value = {
                "prometheus": {
                    "environments": {"stage": {"url": "https://prom.stage.example.com"}}
                }
            }
            result = get_env_config("stage", "prometheus")
            assert "kubeconfig" in result


class TestResolveRepoPathExtended:
    def test_resolve_from_config(self, tmp_path):
        with patch("server.utils.load_config") as mock_load:
            repo_dir = tmp_path / "my-repo"
            repo_dir.mkdir()
            mock_load.return_value = {
                "repositories": {"my-repo": {"path": str(repo_dir)}},
                "paths": {},
            }
            result = resolve_repo_path("my-repo")
            assert result == str(repo_dir)

    def test_resolve_from_workspace_roots(self, tmp_path):
        with patch("server.utils.load_config") as mock_load:
            repo_dir = tmp_path / "my-repo"
            repo_dir.mkdir()
            mock_load.return_value = {
                "repositories": {},
                "paths": {"workspace_roots": [str(tmp_path)]},
            }
            result = resolve_repo_path("my-repo")
            assert result == str(repo_dir)

    def test_resolve_not_found_returns_as_is(self):
        with patch("server.utils.load_config") as mock_load:
            mock_load.return_value = {"repositories": {}, "paths": {}}
            result = resolve_repo_path("nonexistent-repo-xyz")
            assert result == "nonexistent-repo-xyz"

    def test_resolve_expanduser(self, tmp_path):
        result = resolve_repo_path(str(tmp_path))
        assert result == str(tmp_path)


class TestGetRepoConfig:
    def test_exact_match(self):
        with patch("server.utils.load_config") as mock_load:
            mock_load.return_value = {
                "repositories": {
                    "backend": {
                        "path": "/home/user/backend",
                        "gitlab": "org/backend",
                    }
                }
            }
            result = get_repo_config("backend")
            assert result["path"] == "/home/user/backend"

    def test_match_by_path(self):
        with patch("server.utils.load_config") as mock_load:
            mock_load.return_value = {
                "repositories": {
                    "backend": {
                        "path": "/home/user/backend",
                        "gitlab": "org/backend",
                    }
                }
            }
            result = get_repo_config("backend")
            assert result["gitlab"] == "org/backend"

    def test_not_found(self):
        with patch("server.utils.load_config") as mock_load:
            mock_load.return_value = {"repositories": {}}
            result = get_repo_config("nonexistent")
            assert result == {}


class TestBuildShellSources:
    def test_no_bashrc(self, tmp_path):
        result = _build_shell_sources(tmp_path)
        assert result == []

    def test_with_bashrc(self, tmp_path):
        (tmp_path / ".bashrc").touch()
        result = _build_shell_sources(tmp_path)
        assert any(".bashrc" in s for s in result)

    def test_with_bashrc_d(self, tmp_path):
        bashrc_d = tmp_path / ".bashrc.d"
        bashrc_d.mkdir()
        (bashrc_d / "00-loader.sh").touch()
        (bashrc_d / "10-custom.sh").touch()
        result = _build_shell_sources(tmp_path)
        assert any("00-loader.sh" in s for s in result)
        assert any("10-custom.sh" in s for s in result)

    def test_bashrc_d_without_loader(self, tmp_path):
        bashrc_d = tmp_path / ".bashrc.d"
        bashrc_d.mkdir()
        (bashrc_d / "custom.sh").touch()
        result = _build_shell_sources(tmp_path)
        assert any("custom.sh" in s for s in result)


class TestPrepareShellEnvironment:
    def test_sets_home(self, tmp_path):
        env = _prepare_shell_environment(tmp_path)
        assert env["HOME"] == str(tmp_path)

    def test_sets_user(self, tmp_path):
        env = _prepare_shell_environment(tmp_path)
        assert env["USER"] == tmp_path.name

    def test_clears_virtualenv(self, tmp_path):
        with patch.dict(
            os.environ, {"VIRTUAL_ENV": "/some/venv", "PIPENV_ACTIVE": "1"}
        ):
            env = _prepare_shell_environment(tmp_path)
            assert "VIRTUAL_ENV" not in env
            assert "PIPENV_ACTIVE" not in env

    def test_removes_venv_from_path(self, tmp_path):
        with patch.dict(
            os.environ, {"PATH": "/usr/bin:/some/.venv/bin:/usr/local/bin"}
        ):
            env = _prepare_shell_environment(tmp_path)
            assert ".venv" not in env["PATH"]

    def test_adds_user_bin(self, tmp_path):
        env = _prepare_shell_environment(tmp_path)
        assert str(tmp_path / "bin") in env["PATH"]

    def test_sets_display(self, tmp_path):
        env = _prepare_shell_environment(tmp_path)
        assert "DISPLAY" in env


class TestGetGitlabHost:
    def test_from_env(self):
        with patch.dict(os.environ, {"GITLAB_HOST": "custom.gitlab.com"}):
            result = get_gitlab_host()
            assert result == "custom.gitlab.com"

    def test_from_config(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GITLAB_HOST", None)
            with patch("server.utils.load_config") as mock_load:
                mock_load.return_value = {"gitlab": {"host": "my-gitlab.example.com"}}
                result = get_gitlab_host()
                assert result == "my-gitlab.example.com"

    def test_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GITLAB_HOST", None)
            with patch("server.utils.load_config") as mock_load:
                mock_load.return_value = {}
                result = get_gitlab_host()
                assert result == "gitlab.cee.redhat.com"


class TestGetServiceUrl:
    def test_returns_url_from_config(self):
        with patch("server.utils.get_env_config") as mock_env_config:
            mock_env_config.return_value = {"url": "https://prom.example.com"}
            result = get_service_url("prometheus", "stage")
            assert result == "https://prom.example.com"

    def test_empty_environment_raises(self):
        with pytest.raises(ValueError, match="environment"):
            get_service_url("prometheus", "")

    def test_whitespace_environment_raises(self):
        with pytest.raises(ValueError, match="environment"):
            get_service_url("prometheus", "   ")

    def test_fallback_to_env_var(self):
        with patch("server.utils.get_env_config") as mock_env_config:
            with patch.dict(
                os.environ,
                {"PROMETHEUS_STAGE_URL": "https://env-var-prom.example.com"},
            ):
                mock_env_config.return_value = {}
                result = get_service_url("prometheus", "stage")
                assert result == "https://env-var-prom.example.com"

    def test_raises_when_not_configured(self):
        with patch("server.utils.get_env_config") as mock_env_config:
            mock_env_config.return_value = {}
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("PROMETHEUS_STAGE_URL", None)
                with pytest.raises(ValueError, match="not configured"):
                    get_service_url("prometheus", "stage")


class TestGetUserConfig:
    def test_returns_user_config(self):
        with patch("server.utils.get_section_config") as mock_section:
            mock_section.return_value = {
                "username": "testuser",
                "email": "test@test.com",
            }
            result = get_user_config()
            assert result["username"] == "testuser"


class TestRunCmdSync:
    def test_successful_command(self):
        from server.utils import run_cmd_sync

        success, output = run_cmd_sync(["echo", "hello"], use_shell=False)
        assert success is True
        assert "hello" in output

    def test_failed_command(self):
        from server.utils import run_cmd_sync

        success, output = run_cmd_sync(["false"], use_shell=False)
        assert success is False

    def test_timeout(self):
        from server.utils import run_cmd_sync

        success, output = run_cmd_sync(["sleep", "60"], use_shell=False, timeout=1)
        assert success is False
        assert "timed out" in output

    def test_command_not_found(self):
        from server.utils import run_cmd_sync

        success, output = run_cmd_sync(
            ["nonexistent_command_xyz_abc_123"], use_shell=False
        )
        assert success is False
        assert "not found" in output.lower() or "nonexistent" in output.lower()

    def test_with_env(self):
        from server.utils import run_cmd_sync

        success, output = run_cmd_sync(
            ["env"], use_shell=False, env={"MY_TEST_VAR": "my_test_value"}
        )
        assert success is True
        assert "MY_TEST_VAR=my_test_value" in output

    def test_with_cwd(self, tmp_path):
        from server.utils import run_cmd_sync

        success, output = run_cmd_sync(["pwd"], use_shell=False, cwd=str(tmp_path))
        assert success is True
        assert str(tmp_path) in output


class TestRunCmd:
    @pytest.mark.asyncio
    async def test_successful_command(self):
        from server.utils import run_cmd

        success, output = await run_cmd(["echo", "hello"], use_shell=False)
        assert success is True
        assert "hello" in output

    @pytest.mark.asyncio
    async def test_failed_command(self):
        from server.utils import run_cmd

        success, output = await run_cmd(["false"], use_shell=False)
        assert success is False

    @pytest.mark.asyncio
    async def test_timeout(self):
        from server.utils import run_cmd

        success, output = await run_cmd(["sleep", "60"], use_shell=False, timeout=1)
        assert success is False
        assert "timed out" in output

    @pytest.mark.asyncio
    async def test_command_not_found(self):
        from server.utils import run_cmd

        success, output = await run_cmd(
            ["nonexistent_command_xyz_abc_123"], use_shell=False
        )
        assert success is False

    @pytest.mark.asyncio
    async def test_check_raises(self):
        from server.utils import run_cmd

        with pytest.raises(subprocess.CalledProcessError):
            await run_cmd(["false"], use_shell=False, check=True)

    @pytest.mark.asyncio
    async def test_with_cwd_shell_mode(self, tmp_path):
        from server.utils import run_cmd

        success, output = await run_cmd(["pwd"], cwd=str(tmp_path), use_shell=True)
        assert success is True
        assert str(tmp_path) in output


class TestRunCmdFull:
    @pytest.mark.asyncio
    async def test_returns_three_parts(self):
        from server.utils import run_cmd_full

        success, stdout, stderr = await run_cmd_full(["echo", "hello"], use_shell=False)
        assert success is True
        assert "hello" in stdout
        assert stderr == "" or isinstance(stderr, str)

    @pytest.mark.asyncio
    async def test_timeout(self):
        from server.utils import run_cmd_full

        success, stdout, stderr = await run_cmd_full(
            ["sleep", "60"], use_shell=False, timeout=1
        )
        assert success is False
        assert "timed out" in stderr

    @pytest.mark.asyncio
    async def test_command_not_found(self):
        from server.utils import run_cmd_full

        success, stdout, stderr = await run_cmd_full(
            ["nonexistent_command_xyz_abc_123"], use_shell=False
        )
        assert success is False

    @pytest.mark.asyncio
    async def test_failure(self):
        from server.utils import run_cmd_full

        success, stdout, stderr = await run_cmd_full(
            ["ls", "/nonexistent_path_xyz"], use_shell=False
        )
        assert success is False


class TestRunCmdShell:
    @pytest.mark.asyncio
    async def test_delegates_to_run_cmd_full(self):
        from server.utils import run_cmd_shell

        success, stdout, stderr = await run_cmd_shell(["echo", "test"])
        assert success is True
        assert "test" in stdout


class TestLoadConfigReload:
    def test_load_config_reload(self):
        with patch("server.utils._config_manager") as mock_cm:
            mock_cm.get_all.return_value = {"refreshed": True}
            result = load_config(reload=True)
            mock_cm.reload.assert_called_once()
            assert result == {"refreshed": True}


class TestGetKubeBase:
    def test_custom_kube_base(self):
        with patch("server.utils.load_config") as mock_load:
            from server.utils import _get_kube_base

            mock_load.return_value = {"paths": {"kube_base": "~/custom-kube"}}
            result = _get_kube_base()
            assert "custom-kube" in str(result)

    def test_default_kube_base(self):
        with patch("server.utils.load_config") as mock_load:
            from server.utils import _get_kube_base

            mock_load.return_value = {"paths": {}}
            result = _get_kube_base()
            assert str(result).endswith(".kube")


class TestGetRepoConfigPathMatch:
    def test_match_by_path_suffix(self):
        with patch("server.utils.load_config") as mock_load:
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
    @pytest.mark.asyncio
    async def test_kubeconfig_not_found(self):
        from server.utils import check_cluster_auth

        with patch(
            "server.utils.get_kubeconfig", return_value="/nonexistent/kube/config"
        ):
            with patch("os.path.exists", return_value=False):
                result = await check_cluster_auth("stage")
                assert result is False

    @pytest.mark.asyncio
    async def test_auth_valid(self):
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
        from server.utils import check_cluster_auth

        with patch("server.utils.get_kubeconfig", return_value="/tmp/kube/config.s"):
            with patch("os.path.exists", return_value=True):
                with patch(
                    "asyncio.to_thread", side_effect=Exception("connection error")
                ):
                    result = await check_cluster_auth("stage")
                    assert result is False


class TestRefreshClusterAuth:
    @pytest.mark.asyncio
    async def test_refresh_success(self):
        from server.utils import refresh_cluster_auth

        with patch("server.utils.run_cmd_shell") as mock_shell:
            mock_shell.side_effect = [
                (True, "", ""),
                (True, "", ""),
            ]
            result = await refresh_cluster_auth("stage")
            assert result is True

    @pytest.mark.asyncio
    async def test_refresh_failure(self):
        from server.utils import refresh_cluster_auth

        with patch("server.utils.run_cmd_shell") as mock_shell:
            mock_shell.side_effect = [
                (True, "", ""),
                (False, "", "auth failed"),
            ]
            result = await refresh_cluster_auth("stage")
            assert result is False

    @pytest.mark.asyncio
    async def test_refresh_clean_fails_but_kube_succeeds(self):
        from server.utils import refresh_cluster_auth

        with patch("server.utils.run_cmd_shell") as mock_shell:
            mock_shell.side_effect = [
                (False, "", "clean failed"),
                (True, "", ""),
            ]
            result = await refresh_cluster_auth("stage")
            assert result is True


class TestEnsureClusterAuth:
    @pytest.mark.asyncio
    async def test_auth_already_valid(self):
        from server.utils import ensure_cluster_auth

        with patch("server.utils.check_cluster_auth", return_value=True):
            success, error = await ensure_cluster_auth("stage")
            assert success is True
            assert error == ""

    @pytest.mark.asyncio
    async def test_auto_refresh_disabled(self):
        from server.utils import ensure_cluster_auth

        with patch("server.utils.check_cluster_auth", return_value=False):
            success, error = await ensure_cluster_auth("stage", auto_refresh=False)
            assert success is False
            assert "expired" in error.lower()

    @pytest.mark.asyncio
    async def test_refresh_succeeds(self):
        from server.utils import ensure_cluster_auth

        with patch("server.utils.check_cluster_auth", return_value=False):
            with patch("server.utils.refresh_cluster_auth", return_value=True):
                success, error = await ensure_cluster_auth("stage")
                assert success is True
                assert error == ""

    @pytest.mark.asyncio
    async def test_refresh_fails(self):
        from server.utils import ensure_cluster_auth

        with patch("server.utils.check_cluster_auth", return_value=False):
            with patch("server.utils.refresh_cluster_auth", return_value=False):
                success, error = await ensure_cluster_auth("stage")
                assert success is False
                assert "failed" in error.lower()
                assert "kube" in error.lower()


class TestRunKubectl:
    @pytest.mark.asyncio
    async def test_with_environment(self):
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
        from server.utils import run_kubectl

        with patch("server.utils.ensure_cluster_auth", return_value=(True, "")):
            with patch("server.utils.run_cmd", return_value=(True, "ok\n")) as mock_cmd:
                success, output = await run_kubectl(["get", "pods"])
                assert success is True
                cmd_called = mock_cmd.call_args[0][0]
                assert any("config.s" in arg for arg in cmd_called)

    @pytest.mark.asyncio
    async def test_with_explicit_kubeconfig(self):
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
        from server.utils import run_kubectl

        with patch(
            "server.utils.ensure_cluster_auth", return_value=(False, "Auth failed")
        ):
            success, output = await run_kubectl(["get", "pods"], environment="stage")
            assert success is False
            assert "Auth failed" in output

    @pytest.mark.asyncio
    async def test_auth_error_in_output_adds_hint(self):
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
        from server.utils import run_kubectl

        with patch("server.utils.run_cmd", return_value=(True, "ok\n")):
            with patch("server.utils.ensure_cluster_auth") as mock_auth:
                success, output = await run_kubectl(
                    ["get", "pods"], environment="stage", auto_auth=False
                )
                mock_auth.assert_not_called()
                assert success is True

    @pytest.mark.asyncio
    async def test_detect_env_from_kubeconfig_path(self):
        from server.utils import run_kubectl

        with patch(
            "server.utils.ensure_cluster_auth", return_value=(True, "")
        ) as mock_auth:
            with patch("server.utils.run_cmd", return_value=(True, "ok\n")):
                await run_kubectl(
                    ["get", "pods"], kubeconfig="/home/user/.kube/config.p"
                )
                mock_auth.assert_called_once_with("production", auto_refresh=True)

    @pytest.mark.asyncio
    async def test_detect_env_from_kubeconfig_ephemeral(self):
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
    @pytest.mark.asyncio
    async def test_basic_oc_command(self):
        from server.utils import run_oc

        with patch("server.utils.run_cmd", return_value=(True, "ok\n")) as mock_cmd:
            success, output = await run_oc(["get", "pods"], environment="stage")
            assert success is True
            cmd_called = mock_cmd.call_args[0][0]
            assert cmd_called[0] == "oc"
            assert any("kubeconfig" in arg for arg in cmd_called)

    @pytest.mark.asyncio
    async def test_oc_with_namespace(self):
        from server.utils import run_oc

        with patch("server.utils.run_cmd", return_value=(True, "ok\n")) as mock_cmd:
            await run_oc(["get", "pods"], environment="stage", namespace="test-ns")
            cmd_called = mock_cmd.call_args[0][0]
            assert "-n" in cmd_called
            assert "test-ns" in cmd_called


class TestGetBearerToken:
    @pytest.mark.asyncio
    async def test_token_from_kubeconfig(self):
        from server.utils import get_bearer_token

        with patch("server.utils.ensure_cluster_auth", return_value=(True, "")):
            with patch("server.utils.run_cmd") as mock_cmd:
                mock_cmd.return_value = (True, "sha256~mytoken123")
                token = await get_bearer_token("/kube/config.s", environment="stage")
                assert token == "sha256~mytoken123"

    @pytest.mark.asyncio
    async def test_redacted_falls_through(self):
        from server.utils import get_bearer_token

        with patch("server.utils.ensure_cluster_auth", return_value=(True, "")):
            with patch("server.utils.run_cmd") as mock_cmd:
                mock_cmd.side_effect = [
                    (True, "REDACTED"),
                    (True, "sha256~real_token\n"),
                ]
                token = await get_bearer_token("/kube/config.s", environment="stage")
                assert token == "sha256~real_token"

    @pytest.mark.asyncio
    async def test_no_token_available(self):
        from server.utils import get_bearer_token

        with patch("server.utils.ensure_cluster_auth", return_value=(True, "")):
            with patch("server.utils.run_cmd") as mock_cmd:
                mock_cmd.side_effect = [
                    (False, ""),
                    (False, ""),
                ]
                token = await get_bearer_token("/kube/config.s", environment="stage")
                assert token is None

    @pytest.mark.asyncio
    async def test_auth_refresh_fails(self):
        from server.utils import get_bearer_token

        with patch(
            "server.utils.ensure_cluster_auth", return_value=(False, "auth fail")
        ):
            token = await get_bearer_token("/kube/config.s", environment="stage")
            assert token is None

    @pytest.mark.asyncio
    async def test_detect_env_from_kubeconfig(self):
        from server.utils import get_bearer_token

        with patch(
            "server.utils.ensure_cluster_auth", return_value=(True, "")
        ) as mock_auth:
            with patch("server.utils.run_cmd", return_value=(True, "mytoken")):
                await get_bearer_token("/kube/config.p")
                mock_auth.assert_called_once_with("production", auto_refresh=True)

    @pytest.mark.asyncio
    async def test_detect_env_ephemeral(self):
        from server.utils import get_bearer_token

        with patch(
            "server.utils.ensure_cluster_auth", return_value=(True, "")
        ) as mock_auth:
            with patch("server.utils.run_cmd", return_value=(True, "mytoken")):
                await get_bearer_token("/kube/config.e")
                mock_auth.assert_called_once_with("ephemeral", auto_refresh=True)

    @pytest.mark.asyncio
    async def test_detect_env_konflux(self):
        from server.utils import get_bearer_token

        with patch(
            "server.utils.ensure_cluster_auth", return_value=(True, "")
        ) as mock_auth:
            with patch("server.utils.run_cmd", return_value=(True, "mytoken")):
                await get_bearer_token("/kube/config.k")
                mock_auth.assert_called_once_with("konflux", auto_refresh=True)

    @pytest.mark.asyncio
    async def test_no_auto_auth(self):
        from server.utils import get_bearer_token

        with patch("server.utils.ensure_cluster_auth") as mock_auth:
            with patch("server.utils.run_cmd", return_value=(True, "token")):
                await get_bearer_token("/kube/config.s", auto_auth=False)
                mock_auth.assert_not_called()

    @pytest.mark.asyncio
    async def test_exception_in_kubectl_falls_through(self):
        from server.utils import get_bearer_token

        with patch("server.utils.ensure_cluster_auth", return_value=(True, "")):
            with patch("server.utils.run_cmd") as mock_cmd:
                mock_cmd.side_effect = [
                    Exception("kubectl error"),
                    (True, "fallback_token\n"),
                ]
                token = await get_bearer_token("/kube/config.s", environment="stage")
                assert token == "fallback_token"


class TestPrepareShellEnvironmentExtended:
    def test_xauthority_from_env(self, tmp_path):
        with patch.dict(os.environ, {"XAUTHORITY": "/custom/Xauthority"}, clear=False):
            env = _prepare_shell_environment(tmp_path)
            assert env["XAUTHORITY"] == "/custom/Xauthority"

    def test_xauthority_from_file(self, tmp_path):
        xauth = tmp_path / ".Xauthority"
        xauth.touch()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XAUTHORITY", None)
            env = _prepare_shell_environment(tmp_path)
            assert env.get("XAUTHORITY") == str(xauth)

    def test_wayland_from_env(self, tmp_path):
        with patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-1"}, clear=False):
            env = _prepare_shell_environment(tmp_path)
            assert env["WAYLAND_DISPLAY"] == "wayland-1"

    def test_xdg_runtime_from_env(self, tmp_path):
        with patch.dict(os.environ, {"XDG_RUNTIME_DIR": "/run/user/1234"}, clear=False):
            env = _prepare_shell_environment(tmp_path)
            assert env["XDG_RUNTIME_DIR"] == "/run/user/1234"

    def test_display_default_when_not_in_env(self, tmp_path):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISPLAY", None)
            env = _prepare_shell_environment(tmp_path)
            assert env.get("DISPLAY") == ":0"


class TestRunCmdSyncShellMode:
    def test_shell_mode_with_cwd(self, tmp_path):
        from server.utils import run_cmd_sync

        success, output = run_cmd_sync(["pwd"], cwd=str(tmp_path), use_shell=True)
        assert success is True
        assert str(tmp_path) in output

    def test_shell_mode_basic(self):
        from server.utils import run_cmd_sync

        success, output = run_cmd_sync(["echo", "shell_test"], use_shell=True)
        assert success is True
        assert "shell_test" in output

    def test_shell_mode_with_env(self):
        from server.utils import run_cmd_sync

        success, output = run_cmd_sync(
            ["env"], use_shell=True, env={"SYNC_TEST_VAR": "sync_val"}
        )
        assert success is True


class TestRunCmdFullExtended:
    @pytest.mark.asyncio
    async def test_with_env_vars(self):
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
        from server.utils import run_cmd_full

        success, stdout, stderr = await run_cmd_full(
            ["pwd"], cwd=str(tmp_path), use_shell=True
        )
        assert success is True
        assert str(tmp_path) in stdout

    @pytest.mark.asyncio
    async def test_generic_exception(self):
        from server.utils import run_cmd_full

        with patch("asyncio.to_thread", side_effect=RuntimeError("boom")):
            success, stdout, stderr = await run_cmd_full(
                ["echo", "test"], use_shell=False
            )
            assert success is False
            assert "boom" in stderr


class TestRunCmdWithEnvShellMode:
    @pytest.mark.asyncio
    async def test_env_passed_in_shell_mode(self):
        from server.utils import run_cmd

        success, output = await run_cmd(
            ["env"], use_shell=True, env={"RUN_CMD_TEST": "shell_env_val"}
        )
        assert success is True

    @pytest.mark.asyncio
    async def test_generic_exception(self):
        from server.utils import run_cmd

        with patch("asyncio.to_thread", side_effect=RuntimeError("async boom")):
            success, output = await run_cmd(["echo", "test"], use_shell=False)
            assert success is False
            assert "async boom" in output
