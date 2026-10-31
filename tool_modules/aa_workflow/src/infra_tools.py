"""Infrastructure Tools - VPN and Kubernetes connectivity.

Provides tools for:
- vpn_connect: Connect to Red Hat VPN
- kube_login: Authenticate to Kubernetes clusters
"""

import asyncio
import contextlib
import fcntl
import json
import logging
import os
import tempfile
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING

from mcp.types import TextContent

# Setup project path for server imports (must be before server imports)
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization


# Setup project path for server imports
from server.tool_registry import ToolRegistry
from server.utils import load_config, run_cmd_full, run_cmd_shell, truncate_output

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = logging.getLogger(__name__)


# File-based state for VPN connection debouncing
# Uses file lock + timestamp file to coordinate across multiple process/module instances
# Paths are read from config.json "paths" section with fallbacks to /tmp
def _safe_state_path(configured: str) -> Path | None:
    """Return the resolved path if it lies under the temp or home directory."""
    resolved = os.path.realpath(os.path.expanduser(configured))
    for base in (tempfile.gettempdir(), os.path.expanduser("~")):
        root = os.path.realpath(base)
        if resolved.startswith(root + os.sep):
            return Path(resolved)
    return None


def _get_infra_path(key: str, default: str) -> Path:
    """Read an infrastructure file path from config.json with fallback."""
    try:
        config = load_config()
        paths = config.get("paths", {})
        configured = paths.get(key)
        if configured:
            safe = _safe_state_path(str(configured))
            if safe is not None:
                return safe
            logger.warning("Ignoring paths.%s outside temp/home directories: %s", key, configured)
    except (OSError, ValueError, AttributeError) as e:
        logger.debug("Suppressed error in _get_infra_path: %s", e)
    return Path(default)


_tmp = tempfile.gettempdir()
_VPN_LOCK_FILE = _get_infra_path("vpn_lock_file", f"{_tmp}/aa_workflow_vpn.lock")
_VPN_STATE_FILE = _get_infra_path("vpn_state_file", f"{_tmp}/aa_workflow_vpn_state")
_VPN_DEBOUNCE_SECONDS = 30  # Don't reconnect within 30 seconds of last successful connect


def _get_vpn_last_connect_time() -> float:
    """Get the last VPN connect time from shared state file."""
    try:
        if _VPN_STATE_FILE.exists():
            return float(_VPN_STATE_FILE.read_text(encoding="utf-8").strip())
    except (ValueError, OSError) as e:
        logger.debug("Suppressed error in _get_vpn_last_connect_time: %s", e)
    return 0


def _set_vpn_last_connect_time(timestamp: float) -> None:
    """Set the last VPN connect time in shared state file."""
    try:
        _VPN_STATE_FILE.write_text(str(timestamp), encoding="utf-8")
    except OSError as e:
        logger.debug("Suppressed error in _set_vpn_last_connect_time: %s", e)


def _lock_file(path: Path) -> int:
    """Open ``path`` and take an exclusive flock on it (blocking); return the fd."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
    except OSError:
        os.close(fd)
        raise
    return fd


def _unlock_file(fd: int, owner: str) -> None:
    """Release and close a lock taken by _lock_file()."""
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    except OSError as e:
        logger.debug("Suppressed error in %s (lock release): %s", owner, e)


@contextlib.asynccontextmanager
async def _exclusive_lock(path: Path, owner: str) -> AsyncIterator[None]:
    """Hold a cross-process file lock without blocking the event loop.

    The open and the (possibly long) blocking flock run in a worker thread.
    """
    fd = await asyncio.to_thread(_lock_file, path)
    try:
        yield
    finally:
        _unlock_file(fd, owner)


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
    async with _exclusive_lock(_VPN_LOCK_FILE, "_vpn_connect_impl"):
        # Double-check after acquiring lock (another process may have connected)
        time_since_last = time.time() - _get_vpn_last_connect_time()
        if time_since_last < _VPN_DEBOUNCE_SECONDS and await _check_vpn_connected():
            return [
                TextContent(
                    type="text",
                    text=f"✅ VPN already connected (connected {time_since_last:.0f}s ago)",
                )
            ]

        vpn_script = _vpn_script_path()
        if not os.path.exists(vpn_script):
            return [TextContent(type="text", text=_VPN_SCRIPT_MISSING.format(vpn_script=vpn_script))]

        lines = ["## Connecting to VPN...", ""]
        try:
            lines.extend(await _run_vpn_script(vpn_script))
        except asyncio.TimeoutError:
            lines.append("❌ VPN connection timed out after 120s")
            lines.append("Try running manually: `vpn-connect`")
        except (OSError, RuntimeError, ValueError) as e:
            lines.append(f"❌ Error: {e}")

        return [TextContent(type="text", text="\n".join(lines))]


_VPN_SCRIPT_MISSING = """❌ VPN connect script not found at: {vpn_script}

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

