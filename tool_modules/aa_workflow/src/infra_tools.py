"""Infrastructure Tools - VPN and Kubernetes connectivity.

Provides tools for:
- vpn_connect: Connect to Red Hat VPN
- kube_login: Authenticate to Kubernetes clusters
"""

import asyncio
import fcntl
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

from mcp.types import TextContent

if TYPE_CHECKING:
    from fastmcp import FastMCP

# Setup project path for server imports (must be before server imports)
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization


# Setup project path for server imports
from server.tool_registry import ToolRegistry
from server.utils import load_config, run_cmd_full, run_cmd_shell, truncate_output

# File-based state for VPN connection debouncing
# Uses file lock + timestamp file to coordinate across multiple process/module instances
_VPN_LOCK_FILE = Path("/tmp/aa_workflow_vpn.lock")
_VPN_STATE_FILE = Path("/tmp/aa_workflow_vpn_state")
_VPN_DEBOUNCE_SECONDS = (
    30  # Don't reconnect within 30 seconds of last successful connect
)


def _get_vpn_last_connect_time() -> float:
    """Get the last VPN connect time from shared state file."""
    try:
        if _VPN_STATE_FILE.exists():
            return float(_VPN_STATE_FILE.read_text().strip())
    except (ValueError, OSError):
        pass
    return 0


def _set_vpn_last_connect_time(timestamp: float) -> None:
    """Set the last VPN connect time in shared state file."""
    try:
        _VPN_STATE_FILE.write_text(str(timestamp))
    except OSError:
        pass


async def _vpn_connect_impl() -> list[TextContent]:
    """
    Connect to the Red Hat VPN.

    Use this when tools fail with 'No route to host' or similar network errors.

    The VPN is required for:
    - Ephemeral cluster access
    - Stage cluster access
    - Konflux cluster access
    - Internal GitLab access

    This function is debounced - if called multiple times within 30 seconds,
    subsequent calls will return immediately with success (assuming VPN is connected).

    Uses file-based locking to coordinate across multiple processes/module instances.

    Returns:
        VPN connection result.
    """
    # Check if VPN was recently connected (debounce) using shared state
    last_connect = _get_vpn_last_connect_time()
    time_since_last = time.time() - last_connect
    if time_since_last < _VPN_DEBOUNCE_SECONDS:
        # Check if VPN is actually connected by testing connectivity
        is_connected = await _check_vpn_connected()
        if is_connected:
            return [
                TextContent(
                    type="text",
                    text=f"✅ VPN already connected (connected {time_since_last:.0f}s ago, debounce active)",
                )
            ]

    # Use file-based lock to prevent multiple simultaneous connection attempts
    # This works across different processes and module instances
    lock_fd = None
    try:
        lock_fd = open(_VPN_LOCK_FILE, "w")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)  # Exclusive lock, blocks until acquired

        # Double-check after acquiring lock (another process may have connected)
        last_connect = _get_vpn_last_connect_time()
        time_since_last = time.time() - last_connect
        if time_since_last < _VPN_DEBOUNCE_SECONDS:
            is_connected = await _check_vpn_connected()
            if is_connected:
                return [
                    TextContent(
                        type="text",
                        text=f"✅ VPN already connected (connected {time_since_last:.0f}s ago)",
                    )
                ]

        config = load_config()
        paths = config.get("paths", {})

        vpn_script = paths.get("vpn_connect_script")
        if not vpn_script:
            vpn_script = os.path.expanduser(
                "~/src/redhatter/src/redhatter_vpn/vpn-connect"
            )

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

            # Check for success indicators in output
            output_lower = output.lower()
            is_success = (
                success
                or "successfully activated" in output_lower
                or "connection successfully" in output_lower
                or "already active" in output_lower  # VPN was already connected
            )

            if is_success:
                lines.append("✅ VPN connected successfully")
                # Update last connect time on success (shared state file)
                _set_vpn_last_connect_time(time.time())
            else:
                # Even if script says it may have failed, verify by testing connectivity
                await asyncio.sleep(2)  # Give VPN a moment to establish
                is_connected = await _check_vpn_connected()
                if is_connected:
                    lines.append("✅ VPN connected (verified by connectivity check)")
                    _set_vpn_last_connect_time(time.time())
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

    finally:
        # Release the file lock
        if lock_fd:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                lock_fd.close()
            except Exception:
                pass


