"""Docker tool definitions - Container management tools.

Provides:
Compose tools:
- docker_compose_status: Check container status
- docker_compose_up: Start docker-compose services
- docker_compose_down: Stop and remove docker-compose services
- docker_compose_logs: View logs from docker-compose services
- docker_compose_restart: Restart docker-compose services

Container tools:
- docker_ps: List containers
- docker_logs: View container logs
- docker_exec: Execute commands in containers
- docker_cp: Copy files to/from containers
- docker_start: Start a stopped container
- docker_stop: Stop a running container
- docker_restart: Restart a container
- docker_rm: Remove a container
- docker_inspect: Inspect a Docker object

Volume tools:
- docker_volume_list: List volumes
- docker_volume_rm: Remove a volume
- docker_volume_prune: Remove unused volumes

Network tools:
- docker_network_list: List networks
- docker_network_inspect: Inspect a network
- docker_network_create: Create a network
- docker_network_rm: Remove a network

Image tools:
- docker_images: List images
- docker_image_rm: Remove an image

System tools:
- docker_system_prune: Remove unused Docker data
"""

import logging

from fastmcp import FastMCP

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import run_cmd, truncate_output

logger = logging.getLogger(__name__)

from tool_modules.aa_docker.src.docker_tools_impl import (  # pylint: disable=ungrouped-imports,wrong-import-position
    _docker_compose_down_impl,
    _docker_compose_logs_impl,
    _docker_compose_restart_impl,
    _docker_compose_status_impl,
    _docker_compose_up_impl,
    _docker_cp_impl,
    _docker_exec_impl,
    _docker_logs_impl,
    _docker_network_create_impl,
    _docker_network_inspect_impl,
    _docker_network_list_impl,
    _docker_network_rm_impl,
    _docker_ps_impl,
    _docker_volume_list_impl,
    _docker_volume_prune_impl,
    _docker_volume_rm_impl,
)


@auto_heal()
async def _docker_stop_impl(
    container: str,
    timeout: int = 10,
) -> str:
    """
    Stop a running Docker container.

    Args:
        container: Container name or ID
        timeout: Seconds to wait before killing

    Returns:
        Stop result.
    """
    cmd = ["docker", "stop", "-t", str(timeout), container]

    success, output = await run_cmd(cmd, timeout=timeout + 30)

    if success:
        return f"✅ Container '{container}' stopped"
    return f"❌ Failed to stop container: {output}"


@auto_heal()
async def _docker_start_impl(
    container: str,
) -> str:
    """
    Start a stopped Docker container.

    Args:
        container: Container name or ID

    Returns:
        Start result.
    """
    cmd = ["docker", "start", container]

    success, output = await run_cmd(cmd, timeout=30)

    if success:
        return f"✅ Container '{container}' started"
    return f"❌ Failed to start container: {output}"


@auto_heal()
async def _docker_restart_impl(
    container: str,
    timeout: int = 10,
) -> str:
    """
    Restart a Docker container.

    Args:
        container: Container name or ID
        timeout: Seconds to wait before killing

    Returns:
        Restart result.
    """
    cmd = ["docker", "restart", "-t", str(timeout), container]

    success, output = await run_cmd(cmd, timeout=timeout + 30)

    if success:
        return f"✅ Container '{container}' restarted"
    return f"❌ Failed to restart container: {output}"


@auto_heal()
async def _docker_rm_impl(
    container: str,
    force: bool = False,
    volumes: bool = False,
) -> str:
    """
    Remove a Docker container.

    Args:
        container: Container name or ID
        force: Force removal of running container
        volumes: Remove associated volumes

    Returns:
        Removal result.
    """
    cmd = ["docker", "rm"]
    if force:
        cmd.append("-")
    if volumes:
        cmd.append("-v")
    cmd.append(container)

    success, output = await run_cmd(cmd, timeout=30)

    if success:
        return f"✅ Container '{container}' removed"
    return f"❌ Failed to remove container: {output}"


