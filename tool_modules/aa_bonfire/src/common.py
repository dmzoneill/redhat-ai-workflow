"""Shared helpers for Bonfire tool modules.

Extracted from tools_basic.py and tools_extra.py to eliminate duplication (DUP-004).
"""

import logging

from server.utils import (
    ensure_cluster_auth,
    get_kubeconfig,
    get_section_config,
    run_cmd,
)

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
            "quay.io/redhat-user-workloads/aap-aa-tenant/"
            "aap-aa-main/automation-analytics-backend-main",
        ),
        "ref_env": config.get("ref_env", "insights-production"),
    }


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

    # Build env with KUBECONFIG
    run_env = {"KUBECONFIG": kubeconfig}
    if env:
        run_env.update(env)

    # Use unified run_cmd
    return await run_cmd(cmd, env=run_env, timeout=timeout)
