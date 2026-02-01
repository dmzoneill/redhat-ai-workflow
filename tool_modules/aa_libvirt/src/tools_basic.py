"""Libvirt/virsh tool definitions - KVM/QEMU virtual machine management.

Provides:
VM Lifecycle tools:
- virsh_list: List virtual machines
- virsh_start: Start a VM
- virsh_shutdown: Gracefully shutdown a VM
- virsh_destroy: Force stop a VM
- virsh_reboot: Reboot a VM
- virsh_suspend: Suspend a VM
- virsh_resume: Resume a suspended VM
- virsh_undefine: Remove VM definition

VM Creation tools:
- virt_install: Create a new VM with virt-install
- virsh_define: Define a VM from XML
- virsh_clone: Clone an existing VM

VM Information tools:
- virsh_dominfo: Get VM information
- virsh_domstate: Get VM state
- virsh_domblklist: List VM block devices
- virsh_domiflist: List VM network interfaces
- virsh_dumpxml: Dump VM XML configuration
- virsh_vcpuinfo: Get VM vCPU information
- virsh_memtune: Get/set VM memory parameters

Snapshot tools:
- virsh_snapshot_create: Create a VM snapshot
- virsh_snapshot_list: List VM snapshots
- virsh_snapshot_revert: Revert to a snapshot
- virsh_snapshot_delete: Delete a snapshot

Storage tools:
- virsh_pool_list: List storage pools
- virsh_pool_info: Get storage pool info
- virsh_vol_list: List volumes in a pool
- virsh_vol_create: Create a new volume
- virsh_vol_delete: Delete a volume
- virsh_vol_resize: Resize a volume

Network tools:
- virsh_net_list: List virtual networks
- virsh_net_info: Get network information
- virsh_net_start: Start a network
- virsh_net_destroy: Stop a network

Console/Display tools:
- virsh_console: Get console connection info
- virsh_vncdisplay: Get VNC display port
- virsh_screenshot: Take VM screenshot
"""

import logging
import os
from pathlib import Path

from fastmcp import FastMCP

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import run_cmd, truncate_output

logger = logging.getLogger(__name__)


def _get_virsh_env() -> dict:
    """Get environment variables for virsh commands.

    Returns:
        Environment dict with libvirt variables set.
    """
    env = os.environ.copy()
    # Default to system connection if not set
    env.setdefault("LIBVIRT_DEFAULT_URI", "qemu:///system")
    return env


# =============================================================================
# VM Lifecycle Tools
# =============================================================================


@auto_heal()
async def _virsh_list_impl(
    all_vms: bool = True,
    state: str = "",
) -> str:
    """
    List virtual machines.

    Args:
        all_vms: Show all VMs including inactive
        state: Filter by state (running, paused, shutoff, etc.)

    Returns:
        List of VMs with their states.
    """
    cmd = ["virsh", "list"]
    if all_vms:
        cmd.append("--all")
    if state:
        cmd.extend(["--state-" + state])

    success, output = await run_cmd(cmd, timeout=30, env=_get_virsh_env())

    if success:
        return f"## Virtual Machines\n\n```\n{output}\n```"
    return f"❌ Failed to list VMs: {output}"


@auto_heal()
async def _virsh_start_impl(
    domain: str,
) -> str:
    """
    Start a virtual machine.

    Args:
        domain: VM name or UUID

    Returns:
        Start result.
    """
    cmd = ["virsh", "start", domain]

    success, output = await run_cmd(cmd, timeout=60, env=_get_virsh_env())

    if success:
        return f"✅ VM '{domain}' started\n\n{output}"
    return f"❌ Failed to start VM: {output}"


@auto_heal()
async def _virsh_shutdown_impl(
    domain: str,
    mode: str = "",
) -> str:
    """
    Gracefully shutdown a virtual machine.

    Args:
        domain: VM name or UUID
        mode: Shutdown mode (acpi, agent, initctl, signal, paravirt)

    Returns:
        Shutdown result.
    """
    cmd = ["virsh", "shutdown", domain]
    if mode:
        cmd.extend(["--mode", mode])

    success, output = await run_cmd(cmd, timeout=60, env=_get_virsh_env())

    if success:
        return f"✅ Shutdown signal sent to '{domain}'\n\n{output}"
    return f"❌ Failed to shutdown VM: {output}"


@auto_heal()
async def _virsh_destroy_impl(
    domain: str,
    graceful: bool = False,
) -> str:
    """
    Force stop a virtual machine (like pulling the power cord).

    Args:
        domain: VM name or UUID
        graceful: Try graceful destroy first

    Returns:
        Destroy result.
    """
    cmd = ["virsh", "destroy", domain]
    if graceful:
        cmd.append("--graceful")

    success, output = await run_cmd(cmd, timeout=30, env=_get_virsh_env())

    if success:
        return f"✅ VM '{domain}' destroyed\n\n{output}"
    return f"❌ Failed to destroy VM: {output}"


@auto_heal()
async def _virsh_reboot_impl(
    domain: str,
    mode: str = "",
) -> str:
    """
    Reboot a virtual machine.

    Args:
        domain: VM name or UUID
        mode: Reboot mode (acpi, agent, initctl, signal, paravirt)

    Returns:
        Reboot result.
    """
    cmd = ["virsh", "reboot", domain]
    if mode:
        cmd.extend(["--mode", mode])

    success, output = await run_cmd(cmd, timeout=60, env=_get_virsh_env())

    if success:
        return f"✅ Reboot signal sent to '{domain}'\n\n{output}"
    return f"❌ Failed to reboot VM: {output}"


