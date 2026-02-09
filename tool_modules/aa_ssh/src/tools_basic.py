"""SSH tool definitions - Secure shell and key management.

Provides:
Key tools:
- ssh_keygen: Generate SSH key pair
- ssh_keygen_show: Show public key
- ssh_keyscan: Scan host for SSH keys
- ssh_copy_id: Copy public key to remote host

Connection tools:
- ssh_command: Execute command on remote host
- ssh_test: Test SSH connection

Config tools:
- ssh_config_list: List SSH config hosts
- ssh_known_hosts_list: List known hosts
- ssh_known_hosts_remove: Remove host from known_hosts

Agent tools:
- ssh_add: Add key to SSH agent
- ssh_add_list: List keys in SSH agent
"""

import logging
from pathlib import Path

from fastmcp import FastMCP

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import run_cmd, truncate_output

logger = logging.getLogger(__name__)


@auto_heal()
async def _ssh_keygen_impl(
    key_file: str,
    key_type: str = "ed25519",
    bits: int = 0,
    comment: str = "",
    passphrase: str = "",
) -> str:
    """Generate SSH key pair."""
    key_path = Path(key_file).expanduser()

    cmd = ["ssh-keygen", "-t", key_type, "-f", str(key_path), "-N", passphrase]

    if bits > 0:
        cmd.extend(["-b", str(bits)])
    if comment:
        cmd.extend(["-C", comment])

    success, output = await run_cmd(cmd, timeout=30)
    if success:
        return f"✅ Generated {key_type} key: {key_path}\n\n{output}"
    return f"❌ Key generation failed: {output}"


@auto_heal()
async def _ssh_keygen_show_impl(key_file: str) -> str:
    """Show public key."""
    key_path = Path(key_file).expanduser()

    # If private key given, show the .pub file
    pub_path = key_path
    if not str(key_path).endswith(".pub"):
        pub_path = Path(str(key_path) + ".pub")

    if not pub_path.exists():
        return f"❌ Public key not found: {pub_path}"

    cmd = ["cat", str(pub_path)]
    success, output = await run_cmd(cmd, timeout=10)

    if success:
        return f"## Public Key: {pub_path.name}\n\n```\n{output}\n```"
    return f"❌ Failed to read key: {output}"


@auto_heal()
async def _ssh_keyscan_impl(
    host: str,
    port: int = 22,
    key_type: str = "",
) -> str:
    """Scan host for SSH keys."""
    cmd = ["ssh-keyscan", "-p", str(port)]
    if key_type:
        cmd.extend(["-t", key_type])
    cmd.append(host)

    success, output = await run_cmd(cmd, timeout=30)
    if success:
        return f"## SSH Keys: {host}\n\n```\n{output}\n```"
    return f"❌ Key scan failed: {output}"


@auto_heal()
async def _ssh_copy_id_impl(
    host: str,
    user: str = "",
    key_file: str = "",
    port: int = 22,
) -> str:
    """Copy public key to remote host."""
    cmd = ["ssh-copy-id"]
    if key_file:
        key_path = Path(key_file).expanduser()
        cmd.extend(["-i", str(key_path)])
    cmd.extend(["-p", str(port)])

    target = f"{user}@{host}" if user else host
    cmd.append(target)

    success, output = await run_cmd(cmd, timeout=60)
    if success:
        return f"✅ Copied key to {target}\n\n{output}"
    return f"❌ Copy failed: {output}"


@auto_heal()
async def _ssh_command_impl(
    host: str,
    command: str,
    user: str = "",
    port: int = 22,
    key_file: str = "",
    timeout_secs: int = 60,
) -> str:
    """Execute command on remote host."""
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
    cmd.extend(["-p", str(port)])

    if key_file:
        key_path = Path(key_file).expanduser()
        cmd.extend(["-i", str(key_path)])

    target = f"{user}@{host}" if user else host
    cmd.append(target)
    cmd.append(command)

    success, output = await run_cmd(cmd, timeout=timeout_secs)
    if success:
        return f"## SSH: {target}\n\n```\n{truncate_output(output, max_length=5000, mode='tail')}\n```"
    return f"❌ Command failed: {output}"


@auto_heal()
async def _ssh_test_impl(
    host: str,
    user: str = "",
    port: int = 22,
    key_file: str = "",
) -> str:
    """Test SSH connection."""
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    cmd.extend(["-p", str(port)])

    if key_file:
        key_path = Path(key_file).expanduser()
        cmd.extend(["-i", str(key_path)])

    target = f"{user}@{host}" if user else host
    cmd.append(target)
    cmd.append("echo 'SSH connection successful'")

    success, output = await run_cmd(cmd, timeout=15)
    if success:
        return f"✅ SSH connection to {target} successful"
    return f"❌ SSH connection to {target} failed: {output}"


@auto_heal()
async def _ssh_config_list_impl() -> str:
    """List SSH config hosts."""
    config_path = Path.home() / ".ssh" / "config"

    if not config_path.exists():
        return "No SSH config file found"

    cmd = ["grep", "-E", "^Host\\s", str(config_path)]
    success, output = await run_cmd(cmd, timeout=10)

    if success:
        hosts = [
            line.replace("Host ", "").strip() for line in output.strip().split("\n")
        ]
        hosts = [h for h in hosts if h and not h.startswith("*")]
        host_list = "\n".join(f"- {h}" for h in hosts)
        return f"## SSH Config Hosts\n\n{host_list}"
    return "No hosts found in SSH config"


