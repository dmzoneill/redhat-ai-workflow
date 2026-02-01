"""Docker core tools - essential container operations.

This module provides the minimal set of Docker tools needed for most workflows:
- docker_ps: List running containers
- docker_logs: View container logs
- docker_exec: Execute commands in containers
- docker_images: List images
- docker_stop, docker_start: Container lifecycle
- docker_compose_status, docker_compose_up: Compose operations

Total: ~8 core tools (down from 24 in basic)
"""

import logging

from fastmcp import FastMCP

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
        _docker_compose_status_impl,
        _docker_compose_up_impl,
        _docker_exec_impl,
        _docker_images_impl,
        _docker_logs_impl,
        _docker_ps_impl,
        _docker_start_impl,
        _docker_stop_impl,
    )
except ImportError:
    # Direct loading - use importlib to avoid sys.path pollution
    _basic_file = Path(__file__).parent / "tools_basic.py"
    _spec = importlib.util.spec_from_file_location("docker_tools_basic", _basic_file)
    _basic_module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_basic_module)
    _docker_compose_status_impl = _basic_module._docker_compose_status_impl
    _docker_compose_up_impl = _basic_module._docker_compose_up_impl
    _docker_exec_impl = _basic_module._docker_exec_impl
    _docker_images_impl = _basic_module._docker_images_impl
    _docker_logs_impl = _basic_module._docker_logs_impl
    _docker_ps_impl = _basic_module._docker_ps_impl
    _docker_start_impl = _basic_module._docker_start_impl
    _docker_stop_impl = _basic_module._docker_stop_impl

logger = logging.getLogger(__name__)


def register_tools(server: FastMCP) -> int:
    """Register core Docker tools."""
    registry = ToolRegistry(server)

    @auto_heal()
    @registry.tool()
    async def docker_ps(all_containers: bool = False, format: str = "") -> str:
        """List Docker containers."""
        return await _docker_ps_impl(all_containers, format)

    @auto_heal()
    @registry.tool()
    async def docker_logs(container: str, tail: int = 100, follow: bool = False) -> str:
        """View container logs."""
        return await _docker_logs_impl(container, tail, follow)

    @auto_heal()
    @registry.tool()
    async def docker_exec(container: str, command: str, interactive: bool = False) -> str:
        """Execute command in a container."""
        return await _docker_exec_impl(container, command, interactive)

    @auto_heal()
    @registry.tool()
    async def docker_images(all_images: bool = False) -> str:
        """List Docker images."""
        return await _docker_images_impl(all_images)

    @auto_heal()
    @registry.tool()
    async def docker_stop(container: str, timeout: int = 10) -> str:
        """Stop a running container."""
        return await _docker_stop_impl(container, timeout)

    @auto_heal()
    @registry.tool()
    async def docker_start(container: str) -> str:
        """Start a stopped container."""
        return await _docker_start_impl(container)

    @auto_heal()
    @registry.tool()
    async def docker_compose_status(project_dir: str = ".") -> str:
        """Get docker-compose service status."""
        return await _docker_compose_status_impl(project_dir)

    @auto_heal()
    @registry.tool()
    async def docker_compose_up(project_dir: str = ".", detach: bool = True, build: bool = False) -> str:
        """Start docker-compose services."""
        return await _docker_compose_up_impl(project_dir, detach, build)

    logger.info(f"Registered {registry.count} core Docker tools")
    return registry.count
