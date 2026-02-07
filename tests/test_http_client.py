"""Tests for server.http_client module."""

from unittest.mock import AsyncMock

import httpx

from server.http_client import (
    APIClient,
    alertmanager_client,
    grafana_client,
    kibana_client,
    prometheus_client,
    quay_client,
)


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

    def test_grafana_client_creates_client(self):
        """Test grafana_client factory."""
        client = grafana_client("https://grafana.example.com", "tok", timeout=60.0)
        assert client.base_url == "https://grafana.example.com"
        assert client.bearer_token == "tok"
        assert client.timeout == 60.0
        assert "kube" in client.auth_error_msg

    def test_prometheus_client_custom_timeout(self):
        """Test prometheus_client with custom timeout."""
        client = prometheus_client("https://prom.example.com", timeout=120.0)
        assert client.timeout == 120.0

    def test_alertmanager_client_strips_trailing_slash(self):
        """Test alertmanager_client strips trailing slash before appending /api/v2."""
        client = alertmanager_client("https://am.example.com/")
        assert client.base_url == "https://am.example.com/api/v2"


# ---------------------------------------------------------------------------
# Tests for _handle_response
# ---------------------------------------------------------------------------


class TestHandleResponse:
    """Tests for APIClient._handle_response."""

    def test_401_returns_auth_error(self):
        """401 status returns (False, auth_error_msg)."""
        client = APIClient(auth_error_msg="Auth needed")
        response = httpx.Response(401, text="Unauthorized")
        success, msg = client._handle_response(response)
        assert success is False
        assert msg == "Auth needed"

    def test_404_returns_not_found(self):
        """404 status returns (False, not_found_msg)."""
        client = APIClient(not_found_msg="Custom not found")
        response = httpx.Response(404, text="Not Found")
        success, msg = client._handle_response(response)
        assert success is False
        assert msg == "Custom not found"

    def test_500_returns_http_error(self):
        """500 status returns (False, error string)."""
        client = APIClient()
        response = httpx.Response(500, text="Internal Server Error")
        success, msg = client._handle_response(response)
        assert success is False
        assert "HTTP 500" in msg

    def test_400_returns_http_error(self):
        """400 status returns (False, error string)."""
        client = APIClient()
        response = httpx.Response(400, text="Bad Request")
        success, msg = client._handle_response(response)
        assert success is False
        assert "HTTP 400" in msg

    def test_200_json_response(self):
        """200 with JSON body returns (True, parsed dict)."""
        client = APIClient()
        response = httpx.Response(
            200,
            json={"status": "ok", "data": [1, 2, 3]},
        )
        success, data = client._handle_response(response)
        assert success is True
        assert data == {"status": "ok", "data": [1, 2, 3]}

    def test_200_non_json_response(self):
        """200 with non-JSON body returns (True, text)."""
        client = APIClient()
        response = httpx.Response(200, text="plain text response")
        success, data = client._handle_response(response)
        assert success is True
        assert data == "plain text response"

    def test_500_truncates_long_response(self):
        """HTTP error truncates body to 500 chars."""
        client = APIClient()
        long_text = "x" * 1000
        response = httpx.Response(502, text=long_text)
        success, msg = client._handle_response(response)
        assert success is False
        assert len(msg) < 600  # "HTTP 502: " + 500 chars


# ---------------------------------------------------------------------------
# Tests for _get_client and lifecycle
# ---------------------------------------------------------------------------


class TestClientLifecycle:
    """Tests for _get_client, close, context manager."""

    async def test_get_client_creates_instance(self):
        """_get_client creates an httpx.AsyncClient."""
        client = APIClient(timeout=5.0)
        http_client = await client._get_client()
        assert isinstance(http_client, httpx.AsyncClient)
        await client.close()

    async def test_get_client_reuses_instance(self):
        """_get_client returns same instance on repeated calls."""
        client = APIClient()
        c1 = await client._get_client()
        c2 = await client._get_client()
        assert c1 is c2
        await client.close()

    async def test_get_client_recreates_after_close(self):
        """_get_client creates new instance after close."""
        client = APIClient()
        c1 = await client._get_client()
        await client.close()
        c2 = await client._get_client()
        assert c1 is not c2
        await client.close()

    async def test_close_sets_client_none(self):
        """close() sets internal client to None."""
        client = APIClient()
        await client._get_client()
        assert client._client is not None
        await client.close()
        assert client._client is None

    async def test_close_no_client_no_error(self):
        """close() does not raise when no client exists."""
        client = APIClient()
        await client.close()  # should not raise

    async def test_context_manager(self):
        """Async context manager calls close on exit."""
        async with APIClient() as client:
            assert isinstance(client, APIClient)
            _ = await client._get_client()
        # After exit, client should be closed
        assert client._client is None


# ---------------------------------------------------------------------------
# Tests for request method
# ---------------------------------------------------------------------------