@auto_heal()
async def _virsh_suspend_impl(
    domain: str,
) -> str:
    """
    Suspend a virtual machine.

    Args:
        domain: VM name or UUID

    Returns:
        Suspend result.
    """
    cmd = ["virsh", "suspend", domain]

    success, output = await run_cmd(cmd, timeout=30, env=_get_virsh_env())

    if success:
        return f"✅ VM '{domain}' suspended\n\n{output}"
    return f"❌ Failed to suspend VM: {output}"


@auto_heal()
async def _virsh_resume_impl(
    domain: str,
) -> str:
    """
    Resume a suspended virtual machine.

    Args:
        domain: VM name or UUID

    Returns:
        Resume result.
    """
    cmd = ["virsh", "resume", domain]

    success, output = await run_cmd(cmd, timeout=30, env=_get_virsh_env())

    if success:
        return f"✅ VM '{domain}' resumed\n\n{output}"
    return f"❌ Failed to resume VM: {output}"


@auto_heal()
async def _virsh_undefine_impl(
    domain: str,
    remove_all_storage: bool = False,
    nvram: bool = False,
    snapshots_metadata: bool = False,
) -> str:
    """
    Remove a VM definition (undefine).

    Args:
        domain: VM name or UUID
        remove_all_storage: Also remove all associated storage volumes
        nvram: Also remove NVRAM file
        snapshots_metadata: Also remove snapshot metadata

    Returns:
        Undefine result.
    """
    cmd = ["virsh", "undefine", domain]
    if remove_all_storage:
        cmd.append("--remove-all-storage")
    if nvram:
        cmd.append("--nvram")
    if snapshots_metadata:
        cmd.append("--snapshots-metadata")

    success, output = await run_cmd(cmd, timeout=60, env=_get_virsh_env())

    if success:
        return f"✅ VM '{domain}' undefined\n\n{output}"
    return f"❌ Failed to undefine VM: {output}"


# =============================================================================
# VM Creation Tools
# =============================================================================


@auto_heal()
async def _virt_install_impl(
    name: str,
    memory: int,
    vcpus: int,
    disk_size: int = 20,
    disk_path: str = "",
    cdrom: str = "",
    location: str = "",
    os_variant: str = "",
    network: str = "default",
    graphics: str = "vnc",
    extra_args: str = "",
    autostart: bool = False,
    noautoconsole: bool = True,
    timeout: int = 600,
) -> str:
    """
    Create a new virtual machine with virt-install.

    Args:
        name: VM name
        memory: Memory in MB
        vcpus: Number of virtual CPUs
        disk_size: Disk size in GB (used if disk_path not specified)
        disk_path: Path to existing disk image or where to create new one
        cdrom: Path to ISO file for CD-ROM boot
        location: Installation source URL or path (for network install)
        os_variant: OS variant (e.g., "rhel9.0", "fedora38", "ubuntu22.04")
        network: Network name or config (default: "default")
        graphics: Graphics type (vnc, spice, none)
        extra_args: Extra kernel arguments for installation
        autostart: Start VM automatically on host boot
        noautoconsole: Don't automatically connect to console
        timeout: Timeout in seconds

    Returns:
        Installation result.

    Examples:
        # Create VM from ISO
        virt_install(name="myvm", memory=2048, vcpus=2, cdrom="/path/to/install.iso", os_variant="rhel9.0")

        # Create VM with network install
        virt_install(name="myvm", memory=2048, vcpus=2, location="http://mirror/rhel9/", os_variant="rhel9.0")
    """
    cmd = [
        "virt-install",
        "--name",
        name,
        "--memory",
        str(memory),
        "--vcpus",
        str(vcpus),
    ]

    # Disk configuration
    if disk_path:
        cmd.extend(["--disk", f"path={disk_path},size={disk_size}"])
    else:
        cmd.extend(["--disk", f"size={disk_size}"])

    # Installation source
    if cdrom:
        cmd.extend(["--cdrom", cdrom])
    elif location:
        cmd.extend(["--location", location])
    else:
        cmd.append("--import")  # Import existing disk

    # OS variant for optimizations
    if os_variant:
        cmd.extend(["--os-variant", os_variant])

    # Network
    if network:
        if "=" in network:
            cmd.extend(["--network", network])
        else:
            cmd.extend(["--network", f"network={network}"])

    # Graphics
    cmd.extend(["--graphics", graphics])

    # Extra kernel args
    if extra_args:
        cmd.extend(["--extra-args", extra_args])

    # Options
    if autostart:
        cmd.append("--autostart")
    if noautoconsole:
        cmd.append("--noautoconsole")

    success, output = await run_cmd(cmd, timeout=timeout, env=_get_virsh_env())

    if success:
        truncated = truncate_output(output, max_length=3000, mode="tail")
        return f"✅ VM '{name}' created successfully\n\n```\n{truncated}\n```"
    truncated = truncate_output(output, max_length=3000, mode="tail")
    return f"❌ Failed to create VM:\n\n```\n{truncated}\n```"


