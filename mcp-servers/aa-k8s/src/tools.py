"""AA Kubernetes MCP Server - Kubernetes operations via kubectl.

Authentication: Uses kubeconfig files in ~/.kube/
  - config.s = stage
  - config.p = production  
  - config.e = ephemeral
  - config.ap = App-SRE SaaS pipelines
"""

import asyncio
import os
import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP


KUBE_BASE = Path.home() / ".kube"

# Environment to kubeconfig mapping
KUBECONFIG_MAP = {
    "stage": "config.s", "s": "config.s",
    "production": "config.p", "prod": "config.p", "p": "config.p",
    "ephemeral": "config.e", "e": "config.e",
    "appsre-pipelines": "config.ap", "ap": "config.ap", "saas": "config.ap",
}


def get_kubeconfig(env: str, namespace: str = "") -> str:
    """Get kubeconfig path for environment."""
    config_name = KUBECONFIG_MAP.get(env.lower(), f"config.{env}")
    return str(KUBE_BASE / config_name)


async def run_kubectl(
    args: list[str], kubeconfig: str | None = None, namespace: str | None = None, timeout: int = 60
) -> tuple[bool, str]:
    """Run kubectl command and return (success, output).
    
    Uses --kubeconfig= flag for explicit config selection.
    """
    cmd = ["kubectl"]
    if kubeconfig:
        cmd.append(f"--kubeconfig={kubeconfig}")
    cmd.extend(args)
    if namespace:
        cmd.extend(["-n", namespace])
    
    try:
        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, timeout=timeout
        )
        output = result.stdout
        if result.returncode != 0:
            output = result.stderr or result.stdout or "Command failed"
            return False, output
        return True, output
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout}s"
    except FileNotFoundError:
        return False, "kubectl not found"
    except Exception as e:
        return False, str(e)


# ==================== PODS ====================

