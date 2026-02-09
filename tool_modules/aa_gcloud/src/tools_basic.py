"""Google Cloud CLI tool definitions - GCP management.

Provides:
Compute tools:
- gcloud_compute_instances_list: List compute instances
- gcloud_compute_instances_start: Start instances
- gcloud_compute_instances_stop: Stop instances
- gcloud_compute_instances_describe: Get instance details

Storage tools:
- gcloud_storage_ls: List storage buckets/objects
- gcloud_storage_cp: Copy files to/from GCS
- gcloud_storage_rm: Remove storage objects

Project tools:
- gcloud_projects_list: List projects
- gcloud_config_list: Show current configuration
- gcloud_config_set_project: Set active project

Auth tools:
- gcloud_auth_list: List authenticated accounts
- gcloud_auth_print_identity_token: Get identity token

GKE tools:
- gcloud_container_clusters_list: List GKE clusters
- gcloud_container_clusters_get_credentials: Get cluster credentials
"""

import logging
import os

from fastmcp import FastMCP

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import run_cmd, truncate_output

logger = logging.getLogger(__name__)


def _get_gcloud_env() -> dict:
    """Get environment variables for gcloud commands."""
    env = os.environ.copy()
    return env


@auto_heal()
async def _gcloud_compute_instances_list_impl(
    project: str = "",
    zone: str = "",
    filter_expr: str = "",
) -> str:
    """List compute instances."""
    cmd = ["gcloud", "compute", "instances", "list", "--format=table"]
    if project:
        cmd.extend(["--project", project])
    if zone:
        cmd.extend(["--zones", zone])
    if filter_expr:
        cmd.extend(["--filter", filter_expr])

    success, output = await run_cmd(cmd, timeout=60, env=_get_gcloud_env())
    if success:
        return f"## Compute Instances\n\n```\n{output}\n```"
    return f"❌ Failed to list instances: {output}"


@auto_heal()
async def _gcloud_compute_instances_start_impl(
    instance: str,
    zone: str,
    project: str = "",
) -> str:
    """Start compute instance."""
    cmd = ["gcloud", "compute", "instances", "start", instance, "--zone", zone]
    if project:
        cmd.extend(["--project", project])

    success, output = await run_cmd(cmd, timeout=120, env=_get_gcloud_env())
    if success:
        return f"✅ Started instance {instance}\n\n{output}"
    return f"❌ Failed to start instance: {output}"


@auto_heal()
async def _gcloud_compute_instances_stop_impl(
    instance: str,
    zone: str,
    project: str = "",
) -> str:
    """Stop compute instance."""
    cmd = ["gcloud", "compute", "instances", "stop", instance, "--zone", zone]
    if project:
        cmd.extend(["--project", project])

    success, output = await run_cmd(cmd, timeout=120, env=_get_gcloud_env())
    if success:
        return f"✅ Stopped instance {instance}\n\n{output}"
    return f"❌ Failed to stop instance: {output}"


@auto_heal()
async def _gcloud_compute_instances_describe_impl(
    instance: str,
    zone: str,
    project: str = "",
) -> str:
    """Get instance details."""
    cmd = ["gcloud", "compute", "instances", "describe", instance, "--zone", zone]
    if project:
        cmd.extend(["--project", project])

    success, output = await run_cmd(cmd, timeout=60, env=_get_gcloud_env())
    if success:
        return f"## Instance: {instance}\n\n```yaml\n{truncate_output(output, max_length=5000, mode='head')}\n```"
    return f"❌ Failed to describe instance: {output}"


@auto_heal()
async def _gcloud_storage_ls_impl(
    path: str = "",
    recursive: bool = False,
    long_listing: bool = False,
) -> str:
    """List storage buckets/objects."""
    cmd = ["gcloud", "storage", "ls"]
    if path:
        cmd.append(path)
    if recursive:
        cmd.append("--recursive")
    if long_listing:
        cmd.append("-l")

    success, output = await run_cmd(cmd, timeout=60, env=_get_gcloud_env())
    if success:
        return f"## Storage Listing\n\n```\n{truncate_output(output, max_length=5000, mode='tail')}\n```"
    return f"❌ Failed to list storage: {output}"


