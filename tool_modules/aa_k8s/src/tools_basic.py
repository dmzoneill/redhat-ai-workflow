"""AA Kubernetes MCP Server - Kubernetes operations via kubectl.

Authentication: Uses kubeconfig files in ~/.kube/
  - config.s = stage
  - config.p = production
  - config.e = ephemeral
  - config.ap = App-SRE SaaS pipelines
"""

from mcp.server.fastmcp import FastMCP

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import get_kubeconfig, run_kubectl, truncate_output

# Setup project path for server imports
from tool_modules.common import PROJECT_ROOT  # noqa: F401 - side effect: adds to sys.path

# ==================== PODS ====================


# ==================== TOOL IMPLEMENTATIONS ====================


@auto_heal()
async def _k8s_environment_summary_impl(
    environment: str = "",
) -> str:
    """
    Get summary of namespace health across environments.

    Args:
        environment: Specific environment, or empty for all

    Returns:
        Summary of environment health.
    """
    envs = [environment] if environment else ["stage", "production"]
    lines = ["## Environment Summary", ""]

    for env in envs:
        kubeconfig = get_kubeconfig(env)
        lines.append(f"### {env.upper()}")

        # Check connectivity
        success, output = await run_kubectl(["cluster-info"], kubeconfig=kubeconfig)
        if not success:
            lines.append(f"⚠️ Not connected: {output[:50]}")
            lines.append("")
            continue

        # Get namespaces with our prefix
        success, output = await run_kubectl(["get", "namespaces", "-o", "name"], kubeconfig=kubeconfig)
        if success:
            ns_list = [ln.replace("namespace/", "") for ln in output.strip().split("\n") if "your-app" in ln]
            lines.append(f"- Namespaces: {len(ns_list)}")
            for ns in ns_list[:5]:
                lines.append(f"  - {ns}")
            if len(ns_list) > 5:
                lines.append(f"  - ... and {len(ns_list) - 5} more")

        lines.append("")

    return "\n".join(lines)


@auto_heal()
async def _k8s_namespace_health_impl(
    namespace: str,
    environment: str = "stage",
) -> str:
    """
    Get health status of a Kubernetes namespace.

    Args:
        namespace: The namespace to check
        environment: Environment (stage, production, ephemeral)

    Returns:
        Detailed health report for the namespace.
    """
    kubeconfig = get_kubeconfig(environment, namespace)
    lines = [f"## Namespace Health: {namespace} ({environment})", ""]

    # Get pods
    success, output = await run_kubectl(["get", "pods", "-o", "wide"], kubeconfig=kubeconfig, namespace=namespace)
    if success:
        pod_lines = [ln for ln in output.strip().split("\n")[1:] if ln.strip()]
        total = len(pod_lines)
        running = len([ln for ln in pod_lines if "Running" in ln])
        pending = len([ln for ln in pod_lines if "Pending" in ln])
        failed = len([ln for ln in pod_lines if "Error" in ln or "Failed" in ln or "CrashLoop" in ln])

        lines.append("### Pods")
        lines.append(f"- Total: {total}")
        lines.append(f"- Running: {running}")
        lines.append(f"- Pending: {pending}")
        lines.append(f"- Failed/Error: {failed}")
    else:
        lines.append(f"⚠️ Could not get pods: {output[:100]}")

    # Get deployments
    success, output = await run_kubectl(
        ["get", "deployments", "-o", "wide"], kubeconfig=kubeconfig, namespace=namespace
    )
    if success:
        dep_lines = [ln for ln in output.strip().split("\n")[1:] if ln.strip()]
        total = len(dep_lines)
        ready = 0
        for ln in dep_lines:
            parts = ln.split()
            if len(parts) >= 2:
                replicas = parts[1]  # READY column like "2/2"
                if "/" in replicas:
                    current, desired = replicas.split("/")
                    if current == desired:
                        ready += 1

        lines.append("")
        lines.append("### Deployments")
        lines.append(f"- Total: {total}")
        lines.append(f"- Ready: {ready}")

    # Check for issues
    lines.append("")
    lines.append("### Status")
    if failed > 0 or pending > 0:
        lines.append("⚠️ Issues detected")
    else:
        lines.append("✅ Healthy")

    return "\n".join(lines)


