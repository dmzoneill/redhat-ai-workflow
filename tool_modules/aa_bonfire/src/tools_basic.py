"""Bonfire MCP Server - Ephemeral namespace management and ClowdApp deployment.

Provides 21 tools for managing ephemeral namespaces and deploying apps.
"""

import logging
from typing import TypedDict

from fastmcp import FastMCP
from mcp.types import TextContent

# Setup project path for server imports (must be before server imports)
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization

from server.auto_heal_decorator import auto_heal_ephemeral
from server.tool_registry import ToolRegistry
from server.utils import run_cmd, truncate_output

from .common import aa_deploy_args, deploy_failure_text, get_app_config, get_ephemeral_kubeconfig, run_bonfire

logger = logging.getLogger(__name__)


# ==================== VERSION / INFO ====================


# ==================== TOOL IMPLEMENTATIONS ====================


async def _bonfire_apps_dependencies_impl(component: str) -> list[TextContent]:
    """Implementation of bonfire_apps_dependencies tool."""
    success, output = await run_bonfire(["apps", "what-depends-on", component])

    if not success:
        return [TextContent(type="text", text=f"❌ Failed to check dependencies:\n\n{output}")]

    return [
        TextContent(
            type="text",
            text=f"## Apps depending on `{component}`\n\n```\n{output}\n```",
        )
    ]


class DeployOptions(TypedDict):
    """Options for ``bonfire deploy`` (mirrors the bonfire_deploy tool parameters)."""

    namespace: str
    source: str
    target_env: str
    ref_env: str
    set_image_tag: str
    set_template_ref: str
    component: str
    timeout: int
    no_get_dependencies: bool
    single_replicas: bool
    reserve: bool


def _deploy_args(app: str, opts: DeployOptions) -> list[str]:
    """Build the ``bonfire deploy`` argument list."""
    apps = app.split() if " " in app else [app]
    args = ["deploy", *apps]
    args.extend(["--source", opts["source"], "--target-env", opts["target_env"], "--timeout", str(opts["timeout"])])
    for flag, value in (
        ("--namespace", opts["namespace"]),
        ("--ref-env", opts["ref_env"]),
        ("--set-image-tag", opts["set_image_tag"]),
        ("--set-template-ref", opts["set_template_ref"]),
        ("--component", opts["component"]),
    ):
        if value:
            args.extend([flag, value])
    for flag, enabled in (
        ("--no-get-dependencies", opts["no_get_dependencies"]),
        ("--single-replicas", opts["single_replicas"]),
        ("--reserve", opts["reserve"]),
    ):
        if enabled:
            args.append(flag)
    return args


async def _bonfire_deploy_impl(app: str, opts: DeployOptions) -> list[TextContent]:
    """Implementation of bonfire_deploy tool."""
    args = _deploy_args(app, opts)

    success, output = await run_bonfire(args, timeout=opts["timeout"] + 120)

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


def _validate_aa_refs(template_ref: str, image_tag: str, image_base: str) -> tuple[str | None, str | None]:
    """Validate template_ref (40-char SHA) and image_tag (64-hex digest); returns (digest, None) or (None, error)."""
    # VALIDATE template_ref: Must be FULL 40-char git commit SHA
    if len(template_ref) != 40:
        err_msg = (
            f"❌ **Invalid template_ref: `{template_ref}` "
            f"({len(template_ref)} chars)**\n\n"
            "template_ref must be a FULL 40-character git commit SHA.\n\n"
            "**Fix:** Get the full SHA:\n"
            f"```bash\ngit rev-parse {template_ref}\n```"
        )
        return None, err_msg

    # Strip sha256: prefix if present
    digest = image_tag
    digest = digest.removeprefix("sha256:")

    # VALIDATE image_tag: Must be 64-char sha256 digest
    if len(digest) != 64:
        return None, (
            f"""❌ **Invalid image_tag: `{image_tag}` ({len(digest)} chars)**

image_tag must be the 64-char sha256 digest from the built image (NOT the git SHA).

**How to get it:**
1. Call `quay_get_tag(repository='...', tag='{template_ref}')`
2. Look for "Manifest Digest: sha256:XXXX..."
3. Use the 64-char hex part after "sha256:"

**Or via CLI:**
```bash
skopeo inspect docker://{image_base}:{template_ref} | jq -r '.Digest' | cut -d: -f2
```"""
        )

    # Validate digest is hex
    if not all(c in "0123456789abcdef" for c in digest.lower()):
        return None, (
            f"""❌ **Invalid digest format: `{digest}`**

Expected 64 hex characters (0-9, a-f). Got non-hex characters."""
        )

    return digest, None