💡 Alternatively, run manually: `vpn-connect` or use your VPN client."""


def _vpn_script_path() -> str:
    """Return the configured VPN connect script path, user-expanded."""
    vpn_script = load_config().get("paths", {}).get("vpn_connect_script")
    if not vpn_script:
        vpn_script = os.path.expanduser("~/src/redhatter/src/redhatter_vpn/vpn-connect")
    return os.path.expanduser(vpn_script)


async def _run_vpn_script(vpn_script: str) -> list[str]:
    """Run the VPN script and return result lines, recording a success."""
    success, stdout, stderr = await run_cmd_shell([vpn_script], timeout=120)
    output = stdout + stderr

    # Check for success indicators in output
    output_lower = output.lower()
    is_success = (
        success
        or "successfully activated" in output_lower
        or "connection successfully" in output_lower
        or "already active" in output_lower  # VPN was already connected
    )

    lines = []
    if is_success:
        lines.append("✅ VPN connected successfully")
        # Update last connect time on success (shared state file)
        _set_vpn_last_connect_time(time.time())
    else:
        # Even if script says it may have failed, verify by testing connectivity
        await asyncio.sleep(2)  # Give VPN a moment to establish
        if await _check_vpn_connected():
            lines.append("✅ VPN connected (verified by connectivity check)")
            _set_vpn_last_connect_time(time.time())
        else:
            lines.append("⚠️ VPN connection may have failed")

    lines.extend(["", "```", truncate_output(output, max_length=2000, mode="tail"), "```"])
    return lines


async def _check_vpn_connected() -> bool:
    """Check if VPN is connected by testing connectivity to internal host."""
    try:
        # Try to resolve an internal hostname - this is fast and reliable
        success, stdout, _ = await run_cmd_full(
            ["host", "-W", "2", "gitlab.cee.redhat.com"],
            timeout=5,
            use_shell=False,
        )
        return success and "has address" in stdout
    except (OSError, RuntimeError, ValueError, asyncio.TimeoutError) as e:
        logger.debug("Suppressed error in _check_vpn_connected: %s", e)
        return False


# File-based state for kube_login debouncing (per cluster)
_KUBE_LOCK_FILE = _get_infra_path("kube_lock_file", f"{_tmp}/aa_workflow_kube.lock")
_KUBE_STATE_FILE = _get_infra_path("kube_state_file", f"{_tmp}/aa_workflow_kube_state")
_KUBE_DEBOUNCE_SECONDS = 60  # Don't re-login within 60 seconds of last successful login


def _get_kube_last_login_time(cluster: str) -> float:
    """Get the last kube login time for a cluster from shared state file."""
    try:
        if _KUBE_STATE_FILE.exists():
            state = json.loads(_KUBE_STATE_FILE.read_text(encoding="utf-8"))
            return state.get(cluster, 0)
    except (ValueError, OSError) as e:
        logger.debug("Suppressed error in _get_kube_last_login_time: %s", e)
    return 0


def _set_kube_last_login_time(cluster: str, timestamp: float) -> None:
    """Set the last kube login time for a cluster in shared state file."""
    try:
        state = {}
        if _KUBE_STATE_FILE.exists():
            try:
                state = json.loads(_KUBE_STATE_FILE.read_text(encoding="utf-8"))
            except ValueError as e:
                logger.debug("Suppressed error in _set_kube_last_login_time (read existing): %s", e)
        state[cluster] = timestamp
        _KUBE_STATE_FILE.write_text(json.dumps(state), encoding="utf-8")
    except OSError as e:
        logger.debug("Suppressed error in _set_kube_last_login_time (write): %s", e)


async def _check_kube_connected(cluster: str) -> bool:
    """Check if we're already authenticated to a cluster."""
    kubeconfig_suffix = {"s": ".s", "p": ".p", "k": ".k", "e": ".e"}
    kubeconfig = os.path.expanduser(f"~/.kube/config{kubeconfig_suffix.get(cluster, '')}")

    if not os.path.exists(kubeconfig):
        return False

    try:
        success, _, _ = await run_cmd_full(
            ["oc", "--kubeconfig", kubeconfig, "whoami"],
            timeout=10,
        )
        return success
    except (OSError, RuntimeError, ValueError, asyncio.TimeoutError) as e:
        logger.debug("Suppressed error in _check_kube_connected: %s", e)
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
    short_cluster = _CLUSTER_ALIASES.get(cluster.lower(), cluster.lower())

    if short_cluster not in _CLUSTER_NAMES:
        return [TextContent(type="text", text=_UNKNOWN_CLUSTER.format(cluster=cluster))]

    name = _CLUSTER_NAMES[short_cluster]

    # Check if we recently logged in (debounce) using shared state
    time_since_last = time.time() - _get_kube_last_login_time(short_cluster)
    if time_since_last < _KUBE_DEBOUNCE_SECONDS and await _check_kube_connected(short_cluster):
        return [
            TextContent(
                type="text",
                text=f"✅ Already logged into {name} cluster (logged in {time_since_last:.0f}s ago, debounce active)",
            )
        ]

    # Use file-based lock to prevent multiple simultaneous login attempts
    async with _exclusive_lock(_KUBE_LOCK_FILE, "_kube_login_impl"):
        # Double-check after acquiring lock (another process may have logged in)
        time_since_last = time.time() - _get_kube_last_login_time(short_cluster)
        if time_since_last < _KUBE_DEBOUNCE_SECONDS and await _check_kube_connected(short_cluster):
            return [
                TextContent(
                    type="text",
                    text=f"✅ Already logged into {name} cluster (logged in {time_since_last:.0f}s ago)",
                )
            ]

        lines = [f"## Logging into {name} cluster...", ""]
        kubeconfig = os.path.expanduser(f"~/.kube/config.{short_cluster}")
        try:
            lines.extend(await _run_kube_login(short_cluster, kubeconfig))
            # Always verify connection after login attempt
            lines.extend(["", "### Testing connection..."])
            lines.extend(await _verify_kube_connection(short_cluster, kubeconfig))
        except FileNotFoundError:
            lines.extend(_KUBE_NOT_FOUND_LINES)
        except (OSError, RuntimeError, ValueError, asyncio.TimeoutError) as e:
            lines.append(f"❌ Error: {e}")

        return [TextContent(type="text", text="\n".join(lines))]


