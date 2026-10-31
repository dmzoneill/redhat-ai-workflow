"""Bonfire MCP Server - Ephemeral namespace management and ClowdApp deployment (extra tools).

Provides additional tools for managing ephemeral namespaces and deploying apps.
"""

import json
import logging
import re
from pathlib import Path
from typing import TypedDict

from fastmcp import FastMCP
from mcp.types import TextContent

# Setup project path for server imports (must be before server imports)
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization

from server.auto_heal_decorator import auto_heal_ephemeral
from server.tool_registry import ToolRegistry
from server.utils import truncate_output

from .common import aa_deploy_args, deploy_failure_text, get_app_config, get_ephemeral_kubeconfig, run_bonfire

logger = logging.getLogger(__name__)


# ==================== VERSION / INFO ====================


# ==================== TOOL IMPLEMENTATIONS ====================


class IqeCjiOptions(TypedDict):
    """Optional settings for ``bonfire deploy-iqe-cji``."""

    cji_name: str
    marker: str
    filter_expr: str
    env: str


class ProcessOptions(TypedDict):
    """Options for ``bonfire process``."""

    namespace: str
    source: str
    target_env: str
    set_image_tag: str
    component: str
    no_get_dependencies: bool


@auto_heal_ephemeral()
async def _bonfire_apps_list_impl(
    target_env: str = "insights-ephemeral",
) -> list[TextContent]:
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


