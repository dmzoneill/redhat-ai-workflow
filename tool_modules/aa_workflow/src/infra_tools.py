"""Infrastructure Tools - VPN and Kubernetes connectivity.

Provides tools for:
- vpn_connect: Connect to Red Hat VPN
- kube_login: Authenticate to Kubernetes clusters
"""

import asyncio
import os
from typing import TYPE_CHECKING

from mcp.types import TextContent

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

# Setup project path for server imports
from server.tool_registry import ToolRegistry
from server.utils import load_config, run_cmd_full, run_cmd_shell, truncate_output
from tool_modules.common import PROJECT_ROOT  # noqa: F401 - side effect: adds to sys.path


async def _vpn_connect_impl() -> list[TextContent]:
    """
    Connect to the Red Hat VPN.

    Use this when tools fail with 'No route to host' or similar network errors.

    The VPN is required for:
    - Ephemeral cluster access
    - Stage cluster access
    - Konflux cluster access
    - Internal GitLab access

    Returns:
        VPN connection result.
    """
    config = load_config()
    paths = config.get("paths", {})

    vpn_script = paths.get("vpn_connect_script")
    if not vpn_script:
        vpn_script = os.path.expanduser("~/src/redhatter/src/redhatter_vpn/vpn-connect")

    vpn_script = os.path.expanduser(vpn_script)

    if not os.path.exists(vpn_script):
        return [
            TextContent(
                type="text",
                text=f"""❌ VPN connect script not found at: {vpn_script}

**To fix:**
1. Clone the redhatter repo or ensure the script exists
2. Or add to config.json:
```json
{{
  "paths": {{
    "vpn_connect_script": "/path/to/vpn-connect"
  }}
}}
```

💡 Alternatively, run manually: `vpn-connect` or use your VPN client.""",
            )
        ]

    lines = ["## Connecting to VPN...", ""]

    try:
        success, stdout, stderr = await run_cmd_shell(
            [vpn_script],
            timeout=120,
        )

        output = stdout + stderr

        if success or "successfully activated" in output.lower() or "connection successfully" in output.lower():
            lines.append("✅ VPN connected successfully")
        else:
            lines.append("⚠️ VPN connection may have failed")

        lines.append("")
        lines.append("```")
        lines.append(truncate_output(output, max_length=2000, mode="tail"))
        lines.append("```")

    except asyncio.TimeoutError:
        lines.append("❌ VPN connection timed out after 120s")
        lines.append("Try running manually: `vpn-connect`")
    except Exception as e:
        lines.append(f"❌ Error: {e}")

    return [TextContent(type="text", text="\n".join(lines))]


async def _kube_login_impl(cluster: str) -> list[TextContent]:
    """
    Refresh Kubernetes credentials for a cluster.

    Use this when tools fail with 'Unauthorized', 'token expired', or similar auth errors.

    Args:
        cluster: Cluster to login to:
                 - 's' or 'stage' = Stage cluster
                 - 'p' or 'prod' = Production cluster
                 - 'k' or 'konflux' = Konflux cluster
                 - 'e' or 'ephemeral' = Ephemeral cluster

    Returns:
        Login result with new token info.
    """
    cluster_map = {
        "stage": "s",
        "production": "p",
        "prod": "p",
        "konflux": "k",
        "ephemeral": "e",
    }

    short_cluster = cluster_map.get(cluster.lower(), cluster.lower())

    if short_cluster not in ["s", "p", "k", "e"]:
        return [
            TextContent(
                type="text",
                text=f"""❌ Unknown cluster: {cluster}

**Valid options:**
- `s` or `stage` = Stage cluster
- `p` or `prod` = Production cluster
- `k` or `konflux` = Konflux cluster
- `e` or `ephemeral` = Ephemeral cluster""",
            )
        ]

    cluster_names = {
        "s": "Stage",
        "p": "Production",
        "k": "Konflux",
        "e": "Ephemeral",
    }

    lines = [f"## Logging into {cluster_names[short_cluster]} cluster...", ""]

    kubeconfig_suffix = {
        "s": ".s",
        "p": ".p",
        "k": ".k",
        "e": ".e",
    }
    kubeconfig = os.path.expanduser(f"~/.kube/config{kubeconfig_suffix[short_cluster]}")

    try:
        if os.path.exists(kubeconfig):
            test_success, _, _ = await run_cmd_full(
                ["oc", "--kubeconfig", kubeconfig, "whoami"],
                timeout=10,
            )
            if not test_success:
                lines.append("⚠️ Existing credentials are stale, cleaning up...")
                lines.append("")
                await run_cmd_shell(["kube-clean", short_cluster], timeout=30)

        lines.append("🌐 *A browser window may open for SSO authentication*")
        lines.append("")

        kube_cmd = ["kube", short_cluster]

        success, stdout, stderr = await run_cmd_shell(
            kube_cmd,
            timeout=120,
        )

        output = stdout + stderr

        if success:
            lines.append(f"✅ Logged into {cluster_names[short_cluster]} cluster")
        else:
            lines.append("⚠️ Login may have issues")

        lines.append("")
        lines.append("```")
        lines.append(truncate_output(output, max_length=1500, mode="tail"))
        lines.append("```")

        if os.path.exists(kubeconfig):
            lines.append("")
            lines.append("### Testing connection...")

            test_success, test_out, test_err = await run_cmd_full(
                [
                    "kubectl",
                    "--kubeconfig",
                    kubeconfig,
                    "get",
                    "ns",
                    "--no-headers",
                    "-o",
                    "name",
                ],
                timeout=30,
            )

            if test_success:
                ns_count = len(test_out.strip().split("\n")) if test_out.strip() else 0
                lines.append(f"✅ Connection verified ({ns_count} namespaces accessible)")
            else:
                lines.append(f"⚠️ Connection test failed: {test_err}")

    except FileNotFoundError:
        lines.append("❌ `kube` command not found")
        lines.append("")
        lines.append("The `kube` script should be in your PATH. It typically:")
        lines.append("1. Runs `oc login` with the appropriate cluster URL")
        lines.append("2. Saves credentials to `~/.kube/config.{s,p,k,e}`")
        lines.append("")
        lines.append("**Alternative manual login:**")
        lines.append("```bash")
        lines.append("oc login --server=<cluster-url>")
        lines.append("```")
    except Exception as e:
        lines.append(f"❌ Error: {e}")

    return [TextContent(type="text", text="\n".join(lines))]


def register_infra_tools(server: "FastMCP") -> int:
    """Register infrastructure tools with the MCP server."""
    registry = ToolRegistry(server)

    @registry.tool()
    async def vpn_connect() -> list[TextContent]:
        """
        Connect to the Red Hat VPN.

        Use this when tools fail with 'No route to host' or similar network errors.

        The VPN is required for:
        - Ephemeral cluster access
        - Stage cluster access
        - Konflux cluster access
        - Internal GitLab access

        Returns:
            VPN connection result.
        """
        return await _vpn_connect_impl()

    @registry.tool()
    async def kube_login(cluster: str) -> list[TextContent]:
        """
        Refresh Kubernetes credentials for a cluster.

        Use this when tools fail with 'Unauthorized', 'token expired', or similar auth errors.

        Args:
            cluster: Cluster to login to:
                     - 's' or 'stage' = Stage cluster
                     - 'p' or 'prod' = Production cluster
                     - 'k' or 'konflux' = Konflux cluster
                     - 'e' or 'ephemeral' = Ephemeral cluster

        Returns:
            Login result with new token info.
        """
        return await _kube_login_impl(cluster)

    return registry.count
