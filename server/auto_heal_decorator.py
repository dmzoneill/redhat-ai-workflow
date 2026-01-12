"""Auto-heal decorator for MCP tools.

This decorator automatically handles common failures by:
1. Detecting failure patterns in tool output
2. Applying fixes (kube_login, vpn_connect)
3. Retrying the operation
4. Logging failures for learning

Usage:
    from server.auto_heal_decorator import auto_heal

    @auto_heal(cluster="ephemeral")
    @registry.tool()
    async def bonfire_namespace_reserve(duration: str = "4h") -> str:
        ...
"""

import asyncio
import logging
import os
from functools import wraps
from typing import Callable, Literal

logger = logging.getLogger(__name__)

# Error patterns for detection
AUTH_PATTERNS = [
    "unauthorized",
    "401",
    "forbidden",
    "403",
    "token expired",
    "authentication required",
    "not authorized",
    "permission denied",
    "the server has asked for the client to provide credentials",
]

NETWORK_PATTERNS = [
    "no route to host",
    "connection refused",
    "network unreachable",
    "timeout",
    "dial tcp",
    "connection reset",
    "eof",
    "cannot connect",
]

ClusterType = Literal["stage", "prod", "ephemeral", "konflux", "auto"]


def _detect_failure_type(output: str) -> tuple[str | None, str]:
    """Detect failure type from output.

    Returns:
        (failure_type, error_snippet) or (None, "") if no failure
    """
    if not output:
        return None, ""

    output_lower = output.lower()

    # Check for error indicators
    is_error = (
        "❌" in output
        or output_lower.startswith("error")
        or "failed" in output_lower[:200]
        or "exception" in output_lower[:200]
    )

    if not is_error:
        return None, ""

    error_snippet = output[:300]

    # Check auth issues
    if any(p in output_lower for p in AUTH_PATTERNS):
        return "auth", error_snippet

    # Check network issues
    if any(p in output_lower for p in NETWORK_PATTERNS):
        return "network", error_snippet

    return "unknown", error_snippet


def _guess_cluster(tool_name: str, output: str) -> str:
    """Guess which cluster based on tool name and error context."""
    tool_lower = tool_name.lower()
    output_lower = output.lower()

    if "bonfire" in tool_lower or "ephemeral" in output_lower:
        return "ephemeral"
    if "konflux" in tool_lower:
        return "konflux"
    if "prod" in output_lower:
        return "prod"
    return "stage"


async def _run_kube_login(cluster: str) -> bool:
    """Run kube_login fix using kube-clean and kube commands.

    This matches the behavior of the kube_login MCP tool which:
    1. Runs kube-clean to remove stale credentials
    2. Runs kube to refresh the kubeconfig via SSO

    Returns True if successful.
    """
    try:
        from server.utils import run_cmd_full, run_cmd_shell

        # Map cluster names to short codes
        cluster_map = {
            "stage": "s",
            "production": "p",
            "prod": "p",
            "ephemeral": "e",
            "konflux": "k",
        }
        short = cluster_map.get(cluster, cluster)
        if len(short) > 1 and short not in cluster_map.values():
            short = short[0]

        kubeconfig_suffix = {"s": ".s", "p": ".p", "e": ".e", "k": ".k"}
        kubeconfig = os.path.expanduser(f"~/.kube/config{kubeconfig_suffix.get(short, '.s')}")

        # Step 1: Check if existing credentials are stale
        if os.path.exists(kubeconfig):
            test_success, _, _ = await run_cmd_full(
                ["oc", "--kubeconfig", kubeconfig, "whoami"],
                timeout=10,
            )
            if not test_success:
                # Credentials are stale, clean them up first
                logger.info(f"Auto-heal: running kube-clean {short}")
                await run_cmd_shell(["kube-clean", short], timeout=30)

        # Step 2: Run kube command to refresh credentials (opens browser for SSO)
        logger.info(f"Auto-heal: running kube {short}")
        success, stdout, stderr = await run_cmd_shell(
            ["kube", short],
            timeout=120,
        )

        output = stdout + stderr
        if success or "logged in" in output.lower():
            logger.info(f"Auto-heal: kube_login({cluster}) successful")
            return True

        # Fallback: try oc login directly if kube command not found
        if "command not found" in output.lower() or "not found" in output.lower():
            logger.info("Auto-heal: kube command not found, trying oc login")
            success, stdout, stderr = await run_cmd_shell(
                ["oc", "login", f"--kubeconfig={kubeconfig}"],
                timeout=120,
            )
            output = stdout + stderr
            if success or "logged in" in output.lower():
                logger.info(f"Auto-heal: kube_login({cluster}) via oc login successful")
                return True

        logger.warning(f"Auto-heal: kube_login({cluster}) failed: {output[:200]}")
        return False

    except ImportError as e:
        logger.warning(f"Auto-heal: kube_login missing dependency: {e}")
        return False
    except FileNotFoundError as e:
        logger.warning(f"Auto-heal: kube_login({cluster}) command not found: {e}")
        return False
    except OSError as e:
        logger.warning(f"Auto-heal: kube_login({cluster}) OS error: {e}")
        return False