@auto_heal()
async def _docker_images_impl(
    filter_name: str = "",
    all_images: bool = False,
    dangling: bool = False,
) -> str:
    """
    List Docker images.

    Args:
        filter_name: Filter by image name/reference
        all_images: Show all images (including intermediate)
        dangling: Show only dangling images

    Returns:
        Image list.
    """
    cmd = [
        "docker",
        "images",
        "--format",
        "table {{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.Size}}\t{{.CreatedSince}}",
    ]
    if all_images:
        cmd.append("-a")
    if filter_name:
        cmd.extend(["--filter", f"reference={filter_name}"])
    if dangling:
        cmd.extend(["--filter", "dangling=true"])

    success, output = await run_cmd(cmd, timeout=30)

    if not success:
        return f"❌ Failed to list images: {output}"

    return f"## Docker Images\n\n```\n{output}\n```"


@auto_heal()
async def _docker_image_rm_impl(
    image: str,
    force: bool = False,
) -> str:
    """
    Remove a Docker image.

    Args:
        image: Image name, ID, or tag
        force: Force removal

    Returns:
        Removal result.
    """
    cmd = ["docker", "rmi"]
    if force:
        cmd.append("-")
    cmd.append(image)

    success, output = await run_cmd(cmd, timeout=60)

    if success:
        return f"✅ Image '{image}' removed"
    return f"❌ Failed to remove image: {output}"


@auto_heal()
async def _docker_system_prune_impl(
    all_unused: bool = False,
    volumes: bool = False,
    force: bool = True,
) -> str:
    """
    Remove unused Docker data (containers, networks, images).

    Args:
        all_unused: Remove all unused images, not just dangling
        volumes: Also prune volumes
        force: Skip confirmation prompt

    Returns:
        Prune result.
    """
    cmd = ["docker", "system", "prune"]
    if all_unused:
        cmd.append("-a")
    if volumes:
        cmd.append("--volumes")
    if force:
        cmd.append("-")

    success, output = await run_cmd(cmd, timeout=120)

    if success:
        return f"✅ System prune completed\n\n{output}"
    return f"❌ Failed to prune system: {output}"


@auto_heal()
async def _docker_inspect_impl(
    target: str,
    format_str: str = "",
) -> str:
    """
    Inspect a Docker object (container, image, volume, network).

    Args:
        target: Name or ID of the object to inspect
        format_str: Go template format string (optional)

    Returns:
        Object details in JSON format.
    """
    cmd = ["docker", "inspect"]
    if format_str:
        cmd.extend(["--format", format_str])
    cmd.append(target)

    success, output = await run_cmd(cmd, timeout=30)

    if success:
        return f"## Docker Inspect: {target}\n\n```json\n{truncate_output(output, max_length=5000, mode='head')}\n```"  # pylint: disable=line-too-long
    return f"❌ Failed to inspect: {output}"