def _parse_snapshot(snapshot_json: str) -> tuple[str, str]:
    """Extract (template_ref, image_digest) from a Konflux snapshot JSON string or file path.

    Raises:
        ValueError: with a user-facing message when the refs are missing or malformed.
    """
    if snapshot_json.strip().startswith("{"):
        snapshot = json.loads(snapshot_json)
    else:
        # Assume file path
        snapshot = json.loads(Path(snapshot_json).read_text(encoding="utf-8"))

    template_ref = ""
    image_digest = ""
    for comp in snapshot.get("spec", {}).get("components", []):
        container_image = comp.get("containerImage", "")
        if "automation-analytics" in container_image or "your-app-backend" in container_image:
            if "@sha256:" in container_image:
                # Extract the 64-char sha256 digest
                image_digest = container_image.split("@sha256:")[-1]
            template_ref = comp.get("source", {}).get("git", {}).get("revision", "")
            break

    if not template_ref or not image_digest:
        raise ValueError("❌ Could not extract template_ref and sha256 digest from snapshot")
    if len(template_ref) != 40:
        raise ValueError(
            f"❌ Invalid template_ref from snapshot: `{template_ref}` ({len(template_ref)} chars, need 40)"
        )
    if len(image_digest) != 64:
        raise ValueError(
            f"❌ Invalid image digest from snapshot: `{image_digest}` ({len(image_digest)} chars, need 64)"
        )
    return template_ref, image_digest


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
    lines = [f"## Deploy from Snapshot to `{namespace}`", ""]

    try:
        template_ref, image_digest = _parse_snapshot(snapshot_json)
    except json.JSONDecodeError as e:
        return [TextContent(type="text", text=f"❌ Invalid JSON in snapshot: {e}")]
    except OSError as e:
        return [TextContent(type="text", text=f"❌ Failed to read snapshot file: {e}")]
    except (KeyError, TypeError) as e:
        return [TextContent(type="text", text=f"❌ Failed to parse snapshot structure: {e}")]
    except ValueError as e:
        return [TextContent(type="text", text=str(e))]

    lines.append(f"**Template Ref:** `{template_ref}`")
    lines.append(f"**Image Digest:** `{image_digest[:16]}...`")
    lines.append("")

    # Deploy using exact ITS pattern
    app_cfg = get_app_config(billing=billing)
    component = app_cfg["component"]

    deploy_args = aa_deploy_args(app_cfg, namespace, timeout, (template_ref, image_digest))

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

    # Local deploy without image overrides - uses defaults from ref-env
    args = aa_deploy_args(app_cfg, namespace, timeout)

    kubeconfig = get_ephemeral_kubeconfig()
    cmd_preview = f"KUBECONFIG={kubeconfig} bonfire {' '.join(args)}"
    # Log only the bonfire arguments; the kubeconfig path stays out of logs.
    logger.info("Local deploy: bonfire %s", " ".join(args))

    success, output = await run_bonfire(args, timeout=timeout + 120)

    if not success:
        return [TextContent(type="text", text=deploy_failure_text("❌ Local deploy failed", cmd_preview, output))]

    display_output = truncate_output(output, 5000, mode="tail")

    return [
        TextContent(
            type="text",
            text=f"""## ✅ Local Deploy: {app_name} ({"billing" if billing else "main"})

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

    return [
        TextContent(
            type="text",
            text=f"✅ ClowdEnvironment deployed to `{namespace}`\n\n{output}",
        )
    ]


@auto_heal_ephemeral()
async def _bonfire_deploy_iqe_cji_impl(namespace: str, opts: IqeCjiOptions, timeout: int = 600) -> list[TextContent]:
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
    cji_name, marker, filter_expr, env = opts["cji_name"], opts["marker"], opts["filter_expr"], opts["env"]
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

    return [
        TextContent(
            type="text",
            text=f"✅ IQE CJI deployed to `{namespace}`\n\n```\n{output}\n```",
        )
    ]


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
        return [
            TextContent(
                type="text",
                text=f"❌ Deploy with reserve failed:\n\n```\n{output}\n```",
            )
        ]

    display_output = truncate_output(output, 5000, mode="tail")

    return [
        TextContent(
            type="text",
            text=f"## ✅ Reserved & Deployed `{app}`\n\n```\n{display_output}\n```",
        )
    ]


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

    namespace = await _workflow_reserve(duration, lines)
    if not namespace:
        return [TextContent(type="text", text="\n".join(lines))]

    deployed = await _workflow_deploy(namespace, billing, lines)
    if not deployed:
        return [TextContent(type="text", text="\n".join(lines))]

    # Step 3: Run IQE (optional)
    if run_iqe:
        await _workflow_run_iqe(namespace, iqe_marker, lines)

    lines.extend(_workflow_summary(namespace, duration))
    return [TextContent(type="text", text="\n".join(lines))]


async def _workflow_reserve(duration: str, lines: list[str]) -> str | None:
    """Step 1 of the full test workflow: reserve a namespace and return its name."""
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
        return None

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
        return None

    lines.append(f"✅ Reserved: `{namespace}`")
    lines.append("")
    return namespace


async def _workflow_deploy(namespace: str, billing: bool, lines: list[str]) -> bool:
    """Step 2 of the full test workflow: deploy the app; returns True on success."""
    app_cfg = get_app_config(billing=billing)
    component = app_cfg["component"]
    app_name = app_cfg["app_name"]

    lines.append(f"### Step 2: Deploying {app_name} ({component})...")

    deploy_args = aa_deploy_args(app_cfg, namespace, 900)

    success, output = await run_bonfire(deploy_args, timeout=960)

    if not success:
        lines.append(f"❌ Deployment failed:\n```\n{truncate_output(output, 2000, mode='tail')}\n```")
        lines.append(
            f"\n⚠️ Namespace `{namespace}` still reserved. "
            f"Release with: `bonfire_namespace_release(namespace='{namespace}')`"
        )
        return False

    lines.append(f"✅ Deployed `{component}`")
    lines.append("")
    return True


async def _workflow_run_iqe(namespace: str, iqe_marker: str, lines: list[str]) -> None:
    """Step 3 of the full test workflow: deploy the IQE CJI."""
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


def _workflow_summary(namespace: str, duration: str) -> list[str]:
    """Closing summary lines for the full test workflow."""
    lines: list[str] = []
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"**Namespace:** `{namespace}`")
    lines.append(f"**Duration:** {duration}")
    lines.append("")
    lines.append("**Useful commands:**")
    lines.append(f"- Check pods: `kubectl_get_pods(namespace='{namespace}', environment='ephemeral')`")
    lines.append(f"- Get logs: `kubectl_logs(pod_name='...', namespace='{namespace}', environment='ephemeral')`")
    lines.append(f"- Extend time: `bonfire_namespace_extend(namespace='{namespace}', duration='1h')`")
    lines.append(f"- Release: `bonfire_namespace_release(namespace='{namespace}')`")
    return lines


@auto_heal_ephemeral()
async def _bonfire_process_impl(app: str, opts: ProcessOptions) -> list[TextContent]:
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

    args.extend(["--source", opts["source"]])
    args.extend(["--target-env", opts["target_env"]])

    for flag, value in (
        ("--namespace", opts["namespace"]),
        ("--set-image-tag", opts["set_image_tag"]),
        ("--component", opts["component"]),
    ):
        if value:
            args.extend([flag, value])
    if opts["no_get_dependencies"]:
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
    return [
        TextContent(
            type="text",
            text=f"## ClowdEnvironment: `{namespace}`\n\n```yaml\n{output}\n```",
        )
    ]


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
    async def bonfire_apps_list(
        target_env: str = "insights-ephemeral",
    ) -> list[TextContent]:
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
    # MCP tool schema is generated from this signature; parameters are the public tool API.
    # pylint: disable-next=too-many-arguments,too-many-positional-arguments
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
        return await _bonfire_deploy_iqe_cji_impl(
            namespace,
            IqeCjiOptions(cji_name=cji_name, marker=marker, filter_expr=filter_expr, env=env),
            timeout,
        )

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
    # MCP tool schema is generated from this signature; parameters are the public tool API.
    # pylint: disable-next=too-many-arguments,too-many-positional-arguments
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
            app,
            ProcessOptions(
                namespace=namespace,
                source=source,
                target_env=target_env,
                set_image_tag=set_image_tag,
                component=component,
                no_get_dependencies=no_get_dependencies,
            ),
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
