"""Systemd core tools - essential service management.

This module provides the minimal set of systemd tools needed for most workflows:
- systemctl_status, systemctl_start, systemctl_stop, systemctl_restart
- systemctl_enable, systemctl_disable
- journalctl_unit: View service logs

Total: ~6 core tools (down from 16 in basic)
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
        _journalctl_unit_impl,
        _systemctl_disable_impl,
        _systemctl_enable_impl,
        _systemctl_restart_impl,
        _systemctl_start_impl,
        _systemctl_status_impl,
        _systemctl_stop_impl,
    )
except ImportError:
    # Direct loading - use importlib to avoid sys.path pollution
    _basic_file = Path(__file__).parent / "tools_basic.py"
    _spec = importlib.util.spec_from_file_location("systemd_tools_basic", _basic_file)
    _basic_module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_basic_module)
    _journalctl_unit_impl = _basic_module._journalctl_unit_impl
    _systemctl_disable_impl = _basic_module._systemctl_disable_impl
    _systemctl_enable_impl = _basic_module._systemctl_enable_impl
    _systemctl_restart_impl = _basic_module._systemctl_restart_impl
    _systemctl_start_impl = _basic_module._systemctl_start_impl
    _systemctl_status_impl = _basic_module._systemctl_status_impl
    _systemctl_stop_impl = _basic_module._systemctl_stop_impl

logger = logging.getLogger(__name__)


def register_tools(server: FastMCP) -> int:
    """Register core systemd tools."""
    registry = ToolRegistry(server)

    @auto_heal()
    @registry.tool()
    async def systemctl_status(unit: str, user: bool = False) -> str:
        """Get status of a systemd unit."""
        return await _systemctl_status_impl(unit, user)

    @auto_heal()
    @registry.tool()
    async def systemctl_start(unit: str, user: bool = False) -> str:
        """Start a systemd unit."""
        return await _systemctl_start_impl(unit, user)

    @auto_heal()
    @registry.tool()
    async def systemctl_stop(unit: str, user: bool = False) -> str:
        """Stop a systemd unit."""
        return await _systemctl_stop_impl(unit, user)

    @auto_heal()
    @registry.tool()
    async def systemctl_restart(unit: str, user: bool = False) -> str:
        """Restart a systemd unit."""
        return await _systemctl_restart_impl(unit, user)

    @auto_heal()
    @registry.tool()
    async def systemctl_enable(unit: str, now: bool = False, user: bool = False) -> str:
        """Enable a systemd unit."""
        return await _systemctl_enable_impl(unit, now, user)

    @auto_heal()
    @registry.tool()
    async def systemctl_disable(unit: str, now: bool = False, user: bool = False) -> str:
        """Disable a systemd unit."""
        return await _systemctl_disable_impl(unit, now, user)

    @auto_heal()
    @registry.tool()
    async def journalctl_unit(unit: str, lines: int = 100, since: str = "") -> str:
        """View logs for a systemd unit."""
        return await _journalctl_unit_impl(unit, lines, since)

    logger.info(f"Registered {registry.count} core systemd tools")
    return registry.count