async def _check_aa_image_exists(template_ref: str, image_base: str) -> str | None:
    """HARD STOP check that the Konflux image exists in Quay; returns an error message or None."""
    repository = "aap-aa-tenant/aap-aa-main/automation-analytics-backend-main"
    image_ref = f"docker://quay.io/redhat-user-workloads/{repository}:{template_ref}"

    logger.info("Checking if image exists: %s", image_ref)

    check_success, check_output = await run_cmd(
        ["skopeo", "inspect", "--raw", image_ref],
        timeout=30,
    )

    if not check_success or "manifest unknown" in check_output.lower():
        # Check if it was a timeout
        if "timed out" in check_output.lower():
            return "❌ Image check timed out. Verify image exists before retrying."

        return f"""❌ **STOP: Image not found in Quay**

The image for commit `{template_ref[:12]}...` does not exist in redhat-user-workloads.

**Image checked:** `{image_base}:{template_ref}`

**Possible causes:**
1. Konflux hasn't built the image yet (check pipeline status)
2. The commit SHA is incorrect
3. The build failed

**What to do:**
1. Check Konflux build status for this commit
2. Wait for the build to complete
3. Retry once the image is available

**DO NOT** proceed with deployment - it will fail with ImagePullBackOff."""

    return None


async def _bonfire_deploy_aa_impl(
    namespace: str,
    template_ref: str,
    image_tag: str,
    billing: bool = False,
    timeout: int = 900,
) -> list[TextContent]:
    """Implementation of bonfire_deploy_aa tool."""
    # Load app config from config.json
    app_cfg = get_app_config(billing=billing)
    image_base = app_cfg["image_base"]

    if not image_base:
        return [
            TextContent(
                type="text",
                text="❌ image_base not configured in config.json bonfire.apps section",
            )
        ]

    digest, error = _validate_aa_refs(template_ref, image_tag, image_base)
    if error or digest is None:
        return [TextContent(type="text", text=error or "❌ Invalid image_tag")]

    # HARD STOP: Check if image exists in Quay before deploying
    image_error = await _check_aa_image_exists(template_ref, image_base)
    if image_error:
        return [TextContent(type="text", text=image_error)]

    logger.info("Image verified, proceeding with deploy")

    args = aa_deploy_args(app_cfg, namespace, timeout, (template_ref, digest))

    # Log the full command for debugging
    cmd_preview = f"KUBECONFIG={get_ephemeral_kubeconfig()} bonfire {' '.join(args)}"
    # Log only the bonfire arguments; the kubeconfig path stays out of logs.
    logger.info("Deploying AA: bonfire %s", " ".join(args))

    success, output = await run_bonfire(args, timeout=timeout + 120)

    if not success:
        text = deploy_failure_text(f"❌ AA {'billing' if billing else 'main'} deployment failed", cmd_preview, output)
        return [TextContent(type="text", text=text)]

    text = "\n".join(
        [
            f"## ✅ Deployed Automation Analytics ({'billing' if billing else 'main'})",
            "",
            f"**Namespace:** `{namespace}`",
            f"**Component:** `{app_cfg['component']}`",
            f"**Template Ref:** `{template_ref}`",
            f"**Image Digest:** `{digest[:16]}...`",
            "",
            "**Command used:**",
            "```bash",
            cmd_preview,
            "```",
            "",
            "**Output:**",
            "```",
            truncate_output(output, 5000, mode="tail"),
            "```",
            "",
            "**Next steps:**",
            f"- Check pods: `kubectl_get_pods(namespace='{namespace}', environment='ephemeral')`",
            f"- Run IQE tests: `bonfire_deploy_iqe_cji(namespace='{namespace}')`",
        ]
    )
    return [TextContent(type="text", text=text)]


async def _bonfire_namespace_describe_impl(namespace: str) -> list[TextContent]:
    """Implementation of bonfire_namespace_describe tool."""
    success, output = await run_bonfire(["namespace", "describe", namespace])

    if not success:
        return [TextContent(type="text", text=f"❌ Failed to describe namespace:\n\n{output}")]

    return [TextContent(type="text", text=f"## Namespace: `{namespace}`\n\n```\n{output}\n```")]


async def _bonfire_namespace_extend_impl(
    namespace: str,
    duration: str = "1h",
) -> list[TextContent]:
    """Implementation of bonfire_namespace_extend tool."""
    success, output = await run_bonfire(["namespace", "extend", namespace, "--duration", duration])

    if not success:
        return [TextContent(type="text", text=f"❌ Failed to extend namespace:\n\n{output}")]

    return [
        TextContent(
            type="text",
            text=f"✅ Namespace `{namespace}` extended by {duration}\n\n{output}",
        )
    ]


async def _bonfire_namespace_list_impl(mine_only: bool = True) -> list[TextContent]:
    """Implementation of bonfire_namespace_list tool."""
    args = ["namespace", "list"]
    if mine_only:
        args.append("--mine")

    success, output = await run_bonfire(args)

    if not success:
        return [TextContent(type="text", text=f"❌ Failed to list namespaces:\n\n{output}")]

    title = "My Ephemeral Namespaces" if mine_only else "All Ephemeral Namespaces"
    return [TextContent(type="text", text=f"## {title}\n\n```\n{output}\n```")]


async def _bonfire_namespace_release_impl(namespace: str, force: bool = False) -> list[TextContent]:
    """Implementation of bonfire_namespace_release tool."""
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


