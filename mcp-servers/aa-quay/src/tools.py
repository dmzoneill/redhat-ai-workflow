"""Quay.io MCP Server - Container image management tools.

Provides 8 tools for checking images, tags, and security scans.
"""

import base64
import json
import logging
import os
from pathlib import Path

import httpx

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

logger = logging.getLogger(__name__)



# ==================== Configuration ====================

QUAY_API_URL = os.getenv("QUAY_API_URL", "https://quay.io/api/v1")
QUAY_DEFAULT_NAMESPACE = os.getenv("QUAY_NAMESPACE", "redhat-user-workloads")


def get_docker_quay_token() -> str:
    """
    Extract Quay.io token from Docker/Podman config files.
    
    Checks in order:
    1. ~/.docker/config.json (Docker)
    2. ~/.config/containers/auth.json (Podman)
    3. $XDG_RUNTIME_DIR/containers/auth.json (Podman runtime)
    """
    auth_files = [
        Path.home() / ".docker" / "config.json",
        Path.home() / ".config" / "containers" / "auth.json",
    ]
    
    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR")
    if xdg_runtime:
        auth_files.append(Path(xdg_runtime) / "containers" / "auth.json")
    
    for auth_file in auth_files:
        if auth_file.exists():
            try:
                with open(auth_file) as f:
                    data = json.load(f)
                
                auths = data.get("auths", {})
                
                for registry, auth_data in auths.items():
                    if "quay.io" in registry.lower():
                        if "auth" in auth_data:
                            decoded = base64.b64decode(auth_data["auth"]).decode()
                            if ":" in decoded:
                                _, token = decoded.split(":", 1)
                                logger.info(f"Loaded Quay.io token from {auth_file}")
                                return token
                            return decoded
            except Exception as e:
                logger.warning(f"Failed to read {auth_file}: {e}")
                continue
    
    return ""


def get_quay_token() -> str:
    """Get Quay token from environment or Docker/Podman config."""
    token = os.getenv("QUAY_TOKEN", "")
    if not token:
        token = get_docker_quay_token()
    return token


async def quay_request(
    endpoint: str,
    method: str = "GET",
    params: dict | None = None,
) -> tuple[bool, dict | str]:
    """Make a request to Quay.io API."""
    url = f"{QUAY_API_URL}{endpoint}"
    
    headers = {"Accept": "application/json"}
    
    token = get_quay_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(method, url, headers=headers, params=params)
            
            if response.status_code == 404:
                return False, "Not found"
            elif response.status_code == 401:
                return False, "Unauthorized - check QUAY_TOKEN"
            elif response.status_code == 403:
                return False, "Forbidden - insufficient permissions"
            elif response.status_code >= 400:
                return False, f"Error {response.status_code}: {response.text}"
            
            return True, response.json()
    except httpx.TimeoutException:
        return False, "Request timed out"
    except Exception as e:
        return False, str(e)


def resolve_repo_path(repository: str, namespace: str = "") -> str:
    """Resolve full repository path."""
    ns = namespace or QUAY_DEFAULT_NAMESPACE
    if "/" in repository and not repository.startswith(ns):
        return repository
    return f"{ns}/{repository}"


# ==================== REPOSITORY INFO ====================

