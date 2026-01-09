"""K8s Extra Tools - Advanced k8s operations.

For basic operations, see tools_basic.py.

Tools included (~14):
- kubectl_rollout_restart, kubectl_scale, kubectl_get_ingress, ...
"""

from mcp.server.fastmcp import FastMCP

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import get_kubeconfig, run_kubectl, truncate_output  # noqa: F401

# Setup project path for server imports
from tool_modules.common import PROJECT_ROOT  # noqa: F401 - side effect: adds to sys.path

# ==================== PODS ====================


def register_tools(server: FastMCP) -> int:
    """Register extra k8s tools with the MCP server."""
    registry = ToolRegistry(server)

    @auto_heal()
    @registry.tool()
    async def kubectl_rollout_restart(deployment_name: str, namespace: str, environment: str = "stage") -> str:
        """Restart a deployment (rolling restart)."""
        kubeconfig = get_kubeconfig(environment, namespace)
        success, output = await run_kubectl(
            ["rollout", "restart", f"deployment/{deployment_name}"],
            kubeconfig=kubeconfig,
            namespace=namespace,
        )
        return f"✅ Deployment restarted: {deployment_name}" if success else f"❌ Failed: {output}"

    @auto_heal()
    @registry.tool()
    async def kubectl_scale(deployment_name: str, replicas: int, namespace: str, environment: str = "stage") -> str:
        """Scale a deployment."""
        kubeconfig = get_kubeconfig(environment, namespace)
        success, output = await run_kubectl(
            ["scale", f"deployment/{deployment_name}", f"--replicas={replicas}"],
            kubeconfig=kubeconfig,
            namespace=namespace,
        )
        return f"✅ Scaled to {replicas} replicas" if success else f"❌ Failed: {output}"

    # ==================== SERVICES & NETWORKING ====================

    @auto_heal()
    @registry.tool()
    async def kubectl_get_ingress(namespace: str, environment: str = "stage") -> str:
        """List ingress resources in a namespace."""
        kubeconfig = get_kubeconfig(environment, namespace)
        success, output = await run_kubectl(
            ["get", "ingress", "-o", "wide"], kubeconfig=kubeconfig, namespace=namespace
        )
        return f"## Ingress\n\n```\n{output}\n```" if success else f"❌ Failed: {output}"

    # ==================== CONFIG & SECRETS ====================

    @auto_heal()
    @registry.tool()
    async def kubectl_get_configmaps(namespace: str, environment: str = "stage") -> str:
        """List configmaps in a namespace."""
        kubeconfig = get_kubeconfig(environment, namespace)
        success, output = await run_kubectl(["get", "configmaps"], kubeconfig=kubeconfig, namespace=namespace)
        return f"## ConfigMaps\n\n```\n{output}\n```" if success else f"❌ Failed: {output}"

    @auto_heal()
    @registry.tool()
    async def kubectl_get_secrets(namespace: str, environment: str = "stage") -> str:
        """List secrets in a namespace (names only)."""
        kubeconfig = get_kubeconfig(environment, namespace)
        success, output = await run_kubectl(["get", "secrets"], kubeconfig=kubeconfig, namespace=namespace)
        return f"## Secrets\n\n```\n{output}\n```" if success else f"❌ Failed: {output}"

    # ==================== EVENTS & DEBUGGING ====================

    @auto_heal()
    @registry.tool()
    async def kubectl_exec(
        pod_name: str,
        command: str,
        namespace: str,
        environment: str = "stage",
        container: str = "",
        timeout: int = 30,
    ) -> str:
        """
        Execute a command in a pod.

        Args:
            pod_name: Name of the pod
            namespace: Kubernetes namespace
            environment: Target environment (stage, production, ephemeral)
            container: Specific container name (for multi-container pods)
            command: Command to execute (space-separated)
            timeout: Timeout in seconds

        Returns:
            Command output.
        """
        kubeconfig = get_kubeconfig(environment, namespace)
        args = ["exec", pod_name]
        if container:
            args.extend(["-c", container])
        args.append("--")
        args.extend(command.split())
        success, output = await run_kubectl(args, kubeconfig=kubeconfig, namespace=namespace, timeout=timeout)
        return f"## Exec: {command}\n\n```\n{output}\n```" if success else f"❌ Failed: {output}"

    @auto_heal()
    @registry.tool()
    async def kubectl_cp(
        source: str,
        destination: str,
        namespace: str,
        environment: str = "stage",
        container: str = "",
        to_pod: bool = True,
    ) -> str:
        """
        Copy files to/from a pod.

        Args:
            source: Source path (local file or pod:path)
            destination: Destination path (pod:path or local file)
            namespace: Kubernetes namespace
            environment: Target environment (stage, production, ephemeral)
            container: Specific container name (for multi-container pods)
            to_pod: If True, copy from local to pod. If False, copy from pod to local.

        Returns:
            Copy result.

        Examples:
            kubectl_cp("/tmp/script.sh", "pod-name:/tmp/script.sh", "ns", to_pod=True)
            kubectl_cp("pod-name:/tmp/output.log", "/tmp/output.log", "ns", to_pod=False)
        """
        kubeconfig = get_kubeconfig(environment, namespace)

        # Build source and destination with namespace prefix for pod paths
        if to_pod:
            # source is local, destination is pod
            dest_with_ns = f"{namespace}/{destination}"
            args = ["cp", source, dest_with_ns]
        else:
            # source is pod, destination is local
            src_with_ns = f"{namespace}/{source}"
            args = ["cp", src_with_ns, destination]

        if container:
            args.extend(["-c", container])

        success, output = await run_kubectl(args, kubeconfig=kubeconfig, timeout=60)

        if success:
            direction = "to pod" if to_pod else "from pod"
            return f"✅ Copied {direction}: {source} → {destination}"
        return f"❌ Copy failed: {output}"

    @auto_heal()
    @registry.tool()
    async def kubectl_get_secret_value(
        secret_name: str,
        key: str,
        namespace: str,
        environment: str = "stage",
        decode: bool = True,
    ) -> str:
        """
        Get a specific key from a Kubernetes secret.

        Args:
            secret_name: Name of the secret
            key: Key within the secret to retrieve
            namespace: Kubernetes namespace
            environment: Target environment
            decode: Base64 decode the value (default: True)

        Returns:
            Secret value (decoded if requested).
        """
        kubeconfig = get_kubeconfig(environment, namespace)

        # Get the secret value using jsonpath
        jsonpath = f"{{.data.{key}}}"
        args = ["get", "secret", secret_name, "-o", f"jsonpath={jsonpath}"]

        success, output = await run_kubectl(args, kubeconfig=kubeconfig, namespace=namespace)

        if not success:
            return f"❌ Failed to get secret {secret_name}/{key}: {output}"

        if decode and output:
            import base64

            try:
                decoded = base64.b64decode(output).decode("utf-8")
                return decoded
            except Exception as e:
                return f"❌ Failed to decode: {e}"

        return output

    # ==================== SAAS PIPELINES ====================

    @auto_heal()
    @registry.tool()
    async def kubectl_saas_pipelines(namespace: str = "") -> str:
        """List SaaS deployment pipelines on the App-SRE cluster."""
        kubeconfig = get_kubeconfig("appsre-pipelines")
        args = ["get", "pipelineruns", "-o", "wide", "--sort-by=.metadata.creationTimestamp"]
        success, output = await run_kubectl(args, kubeconfig=kubeconfig, namespace=namespace if namespace else None)
        if not success:
            return f"❌ Failed: {output}\n\nRun: `kube ap` to authenticate"
        return f"## SaaS Pipelines\n\n```\n{output}\n```"

    @auto_heal()
    @registry.tool()
    async def kubectl_saas_deployments(namespace: str) -> str:
        """List deployments on the SaaS/App-SRE cluster."""
        kubeconfig = get_kubeconfig("appsre-pipelines")
        success, output = await run_kubectl(
            ["get", "deployments", "-o", "wide"], kubeconfig=kubeconfig, namespace=namespace
        )
        return f"## SaaS Deployments: {namespace}\n\n```\n{output}\n```" if success else f"❌ Failed: {output}"

    @auto_heal()
    @registry.tool()
    async def kubectl_saas_pods(namespace: str) -> str:
        """List pods on the SaaS/App-SRE cluster."""
        kubeconfig = get_kubeconfig("appsre-pipelines")
        success, output = await run_kubectl(["get", "pods", "-o", "wide"], kubeconfig=kubeconfig, namespace=namespace)
        return f"## SaaS Pods: {namespace}\n\n```\n{output}\n```" if success else f"❌ Failed: {output}"

    @auto_heal()
    @registry.tool()
    async def kubectl_saas_logs(pod_name: str, namespace: str, container: str = "", tail: int = 100) -> str:
        """Get logs from a pod on the SaaS/App-SRE cluster."""
        kubeconfig = get_kubeconfig("appsre-pipelines")
        args = ["logs", pod_name, f"--tail={tail}"]
        if container:
            args.extend(["-c", container])
        success, output = await run_kubectl(args, kubeconfig=kubeconfig, namespace=namespace, timeout=120)
        return f"## Logs: {pod_name}\n\n```\n{output}\n```" if success else f"❌ Failed: {output}"

    # ==================== ADDITIONAL TOOLS (from kubernetes_tools) ====================

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
            ["get", "deployments", "-o", "wide"], kubeconfig=kubeconfig, namespace=namespace
        )
        return f"## Deployments in {namespace}\n\n```\n{output}\n```" if success else f"❌ Failed: {output}"

    @auto_heal()
    @registry.tool()
    async def k8s_list_ephemeral_namespaces() -> str:
        """
        List all ephemeral (PR) namespaces.

        Returns:
            List of active ephemeral namespaces.
        """
        kubeconfig = get_kubeconfig("ephemeral")
        success, output = await run_kubectl(["get", "namespaces", "-o", "name"], kubeconfig=kubeconfig)
        if not success:
            return f"❌ Failed: {output}\n\nRun: `kube e` to authenticate"

        lines = output.strip().split("\n")
        namespaces = [ln.replace("namespace/", "") for ln in lines if ln.strip()]

        # Filter for ephemeral-like namespaces (often have specific patterns)
        ephemeral_ns = [ns for ns in namespaces if any(x in ns for x in ["ephemeral", "pr-", "test-", "temp-"])]

        if not ephemeral_ns:
            return "No ephemeral namespaces found"

        lines = ["## Ephemeral Namespaces", ""]
        for ns in ephemeral_ns:
            lines.append(f"- {ns}")

        return "\n".join(lines)

    return registry.count
