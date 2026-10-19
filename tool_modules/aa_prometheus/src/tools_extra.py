"""Prometheus MCP Server - Extra metrics and alerting tools.

Provides health, error-rate, label, and target tools.
"""

import logging

from fastmcp import FastMCP
from mcp.types import TextContent

from server.auto_heal_decorator import auto_heal_stage
from server.tool_registry import ToolRegistry
from tool_modules.aa_prometheus.src.prometheus_impl import (
    _prometheus_check_health_impl,
    _prometheus_error_rate_impl,
    _prometheus_get_alerts_impl,
    _prometheus_labels_impl,
    _prometheus_namespace_metrics_impl,
    _prometheus_pre_deploy_check_impl,
    _prometheus_series_impl,
    _prometheus_targets_impl,
)

logger = logging.getLogger(__name__)


def register_tools(server: "FastMCP") -> int:
    """Register tools with the MCP server."""
    registry = ToolRegistry(server)

    # ==================== TOOLS NOT USED IN SKILLS ====================
    @auto_heal_stage()
    @registry.tool()
    async def prometheus_check_health(
        namespace: str,
        environment: str = "stage",
    ) -> list[TextContent]:
        """
        Check if a namespace is healthy (no critical/warning alerts).

        Args:
            namespace: Namespace pattern to check (e.g., "your-app-stage")
            environment: "stage" or "prod"

        Returns:
            Health status and any firing alerts.
        """
        return await _prometheus_check_health_impl(namespace, environment)

    @auto_heal_stage()
    @registry.tool()
    async def prometheus_error_rate(
        namespace: str,
        environment: str = "stage",
        window: str = "5m",
    ) -> list[TextContent]:
        """
        Get HTTP error rates for a namespace.

        Args:
            namespace: Kubernetes namespace
            environment: Target environment (stage, production)
            window: Time window for rate calculation (e.g., "5m", "15m", "1h")

        Returns:
            Error rates by status code.
        """
        return await _prometheus_error_rate_impl(namespace, environment, window)

    @auto_heal_stage()
    @registry.tool()
    async def prometheus_get_alerts(
        environment: str = "stage",
        namespace: str = "",
    ) -> list[TextContent]:
        """
        Get firing alerts from Prometheus (simplified view).

        Args:
            environment: "stage" or "prod"
            namespace: Optional namespace filter (e.g., "your-app")

        Returns:
            List of firing alerts.
        """
        return await _prometheus_get_alerts_impl(namespace, environment)

    @auto_heal_stage()
    @registry.tool()
    async def prometheus_labels(
        environment: str = "stage",
        label: str = "",
    ) -> list[TextContent]:
        """
        Get label names or values from Prometheus.

        Args:
            environment: Target environment (stage, production)
            label: If provided, get values for this label. Otherwise, list all labels.

        Returns:
            Label names or values.
        """
        return await _prometheus_labels_impl(environment, label)

    @auto_heal_stage()
    @registry.tool()
    async def prometheus_namespace_metrics(
        namespace: str,
        environment: str = "stage",
    ) -> list[TextContent]:
        """
        Get key metrics for a Kubernetes namespace.

        Args:
            namespace: Kubernetes namespace (e.g., "your-app-stage")
            environment: Target environment (stage, production)

        Returns:
            CPU, memory, and request metrics for the namespace.
        """
        return await _prometheus_namespace_metrics_impl(namespace, environment)

    @auto_heal_stage()
    @registry.tool()
    async def prometheus_pre_deploy_check(
        environment: str = "stage",
    ) -> list[TextContent]:
        """
        Run pre-deployment checks for the application.

        Args:
            environment: "stage" or "prod"

        Returns:
            Whether it's safe to deploy based on current alerts.
        """
        return await _prometheus_pre_deploy_check_impl(environment)

    @auto_heal_stage()
    @registry.tool()
    async def prometheus_series(
        match: str,
        environment: str = "stage",
        limit: int = 20,
    ) -> list[TextContent]:
        """
        Find time series matching a label selector.

        Args:
            match: Label selector (e.g., '{job="api"}', 'up{namespace="your-app-stage"}')
            environment: Target environment (stage, production)
            limit: Maximum series to return

        Returns:
            Matching time series.
        """
        return await _prometheus_series_impl(match, environment, limit)

    @auto_heal_stage()
    @registry.tool()
    async def prometheus_targets(
        environment: str = "stage",
        state: str = "",
    ) -> list[TextContent]:
        """
        Get scrape targets and their health status.

        Args:
            environment: Target environment (stage, production)
            state: Filter by state (up, down, unknown, or empty for all)

        Returns:
            List of targets with health status.
        """
        return await _prometheus_targets_impl(environment, state)

    return registry.count
