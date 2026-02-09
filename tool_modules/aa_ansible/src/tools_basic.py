"""Ansible tool definitions - Automation and configuration management tools.

Provides:
Playbook tools:
- ansible_playbook_run: Run an Ansible playbook
- ansible_playbook_check: Dry-run a playbook (check mode)
- ansible_playbook_list_tasks: List tasks in a playbook
- ansible_playbook_list_tags: List tags in a playbook

Inventory tools:
- ansible_inventory_list: List hosts in inventory
- ansible_inventory_graph: Show inventory hierarchy
- ansible_inventory_host: Get variables for a specific host

Ad-hoc command tools:
- ansible_ping: Ping hosts to check connectivity
- ansible_command: Run ad-hoc command on hosts
- ansible_shell: Run shell command on hosts
- ansible_copy: Copy files to hosts
- ansible_fetch: Fetch files from hosts
- ansible_setup: Gather facts from hosts

Galaxy tools:
- ansible_galaxy_install: Install roles/collections from Galaxy
- ansible_galaxy_list: List installed roles/collections
- ansible_galaxy_remove: Remove installed roles/collections
- ansible_galaxy_search: Search Galaxy for roles/collections

Vault tools:
- ansible_vault_encrypt: Encrypt a file with vault
- ansible_vault_decrypt: Decrypt a vault file
- ansible_vault_view: View encrypted vault file
- ansible_vault_edit_string: Encrypt a string for use in YAML

Config tools:
- ansible_config_dump: Show current Ansible configuration
- ansible_version: Show Ansible version information
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


def _get_ansible_env() -> dict:
    """Get environment variables for Ansible commands.

    Returns:
        Environment dict with ANSIBLE_* variables set.
    """
    env = os.environ.copy()
    # Disable host key checking for automation
    env.setdefault("ANSIBLE_HOST_KEY_CHECKING", "False")
    # Use JSON callback for structured output where possible
    env.setdefault("ANSIBLE_STDOUT_CALLBACK", "yaml")
    # Disable cowsay
    env.setdefault("ANSIBLE_NOCOWS", "1")
    return env


@auto_heal()
async def _ansible_playbook_run_impl(
    playbook: str,
    inventory: str = "",
    limit: str = "",
    tags: str = "",
    skip_tags: str = "",
    extra_vars: str = "",
    verbose: int = 0,
    timeout: int = 600,
    cwd: str = "",
) -> str:
    """
    Run an Ansible playbook.

    Args:
        playbook: Path to the playbook file
        inventory: Inventory file or comma-separated hosts
        limit: Limit to specific hosts/groups
        tags: Only run plays and tasks tagged with these values
        skip_tags: Skip plays and tasks tagged with these values
        extra_vars: Extra variables as key=value or JSON string
        verbose: Verbosity level (0-4)
        timeout: Timeout in seconds
        cwd: Working directory (defaults to playbook directory)

    Returns:
        Playbook execution output.
    """
    playbook_path = Path(playbook).expanduser()
    if not playbook_path.is_absolute():
        if cwd:
            playbook_path = Path(cwd) / playbook_path
        else:
            playbook_path = playbook_path.resolve()

    if not playbook_path.exists():
        return f"❌ Playbook not found: {playbook_path}"

    work_dir = cwd if cwd else str(playbook_path.parent)

    cmd = ["ansible-playbook", str(playbook_path)]

    if inventory:
        cmd.extend(["-i", inventory])
    if limit:
        cmd.extend(["--limit", limit])
    if tags:
        cmd.extend(["--tags", tags])
    if skip_tags:
        cmd.extend(["--skip-tags", skip_tags])
    if extra_vars:
        cmd.extend(["-e", extra_vars])
    if verbose > 0:
        cmd.append("-" + "v" * min(verbose, 4))

    success, output = await run_cmd(
        cmd, cwd=work_dir, timeout=timeout, env=_get_ansible_env()
    )

    if success:
        return f"✅ Playbook completed successfully\n\n```\n{truncate_output(output, max_length=5000, mode='tail')}\n```"
    return f"❌ Playbook failed:\n\n```\n{truncate_output(output, max_length=5000, mode='tail')}\n```"


@auto_heal()
async def _ansible_playbook_check_impl(
    playbook: str,
    inventory: str = "",
    limit: str = "",
    extra_vars: str = "",
    diff: bool = True,
    timeout: int = 300,
    cwd: str = "",
) -> str:
    """
    Dry-run an Ansible playbook (check mode).

    Args:
        playbook: Path to the playbook file
        inventory: Inventory file or comma-separated hosts
        limit: Limit to specific hosts/groups
        extra_vars: Extra variables as key=value or JSON string
        diff: Show differences in files
        timeout: Timeout in seconds
        cwd: Working directory

    Returns:
        Check mode output showing what would change.
    """
    playbook_path = Path(playbook).expanduser()
    if not playbook_path.is_absolute():
        if cwd:
            playbook_path = Path(cwd) / playbook_path
        else:
            playbook_path = playbook_path.resolve()

    if not playbook_path.exists():
        return f"❌ Playbook not found: {playbook_path}"

    work_dir = cwd if cwd else str(playbook_path.parent)

    cmd = ["ansible-playbook", str(playbook_path), "--check"]

    if inventory:
        cmd.extend(["-i", inventory])
    if limit:
        cmd.extend(["--limit", limit])
    if extra_vars:
        cmd.extend(["-e", extra_vars])
    if diff:
        cmd.append("--diff")

    success, output = await run_cmd(
        cmd, cwd=work_dir, timeout=timeout, env=_get_ansible_env()
    )

    status = "✅ Check passed" if success else "⚠️ Check completed with issues"
    return (
        f"{status}\n\n```\n{truncate_output(output, max_length=5000, mode='tail')}\n```"
    )


@auto_heal()
async def _ansible_playbook_list_tasks_impl(
    playbook: str,
    cwd: str = "",
) -> str:
    """
    List tasks in an Ansible playbook.

    Args:
        playbook: Path to the playbook file
        cwd: Working directory

    Returns:
        List of tasks in the playbook.
    """
    playbook_path = Path(playbook).expanduser()
    if not playbook_path.is_absolute():
        if cwd:
            playbook_path = Path(cwd) / playbook_path
        else:
            playbook_path = playbook_path.resolve()

    if not playbook_path.exists():
        return f"❌ Playbook not found: {playbook_path}"

    work_dir = cwd if cwd else str(playbook_path.parent)

    cmd = ["ansible-playbook", str(playbook_path), "--list-tasks"]

    success, output = await run_cmd(
        cmd, cwd=work_dir, timeout=60, env=_get_ansible_env()
    )

    if success:
        return f"## Tasks in {playbook_path.name}\n\n```\n{output}\n```"
    return f"❌ Failed to list tasks: {output}"


@auto_heal()
async def _ansible_playbook_list_tags_impl(
    playbook: str,
    cwd: str = "",
) -> str:
    """
    List tags in an Ansible playbook.

    Args:
        playbook: Path to the playbook file
        cwd: Working directory

    Returns:
        List of tags in the playbook.
    """
    playbook_path = Path(playbook).expanduser()
    if not playbook_path.is_absolute():
        if cwd:
            playbook_path = Path(cwd) / playbook_path
        else:
            playbook_path = playbook_path.resolve()

    if not playbook_path.exists():
        return f"❌ Playbook not found: {playbook_path}"

    work_dir = cwd if cwd else str(playbook_path.parent)

    cmd = ["ansible-playbook", str(playbook_path), "--list-tags"]

    success, output = await run_cmd(
        cmd, cwd=work_dir, timeout=60, env=_get_ansible_env()
    )

    if success:
        return f"## Tags in {playbook_path.name}\n\n```\n{output}\n```"
    return f"❌ Failed to list tags: {output}"


@auto_heal()
async def _ansible_inventory_list_impl(
    inventory: str,
    host: str = "",
    yaml_output: bool = False,
) -> str:
    """
    List hosts in an Ansible inventory.

    Args:
        inventory: Inventory file path or directory
        host: Specific host to show (optional)
        yaml_output: Output in YAML format

    Returns:
        Inventory listing.
    """
    cmd = ["ansible-inventory", "-i", inventory, "--list"]

    if host:
        cmd.extend(["--host", host])
    if yaml_output:
        cmd.append("--yaml")

    success, output = await run_cmd(cmd, timeout=60, env=_get_ansible_env())

    if success:
        fmt = "yaml" if yaml_output else "json"
        return f"## Inventory: {inventory}\n\n```{fmt}\n{truncate_output(output, max_length=5000, mode='head')}\n```"
    return f"❌ Failed to list inventory: {output}"


@auto_heal()
async def _ansible_inventory_graph_impl(
    inventory: str,
) -> str:
    """
    Show inventory hierarchy as a graph.

    Args:
        inventory: Inventory file path or directory

    Returns:
        Inventory graph showing group hierarchy.
    """
    cmd = ["ansible-inventory", "-i", inventory, "--graph"]

    success, output = await run_cmd(cmd, timeout=60, env=_get_ansible_env())

    if success:
        return f"## Inventory Graph: {inventory}\n\n```\n{output}\n```"
    return f"❌ Failed to show inventory graph: {output}"


@auto_heal()
async def _ansible_inventory_host_impl(
    inventory: str,
    host: str,
) -> str:
    """
    Get variables for a specific host.

    Args:
        inventory: Inventory file path or directory
        host: Host name to get variables for

    Returns:
        Host variables in JSON format.
    """
    cmd = ["ansible-inventory", "-i", inventory, "--host", host]

    success, output = await run_cmd(cmd, timeout=60, env=_get_ansible_env())

    if success:
        return f"## Variables for {host}\n\n```json\n{output}\n```"
    return f"❌ Failed to get host variables: {output}"


@auto_heal()
async def _ansible_ping_impl(
    hosts: str,
    inventory: str = "",
    timeout: int = 60,
) -> str:
    """
    Ping hosts to check Ansible connectivity.

    Args:
        hosts: Host pattern (e.g., "all", "webservers", "host1,host2")
        inventory: Inventory file (optional, uses default if not specified)
        timeout: Timeout in seconds

    Returns:
        Ping results for each host.
    """
    cmd = ["ansible", hosts, "-m", "ping"]

    if inventory:
        cmd.extend(["-i", inventory])

    success, output = await run_cmd(cmd, timeout=timeout, env=_get_ansible_env())

    if success:
        return f"## Ping Results\n\n```\n{output}\n```"
    return f"⚠️ Some hosts unreachable:\n\n```\n{output}\n```"


@auto_heal()
async def _ansible_command_impl(
    hosts: str,
    command: str,
    inventory: str = "",
    become: bool = False,
    timeout: int = 120,
) -> str:
    """
    Run an ad-hoc command on hosts.

    Args:
        hosts: Host pattern (e.g., "all", "webservers")
        command: Command to execute
        inventory: Inventory file (optional)
        become: Use privilege escalation (sudo)
        timeout: Timeout in seconds

    Returns:
        Command output from each host.
    """
    cmd = ["ansible", hosts, "-m", "command", "-a", command]

    if inventory:
        cmd.extend(["-i", inventory])
    if become:
        cmd.append("--become")

    success, output = await run_cmd(cmd, timeout=timeout, env=_get_ansible_env())

    if success:
        return f"## Command: {command}\n\n```\n{truncate_output(output, max_length=5000, mode='tail')}\n```"
    return f"❌ Command failed:\n\n```\n{output}\n```"


@auto_heal()
async def _ansible_shell_impl(
    hosts: str,
    command: str,
    inventory: str = "",
    become: bool = False,
    timeout: int = 120,
) -> str:
    """
    Run a shell command on hosts (supports pipes, redirects).

    Args:
        hosts: Host pattern (e.g., "all", "webservers")
        command: Shell command to execute
        inventory: Inventory file (optional)
        become: Use privilege escalation (sudo)
        timeout: Timeout in seconds

    Returns:
        Shell output from each host.
    """
    cmd = ["ansible", hosts, "-m", "shell", "-a", command]

    if inventory:
        cmd.extend(["-i", inventory])
    if become:
        cmd.append("--become")

    success, output = await run_cmd(cmd, timeout=timeout, env=_get_ansible_env())

    if success:
        return f"## Shell: {command}\n\n```\n{truncate_output(output, max_length=5000, mode='tail')}\n```"
    return f"❌ Shell command failed:\n\n```\n{output}\n```"


@auto_heal()
async def _ansible_copy_impl(
    hosts: str,
    src: str,
    dest: str,
    inventory: str = "",
    become: bool = False,
    mode: str = "",
    timeout: int = 120,
) -> str:
    """
    Copy files to remote hosts.

    Args:
        hosts: Host pattern
        src: Source file path (local)
        dest: Destination path (remote)
        inventory: Inventory file (optional)
        become: Use privilege escalation
        mode: File permissions (e.g., "0644")
        timeout: Timeout in seconds

    Returns:
        Copy result.
    """
    args = f"src={src} dest={dest}"
    if mode:
        args += f" mode={mode}"

    cmd = ["ansible", hosts, "-m", "copy", "-a", args]

    if inventory:
        cmd.extend(["-i", inventory])
    if become:
        cmd.append("--become")

    success, output = await run_cmd(cmd, timeout=timeout, env=_get_ansible_env())

    if success:
        return f"✅ Copied {src} to {dest}\n\n```\n{truncate_output(output, max_length=2000, mode='tail')}\n```"
    return f"❌ Copy failed:\n\n```\n{output}\n```"


@auto_heal()
async def _ansible_fetch_impl(
    hosts: str,
    src: str,
    dest: str,
    inventory: str = "",
    flat: bool = False,
    timeout: int = 120,
) -> str:
    """
    Fetch files from remote hosts.

    Args:
        hosts: Host pattern
        src: Source file path (remote)
        dest: Destination directory (local)
        inventory: Inventory file (optional)
        flat: Store files directly in dest without host subdirs
        timeout: Timeout in seconds

    Returns:
        Fetch result.
    """
    args = f"src={src} dest={dest}"
    if flat:
        args += " flat=yes"

    cmd = ["ansible", hosts, "-m", "fetch", "-a", args]

    if inventory:
        cmd.extend(["-i", inventory])

    success, output = await run_cmd(cmd, timeout=timeout, env=_get_ansible_env())

    if success:
        return f"✅ Fetched {src} to {dest}\n\n```\n{truncate_output(output, max_length=2000, mode='tail')}\n```"
    return f"❌ Fetch failed:\n\n```\n{output}\n```"


@auto_heal()
async def _ansible_setup_impl(
    hosts: str,
    inventory: str = "",
    filter_facts: str = "",
    timeout: int = 120,
) -> str:
    """
    Gather facts from hosts.

    Args:
        hosts: Host pattern
        inventory: Inventory file (optional)
        filter_facts: Filter facts by pattern (e.g., "ansible_os*")
        timeout: Timeout in seconds

    Returns:
        Host facts.
    """
    args = ""
    if filter_facts:
        args = f"filter={filter_facts}"

    cmd = ["ansible", hosts, "-m", "setup"]
    if args:
        cmd.extend(["-a", args])

    if inventory:
        cmd.extend(["-i", inventory])

    success, output = await run_cmd(cmd, timeout=timeout, env=_get_ansible_env())

    if success:
        return f"## Facts for {hosts}\n\n```json\n{truncate_output(output, max_length=5000, mode='head')}\n```"
    return f"❌ Failed to gather facts:\n\n```\n{output}\n```"


@auto_heal()
async def _ansible_galaxy_install_impl(
    name: str,
    role: bool = True,
    version: str = "",
    force: bool = False,
    timeout: int = 180,
) -> str:
    """
    Install a role or collection from Ansible Galaxy.

    Args:
        name: Role/collection name (e.g., "geerlingguy.docker" or "community.general")
        role: True for role, False for collection
        version: Specific version to install
        force: Force reinstall if already installed
        timeout: Timeout in seconds

    Returns:
        Installation result.
    """
    if role:
        cmd = ["ansible-galaxy", "role", "install", name]
    else:
        cmd = ["ansible-galaxy", "collection", "install", name]

    if version:
        # For roles, append version with comma; for collections use == syntax
        if role:
            cmd[-1] = f"{name},{version}"
        else:
            cmd[-1] = f"{name}=={version}"
    if force:
        cmd.append("--force")

    success, output = await run_cmd(cmd, timeout=timeout, env=_get_ansible_env())

    item_type = "role" if role else "collection"
    if success:
        return f"✅ Installed {item_type}: {name}\n\n```\n{output}\n```"
    return f"❌ Failed to install {item_type}:\n\n```\n{output}\n```"


@auto_heal()
async def _ansible_galaxy_list_impl(
    role: bool = True,
) -> str:
    """
    List installed roles or collections.

    Args:
        role: True for roles, False for collections

    Returns:
        List of installed items.
    """
    if role:
        cmd = ["ansible-galaxy", "role", "list"]
    else:
        cmd = ["ansible-galaxy", "collection", "list"]

    success, output = await run_cmd(cmd, timeout=60, env=_get_ansible_env())

    item_type = "Roles" if role else "Collections"
    if success:
        return f"## Installed {item_type}\n\n```\n{output}\n```"
    return f"❌ Failed to list {item_type.lower()}:\n\n```\n{output}\n```"


@auto_heal()
async def _ansible_galaxy_remove_impl(
    name: str,
    role: bool = True,
) -> str:
    """
    Remove an installed role or collection.

    Args:
        name: Role/collection name to remove
        role: True for role, False for collection

    Returns:
        Removal result.
    """
    if role:
        cmd = ["ansible-galaxy", "role", "remove", name]
    else:
        cmd = ["ansible-galaxy", "collection", "remove", name]

    success, output = await run_cmd(cmd, timeout=60, env=_get_ansible_env())

    item_type = "role" if role else "collection"
    if success:
        return f"✅ Removed {item_type}: {name}"
    return f"❌ Failed to remove {item_type}:\n\n```\n{output}\n```"


@auto_heal()
async def _ansible_galaxy_search_impl(
    search_term: str,
    role: bool = True,
    limit: int = 20,
) -> str:
    """
    Search Ansible Galaxy for roles or collections.

    Args:
        search_term: Search term
        role: True for roles, False for collections
        limit: Maximum results to return

    Returns:
        Search results.
    """
    if role:
        cmd = ["ansible-galaxy", "role", "search", search_term, f"--limit={limit}"]
    else:
        # Collections don't have CLI search, use role search or suggest web
        cmd = ["ansible-galaxy", "role", "search", search_term, f"--limit={limit}"]

    success, output = await run_cmd(cmd, timeout=60, env=_get_ansible_env())

    if success:
        return f"## Galaxy Search: {search_term}\n\n```\n{output}\n```"
    return f"❌ Search failed:\n\n```\n{output}\n```"


@auto_heal()
async def _ansible_vault_encrypt_impl(
    file_path: str,
    vault_password_file: str = "",
    vault_id: str = "",
) -> str:
    """
    Encrypt a file with Ansible Vault.

    Args:
        file_path: Path to file to encrypt
        vault_password_file: Path to vault password file
        vault_id: Vault ID label

    Returns:
        Encryption result.
    """
    cmd = ["ansible-vault", "encrypt", file_path]

    if vault_password_file:
        cmd.extend(["--vault-password-file", vault_password_file])
    if vault_id:
        cmd.extend(["--vault-id", vault_id])

    success, output = await run_cmd(cmd, timeout=60, env=_get_ansible_env())

    if success:
        return f"✅ Encrypted: {file_path}"
    return f"❌ Encryption failed:\n\n```\n{output}\n```"


@auto_heal()
async def _ansible_vault_decrypt_impl(
    file_path: str,
    vault_password_file: str = "",
) -> str:
    """
    Decrypt an Ansible Vault encrypted file.

    Args:
        file_path: Path to encrypted file
        vault_password_file: Path to vault password file

    Returns:
        Decryption result.
    """
    cmd = ["ansible-vault", "decrypt", file_path]

    if vault_password_file:
        cmd.extend(["--vault-password-file", vault_password_file])

    success, output = await run_cmd(cmd, timeout=60, env=_get_ansible_env())

    if success:
        return f"✅ Decrypted: {file_path}"
    return f"❌ Decryption failed:\n\n```\n{output}\n```"


@auto_heal()
async def _ansible_vault_view_impl(
    file_path: str,
    vault_password_file: str = "",
) -> str:
    """
    View contents of an encrypted vault file.

    Args:
        file_path: Path to encrypted file
        vault_password_file: Path to vault password file

    Returns:
        Decrypted file contents.
    """
    cmd = ["ansible-vault", "view", file_path]

    if vault_password_file:
        cmd.extend(["--vault-password-file", vault_password_file])

    success, output = await run_cmd(cmd, timeout=60, env=_get_ansible_env())

    if success:
        return f"## Vault: {file_path}\n\n```yaml\n{truncate_output(output, max_length=5000, mode='head')}\n```"
    return f"❌ Failed to view vault:\n\n```\n{output}\n```"


@auto_heal()
async def _ansible_vault_encrypt_string_impl(
    plaintext: str,
    name: str,
    vault_password_file: str = "",
) -> str:
    """
    Encrypt a string for use in YAML files.

    Args:
        plaintext: String to encrypt
        name: Variable name for the encrypted string
        vault_password_file: Path to vault password file

    Returns:
        Encrypted string in YAML format.
    """
    cmd = ["ansible-vault", "encrypt_string", plaintext, "--name", name]

    if vault_password_file:
        cmd.extend(["--vault-password-file", vault_password_file])

    success, output = await run_cmd(cmd, timeout=60, env=_get_ansible_env())

    if success:
        return f"## Encrypted String\n\n```yaml\n{output}\n```"
    return f"❌ String encryption failed:\n\n```\n{output}\n```"


@auto_heal()
async def _ansible_config_dump_impl(
    only_changed: bool = False,
) -> str:
    """
    Show current Ansible configuration.

    Args:
        only_changed: Only show settings that differ from defaults

    Returns:
        Configuration dump.
    """
    cmd = ["ansible-config", "dump"]

    if only_changed:
        cmd.append("--only-changed")

    success, output = await run_cmd(cmd, timeout=30, env=_get_ansible_env())

    if success:
        return f"## Ansible Configuration\n\n```\n{truncate_output(output, max_length=5000, mode='head')}\n```"
    return f"❌ Failed to dump config:\n\n```\n{output}\n```"


@auto_heal()
async def _ansible_version_impl() -> str:
    """
    Show Ansible version information.

    Returns:
        Version details including Python and module locations.
    """
    cmd = ["ansible", "--version"]

    success, output = await run_cmd(cmd, timeout=30, env=_get_ansible_env())

    if success:
        return f"## Ansible Version\n\n```\n{output}\n```"
    return f"❌ Failed to get version:\n\n```\n{output}\n```"


def register_tools(server: FastMCP) -> int:
    """
    Register Ansible tools with the MCP server.

    Args:
        server: FastMCP server instance

    Returns:
        Number of tools registered
    """
    registry = ToolRegistry(server)

    # Playbook tools
    @auto_heal()
    @registry.tool()
    async def ansible_playbook_run(
        playbook: str,
        inventory: str = "",
        limit: str = "",
        tags: str = "",
        skip_tags: str = "",
        extra_vars: str = "",
        verbose: int = 0,
        timeout: int = 600,
        cwd: str = "",
    ) -> str:
        """
        Run an Ansible playbook.

        Args:
            playbook: Path to the playbook file
            inventory: Inventory file or comma-separated hosts
            limit: Limit to specific hosts/groups
            tags: Only run plays and tasks tagged with these values
            skip_tags: Skip plays and tasks tagged with these values
            extra_vars: Extra variables as key=value or JSON string
            verbose: Verbosity level (0-4)
            timeout: Timeout in seconds
            cwd: Working directory (defaults to playbook directory)

        Returns:
            Playbook execution output.
        """
        return await _ansible_playbook_run_impl(
            playbook,
            inventory,
            limit,
            tags,
            skip_tags,
            extra_vars,
            verbose,
            timeout,
            cwd,
        )

    @auto_heal()
    @registry.tool()
    async def ansible_playbook_check(
        playbook: str,
        inventory: str = "",
        limit: str = "",
        extra_vars: str = "",
        diff: bool = True,
        timeout: int = 300,
        cwd: str = "",
    ) -> str:
        """
        Dry-run an Ansible playbook (check mode).

        Args:
            playbook: Path to the playbook file
            inventory: Inventory file or comma-separated hosts
            limit: Limit to specific hosts/groups
            extra_vars: Extra variables as key=value or JSON string
            diff: Show differences in files
            timeout: Timeout in seconds
            cwd: Working directory

        Returns:
            Check mode output showing what would change.
        """
        return await _ansible_playbook_check_impl(
            playbook, inventory, limit, extra_vars, diff, timeout, cwd
        )

    @auto_heal()
    @registry.tool()
    async def ansible_playbook_list_tasks(
        playbook: str,
        cwd: str = "",
    ) -> str:
        """
        List tasks in an Ansible playbook.

        Args:
            playbook: Path to the playbook file
            cwd: Working directory

        Returns:
            List of tasks in the playbook.
        """
        return await _ansible_playbook_list_tasks_impl(playbook, cwd)

    @auto_heal()
    @registry.tool()
    async def ansible_playbook_list_tags(
        playbook: str,
        cwd: str = "",
    ) -> str:
        """
        List tags in an Ansible playbook.

        Args:
            playbook: Path to the playbook file
            cwd: Working directory

        Returns:
            List of tags in the playbook.
        """
        return await _ansible_playbook_list_tags_impl(playbook, cwd)

    # Inventory tools
    @auto_heal()
    @registry.tool()
    async def ansible_inventory_list(
        inventory: str,
        host: str = "",
        yaml_output: bool = False,
    ) -> str:
        """
        List hosts in an Ansible inventory.

        Args:
            inventory: Inventory file path or directory
            host: Specific host to show (optional)
            yaml_output: Output in YAML format

        Returns:
            Inventory listing.
        """
        return await _ansible_inventory_list_impl(inventory, host, yaml_output)

    @auto_heal()
    @registry.tool()
    async def ansible_inventory_graph(
        inventory: str,
    ) -> str:
        """
        Show inventory hierarchy as a graph.

        Args:
            inventory: Inventory file path or directory

        Returns:
            Inventory graph showing group hierarchy.
        """
        return await _ansible_inventory_graph_impl(inventory)

    @auto_heal()
    @registry.tool()
    async def ansible_inventory_host(
        inventory: str,
        host: str,
    ) -> str:
        """
        Get variables for a specific host.

        Args:
            inventory: Inventory file path or directory
            host: Host name to get variables for

        Returns:
            Host variables in JSON format.
        """
        return await _ansible_inventory_host_impl(inventory, host)

    # Ad-hoc command tools
    @auto_heal()
    @registry.tool()
    async def ansible_ping(
        hosts: str,
        inventory: str = "",
        timeout: int = 60,
    ) -> str:
        """
        Ping hosts to check Ansible connectivity.

        Args:
            hosts: Host pattern (e.g., "all", "webservers", "host1,host2")
            inventory: Inventory file (optional, uses default if not specified)
            timeout: Timeout in seconds

        Returns:
            Ping results for each host.
        """
        return await _ansible_ping_impl(hosts, inventory, timeout)

    @auto_heal()
    @registry.tool()
    async def ansible_command(
        hosts: str,
        command: str,
        inventory: str = "",
        become: bool = False,
        timeout: int = 120,
    ) -> str:
        """
        Run an ad-hoc command on hosts.

        Args:
            hosts: Host pattern (e.g., "all", "webservers")
            command: Command to execute
            inventory: Inventory file (optional)
            become: Use privilege escalation (sudo)
            timeout: Timeout in seconds

        Returns:
            Command output from each host.
        """
        return await _ansible_command_impl(hosts, command, inventory, become, timeout)

    @auto_heal()
    @registry.tool()
    async def ansible_shell(
        hosts: str,
        command: str,
        inventory: str = "",
        become: bool = False,
        timeout: int = 120,
    ) -> str:
        """
        Run a shell command on hosts (supports pipes, redirects).

        Args:
            hosts: Host pattern (e.g., "all", "webservers")
            command: Shell command to execute
            inventory: Inventory file (optional)
            become: Use privilege escalation (sudo)
            timeout: Timeout in seconds

        Returns:
            Shell output from each host.
        """
        return await _ansible_shell_impl(hosts, command, inventory, become, timeout)

    @auto_heal()
    @registry.tool()
    async def ansible_copy(
        hosts: str,
        src: str,
        dest: str,
        inventory: str = "",
        become: bool = False,
        mode: str = "",
        timeout: int = 120,
    ) -> str:
        """
        Copy files to remote hosts.

        Args:
            hosts: Host pattern
            src: Source file path (local)
            dest: Destination path (remote)
            inventory: Inventory file (optional)
            become: Use privilege escalation
            mode: File permissions (e.g., "0644")
            timeout: Timeout in seconds

        Returns:
            Copy result.
        """
        return await _ansible_copy_impl(
            hosts, src, dest, inventory, become, mode, timeout
        )

    @auto_heal()
    @registry.tool()
    async def ansible_fetch(
        hosts: str,
        src: str,
        dest: str,
        inventory: str = "",
        flat: bool = False,
        timeout: int = 120,
    ) -> str:
        """
        Fetch files from remote hosts.

        Args:
            hosts: Host pattern
            src: Source file path (remote)
            dest: Destination directory (local)
            inventory: Inventory file (optional)
            flat: Store files directly in dest without host subdirs
            timeout: Timeout in seconds

        Returns:
            Fetch result.
        """
        return await _ansible_fetch_impl(hosts, src, dest, inventory, flat, timeout)

    @auto_heal()
    @registry.tool()
    async def ansible_setup(
        hosts: str,
        inventory: str = "",
        filter_facts: str = "",
        timeout: int = 120,
    ) -> str:
        """
        Gather facts from hosts.

        Args:
            hosts: Host pattern
            inventory: Inventory file (optional)
            filter_facts: Filter facts by pattern (e.g., "ansible_os*")
            timeout: Timeout in seconds

        Returns:
            Host facts.
        """
        return await _ansible_setup_impl(hosts, inventory, filter_facts, timeout)

    # Galaxy tools
    @auto_heal()
    @registry.tool()
    async def ansible_galaxy_install(
        name: str,
        role: bool = True,
        version: str = "",
        force: bool = False,
        timeout: int = 180,
    ) -> str:
        """
        Install a role or collection from Ansible Galaxy.

        Args:
            name: Role/collection name (e.g., "geerlingguy.docker" or "community.general")
            role: True for role, False for collection
            version: Specific version to install
            force: Force reinstall if already installed
            timeout: Timeout in seconds

        Returns:
            Installation result.
        """
        return await _ansible_galaxy_install_impl(name, role, version, force, timeout)

    @auto_heal()
    @registry.tool()
    async def ansible_galaxy_list(
        role: bool = True,
    ) -> str:
        """
        List installed roles or collections.

        Args:
            role: True for roles, False for collections

        Returns:
            List of installed items.
        """
        return await _ansible_galaxy_list_impl(role)

    @auto_heal()
    @registry.tool()
    async def ansible_galaxy_remove(
        name: str,
        role: bool = True,
    ) -> str:
        """
        Remove an installed role or collection.

        Args:
            name: Role/collection name to remove
            role: True for role, False for collection

        Returns:
            Removal result.
        """
        return await _ansible_galaxy_remove_impl(name, role)

    @auto_heal()
    @registry.tool()
    async def ansible_galaxy_search(
        search_term: str,
        role: bool = True,
        limit: int = 20,
    ) -> str:
        """
        Search Ansible Galaxy for roles or collections.

        Args:
            search_term: Search term
            role: True for roles, False for collections
            limit: Maximum results to return

        Returns:
            Search results.
        """
        return await _ansible_galaxy_search_impl(search_term, role, limit)

    # Vault tools
    @auto_heal()
    @registry.tool()
    async def ansible_vault_encrypt(
        file_path: str,
        vault_password_file: str = "",
        vault_id: str = "",
    ) -> str:
        """
        Encrypt a file with Ansible Vault.

        Args:
            file_path: Path to file to encrypt
            vault_password_file: Path to vault password file
            vault_id: Vault ID label

        Returns:
            Encryption result.
        """
        return await _ansible_vault_encrypt_impl(
            file_path, vault_password_file, vault_id
        )

    @auto_heal()
    @registry.tool()
    async def ansible_vault_decrypt(
        file_path: str,
        vault_password_file: str = "",
    ) -> str:
        """
        Decrypt an Ansible Vault encrypted file.

        Args:
            file_path: Path to encrypted file
            vault_password_file: Path to vault password file

        Returns:
            Decryption result.
        """
        return await _ansible_vault_decrypt_impl(file_path, vault_password_file)

    @auto_heal()
    @registry.tool()
    async def ansible_vault_view(
        file_path: str,
        vault_password_file: str = "",
    ) -> str:
        """
        View contents of an encrypted vault file.

        Args:
            file_path: Path to encrypted file
            vault_password_file: Path to vault password file

        Returns:
            Decrypted file contents.
        """
        return await _ansible_vault_view_impl(file_path, vault_password_file)

    @auto_heal()
    @registry.tool()
    async def ansible_vault_encrypt_string(
        plaintext: str,
        name: str,
        vault_password_file: str = "",
    ) -> str:
        """
        Encrypt a string for use in YAML files.

        Args:
            plaintext: String to encrypt
            name: Variable name for the encrypted string
            vault_password_file: Path to vault password file

        Returns:
            Encrypted string in YAML format.
        """
        return await _ansible_vault_encrypt_string_impl(
            plaintext, name, vault_password_file
        )

    # Config tools
    @auto_heal()
    @registry.tool()
    async def ansible_config_dump(
        only_changed: bool = False,
    ) -> str:
        """
        Show current Ansible configuration.

        Args:
            only_changed: Only show settings that differ from defaults

        Returns:
            Configuration dump.
        """
        return await _ansible_config_dump_impl(only_changed)

    @auto_heal()
    @registry.tool()
    async def ansible_version() -> str:
        """
        Show Ansible version information.

        Returns:
            Version details including Python and module locations.
        """
        return await _ansible_version_impl()

    return registry.count
