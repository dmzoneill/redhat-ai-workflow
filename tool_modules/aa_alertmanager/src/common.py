"""Shared helpers for Alertmanager tool modules.

Extracted from tools_basic.py and tools_extra.py to eliminate duplication (DUP-004).
"""

from server.http_client import alertmanager_client
from server.utils import (
    get_bearer_token,
    get_env_config,
    get_kubeconfig,
    get_service_url,
)


async def alertmanager_request(
    url: str,
    endpoint: str,
    method: str = "GET",
    data: dict | None = None,
    token: str | None = None,
    timeout: int = 30,
) -> tuple[bool, dict | str]:
    """Make a request to Alertmanager API using shared HTTP client."""
    client = alertmanager_client(url, token, timeout)
    try:
        if method == "GET":
            return await client.get(endpoint)
        elif method == "POST":
            return await client.post(endpoint, json=data)
        elif method == "DELETE":
            return await client.delete(endpoint)
        else:
            return False, f"Unsupported method: {method}"
    finally:
        await client.close()


async def get_alertmanager_config(environment: str) -> tuple[str, str | None]:
    """Get URL and token for Alertmanager environment.

    Uses shared utilities from server for config loading.
    Auto-refreshes auth if credentials are stale.
    """
    url = get_service_url("alertmanager", environment)
    env_config = get_env_config(environment, "alertmanager")
    kubeconfig = env_config.get("kubeconfig", get_kubeconfig(environment))
    token = await get_bearer_token(kubeconfig, environment=environment, auto_auth=True)
    return url, token
