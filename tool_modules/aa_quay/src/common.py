"""Shared helpers for Quay.io tool modules.

Extracted from tools_basic.py and tools_extra.py to eliminate duplication (DUP-004).
"""

import json
import logging
import os
from typing import cast

from server.http_client import quay_client
from server.utils import load_config, run_cmd

logger = logging.getLogger(__name__)


# ==================== Configuration ====================


def _get_quay_config() -> dict:
    """Get Quay configuration from config.json."""
    config = load_config()
    return cast(dict, config.get("quay", {}))


_quay_cfg = _get_quay_config()
QUAY_API_URL = _quay_cfg.get("api_url") or os.getenv(
    "QUAY_API_URL", "https://quay.io/api/v1"
)
QUAY_DEFAULT_NAMESPACE = _quay_cfg.get("default_namespace") or os.getenv(
    "QUAY_NAMESPACE", "redhat-user-workloads"
)
QUAY_REGISTRY = "quay.io"


# ==================== Skopeo Helpers ====================


async def run_skopeo(args: list[str], timeout: int = 30) -> tuple[bool, str]:
    """Run skopeo command and return (success, output)."""
    cmd = ["skopeo"] + args
    logger.info(f"Running: {' '.join(cmd)}")

    # Use unified run_cmd
    return await run_cmd(cmd, timeout=timeout)


async def skopeo_inspect(
    image_ref: str,
    raw: bool = False,
) -> tuple[bool, dict | str]:
    """Inspect an image using skopeo.

    Uses podman/docker login credentials automatically.
    """
    args = ["inspect"]
    if raw:
        args.append("--raw")
    args.append(f"docker://{image_ref}")

    success, output = await run_skopeo(args)

    if not success:
        return False, output

    try:
        return True, json.loads(output)
    except json.JSONDecodeError:
        return True, output


async def skopeo_list_tags(repository: str) -> tuple[bool, list[str]]:
    """List all tags for a repository using skopeo."""
    args = ["list-tags", f"docker://{repository}"]

    success, output = await run_skopeo(args, timeout=60)

    if not success:
        return False, []

    try:
        data = json.loads(output)
        return True, data.get("Tags", [])
    except json.JSONDecodeError:
        return False, []


# ==================== API Fallback ====================


async def quay_api_request(
    endpoint: str,
    method: str = "GET",
    params: dict | None = None,
) -> tuple[bool, dict | str]:
    """Make a request to Quay.io API using shared HTTP client."""
    token = os.getenv("QUAY_TOKEN", "")
    client = quay_client(token if token else None)
    try:
        return await client.request(method, endpoint, params=params)
    finally:
        await client.close()


# ==================== Utilities ====================


def resolve_quay_repo(repository: str, namespace: str = "") -> str:
    """Resolve full repository path."""
    ns = namespace or QUAY_DEFAULT_NAMESPACE
    # If repository already has path components (contains /), use as-is
    if "/" in repository:
        return repository
    # Otherwise, prefix with namespace
    return f"{ns}/{repository}"


def get_full_image_ref(repository: str, tag_or_digest: str = "") -> str:
    """Get full image reference for skopeo."""
    if tag_or_digest:
        if tag_or_digest.startswith("sha256:"):
            return f"{QUAY_REGISTRY}/{repository}@{tag_or_digest}"
        else:
            return f"{QUAY_REGISTRY}/{repository}:{tag_or_digest}"
    return f"{QUAY_REGISTRY}/{repository}"
