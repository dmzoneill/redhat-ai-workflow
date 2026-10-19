"""Prometheus MCP Server - Metrics and alerting tools.

Provides tools for Prometheus queries, alerts, targets, and metrics.
"""

import logging

from fastmcp import FastMCP
from mcp.types import TextContent

from server.auto_heal_decorator import auto_heal_stage
from server.tool_registry import ToolRegistry
from tool_modules.aa_prometheus.src.prometheus_impl import (
    _prometheus_alerts_impl,
    _prometheus_pod_health_impl,
    _prometheus_query_impl,
    _prometheus_query_range_impl,
    _prometheus_rules_impl,
    _shared_get_prometheus_config,
    get_prometheus_config,
    prometheus_api_request,
)
from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

logger = logging.getLogger(__name__)

# Re-exported for callers that import the request helpers from this module.
__all__ = [
    "_prometheus_alerts_impl",
    "_prometheus_pod_health_impl",
    "_prometheus_query_impl",
    "_prometheus_query_range_impl",
    "_prometheus_rules_impl",
    "_shared_get_prometheus_config",
    "get_prometheus_config",
    "prometheus_api_request",
    "register_tools",
]


def register_tools(server: "FastMCP") -> int:
    """Register tools with the MCP server."""
    registry = ToolRegistry(server)

    # ==================== TOOLS USED IN SKILLS ====================
    @auto_heal_stage()
    @registry.tool()
    async def prometheus_alerts(
        environment: str = "stage",
        state: str = "",
        namespace: str = "",
        severity: str = "",
    ) -> list[TextContent]:
        """
        Get current alerts from Prometheus.

        Args:
            environment: Target environment (stage, production)
            state: Filter by state (firing, pending, or empty for all)
            namespace: Filter by namespace
            severity: Filter by severity (critical, warning, info)

        Returns:
            List of alerts with details.
        """
        return await _prometheus_alerts_impl(environment, state, namespace, severity)

    @auto_heal_stage()
    @registry.tool()
    async def prometheus_pod_health(
        pod: str,
        namespace: str,
        environment: str = "stage",
    ) -> list[TextContent]:
        """
        Get health metrics for a specific pod.

        Args:
            pod: Pod name (can be partial, will match with regex)
            namespace: Kubernetes namespace
            environment: Target environment (stage, production)

        Returns:
            Pod CPU, memory, restarts, and status.
        """
        return await _prometheus_pod_health_impl(pod, namespace, environment)

    @auto_heal_stage()
    @registry.tool()
    async def prometheus_query(
        query: str,
        environment: str = "stage",
    ) -> list[TextContent]:
        """
        Execute an instant PromQL query.

        Args:
            query: PromQL query string (e.g., "up", "rate(http_requests_total[5m])")
            environment: Target environment (stage, production)

        Returns:
            Query results with metric values.

        Examples:
            - up{namespace="your-app-stage"}
            - rate(http_requests_total{namespace="your-app-stage"}[5m])
            - sum(container_memory_usage_bytes{namespace="your-app-stage"}) by (pod)
        """
        return await _prometheus_query_impl(query, environment)

    # Public MCP tool; this parameter list is the external keyword API.
    @auto_heal_stage()
    @registry.tool()
    async def prometheus_query_range(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        query: str,
        environment: str = "stage",
        start: str = "",
        end: str = "",
        step: str = "1m",
        duration: str = "1h",
    ) -> list[TextContent]:
        """
        Execute a range PromQL query over time.

        Args:
            query: PromQL query string
            environment: Target environment (stage, production)
            start: Start time (ISO format or relative like "-1h"). Default: now - duration
            end: End time (ISO format or "now"). Default: now
            step: Query resolution (e.g., "1m", "5m", "1h")
            duration: Time range if start not specified (e.g., "1h", "6h", "1d")

        Returns:
            Time series data.
        """
        return await _prometheus_query_range_impl(
            query, environment, start, end, step, duration
        )

    @auto_heal_stage()
    @registry.tool()
    async def prometheus_rules(
        environment: str = "stage",
        rule_type: str = "",
        group: str = "",
    ) -> list[TextContent]:
        """
        Get alerting and recording rules from Prometheus.

        Args:
            environment: Target environment (stage, production)
            rule_type: Filter by type (alert, record, or empty for all)
            group: Filter by rule group name

        Returns:
            List of rules.
        """
        return await _prometheus_rules_impl(environment, rule_type, group)

    return registry.count