@auto_heal()
async def _gcloud_storage_cp_impl(
    source: str,
    destination: str,
    recursive: bool = False,
    timeout: int = 300,
) -> str:
    """Copy files to/from GCS."""
    cmd = ["gcloud", "storage", "cp", source, destination]
    if recursive:
        cmd.append("--recursive")

    success, output = await run_cmd(cmd, timeout=timeout, env=_get_gcloud_env())
    if success:
        return f"✅ Copied {source} to {destination}\n\n{output}"
    return f"❌ Copy failed: {output}"


@auto_heal()
async def _gcloud_storage_rm_impl(
    path: str,
    recursive: bool = False,
) -> str:
    """Remove storage objects."""
    cmd = ["gcloud", "storage", "rm", path]
    if recursive:
        cmd.append("--recursive")

    success, output = await run_cmd(cmd, timeout=120, env=_get_gcloud_env())
    if success:
        return f"✅ Removed {path}\n\n{output}"
    return f"❌ Remove failed: {output}"


@auto_heal()
async def _gcloud_projects_list_impl() -> str:
    """List projects."""
    cmd = ["gcloud", "projects", "list", "--format=table"]

    success, output = await run_cmd(cmd, timeout=60, env=_get_gcloud_env())
    if success:
        return f"## GCP Projects\n\n```\n{output}\n```"
    return f"❌ Failed to list projects: {output}"


@auto_heal()
async def _gcloud_config_list_impl() -> str:
    """Show current configuration."""
    cmd = ["gcloud", "config", "list"]

    success, output = await run_cmd(cmd, timeout=30, env=_get_gcloud_env())
    if success:
        return f"## GCloud Configuration\n\n```\n{output}\n```"
    return f"❌ Failed to list config: {output}"


@auto_heal()
async def _gcloud_config_set_project_impl(project: str) -> str:
    """Set active project."""
    cmd = ["gcloud", "config", "set", "project", project]

    success, output = await run_cmd(cmd, timeout=30, env=_get_gcloud_env())
    if success:
        return f"✅ Set project to {project}"
    return f"❌ Failed to set project: {output}"


@auto_heal()
async def _gcloud_auth_list_impl() -> str:
    """List authenticated accounts."""
    cmd = ["gcloud", "auth", "list"]

    success, output = await run_cmd(cmd, timeout=30, env=_get_gcloud_env())
    if success:
        return f"## Authenticated Accounts\n\n```\n{output}\n```"
    return f"❌ Failed to list accounts: {output}"


@auto_heal()
async def _gcloud_auth_print_identity_token_impl() -> str:
    """Get identity token."""
    cmd = ["gcloud", "auth", "print-identity-token"]

    success, output = await run_cmd(cmd, timeout=30, env=_get_gcloud_env())
    if success:
        return f"## Identity Token\n\n```\n{output[:50]}...{output[-20:]}\n```"
    return f"❌ Failed to get token: {output}"


@auto_heal()
async def _gcloud_container_clusters_list_impl(
    project: str = "",
    region: str = "",
) -> str:
    """List GKE clusters."""
    cmd = ["gcloud", "container", "clusters", "list", "--format=table"]
    if project:
        cmd.extend(["--project", project])
    if region:
        cmd.extend(["--region", region])

    success, output = await run_cmd(cmd, timeout=60, env=_get_gcloud_env())
    if success:
        return f"## GKE Clusters\n\n```\n{output}\n```"
    return f"❌ Failed to list clusters: {output}"


@auto_heal()
async def _gcloud_container_clusters_get_credentials_impl(
    cluster: str,
    zone: str = "",
    region: str = "",
    project: str = "",
) -> str:
    """Get cluster credentials."""
    cmd = ["gcloud", "container", "clusters", "get-credentials", cluster]
    if zone:
        cmd.extend(["--zone", zone])
    if region:
        cmd.extend(["--region", region])
    if project:
        cmd.extend(["--project", project])

    success, output = await run_cmd(cmd, timeout=60, env=_get_gcloud_env())
    if success:
        return f"✅ Got credentials for cluster {cluster}\n\n{output}"
    return f"❌ Failed to get credentials: {output}"