@auto_heal()
async def _kubectl_cp_impl(
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
async def _kubectl_describe_deployment_impl(deployment_name: str, namespace: str, environment: str = "stage") -> str:
    """Describe a deployment in detail."""
    kubeconfig = get_kubeconfig(environment, namespace)
    success, output = await run_kubectl(
        ["describe", "deployment", deployment_name], kubeconfig=kubeconfig, namespace=namespace
    )
    if not success:
        return f"❌ Failed: {output}"
    return f"## Deployment: {deployment_name}\n\n```\n{truncate_output(output, max_length=10000)}\n```"


@auto_heal()
async def _kubectl_describe_pod_impl(pod_name: str, namespace: str, environment: str = "stage") -> str:
    """Describe a pod in detail."""
    kubeconfig = get_kubeconfig(environment, namespace)
    success, output = await run_kubectl(["describe", "pod", pod_name], kubeconfig=kubeconfig, namespace=namespace)
    if not success:
        return f"❌ Failed: {output}"
    return f"## Pod: {pod_name}\n\n```\n{truncate_output(output, max_length=10000)}\n```"


@auto_heal()
async def _kubectl_exec_impl(
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
async def _kubectl_get_impl(
    resource: str,
    namespace: str,
    environment: str = "stage",
    name: str = "",
    output_format: str = "",
) -> str:
    """Get any Kubernetes resource (pods, deployments, pvc, cronjobs, etc.)."""
    kubeconfig = get_kubeconfig(environment, namespace)
    args = ["get", resource]
    if name:
        args.append(name)
    if output_format:
        args.extend(["-o", output_format])
    success, output = await run_kubectl(args, kubeconfig=kubeconfig, namespace=namespace)
    if not success:
        return f"❌ Failed: {output}"
    return f"## {resource.title()}\n\n```\n{truncate_output(output, max_length=15000)}\n```"


@auto_heal()
async def _kubectl_get_configmaps_impl(namespace: str, environment: str = "stage") -> str:
    """List configmaps in a namespace."""
    kubeconfig = get_kubeconfig(environment, namespace)
    success, output = await run_kubectl(["get", "configmaps"], kubeconfig=kubeconfig, namespace=namespace)
    return f"## ConfigMaps\n\n```\n{output}\n```" if success else f"❌ Failed: {output}"


@auto_heal()
async def _kubectl_get_deployments_impl(namespace: str, environment: str = "stage") -> str:
    """List deployments in a namespace."""
    kubeconfig = get_kubeconfig(environment, namespace)
    success, output = await run_kubectl(
        ["get", "deployments", "-o", "wide"], kubeconfig=kubeconfig, namespace=namespace
    )
    return f"## Deployments\n\n```\n{output}\n```" if success else f"❌ Failed: {output}"


@auto_heal()
async def _kubectl_get_events_impl(namespace: str, environment: str = "stage", field_selector: str = "") -> str:
    """Get events in a namespace (useful for debugging)."""
    kubeconfig = get_kubeconfig(environment, namespace)
    args = ["get", "events", "--sort-by=.lastTimestamp"]
    if field_selector:
        args.extend(["--field-selector", field_selector])
    success, output = await run_kubectl(args, kubeconfig=kubeconfig, namespace=namespace)
    if not success:
        return f"❌ Failed: {output}"
    lines = output.split("\n")
    if len(lines) > 50:
        output = "\n".join(lines[:50]) + f"\n\n... ({len(lines) - 50} more events)"
    return f"## Events\n\n```\n{output}\n```"


@auto_heal()
async def _kubectl_get_ingress_impl(namespace: str, environment: str = "stage") -> str:
    """List ingress resources in a namespace."""
    kubeconfig = get_kubeconfig(environment, namespace)
    success, output = await run_kubectl(["get", "ingress", "-o", "wide"], kubeconfig=kubeconfig, namespace=namespace)
    return f"## Ingress\n\n```\n{output}\n```" if success else f"❌ Failed: {output}"


@auto_heal()  # Cluster determined from environment param
async def _kubectl_get_pods_impl(
    namespace: str, environment: str = "stage", selector: str = "", all_namespaces: bool = False
) -> str:
    """List pods in a namespace."""
    kubeconfig = get_kubeconfig(environment, namespace)
    args = ["get", "pods", "-o", "wide"]
    if selector:
        args.extend(["-l", selector])
    if all_namespaces:
        args.append("--all-namespaces")
    success, output = await run_kubectl(args, kubeconfig=kubeconfig, namespace=None if all_namespaces else namespace)
    return output if success else f"❌ Failed: {output}"


@auto_heal()
async def _kubectl_get_secret_value_impl(
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


@auto_heal()
async def _kubectl_get_secrets_impl(namespace: str, environment: str = "stage") -> str:
    """List secrets in a namespace (names only)."""
    kubeconfig = get_kubeconfig(environment, namespace)
    success, output = await run_kubectl(["get", "secrets"], kubeconfig=kubeconfig, namespace=namespace)
    return f"## Secrets\n\n```\n{output}\n```" if success else f"❌ Failed: {output}"


@auto_heal()
async def _kubectl_get_services_impl(namespace: str, environment: str = "stage") -> str:
    """List services in a namespace."""
    kubeconfig = get_kubeconfig(environment, namespace)
    success, output = await run_kubectl(["get", "services", "-o", "wide"], kubeconfig=kubeconfig, namespace=namespace)
    return f"## Services\n\n```\n{output}\n```" if success else f"❌ Failed: {output}"


@auto_heal()
async def _kubectl_logs_impl(
    pod_name: str = "",
    namespace: str = "",
    environment: str = "stage",
    container: str = "",
    tail: int = 100,
    previous: bool = False,
    since: str = "",
    selector: str = "",
) -> str:
    """
    Get logs from a pod or selector.

    Args:
        pod_name: Name of the pod (optional if selector provided)
        namespace: Kubernetes namespace
        environment: Target environment (stage, production, ephemeral)
        container: Specific container name (for multi-container pods)
        tail: Number of lines to show from the end
        previous: Get logs from previous instance (after crash)
        since: Only show logs since duration (e.g., "1h", "30m", "24h")
        selector: Label selector (e.g., "app=myapp") - used if pod_name is empty

    Returns:
        Pod logs.
    """
    kubeconfig = get_kubeconfig(environment, namespace)

    if pod_name:
        args = ["logs", pod_name, f"--tail={tail}"]
    elif selector:
        args = ["logs", "-l", selector, f"--tail={tail}", "--all-containers"]
    else:
        return "❌ Error: Either pod_name or selector must be provided"

    if container and pod_name:  # container only works with single pod
        args.extend(["-c", container])
    if previous:
        args.append("--previous")
    if since:
        args.append(f"--since={since}")

    success, output = await run_kubectl(args, kubeconfig=kubeconfig, namespace=namespace, timeout=120)

    target = pod_name or f"selector {selector}"
    return f"## Logs: {target}\n\n```\n{output}\n```" if success else f"❌ Failed: {output}"


@auto_heal()
async def _kubectl_rollout_restart_impl(deployment_name: str, namespace: str, environment: str = "stage") -> str:
    """Restart a deployment (rolling restart)."""
    kubeconfig = get_kubeconfig(environment, namespace)
    success, output = await run_kubectl(
        ["rollout", "restart", f"deployment/{deployment_name}"],
        kubeconfig=kubeconfig,
        namespace=namespace,
    )
    return f"✅ Deployment restarted: {deployment_name}" if success else f"❌ Failed: {output}"


@auto_heal()
async def _kubectl_rollout_status_impl(deployment_name: str, namespace: str, environment: str = "stage") -> str:
    """Check rollout status of a deployment."""
    kubeconfig = get_kubeconfig(environment, namespace)
    success, output = await run_kubectl(
        ["rollout", "status", f"deployment/{deployment_name}", "--timeout=10s"],
        kubeconfig=kubeconfig,
        namespace=namespace,
    )
    return f"✅ {output}" if success else f"⏳ {output}"


@auto_heal()
async def _kubectl_saas_deployments_impl(namespace: str) -> str:
    """List deployments on the SaaS/App-SRE cluster."""
    kubeconfig = get_kubeconfig("appsre-pipelines")
    success, output = await run_kubectl(
        ["get", "deployments", "-o", "wide"], kubeconfig=kubeconfig, namespace=namespace
    )
    return f"## SaaS Deployments: {namespace}\n\n```\n{output}\n```" if success else f"❌ Failed: {output}"


@auto_heal()
async def _kubectl_saas_pipelines_impl(namespace: str = "") -> str:
    """List SaaS deployment pipelines on the App-SRE cluster."""
    kubeconfig = get_kubeconfig("appsre-pipelines")
    args = ["get", "pipelineruns", "-o", "wide", "--sort-by=.metadata.creationTimestamp"]
    success, output = await run_kubectl(args, kubeconfig=kubeconfig, namespace=namespace if namespace else None)
    if not success:
        return f"❌ Failed: {output}\n\nRun: `kube ap` to authenticate"
    return f"## SaaS Pipelines\n\n```\n{output}\n```"


@auto_heal()
async def _kubectl_scale_impl(deployment_name: str, replicas: int, namespace: str, environment: str = "stage") -> str:
    """Scale a deployment."""
    kubeconfig = get_kubeconfig(environment, namespace)
    success, output = await run_kubectl(
        ["scale", f"deployment/{deployment_name}", f"--replicas={replicas}"],
        kubeconfig=kubeconfig,
        namespace=namespace,
    )
    return f"✅ Scaled to {replicas} replicas" if success else f"❌ Failed: {output}"


@auto_heal()
async def _kubectl_top_pods_impl(namespace: str, environment: str = "stage") -> str:
    """Show resource usage (CPU/memory) for pods."""
    kubeconfig = get_kubeconfig(environment, namespace)
    success, output = await run_kubectl(["top", "pods"], kubeconfig=kubeconfig, namespace=namespace)
    return f"## Pod Metrics\n\n```\n{output}\n```" if success else f"❌ Failed: {output}"


def _register_health_tools(registry: ToolRegistry) -> None:
    """Register health tools."""

    @auto_heal()
    @registry.tool()
    async def k8s_environment_summary(
        environment: str = "",
    ) -> str:
        """
        Get summary of namespace health across environments.

        Args:
            environment: Specific environment, or empty for all

        Returns:
            Summary of environment health.
        """
        return await _k8s_environment_summary_impl(environment)

    @auto_heal()
    @registry.tool()
    async def k8s_namespace_health(
        namespace: str,
        environment: str = "stage",
    ) -> str:
        """
        Get health status of a Kubernetes namespace.

        Args:
            namespace: The namespace to check
            environment: Environment (stage, production, ephemeral)

        Returns:
            Detailed health report for the namespace.
        """
        return await _k8s_namespace_health_impl(namespace, environment)


def _register_basic_ops_tools(registry: ToolRegistry) -> None:
    """Register basic ops tools."""

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
        return await _kubectl_cp_impl(source, destination, namespace, environment, container, to_pod)

    @auto_heal()
    @registry.tool()
    async def kubectl_describe_deployment(deployment_name: str, namespace: str, environment: str = "stage") -> str:
        """Describe a deployment in detail."""
        return await _kubectl_describe_deployment_impl(deployment_name, namespace, environment)

    @auto_heal()
    @registry.tool()
    async def kubectl_describe_pod(pod_name: str, namespace: str, environment: str = "stage") -> str:
        """Describe a pod in detail."""
        return await _kubectl_describe_pod_impl(pod_name, namespace, environment)

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
        return await _kubectl_exec_impl(pod_name, command, namespace, environment, container, timeout)

    @auto_heal()
    @registry.tool()
    async def kubectl_get(
        resource: str,
        namespace: str,
        environment: str = "stage",
        name: str = "",
        output_format: str = "",
    ) -> str:
        """Get any Kubernetes resource (pods, deployments, pvc, cronjobs, etc.)."""
        return await _kubectl_get_impl(resource, namespace, environment, name, output_format)

    @auto_heal()
    @registry.tool()
    async def kubectl_logs(
        pod_name: str = "",
        namespace: str = "",
        environment: str = "stage",
        container: str = "",
        tail: int = 100,
        previous: bool = False,
        since: str = "",
        selector: str = "",
    ) -> str:
        """
        Get logs from a pod or selector.

        Args:
            pod_name: Name of the pod (optional if selector provided)
            namespace: Kubernetes namespace
            environment: Target environment (stage, production, ephemeral)
            container: Specific container name (for multi-container pods)
            tail: Number of lines to show from the end
            previous: Get logs from previous instance (after crash)
            since: Only show logs since duration (e.g., "1h", "30m", "24h")
            selector: Label selector (e.g., "app=myapp") - used if pod_name is empty

        Returns:
            Pod logs.
        """
        return await _kubectl_logs_impl(pod_name, namespace, environment, container, tail, previous, since, selector)

    @auto_heal()
    @registry.tool()
    async def kubectl_top_pods(namespace: str, environment: str = "stage") -> str:
        """Show resource usage (CPU/memory) for pods."""
        return await _kubectl_top_pods_impl(namespace, environment)

    @auto_heal()
    @registry.tool()
    async def kubectl_scale(deployment_name: str, replicas: int, namespace: str, environment: str = "stage") -> str:
        """Scale a deployment."""
        return await _kubectl_scale_impl(deployment_name, replicas, namespace, environment)


def _register_resource_getters_tools(registry: ToolRegistry) -> None:
    """Register resource getters tools."""

    @auto_heal()
    @registry.tool()
    async def kubectl_get_configmaps(namespace: str, environment: str = "stage") -> str:
        """List configmaps in a namespace."""
        return await _kubectl_get_configmaps_impl(namespace, environment)

    @auto_heal()
    @registry.tool()
    async def kubectl_get_deployments(namespace: str, environment: str = "stage") -> str:
        """List deployments in a namespace."""
        return await _kubectl_get_deployments_impl(namespace, environment)

    @auto_heal()
    @registry.tool()
    async def kubectl_get_events(namespace: str, environment: str = "stage", field_selector: str = "") -> str:
        """Get events in a namespace (useful for debugging)."""
        return await _kubectl_get_events_impl(namespace, environment, field_selector)

    @auto_heal()
    @registry.tool()
    async def kubectl_get_ingress(namespace: str, environment: str = "stage") -> str:
        """List ingress resources in a namespace."""
        return await _kubectl_get_ingress_impl(namespace, environment)

    @auto_heal()
    @registry.tool()
    async def kubectl_get_pods(
        namespace: str, environment: str = "stage", selector: str = "", all_namespaces: bool = False
    ) -> str:
        """List pods in a namespace."""
        return await _kubectl_get_pods_impl(namespace, environment, selector, all_namespaces)

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
        return await _kubectl_get_secret_value_impl(secret_name, key, namespace, environment, decode)

    @auto_heal()
    @registry.tool()
    async def kubectl_get_secrets(namespace: str, environment: str = "stage") -> str:
        """List secrets in a namespace (names only)."""
        return await _kubectl_get_secrets_impl(namespace, environment)

    @auto_heal()
    @registry.tool()
    async def kubectl_get_services(namespace: str, environment: str = "stage") -> str:
        """List services in a namespace."""
        return await _kubectl_get_services_impl(namespace, environment)


def _register_rollout_tools(registry: ToolRegistry) -> None:
    """Register rollout tools."""

    @auto_heal()
    @registry.tool()
    async def kubectl_rollout_restart(deployment_name: str, namespace: str, environment: str = "stage") -> str:
        """Restart a deployment (rolling restart)."""
        return await _kubectl_rollout_restart_impl(deployment_name, namespace, environment)

    @auto_heal()
    @registry.tool()
    async def kubectl_rollout_status(deployment_name: str, namespace: str, environment: str = "stage") -> str:
        """Check rollout status of a deployment."""
        return await _kubectl_rollout_status_impl(deployment_name, namespace, environment)


def _register_saas_tools(registry: ToolRegistry) -> None:
    """Register saas tools."""

    @auto_heal()
    @registry.tool()
    async def kubectl_saas_deployments(namespace: str) -> str:
        """List deployments on the SaaS/App-SRE cluster."""
        return await _kubectl_saas_deployments_impl(namespace)

    @auto_heal()
    @registry.tool()
    async def kubectl_saas_pipelines(namespace: str = "") -> str:
        """List SaaS deployment pipelines on the App-SRE cluster."""
        return await _kubectl_saas_pipelines_impl(namespace)


def register_tools(server: "FastMCP") -> int:
    """Register tools with the MCP server."""
    registry = ToolRegistry(server)

    _register_health_tools(registry)
    _register_basic_ops_tools(registry)
    _register_resource_getters_tools(registry)
    _register_rollout_tools(registry)
    _register_saas_tools(registry)

    return registry.count
