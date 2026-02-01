"""Quay.io MCP Server - Container image management tools.

Provides 8 tools for checking images, tags, and security scans.
Uses skopeo (with podman/docker auth) as primary method, API as fallback.
"""

import json
import logging
import os
from typing import cast

from fastmcp import FastMCP

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


async def _quay_check_image_exists_impl(
    repository: str,
    tag_or_digest: str,
    namespace: str = "",
) -> list[TextContent]:
    """Implementation of quay_check_image_exists tool."""
    full_path = resolve_quay_repo(repository, namespace)
    image_ref = get_full_image_ref(full_path, tag_or_digest)

    success, data = await skopeo_inspect(image_ref)

    if not success:
        if "manifest unknown" in str(data).lower() or "not found" in str(data).lower():
            return [
                TextContent(
                    type="text",
                    text=f"""❌ Image NOT found: `{tag_or_digest}`

**Repository:** `{full_path}`

The Konflux build may still be in progress, or the tag doesn't exist.

**Check with:** `podman login quay.io` (or `docker login quay.io`) then retry.""",
                )
            ]
        return [TextContent(type="text", text=f"❌ Error checking image: {data}")]

    digest = data.get("Digest", "N/A")
    digest_hash = digest.replace("sha256:", "") if digest.startswith("sha256:") else digest

    lines = [
        "## ✅ Image Exists",
        "",
        f"**Repository:** `{full_path}`",
        f"**Tag/Digest:** `{tag_or_digest}`",
        f"**Full Digest:** `{digest}`",
        "",
        "Image is ready for deployment!",
        "",
        "**For bonfire:**",
        "```",
        f"IMAGE_TAG={digest_hash}",
        "```",
    ]

    return [TextContent(type="text", text="\n".join(lines))]


async def _quay_get_manifest_impl(
    repository: str,
    tag_or_digest: str,
    namespace: str = "",
) -> list[TextContent]:
    """Implementation of quay_get_manifest tool."""
    full_path = resolve_quay_repo(repository, namespace)
    image_ref = get_full_image_ref(full_path, tag_or_digest)

    # Get raw manifest
    success, data = await skopeo_inspect(image_ref, raw=True)

    if not success:
        return [TextContent(type="text", text=f"❌ Failed to get manifest: {data}")]

    if isinstance(data, dict):
        media_type = data.get("mediaType", "N/A")
        schema_version = data.get("schemaVersion", "N/A")
        layers = data.get("layers", [])

        lines = [
            f"## Manifest: `{tag_or_digest}`",
            "",
            f"**Repository:** `{full_path}`",
            f"**Media Type:** {media_type}",
            f"**Schema Version:** {schema_version}",
            f"**Layers:** {len(layers)}",
        ]
    else:
        lines = [
            f"## Manifest: `{tag_or_digest}`",
            "",
            f"**Repository:** `{full_path}`",
            "",
            "```json",
            str(data)[:1000],
            "```",
        ]

    return [TextContent(type="text", text="\n".join(lines))]


async def _quay_get_tag_impl(
    repository: str,
    tag: str,
    namespace: str = "",
) -> list[TextContent]:
    """Implementation of quay_get_tag tool."""
    full_path = resolve_quay_repo(repository, namespace)
    image_ref = get_full_image_ref(full_path, tag)

    # Use skopeo inspect to get digest
    success, data = await skopeo_inspect(image_ref)

    if not success:
        if "manifest unknown" in str(data).lower():
            return [TextContent(type="text", text=f"❌ Tag `{tag}` not found in `{full_path}`")]
        return [
            TextContent(
                type="text",
                text=(
                    f"❌ Failed to get tag: {data}\n\n"
                    "Ensure you're logged in:\n"
                    "  `podman login quay.io` or `docker login quay.io`"
                ),
            )
        ]

    digest = data.get("Digest", "N/A")
    created = data.get("Created", "N/A")
    arch = data.get("Architecture", "N/A")
    os_name = data.get("Os", "N/A")

    # Extract just the sha256 hash (without sha256: prefix) for bonfire
    digest_hash = digest.replace("sha256:", "") if digest.startswith("sha256:") else digest

    lines = [
        f"## Tag: `{tag}`",
        "",
        f"**Repository:** `{full_path}`",
        f"**Digest:** `{digest}`",
        f"**Created:** {created}",
        f"**Architecture:** {arch}/{os_name}",
        "",
        "**For bonfire deploy:**",
        "```",
        f"IMAGE_TAG={digest_hash}",
        "```",
        "",
        "**Full Image Reference:**",
        "```",
        f"quay.io/{full_path}@{digest}",
        "```",
    ]

    return [TextContent(type="text", text="\n".join(lines))]


