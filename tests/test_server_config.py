"""Tests for server.config module."""

from unittest.mock import MagicMock, patch

from server.config import get_token_from_kubeconfig


class TestGetTokenFromKubeconfig:
    """Tests for get_token_from_kubeconfig function."""

    @patch("server.config.Path.exists", return_value=True)
    @patch("subprocess.run")
    def test_get_token_from_oc_whoami(self, mock_run, mock_exists):
        """Test getting token from oc whoami -t."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="sha256~test_token_12345", stderr=""
        )

        token = get_token_from_kubeconfig("~/.kube/config.s")

        assert token == "sha256~test_token_12345"
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "oc" in call_args
        assert "whoami" in call_args
        assert "-t" in call_args

    @patch("server.config.Path.exists", return_value=True)
    @patch("subprocess.run")
    def test_get_token_fallback_to_kubectl_config(self, mock_run, mock_exists):
        """Test fallback to kubectl config view when oc fails."""
        # First call (oc whoami) fails, second call (kubectl config view --minify) succeeds
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout="", stderr="oc: command not found"),
            MagicMock(
                returncode=0,
                stdout="kubectl_token_67890",
                stderr="",
            ),
        ]

        token = get_token_from_kubeconfig("~/.kube/config.s")

        assert token == "kubectl_token_67890"
        assert mock_run.call_count == 2

    @patch("server.config.Path.exists", return_value=True)
    @patch("subprocess.run")
    def test_get_token_returns_empty_on_failure(self, mock_run, mock_exists):
        """Test returns empty string when all methods fail."""
        # All three calls fail (oc whoami, kubectl --minify, kubectl --raw --minify)
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout="", stderr="oc: command not found"),
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
        ]

        token = get_token_from_kubeconfig("~/.kube/config.s")

        assert token == ""

    @patch("server.config.Path.exists", return_value=True)
    @patch("subprocess.run")
    def test_get_token_handles_exception(self, mock_run, mock_exists):
        """Test handles exception gracefully."""
        mock_run.side_effect = Exception("Unexpected error")

        token = get_token_from_kubeconfig("~/.kube/config.s")

        assert token == ""

    def test_get_token_returns_empty_for_nonexistent_file(self):
        """Test returns empty when kubeconfig file doesn't exist."""
        token = get_token_from_kubeconfig("/nonexistent/path/config")

        assert token == ""
