"""Nmap tool definitions - Network scanning and security audit.

Provides:
Scan tools:
- nmap_scan: Basic port scan
- nmap_quick_scan: Quick scan (top 100 ports)
- nmap_full_scan: Full port scan (all 65535 ports)
- nmap_service_scan: Service/version detection
- nmap_os_scan: OS detection

Discovery tools:
- nmap_ping_scan: Host discovery (ping scan)
- nmap_list_scan: List targets without scanning
- nmap_arp_scan: ARP discovery (local network)

Script tools:
- nmap_vuln_scan: Vulnerability scan
- nmap_script: Run specific NSE script

Output tools:
- nmap_parse_output: Parse nmap output
"""

import logging

from fastmcp import FastMCP

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import run_cmd, truncate_output

logger = logging.getLogger(__name__)


@auto_heal()
async def _nmap_scan_impl(
    target: str,
    ports: str = "",
    tcp: bool = True,
    udp: bool = False,
    timeout: int = 300,
) -> str:
    """Basic port scan."""
    cmd = ["nmap"]
    if tcp and not udp:
        cmd.append("-sT")
    elif udp and not tcp:
        cmd.append("-sU")
    elif tcp and udp:
        cmd.append("-sS")
        cmd.append("-sU")

    if ports:
        cmd.extend(["-p", ports])

    cmd.append(target)

    success, output = await run_cmd(cmd, timeout=timeout)
    if success:
        return f"## Nmap Scan: {target}\n\n```\n{output}\n```"
    return f"❌ Scan failed: {output}"


@auto_heal()
async def _nmap_quick_scan_impl(target: str, timeout: int = 120) -> str:
    """Quick scan (top 100 ports)."""
    cmd = ["nmap", "-F", target]

    success, output = await run_cmd(cmd, timeout=timeout)
    if success:
        return f"## Quick Scan: {target}\n\n```\n{output}\n```"
    return f"❌ Scan failed: {output}"


@auto_heal()
async def _nmap_full_scan_impl(target: str, timeout: int = 1800) -> str:
    """Full port scan (all 65535 ports)."""
    cmd = ["nmap", "-p-", target]

    success, output = await run_cmd(cmd, timeout=timeout)
    if success:
        return f"## Full Scan: {target}\n\n```\n{output}\n```"
    return f"❌ Scan failed: {output}"


@auto_heal()
async def _nmap_service_scan_impl(
    target: str,
    ports: str = "",
    intensity: int = 7,
    timeout: int = 600,
) -> str:
    """Service/version detection."""
    cmd = ["nmap", "-sV", f"--version-intensity={intensity}"]
    if ports:
        cmd.extend(["-p", ports])
    cmd.append(target)

    success, output = await run_cmd(cmd, timeout=timeout)
    if success:
        return f"## Service Scan: {target}\n\n```\n{output}\n```"
    return f"❌ Scan failed: {output}"


@auto_heal()
async def _nmap_os_scan_impl(target: str, timeout: int = 300) -> str:
    """OS detection (requires root)."""
    cmd = ["nmap", "-O", target]

    success, output = await run_cmd(cmd, timeout=timeout)
    if success:
        return f"## OS Detection: {target}\n\n```\n{output}\n```"
    return f"❌ Scan failed (may require root): {output}"


@auto_heal()
async def _nmap_ping_scan_impl(target: str, timeout: int = 120) -> str:
    """Host discovery (ping scan)."""
    cmd = ["nmap", "-sn", target]

    success, output = await run_cmd(cmd, timeout=timeout)
    if success:
        return f"## Ping Scan: {target}\n\n```\n{output}\n```"
    return f"❌ Scan failed: {output}"


@auto_heal()
async def _nmap_list_scan_impl(target: str) -> str:
    """List targets without scanning."""
    cmd = ["nmap", "-sL", target]

    success, output = await run_cmd(cmd, timeout=60)
    if success:
        return f"## Target List: {target}\n\n```\n{output}\n```"
    return f"❌ List failed: {output}"


@auto_heal()
async def _nmap_arp_scan_impl(target: str, timeout: int = 120) -> str:
    """ARP discovery (local network)."""
    cmd = ["nmap", "-PR", "-sn", target]

    success, output = await run_cmd(cmd, timeout=timeout)
    if success:
        return f"## ARP Scan: {target}\n\n```\n{output}\n```"
    return f"❌ Scan failed: {output}"