def register_tools(server: FastMCP) -> int:  # pylint: disable=too-many-locals
    """
    Register docker tools with the MCP server.

    Args:
        server: FastMCP server instance

    Returns:
        Number of tools registered
    """
    registry = ToolRegistry(server)

    @auto_heal()
    @registry.tool()
    async def docker_compose_status(
        repo: str,
        filter_name: str = "",
    ) -> str:
        """
        Check docker-compose container status.

        Args:
            repo: Repository path (where docker-compose.yml is)
            filter_name: Filter containers by name

        Returns:
            Container status.
        """
        return await _docker_compose_status_impl(repo, filter_name)

    @auto_heal()
    @registry.tool()
    async def docker_compose_up(
        repo: str,
        detach: bool = True,
        services: str = "",
        timeout: int = 180,
    ) -> str:
        """
        Start docker-compose services.

        Args:
            repo: Repository path (where docker-compose.yml is)
            detach: Run in background
            services: Specific services to start (space-separated, empty = all)
            timeout: Timeout in seconds

        Returns:
            Startup result.
        """
        return await _docker_compose_up_impl(repo, detach, services, timeout)

    @auto_heal()
    @registry.tool()
    async def docker_cp(
        source: str,
        destination: str,
        to_container: bool = True,
    ) -> str:
        """
        Copy files to/from a Docker container.

        Args:
            source: Source path (local path or container:path)
            destination: Destination path (container:path or local path)
            to_container: If True, copy from local to container

        Returns:
            Copy result.

        Examples:
            docker_cp("/tmp/script.sh", "my_container:/tmp/script.sh", to_container=True)
            docker_cp("my_container:/var/log/app.log", "/tmp/app.log", to_container=False)
        """
        return await _docker_cp_impl(source, destination, to_container)

    @auto_heal()
    @registry.tool()
    async def docker_exec(
        container: str,
        command: str,
        timeout: int = 300,
    ) -> str:
        """
        Execute a command in a running Docker container.

        Args:
            container: Container name or ID
            command: Command to execute
            timeout: Timeout in seconds

        Returns:
            Command output.
        """
        return await _docker_exec_impl(container, command, timeout)

    @auto_heal()
    @registry.tool()
    async def docker_compose_down(
        repo: str,
        volumes: bool = False,
        remove_orphans: bool = False,
        timeout: int = 120,
    ) -> str:
        """
        Stop and remove docker-compose services.

        Args:
            repo: Repository path (where docker-compose.yml is)
            volumes: Also remove volumes
            remove_orphans: Remove containers for services not defined in compose file
            timeout: Timeout in seconds

        Returns:
            Shutdown result.
        """
        return await _docker_compose_down_impl(repo, volumes, remove_orphans, timeout)

    @auto_heal()
    @registry.tool()
    async def docker_compose_logs(
        repo: str,
        services: str = "",
        tail: int = 100,
        follow: bool = False,
        timeout: int = 30,
    ) -> str:
        """
        View logs from docker-compose services.

        Args:
            repo: Repository path (where docker-compose.yml is)
            services: Specific services (space-separated, empty = all)
            tail: Number of lines to show from end
            follow: Stream logs (not recommended for tool use)
            timeout: Timeout in seconds

        Returns:
            Service logs.
        """
        return await _docker_compose_logs_impl(repo, services, tail, follow, timeout)

    @auto_heal()
    @registry.tool()
    async def docker_compose_restart(
        repo: str,
        services: str = "",
        timeout: int = 120,
    ) -> str:
        """
        Restart docker-compose services.

        Args:
            repo: Repository path (where docker-compose.yml is)
            services: Specific services to restart (space-separated, empty = all)
            timeout: Timeout in seconds

        Returns:
            Restart result.
        """
        return await _docker_compose_restart_impl(repo, services, timeout)

    @auto_heal()
    @registry.tool()
    async def docker_ps(
        all_containers: bool = False,
        filter_name: str = "",
        filter_status: str = "",
    ) -> str:
        """
        List Docker containers.

        Args:
            all_containers: Show all containers (including stopped)
            filter_name: Filter by container name
            filter_status: Filter by status (running, exited, paused, etc.)

        Returns:
            Container list.
        """
        return await _docker_ps_impl(all_containers, filter_name, filter_status)

    @auto_heal()
    @registry.tool()
    async def docker_logs(
        container: str,
        tail: int = 100,
        since: str = "",
        timestamps: bool = False,
    ) -> str:
        """
        View logs from a Docker container.

        Args:
            container: Container name or ID
            tail: Number of lines to show from end
            since: Show logs since timestamp (e.g., "10m", "2h", "2024-01-01")
            timestamps: Show timestamps

        Returns:
            Container logs.
        """
        return await _docker_logs_impl(container, tail, since, timestamps)

    @auto_heal()
    @registry.tool()
    async def docker_volume_list(
        filter_name: str = "",
        filter_dangling: bool = False,
    ) -> str:
        """
        List Docker volumes.

        Args:
            filter_name: Filter by volume name pattern
            filter_dangling: Show only dangling (unused) volumes

        Returns:
            Volume list.
        """
        return await _docker_volume_list_impl(filter_name, filter_dangling)

    @auto_heal()
    @registry.tool()
    async def docker_volume_rm(
        volume: str,
        force: bool = False,
    ) -> str:
        """
        Remove a Docker volume.

        Args:
            volume: Volume name to remove
            force: Force removal even if in use

        Returns:
            Removal result.
        """
        return await _docker_volume_rm_impl(volume, force)

    @auto_heal()
    @registry.tool()
    async def docker_volume_prune(
        force: bool = True,
    ) -> str:
        """
        Remove all unused Docker volumes.

        Args:
            force: Skip confirmation prompt

        Returns:
            Prune result.
        """
        return await _docker_volume_prune_impl(force)

    @auto_heal()
    @registry.tool()
    async def docker_network_list(
        filter_name: str = "",
        filter_driver: str = "",
    ) -> str:
        """
        List Docker networks.

        Args:
            filter_name: Filter by network name pattern
            filter_driver: Filter by driver (bridge, host, overlay, etc.)

        Returns:
            Network list.
        """
        return await _docker_network_list_impl(filter_name, filter_driver)

    @auto_heal()
    @registry.tool()
    async def docker_network_inspect(
        network: str,
    ) -> str:
        """
        Inspect a Docker network.

        Args:
            network: Network name or ID

        Returns:
            Network details including connected containers.
        """
        return await _docker_network_inspect_impl(network)

    @auto_heal()
    @registry.tool()
    async def docker_network_create(
        name: str,
        driver: str = "bridge",
        subnet: str = "",
    ) -> str:
        """
        Create a Docker network.

        Args:
            name: Network name
            driver: Network driver (bridge, overlay, host, none)
            subnet: Subnet in CIDR format (e.g., "172.28.0.0/16")

        Returns:
            Creation result.
        """
        return await _docker_network_create_impl(name, driver, subnet)

    @auto_heal()
    @registry.tool()
    async def docker_network_rm(
        network: str,
    ) -> str:
        """
        Remove a Docker network.

        Args:
            network: Network name or ID

        Returns:
            Removal result.
        """
        return await _docker_network_rm_impl(network)

    @auto_heal()
    @registry.tool()
    async def docker_stop(
        container: str,
        timeout: int = 10,
    ) -> str:
        """
        Stop a running Docker container.

        Args:
            container: Container name or ID
            timeout: Seconds to wait before killing

        Returns:
            Stop result.
        """
        return await _docker_stop_impl(container, timeout)

    @auto_heal()
    @registry.tool()
    async def docker_start(
        container: str,
    ) -> str:
        """
        Start a stopped Docker container.

        Args:
            container: Container name or ID

        Returns:
            Start result.
        """
        return await _docker_start_impl(container)

    @auto_heal()
    @registry.tool()
    async def docker_restart(
        container: str,
        timeout: int = 10,
    ) -> str:
        """
        Restart a Docker container.

        Args:
            container: Container name or ID
            timeout: Seconds to wait before killing

        Returns:
            Restart result.
        """
        return await _docker_restart_impl(container, timeout)

    @auto_heal()
    @registry.tool()
    async def docker_rm(
        container: str,
        force: bool = False,
        volumes: bool = False,
    ) -> str:
        """
        Remove a Docker container.

        Args:
            container: Container name or ID
            force: Force removal of running container
            volumes: Remove associated volumes

        Returns:
            Removal result.
        """
        return await _docker_rm_impl(container, force, volumes)

    @auto_heal()
    @registry.tool()
    async def docker_images(
        filter_name: str = "",
        all_images: bool = False,
        dangling: bool = False,
    ) -> str:
        """
        List Docker images.

        Args:
            filter_name: Filter by image name/reference
            all_images: Show all images (including intermediate)
            dangling: Show only dangling images

        Returns:
            Image list.
        """
        return await _docker_images_impl(filter_name, all_images, dangling)

    @auto_heal()
    @registry.tool()
    async def docker_image_rm(
        image: str,
        force: bool = False,
    ) -> str:
        """
        Remove a Docker image.

        Args:
            image: Image name, ID, or tag
            force: Force removal

        Returns:
            Removal result.
        """
        return await _docker_image_rm_impl(image, force)

    @auto_heal()
    @registry.tool()
    async def docker_system_prune(
        all_unused: bool = False,
        volumes: bool = False,
        force: bool = True,
    ) -> str:
        """
        Remove unused Docker data (containers, networks, images).

        Args:
            all_unused: Remove all unused images, not just dangling
            volumes: Also prune volumes
            force: Skip confirmation prompt

        Returns:
            Prune result.
        """
        return await _docker_system_prune_impl(all_unused, volumes, force)

    @auto_heal()
    @registry.tool()
    async def docker_inspect(
        target: str,
        format_str: str = "",
    ) -> str:
        """
        Inspect a Docker object (container, image, volume, network).

        Args:
            target: Name or ID of the object to inspect
            format_str: Go template format string (optional)

        Returns:
            Object details in JSON format.
        """
        return await _docker_inspect_impl(target, format_str)

    return registry.count