@auto_heal()
async def _virsh_define_impl(
    xml_file: str,
) -> str:
    """
    Define a VM from an XML configuration file.

    Args:
        xml_file: Path to XML definition file

    Returns:
        Define result.
    """
    xml_path = Path(xml_file).expanduser()
    if not xml_path.exists():
        return f"❌ XML file not found: {xml_path}"

    cmd = ["virsh", "define", str(xml_path)]

    success, output = await run_cmd(cmd, timeout=30, env=_get_virsh_env())

    if success:
        return f"✅ VM defined from {xml_path.name}\n\n{output}"
    return f"❌ Failed to define VM: {output}"


@auto_heal()
async def _virsh_clone_impl(
    original: str,
    name: str,
    auto_clone: bool = True,
    file: str = "",
) -> str:
    """
    Clone an existing virtual machine.

    Args:
        original: Source VM name
        name: New VM name
        auto_clone: Automatically generate new disk paths
        file: Specific path for cloned disk

    Returns:
        Clone result.
    """
    cmd = ["virt-clone", "--original", original, "--name", name]

    if auto_clone:
        cmd.append("--auto-clone")
    if file:
        cmd.extend(["--file", file])

    success, output = await run_cmd(cmd, timeout=300, env=_get_virsh_env())

    if success:
        return f"✅ VM '{original}' cloned to '{name}'\n\n{output}"
    return f"❌ Failed to clone VM: {output}"


# =============================================================================
# VM Information Tools
# =============================================================================


@auto_heal()
async def _virsh_dominfo_impl(
    domain: str,
) -> str:
    """
    Get detailed information about a VM.

    Args:
        domain: VM name or UUID

    Returns:
        VM information.
    """
    cmd = ["virsh", "dominfo", domain]

    success, output = await run_cmd(cmd, timeout=30, env=_get_virsh_env())

    if success:
        return f"## VM Info: {domain}\n\n```\n{output}\n```"
    return f"❌ Failed to get VM info: {output}"


@auto_heal()
async def _virsh_domstate_impl(
    domain: str,
    reason: bool = True,
) -> str:
    """
    Get the current state of a VM.

    Args:
        domain: VM name or UUID
        reason: Show reason for current state

    Returns:
        VM state.
    """
    cmd = ["virsh", "domstate", domain]
    if reason:
        cmd.append("--reason")

    success, output = await run_cmd(cmd, timeout=30, env=_get_virsh_env())

    if success:
        state = output.strip()
        icon = "🟢" if "running" in state.lower() else "🔴" if "shut" in state.lower() else "🟡"
        return f"{icon} **{domain}**: {state}"
    return f"❌ Failed to get VM state: {output}"


@auto_heal()
async def _virsh_domblklist_impl(
    domain: str,
    details: bool = True,
) -> str:
    """
    List block devices attached to a VM.

    Args:
        domain: VM name or UUID
        details: Show additional details

    Returns:
        Block device list.
    """
    cmd = ["virsh", "domblklist", domain]
    if details:
        cmd.append("--details")

    success, output = await run_cmd(cmd, timeout=30, env=_get_virsh_env())

    if success:
        return f"## Block Devices: {domain}\n\n```\n{output}\n```"
    return f"❌ Failed to list block devices: {output}"


@auto_heal()
async def _virsh_domiflist_impl(
    domain: str,
) -> str:
    """
    List network interfaces attached to a VM.

    Args:
        domain: VM name or UUID

    Returns:
        Network interface list.
    """
    cmd = ["virsh", "domiflist", domain]

    success, output = await run_cmd(cmd, timeout=30, env=_get_virsh_env())

    if success:
        return f"## Network Interfaces: {domain}\n\n```\n{output}\n```"
    return f"❌ Failed to list interfaces: {output}"


@auto_heal()
async def _virsh_dumpxml_impl(
    domain: str,
    inactive: bool = False,
    migratable: bool = False,
) -> str:
    """
    Dump VM XML configuration.

    Args:
        domain: VM name or UUID
        inactive: Show inactive (defined) configuration
        migratable: Show migratable XML

    Returns:
        VM XML configuration.
    """
    cmd = ["virsh", "dumpxml", domain]
    if inactive:
        cmd.append("--inactive")
    if migratable:
        cmd.append("--migratable")

    success, output = await run_cmd(cmd, timeout=30, env=_get_virsh_env())

    if success:
        return f"## XML: {domain}\n\n```xml\n{truncate_output(output, max_length=5000, mode='head')}\n```"
    return f"❌ Failed to dump XML: {output}"


@auto_heal()
async def _virsh_vcpuinfo_impl(
    domain: str,
) -> str:
    """
    Get vCPU information for a VM.

    Args:
        domain: VM name or UUID

    Returns:
        vCPU information.
    """
    cmd = ["virsh", "vcpuinfo", domain]

    success, output = await run_cmd(cmd, timeout=30, env=_get_virsh_env())

    if success:
        return f"## vCPU Info: {domain}\n\n```\n{output}\n```"
    return f"❌ Failed to get vCPU info: {output}"


