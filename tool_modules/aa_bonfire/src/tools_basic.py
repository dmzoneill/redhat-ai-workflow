"""Bonfire Basic Tools - Essential bonfire operations.

For advanced operations, see tools_extra.py.

Tools included (~10):
- bonfire_namespace_reserve, bonfire_namespace_list, bonfire_namespace_describe, bonfire_namespace_release, bonfire_namespace_extend, ...
"""

import asyncio
import logging
import os
import re
import subprocess

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

from server.auto_heal_decorator import auto_heal_ephemeral
from server.tool_registry import ToolRegistry
from server.utils import ensure_cluster_auth, get_kubeconfig, get_section_config, truncate_output

# Setup project path for server imports
from tool_modules.common import PROJECT_ROOT  # noqa: F401 - side effect: adds to sys.path

logger = logging.getLogger(__name__)


def load_bonfire_config() -> dict:
    """Load bonfire configuration from config.json."""
    return get_section_config("bonfire", {})


def get_ephemeral_kubeconfig() -> str:
    """Get kubeconfig path for ephemeral cluster.

    Convenience function - calls get_kubeconfig("ephemeral").
    """
    return get_kubeconfig("ephemeral")


def get_app_config(app_name: str = "", billing: bool = False) -> dict:
    """Get app configuration from config.json.

    For Automation Analytics, the app_name is 'tower-analytics' (the bonfire app name),
    components are 'tower-analytics-clowdapp' or 'tower-analytics-billing-clowdapp'.
    """
    config = load_bonfire_config()
    apps = config.get("apps", {})

    # Try to find the app by name
    resolved_app_name = app_name
    app_config = apps.get(app_name, {})

    if not app_config:
        # Fallback to tower-analytics (default for AA) or first app
        if "tower-analytics" in apps:
            resolved_app_name = "tower-analytics"
            app_config = apps["tower-analytics"]
        elif apps:
            resolved_app_name = next(iter(apps.keys()))
            app_config = apps[resolved_app_name]

    # HARDCODED FALLBACK: If config loading completely failed, use known defaults
    if not resolved_app_name:
        resolved_app_name = "tower-analytics"

    # Get component config
    comp_key = "billing" if billing else "main"
    components = app_config.get("components", {})
    comp_config = components.get(comp_key, components.get("main", {}))

    # Determine component name with proper fallback
    if comp_config and "name" in comp_config:
        component = comp_config["name"]
    else:
        # Hardcoded fallback for AA when config is missing
        if billing:
            component = "tower-analytics-billing-clowdapp"
        else:
            component = "tower-analytics-clowdapp"

    return {
        "app_name": resolved_app_name,
        "component": component,
        "image_base": app_config.get(
            "image_base",
            "quay.io/redhat-user-workloads/aap-aa-tenant/" "aap-aa-main/automation-analytics-backend-main",
        ),
        "ref_env": config.get("ref_env", "insights-production"),
    }


# ==================== Helper Functions ====================


async def run_bonfire(
    args: list[str],
    timeout: int = 300,
    env: dict | None = None,
    auto_auth: bool = True,
) -> tuple[bool, str]:
    """Run bonfire command and return (success, output).

    Args:
        args: Bonfire command arguments
        timeout: Command timeout in seconds
        env: Additional environment variables
        auto_auth: If True, automatically refresh auth if expired (default: True)

    Returns:
        Tuple of (success, output)
    """
    kubeconfig = get_ephemeral_kubeconfig()

    # Check auth before running if auto_auth is enabled
    if auto_auth:
        auth_ok, auth_error = await ensure_cluster_auth("ephemeral", auto_refresh=True)
        if not auth_ok:
            return False, auth_error

    cmd = ["bonfire"] + args

    logger.info(f"Running: {' '.join(cmd)}")

    run_env = os.environ.copy()
    # Always set KUBECONFIG for ephemeral cluster
    run_env["KUBECONFIG"] = kubeconfig
    if env:
        run_env.update(env)

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=run_env,
        )

        output = result.stdout + result.stderr
        if result.returncode != 0:
            return False, output or "Command failed"

        return True, output
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout}s"
    except FileNotFoundError:
        return False, "bonfire not found. Install with: pip install crc-bonfire"
    except Exception as e:
        return False, str(e)


# ==================== VERSION / INFO ====================


