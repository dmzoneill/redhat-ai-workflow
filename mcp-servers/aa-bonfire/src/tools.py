"""Bonfire MCP Server - Ephemeral namespace management and ClowdApp deployment.

Provides 21 tools for managing ephemeral namespaces and deploying apps.
"""

import asyncio
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

# Add aa-common to path for shared utilities
SERVERS_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(SERVERS_DIR / "aa-common"))

from src.utils import get_kubeconfig, get_section_config

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
            "quay.io/redhat-user-workloads/aap-aa-tenant/aap-aa-main/automation-analytics-backend-main",
        ),
        "ref_env": config.get("ref_env", "insights-production"),
    }


# ==================== Helper Functions ====================


async def run_bonfire(
    args: list[str],
    timeout: int = 300,
    env: dict | None = None,
) -> tuple[bool, str]:
    """Run bonfire command and return (success, output)."""
    cmd = ["bonfire"] + args

    logger.info(f"Running: {' '.join(cmd)}")

    run_env = os.environ.copy()
    # Always set KUBECONFIG for ephemeral cluster
    run_env["KUBECONFIG"] = get_ephemeral_kubeconfig()
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


def register_tools(server: "FastMCP") -> int:
    """Register tools with the MCP server."""

    @server.tool()
    async def bonfire_version() -> list[TextContent]:
        """
        Get bonfire version.

        Returns:
            Bonfire version string.
        """
        success, output = await run_bonfire(["version"])
        return [TextContent(type="text", text=output.strip())]

    # ==================== NAMESPACE MANAGEMENT ====================

    @server.tool()
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

    @server.tool()
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

    @server.tool()
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

    @server.tool()
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

    @server.tool()
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
        success, output = await run_bonfire(
            ["namespace", "extend", namespace, "--duration", duration]
        )

        if not success:
            return [TextContent(type="text", text=f"❌ Failed to extend namespace:\n\n{output}")]

        return [
            TextContent(
                type="text", text=f"✅ Namespace `{namespace}` extended by {duration}\n\n{output}"
            )
        ]

    @server.tool()
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

    @server.tool()
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

    @server.tool()
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

        return [
            TextContent(
                type="text", text=f"## Apps depending on `{component}`\n\n```\n{output}\n```"
            )
        ]

    # ==================== DEPLOYMENT ====================

    @server.tool()
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

        display_output = output[-5000:] if len(output) > 5000 else output

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

    @server.tool()
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
            return [
                TextContent(
                    type="text", text=f"❌ Deploy with reserve failed:\n\n```\n{output}\n```"
                )
            ]

        display_output = output[-5000:] if len(output) > 5000 else output

        return [
            TextContent(
                type="text", text=f"## ✅ Reserved & Deployed `{app}`\n\n```\n{display_output}\n```"
            )
        ]

    # ==================== PROCESS (DRY-RUN) ====================

    @server.tool()
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

        if len(output) > 15000:
            output = output[:15000] + "\n\n... (truncated, output too large)"

        return [
            TextContent(
                type="text", text=f"## ClowdApp Template: `{app}`\n\n```yaml\n{output}\n```"
            )
        ]

    # ==================== CLOWDENV ====================

    @server.tool()
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

        return [
            TextContent(
                type="text", text=f"✅ ClowdEnvironment deployed to `{namespace}`\n\n{output}"
            )
        ]

    @server.tool()
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

        if len(output) > 10000:
            output = output[:10000] + "\n\n... (truncated)"

        return [
            TextContent(
                type="text", text=f"## ClowdEnvironment: `{namespace}`\n\n```yaml\n{output}\n```"
            )
        ]

    # ==================== IQE CJI ====================

    @server.tool()
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

        return [
            TextContent(
                type="text", text=f"✅ IQE CJI deployed to `{namespace}`\n\n```\n{output}\n```"
            )
        ]

    @server.tool()
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

        if len(output) > 8000:
            output = output[:8000] + "\n\n... (truncated)"

        return [TextContent(type="text", text=f"## IQE CJI Template\n\n```yaml\n{output}\n```")]

    # ==================== POOL ====================

    @server.tool()
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

    @server.tool()
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
        # Load app config from config.json
        app_cfg = get_app_config(billing=billing)
        component = app_cfg["component"]
        image_base = app_cfg["image_base"]
        app_name = app_cfg["app_name"]
        ref_env = app_cfg["ref_env"]

        if not image_base:
            return [
                TextContent(
                    type="text",
                    text="❌ image_base not configured in config.json bonfire.apps section",
                )
            ]

        # VALIDATE template_ref: Must be FULL 40-char git commit SHA
        if len(template_ref) != 40:
            return [
                TextContent(
                    type="text",
                    text=f"""❌ **Invalid template_ref: `{template_ref}` ({len(template_ref)} chars)**

template_ref must be a FULL 40-character git commit SHA.

**Fix:** Get the full SHA:
```bash
git rev-parse {template_ref}
```""",
                )
            ]

        # Strip sha256: prefix if present
        digest = image_tag
        if digest.startswith("sha256:"):
            digest = digest[7:]

        # VALIDATE image_tag: Must be 64-char sha256 digest
        if len(digest) != 64:
            return [
                TextContent(
                    type="text",
                    text=f"""❌ **Invalid image_tag: `{image_tag}` ({len(digest)} chars)**

image_tag must be the 64-char sha256 digest from the built image (NOT the git SHA).

**How to get it:**
1. Call `quay_get_tag(repository='...', tag='{template_ref}')`
2. Look for "Manifest Digest: sha256:XXXX..."
3. Use the 64-char hex part after "sha256:"

**Or via CLI:**
```bash
skopeo inspect docker://{image_base}:{template_ref} | jq -r '.Digest' | cut -d: -f2
```""",
                )
            ]

        # Validate digest is hex
        if not all(c in "0123456789abcdef" for c in digest.lower()):
            return [
                TextContent(
                    type="text",
                    text=f"""❌ **Invalid digest format: `{digest}`**

Expected 64 hex characters (0-9, a-f). Got non-hex characters.""",
                )
            ]

        # HARD STOP: Check if image exists in Quay before deploying
        repository = "aap-aa-tenant/aap-aa-main/automation-analytics-backend-main"
        image_ref = f"docker://quay.io/redhat-user-workloads/{repository}:{template_ref}"

        logger.info(f"Checking if image exists: {image_ref}")

        try:
            check_result = await asyncio.to_thread(
                subprocess.run,
                ["skopeo", "inspect", "--raw", image_ref],
                capture_output=True,
                text=True,
                timeout=30,
            )
            check_output = check_result.stdout + check_result.stderr

            if check_result.returncode != 0 or "manifest unknown" in check_output.lower():
                return [
                    TextContent(
                        type="text",
                        text=f"""❌ **STOP: Image not found in Quay**

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

**DO NOT** proceed with deployment - it will fail with ImagePullBackOff.""",
                    )
                ]

        except subprocess.TimeoutExpired:
            return [
                TextContent(
                    type="text",
                    text="❌ Image check timed out. Verify image exists before retrying.",
                )
            ]
        except FileNotFoundError:
            logger.warning("skopeo not found, skipping image check")
            # Continue without check if skopeo not installed

        logger.info("Image verified, proceeding with deploy")

        # Build the exact command matching ITS pattern
        # Example:
        # KUBECONFIG=~/.kube/config.e bonfire deploy \
        #   --source=appsre --ref-env insights-production \
        #   --namespace ephemeral-cr3t3n --timeout 900 \
        #   --optional-deps-method hybrid --frontends false \
        #   --component tower-analytics-clowdapp \
        #   --no-remove-resources all \
        #   --set-template-ref tower-analytics-clowdapp=1244ec49e6... \
        #   --set-parameter tower-analytics-clowdapp/IMAGE=quay.io/.../image@sha256 \
        #   --set-parameter tower-analytics-clowdapp/IMAGE_TAG=20a4c976... \
        #   tower-analytics

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
            "--set-template-ref",
            f"{component}={template_ref}",
            "--set-parameter",
            f"{component}/IMAGE={image_base}@sha256",
            "--set-parameter",
            f"{component}/IMAGE_TAG={digest}",
            app_name,
        ]

        # Log the full command for debugging
        kubeconfig = get_ephemeral_kubeconfig()
        cmd_preview = f"KUBECONFIG={kubeconfig} bonfire {' '.join(args)}"
        logger.info(f"Deploying AA: {cmd_preview}")

        success, output = await run_bonfire(args, timeout=timeout + 120)

        if not success:
            # Include the command in error output for debugging
            return [
                TextContent(
                    type="text",
                    text=f"""❌ AA {'billing' if billing else 'main'} deployment failed

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

        display_output = output[-5000:] if len(output) > 5000 else output

        lines = [
            f"## ✅ Deployed Automation Analytics ({'billing' if billing else 'main'})",
            "",
            f"**Namespace:** `{namespace}`",
            f"**Component:** `{component}`",
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
            display_output,
            "```",
            "",
            "**Next steps:**",
            f"- Check pods: `kubectl_get_pods(namespace='{namespace}', environment='ephemeral')`",
            f"- Run IQE tests: `bonfire_deploy_iqe_cji(namespace='{namespace}')`",
        ]

        return [TextContent(type="text", text="\n".join(lines))]

    @server.tool()
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

        display_output = output[-5000:] if len(output) > 5000 else output

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

    @server.tool()
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
            lines.append(f"❌ Deployment failed:\n```\n{output[-2000:]}\n```")
            lines.append(
                f"\n⚠️ Namespace `{namespace}` still reserved. Release with: `bonfire_namespace_release(namespace='{namespace}')`"
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
                lines.append(
                    f"⚠️ IQE deployment failed (app is still running):\n```\n{output[-1000:]}\n```"
                )
            else:
                lines.append("✅ IQE CJI deployed")

        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(f"**Namespace:** `{namespace}`")
        lines.append(f"**Duration:** {duration}")
        lines.append("")
        lines.append("**Useful commands:**")
        lines.append(
            f"- Check pods: `kubectl_get_pods(namespace='{namespace}', environment='ephemeral')`"
        )
        lines.append(
            f"- Get logs: `kubectl_logs(pod_name='...', namespace='{namespace}', environment='ephemeral')`"
        )
        lines.append(
            f"- Extend time: `bonfire_namespace_extend(namespace='{namespace}', duration='1h')`"
        )
        lines.append(f"- Release: `bonfire_namespace_release(namespace='{namespace}')`")

        return [TextContent(type="text", text="\n".join(lines))]

    @server.tool()
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
                if (
                    "automation-analytics" in container_image
                    or "your-app-backend" in container_image
                ):
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
                        text=f"❌ Invalid template_ref from snapshot: `{template_ref}` ({len(template_ref)} chars, need 40)",
                    )
                ]

            if len(image_digest) != 64:
                return [
                    TextContent(
                        type="text",
                        text=f"❌ Invalid image digest from snapshot: `{image_digest}` ({len(image_digest)} chars, need 64)",
                    )
                ]

            lines.append(f"**Template Ref:** `{template_ref}`")
            lines.append(f"**Image Digest:** `{image_digest[:16]}...`")
            lines.append("")

        except Exception as e:
            return [TextContent(type="text", text=f"❌ Failed to parse snapshot: {e}")]

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
            lines.append(f"❌ Deployment failed:\n```\n{output[-2000:]}\n```")
        else:
            lines.append(f"✅ Deployed `{component}` from snapshot!")
            lines.append(f"\n**Namespace:** `{namespace}`")

        return [TextContent(type="text", text="\n".join(lines))]

    # ==================== ENTRY POINT ====================

    return len([m for m in dir() if not m.startswith("_")])  # Approximate count
