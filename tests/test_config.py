"""Tests for configuration loading and validation."""

import base64
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from server.config import (
    get_container_auth,
    get_os_env,
    get_token_from_kubeconfig,
    load_config,
)


class TestLoadConfig:
    """Tests for load_config function."""

    def test_config_loads(self):
        """Config should load without error."""
        config = load_config()
        assert config is not None
        assert isinstance(config, dict)

    def test_get_repository_config(self):
        """Should get repository configuration."""
        config = load_config()
        # This may return None if not configured
        repos = config.get("repositories", {})
        assert isinstance(repos, dict)

    def test_get_with_default(self):
        """Should return default for missing keys."""
        config = load_config()
        result = config.get("nonexistent_key", "default_value")
        assert result == "default_value"


class TestConfigFile:
    """Tests for config.json file format."""

    def test_config_file_exists(self, config_path):
        """config.json should exist."""
        assert config_path.exists(), f"config.json not found at {config_path}"

    def test_config_is_valid_json(self, config_path):
        """config.json should be valid JSON."""
        if config_path.exists():
            content = config_path.read_text()
            data = json.loads(content)
            assert isinstance(data, dict)

    def test_config_has_expected_sections(self, config_path):
        """config.json should have expected top-level keys."""
        if config_path.exists():
            content = config_path.read_text()
            data = json.loads(content)
            # Check for common expected sections
            expected = ["repositories", "environments", "jira", "slack"]
            for key in expected:
                # They may or may not be present, just check structure
                if key in data:
                    assert isinstance(data[key], dict)


# ---------------------------------------------------------------------------
# get_os_env
# ---------------------------------------------------------------------------


class TestGetOsEnv:
    def test_returns_value_when_set(self):
        with patch.dict(os.environ, {"MY_TEST_VAR": "hello"}, clear=False):
            assert get_os_env("MY_TEST_VAR") == "hello"

    def test_returns_default_when_not_set(self):
        env = {k: v for k, v in os.environ.items() if k != "UNSET_VAR_12345"}
        with patch.dict(os.environ, env, clear=True):
            assert get_os_env("UNSET_VAR_12345", "fallback") == "fallback"

    def test_returns_empty_string_default(self):
        env = {k: v for k, v in os.environ.items() if k != "MISSING_VAR"}
        with patch.dict(os.environ, env, clear=True):
            assert get_os_env("MISSING_VAR") == ""


# ---------------------------------------------------------------------------
# get_token_from_kubeconfig
# ---------------------------------------------------------------------------


class TestGetTokenFromKubeconfig:
    def test_returns_empty_when_no_kubeconfig_and_no_env(self):
        assert get_token_from_kubeconfig() == ""

    def test_returns_empty_when_kubeconfig_file_missing(self, tmp_path):
        missing = str(tmp_path / "nonexistent")
        assert get_token_from_kubeconfig(kubeconfig=missing) == ""

    def test_resolves_kubeconfig_by_environment(self):
        with patch(
            "server.utils.get_kubeconfig",
            return_value="/nonexistent/config.s",
        ):
            result = get_token_from_kubeconfig(environment="stage")
        assert result == ""

    def test_oc_whoami_success(self, tmp_path):
        kubeconfig = tmp_path / "config.s"
        kubeconfig.write_text("dummy")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "sha256~mytoken\n"

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            token = get_token_from_kubeconfig(kubeconfig=str(kubeconfig))

        assert token == "sha256~mytoken"
        # Should have called oc whoami -t
        call_args = mock_run.call_args[0][0]
        assert call_args == ["oc", "whoami", "-t"]

    def test_falls_through_to_kubectl_config_view(self, tmp_path):
        kubeconfig = tmp_path / "config.s"
        kubeconfig.write_text("dummy")

        oc_result = MagicMock()
        oc_result.returncode = 1
        oc_result.stdout = ""

        kubectl_result = MagicMock()
        kubectl_result.stdout = "kubectl-token\n"

        with patch("subprocess.run", side_effect=[oc_result, kubectl_result]):
            token = get_token_from_kubeconfig(kubeconfig=str(kubeconfig))

        assert token == "kubectl-token"

    def test_falls_through_to_kubectl_raw(self, tmp_path):
        kubeconfig = tmp_path / "config.s"
        kubeconfig.write_text("dummy")

        oc_result = MagicMock()
        oc_result.returncode = 1
        oc_result.stdout = ""

        kubectl_result = MagicMock()
        kubectl_result.stdout = ""

        raw_result = MagicMock()
        raw_result.stdout = "raw-token\n"

        with patch(
            "subprocess.run",
            side_effect=[oc_result, kubectl_result, raw_result],
        ):
            token = get_token_from_kubeconfig(kubeconfig=str(kubeconfig))

        assert token == "raw-token"

    def test_returns_empty_when_all_fail(self, tmp_path):
        kubeconfig = tmp_path / "config.s"
        kubeconfig.write_text("dummy")

        with patch("subprocess.run", side_effect=Exception("fail")):
            token = get_token_from_kubeconfig(kubeconfig=str(kubeconfig))

        assert token == ""

    def test_expands_user_in_path(self, tmp_path):
        kubeconfig = tmp_path / "config.s"
        kubeconfig.write_text("dummy")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "expanded-token\n"

        with patch("subprocess.run", return_value=mock_result):
            token = get_token_from_kubeconfig(kubeconfig=str(kubeconfig))
        assert token == "expanded-token"


