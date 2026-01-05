"""Tests for server.http_client module."""

from server.http_client import APIClient, alertmanager_client, kibana_client, prometheus_client, quay_client


class TestAPIClient:
    """Tests for APIClient class."""

    def test_build_url_with_base(self):
        """Test URL building with base URL."""
        client = APIClient(base_url="https://api.example.com")
        assert client._build_url("/v1/query") == "https://api.example.com/v1/query"

    def test_build_url_strips_trailing_slash(self):
        """Test URL building strips trailing slash from base."""
        client = APIClient(base_url="https://api.example.com/")
        assert client._build_url("/v1/query") == "https://api.example.com/v1/query"

    def test_build_url_adds_leading_slash(self):
        """Test URL building adds leading slash if missing."""
        client = APIClient(base_url="https://api.example.com")
        assert client._build_url("v1/query") == "https://api.example.com/v1/query"

    def test_build_headers_without_token(self):
        """Test header building without bearer token."""
        client = APIClient()
        headers = client._build_headers()
        assert "Authorization" not in headers
        assert headers["Accept"] == "application/json"
        assert headers["Content-Type"] == "application/json"

    def test_build_headers_with_token(self):
        """Test header building with bearer token."""
        client = APIClient(bearer_token="test-token")
        headers = client._build_headers()
        assert headers["Authorization"] == "Bearer test-token"

    def test_build_headers_with_extra_headers(self):
        """Test header building with extra headers."""
        client = APIClient(extra_headers={"X-Custom": "value"})
        headers = client._build_headers()
        assert headers["X-Custom"] == "value"


class TestFactoryFunctions:
    """Tests for factory functions."""

    def test_prometheus_client_creates_client(self):
        """Test prometheus_client factory."""
        client = prometheus_client("https://prometheus.example.com", "token123")
        assert client.base_url == "https://prometheus.example.com"
        assert client.bearer_token == "token123"
        assert "kube s" in client.auth_error_msg

    def test_alertmanager_client_adds_api_prefix(self):
        """Test alertmanager_client factory adds /api/v2."""
        client = alertmanager_client("https://alertmanager.example.com", "token123")
        assert client.base_url == "https://alertmanager.example.com/api/v2"

    def test_kibana_client_has_xsrf_header(self):
        """Test kibana_client factory adds kbn-xsrf header."""
        client = kibana_client("https://kibana.example.com", "token123")
        assert client.extra_headers.get("kbn-xsrf") == "true"

    def test_quay_client_uses_quay_base_url(self):
        """Test quay_client factory uses Quay.io API."""
        client = quay_client()
        assert "quay.io" in client.base_url

    def test_quay_client_optional_token(self):
        """Test quay_client works without token."""
        client = quay_client()
        assert client.bearer_token is None

        client_with_token = quay_client("my-token")
        assert client_with_token.bearer_token == "my-token"
