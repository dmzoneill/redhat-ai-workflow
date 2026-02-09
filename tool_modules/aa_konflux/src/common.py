"""Shared helpers for Konflux tool modules.

Extracted from tools_basic.py and tools_extra.py to eliminate duplication (DUP-004).
"""

import os
from typing import cast

from server.utils import get_kubeconfig, load_config
from server.utils import run_cmd as run_cmd_base


def get_konflux_config() -> dict:
    """Get Konflux configuration."""
    config = load_config()
    return cast(dict, config.get("konflux", {}))


def get_konflux_kubeconfig() -> str:
    """Get kubeconfig for Konflux cluster from config or default."""
    kubeconfig = get_konflux_config().get("kubeconfig")
    if kubeconfig:
        return os.path.expanduser(kubeconfig)
    # Fall back to get_kubeconfig which uses config.json namespaces section
    return get_kubeconfig("konflux")


# Cached kubeconfig for module-level default
KONFLUX_KUBECONFIG = get_konflux_kubeconfig()
DEFAULT_NAMESPACE = os.getenv("KONFLUX_NAMESPACE", "default")


async def run_konflux_cmd(
    cmd: list[str], kubeconfig: str | None = None, timeout: int = 60
) -> tuple[bool, str]:
    """Run command with Konflux kubeconfig.

    Args:
        cmd: Command and arguments
        kubeconfig: Optional kubeconfig path (defaults to Konflux kubeconfig)
        timeout: Timeout in seconds

    Returns:
        Tuple of (success, output)
    """
    kc = kubeconfig or KONFLUX_KUBECONFIG
    env = {"KUBECONFIG": kc}
    return await run_cmd_base(cmd, env=env, timeout=timeout)


# Backward compatibility alias
run_cmd = run_konflux_cmd