@auto_heal()
async def _virsh_memtune_impl(
    domain: str,
    hard_limit: int = 0,
    soft_limit: int = 0,
    swap_hard_limit: int = 0,
) -> str:
    """
    Get or set VM memory parameters.

    Args:
        domain: VM name or UUID
        hard_limit: Hard memory limit in KB (0 = query only)
        soft_limit: Soft memory limit in KB (0 = query only)
        swap_hard_limit: Swap hard limit in KB (0 = query only)

    Returns:
        Memory parameters.
    """
    cmd = ["virsh", "memtune", domain]

    if hard_limit > 0:
        cmd.extend(["--hard-limit", str(hard_limit)])
    if soft_limit > 0:
        cmd.extend(["--soft-limit", str(soft_limit)])
    if swap_hard_limit > 0:
        cmd.extend(["--swap-hard-limit", str(swap_hard_limit)])

    success, output = await run_cmd(cmd, timeout=30, env=_get_virsh_env())

    if success:
        return f"## Memory Tune: {domain}\n\n```\n{output}\n```"
    return f"❌ Failed to get/set memory parameters: {output}"


# =============================================================================
# Snapshot Tools
# =============================================================================


@auto_heal()
async def _virsh_snapshot_create_impl(
    domain: str,
    name: str = "",
    description: str = "",
    disk_only: bool = False,
    quiesce: bool = False,
) -> str:
    """
    Create a VM snapshot.

    Args:
        domain: VM name or UUID
        name: Snapshot name (auto-generated if not specified)
        description: Snapshot description
        disk_only: Create disk-only snapshot (no memory)
        quiesce: Quiesce guest filesystem (requires guest agent)

    Returns:
        Snapshot creation result.
    """
    cmd = ["virsh", "snapshot-create-as", domain]

    if name:
        cmd.append(name)
    if description:
        cmd.extend(["--description", description])
    if disk_only:
        cmd.append("--disk-only")
    if quiesce:
        cmd.append("--quiesce")

    success, output = await run_cmd(cmd, timeout=120, env=_get_virsh_env())

    if success:
        return f"✅ Snapshot created for '{domain}'\n\n{output}"
    return f"❌ Failed to create snapshot: {output}"


@auto_heal()
async def _virsh_snapshot_list_impl(
    domain: str,
    tree: bool = False,
) -> str:
    """
    List snapshots for a VM.

    Args:
        domain: VM name or UUID
        tree: Show snapshot tree hierarchy

    Returns:
        Snapshot list.
    """
    cmd = ["virsh", "snapshot-list", domain]
    if tree:
        cmd.append("--tree")

    success, output = await run_cmd(cmd, timeout=30, env=_get_virsh_env())

    if success:
        return f"## Snapshots: {domain}\n\n```\n{output}\n```"
    return f"❌ Failed to list snapshots: {output}"


@auto_heal()
async def _virsh_snapshot_revert_impl(
    domain: str,
    snapshot: str,
    running: bool = False,
    paused: bool = False,
) -> str:
    """
    Revert VM to a snapshot.

    Args:
        domain: VM name or UUID
        snapshot: Snapshot name
        running: Start VM after revert
        paused: Pause VM after revert

    Returns:
        Revert result.
    """
    cmd = ["virsh", "snapshot-revert", domain, snapshot]
    if running:
        cmd.append("--running")
    if paused:
        cmd.append("--paused")

    success, output = await run_cmd(cmd, timeout=120, env=_get_virsh_env())

    if success:
        return f"✅ Reverted '{domain}' to snapshot '{snapshot}'\n\n{output}"
    return f"❌ Failed to revert snapshot: {output}"


@auto_heal()
async def _virsh_snapshot_delete_impl(
    domain: str,
    snapshot: str,
    children: bool = False,
    metadata: bool = False,
) -> str:
    """
    Delete a VM snapshot.

    Args:
        domain: VM name or UUID
        snapshot: Snapshot name
        children: Also delete child snapshots
        metadata: Delete only metadata (keep disk data)

    Returns:
        Delete result.
    """
    cmd = ["virsh", "snapshot-delete", domain, snapshot]
    if children:
        cmd.append("--children")
    if metadata:
        cmd.append("--metadata")

    success, output = await run_cmd(cmd, timeout=120, env=_get_virsh_env())

    if success:
        return f"✅ Deleted snapshot '{snapshot}' from '{domain}'\n\n{output}"
    return f"❌ Failed to delete snapshot: {output}"


# =============================================================================
# Storage Tools
# =============================================================================


@auto_heal()
async def _virsh_pool_list_impl(
    all_pools: bool = True,
    details: bool = True,
) -> str:
    """
    List storage pools.

    Args:
        all_pools: Show all pools including inactive
        details: Show additional details

    Returns:
        Storage pool list.
    """
    cmd = ["virsh", "pool-list"]
    if all_pools:
        cmd.append("--all")
    if details:
        cmd.append("--details")

    success, output = await run_cmd(cmd, timeout=30, env=_get_virsh_env())

    if success:
        return f"## Storage Pools\n\n```\n{output}\n```"
    return f"❌ Failed to list pools: {output}"


@auto_heal()
async def _virsh_pool_info_impl(
    pool: str,
) -> str:
    """
    Get storage pool information.

    Args:
        pool: Pool name

    Returns:
        Pool information.
    """
    cmd = ["virsh", "pool-info", pool]

    success, output = await run_cmd(cmd, timeout=30, env=_get_virsh_env())

    if success:
        return f"## Pool Info: {pool}\n\n```\n{output}\n```"
    return f"❌ Failed to get pool info: {output}"