async def _run_vpn_connect() -> bool:
    """Run vpn_connect fix. Returns True if successful."""
    try:
        from server.utils import load_config, run_cmd_shell

        config = load_config()
        paths = config.get("paths", {})
        vpn_script = paths.get("vpn_connect_script")

        if not vpn_script:
            vpn_script = os.path.expanduser("~/src/redhatter/src/redhatter_vpn/vpn-connect")
        else:
            vpn_script = os.path.expanduser(vpn_script)

        if not os.path.exists(vpn_script):
            logger.warning(f"Auto-heal: VPN script not found: {vpn_script}")
            return False

        success, stdout, stderr = await run_cmd_shell(
            [vpn_script],
            timeout=120,
        )

        output = stdout + stderr
        if success or "successfully activated" in output.lower():
            logger.info("Auto-heal: vpn_connect successful")
            return True

        logger.warning(f"Auto-heal: vpn_connect failed: {output[:200]}")
        return False

    except ImportError as e:
        logger.warning(f"Auto-heal: vpn_connect missing dependency: {e}")
        return False
    except OSError as e:
        logger.warning(f"Auto-heal: vpn_connect OS error: {e}")
        return False


def _update_rolling_stats(data: dict, today: str, this_week: str) -> None:
    """Update daily and weekly rolling stats."""
    if "stats" not in data:
        data["stats"] = {}

    # Total counters (only for recent window)
    data["stats"]["total_failures"] = min(data["stats"].get("total_failures", 0) + 1, 1000)
    data["stats"]["auto_fixed"] = min(data["stats"].get("auto_fixed", 0) + 1, 1000)

    # Daily stats
    if "daily" not in data["stats"]:
        data["stats"]["daily"] = {}
    if today not in data["stats"]["daily"]:
        data["stats"]["daily"][today] = {"total": 0, "auto_fixed": 0}
    data["stats"]["daily"][today]["total"] += 1
    data["stats"]["daily"][today]["auto_fixed"] += 1

    # Weekly stats
    if "weekly" not in data["stats"]:
        data["stats"]["weekly"] = {}
    if this_week not in data["stats"]["weekly"]:
        data["stats"]["weekly"][this_week] = {"total": 0, "auto_fixed": 0}
    data["stats"]["weekly"][this_week]["total"] += 1
    data["stats"]["weekly"][this_week]["auto_fixed"] += 1


def _cleanup_old_stats(data: dict) -> None:
    """Remove old stats to keep memory bounded."""
    # Keep only last 30 days of daily stats
    if "daily" in data.get("stats", {}) and len(data["stats"]["daily"]) > 30:
        sorted_days = sorted(data["stats"]["daily"].keys())
        for old_day in sorted_days[:-30]:
            del data["stats"]["daily"][old_day]

    # Keep only last 12 weeks of weekly stats
    if "weekly" in data.get("stats", {}) and len(data["stats"]["weekly"]) > 12:
        sorted_weeks = sorted(data["stats"]["weekly"].keys())
        for old_week in sorted_weeks[:-12]:
            del data["stats"]["weekly"][old_week]

    # Keep only last 100 failure entries
    if len(data.get("failures", [])) > 100:
        data["failures"] = data["failures"][-100:]


async def _log_auto_heal_to_memory(
    tool_name: str,
    failure_type: str,
    error_snippet: str,
    fix_applied: str,
) -> None:
    """Log a successful auto-heal to memory for learning."""
    try:
        from datetime import datetime
        from pathlib import Path

        import yaml

        # Find memory directory
        project_root = Path(__file__).parent.parent
        memory_dir = project_root / "memory" / "learned"
        memory_dir.mkdir(parents=True, exist_ok=True)

        failures_file = memory_dir / "tool_failures.yaml"

        # Load or create
        if failures_file.exists():
            with open(failures_file) as f:
                data = yaml.safe_load(f) or {}
        else:
            data = {"failures": [], "stats": {"total_failures": 0, "auto_fixed": 0, "manual_required": 0}}

        if "failures" not in data:
            data["failures"] = []
        if "stats" not in data:
            data["stats"] = {"total_failures": 0, "auto_fixed": 0, "manual_required": 0}

        # Add entry
        entry = {
            "tool": tool_name,
            "error_type": failure_type,
            "error_snippet": error_snippet[:100],
            "fix_applied": fix_applied,
            "success": True,
            "timestamp": datetime.now().isoformat(),
        }
        data["failures"].append(entry)

        # Update rolling stats
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        this_week = now.strftime("%Y-W%U")

        _update_rolling_stats(data, today, this_week)
        _cleanup_old_stats(data)

        # Write back
        with open(failures_file, "w") as f:
            yaml.dump(data, f, default_flow_style=False)

        logger.debug(f"Logged auto-heal for {tool_name} to memory")

    except Exception as e:
        # Memory logging is best-effort, don't fail the tool
        logger.debug(f"Failed to log auto-heal to memory: {e}")