@auto_heal()
async def _ssh_known_hosts_list_impl() -> str:
    """List known hosts."""
    known_hosts = Path.home() / ".ssh" / "known_hosts"

    if not known_hosts.exists():
        return "No known_hosts file found"

    cmd = ["cat", str(known_hosts)]
    success, output = await run_cmd(cmd, timeout=10)

    if success:
        lines = output.strip().split("\n")
        hosts = []
        for line in lines:
            if line and not line.startswith("#"):
                host = line.split()[0] if line.split() else ""
                if host:
                    hosts.append(host)
        return (
            f"## Known Hosts ({len(hosts)})\n\n```\n" + "\n".join(hosts[:50]) + "\n```"
        )
    return f"❌ Failed to read known_hosts: {output}"


@auto_heal()
async def _ssh_known_hosts_remove_impl(host: str) -> str:
    """Remove host from known_hosts."""
    cmd = ["ssh-keygen", "-R", host]

    success, output = await run_cmd(cmd, timeout=10)
    if success:
        return f"✅ Removed {host} from known_hosts"
    return f"❌ Failed to remove host: {output}"


@auto_heal()
async def _ssh_add_impl(key_file: str = "") -> str:
    """Add key to SSH agent."""
    cmd = ["ssh-add"]
    if key_file:
        key_path = Path(key_file).expanduser()
        cmd.append(str(key_path))

    success, output = await run_cmd(cmd, timeout=30)
    if success:
        return f"✅ Key added to SSH agent\n\n{output}"
    return f"❌ Failed to add key: {output}"


@auto_heal()
async def _ssh_add_list_impl() -> str:
    """List keys in SSH agent."""
    cmd = ["ssh-add", "-l"]

    success, output = await run_cmd(cmd, timeout=10)
    if success:
        return f"## SSH Agent Keys\n\n```\n{output}\n```"
    if "no identities" in output.lower():
        return "No keys in SSH agent"
    return f"❌ Failed to list keys: {output}"


@auto_heal()
async def _ssh_fingerprint_impl(key_file: str) -> str:
    """Show key fingerprint."""
    key_path = Path(key_file).expanduser()

    cmd = ["ssh-keygen", "-l", "-f", str(key_path)]

    success, output = await run_cmd(cmd, timeout=10)
    if success:
        return f"## Key Fingerprint\n\n```\n{output}\n```"
    return f"❌ Failed to get fingerprint: {output}"


def register_tools(server: FastMCP) -> int:
    """Register SSH tools with the MCP server."""
    registry = ToolRegistry(server)

    @auto_heal()
    @registry.tool()
    async def ssh_keygen(
        key_file: str,
        key_type: str = "ed25519",
        comment: str = "",
    ) -> str:
        """Generate SSH key pair.

        Args:
            key_file: Output file path (e.g., ~/.ssh/id_mykey)
            key_type: Key type (ed25519, rsa, ecdsa)
            comment: Key comment
        """
        return await _ssh_keygen_impl(key_file, key_type, 0, comment, "")

    @auto_heal()
    @registry.tool()
    async def ssh_keygen_show(key_file: str) -> str:
        """Show public key.

        Args:
            key_file: Key file path (private or public)
        """
        return await _ssh_keygen_show_impl(key_file)

    @auto_heal()
    @registry.tool()
    async def ssh_keyscan(host: str, port: int = 22) -> str:
        """Scan host for SSH keys.

        Args:
            host: Hostname to scan
            port: SSH port
        """
        return await _ssh_keyscan_impl(host, port)

    @auto_heal()
    @registry.tool()
    async def ssh_command(
        host: str,
        command: str,
        user: str = "",
        port: int = 22,
        key_file: str = "",
    ) -> str:
        """Execute command on remote host.

        Args:
            host: Remote hostname
            command: Command to execute
            user: SSH user
            port: SSH port
            key_file: Private key file
        """
        return await _ssh_command_impl(host, command, user, port, key_file)

    @auto_heal()
    @registry.tool()
    async def ssh_test(
        host: str,
        user: str = "",
        port: int = 22,
        key_file: str = "",
    ) -> str:
        """Test SSH connection.

        Args:
            host: Remote hostname
            user: SSH user
            port: SSH port
            key_file: Private key file
        """
        return await _ssh_test_impl(host, user, port, key_file)

    @auto_heal()
    @registry.tool()
    async def ssh_config_list() -> str:
        """List SSH config hosts."""
        return await _ssh_config_list_impl()

    @auto_heal()
    @registry.tool()
    async def ssh_known_hosts_list() -> str:
        """List known hosts."""
        return await _ssh_known_hosts_list_impl()

    @auto_heal()
    @registry.tool()
    async def ssh_known_hosts_remove(host: str) -> str:
        """Remove host from known_hosts.

        Args:
            host: Hostname to remove
        """
        return await _ssh_known_hosts_remove_impl(host)

    @auto_heal()
    @registry.tool()
    async def ssh_add_list() -> str:
        """List keys in SSH agent."""
        return await _ssh_add_list_impl()

    @auto_heal()
    @registry.tool()
    async def ssh_fingerprint(key_file: str) -> str:
        """Show key fingerprint.

        Args:
            key_file: Key file path
        """
        return await _ssh_fingerprint_impl(key_file)

    return registry.count