_CLUSTER_ALIASES = {
    "stage": "s",
    "production": "p",
    "prod": "p",
    "konflux": "k",
    "ephemeral": "e",
}

_CLUSTER_NAMES = {
    "s": "Stage",
    "p": "Production",
    "k": "Konflux",
    "e": "Ephemeral",
}

_UNKNOWN_CLUSTER = """❌ Unknown cluster: {cluster}

**Valid options:**
- `s` or `stage` = Stage cluster
- `p` or `prod` = Production cluster
- `k` or `konflux` = Konflux cluster
- `e` or `ephemeral` = Ephemeral cluster"""

# Output that means the OAuth token was generated but the login failed
_OAUTH_FAILURE_PATTERNS = (
    "error: login failed",
    "error: the server doesn't have a resource type",
    "error: you must be logged in",
    "error: unauthorized",
    "error: the token provided is invalid",
    "oauth callback error",
    "failed to get token",
    "login error",
)

_KUBE_NOT_FOUND_LINES = (
    "❌ `kube` command not found",
    "",
    "The `kube` script should be in your PATH. It typically:",
    "1. Runs `oc login` with the appropriate cluster URL",
    "2. Saves credentials to `~/.kube/config.{s,p,k,e}`",
    "",
    "**Alternative manual login:**",
    "```bash",
    "oc login --server=<cluster-url>",
    "```",
)