@auto_heal()
async def _nmap_vuln_scan_impl(
    target: str,
    ports: str = "",
    timeout: int = 900,
) -> str:
    """Vulnerability scan."""
    cmd = ["nmap", "--script=vuln"]
    if ports:
        cmd.extend(["-p", ports])
    cmd.append(target)

    success, output = await run_cmd(cmd, timeout=timeout)
    if success:
        return f"## Vulnerability Scan: {target}\n\n```\n{truncate_output(output, max_length=5000, mode='tail')}\n```"
    return f"❌ Scan failed: {output}"


@auto_heal()
async def _nmap_script_impl(
    target: str,
    script: str,
    ports: str = "",
    script_args: str = "",
    timeout: int = 600,
) -> str:
    """Run specific NSE script."""
    cmd = ["nmap", f"--script={script}"]
    if script_args:
        cmd.append(f"--script-args={script_args}")
    if ports:
        cmd.extend(["-p", ports])
    cmd.append(target)

    success, output = await run_cmd(cmd, timeout=timeout)
    if success:
        truncated = truncate_output(output, max_length=5000, mode="tail")
        return f"## Script Scan ({script}): {target}\n\n```\n{truncated}\n```"
    return f"❌ Script scan failed: {output}"


@auto_heal()
async def _nmap_ssl_scan_impl(
    target: str,
    port: int = 443,
    timeout: int = 300,
) -> str:
    """SSL/TLS scan."""
    cmd = ["nmap", "--script=ssl-enum-ciphers,ssl-cert", "-p", str(port), target]

    success, output = await run_cmd(cmd, timeout=timeout)
    if success:
        return f"## SSL Scan: {target}:{port}\n\n```\n{output}\n```"
    return f"❌ SSL scan failed: {output}"


def register_tools(server: FastMCP) -> int:
    """Register nmap tools with the MCP server."""
    registry = ToolRegistry(server)

    @auto_heal()
    @registry.tool()
    async def nmap_scan(
        target: str,
        ports: str = "",
        tcp: bool = True,
        udp: bool = False,
    ) -> str:
        """Basic port scan.

        Args:
            target: Target host/network (IP, hostname, CIDR)
            ports: Port specification (e.g., "22,80,443" or "1-1000")
            tcp: Scan TCP ports
            udp: Scan UDP ports
        """
        return await _nmap_scan_impl(target, ports, tcp, udp)

    @auto_heal()
    @registry.tool()
    async def nmap_quick_scan(target: str) -> str:
        """Quick scan (top 100 ports).

        Args:
            target: Target host/network
        """
        return await _nmap_quick_scan_impl(target)

    @auto_heal()
    @registry.tool()
    async def nmap_full_scan(target: str) -> str:
        """Full port scan (all 65535 ports).

        Args:
            target: Target host/network
        """
        return await _nmap_full_scan_impl(target)

    @auto_heal()
    @registry.tool()
    async def nmap_service_scan(
        target: str,
        ports: str = "",
    ) -> str:
        """Service/version detection.

        Args:
            target: Target host/network
            ports: Port specification
        """
        return await _nmap_service_scan_impl(target, ports)

    @auto_heal()
    @registry.tool()
    async def nmap_os_scan(target: str) -> str:
        """OS detection (may require root).

        Args:
            target: Target host
        """
        return await _nmap_os_scan_impl(target)

    @auto_heal()
    @registry.tool()
    async def nmap_ping_scan(target: str) -> str:
        """Host discovery (ping scan).

        Args:
            target: Target network (e.g., "192.168.1.0/24")
        """
        return await _nmap_ping_scan_impl(target)

    @auto_heal()
    @registry.tool()
    async def nmap_list_scan(target: str) -> str:
        """List targets without scanning.

        Args:
            target: Target specification
        """
        return await _nmap_list_scan_impl(target)

    @auto_heal()
    @registry.tool()
    async def nmap_vuln_scan(target: str, ports: str = "") -> str:
        """Vulnerability scan.

        Args:
            target: Target host
            ports: Port specification
        """
        return await _nmap_vuln_scan_impl(target, ports)

    @auto_heal()
    @registry.tool()
    async def nmap_script(
        target: str,
        script: str,
        ports: str = "",
        script_args: str = "",
    ) -> str:
        """Run specific NSE script.

        Args:
            target: Target host
            script: Script name (e.g., "http-headers", "ssh-auth-methods")
            ports: Port specification
            script_args: Script arguments
        """
        return await _nmap_script_impl(target, script, ports, script_args)

    @auto_heal()
    @registry.tool()
    async def nmap_ssl_scan(target: str, port: int = 443) -> str:
        """SSL/TLS scan.

        Args:
            target: Target host
            port: SSL port
        """
        return await _nmap_ssl_scan_impl(target, port)

    return registry.count