@auto_heal()
async def _virsh_vol_list_impl(
    pool: str,
    details: bool = True,
) -> str:
    """
    List volumes in a storage pool.

    Args:
        pool: Pool name
        details: Show additional details

    Returns:
        Volume list.
    """
    cmd = ["virsh", "vol-list", pool]
    if details:
        cmd.append("--details")

    success, output = await run_cmd(cmd, timeout=30, env=_get_virsh_env())

    if success:
        return f"## Volumes in {pool}\n\n```\n{output}\n```"
    return f"❌ Failed to list volumes: {output}"


@auto_heal()
async def _virsh_vol_create_impl(
    pool: str,
    name: str,
    capacity: str,
    format_type: str = "qcow2",
    allocation: str = "",
) -> str:
    """
    Create a new storage volume.

    Args:
        pool: Pool name
        name: Volume name
        capacity: Volume capacity (e.g., "20G", "100M")
        format_type: Volume format (qcow2, raw, vmdk)
        allocation: Initial allocation (e.g., "1G")

    Returns:
        Volume creation result.
    """
    cmd = [
        "virsh",
        "vol-create-as",
        pool,
        name,
        capacity,
        "--format",
        format_type,
    ]
    if allocation:
        cmd.extend(["--allocation", allocation])

    success, output = await run_cmd(cmd, timeout=120, env=_get_virsh_env())

    if success:
        return f"✅ Volume '{name}' created in pool '{pool}'\n\n{output}"
    return f"❌ Failed to create volume: {output}"


@auto_heal()
async def _virsh_vol_delete_impl(
    pool: str,
    vol: str,
) -> str:
    """
    Delete a storage volume.

    Args:
        pool: Pool name
        vol: Volume name

    Returns:
        Delete result.
    """
    cmd = ["virsh", "vol-delete", "--pool", pool, vol]

    success, output = await run_cmd(cmd, timeout=60, env=_get_virsh_env())

    if success:
        return f"✅ Volume '{vol}' deleted from pool '{pool}'"
    return f"❌ Failed to delete volume: {output}"


@auto_heal()
async def _virsh_vol_resize_impl(
    pool: str,
    vol: str,
    capacity: str,
    shrink: bool = False,
) -> str:
    """
    Resize a storage volume.

    Args:
        pool: Pool name
        vol: Volume name
        capacity: New capacity (e.g., "50G") or delta (e.g., "+10G")
        shrink: Allow shrinking (dangerous!)

    Returns:
        Resize result.
    """
    cmd = ["virsh", "vol-resize", "--pool", pool, vol, capacity]
    if shrink:
        cmd.append("--shrink")

    success, output = await run_cmd(cmd, timeout=120, env=_get_virsh_env())

    if success:
        return f"✅ Volume '{vol}' resized to {capacity}\n\n{output}"
    return f"❌ Failed to resize volume: {output}"


# =============================================================================
# Network Tools
# =============================================================================


@auto_heal()
async def _virsh_net_list_impl(
    all_nets: bool = True,
) -> str:
    """
    List virtual networks.

    Args:
        all_nets: Show all networks including inactive

    Returns:
        Network list.
    """
    cmd = ["virsh", "net-list"]
    if all_nets:
        cmd.append("--all")

    success, output = await run_cmd(cmd, timeout=30, env=_get_virsh_env())

    if success:
        return f"## Virtual Networks\n\n```\n{output}\n```"
    return f"❌ Failed to list networks: {output}"


@auto_heal()
async def _virsh_net_info_impl(
    network: str,
) -> str:
    """
    Get virtual network information.

    Args:
        network: Network name

    Returns:
        Network information.
    """
    cmd = ["virsh", "net-info", network]

    success, output = await run_cmd(cmd, timeout=30, env=_get_virsh_env())

    if success:
        return f"## Network Info: {network}\n\n```\n{output}\n```"
    return f"❌ Failed to get network info: {output}"


@auto_heal()
async def _virsh_net_start_impl(
    network: str,
) -> str:
    """
    Start a virtual network.

    Args:
        network: Network name

    Returns:
        Start result.
    """
    cmd = ["virsh", "net-start", network]

    success, output = await run_cmd(cmd, timeout=30, env=_get_virsh_env())

    if success:
        return f"✅ Network '{network}' started\n\n{output}"
    return f"❌ Failed to start network: {output}"


@auto_heal()
async def _virsh_net_destroy_impl(
    network: str,
) -> str:
    """
    Stop a virtual network.

    Args:
        network: Network name

    Returns:
        Stop result.
    """
    cmd = ["virsh", "net-destroy", network]

    success, output = await run_cmd(cmd, timeout=30, env=_get_virsh_env())

    if success:
        return f"✅ Network '{network}' stopped\n\n{output}"
    return f"❌ Failed to stop network: {output}"


# =============================================================================
# Console/Display Tools
# =============================================================================


@auto_heal()
async def _virsh_console_info_impl(
    domain: str,
) -> str:
    """
    Get console connection information for a VM.

    Args:
        domain: VM name or UUID

    Returns:
        Console connection info.
    """
    # Get TTY info
    cmd = ["virsh", "ttyconsole", domain]
    success, tty_output = await run_cmd(cmd, timeout=30, env=_get_virsh_env())

    info = [f"## Console Info: {domain}", ""]

    if success and tty_output.strip():
        info.append(f"**TTY Console**: `{tty_output.strip()}`")
        info.append("")
        info.append("Connect with: `virsh console " + domain + "`")
    else:
        info.append("No TTY console available")

    return "\n".join(info)


