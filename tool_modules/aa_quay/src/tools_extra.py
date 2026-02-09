"""Quay.io MCP Server - Container image management tools (extra tools).

Provides additional tools for checking images, tags, and security scans.
Uses skopeo (with podman/docker auth) as primary method, API as fallback.
"""

import logging

from fastmcp import FastMCP

# Setup project path for server imports (must be before server imports)
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization

from mcp.types import TextContent

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry

from .common import (
    get_full_image_ref,
    quay_api_request,
    resolve_quay_repo,
    skopeo_list_tags,
)

logger = logging.getLogger(__name__)


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
            return [
                TextContent(type="text", text=f"❌ Failed to get repository: {data}")
            ]

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
            f"Found {len(tags)} tags"
            + (f" matching '{filter_tag}'" if filter_tag else "")
            + ":",
            "",
        ]

        for tag in tags:
            lines.append(f"- `{tag}`")

        return [TextContent(type="text", text="\n".join(lines))]