async def _run_kube_login(short_cluster: str, kubeconfig: str) -> list[str]:
    """Clean stale credentials, run ``kube <cluster>`` and describe the result."""
    lines = []
    if os.path.exists(kubeconfig):
        test_success, _, _ = await run_cmd_full(["oc", "--kubeconfig", kubeconfig, "whoami"], timeout=10)
        if not test_success:
            lines.append("⚠️ Existing credentials are stale, cleaning up...")
            lines.append("")
            await run_cmd_shell(["kube-clean", short_cluster], timeout=30)

    lines.append("🌐 *A browser window may open for SSO authentication*")
    lines.append("")

    success, stdout, stderr = await run_cmd_shell(["kube", short_cluster], timeout=120)
    output = stdout + stderr
    oauth_failed = any(pattern in output.lower() for pattern in _OAUTH_FAILURE_PATTERNS)

    if success and not oauth_failed:
        lines.append(f"✅ Logged into {_CLUSTER_NAMES[short_cluster]} cluster")
    elif oauth_failed:
        lines.extend(
            [
                "❌ OAuth authentication failed",
                "",
                "**Common causes:**",
                "1. Browser didn't complete SSO flow",
                "2. OAuth token was generated but callback to cluster failed",
                "3. Network issue during token exchange",
                "",
                "**To fix:**",
                f"1. Try running `kube-clean {short_cluster}` to clear stale tokens",
                f"2. Run `kube {short_cluster}` manually and complete browser SSO",
                "3. Ensure VPN is connected if required",
            ]
        )
    else:
        lines.append("⚠️ Login may have issues")

    lines.extend(["", "```", truncate_output(output, max_length=1500, mode="tail"), "```"])
    return lines


def _diagnose_kube_error(short_cluster: str, test_err: str, test_out: str) -> list[str]:
    """Explain a failed connection test from its error output."""
    test_error = (test_err or test_out or "").lower()
    if "unauthorized" in test_error or "401" in test_error:
        return [
            "**Issue:** Token is invalid or expired",
            "**Fix:** OAuth callback may have failed. Try:",
            f"  1. `kube-clean {short_cluster}`",
            f"  2. `kube {short_cluster}` (complete browser SSO)",
        ]
    if "forbidden" in test_error or "403" in test_error:
        return ["**Issue:** Token valid but lacks permissions", "**Fix:** Check your cluster role bindings"]
    if "no route" in test_error or "connection refused" in test_error:
        return ["**Issue:** Cannot reach cluster API", "**Fix:** Ensure VPN is connected"]
    if "certificate" in test_error:
        return ["**Issue:** TLS certificate error", "**Fix:** Kubeconfig may have stale CA data. Try `kube-clean`"]
    return [f"**Error:** {test_err[:200] if test_err else 'Unknown'}"]


async def _verify_kube_connection(short_cluster: str, kubeconfig: str) -> list[str]:
    """List namespaces with the new kubeconfig and report the outcome."""
    if not os.path.exists(kubeconfig):
        return [f"⚠️ Kubeconfig not found at {kubeconfig}", "Login may not have completed successfully."]

    test_success, test_out, test_err = await run_cmd_full(
        ["kubectl", "--kubeconfig", kubeconfig, "get", "ns", "--no-headers", "-o", "name"],
        timeout=30,
    )
    if test_success:
        ns_count = len(test_out.strip().split("\n")) if test_out.strip() else 0
        # Update last login time on successful verification
        _set_kube_last_login_time(short_cluster, time.time())
        return [f"✅ Connection verified ({ns_count} namespaces accessible)"]

    return [
        "❌ Connection test failed",
        "",
        *_diagnose_kube_error(short_cluster, test_err, test_out),
        "",
        "```",
        truncate_output(test_err or test_out or "No output", max_length=500, mode="tail"),
        "```",
    ]


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