def register_tools(server: FastMCP) -> int:
    """Register basic bonfire tools with the MCP server."""
    registry = ToolRegistry(server)

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_reserve(
        duration: str = "1h",
        pool: str = "default",
        requester: str = "",
        name: str = "",
        timeout: int = 600,
        force: bool = True,
    ) -> list[TextContent]:
        """
        Reserve an ephemeral namespace for testing.

        Args:
            duration: How long to reserve (e.g., "1h", "4h", "8h")
            pool: Namespace pool to use (default: "default")
            requester: Your username (for tracking)
            name: Identifier for the reservation
            timeout: Timeout in seconds to wait for resources
            force: Don't prompt if reservations exist for user

        Returns:
            Reserved namespace name.
        """
        args = ["namespace", "reserve"]
        args.extend(["--duration", duration])
        args.extend(["--pool", pool])
        args.extend(["--timeout", str(timeout)])

        if requester:
            args.extend(["--requester", requester])
        if name:
            args.extend(["--name", name])
        if force:
            args.append("--force")

        success, output = await run_bonfire(args, timeout=timeout + 60)

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to reserve namespace:\n\n{output}")]

        lines = [
            "## ✅ Namespace Reserved",
            "",
            f"**Duration:** {duration}",
            f"**Pool:** {pool}",
            "",
            "```",
            output,
            "```",
            "",
            "**Next steps:**",
            "1. Deploy your app: `bonfire_deploy(app='...', namespace='...')`",
            "2. Monitor: `kubectl_get_pods(namespace='...', environment='ephemeral')`",
            "3. Release when done: `bonfire_namespace_release(namespace='...')`",
        ]

        return [TextContent(type="text", text="\n".join(lines))]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_reserve(
        duration: str = "1h",
        pool: str = "default",
        requester: str = "",
        name: str = "",
        timeout: int = 600,
        force: bool = True,
    ) -> list[TextContent]:
        """
        Reserve an ephemeral namespace for testing.

        Args:
            duration: How long to reserve (e.g., "1h", "4h", "8h")
            pool: Namespace pool to use (default: "default")
            requester: Your username (for tracking)
            name: Identifier for the reservation
            timeout: Timeout in seconds to wait for resources
            force: Don't prompt if reservations exist for user

        Returns:
            Reserved namespace name.
        """
        args = ["namespace", "reserve"]
        args.extend(["--duration", duration])
        args.extend(["--pool", pool])
        args.extend(["--timeout", str(timeout)])

        if requester:
            args.extend(["--requester", requester])
        if name:
            args.extend(["--name", name])
        if force:
            args.append("--force")

        success, output = await run_bonfire(args, timeout=timeout + 60)

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to reserve namespace:\n\n{output}")]

        lines = [
            "## ✅ Namespace Reserved",
            "",
            f"**Duration:** {duration}",
            f"**Pool:** {pool}",
            "",
            "```",
            output,
            "```",
            "",
            "**Next steps:**",
            "1. Deploy your app: `bonfire_deploy(app='...', namespace='...')`",
            "2. Monitor: `kubectl_get_pods(namespace='...', environment='ephemeral')`",
            "3. Release when done: `bonfire_namespace_release(namespace='...')`",
        ]

        return [TextContent(type="text", text="\n".join(lines))]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_list(mine_only: bool = True) -> list[TextContent]:
        """
        List current ephemeral namespace reservations.

        Args:
            mine_only: If True (default), only show namespaces owned by current user.
                      ALWAYS use True unless explicitly asked to see all namespaces.

        Returns:
            List of reserved namespaces with status.
        """
        args = ["namespace", "list"]
        if mine_only:
            args.append("--mine")

        success, output = await run_bonfire(args)

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to list namespaces:\n\n{output}")]

        title = "My Ephemeral Namespaces" if mine_only else "All Ephemeral Namespaces"
        return [TextContent(type="text", text=f"## {title}\n\n```\n{output}\n```")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_reserve(
        duration: str = "1h",
        pool: str = "default",
        requester: str = "",
        name: str = "",
        timeout: int = 600,
        force: bool = True,
    ) -> list[TextContent]:
        """
        Reserve an ephemeral namespace for testing.

        Args:
            duration: How long to reserve (e.g., "1h", "4h", "8h")
            pool: Namespace pool to use (default: "default")
            requester: Your username (for tracking)
            name: Identifier for the reservation
            timeout: Timeout in seconds to wait for resources
            force: Don't prompt if reservations exist for user

        Returns:
            Reserved namespace name.
        """
        args = ["namespace", "reserve"]
        args.extend(["--duration", duration])
        args.extend(["--pool", pool])
        args.extend(["--timeout", str(timeout)])

        if requester:
            args.extend(["--requester", requester])
        if name:
            args.extend(["--name", name])
        if force:
            args.append("--force")

        success, output = await run_bonfire(args, timeout=timeout + 60)

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to reserve namespace:\n\n{output}")]

        lines = [
            "## ✅ Namespace Reserved",
            "",
            f"**Duration:** {duration}",
            f"**Pool:** {pool}",
            "",
            "```",
            output,
            "```",
            "",
            "**Next steps:**",
            "1. Deploy your app: `bonfire_deploy(app='...', namespace='...')`",
            "2. Monitor: `kubectl_get_pods(namespace='...', environment='ephemeral')`",
            "3. Release when done: `bonfire_namespace_release(namespace='...')`",
        ]

        return [TextContent(type="text", text="\n".join(lines))]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_list(mine_only: bool = True) -> list[TextContent]:
        """
        List current ephemeral namespace reservations.

        Args:
            mine_only: If True (default), only show namespaces owned by current user.
                      ALWAYS use True unless explicitly asked to see all namespaces.

        Returns:
            List of reserved namespaces with status.
        """
        args = ["namespace", "list"]
        if mine_only:
            args.append("--mine")

        success, output = await run_bonfire(args)

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to list namespaces:\n\n{output}")]

        title = "My Ephemeral Namespaces" if mine_only else "All Ephemeral Namespaces"
        return [TextContent(type="text", text=f"## {title}\n\n```\n{output}\n```")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_describe(namespace: str) -> list[TextContent]:
        """
        Get detailed info about a namespace reservation.

        Args:
            namespace: Namespace to describe

        Returns:
            Namespace details including requester, expiry, etc.
        """
        success, output = await run_bonfire(["namespace", "describe", namespace])

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to describe namespace:\n\n{output}")]

        return [TextContent(type="text", text=f"## Namespace: `{namespace}`\n\n```\n{output}\n```")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_reserve(
        duration: str = "1h",
        pool: str = "default",
        requester: str = "",
        name: str = "",
        timeout: int = 600,
        force: bool = True,
    ) -> list[TextContent]:
        """
        Reserve an ephemeral namespace for testing.

        Args:
            duration: How long to reserve (e.g., "1h", "4h", "8h")
            pool: Namespace pool to use (default: "default")
            requester: Your username (for tracking)
            name: Identifier for the reservation
            timeout: Timeout in seconds to wait for resources
            force: Don't prompt if reservations exist for user

        Returns:
            Reserved namespace name.
        """
        args = ["namespace", "reserve"]
        args.extend(["--duration", duration])
        args.extend(["--pool", pool])
        args.extend(["--timeout", str(timeout)])

        if requester:
            args.extend(["--requester", requester])
        if name:
            args.extend(["--name", name])
        if force:
            args.append("--force")

        success, output = await run_bonfire(args, timeout=timeout + 60)

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to reserve namespace:\n\n{output}")]

        lines = [
            "## ✅ Namespace Reserved",
            "",
            f"**Duration:** {duration}",
            f"**Pool:** {pool}",
            "",
            "```",
            output,
            "```",
            "",
            "**Next steps:**",
            "1. Deploy your app: `bonfire_deploy(app='...', namespace='...')`",
            "2. Monitor: `kubectl_get_pods(namespace='...', environment='ephemeral')`",
            "3. Release when done: `bonfire_namespace_release(namespace='...')`",
        ]

        return [TextContent(type="text", text="\n".join(lines))]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_list(mine_only: bool = True) -> list[TextContent]:
        """
        List current ephemeral namespace reservations.

        Args:
            mine_only: If True (default), only show namespaces owned by current user.
                      ALWAYS use True unless explicitly asked to see all namespaces.

        Returns:
            List of reserved namespaces with status.
        """
        args = ["namespace", "list"]
        if mine_only:
            args.append("--mine")

        success, output = await run_bonfire(args)

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to list namespaces:\n\n{output}")]

        title = "My Ephemeral Namespaces" if mine_only else "All Ephemeral Namespaces"
        return [TextContent(type="text", text=f"## {title}\n\n```\n{output}\n```")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_describe(namespace: str) -> list[TextContent]:
        """
        Get detailed info about a namespace reservation.

        Args:
            namespace: Namespace to describe

        Returns:
            Namespace details including requester, expiry, etc.
        """
        success, output = await run_bonfire(["namespace", "describe", namespace])

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to describe namespace:\n\n{output}")]

        return [TextContent(type="text", text=f"## Namespace: `{namespace}`\n\n```\n{output}\n```")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_release(namespace: str, force: bool = False) -> list[TextContent]:
        """
        Release an ephemeral namespace reservation.

        SAFETY: Only releases namespaces owned by the current user unless force=True.

        Args:
            namespace: Namespace to release
            force: If False (default), verify ownership before release.
                   Only set True if you're absolutely sure.

        Returns:
            Confirmation of release.
        """
        # First verify ownership by checking --mine list
        if not force:
            check_success, check_output = await run_bonfire(["namespace", "list", "--mine"])

            if check_success and namespace not in check_output:
                return [
                    TextContent(
                        type="text",
                        text=f"""❌ **Cannot release namespace `{namespace}`**

This namespace is not owned by you (not in `bonfire namespace list --mine`).

Your namespaces:
```
{check_output}
```

If you're sure you want to release it, call with `force=True` (not recommended).""",
                    )
                ]

        # Always use --force to skip interactive confirmation (non-TTY safe)
        success, output = await run_bonfire(["namespace", "release", namespace, "--force"])

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to release namespace:\n\n{output}")]

        return [TextContent(type="text", text=f"✅ Namespace `{namespace}` released\n\n{output}")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_reserve(
        duration: str = "1h",
        pool: str = "default",
        requester: str = "",
        name: str = "",
        timeout: int = 600,
        force: bool = True,
    ) -> list[TextContent]:
        """
        Reserve an ephemeral namespace for testing.

        Args:
            duration: How long to reserve (e.g., "1h", "4h", "8h")
            pool: Namespace pool to use (default: "default")
            requester: Your username (for tracking)
            name: Identifier for the reservation
            timeout: Timeout in seconds to wait for resources
            force: Don't prompt if reservations exist for user

        Returns:
            Reserved namespace name.
        """
        args = ["namespace", "reserve"]
        args.extend(["--duration", duration])
        args.extend(["--pool", pool])
        args.extend(["--timeout", str(timeout)])

        if requester:
            args.extend(["--requester", requester])
        if name:
            args.extend(["--name", name])
        if force:
            args.append("--force")

        success, output = await run_bonfire(args, timeout=timeout + 60)

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to reserve namespace:\n\n{output}")]

        lines = [
            "## ✅ Namespace Reserved",
            "",
            f"**Duration:** {duration}",
            f"**Pool:** {pool}",
            "",
            "```",
            output,
            "```",
            "",
            "**Next steps:**",
            "1. Deploy your app: `bonfire_deploy(app='...', namespace='...')`",
            "2. Monitor: `kubectl_get_pods(namespace='...', environment='ephemeral')`",
            "3. Release when done: `bonfire_namespace_release(namespace='...')`",
        ]

        return [TextContent(type="text", text="\n".join(lines))]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_list(mine_only: bool = True) -> list[TextContent]:
        """
        List current ephemeral namespace reservations.

        Args:
            mine_only: If True (default), only show namespaces owned by current user.
                      ALWAYS use True unless explicitly asked to see all namespaces.

        Returns:
            List of reserved namespaces with status.
        """
        args = ["namespace", "list"]
        if mine_only:
            args.append("--mine")

        success, output = await run_bonfire(args)

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to list namespaces:\n\n{output}")]

        title = "My Ephemeral Namespaces" if mine_only else "All Ephemeral Namespaces"
        return [TextContent(type="text", text=f"## {title}\n\n```\n{output}\n```")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_describe(namespace: str) -> list[TextContent]:
        """
        Get detailed info about a namespace reservation.

        Args:
            namespace: Namespace to describe

        Returns:
            Namespace details including requester, expiry, etc.
        """
        success, output = await run_bonfire(["namespace", "describe", namespace])

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to describe namespace:\n\n{output}")]

        return [TextContent(type="text", text=f"## Namespace: `{namespace}`\n\n```\n{output}\n```")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_release(namespace: str, force: bool = False) -> list[TextContent]:
        """
        Release an ephemeral namespace reservation.

        SAFETY: Only releases namespaces owned by the current user unless force=True.

        Args:
            namespace: Namespace to release
            force: If False (default), verify ownership before release.
                   Only set True if you're absolutely sure.

        Returns:
            Confirmation of release.
        """
        # First verify ownership by checking --mine list
        if not force:
            check_success, check_output = await run_bonfire(["namespace", "list", "--mine"])

            if check_success and namespace not in check_output:
                return [
                    TextContent(
                        type="text",
                        text=f"""❌ **Cannot release namespace `{namespace}`**

This namespace is not owned by you (not in `bonfire namespace list --mine`).

Your namespaces:
```
{check_output}
```

If you're sure you want to release it, call with `force=True` (not recommended).""",
                    )
                ]

        # Always use --force to skip interactive confirmation (non-TTY safe)
        success, output = await run_bonfire(["namespace", "release", namespace, "--force"])

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to release namespace:\n\n{output}")]

        return [TextContent(type="text", text=f"✅ Namespace `{namespace}` released\n\n{output}")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_extend(
        namespace: str,
        duration: str = "1h",
    ) -> list[TextContent]:
        """
        Extend an ephemeral namespace reservation.

        Args:
            namespace: Namespace to extend
            duration: Additional time (e.g., "1h", "2h")

        Returns:
            New expiration time.
        """
        success, output = await run_bonfire(["namespace", "extend", namespace, "--duration", duration])

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to extend namespace:\n\n{output}")]

        return [TextContent(type="text", text=f"✅ Namespace `{namespace}` extended by {duration}\n\n{output}")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_reserve(
        duration: str = "1h",
        pool: str = "default",
        requester: str = "",
        name: str = "",
        timeout: int = 600,
        force: bool = True,
    ) -> list[TextContent]:
        """
        Reserve an ephemeral namespace for testing.

        Args:
            duration: How long to reserve (e.g., "1h", "4h", "8h")
            pool: Namespace pool to use (default: "default")
            requester: Your username (for tracking)
            name: Identifier for the reservation
            timeout: Timeout in seconds to wait for resources
            force: Don't prompt if reservations exist for user

        Returns:
            Reserved namespace name.
        """
        args = ["namespace", "reserve"]
        args.extend(["--duration", duration])
        args.extend(["--pool", pool])
        args.extend(["--timeout", str(timeout)])

        if requester:
            args.extend(["--requester", requester])
        if name:
            args.extend(["--name", name])
        if force:
            args.append("--force")

        success, output = await run_bonfire(args, timeout=timeout + 60)

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to reserve namespace:\n\n{output}")]

        lines = [
            "## ✅ Namespace Reserved",
            "",
            f"**Duration:** {duration}",
            f"**Pool:** {pool}",
            "",
            "```",
            output,
            "```",
            "",
            "**Next steps:**",
            "1. Deploy your app: `bonfire_deploy(app='...', namespace='...')`",
            "2. Monitor: `kubectl_get_pods(namespace='...', environment='ephemeral')`",
            "3. Release when done: `bonfire_namespace_release(namespace='...')`",
        ]

        return [TextContent(type="text", text="\n".join(lines))]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_list(mine_only: bool = True) -> list[TextContent]:
        """
        List current ephemeral namespace reservations.

        Args:
            mine_only: If True (default), only show namespaces owned by current user.
                      ALWAYS use True unless explicitly asked to see all namespaces.

        Returns:
            List of reserved namespaces with status.
        """
        args = ["namespace", "list"]
        if mine_only:
            args.append("--mine")

        success, output = await run_bonfire(args)

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to list namespaces:\n\n{output}")]

        title = "My Ephemeral Namespaces" if mine_only else "All Ephemeral Namespaces"
        return [TextContent(type="text", text=f"## {title}\n\n```\n{output}\n```")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_describe(namespace: str) -> list[TextContent]:
        """
        Get detailed info about a namespace reservation.

        Args:
            namespace: Namespace to describe

        Returns:
            Namespace details including requester, expiry, etc.
        """
        success, output = await run_bonfire(["namespace", "describe", namespace])

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to describe namespace:\n\n{output}")]

        return [TextContent(type="text", text=f"## Namespace: `{namespace}`\n\n```\n{output}\n```")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_release(namespace: str, force: bool = False) -> list[TextContent]:
        """
        Release an ephemeral namespace reservation.

        SAFETY: Only releases namespaces owned by the current user unless force=True.

        Args:
            namespace: Namespace to release
            force: If False (default), verify ownership before release.
                   Only set True if you're absolutely sure.

        Returns:
            Confirmation of release.
        """
        # First verify ownership by checking --mine list
        if not force:
            check_success, check_output = await run_bonfire(["namespace", "list", "--mine"])

            if check_success and namespace not in check_output:
                return [
                    TextContent(
                        type="text",
                        text=f"""❌ **Cannot release namespace `{namespace}`**

This namespace is not owned by you (not in `bonfire namespace list --mine`).

Your namespaces:
```
{check_output}
```

If you're sure you want to release it, call with `force=True` (not recommended).""",
                    )
                ]

        # Always use --force to skip interactive confirmation (non-TTY safe)
        success, output = await run_bonfire(["namespace", "release", namespace, "--force"])

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to release namespace:\n\n{output}")]

        return [TextContent(type="text", text=f"✅ Namespace `{namespace}` released\n\n{output}")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_extend(
        namespace: str,
        duration: str = "1h",
    ) -> list[TextContent]:
        """
        Extend an ephemeral namespace reservation.

        Args:
            namespace: Namespace to extend
            duration: Additional time (e.g., "1h", "2h")

        Returns:
            New expiration time.
        """
        success, output = await run_bonfire(["namespace", "extend", namespace, "--duration", duration])

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to extend namespace:\n\n{output}")]

        return [TextContent(type="text", text=f"✅ Namespace `{namespace}` extended by {duration}\n\n{output}")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_wait(
        namespace: str,
        timeout: int = 300,
    ) -> list[TextContent]:
        """
        Wait for resources to be ready in a namespace.

        Args:
            namespace: Namespace to wait on
            timeout: Timeout in seconds

        Returns:
            Status when ready or timeout.
        """
        success, output = await run_bonfire(
            ["namespace", "wait-on-resources", namespace, "--timeout", str(timeout)],
            timeout=timeout + 60,
        )

        if not success:
            return [TextContent(type="text", text=f"❌ Wait failed:\n\n{output}")]

        return [TextContent(type="text", text=f"✅ Resources ready in `{namespace}`\n\n{output}")]

    # ==================== APPS ====================

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_reserve(
        duration: str = "1h",
        pool: str = "default",
        requester: str = "",
        name: str = "",
        timeout: int = 600,
        force: bool = True,
    ) -> list[TextContent]:
        """
        Reserve an ephemeral namespace for testing.

        Args:
            duration: How long to reserve (e.g., "1h", "4h", "8h")
            pool: Namespace pool to use (default: "default")
            requester: Your username (for tracking)
            name: Identifier for the reservation
            timeout: Timeout in seconds to wait for resources
            force: Don't prompt if reservations exist for user

        Returns:
            Reserved namespace name.
        """
        args = ["namespace", "reserve"]
        args.extend(["--duration", duration])
        args.extend(["--pool", pool])
        args.extend(["--timeout", str(timeout)])

        if requester:
            args.extend(["--requester", requester])
        if name:
            args.extend(["--name", name])
        if force:
            args.append("--force")

        success, output = await run_bonfire(args, timeout=timeout + 60)

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to reserve namespace:\n\n{output}")]

        lines = [
            "## ✅ Namespace Reserved",
            "",
            f"**Duration:** {duration}",
            f"**Pool:** {pool}",
            "",
            "```",
            output,
            "```",
            "",
            "**Next steps:**",
            "1. Deploy your app: `bonfire_deploy(app='...', namespace='...')`",
            "2. Monitor: `kubectl_get_pods(namespace='...', environment='ephemeral')`",
            "3. Release when done: `bonfire_namespace_release(namespace='...')`",
        ]

        return [TextContent(type="text", text="\n".join(lines))]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_list(mine_only: bool = True) -> list[TextContent]:
        """
        List current ephemeral namespace reservations.

        Args:
            mine_only: If True (default), only show namespaces owned by current user.
                      ALWAYS use True unless explicitly asked to see all namespaces.

        Returns:
            List of reserved namespaces with status.
        """
        args = ["namespace", "list"]
        if mine_only:
            args.append("--mine")

        success, output = await run_bonfire(args)

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to list namespaces:\n\n{output}")]

        title = "My Ephemeral Namespaces" if mine_only else "All Ephemeral Namespaces"
        return [TextContent(type="text", text=f"## {title}\n\n```\n{output}\n```")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_describe(namespace: str) -> list[TextContent]:
        """
        Get detailed info about a namespace reservation.

        Args:
            namespace: Namespace to describe

        Returns:
            Namespace details including requester, expiry, etc.
        """
        success, output = await run_bonfire(["namespace", "describe", namespace])

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to describe namespace:\n\n{output}")]

        return [TextContent(type="text", text=f"## Namespace: `{namespace}`\n\n```\n{output}\n```")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_release(namespace: str, force: bool = False) -> list[TextContent]:
        """
        Release an ephemeral namespace reservation.

        SAFETY: Only releases namespaces owned by the current user unless force=True.

        Args:
            namespace: Namespace to release
            force: If False (default), verify ownership before release.
                   Only set True if you're absolutely sure.

        Returns:
            Confirmation of release.
        """
        # First verify ownership by checking --mine list
        if not force:
            check_success, check_output = await run_bonfire(["namespace", "list", "--mine"])

            if check_success and namespace not in check_output:
                return [
                    TextContent(
                        type="text",
                        text=f"""❌ **Cannot release namespace `{namespace}`**

This namespace is not owned by you (not in `bonfire namespace list --mine`).

Your namespaces:
```
{check_output}
```

If you're sure you want to release it, call with `force=True` (not recommended).""",
                    )
                ]

        # Always use --force to skip interactive confirmation (non-TTY safe)
        success, output = await run_bonfire(["namespace", "release", namespace, "--force"])

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to release namespace:\n\n{output}")]

        return [TextContent(type="text", text=f"✅ Namespace `{namespace}` released\n\n{output}")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_extend(
        namespace: str,
        duration: str = "1h",
    ) -> list[TextContent]:
        """
        Extend an ephemeral namespace reservation.

        Args:
            namespace: Namespace to extend
            duration: Additional time (e.g., "1h", "2h")

        Returns:
            New expiration time.
        """
        success, output = await run_bonfire(["namespace", "extend", namespace, "--duration", duration])

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to extend namespace:\n\n{output}")]

        return [TextContent(type="text", text=f"✅ Namespace `{namespace}` extended by {duration}\n\n{output}")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_wait(
        namespace: str,
        timeout: int = 300,
    ) -> list[TextContent]:
        """
        Wait for resources to be ready in a namespace.

        Args:
            namespace: Namespace to wait on
            timeout: Timeout in seconds

        Returns:
            Status when ready or timeout.
        """
        success, output = await run_bonfire(
            ["namespace", "wait-on-resources", namespace, "--timeout", str(timeout)],
            timeout=timeout + 60,
        )

        if not success:
            return [TextContent(type="text", text=f"❌ Wait failed:\n\n{output}")]

        return [TextContent(type="text", text=f"✅ Resources ready in `{namespace}`\n\n{output}")]

    # ==================== APPS ====================

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_apps_list(target_env: str = "insights-ephemeral") -> list[TextContent]:
        """
        List all deployable apps.

        Args:
            target_env: Target environment (default: insights-ephemeral)

        Returns:
            List of available apps.
        """
        success, output = await run_bonfire(["apps", "list", "--target-env", target_env])

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to list apps:\n\n{output}")]

        return [TextContent(type="text", text=f"## Deployable Apps\n\n```\n{output}\n```")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_reserve(
        duration: str = "1h",
        pool: str = "default",
        requester: str = "",
        name: str = "",
        timeout: int = 600,
        force: bool = True,
    ) -> list[TextContent]:
        """
        Reserve an ephemeral namespace for testing.

        Args:
            duration: How long to reserve (e.g., "1h", "4h", "8h")
            pool: Namespace pool to use (default: "default")
            requester: Your username (for tracking)
            name: Identifier for the reservation
            timeout: Timeout in seconds to wait for resources
            force: Don't prompt if reservations exist for user

        Returns:
            Reserved namespace name.
        """
        args = ["namespace", "reserve"]
        args.extend(["--duration", duration])
        args.extend(["--pool", pool])
        args.extend(["--timeout", str(timeout)])

        if requester:
            args.extend(["--requester", requester])
        if name:
            args.extend(["--name", name])
        if force:
            args.append("--force")

        success, output = await run_bonfire(args, timeout=timeout + 60)

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to reserve namespace:\n\n{output}")]

        lines = [
            "## ✅ Namespace Reserved",
            "",
            f"**Duration:** {duration}",
            f"**Pool:** {pool}",
            "",
            "```",
            output,
            "```",
            "",
            "**Next steps:**",
            "1. Deploy your app: `bonfire_deploy(app='...', namespace='...')`",
            "2. Monitor: `kubectl_get_pods(namespace='...', environment='ephemeral')`",
            "3. Release when done: `bonfire_namespace_release(namespace='...')`",
        ]

        return [TextContent(type="text", text="\n".join(lines))]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_list(mine_only: bool = True) -> list[TextContent]:
        """
        List current ephemeral namespace reservations.

        Args:
            mine_only: If True (default), only show namespaces owned by current user.
                      ALWAYS use True unless explicitly asked to see all namespaces.

        Returns:
            List of reserved namespaces with status.
        """
        args = ["namespace", "list"]
        if mine_only:
            args.append("--mine")

        success, output = await run_bonfire(args)

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to list namespaces:\n\n{output}")]

        title = "My Ephemeral Namespaces" if mine_only else "All Ephemeral Namespaces"
        return [TextContent(type="text", text=f"## {title}\n\n```\n{output}\n```")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_describe(namespace: str) -> list[TextContent]:
        """
        Get detailed info about a namespace reservation.

        Args:
            namespace: Namespace to describe

        Returns:
            Namespace details including requester, expiry, etc.
        """
        success, output = await run_bonfire(["namespace", "describe", namespace])

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to describe namespace:\n\n{output}")]

        return [TextContent(type="text", text=f"## Namespace: `{namespace}`\n\n```\n{output}\n```")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_release(namespace: str, force: bool = False) -> list[TextContent]:
        """
        Release an ephemeral namespace reservation.

        SAFETY: Only releases namespaces owned by the current user unless force=True.

        Args:
            namespace: Namespace to release
            force: If False (default), verify ownership before release.
                   Only set True if you're absolutely sure.

        Returns:
            Confirmation of release.
        """
        # First verify ownership by checking --mine list
        if not force:
            check_success, check_output = await run_bonfire(["namespace", "list", "--mine"])

            if check_success and namespace not in check_output:
                return [
                    TextContent(
                        type="text",
                        text=f"""❌ **Cannot release namespace `{namespace}`**

This namespace is not owned by you (not in `bonfire namespace list --mine`).

Your namespaces:
```
{check_output}
```

If you're sure you want to release it, call with `force=True` (not recommended).""",
                    )
                ]

        # Always use --force to skip interactive confirmation (non-TTY safe)
        success, output = await run_bonfire(["namespace", "release", namespace, "--force"])

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to release namespace:\n\n{output}")]

        return [TextContent(type="text", text=f"✅ Namespace `{namespace}` released\n\n{output}")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_extend(
        namespace: str,
        duration: str = "1h",
    ) -> list[TextContent]:
        """
        Extend an ephemeral namespace reservation.

        Args:
            namespace: Namespace to extend
            duration: Additional time (e.g., "1h", "2h")

        Returns:
            New expiration time.
        """
        success, output = await run_bonfire(["namespace", "extend", namespace, "--duration", duration])

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to extend namespace:\n\n{output}")]

        return [TextContent(type="text", text=f"✅ Namespace `{namespace}` extended by {duration}\n\n{output}")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_wait(
        namespace: str,
        timeout: int = 300,
    ) -> list[TextContent]:
        """
        Wait for resources to be ready in a namespace.

        Args:
            namespace: Namespace to wait on
            timeout: Timeout in seconds

        Returns:
            Status when ready or timeout.
        """
        success, output = await run_bonfire(
            ["namespace", "wait-on-resources", namespace, "--timeout", str(timeout)],
            timeout=timeout + 60,
        )

        if not success:
            return [TextContent(type="text", text=f"❌ Wait failed:\n\n{output}")]

        return [TextContent(type="text", text=f"✅ Resources ready in `{namespace}`\n\n{output}")]

    # ==================== APPS ====================

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_apps_list(target_env: str = "insights-ephemeral") -> list[TextContent]:
        """
        List all deployable apps.

        Args:
            target_env: Target environment (default: insights-ephemeral)

        Returns:
            List of available apps.
        """
        success, output = await run_bonfire(["apps", "list", "--target-env", target_env])

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to list apps:\n\n{output}")]

        return [TextContent(type="text", text=f"## Deployable Apps\n\n```\n{output}\n```")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_apps_dependencies(component: str) -> list[TextContent]:
        """
        Show apps that depend on a component.

        Args:
            component: Component name to check

        Returns:
            List of apps depending on this component.
        """
        success, output = await run_bonfire(["apps", "what-depends-on", component])

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to check dependencies:\n\n{output}")]

        return [TextContent(type="text", text=f"## Apps depending on `{component}`\n\n```\n{output}\n```")]

    # ==================== DEPLOYMENT ====================

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_reserve(
        duration: str = "1h",
        pool: str = "default",
        requester: str = "",
        name: str = "",
        timeout: int = 600,
        force: bool = True,
    ) -> list[TextContent]:
        """
        Reserve an ephemeral namespace for testing.

        Args:
            duration: How long to reserve (e.g., "1h", "4h", "8h")
            pool: Namespace pool to use (default: "default")
            requester: Your username (for tracking)
            name: Identifier for the reservation
            timeout: Timeout in seconds to wait for resources
            force: Don't prompt if reservations exist for user

        Returns:
            Reserved namespace name.
        """
        args = ["namespace", "reserve"]
        args.extend(["--duration", duration])
        args.extend(["--pool", pool])
        args.extend(["--timeout", str(timeout)])

        if requester:
            args.extend(["--requester", requester])
        if name:
            args.extend(["--name", name])
        if force:
            args.append("--force")

        success, output = await run_bonfire(args, timeout=timeout + 60)

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to reserve namespace:\n\n{output}")]

        lines = [
            "## ✅ Namespace Reserved",
            "",
            f"**Duration:** {duration}",
            f"**Pool:** {pool}",
            "",
            "```",
            output,
            "```",
            "",
            "**Next steps:**",
            "1. Deploy your app: `bonfire_deploy(app='...', namespace='...')`",
            "2. Monitor: `kubectl_get_pods(namespace='...', environment='ephemeral')`",
            "3. Release when done: `bonfire_namespace_release(namespace='...')`",
        ]

        return [TextContent(type="text", text="\n".join(lines))]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_list(mine_only: bool = True) -> list[TextContent]:
        """
        List current ephemeral namespace reservations.

        Args:
            mine_only: If True (default), only show namespaces owned by current user.
                      ALWAYS use True unless explicitly asked to see all namespaces.

        Returns:
            List of reserved namespaces with status.
        """
        args = ["namespace", "list"]
        if mine_only:
            args.append("--mine")

        success, output = await run_bonfire(args)

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to list namespaces:\n\n{output}")]

        title = "My Ephemeral Namespaces" if mine_only else "All Ephemeral Namespaces"
        return [TextContent(type="text", text=f"## {title}\n\n```\n{output}\n```")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_describe(namespace: str) -> list[TextContent]:
        """
        Get detailed info about a namespace reservation.

        Args:
            namespace: Namespace to describe

        Returns:
            Namespace details including requester, expiry, etc.
        """
        success, output = await run_bonfire(["namespace", "describe", namespace])

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to describe namespace:\n\n{output}")]

        return [TextContent(type="text", text=f"## Namespace: `{namespace}`\n\n```\n{output}\n```")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_release(namespace: str, force: bool = False) -> list[TextContent]:
        """
        Release an ephemeral namespace reservation.

        SAFETY: Only releases namespaces owned by the current user unless force=True.

        Args:
            namespace: Namespace to release
            force: If False (default), verify ownership before release.
                   Only set True if you're absolutely sure.

        Returns:
            Confirmation of release.
        """
        # First verify ownership by checking --mine list
        if not force:
            check_success, check_output = await run_bonfire(["namespace", "list", "--mine"])

            if check_success and namespace not in check_output:
                return [
                    TextContent(
                        type="text",
                        text=f"""❌ **Cannot release namespace `{namespace}`**

This namespace is not owned by you (not in `bonfire namespace list --mine`).

Your namespaces:
```
{check_output}
```

If you're sure you want to release it, call with `force=True` (not recommended).""",
                    )
                ]

        # Always use --force to skip interactive confirmation (non-TTY safe)
        success, output = await run_bonfire(["namespace", "release", namespace, "--force"])

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to release namespace:\n\n{output}")]

        return [TextContent(type="text", text=f"✅ Namespace `{namespace}` released\n\n{output}")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_extend(
        namespace: str,
        duration: str = "1h",
    ) -> list[TextContent]:
        """
        Extend an ephemeral namespace reservation.

        Args:
            namespace: Namespace to extend
            duration: Additional time (e.g., "1h", "2h")

        Returns:
            New expiration time.
        """
        success, output = await run_bonfire(["namespace", "extend", namespace, "--duration", duration])

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to extend namespace:\n\n{output}")]

        return [TextContent(type="text", text=f"✅ Namespace `{namespace}` extended by {duration}\n\n{output}")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_wait(
        namespace: str,
        timeout: int = 300,
    ) -> list[TextContent]:
        """
        Wait for resources to be ready in a namespace.

        Args:
            namespace: Namespace to wait on
            timeout: Timeout in seconds

        Returns:
            Status when ready or timeout.
        """
        success, output = await run_bonfire(
            ["namespace", "wait-on-resources", namespace, "--timeout", str(timeout)],
            timeout=timeout + 60,
        )

        if not success:
            return [TextContent(type="text", text=f"❌ Wait failed:\n\n{output}")]

        return [TextContent(type="text", text=f"✅ Resources ready in `{namespace}`\n\n{output}")]

    # ==================== APPS ====================

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_apps_list(target_env: str = "insights-ephemeral") -> list[TextContent]:
        """
        List all deployable apps.

        Args:
            target_env: Target environment (default: insights-ephemeral)

        Returns:
            List of available apps.
        """
        success, output = await run_bonfire(["apps", "list", "--target-env", target_env])

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to list apps:\n\n{output}")]

        return [TextContent(type="text", text=f"## Deployable Apps\n\n```\n{output}\n```")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_apps_dependencies(component: str) -> list[TextContent]:
        """
        Show apps that depend on a component.

        Args:
            component: Component name to check

        Returns:
            List of apps depending on this component.
        """
        success, output = await run_bonfire(["apps", "what-depends-on", component])

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to check dependencies:\n\n{output}")]

        return [TextContent(type="text", text=f"## Apps depending on `{component}`\n\n```\n{output}\n```")]

    # ==================== DEPLOYMENT ====================

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_deploy(
        app: str,
        namespace: str = "",
        source: str = "appsre",
        target_env: str = "insights-ephemeral",
        ref_env: str = "",
        set_image_tag: str = "",
        set_template_ref: str = "",
        component: str = "",
        timeout: int = 600,
        no_get_dependencies: bool = False,
        single_replicas: bool = True,
        reserve: bool = False,
    ) -> list[TextContent]:
        """
        Deploy a ClowdApp to an ephemeral namespace.

        Args:
            app: Application name(s) to deploy (space-separated for multiple)
            namespace: Target namespace (if empty and reserve=False, uses current context)
            source: Config source - "appsre" or "file"
            target_env: Target environment for template params
            ref_env: Reference environment for default refs/IMAGE_TAGs
            set_image_tag: Override image tag format: '<image uri>=<tag>'
            set_template_ref: Override template ref: '<component>=<ref>'
            component: Specific component(s) to deploy
            timeout: Deployment timeout in seconds
            no_get_dependencies: Don't fetch ClowdApp dependencies
            single_replicas: Set all replicas to 1
            reserve: Force reserve a new namespace

        Returns:
            Deployment status.
        """
        apps = app.split() if " " in app else [app]
        args = ["deploy"] + apps

        args.extend(["--source", source])
        args.extend(["--target-env", target_env])
        args.extend(["--timeout", str(timeout)])

        if namespace:
            args.extend(["--namespace", namespace])
        if ref_env:
            args.extend(["--ref-env", ref_env])
        if set_image_tag:
            args.extend(["--set-image-tag", set_image_tag])
        if set_template_ref:
            args.extend(["--set-template-ref", set_template_ref])
        if component:
            args.extend(["--component", component])
        if no_get_dependencies:
            args.append("--no-get-dependencies")
        if single_replicas:
            args.append("--single-replicas")
        if reserve:
            args.append("--reserve")

        success, output = await run_bonfire(args, timeout=timeout + 120)

        if not success:
            return [TextContent(type="text", text=f"❌ Deployment failed:\n\n```\n{output}\n```")]

        display_output = truncate_output(output, 5000, mode="tail")

        lines = [
            f"## ✅ Deployed `{app}`",
            "",
            "```",
            display_output,
            "```",
            "",
            "**Check status:**",
            "- Pods: `kubectl_get_pods(namespace='...', environment='ephemeral')`",
            "- Logs: `kubectl_logs(pod_name='...', namespace='...', environment='ephemeral')`",
        ]

        return [TextContent(type="text", text="\n".join(lines))]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_deploy_with_reserve(
        app: str,
        duration: str = "1h",
        pool: str = "default",
        requester: str = "",
        timeout: int = 600,
    ) -> list[TextContent]:
        """
        Reserve a namespace AND deploy app in one step.

        Args:
            app: Application name(s) to deploy
            duration: Namespace reservation duration
            pool: Namespace pool
            requester: Your username
            timeout: Deployment timeout

        Returns:
            Namespace and deployment status.
        """
        apps = app.split() if " " in app else [app]
        args = ["deploy"] + apps

        args.append("--reserve")
        args.extend(["--duration", duration])
        args.extend(["--pool", pool])
        args.extend(["--timeout", str(timeout)])
        args.append("--force")
        args.append("--single-replicas")

        if requester:
            args.extend(["--requester", requester])

        success, output = await run_bonfire(args, timeout=timeout + 120)

        if not success:
            return [TextContent(type="text", text=f"❌ Deploy with reserve failed:\n\n```\n{output}\n```")]

        display_output = truncate_output(output, 5000, mode="tail")

        return [TextContent(type="text", text=f"## ✅ Reserved & Deployed `{app}`\n\n```\n{display_output}\n```")]

    # ==================== PROCESS (DRY-RUN) ====================

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_process(
        app: str,
        namespace: str = "",
        source: str = "appsre",
        target_env: str = "insights-ephemeral",
        set_image_tag: str = "",
        component: str = "",
        no_get_dependencies: bool = False,
    ) -> list[TextContent]:
        """
        Process and show the rendered ClowdApp template (dry-run, no deploy).

        Args:
            app: Application name
            namespace: Namespace to render for
            source: Config source
            target_env: Target environment
            set_image_tag: Override image tag
            component: Specific component
            no_get_dependencies: Don't fetch dependencies

        Returns:
            Rendered ClowdApp YAML.
        """
        apps = app.split() if " " in app else [app]
        args = ["process"] + apps

        args.extend(["--source", source])
        args.extend(["--target-env", target_env])

        if namespace:
            args.extend(["--namespace", namespace])
        if set_image_tag:
            args.extend(["--set-image-tag", set_image_tag])
        if component:
            args.extend(["--component", component])
        if no_get_dependencies:
            args.append("--no-get-dependencies")

        success, output = await run_bonfire(args)

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to process template:\n\n{output}")]

        output = truncate_output(output, max_length=15000, suffix="\n\n... (truncated, output too large)")
        return [TextContent(type="text", text=f"## ClowdApp Template: `{app}`\n\n```yaml\n{output}\n```")]

    # ==================== CLOWDENV ====================

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_deploy_env(
        namespace: str,
        timeout: int = 300,
    ) -> list[TextContent]:
        """
        Deploy a ClowdEnvironment to a namespace.

        Args:
            namespace: Target namespace
            timeout: Timeout in seconds

        Returns:
            Deployment status.
        """
        args = ["deploy-env", "--namespace", namespace, "--timeout", str(timeout)]

        success, output = await run_bonfire(args, timeout=timeout + 60)

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to deploy ClowdEnv:\n\n{output}")]

        return [TextContent(type="text", text=f"✅ ClowdEnvironment deployed to `{namespace}`\n\n{output}")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_process_env(namespace: str) -> list[TextContent]:
        """
        Process ClowdEnv template and show output (dry-run).

        Args:
            namespace: Target namespace

        Returns:
            Rendered ClowdEnvironment YAML.
        """
        args = ["process-env", "--namespace", namespace]

        success, output = await run_bonfire(args)

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to process ClowdEnv:\n\n{output}")]

        output = truncate_output(output, max_length=10000)
        return [TextContent(type="text", text=f"## ClowdEnvironment: `{namespace}`\n\n```yaml\n{output}\n```")]

    # ==================== IQE CJI ====================

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_deploy_iqe_cji(
        namespace: str,
        cji_name: str = "",
        marker: str = "",
        filter_expr: str = "",
        env: str = "",
        timeout: int = 600,
    ) -> list[TextContent]:
        """
        Deploy IQE ClowdJobInvocation for integration tests.

        Args:
            namespace: Target namespace
            cji_name: Name for the CJI
            marker: pytest marker expression
            filter_expr: pytest filter expression
            env: Additional env vars (comma-separated KEY=VALUE)
            timeout: Timeout in seconds

        Returns:
            CJI deployment status.
        """
        args = ["deploy-iqe-cji", "--namespace", namespace, "--timeout", str(timeout)]

        if cji_name:
            args.extend(["--cji-name", cji_name])
        if marker:
            args.extend(["--marker", marker])
        if filter_expr:
            args.extend(["--filter", filter_expr])
        if env:
            for e in env.split(","):
                args.extend(["--env", e.strip()])

        success, output = await run_bonfire(args, timeout=timeout + 120)

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to deploy IQE CJI:\n\n{output}")]

        return [TextContent(type="text", text=f"✅ IQE CJI deployed to `{namespace}`\n\n```\n{output}\n```")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_process_iqe_cji(
        namespace: str,
        marker: str = "",
        filter_expr: str = "",
    ) -> list[TextContent]:
        """
        Process IQE CJI template (dry-run).

        Args:
            namespace: Target namespace
            marker: pytest marker expression
            filter_expr: pytest filter expression

        Returns:
            Rendered CJI YAML.
        """
        args = ["process-iqe-cji", "--namespace", namespace]

        if marker:
            args.extend(["--marker", marker])
        if filter_expr:
            args.extend(["--filter", filter_expr])

        success, output = await run_bonfire(args)

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to process IQE CJI:\n\n{output}")]

        output = truncate_output(output, max_length=8000)
        return [TextContent(type="text", text=f"## IQE CJI Template\n\n```yaml\n{output}\n```")]

    # ==================== POOL ====================

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_pool_list() -> list[TextContent]:
        """
        List available namespace pool types.

        Returns:
            List of pool types.
        """
        success, output = await run_bonfire(["pool", "list"])

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to list pools:\n\n{output}")]

        return [TextContent(type="text", text=f"## Namespace Pools\n\n```\n{output}\n```")]

    # ==================== AUTOMATION ANALYTICS HELPERS ====================

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_reserve(
        duration: str = "1h",
        pool: str = "default",
        requester: str = "",
        name: str = "",
        timeout: int = 600,
        force: bool = True,
    ) -> list[TextContent]:
        """
        Reserve an ephemeral namespace for testing.

        Args:
            duration: How long to reserve (e.g., "1h", "4h", "8h")
            pool: Namespace pool to use (default: "default")
            requester: Your username (for tracking)
            name: Identifier for the reservation
            timeout: Timeout in seconds to wait for resources
            force: Don't prompt if reservations exist for user

        Returns:
            Reserved namespace name.
        """
        args = ["namespace", "reserve"]
        args.extend(["--duration", duration])
        args.extend(["--pool", pool])
        args.extend(["--timeout", str(timeout)])

        if requester:
            args.extend(["--requester", requester])
        if name:
            args.extend(["--name", name])
        if force:
            args.append("--force")

        success, output = await run_bonfire(args, timeout=timeout + 60)

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to reserve namespace:\n\n{output}")]

        lines = [
            "## ✅ Namespace Reserved",
            "",
            f"**Duration:** {duration}",
            f"**Pool:** {pool}",
            "",
            "```",
            output,
            "```",
            "",
            "**Next steps:**",
            "1. Deploy your app: `bonfire_deploy(app='...', namespace='...')`",
            "2. Monitor: `kubectl_get_pods(namespace='...', environment='ephemeral')`",
            "3. Release when done: `bonfire_namespace_release(namespace='...')`",
        ]

        return [TextContent(type="text", text="\n".join(lines))]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_list(mine_only: bool = True) -> list[TextContent]:
        """
        List current ephemeral namespace reservations.

        Args:
            mine_only: If True (default), only show namespaces owned by current user.
                      ALWAYS use True unless explicitly asked to see all namespaces.

        Returns:
            List of reserved namespaces with status.
        """
        args = ["namespace", "list"]
        if mine_only:
            args.append("--mine")

        success, output = await run_bonfire(args)

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to list namespaces:\n\n{output}")]

        title = "My Ephemeral Namespaces" if mine_only else "All Ephemeral Namespaces"
        return [TextContent(type="text", text=f"## {title}\n\n```\n{output}\n```")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_describe(namespace: str) -> list[TextContent]:
        """
        Get detailed info about a namespace reservation.

        Args:
            namespace: Namespace to describe

        Returns:
            Namespace details including requester, expiry, etc.
        """
        success, output = await run_bonfire(["namespace", "describe", namespace])

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to describe namespace:\n\n{output}")]

        return [TextContent(type="text", text=f"## Namespace: `{namespace}`\n\n```\n{output}\n```")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_release(namespace: str, force: bool = False) -> list[TextContent]:
        """
        Release an ephemeral namespace reservation.

        SAFETY: Only releases namespaces owned by the current user unless force=True.

        Args:
            namespace: Namespace to release
            force: If False (default), verify ownership before release.
                   Only set True if you're absolutely sure.

        Returns:
            Confirmation of release.
        """
        # First verify ownership by checking --mine list
        if not force:
            check_success, check_output = await run_bonfire(["namespace", "list", "--mine"])

            if check_success and namespace not in check_output:
                return [
                    TextContent(
                        type="text",
                        text=f"""❌ **Cannot release namespace `{namespace}`**

This namespace is not owned by you (not in `bonfire namespace list --mine`).

Your namespaces:
```
{check_output}
```

If you're sure you want to release it, call with `force=True` (not recommended).""",
                    )
                ]

        # Always use --force to skip interactive confirmation (non-TTY safe)
        success, output = await run_bonfire(["namespace", "release", namespace, "--force"])

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to release namespace:\n\n{output}")]

        return [TextContent(type="text", text=f"✅ Namespace `{namespace}` released\n\n{output}")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_extend(
        namespace: str,
        duration: str = "1h",
    ) -> list[TextContent]:
        """
        Extend an ephemeral namespace reservation.

        Args:
            namespace: Namespace to extend
            duration: Additional time (e.g., "1h", "2h")

        Returns:
            New expiration time.
        """
        success, output = await run_bonfire(["namespace", "extend", namespace, "--duration", duration])

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to extend namespace:\n\n{output}")]

        return [TextContent(type="text", text=f"✅ Namespace `{namespace}` extended by {duration}\n\n{output}")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_namespace_wait(
        namespace: str,
        timeout: int = 300,
    ) -> list[TextContent]:
        """
        Wait for resources to be ready in a namespace.

        Args:
            namespace: Namespace to wait on
            timeout: Timeout in seconds

        Returns:
            Status when ready or timeout.
        """
        success, output = await run_bonfire(
            ["namespace", "wait-on-resources", namespace, "--timeout", str(timeout)],
            timeout=timeout + 60,
        )

        if not success:
            return [TextContent(type="text", text=f"❌ Wait failed:\n\n{output}")]

        return [TextContent(type="text", text=f"✅ Resources ready in `{namespace}`\n\n{output}")]

    # ==================== APPS ====================

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_apps_list(target_env: str = "insights-ephemeral") -> list[TextContent]:
        """
        List all deployable apps.

        Args:
            target_env: Target environment (default: insights-ephemeral)

        Returns:
            List of available apps.
        """
        success, output = await run_bonfire(["apps", "list", "--target-env", target_env])

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to list apps:\n\n{output}")]

        return [TextContent(type="text", text=f"## Deployable Apps\n\n```\n{output}\n```")]

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_apps_dependencies(component: str) -> list[TextContent]:
        """
        Show apps that depend on a component.

        Args:
            component: Component name to check

        Returns:
            List of apps depending on this component.
        """
        success, output = await run_bonfire(["apps", "what-depends-on", component])

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to check dependencies:\n\n{output}")]

        return [TextContent(type="text", text=f"## Apps depending on `{component}`\n\n```\n{output}\n```")]

    # ==================== DEPLOYMENT ====================

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_deploy(
        app: str,
        namespace: str = "",
        source: str = "appsre",
        target_env: str = "insights-ephemeral",
        ref_env: str = "",
        set_image_tag: str = "",
        set_template_ref: str = "",
        component: str = "",
        timeout: int = 600,
        no_get_dependencies: bool = False,
        single_replicas: bool = True,
        reserve: bool = False,
    ) -> list[TextContent]:
        """
        Deploy a ClowdApp to an ephemeral namespace.

        Args:
            app: Application name(s) to deploy (space-separated for multiple)
            namespace: Target namespace (if empty and reserve=False, uses current context)
            source: Config source - "appsre" or "file"
            target_env: Target environment for template params
            ref_env: Reference environment for default refs/IMAGE_TAGs
            set_image_tag: Override image tag format: '<image uri>=<tag>'
            set_template_ref: Override template ref: '<component>=<ref>'
            component: Specific component(s) to deploy
            timeout: Deployment timeout in seconds
            no_get_dependencies: Don't fetch ClowdApp dependencies
            single_replicas: Set all replicas to 1
            reserve: Force reserve a new namespace

        Returns:
            Deployment status.
        """
        apps = app.split() if " " in app else [app]
        args = ["deploy"] + apps

        args.extend(["--source", source])
        args.extend(["--target-env", target_env])
        args.extend(["--timeout", str(timeout)])

        if namespace:
            args.extend(["--namespace", namespace])
        if ref_env:
            args.extend(["--ref-env", ref_env])
        if set_image_tag:
            args.extend(["--set-image-tag", set_image_tag])
        if set_template_ref:
            args.extend(["--set-template-ref", set_template_ref])
        if component:
            args.extend(["--component", component])
        if no_get_dependencies:
            args.append("--no-get-dependencies")
        if single_replicas:
            args.append("--single-replicas")
        if reserve:
            args.append("--reserve")

        success, output = await run_bonfire(args, timeout=timeout + 120)

        if not success:
            return [TextContent(type="text", text=f"❌ Deployment failed:\n\n```\n{output}\n```")]

        display_output = truncate_output(output, 5000, mode="tail")

        lines = [
            f"## ✅ Deployed `{app}`",
            "",
            "```",
            display_output,
            "```",
            "",
            "**Check status:**",
            "- Pods: `kubectl_get_pods(namespace='...', environment='ephemeral')`",
            "- Logs: `kubectl_logs(pod_name='...', namespace='...', environment='ephemeral')`",
        ]

        return [TextContent(type="text", text="\n".join(lines))]

    return registry.count