async def _check_vpn_connected() -> bool:
    """Check if VPN is connected by testing connectivity to internal host."""
    try:
        # Try to resolve an internal hostname - this is fast and reliable
        success, stdout, stderr = await run_cmd_full(
            ["host", "-W", "2", "gitlab.cee.redhat.com"],
            timeout=5,
            use_shell=False,
        )
        return success and "has address" in stdout
    except Exception:
        return False


# File-based state for kube_login debouncing (per cluster)
_KUBE_LOCK_FILE = Path("/tmp/aa_workflow_kube.lock")
_KUBE_STATE_FILE = Path("/tmp/aa_workflow_kube_state")
_KUBE_DEBOUNCE_SECONDS = 60  # Don't re-login within 60 seconds of last successful login


def _get_kube_last_login_time(cluster: str) -> float:
    """Get the last kube login time for a cluster from shared state file."""
    try:
        if _KUBE_STATE_FILE.exists():
            import json

            state = json.loads(_KUBE_STATE_FILE.read_text())
            return state.get(cluster, 0)
    except (ValueError, OSError, json.JSONDecodeError):
        pass
    return 0


def _set_kube_last_login_time(cluster: str, timestamp: float) -> None:
    """Set the last kube login time for a cluster in shared state file."""
    try:
        import json

        state = {}
        if _KUBE_STATE_FILE.exists():
            try:
                state = json.loads(_KUBE_STATE_FILE.read_text())
            except (json.JSONDecodeError, ValueError):
                pass
        state[cluster] = timestamp
        _KUBE_STATE_FILE.write_text(json.dumps(state))
    except OSError:
        pass


async def _check_kube_connected(cluster: str) -> bool:
    """Check if we're already authenticated to a cluster."""
    kubeconfig_suffix = {"s": ".s", "p": ".p", "k": ".k", "e": ".e"}
    kubeconfig = os.path.expanduser(
        f"~/.kube/config{kubeconfig_suffix.get(cluster, '')}"
    )

    if not os.path.exists(kubeconfig):
        return False

    try:
        success, _, _ = await run_cmd_full(
            ["oc", "--kubeconfig", kubeconfig, "whoami"],
            timeout=10,
        )
        return success
    except Exception:
        return False


