"""Bonfire MCP Server - Ephemeral namespace management and ClowdApp deployment.

Provides 21 tools for managing ephemeral namespaces and deploying apps.
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


# ==================== TOOL IMPLEMENTATIONS ====================


@auto_heal_ephemeral()
async def _bonfire_apps_list_impl(target_env: str = "insights-ephemeral") -> list[TextContent]:
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
async def _bonfire_deploy_aa_from_snapshot_impl(
    namespace: str,
    snapshot_json: str,
    billing: bool = False,
    timeout: int = 900,
) -> list[TextContent]:
    """
    Deploy Automation Analytics using Konflux snapshot data.

    Parses the snapshot to extract template_ref and image_tag, then deploys
    using the exact ITS bonfire command pattern.

    Args:
        namespace: Target ephemeral namespace
        snapshot_json: JSON string from Konflux snapshot (spec.components)
        billing: If True, deploy billing component
        timeout: Deployment timeout

    Returns:
        Deployment status.
    """
    import json as json_module

    lines = [f"## Deploy from Snapshot to `{namespace}`", ""]

    try:
        # Parse JSON
        if snapshot_json.strip().startswith("{"):
            snapshot = json_module.loads(snapshot_json)
        else:
            # Assume file path
            with open(snapshot_json) as f:
                snapshot = json_module.load(f)

        # Extract components
        components = snapshot.get("spec", {}).get("components", [])

        template_ref = None
        image_digest = None

        for comp in components:
            container_image = comp.get("containerImage", "")
            if "automation-analytics" in container_image or "your-app-backend" in container_image:
                if "@sha256:" in container_image:
                    # Extract the 64-char sha256 digest
                    image_digest = container_image.split("@sha256:")[-1]
                template_ref = comp.get("source", {}).get("git", {}).get("revision", "")
                break

        if not template_ref or not image_digest:
            return [
                TextContent(
                    type="text",
                    text="❌ Could not extract template_ref and sha256 digest from snapshot",
                )
            ]

        # Validate lengths
        if len(template_ref) != 40:
            return [
                TextContent(
                    type="text",
                    text=(
                        f"❌ Invalid template_ref from snapshot: "
                        f"`{template_ref}` ({len(template_ref)} chars, need 40)"
                    ),
                )
            ]

        if len(image_digest) != 64:
            return [
                TextContent(
                    type="text",
                    text=(
                        f"❌ Invalid image digest from snapshot: "
                        f"`{image_digest}` ({len(image_digest)} chars, need 64)"
                    ),
                )
            ]

        lines.append(f"**Template Ref:** `{template_ref}`")
        lines.append(f"**Image Digest:** `{image_digest[:16]}...`")
        lines.append("")

    except json_module.JSONDecodeError as e:
        return [TextContent(type="text", text=f"❌ Invalid JSON in snapshot: {e}")]
    except OSError as e:
        return [TextContent(type="text", text=f"❌ Failed to read snapshot file: {e}")]
    except (KeyError, TypeError) as e:
        return [TextContent(type="text", text=f"❌ Failed to parse snapshot structure: {e}")]

    # Deploy using exact ITS pattern
    app_cfg = get_app_config(billing=billing)
    component = app_cfg["component"]
    app_name = app_cfg["app_name"]
    ref_env = app_cfg["ref_env"]
    image_base = app_cfg.get("image_base", "")

    # Exact ITS command pattern
    deploy_args = [
        "deploy",
        "--source=appsre",
        "--ref-env",
        ref_env,
        "--namespace",
        namespace,
        "--timeout",
        str(timeout),
        "--optional-deps-method",
        "hybrid",
        "--frontends",
        "false",
        "--component",
        component,
        "--no-remove-resources",
        "all",
        "--set-template-ref",
        f"{component}={template_ref}",
        "--set-parameter",
        f"{component}/IMAGE={image_base}@sha256",
        "--set-parameter",
        f"{component}/IMAGE_TAG={image_digest}",
        app_name,
    ]

    kubeconfig = get_ephemeral_kubeconfig()
    cmd_preview = f"KUBECONFIG={kubeconfig} bonfire {' '.join(deploy_args)}"

    lines.append("### Deploying...")
    lines.append(f"```bash\n{cmd_preview}\n```")
    lines.append("")

    success, output = await run_bonfire(deploy_args, timeout=timeout + 60)

    if not success:
        lines.append(f"❌ Deployment failed:\n```\n{truncate_output(output, 2000, mode='tail')}\n```")
    else:
        lines.append(f"✅ Deployed `{component}` from snapshot!")
        lines.append(f"\n**Namespace:** `{namespace}`")

    return [TextContent(type="text", text="\n".join(lines))]


@auto_heal_ephemeral()
async def _bonfire_deploy_aa_local_impl(
    namespace: str,
    billing: bool = False,
    timeout: int = 900,
) -> list[TextContent]:
    """
    Deploy Automation Analytics for local development (uses default refs from ref-env).

    This is for quick local testing without specifying a specific commit.
    For MR testing, use bonfire_deploy_aa with specific template_ref and image_tag.

    Args:
        namespace: Target ephemeral namespace
        billing: If True, deploy tower-analytics-billing-clowdapp
        timeout: Deployment timeout

    Returns:
        Deployment status.
    """
    # Load app config from config.json
    app_cfg = get_app_config(billing=billing)
    component = app_cfg["component"]
    app_name = app_cfg["app_name"]
    ref_env = app_cfg["ref_env"]

    # Local deploy without image overrides - uses defaults from ref-env
    args = [
        "deploy",
        "--source=appsre",
        "--ref-env",
        ref_env,
        "--namespace",
        namespace,
        "--timeout",
        str(timeout),
        "--optional-deps-method",
        "hybrid",
        "--frontends",
        "false",
        "--component",
        component,
        "--no-remove-resources",
        "all",
        app_name,
    ]

    kubeconfig = get_ephemeral_kubeconfig()
    cmd_preview = f"KUBECONFIG={kubeconfig} bonfire {' '.join(args)}"
    logger.info(f"Local deploy: {cmd_preview}")

    success, output = await run_bonfire(args, timeout=timeout + 120)

    if not success:
        return [
            TextContent(
                type="text",
                text=f"""❌ Local deploy failed

