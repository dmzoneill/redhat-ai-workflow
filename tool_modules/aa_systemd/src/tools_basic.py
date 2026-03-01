"""Systemd tool definitions - Service and system management.

Provides:
Service tools:
- systemctl_status: Get service status
- systemctl_start: Start service
- systemctl_stop: Stop service
- systemctl_restart: Restart service
- systemctl_enable: Enable service at boot
- systemctl_disable: Disable service at boot
- systemctl_list_units: List units
- systemctl_list_unit_files: List unit files
- systemctl_is_active: Check if service is active
- systemctl_is_enabled: Check if service is enabled

Journal tools:
- journalctl_logs: View journal logs
- journalctl_unit: View logs for specific unit
- journalctl_boot: View logs from current/previous boot
- journalctl_follow: Get recent logs (tail-like)

System tools:
- systemctl_daemon_reload: Reload systemd configuration
- hostnamectl_status: Get hostname info
- timedatectl_status: Get time/date info
"""

import logging

from fastmcp import FastMCP

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import run_cmd, truncate_output

logger = logging.getLogger(__name__)


def _build_systemctl_cmd(user: bool, action: str, *args: str) -> list[str]:
    """Build systemctl command. Args: user, action, then positional args (unit, --no-pager, etc)."""
    cmd = ["systemctl"]
    if user:
        cmd.append("--user")
    cmd.append(action)
    cmd.extend(args)
    return cmd


@auto_heal()
async def _systemctl_status_impl(unit: str, user: bool = False) -> str:
    """Get service status."""
    cmd = _build_systemctl_cmd(user, "status", unit, "--no-pager")

    success, output = await run_cmd(cmd, timeout=30)
    # systemctl status returns non-zero for inactive services
    return f"## Service Status: {unit}\n\n```\n{output}\n```"


@auto_heal()
async def _systemctl_start_impl(unit: str, user: bool = False) -> str:
    """Start service."""
    cmd = _build_systemctl_cmd(user, "start", unit)

    success, output = await run_cmd(cmd, timeout=60)
    if success:
        return f"✅ Started {unit}"
    return f"❌ Failed to start {unit}: {output}"


@auto_heal()
async def _systemctl_stop_impl(unit: str, user: bool = False) -> str:
    """Stop service."""
    cmd = _build_systemctl_cmd(user, "stop", unit)

    success, output = await run_cmd(cmd, timeout=60)
    if success:
        return f"✅ Stopped {unit}"
    return f"❌ Failed to stop {unit}: {output}"


@auto_heal()
async def _systemctl_restart_impl(unit: str, user: bool = False) -> str:
    """Restart service."""
    cmd = _build_systemctl_cmd(user, "restart", unit)

    success, output = await run_cmd(cmd, timeout=60)
    if success:
        return f"✅ Restarted {unit}"
    return f"❌ Failed to restart {unit}: {output}"


@auto_heal()
async def _systemctl_enable_impl(
    unit: str, now: bool = False, user: bool = False
) -> str:
    """Enable service at boot."""
    args = ["enable", unit]
    if now:
        args.append("--now")
    cmd = _build_systemctl_cmd(user, *args)

    success, output = await run_cmd(cmd, timeout=30)
    if success:
        return f"✅ Enabled {unit}\n\n{output}"
    return f"❌ Failed to enable {unit}: {output}"


@auto_heal()
async def _systemctl_disable_impl(
    unit: str, now: bool = False, user: bool = False
) -> str:
    """Disable service at boot."""
    args = ["disable", unit]
    if now:
        args.append("--now")
    cmd = _build_systemctl_cmd(user, *args)

    success, output = await run_cmd(cmd, timeout=30)
    if success:
        return f"✅ Disabled {unit}\n\n{output}"
    return f"❌ Failed to disable {unit}: {output}"


@auto_heal()
async def _systemctl_list_units_impl(
    type_filter: str = "",
    state: str = "",
    user: bool = False,
) -> str:
    """List units."""
    args = ["list-units", "--no-pager"]
    if type_filter:
        args.extend(["--type", type_filter])
    if state:
        args.extend(["--state", state])
    cmd = _build_systemctl_cmd(user, *args)

    success, output = await run_cmd(cmd, timeout=30)
    if success:
        return f"## Systemd Units\n\n```\n{truncate_output(output, max_length=5000, mode='head')}\n```"
    return f"❌ Failed to list units: {output}"