def register_tools(server: FastMCP) -> int:
    """Register GCloud tools with the MCP server."""
    registry = ToolRegistry(server)

    @auto_heal()
    @registry.tool()
    async def gcloud_compute_instances_list(
        project: str = "",
        zone: str = "",
    ) -> str:
        """List compute instances.

        Args:
            project: GCP project ID
            zone: Zone filter
        """
        return await _gcloud_compute_instances_list_impl(project, zone)

    @auto_heal()
    @registry.tool()
    async def gcloud_compute_instances_start(
        instance: str,
        zone: str,
        project: str = "",
    ) -> str:
        """Start compute instance.

        Args:
            instance: Instance name
            zone: Instance zone
            project: GCP project ID
        """
        return await _gcloud_compute_instances_start_impl(instance, zone, project)

    @auto_heal()
    @registry.tool()
    async def gcloud_compute_instances_stop(
        instance: str,
        zone: str,
        project: str = "",
    ) -> str:
        """Stop compute instance.

        Args:
            instance: Instance name
            zone: Instance zone
            project: GCP project ID
        """
        return await _gcloud_compute_instances_stop_impl(instance, zone, project)

    @auto_heal()
    @registry.tool()
    async def gcloud_compute_instances_describe(
        instance: str,
        zone: str,
        project: str = "",
    ) -> str:
        """Get instance details.

        Args:
            instance: Instance name
            zone: Instance zone
            project: GCP project ID
        """
        return await _gcloud_compute_instances_describe_impl(instance, zone, project)

    @auto_heal()
    @registry.tool()
    async def gcloud_storage_ls(
        path: str = "",
        recursive: bool = False,
    ) -> str:
        """List storage buckets/objects.

        Args:
            path: GCS path (gs://bucket/prefix)
            recursive: List recursively
        """
        return await _gcloud_storage_ls_impl(path, recursive)

    @auto_heal()
    @registry.tool()
    async def gcloud_storage_cp(
        source: str,
        destination: str,
        recursive: bool = False,
    ) -> str:
        """Copy files to/from GCS.

        Args:
            source: Source path
            destination: Destination path
            recursive: Copy recursively
        """
        return await _gcloud_storage_cp_impl(source, destination, recursive)

    @auto_heal()
    @registry.tool()
    async def gcloud_storage_rm(path: str, recursive: bool = False) -> str:
        """Remove storage objects.

        Args:
            path: GCS path to remove
            recursive: Remove recursively
        """
        return await _gcloud_storage_rm_impl(path, recursive)

    @auto_heal()
    @registry.tool()
    async def gcloud_projects_list() -> str:
        """List GCP projects."""
        return await _gcloud_projects_list_impl()

    @auto_heal()
    @registry.tool()
    async def gcloud_config_list() -> str:
        """Show current gcloud configuration."""
        return await _gcloud_config_list_impl()

    @auto_heal()
    @registry.tool()
    async def gcloud_config_set_project(project: str) -> str:
        """Set active GCP project.

        Args:
            project: Project ID to set
        """
        return await _gcloud_config_set_project_impl(project)

    @auto_heal()
    @registry.tool()
    async def gcloud_auth_list() -> str:
        """List authenticated accounts."""
        return await _gcloud_auth_list_impl()

    @auto_heal()
    @registry.tool()
    async def gcloud_container_clusters_list(
        project: str = "",
        region: str = "",
    ) -> str:
        """List GKE clusters.

        Args:
            project: GCP project ID
            region: Region filter
        """
        return await _gcloud_container_clusters_list_impl(project, region)

    @auto_heal()
    @registry.tool()
    async def gcloud_container_clusters_get_credentials(
        cluster: str,
        zone: str = "",
        region: str = "",
        project: str = "",
    ) -> str:
        """Get GKE cluster credentials.

        Args:
            cluster: Cluster name
            zone: Cluster zone (for zonal clusters)
            region: Cluster region (for regional clusters)
            project: GCP project ID
        """
        return await _gcloud_container_clusters_get_credentials_impl(
            cluster, zone, region, project
        )

    return registry.count