def _convert_result_to_string(result: any) -> str:
    """Convert tool result to string for pattern matching."""
    if hasattr(result, "__iter__") and not isinstance(result, str):
        # Handle list[TextContent] or similar
        try:
            return str(result[0].text if hasattr(result[0], "text") else result[0])
        except (IndexError, TypeError):
            return str(result)
    return str(result)


async def _apply_auto_heal_fix(failure_type: str, cluster: ClusterType, tool_name: str, result_str: str) -> bool:
    """Apply auto-heal fix based on failure type."""
    if failure_type == "auth":
        target_cluster = cluster if cluster != "auto" else _guess_cluster(tool_name, result_str)
        logger.info(f"Auto-heal: {tool_name} auth failure, running kube_login({target_cluster})")
        return await _run_kube_login(target_cluster)
    elif failure_type == "network":
        logger.info(f"Auto-heal: {tool_name} network failure, running vpn_connect()")
        return await _run_vpn_connect()
    return False


async def _handle_retry_with_heal(
    tool_name: str,
    failure_type: str,
    error_snippet: str,
    cluster: ClusterType,
    result_str: str,
) -> bool:
    """Handle retry with auto-heal fix application and logging."""
    fix_applied = await _apply_auto_heal_fix(failure_type, cluster, tool_name, result_str)

    if not fix_applied:
        logger.warning(f"Auto-heal: fix for {tool_name} failed, giving up")
        return False

    # Log successful fix to memory
    await _log_auto_heal_to_memory(
        tool_name=tool_name,
        failure_type=failure_type,
        error_snippet=error_snippet,
        fix_applied="kube_login" if failure_type == "auth" else "vpn_connect",
    )

    await asyncio.sleep(1)
    return True


def auto_heal(
    cluster: ClusterType = "auto",
    max_retries: int = 1,
    retry_on: list[str] | None = None,
):
    """Decorator that adds auto-healing to MCP tool functions.

    When a tool fails with an auth or network error, this decorator will:
    1. Detect the failure type
    2. Apply the appropriate fix (kube_login or vpn_connect)
    3. Retry the tool call
    4. Log the result

    Args:
        cluster: Cluster hint for auth fixes. "auto" guesses from tool name.
        max_retries: Maximum retry attempts after applying fix (default: 1)
        retry_on: List of failure types to retry on. Default: ["auth", "network"]

    Example:
        @auto_heal(cluster="ephemeral")
        @registry.tool()
        async def bonfire_namespace_reserve(duration: str = "4h") -> str:
            ...
    """
    if retry_on is None:
        retry_on = ["auth", "network"]

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            tool_name = func.__name__
            last_result = None

            for attempt in range(max_retries + 1):
                try:
                    result = await func(*args, **kwargs)
                    last_result = result

                    # Convert result to string for pattern matching
                    result_str = _convert_result_to_string(result)

                    # Check for soft failures (error messages in successful return)
                    failure_type, error_snippet = _detect_failure_type(result_str)

                    if not failure_type:
                        # Success! Return the result
                        return result

                    if failure_type not in retry_on:
                        # Not a retryable failure type
                        logger.debug(f"Auto-heal: {tool_name} failed with non-retryable type: {failure_type}")
                        return result

                    if attempt >= max_retries:
                        # Out of retries
                        logger.warning(f"Auto-heal: {tool_name} failed after {attempt + 1} attempts")
                        return result

                    # Apply fix and log
                    fix_success = await _handle_retry_with_heal(
                        tool_name, failure_type, error_snippet, cluster, result_str
                    )

                    if not fix_success:
                        return result
                    logger.info(f"Auto-heal: retrying {tool_name} (attempt {attempt + 2}/{max_retries + 1})")

                except Exception as e:
                    # Handle exceptions (not just error messages in output)
                    error_str = str(e)
                    failure_type, _ = _detect_failure_type(error_str)

                    if failure_type in retry_on and attempt < max_retries:
                        fix_applied = await _apply_auto_heal_fix(failure_type, cluster, tool_name, error_str)
                        if fix_applied:
                            await asyncio.sleep(1)
                            continue

                    # Re-raise if we can't fix
                    raise

            return last_result

        # Mark the function as auto-heal enabled for introspection
        wrapper.__dict__["_auto_heal_enabled"] = True
        wrapper.__dict__["_auto_heal_cluster"] = cluster
        wrapper.__dict__["_auto_heal_max_retries"] = max_retries

        return wrapper

    return decorator


# Convenience decorators for common cases
def auto_heal_ephemeral(max_retries: int = 1):
    """Auto-heal decorator pre-configured for ephemeral cluster tools."""
    return auto_heal(cluster="ephemeral", max_retries=max_retries)


def auto_heal_stage(max_retries: int = 1):
    """Auto-heal decorator pre-configured for stage cluster tools."""
    return auto_heal(cluster="stage", max_retries=max_retries)


def auto_heal_konflux(max_retries: int = 1):
    """Auto-heal decorator pre-configured for Konflux cluster tools."""
    return auto_heal(cluster="konflux", max_retries=max_retries)
