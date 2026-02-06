"""Kubernetes core tools - essential cluster operations.

This module provides the minimal set of k8s tools needed for most workflows:
- kubectl_get_pods: List pods
- kubectl_logs: View pod logs
- kubectl_describe_pod: Pod details
- kubectl_get_deployments: List deployments
- kubectl_get_events: View events
- kubectl_get_configmaps: List configmaps
- kubectl_get_secrets: List secrets
- kubectl_exec: Execute in pod

For additional tools (scale, rollout, cp, etc.), use:
- k8s_basic: Loads core + basic tools
- tool_exec("kubectl_scale", {...}): Call specific tools on-demand

Total: ~8 core tools (down from 22 in basic)
"""

import logging

from fastmcp import FastMCP

# Setup project path for server imports
from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

import importlib.util
from pathlib import Path

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry

# Import implementations from basic module
# Support both package import and direct loading via importlib
try:
    from .tools_basic import (
        _kubectl_describe_pod_impl,
        _kubectl_exec_impl,
        _kubectl_get_configmaps_impl,
        _kubectl_get_deployments_impl,
        _kubectl_get_events_impl,
        _kubectl_get_pods_impl,
        _kubectl_get_secrets_impl,
        _kubectl_logs_impl,
    )
except ImportError:
    # Direct loading - use importlib to avoid sys.path pollution
    _basic_file = Path(__file__).parent / "tools_basic.py"
    _spec = importlib.util.spec_from_file_location("k8s_tools_basic", _basic_file)
    _basic_module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_basic_module)
    _kubectl_describe_pod_impl = _basic_module._kubectl_describe_pod_impl
    _kubectl_exec_impl = _basic_module._kubectl_exec_impl
    _kubectl_get_configmaps_impl = _basic_module._kubectl_get_configmaps_impl
    _kubectl_get_deployments_impl = _basic_module._kubectl_get_deployments_impl
    _kubectl_get_events_impl = _basic_module._kubectl_get_events_impl
    _kubectl_get_pods_impl = _basic_module._kubectl_get_pods_impl
    _kubectl_get_secrets_impl = _basic_module._kubectl_get_secrets_impl
    _kubectl_logs_impl = _basic_module._kubectl_logs_impl

logger = logging.getLogger(__name__)


def register_tools(server: FastMCP) -> int:
    """
    Register core Kubernetes tools with the MCP server.

    Core tools (~8 tools):
    - kubectl_get_pods: List pods in namespace
    - kubectl_logs: View pod logs
    - kubectl_describe_pod: Get pod details
    - kubectl_get_deployments: List deployments
    - kubectl_get_events: View cluster events
    - kubectl_get_configmaps: List configmaps
    - kubectl_get_secrets: List secrets
    - kubectl_exec: Execute command in pod

    For additional tools, load k8s_basic or use tool_exec().
    """
    registry = ToolRegistry(server)

    @auto_heal()
    @registry.tool()
    async def kubectl_get_pods(
        namespace: str,
        environment: str = "stage",
        label_selector: str = "",
    ) -> str:
        """
        List pods in a namespace.

        Args:
            namespace: Kubernetes namespace
            environment: Environment (stage, prod, ephemeral)
            label_selector: Filter by labels (optional)

        Returns:
            List of pods with status.
        """
        return await _kubectl_get_pods_impl(namespace, environment, label_selector)

    @auto_heal()
    @registry.tool()
    async def kubectl_logs(
        pod_name: str,
        namespace: str,
        environment: str = "stage",
        container: str = "",
        tail: int = 100,
        previous: bool = False,
    ) -> str:
        """
        View pod logs.

        Args:
            pod_name: Pod name (can be partial for matching)
            namespace: Kubernetes namespace
            environment: Environment (stage, prod, ephemeral)
            container: Container name (if multi-container pod)
            tail: Number of lines to show
            previous: Show previous container logs

        Returns:
            Pod logs.
        """
        return await _kubectl_logs_impl(pod_name, namespace, environment, container, tail, previous)

    @auto_heal()
    @registry.tool()
    async def kubectl_describe_pod(pod_name: str, namespace: str, environment: str = "stage") -> str:
        """
        Get detailed pod information.

        Args:
            pod_name: Pod name
            namespace: Kubernetes namespace
            environment: Environment (stage, prod, ephemeral)

        Returns:
            Detailed pod description.
        """
        return await _kubectl_describe_pod_impl(pod_name, namespace, environment)

    @auto_heal()
    @registry.tool()
    async def kubectl_get_deployments(namespace: str, environment: str = "stage") -> str:
        """
        List deployments in a namespace.

        Args:
            namespace: Kubernetes namespace
            environment: Environment (stage, prod, ephemeral)

        Returns:
            List of deployments with replica status.
        """
        return await _kubectl_get_deployments_impl(namespace, environment)

    @auto_heal()
    @registry.tool()
    async def kubectl_get_events(namespace: str, environment: str = "stage", field_selector: str = "") -> str:
        """
        View cluster events.

        Args:
            namespace: Kubernetes namespace
            environment: Environment (stage, prod, ephemeral)
            field_selector: Filter events (optional)

        Returns:
            Recent cluster events.
        """
        return await _kubectl_get_events_impl(namespace, environment, field_selector)

    @auto_heal()
    @registry.tool()
    async def kubectl_get_configmaps(namespace: str, environment: str = "stage") -> str:
        """
        List configmaps in a namespace.

        Args:
            namespace: Kubernetes namespace
            environment: Environment (stage, prod, ephemeral)

        Returns:
            List of configmaps.
        """
        return await _kubectl_get_configmaps_impl(namespace, environment)

    @auto_heal()
    @registry.tool()
    async def kubectl_get_secrets(namespace: str, environment: str = "stage") -> str:
        """
        List secrets in a namespace.

        Args:
            namespace: Kubernetes namespace
            environment: Environment (stage, prod, ephemeral)

        Returns:
            List of secrets (names only, not values).
        """
        return await _kubectl_get_secrets_impl(namespace, environment)

    @auto_heal()
    @registry.tool()
    async def kubectl_exec(
        pod_name: str,
        namespace: str,
        command: str,
        environment: str = "stage",
        container: str = "",
    ) -> str:
        """
        Execute a command in a pod.

        Args:
            pod_name: Pod name
            namespace: Kubernetes namespace
            command: Command to execute
            environment: Environment (stage, prod, ephemeral)
            container: Container name (if multi-container pod)

        Returns:
            Command output.
        """
        return await _kubectl_exec_impl(pod_name, namespace, command, environment, container)

    logger.info(f"Registered {registry.count} core Kubernetes tools")
    return registry.count