@auto_heal()
async def _systemctl_list_unit_files_impl(
    type_filter: str = "",
    state: str = "",
    user: bool = False,
) -> str:
    """List unit files."""
    args = ["list-unit-files", "--no-pager"]
    if type_filter:
        args.extend(["--type", type_filter])
    if state:
        args.extend(["--state", state])
    cmd = _build_systemctl_cmd(user, *args)

    success, output = await run_cmd(cmd, timeout=30)
    if success:
        return f"## Unit Files\n\n```\n{truncate_output(output, max_length=5000, mode='head')}\n```"
    return f"❌ Failed to list unit files: {output}"


@auto_heal()
async def _systemctl_is_active_impl(unit: str, user: bool = False) -> str:
    """Check if service is active."""
    cmd = _build_systemctl_cmd(user, "is-active", unit)

    success, output = await run_cmd(cmd, timeout=30)
    status = output.strip()
    icon = "🟢" if status == "active" else "🔴"
    return f"{icon} **{unit}**: {status}"


@auto_heal()
async def _systemctl_is_enabled_impl(unit: str, user: bool = False) -> str:
    """Check if service is enabled."""
    cmd = _build_systemctl_cmd(user, "is-enabled", unit)

    success, output = await run_cmd(cmd, timeout=30)
    status = output.strip()
    icon = "✅" if status == "enabled" else "⭕"
    return f"{icon} **{unit}**: {status}"


@auto_heal()
async def _journalctl_logs_impl(
    lines: int = 100,
    since: str = "",
    until: str = "",
    priority: str = "",
    grep: str = "",
) -> str:
    """View journal logs."""
    cmd = ["journalctl", "--no-pager", "-n", str(lines)]
    if since:
        cmd.extend(["--since", since])
    if until:
        cmd.extend(["--until", until])
    if priority:
        cmd.extend(["-p", priority])
    if grep:
        cmd.extend(["-g", grep])

    success, output = await run_cmd(cmd, timeout=60)
    if success:
        return f"## Journal Logs\n\n```\n{truncate_output(output, max_length=5000, mode='tail')}\n```"
    return f"❌ Failed to get logs: {output}"


@auto_heal()
async def _journalctl_unit_impl(
    unit: str,
    lines: int = 100,
    since: str = "",
    follow: bool = False,
    user: bool = False,
    until: str = "",
) -> str:
    """View logs for specific unit."""
    cmd = ["journalctl", "--no-pager", "-u", unit, "-n", str(lines)]
    if user:
        cmd.insert(1, "--user")
    if since:
        cmd.extend(["--since", since])
    if until:
        cmd.extend(["--until", until])

    success, output = await run_cmd(cmd, timeout=60)
    if success:
        return f"## Logs: {unit}\n\n```\n{truncate_output(output, max_length=5000, mode='tail')}\n```"
    return f"❌ Failed to get logs: {output}"


@auto_heal()
async def _journalctl_boot_impl(boot: int = 0, lines: int = 200) -> str:
    """View logs from current/previous boot."""
    cmd = ["journalctl", "--no-pager", "-b", str(boot), "-n", str(lines)]

    success, output = await run_cmd(cmd, timeout=60)
    if success:
        boot_desc = "current" if boot == 0 else f"boot {boot}"
        return f"## Boot Logs ({boot_desc})\n\n```\n{truncate_output(output, max_length=5000, mode='tail')}\n```"
    return f"❌ Failed to get boot logs: {output}"


@auto_heal()
async def _systemctl_daemon_reload_impl(user: bool = False) -> str:
    """Reload systemd configuration."""
    cmd = ["systemctl"]
    if user:
        cmd.append("--user")
    cmd.append("daemon-reload")

    success, output = await run_cmd(cmd, timeout=30)
    if success:
        return "✅ Daemon configuration reloaded"
    return f"❌ Failed to reload: {output}"


@auto_heal()
async def _hostnamectl_status_impl() -> str:
    """Get hostname info."""
    cmd = ["hostnamectl", "status"]

    success, output = await run_cmd(cmd, timeout=30)
    if success:
        return f"## Hostname Info\n\n```\n{output}\n```"
    return f"❌ Failed to get hostname info: {output}"


@auto_heal()
async def _timedatectl_status_impl() -> str:
    """Get time/date info."""
    cmd = ["timedatectl", "status"]

    success, output = await run_cmd(cmd, timeout=30)
    if success:
        return f"## Time/Date Info\n\n```\n{output}\n```"
    return f"❌ Failed to get time info: {output}"