**Command:**
```bash
{cmd_preview}
```

**Output:**
```
{output}
```""",
            )
        ]

    display_output = truncate_output(output, 5000, mode="tail")

    return [
        TextContent(
            type="text",
            text=f"""## ✅ Local Deploy: {app_name} ({'billing' if billing else 'main'})

**Namespace:** `{namespace}`
**Component:** `{component}`

**Command:**
```bash
{cmd_preview}
```

**Output:**
```
{display_output}
```""",
        )
    ]


@auto_heal_ephemeral()
async def _bonfire_deploy_env_impl(
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
async def _bonfire_deploy_iqe_cji_impl(
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
async def _bonfire_deploy_with_reserve_impl(
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


@auto_heal_ephemeral()
async def _bonfire_full_test_workflow_impl(
    duration: str = "2h",
    billing: bool = False,
    run_iqe: bool = True,
    iqe_marker: str = "smoke",
) -> list[TextContent]:
    """
    Complete test workflow: reserve namespace, deploy AA, optionally run IQE.

    Args:
        duration: Namespace reservation duration
        billing: If True, deploy billing component
        run_iqe: If True, also deploy IQE CJI after app deploy
        iqe_marker: pytest marker for IQE tests (e.g., "smoke", "regression")

    Returns:
        Workflow status with namespace info.
    """
    lines = ["## 🚀 Full Test Workflow", ""]

    # Step 1: Reserve namespace
    lines.append("### Step 1: Reserving namespace...")
    reserve_args = [
        "namespace",
        "reserve",
        "--duration",
        duration,
        "--pool",
        "default",
        "--timeout",
        "600",
        "--force",
    ]

    success, output = await run_bonfire(reserve_args, timeout=660)

    if not success:
        lines.append(f"❌ Failed to reserve namespace:\n```\n{output}\n```")
        return [TextContent(type="text", text="\n".join(lines))]

    # Try to extract namespace from output
    namespace = None
    for line in output.split("\n"):
        if "ephemeral-" in line.lower():
            match = re.search(r"(ephemeral-[a-z0-9]+)", line.lower())
            if match:
                namespace = match.group(1)
                break

    if not namespace:
        lines.append(f"⚠️ Namespace reserved but couldn't parse name:\n```\n{output}\n```")
        return [TextContent(type="text", text="\n".join(lines))]

    lines.append(f"✅ Reserved: `{namespace}`")
    lines.append("")

    # Step 2: Deploy the app
    app_cfg = get_app_config(billing=billing)
    component = app_cfg["component"]
    app_name = app_cfg["app_name"]
    ref_env = app_cfg["ref_env"]

    lines.append(f"### Step 2: Deploying {app_name} ({component})...")

    deploy_args = [
        "deploy",
        "--source=appsre",
        "--ref-env",
        ref_env,
        "--namespace",
        namespace,
        "--timeout",
        "900",
        "--optional-deps-method",
        "hybrid",
        "--frontends",
        "false",
        "--component",
        component,
        "--no-remove-resources",
        "all",
        app_name,
    ]

    success, output = await run_bonfire(deploy_args, timeout=960)

    if not success:
        lines.append(f"❌ Deployment failed:\n```\n{truncate_output(output, 2000, mode='tail')}\n```")
        lines.append(
            f"\n⚠️ Namespace `{namespace}` still reserved. "
            f"Release with: `bonfire_namespace_release(namespace='{namespace}')`"
        )
        return [TextContent(type="text", text="\n".join(lines))]

    lines.append(f"✅ Deployed `{component}`")
    lines.append("")

    # Step 3: Run IQE (optional)
    if run_iqe:
        lines.append(f"### Step 3: Running IQE tests (marker: {iqe_marker})...")

        iqe_args = [
            "deploy-iqe-cji",
            "--namespace",
            namespace,
            "--timeout",
            "600",
        ]
        if iqe_marker:
            iqe_args.extend(["--marker", iqe_marker])

        success, output = await run_bonfire(iqe_args, timeout=660)

        if not success:
            truncated = truncate_output(output, 1000, mode="tail")
            lines.append(f"⚠️ IQE deployment failed (app is still running):\n```\n{truncated}\n```")
        else:
            lines.append("✅ IQE CJI deployed")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"**Namespace:** `{namespace}`")
    lines.append(f"**Duration:** {duration}")
    lines.append("")
    lines.append("**Useful commands:**")
    lines.append(f"- Check pods: `kubectl_get_pods(namespace='{namespace}', environment='ephemeral')`")
    lines.append(f"- Get logs: `kubectl_logs(pod_name='...', " f"namespace='{namespace}', environment='ephemeral')`")
    lines.append(f"- Extend time: `bonfire_namespace_extend(namespace='{namespace}', duration='1h')`")
    lines.append(f"- Release: `bonfire_namespace_release(namespace='{namespace}')`")

    return [TextContent(type="text", text="\n".join(lines))]


@auto_heal_ephemeral()
async def _bonfire_process_impl(
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


@auto_heal_ephemeral()
async def _bonfire_process_env_impl(namespace: str) -> list[TextContent]:
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


@auto_heal_ephemeral()
async def _bonfire_process_iqe_cji_impl(
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


def register_tools(server: "FastMCP") -> int:
    """Register tools with the MCP server."""
    registry = ToolRegistry(server)

    # ==================== TOOLS NOT USED IN SKILLS ====================
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
        return await _bonfire_apps_list_impl(target_env)

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_deploy_aa_from_snapshot(
        namespace: str,
        snapshot_json: str,
        billing: bool = False,
        timeout: int = 900,
    ) -> list[TextContent]:
        """
        Deploy Automation Analytics using Konflux snapshot data.

        Parses the snapshot to extract template_ref and image_tag, then deploys
        using the exact ITS bonfire command pattern.

        Args:
            namespace: Target ephemeral namespace
            snapshot_json: JSON string from Konflux snapshot (spec.components)
            billing: If True, deploy billing component
            timeout: Deployment timeout

        Returns:
            Deployment status.
        """
        return await _bonfire_deploy_aa_from_snapshot_impl(namespace, snapshot_json, billing, timeout)

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_deploy_aa_local(
        namespace: str,
        billing: bool = False,
        timeout: int = 900,
    ) -> list[TextContent]:
        """
        Deploy Automation Analytics for local development (uses default refs from ref-env).

        This is for quick local testing without specifying a specific commit.
        For MR testing, use bonfire_deploy_aa with specific template_ref and image_tag.

        Args:
            namespace: Target ephemeral namespace
            billing: If True, deploy tower-analytics-billing-clowdapp
            timeout: Deployment timeout

        Returns:
            Deployment status.
        """
        return await _bonfire_deploy_aa_local_impl(namespace, billing, timeout)

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
        return await _bonfire_deploy_env_impl(namespace, timeout)

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
        return await _bonfire_deploy_iqe_cji_impl(namespace, cji_name, marker, filter_expr, env, timeout)

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
        return await _bonfire_deploy_with_reserve_impl(app, duration, pool, requester, timeout)

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_full_test_workflow(
        duration: str = "2h",
        billing: bool = False,
        run_iqe: bool = True,
        iqe_marker: str = "smoke",
    ) -> list[TextContent]:
        """
        Complete test workflow: reserve namespace, deploy AA, optionally run IQE.

        Args:
            duration: Namespace reservation duration
            billing: If True, deploy billing component
            run_iqe: If True, also deploy IQE CJI after app deploy
            iqe_marker: pytest marker for IQE tests (e.g., "smoke", "regression")

        Returns:
            Workflow status with namespace info.
        """
        return await _bonfire_full_test_workflow_impl(duration, billing, run_iqe, iqe_marker)

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
        return await _bonfire_process_impl(
            app, namespace, source, target_env, set_image_tag, component, no_get_dependencies
        )

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
        return await _bonfire_process_env_impl(namespace)

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
        return await _bonfire_process_iqe_cji_impl(namespace, marker, filter_expr)

    return registry.count
