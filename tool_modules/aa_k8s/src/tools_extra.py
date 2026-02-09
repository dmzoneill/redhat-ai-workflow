"""AA Kubernetes MCP Server - Kubernetes operations via kubectl.

Authentication: Uses kubeconfig files in ~/.kube/
  - config.s = stage
  - config.p = production
  - config.e = ephemeral
  - config.ap = App-SRE SaaS pipelines
"""

from fastmcp import FastMCP

# Setup project path for server imports (must be before server imports)
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization


from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import get_kubeconfig, run_kubectl

# Setup project path for server imports


# ==================== PODS ====================


def register_tools(server: "FastMCP") -> int:
    """Register tools with the MCP server."""
    registry = ToolRegistry(server)

    # ==================== TOOLS NOT USED IN SKILLS ====================
    @auto_heal()
    @registry.tool()
    async def k8s_list_deployments(
        namespace: str,
        environment: str = "stage",
    ) -> str:
        """
        List all deployments in a Kubernetes namespace (alias for kubectl_get_deployments).

        Args:
            namespace: The namespace
            environment: Environment (stage, production, ephemeral)

        Returns:
            List of deployments.
        """
        kubeconfig = get_kubeconfig(environment, namespace)
        success, output = await run_kubectl(
            ["get", "deployments", "-o", "wide"],
            kubeconfig=kubeconfig,
            namespace=namespace,
        )
        return (
            f"## Deployments in {namespace}\n\n```\n{output}\n```"
            if success
            else f"❌ Failed: {output}"
        )

    @auto_heal()
    @registry.tool()
    async def k8s_list_ephemeral_namespaces() -> str:
        """
        List all ephemeral (PR) namespaces.

        Returns:
            List of active ephemeral namespaces.
        """
        kubeconfig = get_kubeconfig("ephemeral")
        success, output = await run_kubectl(
            ["get", "namespaces", "-o", "name"], kubeconfig=kubeconfig
        )
        if not success:
            return f"❌ Failed: {output}\n\nRun: `kube e` to authenticate"

        lines = output.strip().split("\n")
        namespaces = [ln.replace("namespace/", "") for ln in lines if ln.strip()]

        # Filter for ephemeral-like namespaces (often have specific patterns)
        ephemeral_ns = [
            ns
            for ns in namespaces
            if any(x in ns for x in ["ephemeral", "pr-", "test-", "temp-"])
        ]

        if not ephemeral_ns:
            return "No ephemeral namespaces found"

        lines = ["## Ephemeral Namespaces", ""]
        for ns in ephemeral_ns:
            lines.append(f"- {ns}")

        return "\n".join(lines)

    @auto_heal()
    @registry.tool()
    async def k8s_list_pods(
        namespace: str,
        environment: str = "stage",
    ) -> str:
        """
        List all pods in a Kubernetes namespace (alias for kubectl_get_pods).

        Args:
            namespace: The namespace to list pods from
            environment: Environment (stage, production, ephemeral)

        Returns:
            List of pods with status.
        """
        kubeconfig = get_kubeconfig(environment, namespace)
        success, output = await run_kubectl(
            ["get", "pods", "-o", "wide"], kubeconfig=kubeconfig, namespace=namespace
        )
        return (
            f"## Pods in {namespace}\n\n```\n{output}\n```"
            if success
            else f"❌ Failed: {output}"
        )

    @auto_heal()
    @registry.tool()
    async def kubectl_delete_pod(
        pod_name: str, namespace: str, environment: str = "stage", force: bool = False
    ) -> str:
        """Delete a pod (force restart)."""
        kubeconfig = get_kubeconfig(environment, namespace)
        args = ["delete", "pod", pod_name]
        if force:
            args.extend(["--force", "--grace-period=0"])
        success, output = await run_kubectl(
            args, kubeconfig=kubeconfig, namespace=namespace
        )
        return f"✅ Pod deleted: {pod_name}" if success else f"❌ Failed: {output}"

    @auto_heal()
    @registry.tool()
    async def kubectl_saas_logs(
        pod_name: str, namespace: str, container: str = "", tail: int = 100
    ) -> str:
        """Get logs from a pod on the SaaS/App-SRE cluster."""
        kubeconfig = get_kubeconfig("appsre-pipelines")
        args = ["logs", pod_name, f"--tail={tail}"]
        if container:
            args.extend(["-c", container])
        success, output = await run_kubectl(
            args, kubeconfig=kubeconfig, namespace=namespace, timeout=120
        )
        return (
            f"## Logs: {pod_name}\n\n```\n{output}\n```"
            if success
            else f"❌ Failed: {output}"
        )

    @auto_heal()
    @registry.tool()
    async def kubectl_saas_pods(namespace: str) -> str:
        """List pods on the SaaS/App-SRE cluster."""
        kubeconfig = get_kubeconfig("appsre-pipelines")
        success, output = await run_kubectl(
            ["get", "pods", "-o", "wide"], kubeconfig=kubeconfig, namespace=namespace
        )
        return (
            f"## SaaS Pods: {namespace}\n\n```\n{output}\n```"
            if success
            else f"❌ Failed: {output}"
        )