@auto_heal()
async def _virsh_vncdisplay_impl(
    domain: str,
) -> str:
    """
    Get VNC display port for a VM.

    Args:
        domain: VM name or UUID

    Returns:
        VNC display information.
    """
    cmd = ["virsh", "vncdisplay", domain]

    success, output = await run_cmd(cmd, timeout=30, env=_get_virsh_env())

    if success:
        display = output.strip()
        if display:
            # Parse display number (e.g., ":0" means port 5900)
            if display.startswith(":"):
                port = 5900 + int(display[1:])
                return (
                    f"## VNC Display: {domain}\n\n"
                    f"Display: `{display}`\nPort: `{port}`\n\n"
                    f"Connect with: `vncviewer localhost{display}`"
                )
            return f"## VNC Display: {domain}\n\n{display}"
        return f"⚠️ No VNC display configured for '{domain}'"
    return f"❌ Failed to get VNC display: {output}"


@auto_heal()
async def _virsh_screenshot_impl(
    domain: str,
    file: str = "",
) -> str:
    """
    Take a screenshot of a VM's display.

    Args:
        domain: VM name or UUID
        file: Output file path (default: /tmp/{domain}-screenshot.ppm)

    Returns:
        Screenshot result.
    """
    if not file:
        file = f"/tmp/{domain}-screenshot.ppm"

    cmd = ["virsh", "screenshot", domain, "--file", file]

    success, output = await run_cmd(cmd, timeout=30, env=_get_virsh_env())

    if success:
        return f"✅ Screenshot saved to: {file}\n\n{output}"
    return f"❌ Failed to take screenshot: {output}"


# =============================================================================
# Tool Registration
# =============================================================================


