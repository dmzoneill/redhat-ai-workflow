"""Shared HTTP client for API requests.

Provides a consistent interface for making authenticated HTTP requests
to services like Prometheus, Alertmanager, Kibana, and Quay.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

Method = Literal["GET", "POST", "DELETE", "PUT", "PATCH"]


@dataclass
class APIClient:
    """Reusable async HTTP client with bearer token auth and error handling.

    Usage:
        client = APIClient(base_url="https://prometheus.example.com", bearer_token=token)
        success, result = await client.get("/api/v1/query", params={"query": "up"})

        # Or with context manager for proper cleanup
        async with APIClient(base_url=url, bearer_token=token) as client:
            success, result = await client.get("/api/v1/query")
    """

    base_url: str = ""
    bearer_token: str | None = None
    timeout: float = 30.0
    follow_redirects: bool = True
    verify_ssl: bool = True
    extra_headers: dict[str, str] = field(default_factory=dict)

    # Auth error message templates
    auth_error_msg: str = "Authentication required. Refresh your cluster credentials."
    not_found_msg: str = "Not found"

    # Internal client (created lazily)
    _client: httpx.AsyncClient | None = field(default=None, repr=False)

    def _build_headers(self) -> dict[str, str]:
        """Build request headers including auth."""
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        headers.update(self.extra_headers)
        return headers

    def _build_url(self, endpoint: str) -> str:
        """Build full URL from base and endpoint."""
        base = self.base_url.rstrip("/")
        if not endpoint.startswith("/"):
            endpoint = f"/{endpoint}"
        return f"{base}{endpoint}"

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=self.follow_redirects,
                verify=self.verify_ssl,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "APIClient":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()

    def _handle_response(self, response: httpx.Response) -> tuple[bool, dict | str]:
        """Handle HTTP response with standard error handling."""
        if response.status_code == 401:
            return False, self.auth_error_msg
        if response.status_code == 404:
            return False, self.not_found_msg
        if response.status_code >= 400:
            return False, f"HTTP {response.status_code}: {response.text[:500]}"

        # Try to parse JSON
        try:
            return True, response.json()
        except (ValueError, TypeError):
            return True, response.text

    async def request(
        self,
        method: Method,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[bool, dict | str]:
        """Make an HTTP request.

        Args:
            method: HTTP method (GET, POST, DELETE, etc.)
            endpoint: API endpoint (appended to base_url)
            params: Query parameters
            json: JSON body for POST/PUT/PATCH
            headers: Additional headers (merged with defaults)

        Returns:
            Tuple of (success, response_data_or_error_message)
        """
        url = self._build_url(endpoint)
        request_headers = self._build_headers()
        if headers:
            request_headers.update(headers)

        try:
            client = await self._get_client()
            response = await client.request(
                method,
                url,
                headers=request_headers,
                params=params,
                json=json,
            )
            return self._handle_response(response)
        except httpx.TimeoutException:
            return False, f"Request timed out after {self.timeout}s"
        except httpx.ConnectError as e:
            return False, f"Connection error: {e}"
        except httpx.HTTPStatusError as e:
            return False, f"HTTP error {e.response.status_code}: {e}"
        except httpx.RequestError as e:
            return False, f"Request error: {e}"

    async def get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[bool, dict | str]:
        """Make a GET request."""
        return await self.request("GET", endpoint, params=params, headers=headers)

    async def post(
        self,
        endpoint: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[bool, dict | str]:
        """Make a POST request."""
        return await self.request(
            "POST", endpoint, params=params, json=json, headers=headers
        )

    async def delete(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[bool, dict | str]:
        """Make a DELETE request."""
        return await self.request("DELETE", endpoint, params=params, headers=headers)

    async def put(
        self,
        endpoint: str,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[bool, dict | str]:
        """Make a PUT request."""
        return await self.request("PUT", endpoint, json=json, headers=headers)


# Convenience factory functions for common services


def prometheus_client(
    url: str, token: str | None = None, timeout: float = 30.0
) -> APIClient:
    """Create an API client configured for Prometheus.

    Args:
        url: Prometheus base URL
        token: Bearer token for authentication
        timeout: Request timeout in seconds
    """
    return APIClient(
        base_url=url,
        bearer_token=token,
        timeout=timeout,
        auth_error_msg="Authentication required. Run: kube s (or kube p) to authenticate.",
    )


def alertmanager_client(
    url: str, token: str | None = None, timeout: float = 30.0
) -> APIClient:
    """Create an API client configured for Alertmanager.

    The Alertmanager API uses /api/v2 prefix.

    Args:
        url: Alertmanager base URL
        token: Bearer token for authentication
        timeout: Request timeout in seconds
    """
    # Alertmanager uses /api/v2 prefix
    base_url = f"{url.rstrip('/')}/api/v2"
    return APIClient(
        base_url=base_url,
        bearer_token=token,
        timeout=timeout,
        auth_error_msg="Authentication required. Refresh cluster credentials.",
    )


def kibana_client(
    url: str, token: str | None = None, timeout: float = 30.0
) -> APIClient:
    """Create an API client configured for Kibana.

    Kibana requires the kbn-xsrf header for non-GET requests.

    Args:
        url: Kibana base URL
        token: Bearer token for authentication
        timeout: Request timeout in seconds
    """
    return APIClient(
        base_url=url,
        bearer_token=token,
        timeout=timeout,
        extra_headers={"kbn-xsrf": "true"},
        auth_error_msg="Unauthorized - run 'kube s' or 'kube p' to authenticate",
    )


def grafana_client(
    url: str, token: str | None = None, timeout: float = 30.0
) -> APIClient:
    """Create an API client configured for Grafana.

    Args:
        url: Grafana base URL
        token: Bearer token for authentication
        timeout: Request timeout in seconds
    """
    return APIClient(
        base_url=url,
        bearer_token=token,
        timeout=timeout,
        auth_error_msg="Authentication required. Run: kube s (or kube p) to authenticate.",
    )


def quay_client(token: str | None = None, timeout: float = 30.0) -> APIClient:
    """Create an API client configured for Quay.io.

    Args:
        token: Bearer token for authentication (optional for public repos)
        timeout: Request timeout in seconds
    """
    return APIClient(
        base_url="https://quay.io/api/v1",
        bearer_token=token,
        timeout=timeout,
    )