def register_tools(server: "FastMCP") -> int:
    """Register tools with the MCP server."""
    
    @server.tool()
    async def quay_get_repository(
        repository: str,
        namespace: str = "",
    ) -> list[TextContent]:
        """
        Get information about a Quay.io repository.

        Args:
            repository: Repository name (e.g., "your-tenant/aap-aa-main/your-backend-main")
            namespace: Optional namespace override (default: redhat-user-workloads)

        Returns:
            Repository details including description, visibility, tags count.
        """
        full_path = resolve_repo_path(repository, namespace)

        success, data = await quay_request(f"/repository/{full_path}")

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to get repository: {data}")]

        lines = [
            f"## Repository: `{full_path}`",
            "",
            f"**Description:** {data.get('description', 'N/A')}",
            f"**Visibility:** {'public' if data.get('is_public', False) else 'private'}",
            f"**Tags:** {data.get('tag_count', 'N/A')}",
            f"**Created:** {data.get('created_datetime', 'N/A')}",
            "",
            f"**URL:** https://quay.io/repository/{full_path}",
        ]

        return [TextContent(type="text", text="\n".join(lines))]


    @server.tool()
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
            List of image tags with digests and dates.
        """
        full_path = resolve_repo_path(repository, namespace)

        params = {"limit": limit}
        if filter_tag:
            params["filter_tag_name"] = filter_tag

        success, data = await quay_request(f"/repository/{full_path}/tag/", params=params)

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to list tags: {data}")]

        tags = data.get("tags", [])

        if not tags:
            return [TextContent(type="text", text=f"No tags found for `{full_path}`")]

        lines = [
            f"## Tags for `{full_path}`",
            "",
            f"Found {len(tags)} tags:",
            "",
            "| Tag | Digest | Last Modified |",
            "|-----|--------|---------------|",
        ]

        for tag in tags[:limit]:
            name = tag.get("name", "N/A")
            digest = tag.get("manifest_digest", "N/A")[:19] + "..." if tag.get("manifest_digest") else "N/A"
            modified = tag.get("last_modified", "N/A")
            lines.append(f"| `{name}` | `{digest}` | {modified} |")

        return [TextContent(type="text", text="\n".join(lines))]


    @server.tool()
    async def quay_get_tag(
        repository: str,
        tag: str,
        namespace: str = "",
    ) -> list[TextContent]:
        """
        Get details for a specific image tag.

        Args:
            repository: Repository name
            tag: Tag name (e.g., "latest", "sha-abc123", digest)
            namespace: Optional namespace override

        Returns:
            Tag details including full digest, size, layers.
        """
        full_path = resolve_repo_path(repository, namespace)

        success, data = await quay_request(
            f"/repository/{full_path}/tag/",
            params={"specificTag": tag}
        )

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to get tag: {data}")]

        tags = data.get("tags", [])
        matching = [t for t in tags if t.get("name") == tag]

        if not matching:
            matching = [t for t in tags if tag in t.get("manifest_digest", "")]

        if not matching:
            return [TextContent(type="text", text=f"❌ Tag `{tag}` not found in `{full_path}`")]

        tag_info = matching[0]

        lines = [
            f"## Tag: `{tag_info.get('name')}`",
            "",
            f"**Repository:** `{full_path}`",
            f"**Manifest Digest:** `{tag_info.get('manifest_digest', 'N/A')}`",
            f"**Last Modified:** {tag_info.get('last_modified', 'N/A')}",
            f"**Size:** {tag_info.get('size', 'N/A')} bytes",
            "",
            "**Full Image Reference:**",
            "```",
            f"quay.io/{full_path}@{tag_info.get('manifest_digest', 'N/A')}",
            "```",
        ]

        return [TextContent(type="text", text="\n".join(lines))]


    @server.tool()
    async def quay_check_image_exists(
        repository: str,
        digest: str,
        namespace: str = "",
    ) -> list[TextContent]:
        """
        Check if a specific image digest exists (useful before deploying).

        Args:
            repository: Repository name
            digest: Image digest (sha256:...) to check
            namespace: Optional namespace override

        Returns:
            Whether the image exists and is ready for deployment.
        """
        full_path = resolve_repo_path(repository, namespace)

        if not digest.startswith("sha256:"):
            digest = f"sha256:{digest}"

        success, data = await quay_request(f"/repository/{full_path}/manifest/{digest}")

        if not success:
            if "Not found" in str(data):
                return [TextContent(type="text", text=f"❌ Image NOT found: `{digest[:20]}...`\n\nThe build may still be in progress. Check Konflux pipeline status.")]
            return [TextContent(type="text", text=f"❌ Error checking image: {data}")]

        lines = [
            "## ✅ Image Exists",
            "",
            f"**Repository:** `{full_path}`",
            f"**Digest:** `{digest}`",
            "",
            "Image is ready for deployment!",
            "",
            "**Full reference:**",
            "```",
            f"quay.io/{full_path}@{digest}",
            "```",
        ]

        return [TextContent(type="text", text="\n".join(lines))]


    # ==================== SECURITY SCANS ====================

    @server.tool()
    async def quay_get_vulnerabilities(
        repository: str,
        digest: str,
        namespace: str = "",
    ) -> list[TextContent]:
        """
        Get security vulnerabilities for an image.

        Args:
            repository: Repository name
            digest: Image digest to scan
            namespace: Optional namespace override

        Returns:
            Vulnerability scan results.
        """
        full_path = resolve_repo_path(repository, namespace)

        if not digest.startswith("sha256:"):
            digest = f"sha256:{digest}"

        success, data = await quay_request(f"/repository/{full_path}/manifest/{digest}/security")

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to get vulnerabilities: {data}")]

        status = data.get("status", "unknown")

        if status == "queued":
            return [TextContent(type="text", text="⏳ Security scan is queued, check back later")]
        elif status == "scanning":
            return [TextContent(type="text", text="🔍 Security scan in progress...")]
        elif status == "unsupported":
            return [TextContent(type="text", text="⚠️ Security scanning not supported for this image")]

        vulns = data.get("data", {}).get("Layer", {}).get("Features", [])

        severity_counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0, "Unknown": 0}
        critical_vulns = []
        high_vulns = []

        for feature in vulns:
            for vuln in feature.get("Vulnerabilities", []):
                severity = vuln.get("Severity", "Unknown")
                severity_counts[severity] = severity_counts.get(severity, 0) + 1

                if severity == "Critical":
                    critical_vulns.append({
                        "name": vuln.get("Name"),
                        "package": feature.get("Name"),
                        "fixed_by": vuln.get("FixedBy", "N/A"),
                    })
                elif severity == "High":
                    high_vulns.append({
                        "name": vuln.get("Name"),
                        "package": feature.get("Name"),
                    })

        total = sum(severity_counts.values())

        lines = [
            f"## Security Scan: `{digest[:20]}...`",
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
            if len(critical_vulns) > 5:
                lines.append(f"- ... and {len(critical_vulns) - 5} more")

        if high_vulns and len(high_vulns) <= 10:
            lines.extend(["", "### 🟠 High Vulnerabilities", ""])
            for v in high_vulns[:5]:
                lines.append(f"- **{v['name']}** in `{v['package']}`")

        return [TextContent(type="text", text="\n".join(lines))]


    @server.tool()
    async def quay_get_manifest(
        repository: str,
        digest: str,
        namespace: str = "",
    ) -> list[TextContent]:
        """
        Get manifest details for an image.

        Args:
            repository: Repository name
            digest: Image digest
            namespace: Optional namespace override

        Returns:
            Manifest details including layers and config.
        """
        full_path = resolve_repo_path(repository, namespace)

        if not digest.startswith("sha256:"):
            digest = f"sha256:{digest}"

        success, data = await quay_request(f"/repository/{full_path}/manifest/{digest}")

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to get manifest: {data}")]

        lines = [
            f"## Manifest: `{digest[:30]}...`",
            "",
            f"**Repository:** `{full_path}`",
            f"**Media Type:** {data.get('manifest_data', {}).get('mediaType', 'N/A')}",
            f"**Schema Version:** {data.get('manifest_data', {}).get('schemaVersion', 'N/A')}",
        ]

        layers = data.get("manifest_data", {}).get("layers", [])
        if layers:
            lines.extend(["", f"**Layers:** {len(layers)}"])

        return [TextContent(type="text", text="\n".join(lines))]


    # ==================== AA SPECIFIC ====================

    @server.tool()
    async def quay_check_aa_image(
        image_tag: str,
        component: str = "main",
    ) -> list[TextContent]:
        """
        Check if Automation Analytics image exists and is ready for deploy.

        Args:
            image_tag: Image digest/tag from Konflux snapshot
            component: "main" or "billing" (both use same image)

        Returns:
            Image status and deployment readiness.
        """
        repo = "your-tenant/aap-aa-main/your-backend-main"
        namespace = "redhat-user-workloads"
        full_path = f"{namespace}/{repo}"

        digest = image_tag
        if not digest.startswith("sha256:"):
            digest = f"sha256:{digest}"

        success, data = await quay_request(f"/repository/{full_path}/manifest/{digest}")

        if not success:
            if "Not found" in str(data):
                lines = [
                    "## ❌ Image Not Found",
                    "",
                    f"**Digest:** `{image_tag[:30]}...`",
                    f"**Repository:** `{full_path}`",
                    "",
                    "The Konflux build may still be in progress.",
                    "",
                    "**Check build status:**",
                    "- `konflux_pipelineruns(namespace='your-tenant')`",
                ]
                return [TextContent(type="text", text="\n".join(lines))]
            return [TextContent(type="text", text=f"❌ Error: {data}")]

        lines = [
            "## ✅ AA Image Ready",
            "",
            f"**Component:** {component}",
            f"**Digest:** `{digest}`",
            "",
            "Image is built and ready for deployment!",
            "",
            "**Deploy with:**",
            "```",
            f"bonfire_deploy_aa(",
            f"    namespace='ephemeral-XXXXX',",
            f"    template_ref='<commit_sha>',",
            f"    image_tag='{image_tag}',",
            f"    billing={component == 'billing'}",
            f")",
            "```",
        ]

        return [TextContent(type="text", text="\n".join(lines))]


    @server.tool()
    async def quay_list_aa_tags(limit: int = 10) -> list[TextContent]:
        """
        List recent tags for Automation Analytics image.

        Returns:
            Recent AA image tags with build dates.
        """
        repo = "your-tenant/aap-aa-main/your-backend-main"
        namespace = "redhat-user-workloads"
        full_path = f"{namespace}/{repo}"

        success, data = await quay_request(f"/repository/{full_path}/tag/", params={"limit": limit})

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to list AA tags: {data}")]

        tags = data.get("tags", [])

        if not tags:
            return [TextContent(type="text", text="No tags found for AA repository")]

        lines = [
            "## Automation Analytics Images",
            "",
            f"**Repository:** `{full_path}`",
            "",
            "| Tag | Digest | Modified |",
            "|-----|--------|----------|",
        ]

        for tag in tags[:limit]:
            name = tag.get("name", "N/A")
            if len(name) > 30:
                name = name[:27] + "..."
            digest = tag.get("manifest_digest", "")[:19] + "..." if tag.get("manifest_digest") else "N/A"
            modified = tag.get("last_modified", "N/A")
            lines.append(f"| `{name}` | `{digest}` | {modified} |")

        lines.extend(["", f"[View on Quay.io](https://quay.io/repository/{full_path}?tab=tags)"])

        return [TextContent(type="text", text="\n".join(lines))]


    # ==================== ENTRY POINT ====================
    
    return len([m for m in dir() if not m.startswith('_')])  # Approximate count