async def _kube_login_impl(cluster: str) -> list[TextContent]:
    """
    Refresh Kubernetes credentials for a cluster.

    Use this when tools fail with 'Unauthorized', 'token expired', or similar auth errors.

    Uses file-based locking to coordinate across multiple processes/module instances.

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
                text="""❌ Unknown cluster: {cluster}

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

    # Check if we recently logged in (debounce) using shared state
    last_login = _get_kube_last_login_time(short_cluster)
    time_since_last = time.time() - last_login
    if time_since_last < _KUBE_DEBOUNCE_SECONDS:
        # Check if we're actually authenticated
        is_connected = await _check_kube_connected(short_cluster)
        if is_connected:
            return [
                TextContent(
                    type="text",
                    text=(
                        f"✅ Already logged into {cluster_names[short_cluster]} cluster"
                        f" (logged in {time_since_last:.0f}s ago, debounce active)"
                    ),
                )
            ]

    # Use file-based lock to prevent multiple simultaneous login attempts
    lock_fd = None
    try:
        lock_fd = open(_KUBE_LOCK_FILE, "w")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)  # Exclusive lock, blocks until acquired

        # Double-check after acquiring lock (another process may have logged in)
        last_login = _get_kube_last_login_time(short_cluster)
        time_since_last = time.time() - last_login
        if time_since_last < _KUBE_DEBOUNCE_SECONDS:
            is_connected = await _check_kube_connected(short_cluster)
            if is_connected:
                return [
                    TextContent(
                        type="text",
                        text=(
                            f"✅ Already logged into {cluster_names[short_cluster]} cluster"
                            f" (logged in {time_since_last:.0f}s ago)"
                        ),
                    )
                ]

        lines = [f"## Logging into {cluster_names[short_cluster]} cluster...", ""]

        kubeconfig_suffix = {
            "s": ".s",
            "p": ".p",
            "k": ".k",
            "e": ".e",
        }
        kubeconfig = os.path.expanduser(
            f"~/.kube/config{kubeconfig_suffix[short_cluster]}"
        )

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

            # Detect OAuth callback failures - token generated but login failed
            oauth_failure_patterns = [
                "error: login failed",
                "error: the server doesn't have a resource type",
                "error: you must be logged in",
                "error: unauthorized",
                "error: the token provided is invalid",
                "oauth callback error",
                "failed to get token",
                "login error",
            ]
            oauth_failed = any(
                pattern in output.lower() for pattern in oauth_failure_patterns
            )

            login_success = False
            if success and not oauth_failed:
                lines.append(f"✅ Logged into {cluster_names[short_cluster]} cluster")
                login_success = True  # noqa: F841
            elif oauth_failed:
                lines.append("❌ OAuth authentication failed")
                lines.append("")
                lines.append("**Common causes:**")
                lines.append("1. Browser didn't complete SSO flow")
                lines.append(
                    "2. OAuth token was generated but callback to cluster failed"
                )
                lines.append("3. Network issue during token exchange")
                lines.append("")
                lines.append("**To fix:**")
                lines.append(
                    "1. Try running `kube-clean {short_cluster}` to clear stale tokens"
                )
                lines.append(
                    "2. Run `kube {short_cluster}` manually and complete browser SSO"
                )
                lines.append("3. Ensure VPN is connected if required")
            else:
                lines.append("⚠️ Login may have issues")

            lines.append("")
            lines.append("```")
            lines.append(truncate_output(output, max_length=1500, mode="tail"))
            lines.append("```")

            # Always verify connection after login attempt
            lines.append("")
            lines.append("### Testing connection...")

            if os.path.exists(kubeconfig):
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
                    ns_count = (
                        len(test_out.strip().split("\n")) if test_out.strip() else 0
                    )
                    lines.append(
                        f"✅ Connection verified ({ns_count} namespaces accessible)"
                    )
                    # Update last login time on successful verification
                    _set_kube_last_login_time(short_cluster, time.time())
                else:
                    # Detailed error analysis for connection test failure
                    test_error = (test_err or test_out or "").lower()
                    lines.append("❌ Connection test failed")
                    lines.append("")

                    if "unauthorized" in test_error or "401" in test_error:
                        lines.append("**Issue:** Token is invalid or expired")
                        lines.append("**Fix:** OAuth callback may have failed. Try:")
                        lines.append(f"  1. `kube-clean {short_cluster}`")
                        lines.append(
                            f"  2. `kube {short_cluster}` (complete browser SSO)"
                        )
                    elif "forbidden" in test_error or "403" in test_error:
                        lines.append("**Issue:** Token valid but lacks permissions")
                        lines.append("**Fix:** Check your cluster role bindings")
                    elif "no route" in test_error or "connection refused" in test_error:
                        lines.append("**Issue:** Cannot reach cluster API")
                        lines.append("**Fix:** Ensure VPN is connected")
                    elif "certificate" in test_error:
                        lines.append("**Issue:** TLS certificate error")
                        lines.append(
                            "**Fix:** Kubeconfig may have stale CA data. Try `kube-clean`"
                        )
                    else:
                        lines.append(
                            f"**Error:** {test_err[:200] if test_err else 'Unknown'}"
                        )

                    lines.append("")
                    lines.append("```")
                    lines.append(
                        truncate_output(
                            test_err or test_out or "No output",
                            max_length=500,
                            mode="tail",
                        )
                    )
                    lines.append("```")
            else:
                lines.append(f"⚠️ Kubeconfig not found at {kubeconfig}")
                lines.append("Login may not have completed successfully.")

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

    finally:
        # Release the file lock
        if lock_fd:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                lock_fd.close()
            except Exception:
                pass


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