async def _quay_get_vulnerabilities_impl(
    repository: str,
    digest: str,
    namespace: str = "",
) -> list[TextContent]:
    """Implementation of quay_get_vulnerabilities tool."""
    full_path = resolve_quay_repo(repository, namespace)

    if not digest.startswith("sha256:"):
        digest = f"sha256:{digest}"

    success, data = await quay_api_request(f"/repository/{full_path}/manifest/{digest}/security")

    if not success:
        return [
            TextContent(
                type="text",
                text=(
                    f"❌ Failed to get vulnerabilities: {data}\n\n"
                    "Note: Security scans require QUAY_TOKEN environment variable."
                ),
            )
        ]

    status = data.get("status", "unknown")

    if status == "queued":
        return [TextContent(type="text", text="⏳ Security scan is queued, check back later")]
    elif status == "scanning":
        return [TextContent(type="text", text="🔍 Security scan in progress...")]
    elif status == "unsupported":
        return [TextContent(type="text", text="⚠️ Security scanning not supported for this image")]

    vulns = data.get("data", {}).get("Layer", {}).get("Features", [])

    severity_counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
    critical_vulns = []

    for feature in vulns:
        for vuln in feature.get("Vulnerabilities", []):
            severity = vuln.get("Severity", "Unknown")
            if severity in severity_counts:
                severity_counts[severity] += 1

            if severity == "Critical":
                critical_vulns.append(
                    {
                        "name": vuln.get("Name"),
                        "package": feature.get("Name"),
                        "fixed_by": vuln.get("FixedBy", "N/A"),
                    }
                )

    total = sum(severity_counts.values())

    lines = [
        f"## Security Scan: `{digest[:30]}...`",
        "",
        f"**Status:** {status}",
        f"**Total Vulnerabilities:** {total}",
        "",
        "| Severity | Count |",
        "|----------|-------|",
        f"| 🔴 Critical | {severity_counts['Critical']} |",
        f"| 🟠 High | {severity_counts['High']} |",
        f"| 🟡 Medium | {severity_counts['Medium']} |",
        f"| 🟢 Low | {severity_counts['Low']} |",
    ]

    if critical_vulns:
        lines.extend(["", "### 🔴 Critical Vulnerabilities", ""])
        for v in critical_vulns[:5]:
            lines.append(f"- **{v['name']}** in `{v['package']}` (fix: {v['fixed_by']})")

    return [TextContent(type="text", text="\n".join(lines))]


async def _skopeo_get_digest_impl(
    repository: str,
    tag: str,
    namespace: str = "",
) -> list[TextContent]:
    """Implementation of skopeo_get_digest tool - get sha256 digest for bonfire deploy."""
    full_path = resolve_quay_repo(repository, namespace)
    image_ref = get_full_image_ref(full_path, tag)

    success, data = await skopeo_inspect(image_ref)

    if not success:
        if "manifest unknown" in str(data).lower():
            return [
                TextContent(
                    type="text",
                    text=f"""❌ Image NOT found: `{tag}`

**Repository:** `{full_path}`

The Konflux build may still be in progress. Check:
- Konflux pipeline status
- Quay.io repository tags

**Wait for build to complete before deploying.**""",
                )
            ]
        return [TextContent(type="text", text=f"❌ Failed to get digest: {data}")]

    digest = data.get("Digest", "")
    if not digest:
        return [TextContent(type="text", text="❌ No digest found in image metadata")]

    # Extract just the hash (without sha256: prefix) for bonfire
    digest_hash = digest.replace("sha256:", "") if digest.startswith("sha256:") else digest

    return [
        TextContent(
            type="text",
            text=f"""## ✅ Image Digest

**Repository:** `{full_path}`
**Tag:** `{tag}`
**Digest:** `{digest}`

**For bonfire deploy (IMAGE_TAG):**
```
{digest_hash}
```

**Full image reference:**
```
quay.io/{full_path}@{digest}
```""",
        )
    ]


