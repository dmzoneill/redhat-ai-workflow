"""Tests for server.cli_runner module."""

from server.cli_runner import (
    CLIRunner,
    bonfire_runner,
    git_runner,
    glab_runner,
    kubectl_runner,
    rh_issue_runner,
    skopeo_runner,
)


class TestCLIRunner:
    """Tests for CLIRunner class."""

    def test_default_timeout(self):
        """Test default timeout is 60 seconds."""
        runner = CLIRunner("test")
        assert runner.timeout == 60

    def test_custom_timeout(self):
        """Test custom timeout."""
        runner = CLIRunner("test", timeout=120)
        assert runner.timeout == 120

    def test_build_env_merges_vars(self):
        """Test environment variable merging."""
        runner = CLIRunner("test", env_vars={"VAR1": "value1"})
        env = runner._build_env({"VAR2": "value2"})
        assert env["VAR1"] == "value1"
        assert env["VAR2"] == "value2"

    def test_build_env_extra_overrides(self):
        """Test extra env vars override defaults."""
        runner = CLIRunner("test", env_vars={"VAR1": "original"})
        env = runner._build_env({"VAR1": "override"})
        assert env["VAR1"] == "override"

    def test_detect_error_type_auth(self):
        """Test auth error detection."""
        runner = CLIRunner("test")
        assert runner._detect_error_type("Error: Unauthorized") == "auth"
        assert runner._detect_error_type("401 Forbidden") == "auth"
        assert runner._detect_error_type("token expired") == "auth"

    def test_detect_error_type_network(self):
        """Test network error detection."""
        runner = CLIRunner("test")
        assert runner._detect_error_type("No route to host") == "network"
        assert runner._detect_error_type("Connection refused") == "network"

    def test_detect_error_type_none(self):
        """Test no error type for other errors."""
        runner = CLIRunner("test")
        assert runner._detect_error_type("Some other error") is None

    def test_custom_auth_patterns(self):
        """Test custom auth error patterns."""
        runner = CLIRunner("test", auth_error_patterns=["CUSTOM_AUTH_ERROR"])
        assert runner._detect_error_type("CUSTOM_AUTH_ERROR detected") == "auth"


class TestFactoryFunctions:
    """Tests for factory functions."""

    def test_git_runner(self):
        """Test git_runner factory."""
        runner = git_runner(cwd="/tmp", timeout=30)
        assert runner.command == "git"
        assert runner.cwd == "/tmp"
        assert runner.timeout == 30

    def test_glab_runner_has_gitlab_host(self):
        """Test glab_runner sets GITLAB_HOST."""
        runner = glab_runner(gitlab_host="gitlab.example.com")
        assert runner.command == "glab"
        assert runner.env_vars["GITLAB_HOST"] == "gitlab.example.com"

    def test_bonfire_runner_has_kubeconfig(self):
        """Test bonfire_runner sets KUBECONFIG."""
        runner = bonfire_runner(kubeconfig="/path/to/config")
        assert runner.command == "bonfire"
        assert runner.env_vars["KUBECONFIG"] == "/path/to/config"
        assert runner.timeout == 300  # Default for bonfire

    def test_kubectl_runner_has_kubeconfig(self):
        """Test kubectl_runner sets KUBECONFIG."""
        runner = kubectl_runner(kubeconfig="/path/to/config")
        assert runner.command == "kubectl"
        assert runner.env_vars["KUBECONFIG"] == "/path/to/config"

    def test_skopeo_runner(self):
        """Test skopeo_runner factory."""
        runner = skopeo_runner(timeout=60)
        assert runner.command == "skopeo"
        assert runner.timeout == 60

    def test_rh_issue_runner_uses_shell(self):
        """Test rh_issue_runner uses shell mode."""
        runner = rh_issue_runner()
        assert runner.command == "rh-issue"
        assert runner.shell_mode is True
        assert "JIRA_JPAT" in runner.auth_error_patterns
