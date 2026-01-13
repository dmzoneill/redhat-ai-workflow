"""Quay.io MCP Server - Container image management tools (extra tools).

Provides additional tools for checking images, tags, and security scans.
Uses skopeo (with podman/docker auth) as primary method, API as fallback.
"""

import json
import logging
import os
from typing import cast

from mcp.server.fastmcp import FastMCP

# Setup project path for server imports (must be before server imports)
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization

from mcp.types import TextContent

from server.auto_heal_decorator import auto_heal
from server.http_client import quay_client
from server.tool_registry import ToolRegistry
from server.utils import load_config, run_cmd

logger = logging.getLogger(__name__)


# ==================== Configuration ====================


def _get_quay_config() -> dict:
    """Get Quay configuration from config.json."""
    config = load_config()
    return cast(dict, config.get("quay", {}))


_quay_cfg = _get_quay_config()
QUAY_API_URL = _quay_cfg.get("api_url") or os.getenv("QUAY_API_URL", "https://quay.io/api/v1")
QUAY_DEFAULT_NAMESPACE = _quay_cfg.get("default_namespace") or os.getenv("QUAY_NAMESPACE", "redhat-user-workloads")
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


# ==================== Tool Registration ====================


def register_tools(server: "FastMCP") -> int:
    """Register tools with the MCP server."""
    registry = ToolRegistry(server)

    # ==================== TOOLS NOT USED IN SKILLS ====================
    @auto_heal()
    @registry.tool()
    async def quay_get_repository(
        repository: str,
        namespace: str = "",
    ) -> list[TextContent]:
        """
        Get information about a Quay.io repository.

        Args:
            repository: Repository name
            namespace: Optional namespace override (default: redhat-user-workloads)

        Returns:
            Repository details including description, visibility, tags count.
        """
        full_path = resolve_quay_repo(repository, namespace)

        # Try skopeo first to list tags (gives us tag count)
        image_ref = get_full_image_ref(full_path)
        success, tags = await skopeo_list_tags(image_ref)

        if success:
            lines = [
                f"## Repository: `{full_path}`",
                "",
                f"**Tags:** {len(tags)}",
                f"**URL:** https://quay.io/repository/{full_path}",
                "",
                "**Recent tags:**",
            ]
            for tag in sorted(tags, reverse=True)[:10]:
                lines.append(f"- `{tag}`")
            return [TextContent(type="text", text="\n".join(lines))]

        # Fallback to API
        success, data = await quay_api_request(f"/repository/{full_path}")
        if not success:
            return [TextContent(type="text", text=f"❌ Failed to get repository: {data}")]

        lines = [
            f"## Repository: `{full_path}`",
            "",
            f"**Description:** {data.get('description', 'N/A')}",
            f"**Visibility:** {'public' if data.get('is_public', False) else 'private'}",
            f"**Tags:** {data.get('tag_count', 'N/A')}",
            f"**URL:** https://quay.io/repository/{full_path}",
        ]
        return [TextContent(type="text", text="\n".join(lines))]

    @auto_heal()
    @registry.tool()
    async def quay_list_tags(
        repository: str,
        namespace: str = "",
        limit: int = 20,
        filter_tag: str = "",
    ) -> list[TextContent]:
        """
        List tags for a Quay.io repository.

        Args:
            repository: Repository name
            namespace: Optional namespace override
            limit: Maximum number of tags to return
            filter_tag: Optional filter string to match tag names

        Returns:
            List of image tags.
        """
        full_path = resolve_quay_repo(repository, namespace)
        image_ref = get_full_image_ref(full_path)

        # Use skopeo list-tags
        success, tags = await skopeo_list_tags(image_ref)

        if not success:
            return [
                TextContent(
                    type="text",
                    text=(
                        "❌ Failed to list tags. Ensure you're logged in:\n"
                        "  `podman login quay.io` or `docker login quay.io`"
                    ),
                )
            ]

        if not tags:
            return [TextContent(type="text", text=f"No tags found for `{full_path}`")]

        # Filter if requested
        if filter_tag:
            tags = [t for t in tags if filter_tag in t]

        # Sort by name (descending to get newest first for commit SHAs)
        tags = sorted(tags, reverse=True)[:limit]

        lines = [
            f"## Tags for `{full_path}`",
            "",
            f"Found {len(tags)} tags" + (f" matching '{filter_tag}'" if filter_tag else "") + ":",
            "",
        ]

        for tag in tags:
            lines.append(f"- `{tag}`")

        return [TextContent(type="text", text="\n".join(lines))]