def register_tools(server: FastMCP) -> int:
    """
    Register libvirt/virsh tools with the MCP server.

    Args:
        server: FastMCP server instance

    Returns:
        Number of tools registered
    """
    registry = ToolRegistry(server)

    # VM Lifecycle tools
    @auto_heal()
    @registry.tool()
    async def virsh_list(
        all_vms: bool = True,
        state: str = "",
    ) -> str:
        """
        List virtual machines.

        Args:
            all_vms: Show all VMs including inactive
            state: Filter by state (running, paused, shutoff, etc.)

        Returns:
            List of VMs with their states.
        """
        return await _virsh_list_impl(all_vms, state)

    @auto_heal()
    @registry.tool()
    async def virsh_start(domain: str) -> str:
        """
        Start a virtual machine.

        Args:
            domain: VM name or UUID

        Returns:
            Start result.
        """
        return await _virsh_start_impl(domain)

    @auto_heal()
    @registry.tool()
    async def virsh_shutdown(domain: str, mode: str = "") -> str:
        """
        Gracefully shutdown a virtual machine.

        Args:
            domain: VM name or UUID
            mode: Shutdown mode (acpi, agent, initctl, signal, paravirt)

        Returns:
            Shutdown result.
        """
        return await _virsh_shutdown_impl(domain, mode)

    @auto_heal()
    @registry.tool()
    async def virsh_destroy(domain: str, graceful: bool = False) -> str:
        """
        Force stop a virtual machine (like pulling the power cord).

        Args:
            domain: VM name or UUID
            graceful: Try graceful destroy first

        Returns:
            Destroy result.
        """
        return await _virsh_destroy_impl(domain, graceful)

    @auto_heal()
    @registry.tool()
    async def virsh_reboot(domain: str, mode: str = "") -> str:
        """
        Reboot a virtual machine.

        Args:
            domain: VM name or UUID
            mode: Reboot mode (acpi, agent, initctl, signal, paravirt)

        Returns:
            Reboot result.
        """
        return await _virsh_reboot_impl(domain, mode)

    @auto_heal()
    @registry.tool()
    async def virsh_suspend(domain: str) -> str:
        """
        Suspend a virtual machine.

        Args:
            domain: VM name or UUID

        Returns:
            Suspend result.
        """
        return await _virsh_suspend_impl(domain)

    @auto_heal()
    @registry.tool()
    async def virsh_resume(domain: str) -> str:
        """
        Resume a suspended virtual machine.

        Args:
            domain: VM name or UUID

        Returns:
            Resume result.
        """
        return await _virsh_resume_impl(domain)

    @auto_heal()
    @registry.tool()
    async def virsh_undefine(
        domain: str,
        remove_all_storage: bool = False,
        nvram: bool = False,
        snapshots_metadata: bool = False,
    ) -> str:
        """
        Remove a VM definition (undefine).

        Args:
            domain: VM name or UUID
            remove_all_storage: Also remove all associated storage volumes
            nvram: Also remove NVRAM file
            snapshots_metadata: Also remove snapshot metadata

        Returns:
            Undefine result.
        """
        return await _virsh_undefine_impl(domain, remove_all_storage, nvram, snapshots_metadata)

    # VM Creation tools
    @auto_heal()
    @registry.tool()
    async def virt_install(
        name: str,
        memory: int,
        vcpus: int,
        disk_size: int = 20,
        disk_path: str = "",
        cdrom: str = "",
        location: str = "",
        os_variant: str = "",
        network: str = "default",
        graphics: str = "vnc",
        extra_args: str = "",
        autostart: bool = False,
        noautoconsole: bool = True,
        timeout: int = 600,
    ) -> str:
        """
        Create a new virtual machine with virt-install.

        Args:
            name: VM name
            memory: Memory in MB
            vcpus: Number of virtual CPUs
            disk_size: Disk size in GB (used if disk_path not specified)
            disk_path: Path to existing disk image or where to create new one
            cdrom: Path to ISO file for CD-ROM boot
            location: Installation source URL or path (for network install)
            os_variant: OS variant (e.g., "rhel9.0", "fedora38", "ubuntu22.04")
            network: Network name or config (default: "default")
            graphics: Graphics type (vnc, spice, none)
            extra_args: Extra kernel arguments for installation
            autostart: Start VM automatically on host boot
            noautoconsole: Don't automatically connect to console
            timeout: Timeout in seconds

        Returns:
            Installation result.
        """
        return await _virt_install_impl(
            name,
            memory,
            vcpus,
            disk_size,
            disk_path,
            cdrom,
            location,
            os_variant,
            network,
            graphics,
            extra_args,
            autostart,
            noautoconsole,
            timeout,
        )

    @auto_heal()
    @registry.tool()
    async def virsh_define(xml_file: str) -> str:
        """
        Define a VM from an XML configuration file.

        Args:
            xml_file: Path to XML definition file

        Returns:
            Define result.
        """
        return await _virsh_define_impl(xml_file)

    @auto_heal()
    @registry.tool()
    async def virsh_clone(
        original: str,
        name: str,
        auto_clone: bool = True,
        file: str = "",
    ) -> str:
        """
        Clone an existing virtual machine.

        Args:
            original: Source VM name
            name: New VM name
            auto_clone: Automatically generate new disk paths
            file: Specific path for cloned disk

        Returns:
            Clone result.
        """
        return await _virsh_clone_impl(original, name, auto_clone, file)

    # VM Information tools
    @auto_heal()
    @registry.tool()
    async def virsh_dominfo(domain: str) -> str:
        """
        Get detailed information about a VM.

        Args:
            domain: VM name or UUID

        Returns:
            VM information.
        """
        return await _virsh_dominfo_impl(domain)

    @auto_heal()
    @registry.tool()
    async def virsh_domstate(domain: str, reason: bool = True) -> str:
        """
        Get the current state of a VM.

        Args:
            domain: VM name or UUID
            reason: Show reason for current state

        Returns:
            VM state.
        """
        return await _virsh_domstate_impl(domain, reason)

    @auto_heal()
    @registry.tool()
    async def virsh_domblklist(domain: str, details: bool = True) -> str:
        """
        List block devices attached to a VM.

        Args:
            domain: VM name or UUID
            details: Show additional details

        Returns:
            Block device list.
        """
        return await _virsh_domblklist_impl(domain, details)

    @auto_heal()
    @registry.tool()
    async def virsh_domiflist(domain: str) -> str:
        """
        List network interfaces attached to a VM.

        Args:
            domain: VM name or UUID

        Returns:
            Network interface list.
        """
        return await _virsh_domiflist_impl(domain)

    @auto_heal()
    @registry.tool()
    async def virsh_dumpxml(
        domain: str,
        inactive: bool = False,
        migratable: bool = False,
    ) -> str:
        """
        Dump VM XML configuration.

        Args:
            domain: VM name or UUID
            inactive: Show inactive (defined) configuration
            migratable: Show migratable XML

        Returns:
            VM XML configuration.
        """
        return await _virsh_dumpxml_impl(domain, inactive, migratable)

    @auto_heal()
    @registry.tool()
    async def virsh_vcpuinfo(domain: str) -> str:
        """
        Get vCPU information for a VM.

        Args:
            domain: VM name or UUID

        Returns:
            vCPU information.
        """
        return await _virsh_vcpuinfo_impl(domain)

    @auto_heal()
    @registry.tool()
    async def virsh_memtune(
        domain: str,
        hard_limit: int = 0,
        soft_limit: int = 0,
        swap_hard_limit: int = 0,
    ) -> str:
        """
        Get or set VM memory parameters.

        Args:
            domain: VM name or UUID
            hard_limit: Hard memory limit in KB (0 = query only)
            soft_limit: Soft memory limit in KB (0 = query only)
            swap_hard_limit: Swap hard limit in KB (0 = query only)

        Returns:
            Memory parameters.
        """
        return await _virsh_memtune_impl(domain, hard_limit, soft_limit, swap_hard_limit)

    # Snapshot tools
    @auto_heal()
    @registry.tool()
    async def virsh_snapshot_create(
        domain: str,
        name: str = "",
        description: str = "",
        disk_only: bool = False,
        quiesce: bool = False,
    ) -> str:
        """
        Create a VM snapshot.

        Args:
            domain: VM name or UUID
            name: Snapshot name (auto-generated if not specified)
            description: Snapshot description
            disk_only: Create disk-only snapshot (no memory)
            quiesce: Quiesce guest filesystem (requires guest agent)

        Returns:
            Snapshot creation result.
        """
        return await _virsh_snapshot_create_impl(domain, name, description, disk_only, quiesce)

    @auto_heal()
    @registry.tool()
    async def virsh_snapshot_list(domain: str, tree: bool = False) -> str:
        """
        List snapshots for a VM.

        Args:
            domain: VM name or UUID
            tree: Show snapshot tree hierarchy

        Returns:
            Snapshot list.
        """
        return await _virsh_snapshot_list_impl(domain, tree)

    @auto_heal()
    @registry.tool()
    async def virsh_snapshot_revert(
        domain: str,
        snapshot: str,
        running: bool = False,
        paused: bool = False,
    ) -> str:
        """
        Revert VM to a snapshot.

        Args:
            domain: VM name or UUID
            snapshot: Snapshot name
            running: Start VM after revert
            paused: Pause VM after revert

        Returns:
            Revert result.
        """
        return await _virsh_snapshot_revert_impl(domain, snapshot, running, paused)

    @auto_heal()
    @registry.tool()
    async def virsh_snapshot_delete(
        domain: str,
        snapshot: str,
        children: bool = False,
        metadata: bool = False,
    ) -> str:
        """
        Delete a VM snapshot.

        Args:
            domain: VM name or UUID
            snapshot: Snapshot name
            children: Also delete child snapshots
            metadata: Delete only metadata (keep disk data)

        Returns:
            Delete result.
        """
        return await _virsh_snapshot_delete_impl(domain, snapshot, children, metadata)

    # Storage tools
    @auto_heal()
    @registry.tool()
    async def virsh_pool_list(all_pools: bool = True, details: bool = True) -> str:
        """
        List storage pools.

        Args:
            all_pools: Show all pools including inactive
            details: Show additional details

        Returns:
            Storage pool list.
        """
        return await _virsh_pool_list_impl(all_pools, details)

    @auto_heal()
    @registry.tool()
    async def virsh_pool_info(pool: str) -> str:
        """
        Get storage pool information.

        Args:
            pool: Pool name

        Returns:
            Pool information.
        """
        return await _virsh_pool_info_impl(pool)

    @auto_heal()
    @registry.tool()
    async def virsh_vol_list(pool: str, details: bool = True) -> str:
        """
        List volumes in a storage pool.

        Args:
            pool: Pool name
            details: Show additional details

        Returns:
            Volume list.
        """
        return await _virsh_vol_list_impl(pool, details)

    @auto_heal()
    @registry.tool()
    async def virsh_vol_create(
        pool: str,
        name: str,
        capacity: str,
        format_type: str = "qcow2",
        allocation: str = "",
    ) -> str:
        """
        Create a new storage volume.

        Args:
            pool: Pool name
            name: Volume name
            capacity: Volume capacity (e.g., "20G", "100M")
            format_type: Volume format (qcow2, raw, vmdk)
            allocation: Initial allocation (e.g., "1G")

        Returns:
            Volume creation result.
        """
        return await _virsh_vol_create_impl(pool, name, capacity, format_type, allocation)

    @auto_heal()
    @registry.tool()
    async def virsh_vol_delete(pool: str, vol: str) -> str:
        """
        Delete a storage volume.

        Args:
            pool: Pool name
            vol: Volume name

        Returns:
            Delete result.
        """
        return await _virsh_vol_delete_impl(pool, vol)

    @auto_heal()
    @registry.tool()
    async def virsh_vol_resize(
        pool: str,
        vol: str,
        capacity: str,
        shrink: bool = False,
    ) -> str:
        """
        Resize a storage volume.

        Args:
            pool: Pool name
            vol: Volume name
            capacity: New capacity (e.g., "50G") or delta (e.g., "+10G")
            shrink: Allow shrinking (dangerous!)

        Returns:
            Resize result.
        """
        return await _virsh_vol_resize_impl(pool, vol, capacity, shrink)

    # Network tools
    @auto_heal()
    @registry.tool()
    async def virsh_net_list(all_nets: bool = True) -> str:
        """
        List virtual networks.

        Args:
            all_nets: Show all networks including inactive

        Returns:
            Network list.
        """
        return await _virsh_net_list_impl(all_nets)

    @auto_heal()
    @registry.tool()
    async def virsh_net_info(network: str) -> str:
        """
        Get virtual network information.

        Args:
            network: Network name

        Returns:
            Network information.
        """
        return await _virsh_net_info_impl(network)

    @auto_heal()
    @registry.tool()
    async def virsh_net_start(network: str) -> str:
        """
        Start a virtual network.

        Args:
            network: Network name

        Returns:
            Start result.
        """
        return await _virsh_net_start_impl(network)

    @auto_heal()
    @registry.tool()
    async def virsh_net_destroy(network: str) -> str:
        """
        Stop a virtual network.

        Args:
            network: Network name

        Returns:
            Stop result.
        """
        return await _virsh_net_destroy_impl(network)

    # Console/Display tools
    @auto_heal()
    @registry.tool()
    async def virsh_console_info(domain: str) -> str:
        """
        Get console connection information for a VM.

        Args:
            domain: VM name or UUID

        Returns:
            Console connection info.
        """
        return await _virsh_console_info_impl(domain)

    @auto_heal()
    @registry.tool()
    async def virsh_vncdisplay(domain: str) -> str:
        """
        Get VNC display port for a VM.

        Args:
            domain: VM name or UUID

        Returns:
            VNC display information.
        """
        return await _virsh_vncdisplay_impl(domain)

    @auto_heal()
    @registry.tool()
    async def virsh_screenshot(domain: str, file: str = "") -> str:
        """
        Take a screenshot of a VM's display.

        Args:
            domain: VM name or UUID
            file: Output file path (default: /tmp/{domain}-screenshot.ppm)

        Returns:
            Screenshot result.
        """
        return await _virsh_screenshot_impl(domain, file)

    return registry.count