class TestRequest:
    """Tests for APIClient.request method."""

    async def test_get_request(self):
        """GET request returns parsed JSON."""
        client = APIClient(base_url="https://api.example.com")
        mock_response = httpx.Response(200, json={"result": "ok"})
        mock_http = AsyncMock()
        mock_http.request = AsyncMock(return_value=mock_response)
        mock_http.is_closed = False

        client._client = mock_http
        success, data = await client.get("/test")
        assert success is True
        assert data == {"result": "ok"}

    async def test_post_request_with_json(self):
        """POST request sends JSON body."""
        client = APIClient(base_url="https://api.example.com")
        mock_response = httpx.Response(201, json={"id": 1})
        mock_http = AsyncMock()
        mock_http.request = AsyncMock(return_value=mock_response)
        mock_http.is_closed = False

        client._client = mock_http
        success, data = await client.post("/items", json={"name": "test"})
        assert success is True
        assert data == {"id": 1}

    async def test_delete_request(self):
        """DELETE request works correctly."""
        client = APIClient(base_url="https://api.example.com")
        mock_response = httpx.Response(200, json={"deleted": True})
        mock_http = AsyncMock()
        mock_http.request = AsyncMock(return_value=mock_response)
        mock_http.is_closed = False

        client._client = mock_http
        success, data = await client.delete("/items/1")
        assert success is True
        assert data == {"deleted": True}

    async def test_put_request(self):
        """PUT request works correctly."""
        client = APIClient(base_url="https://api.example.com")
        mock_response = httpx.Response(200, json={"updated": True})
        mock_http = AsyncMock()
        mock_http.request = AsyncMock(return_value=mock_response)
        mock_http.is_closed = False

        client._client = mock_http
        success, data = await client.put("/items/1", json={"name": "updated"})
        assert success is True
        assert data == {"updated": True}

    async def test_request_with_custom_headers(self):
        """Request merges custom headers."""
        client = APIClient(base_url="https://api.example.com", bearer_token="tok")
        mock_response = httpx.Response(200, json={})
        mock_http = AsyncMock()
        mock_http.request = AsyncMock(return_value=mock_response)
        mock_http.is_closed = False

        client._client = mock_http
        await client.get("/test", headers={"X-Extra": "val"})

        call_kwargs = mock_http.request.call_args
        headers = call_kwargs.kwargs["headers"]
        assert headers["X-Extra"] == "val"
        assert headers["Authorization"] == "Bearer tok"

    async def test_request_with_params(self):
        """Request passes query parameters."""
        client = APIClient(base_url="https://api.example.com")
        mock_response = httpx.Response(200, json={})
        mock_http = AsyncMock()
        mock_http.request = AsyncMock(return_value=mock_response)
        mock_http.is_closed = False

        client._client = mock_http
        await client.get("/search", params={"q": "test"})

        call_kwargs = mock_http.request.call_args
        assert call_kwargs.kwargs["params"] == {"q": "test"}

    async def test_request_timeout_error(self):
        """Timeout error returns (False, message)."""
        client = APIClient(base_url="https://api.example.com", timeout=5.0)
        mock_http = AsyncMock()
        mock_http.request = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        mock_http.is_closed = False

        client._client = mock_http
        success, msg = await client.get("/slow")
        assert success is False
        assert "timed out" in msg.lower()

    async def test_request_connect_error(self):
        """Connection error returns (False, message)."""
        client = APIClient(base_url="https://api.example.com")
        mock_http = AsyncMock()
        mock_http.request = AsyncMock(
            side_effect=httpx.ConnectError("connection refused")
        )
        mock_http.is_closed = False

        client._client = mock_http
        success, msg = await client.get("/down")
        assert success is False
        assert "connection error" in msg.lower()

    async def test_request_http_status_error(self):
        """HTTPStatusError returns (False, message)."""
        client = APIClient(base_url="https://api.example.com")
        mock_response = httpx.Response(503, text="Service Unavailable")
        mock_request = httpx.Request("GET", "https://api.example.com/fail")
        mock_http = AsyncMock()
        mock_http.request = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Server Error", request=mock_request, response=mock_response
            )
        )
        mock_http.is_closed = False

        client._client = mock_http
        success, msg = await client.get("/fail")
        assert success is False
        assert "HTTP error" in msg

    async def test_request_generic_error(self):
        """Generic RequestError returns (False, message)."""
        client = APIClient(base_url="https://api.example.com")
        mock_http = AsyncMock()
        mock_http.request = AsyncMock(side_effect=httpx.RequestError("something broke"))
        mock_http.is_closed = False

        client._client = mock_http
        success, msg = await client.get("/broken")
        assert success is False
        assert "request error" in msg.lower()


# ---------------------------------------------------------------------------
# Tests for APIClient dataclass defaults
# ---------------------------------------------------------------------------


class TestAPIClientDefaults:
    """Tests for default field values of APIClient."""

    def test_default_values(self):
        """APIClient has expected defaults."""
        client = APIClient()
        assert client.base_url == ""
        assert client.bearer_token is None
        assert client.timeout == 30.0
        assert client.follow_redirects is True
        assert client.verify_ssl is True
        assert client.extra_headers == {}
        assert client._client is None

    def test_custom_ssl_and_redirects(self):
        """APIClient accepts custom ssl and redirect settings."""
        client = APIClient(verify_ssl=False, follow_redirects=False)
        assert client.verify_ssl is False
        assert client.follow_redirects is False