class ReserveOptions(TypedDict):
    """Options for ``bonfire namespace reserve``."""

    requester: str
    name: str
    timeout: int
    force: bool


async def _bonfire_namespace_reserve_impl(duration: str, pool: str, opts: ReserveOptions) -> list[TextContent]:
    """Implementation of bonfire_namespace_reserve tool."""
    requester, name, timeout, force = opts["requester"], opts["name"], opts["timeout"], opts["force"]
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


async def _bonfire_namespace_wait_impl(
    namespace: str,
    timeout: int = 300,
) -> list[TextContent]:
    """Implementation of bonfire_namespace_wait tool."""
    success, output = await run_bonfire(
        ["namespace", "wait-on-resources", namespace, "--timeout", str(timeout)],
        timeout=timeout + 60,
    )

    if not success:
        return [TextContent(type="text", text=f"❌ Wait failed:\n\n{output}")]

    return [TextContent(type="text", text=f"✅ Resources ready in `{namespace}`\n\n{output}")]


async def _bonfire_pool_list_impl() -> list[TextContent]:
    """Implementation of bonfire_pool_list tool."""
    success, output = await run_bonfire(["pool", "list"])

    if not success:
        return [TextContent(type="text", text=f"❌ Failed to list pools:\n\n{output}")]

    return [TextContent(type="text", text=f"## Namespace Pools\n\n```\n{output}\n```")]


def register_tools(server: "FastMCP") -> int:
    """Register tools with the MCP server."""
    registry = ToolRegistry(server)

    # REMOVED: bonfire_version - low value, rarely needed

    # ==================== NAMESPACE MANAGEMENT ====================
    # ==================== TOOLS USED IN SKILLS ====================
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
        return await _bonfire_apps_dependencies_impl(component)

    @auto_heal_ephemeral()
    @registry.tool()
    # MCP tool schema is generated from this signature; parameters are the public tool API.
    # pylint: disable-next=too-many-arguments,too-many-positional-arguments
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
        return await _bonfire_deploy_impl(
            app,
            DeployOptions(
                namespace=namespace,
                source=source,
                target_env=target_env,
                ref_env=ref_env,
                set_image_tag=set_image_tag,
                set_template_ref=set_template_ref,
                component=component,
                timeout=timeout,
                no_get_dependencies=no_get_dependencies,
                single_replicas=single_replicas,
                reserve=reserve,
            ),
        )

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_deploy_aa(
        namespace: str,
        template_ref: str,
        image_tag: str,
        billing: bool = False,
        timeout: int = 900,
    ) -> list[TextContent]:
        """
        Deploy Automation Analytics to ephemeral namespace (matches ITS pattern exactly).

        Command format (billing=false):
        KUBECONFIG=~/.kube/config.e bonfire deploy \\
          --source=appsre --ref-env insights-production \\
          --namespace ephemeral-xxx --timeout 900 \\
          --optional-deps-method hybrid --frontends false \\
          --component tower-analytics-clowdapp \\
          --no-remove-resources all \\
          --set-template-ref tower-analytics-clowdapp=<40-char-git-sha> \\
          --set-parameter tower-analytics-clowdapp/IMAGE=quay.io/.../image@sha256 \\
          --set-parameter tower-analytics-clowdapp/IMAGE_TAG=<64-char-sha256-digest> \\
          tower-analytics

        Args:
            namespace: Target ephemeral namespace (e.g., "ephemeral-uhfivg")
            template_ref: Full 40-char git commit SHA for template
            image_tag: 64-char sha256 digest from Quay (NOT git SHA!)
                       Get this from quay_get_tag output: "Manifest Digest: sha256:..."
            billing: If True, deploy tower-analytics-billing-clowdapp
                     If False, deploy tower-analytics-clowdapp
            timeout: Deployment timeout in seconds

        Returns:
            Deployment status.
        """
        return await _bonfire_deploy_aa_impl(namespace, template_ref, image_tag, billing, timeout)

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
        return await _bonfire_namespace_describe_impl(namespace)

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
        return await _bonfire_namespace_extend_impl(namespace, duration)

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
        return await _bonfire_namespace_list_impl(mine_only)

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
        return await _bonfire_namespace_release_impl(namespace, force)

    @auto_heal_ephemeral()
    @registry.tool()
    # MCP tool schema is generated from this signature; parameters are the public tool API.
    # pylint: disable-next=too-many-arguments,too-many-positional-arguments
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
        return await _bonfire_namespace_reserve_impl(
            duration, pool, ReserveOptions(requester=requester, name=name, timeout=timeout, force=force)
        )

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
        return await _bonfire_namespace_wait_impl(namespace, timeout)

    @auto_heal_ephemeral()
    @registry.tool()
    async def bonfire_pool_list() -> list[TextContent]:
        """
        List available namespace pool types.

        Returns:
            List of pool types.
        """
        return await _bonfire_pool_list_impl()

    return registry.count