def register_tools(server: "FastMCP") -> int:
    """Register tools with the MCP server."""
    
    @server.tool()
    async def kubectl_get_pods(namespace: str, environment: str = "stage", selector: str = "", all_namespaces: bool = False) -> str:
        """List pods in a namespace."""
        kubeconfig = get_kubeconfig(environment, namespace)
        args = ["get", "pods", "-o", "wide"]
        if selector: args.extend(["-l", selector])
        if all_namespaces: args.append("--all-namespaces")
        success, output = await run_kubectl(args, kubeconfig=kubeconfig, namespace=None if all_namespaces else namespace)
        return output if success else f"❌ Failed: {output}"


    @server.tool()
    async def kubectl_describe_pod(pod_name: str, namespace: str, environment: str = "stage") -> str:
        """Describe a pod in detail."""
        kubeconfig = get_kubeconfig(environment, namespace)
        success, output = await run_kubectl(["describe", "pod", pod_name], kubeconfig=kubeconfig, namespace=namespace)
        if not success:
            return f"❌ Failed: {output}"
        if len(output) > 10000:
            output = output[:10000] + "\n\n... (truncated)"
        return f"## Pod: {pod_name}\n\n```\n{output}\n```"


    @server.tool()
    async def kubectl_logs(
        pod_name: str, namespace: str, environment: str = "stage", container: str = "", tail: int = 100, previous: bool = False
    ) -> str:
        """Get logs from a pod."""
        kubeconfig = get_kubeconfig(environment, namespace)
        args = ["logs", pod_name, f"--tail={tail}"]
        if container: args.extend(["-c", container])
        if previous: args.append("--previous")
        success, output = await run_kubectl(args, kubeconfig=kubeconfig, namespace=namespace, timeout=120)
        return f"## Logs: {pod_name}\n\n```\n{output}\n```" if success else f"❌ Failed: {output}"


    @server.tool()
    async def kubectl_delete_pod(pod_name: str, namespace: str, environment: str = "stage", force: bool = False) -> str:
        """Delete a pod (force restart)."""
        kubeconfig = get_kubeconfig(environment, namespace)
        args = ["delete", "pod", pod_name]
        if force: args.extend(["--force", "--grace-period=0"])
        success, output = await run_kubectl(args, kubeconfig=kubeconfig, namespace=namespace)
        return f"✅ Pod deleted: {pod_name}" if success else f"❌ Failed: {output}"


    # ==================== DEPLOYMENTS ====================

    @server.tool()
    async def kubectl_get_deployments(namespace: str, environment: str = "stage") -> str:
        """List deployments in a namespace."""
        kubeconfig = get_kubeconfig(environment, namespace)
        success, output = await run_kubectl(["get", "deployments", "-o", "wide"], kubeconfig=kubeconfig, namespace=namespace)
        return f"## Deployments\n\n```\n{output}\n```" if success else f"❌ Failed: {output}"


    @server.tool()
    async def kubectl_describe_deployment(deployment_name: str, namespace: str, environment: str = "stage") -> str:
        """Describe a deployment in detail."""
        kubeconfig = get_kubeconfig(environment, namespace)
        success, output = await run_kubectl(["describe", "deployment", deployment_name], kubeconfig=kubeconfig, namespace=namespace)
        if not success:
            return f"❌ Failed: {output}"
        if len(output) > 10000:
            output = output[:10000] + "\n\n... (truncated)"
        return f"## Deployment: {deployment_name}\n\n```\n{output}\n```"


    @server.tool()
    async def kubectl_rollout_status(deployment_name: str, namespace: str, environment: str = "stage") -> str:
        """Check rollout status of a deployment."""
        kubeconfig = get_kubeconfig(environment, namespace)
        success, output = await run_kubectl(
            ["rollout", "status", f"deployment/{deployment_name}", "--timeout=10s"],
            kubeconfig=kubeconfig, namespace=namespace
        )
        return f"✅ {output}" if success else f"⏳ {output}"


    @server.tool()
    async def kubectl_rollout_restart(deployment_name: str, namespace: str, environment: str = "stage") -> str:
        """Restart a deployment (rolling restart)."""
        kubeconfig = get_kubeconfig(environment, namespace)
        success, output = await run_kubectl(
            ["rollout", "restart", f"deployment/{deployment_name}"],
            kubeconfig=kubeconfig, namespace=namespace
        )
        return f"✅ Deployment restarted: {deployment_name}" if success else f"❌ Failed: {output}"


    @server.tool()
    async def kubectl_scale(deployment_name: str, replicas: int, namespace: str, environment: str = "stage") -> str:
        """Scale a deployment."""
        kubeconfig = get_kubeconfig(environment, namespace)
        success, output = await run_kubectl(
            ["scale", f"deployment/{deployment_name}", f"--replicas={replicas}"],
            kubeconfig=kubeconfig, namespace=namespace
        )
        return f"✅ Scaled to {replicas} replicas" if success else f"❌ Failed: {output}"


    # ==================== SERVICES & NETWORKING ====================

    @server.tool()
    async def kubectl_get_services(namespace: str, environment: str = "stage") -> str:
        """List services in a namespace."""
        kubeconfig = get_kubeconfig(environment, namespace)
        success, output = await run_kubectl(["get", "services", "-o", "wide"], kubeconfig=kubeconfig, namespace=namespace)
        return f"## Services\n\n```\n{output}\n```" if success else f"❌ Failed: {output}"


    @server.tool()
    async def kubectl_get_ingress(namespace: str, environment: str = "stage") -> str:
        """List ingress resources in a namespace."""
        kubeconfig = get_kubeconfig(environment, namespace)
        success, output = await run_kubectl(["get", "ingress", "-o", "wide"], kubeconfig=kubeconfig, namespace=namespace)
        return f"## Ingress\n\n```\n{output}\n```" if success else f"❌ Failed: {output}"


    # ==================== CONFIG & SECRETS ====================

    @server.tool()
    async def kubectl_get_configmaps(namespace: str, environment: str = "stage") -> str:
        """List configmaps in a namespace."""
        kubeconfig = get_kubeconfig(environment, namespace)
        success, output = await run_kubectl(["get", "configmaps"], kubeconfig=kubeconfig, namespace=namespace)
        return f"## ConfigMaps\n\n```\n{output}\n```" if success else f"❌ Failed: {output}"


    @server.tool()
    async def kubectl_get_secrets(namespace: str, environment: str = "stage") -> str:
        """List secrets in a namespace (names only)."""
        kubeconfig = get_kubeconfig(environment, namespace)
        success, output = await run_kubectl(["get", "secrets"], kubeconfig=kubeconfig, namespace=namespace)
        return f"## Secrets\n\n```\n{output}\n```" if success else f"❌ Failed: {output}"


    # ==================== EVENTS & DEBUGGING ====================

    @server.tool()
    async def kubectl_get_events(namespace: str, environment: str = "stage", field_selector: str = "") -> str:
        """Get events in a namespace (useful for debugging)."""
        kubeconfig = get_kubeconfig(environment, namespace)
        args = ["get", "events", "--sort-by=.lastTimestamp"]
        if field_selector: args.extend(["--field-selector", field_selector])
        success, output = await run_kubectl(args, kubeconfig=kubeconfig, namespace=namespace)
        if not success:
            return f"❌ Failed: {output}"
        lines = output.split('\n')
        if len(lines) > 50:
            output = '\n'.join(lines[:50]) + f"\n\n... ({len(lines) - 50} more events)"
        return f"## Events\n\n```\n{output}\n```"


    @server.tool()
    async def kubectl_top_pods(namespace: str, environment: str = "stage") -> str:
        """Show resource usage (CPU/memory) for pods."""
        kubeconfig = get_kubeconfig(environment, namespace)
        success, output = await run_kubectl(["top", "pods"], kubeconfig=kubeconfig, namespace=namespace)
        return f"## Pod Metrics\n\n```\n{output}\n```" if success else f"❌ Failed: {output}"


    # ==================== GENERIC ====================

    @server.tool()
    async def kubectl_get(resource: str, namespace: str, environment: str = "stage", name: str = "", output_format: str = "") -> str:
        """Get any Kubernetes resource (pods, deployments, pvc, cronjobs, etc.)."""
        kubeconfig = get_kubeconfig(environment, namespace)
        args = ["get", resource]
        if name: args.append(name)
        if output_format: args.extend(["-o", output_format])
        success, output = await run_kubectl(args, kubeconfig=kubeconfig, namespace=namespace)
        if not success:
            return f"❌ Failed: {output}"
        if len(output) > 15000:
            output = output[:15000] + "\n\n... (truncated)"
        return f"## {resource.title()}\n\n```\n{output}\n```"


    @server.tool()
    async def kubectl_exec(pod_name: str, command: str, namespace: str, environment: str = "stage", container: str = "") -> str:
        """Execute a command in a pod."""
        kubeconfig = get_kubeconfig(environment, namespace)
        args = ["exec", pod_name]
        if container: args.extend(["-c", container])
        args.append("--")
        args.extend(command.split())
        success, output = await run_kubectl(args, kubeconfig=kubeconfig, namespace=namespace, timeout=30)
        return f"## Exec: {command}\n\n```\n{output}\n```" if success else f"❌ Failed: {output}"


    # ==================== SAAS PIPELINES ====================

    @server.tool()
    async def kubectl_saas_pipelines(namespace: str = "") -> str:
        """List SaaS deployment pipelines on the App-SRE cluster."""
        kubeconfig = get_kubeconfig("appsre-pipelines")
        args = ["get", "pipelineruns", "-o", "wide", "--sort-by=.metadata.creationTimestamp"]
        success, output = await run_kubectl(args, kubeconfig=kubeconfig, namespace=namespace if namespace else None)
        if not success:
            return f"❌ Failed: {output}\n\nRun: `kube ap` to authenticate"
        return f"## SaaS Pipelines\n\n```\n{output}\n```"


    @server.tool()
    async def kubectl_saas_deployments(namespace: str) -> str:
        """List deployments on the SaaS/App-SRE cluster."""
        kubeconfig = get_kubeconfig("appsre-pipelines")
        success, output = await run_kubectl(["get", "deployments", "-o", "wide"], kubeconfig=kubeconfig, namespace=namespace)
        return f"## SaaS Deployments: {namespace}\n\n```\n{output}\n```" if success else f"❌ Failed: {output}"


    @server.tool()
    async def kubectl_saas_pods(namespace: str) -> str:
        """List pods on the SaaS/App-SRE cluster."""
        kubeconfig = get_kubeconfig("appsre-pipelines")
        success, output = await run_kubectl(["get", "pods", "-o", "wide"], kubeconfig=kubeconfig, namespace=namespace)
        return f"## SaaS Pods: {namespace}\n\n```\n{output}\n```" if success else f"❌ Failed: {output}"


    @server.tool()
    async def kubectl_saas_logs(pod_name: str, namespace: str, container: str = "", tail: int = 100) -> str:
        """Get logs from a pod on the SaaS/App-SRE cluster."""
        kubeconfig = get_kubeconfig("appsre-pipelines")
        args = ["logs", pod_name, f"--tail={tail}"]
        if container: args.extend(["-c", container])
        success, output = await run_kubectl(args, kubeconfig=kubeconfig, namespace=namespace, timeout=120)
        return f"## Logs: {pod_name}\n\n```\n{output}\n```" if success else f"❌ Failed: {output}"


    # ==================== ADDITIONAL TOOLS (from kubernetes_tools) ====================

    @server.tool()
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
        kubeconfig = get_kubeconfig(environment, namespace)
        lines = [f"## Namespace Health: {namespace} ({environment})", ""]

        # Get pods
        success, output = await run_kubectl(["get", "pods", "-o", "wide"], kubeconfig=kubeconfig, namespace=namespace)
        if success:
            pod_lines = [l for l in output.strip().split('\n')[1:] if l.strip()]
            total = len(pod_lines)
            running = len([l for l in pod_lines if 'Running' in l])
            pending = len([l for l in pod_lines if 'Pending' in l])
            failed = len([l for l in pod_lines if 'Error' in l or 'Failed' in l or 'CrashLoop' in l])

            lines.append("### Pods")
            lines.append(f"- Total: {total}")
            lines.append(f"- Running: {running}")
            lines.append(f"- Pending: {pending}")
            lines.append(f"- Failed/Error: {failed}")
        else:
            lines.append(f"⚠️ Could not get pods: {output[:100]}")

        # Get deployments
        success, output = await run_kubectl(["get", "deployments", "-o", "wide"], kubeconfig=kubeconfig, namespace=namespace)
        if success:
            dep_lines = [l for l in output.strip().split('\n')[1:] if l.strip()]
            total = len(dep_lines)
            ready = 0
            for l in dep_lines:
                parts = l.split()
                if len(parts) >= 2:
                    replicas = parts[1]  # READY column like "2/2"
                    if '/' in replicas:
                        current, desired = replicas.split('/')
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


    @server.tool()
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
        success, output = await run_kubectl(["get", "pods", "-o", "wide"], kubeconfig=kubeconfig, namespace=namespace)
        return f"## Pods in {namespace}\n\n```\n{output}\n```" if success else f"❌ Failed: {output}"


    @server.tool()
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
        success, output = await run_kubectl(["get", "deployments", "-o", "wide"], kubeconfig=kubeconfig, namespace=namespace)
        return f"## Deployments in {namespace}\n\n```\n{output}\n```" if success else f"❌ Failed: {output}"


    @server.tool()
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
                ns_list = [l.replace("namespace/", "") for l in output.strip().split('\n') if "your-app" in l or "your-app" in l]
                lines.append(f"- Namespaces: {len(ns_list)}")
                for ns in ns_list[:5]:
                    lines.append(f"  - {ns}")
                if len(ns_list) > 5:
                    lines.append(f"  - ... and {len(ns_list) - 5} more")

            lines.append("")

        return "\n".join(lines)


    @server.tool()
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

        namespaces = [l.replace("namespace/", "") for l in output.strip().split('\n') if l.strip()]

        # Filter for ephemeral-like namespaces (often have specific patterns)
        ephemeral_ns = [ns for ns in namespaces if any(x in ns for x in ["ephemeral", "pr-", "test-", "temp-"])]

        if not ephemeral_ns:
            return "No ephemeral namespaces found"

        lines = ["## Ephemeral Namespaces", ""]
        for ns in ephemeral_ns:
            lines.append(f"- {ns}")

        return "\n".join(lines)

    return len([m for m in dir() if not m.startswith('_')])  # Approximate count