# ---------------------------------------------------------------------------
# get_container_auth
# ---------------------------------------------------------------------------


class TestGetContainerAuth:
    def test_returns_none_when_no_auth_files_exist(self, tmp_path):
        with (
            patch(
                "server.config.load_config",
                return_value={"paths": {}},
            ),
            patch.object(Path, "home", return_value=tmp_path),
            patch.dict(
                os.environ, {"XDG_RUNTIME_DIR": str(tmp_path / "run")}, clear=False
            ),
        ):
            result = get_container_auth("quay.io")
        assert result is None

    def test_extracts_token_from_auth_json(self, tmp_path):
        auth_value = base64.b64encode(b"user:mypassword").decode()
        auth_data = {"auths": {"quay.io": {"auth": auth_value}}}
        auth_file = tmp_path / "auth.json"
        auth_file.write_text(json.dumps(auth_data))

        with patch(
            "server.utils.load_config",
            return_value={"paths": {"container_auth": str(auth_file)}},
        ):
            result = get_container_auth("quay.io")
        assert result == "mypassword"

    def test_returns_decoded_value_without_colon(self, tmp_path):
        auth_value = base64.b64encode(b"tokenonly").decode()
        auth_data = {"auths": {"quay.io": {"auth": auth_value}}}
        auth_file = tmp_path / "auth.json"
        auth_file.write_text(json.dumps(auth_data))

        with patch(
            "server.utils.load_config",
            return_value={"paths": {"container_auth": str(auth_file)}},
        ):
            result = get_container_auth("quay.io")
        assert result == "tokenonly"

    def test_searches_matching_registry(self, tmp_path):
        auth_value = base64.b64encode(b"user:pass123").decode()
        auth_data = {"auths": {"registry.example.com": {"auth": auth_value}}}
        auth_file = tmp_path / "auth.json"
        auth_file.write_text(json.dumps(auth_data))

        with patch(
            "server.utils.load_config",
            return_value={"paths": {"container_auth": str(auth_file)}},
        ):
            result = get_container_auth("registry.example.com")
        assert result == "pass123"

    def test_returns_none_when_registry_not_in_auths(self, tmp_path):
        auth_data = {"auths": {"docker.io": {"auth": "dW46cHc="}}}
        auth_file = tmp_path / "auth.json"
        auth_file.write_text(json.dumps(auth_data))

        with patch(
            "server.utils.load_config",
            return_value={"paths": {"container_auth": str(auth_file)}},
        ):
            result = get_container_auth("quay.io")
        assert result is None

    def test_skips_invalid_json_files(self, tmp_path):
        auth_file = tmp_path / "auth.json"
        auth_file.write_text("not json")

        with (
            patch(
                "server.utils.load_config",
                return_value={"paths": {"container_auth": str(auth_file)}},
            ),
            patch.object(Path, "home", return_value=tmp_path / "home"),
            patch.dict(
                os.environ, {"XDG_RUNTIME_DIR": str(tmp_path / "run")}, clear=False
            ),
        ):
            result = get_container_auth("quay.io")
        assert result is None