async def _quay_list_aa_tags_impl(
    limit: int = 10,
    filter_tag: str = "",
) -> list[TextContent]:
    """Implementation of quay_list_aa_tags tool."""
    repo = "aap-aa-tenant/aap-aa-main/automation-analytics-backend-main"
    full_path = f"{QUAY_DEFAULT_NAMESPACE}/{repo}"
    image_ref = get_full_image_ref(full_path)

    success, tags = await skopeo_list_tags(image_ref)

    if not success:
        return [
            TextContent(
                type="text",
                text=(
                    "❌ Failed to list AA tags.\n\n"
                    "Ensure you're logged in:\n"
                    "  `podman login quay.io` or `docker login quay.io`"
                ),
            )
        ]

    if not tags:
        return [TextContent(type="text", text="No tags found for AA repository")]

    # Filter if requested
    if filter_tag:
        tags = [t for t in tags if filter_tag in t]

    # Sort descending and limit
    tags = sorted(tags, reverse=True)[:limit]

    lines = [
        "## Automation Analytics Images",
        "",
        f"**Repository:** `{full_path}`",
        "",
    ]

    for tag in tags:
        lines.append(f"- `{tag}`")

    lines.extend(
        [
            "",
            f"[View on Quay.io](https://quay.io/repository/{full_path}?tab=tags)",
        ]
    )

    return [TextContent(type="text", text="\n".join(lines))]


def register_tools(server: "FastMCP") -> int:
    """Register tools with the MCP server."""
    registry = ToolRegistry(server)

    # ==================== TOOLS USED IN SKILLS ====================
    @auto_heal()
    @registry.tool()
    async def quay_check_image_exists(
        repository: str,
        tag_or_digest: str,
        namespace: str = "",
    ) -> list[TextContent]:
        """
        Check if a specific image tag or digest exists (useful before deploying).

        Args:
            repository: Repository name
            tag_or_digest: Image tag (e.g., "abc123") or digest (sha256:...)
            namespace: Optional namespace override

        Returns:
            Whether the image exists, and its full digest if found.
        """
        return await _quay_check_image_exists_impl(repository, tag_or_digest, namespace)

    @auto_heal()
    @registry.tool()
    async def quay_get_manifest(
        repository: str,
        tag_or_digest: str,
        namespace: str = "",
    ) -> list[TextContent]:
        """
        Get manifest details for an image.

        Args:
            repository: Repository name
            tag_or_digest: Image tag or digest
            namespace: Optional namespace override

        Returns:
            Manifest details including layers and config.
        """
        return await _quay_get_manifest_impl(repository, tag_or_digest, namespace)

    @auto_heal()
    @registry.tool()
    async def quay_get_tag(
        repository: str,
        tag: str,
        namespace: str = "",
    ) -> list[TextContent]:
        """
        Get details for a specific image tag including its sha256 digest.

        Args:
            repository: Repository name
            tag: Tag name (e.g., "latest", "abc123def")
            namespace: Optional namespace override

        Returns:
            Tag details including full sha256 digest for deployment.
        """
        return await _quay_get_tag_impl(repository, tag, namespace)

    @auto_heal()
    @registry.tool()
    async def quay_get_vulnerabilities(
        repository: str,
        digest: str,
        namespace: str = "",
    ) -> list[TextContent]:
        """
        Get security vulnerabilities for an image.

        Note: This requires API access as skopeo doesn't provide vuln data.

        Args:
            repository: Repository name
            digest: Image digest to scan
            namespace: Optional namespace override

        Returns:
            Vulnerability scan results.
        """
        return await _quay_get_vulnerabilities_impl(repository, digest, namespace)

    @auto_heal()
    @registry.tool()
    async def quay_list_aa_tags(
        limit: int = 10,
        filter_tag: str = "",
    ) -> list[TextContent]:
        """
        List recent tags for Automation Analytics image.

        Args:
            limit: Max tags to show
            filter_tag: Optional filter (e.g., commit SHA prefix)

        Returns:
            Recent AA image tags.
        """
        return await _quay_list_aa_tags_impl(limit, filter_tag)

    @auto_heal()
    @registry.tool()
    async def skopeo_get_digest(
        repository: str,
        tag: str,
        namespace: str = "",
    ) -> list[TextContent]:
        """
        Get sha256 digest for an image tag using skopeo.

        Use this to get the IMAGE_TAG value needed for bonfire deploy.
        Returns the 64-char sha256 hash (without 'sha256:' prefix).

        Args:
            repository: Repository path (e.g., "aap-aa-tenant/aap-aa-main/automation-analytics-backend-main")
            tag: Image tag (typically a 40-char git commit SHA)
            namespace: Optional namespace override (default: redhat-user-workloads)

        Returns:
            The sha256 digest for bonfire IMAGE_TAG parameter.
        """
        return await _skopeo_get_digest_impl(repository, tag, namespace)

    return registry.count