def register_tools(server: FastMCP) -> int:
    """Register systemd tools with the MCP server."""
    registry = ToolRegistry(server)

    @auto_heal()
    @registry.tool()
    async def systemctl_status(unit: str, user: bool = False) -> str:
        """Get service status.

        Args:
            unit: Service/unit name
            user: Use user session (--user)
        """
        return await _systemctl_status_impl(unit, user)

    @auto_heal()
    @registry.tool()
    async def systemctl_start(unit: str, user: bool = False) -> str:
        """Start service.

        Args:
            unit: Service/unit name
            user: Use user session
        """
        return await _systemctl_start_impl(unit, user)

    @auto_heal()
    @registry.tool()
    async def systemctl_stop(unit: str, user: bool = False) -> str:
        """Stop service.

        Args:
            unit: Service/unit name
            user: Use user session
        """
        return await _systemctl_stop_impl(unit, user)

    @auto_heal()
    @registry.tool()
    async def systemctl_restart(unit: str, user: bool = False) -> str:
        """Restart service.

        Args:
            unit: Service/unit name
            user: Use user session
        """
        return await _systemctl_restart_impl(unit, user)

    @auto_heal()
    @registry.tool()
    async def systemctl_enable(unit: str, now: bool = False, user: bool = False) -> str:
        """Enable service at boot.

        Args:
            unit: Service/unit name
            now: Also start the service now
            user: Use user session
        """
        return await _systemctl_enable_impl(unit, now, user)

    @auto_heal()
    @registry.tool()
    async def systemctl_disable(
        unit: str, now: bool = False, user: bool = False
    ) -> str:
        """Disable service at boot.

        Args:
            unit: Service/unit name
            now: Also stop the service now
            user: Use user session
        """
        return await _systemctl_disable_impl(unit, now, user)

    @auto_heal()
    @registry.tool()
    async def systemctl_list_units(
        type_filter: str = "",
        state: str = "",
        user: bool = False,
    ) -> str:
        """List systemd units.

        Args:
            type_filter: Filter by type (service, socket, timer, etc.)
            state: Filter by state (running, failed, etc.)
            user: Use user session
        """
        return await _systemctl_list_units_impl(type_filter, state, user)

    @auto_heal()
    @registry.tool()
    async def systemctl_list_unit_files(
        type_filter: str = "",
        state: str = "",
        user: bool = False,
    ) -> str:
        """List unit files.

        Args:
            type_filter: Filter by type
            state: Filter by state (enabled, disabled, etc.)
            user: Use user session
        """
        return await _systemctl_list_unit_files_impl(type_filter, state, user)

    @auto_heal()
    @registry.tool()
    async def systemctl_is_active(unit: str, user: bool = False) -> str:
        """Check if service is active.

        Args:
            unit: Service/unit name
            user: Use user session
        """
        return await _systemctl_is_active_impl(unit, user)

    @auto_heal()
    @registry.tool()
    async def systemctl_is_enabled(unit: str, user: bool = False) -> str:
        """Check if service is enabled.

        Args:
            unit: Service/unit name
            user: Use user session
        """
        return await _systemctl_is_enabled_impl(unit, user)

    @auto_heal()
    @registry.tool()
    async def journalctl_logs(
        lines: int = 100,
        since: str = "",
        priority: str = "",
        grep: str = "",
    ) -> str:
        """View journal logs.

        Args:
            lines: Number of lines to show
            since: Show logs since (e.g., "1 hour ago", "2024-01-01")
            priority: Filter by priority (emerg, alert, crit, err, warning, notice, info, debug)
            grep: Filter by pattern
        """
        return await _journalctl_logs_impl(lines, since, "", priority, grep)

    @auto_heal()
    @registry.tool()
    async def journalctl_unit(
        unit: str, lines: int = 100, since: str = "", user: bool = False
    ) -> str:
        """View logs for specific unit.

        Args:
            unit: Service/unit name
            lines: Number of lines to show
            since: Show logs since
            user: Use user session (for --user services)
        """
        return await _journalctl_unit_impl(unit, lines, since, user=user)

    @auto_heal()
    @registry.tool()
    async def journalctl_boot(boot: int = 0, lines: int = 200) -> str:
        """View logs from current/previous boot.

        Args:
            boot: Boot offset (0=current, -1=previous, etc.)
            lines: Number of lines to show
        """
        return await _journalctl_boot_impl(boot, lines)

    @auto_heal()
    @registry.tool()
    async def systemctl_daemon_reload(user: bool = False) -> str:
        """Reload systemd configuration.

        Args:
            user: Use user session
        """
        return await _systemctl_daemon_reload_impl(user)

    @auto_heal()
    @registry.tool()
    async def hostnamectl_status() -> str:
        """Get hostname info."""
        return await _hostnamectl_status_impl()

    @auto_heal()
    @registry.tool()
    async def timedatectl_status() -> str:
        """Get time/date info."""
        return await _timedatectl_status_impl()

    return registry.count
