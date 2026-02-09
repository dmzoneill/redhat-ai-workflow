"""Ansible core tools - essential automation operations.

This module provides the minimal set of Ansible tools needed for most workflows:
- ansible_playbook_run: Run playbooks
- ansible_inventory_list: List inventory
- ansible_ping: Test connectivity
- ansible_command: Run ad-hoc commands
- ansible_setup: Gather facts
- ansible_vault_encrypt, ansible_vault_decrypt: Secrets management

Total: ~8 core tools (down from 23 in basic)
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
        _ansible_command_impl,
        _ansible_inventory_list_impl,
        _ansible_ping_impl,
        _ansible_playbook_run_impl,
        _ansible_setup_impl,
        _ansible_vault_decrypt_impl,
        _ansible_vault_encrypt_impl,
        _ansible_version_impl,
    )
except ImportError:
    # Direct loading - use importlib to avoid sys.path pollution
    _basic_file = Path(__file__).parent / "tools_basic.py"
    _spec = importlib.util.spec_from_file_location("ansible_tools_basic", _basic_file)
    _basic_module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_basic_module)
    _ansible_command_impl = _basic_module._ansible_command_impl
    _ansible_inventory_list_impl = _basic_module._ansible_inventory_list_impl
    _ansible_ping_impl = _basic_module._ansible_ping_impl
    _ansible_playbook_run_impl = _basic_module._ansible_playbook_run_impl
    _ansible_setup_impl = _basic_module._ansible_setup_impl
    _ansible_vault_decrypt_impl = _basic_module._ansible_vault_decrypt_impl
    _ansible_vault_encrypt_impl = _basic_module._ansible_vault_encrypt_impl
    _ansible_version_impl = _basic_module._ansible_version_impl

logger = logging.getLogger(__name__)


def register_tools(server: FastMCP) -> int:
    """Register core Ansible tools."""
    registry = ToolRegistry(server)

    @auto_heal()
    @registry.tool()
    async def ansible_playbook_run(
        playbook: str,
        inventory: str = "",
        extra_vars: str = "",
        tags: str = "",
        limit: str = "",
    ) -> str:
        """Run an Ansible playbook."""
        return await _ansible_playbook_run_impl(
            playbook, inventory, extra_vars, tags, limit
        )

    @auto_heal()
    @registry.tool()
    async def ansible_inventory_list(inventory: str = "") -> str:
        """List hosts in inventory."""
        return await _ansible_inventory_list_impl(inventory)

    @auto_heal()
    @registry.tool()
    async def ansible_ping(hosts: str = "all", inventory: str = "") -> str:
        """Test connectivity to hosts."""
        return await _ansible_ping_impl(hosts, inventory)

    @auto_heal()
    @registry.tool()
    async def ansible_command(hosts: str, command: str, inventory: str = "") -> str:
        """Run ad-hoc command on hosts."""
        return await _ansible_command_impl(hosts, command, inventory)

    @auto_heal()
    @registry.tool()
    async def ansible_setup(
        hosts: str = "all", inventory: str = "", filter: str = ""
    ) -> str:
        """Gather facts from hosts."""
        return await _ansible_setup_impl(hosts, inventory, filter)

    @auto_heal()
    @registry.tool()
    async def ansible_vault_encrypt(file: str, vault_password_file: str = "") -> str:
        """Encrypt a file with Ansible Vault."""
        return await _ansible_vault_encrypt_impl(file, vault_password_file)

    @auto_heal()
    @registry.tool()
    async def ansible_vault_decrypt(file: str, vault_password_file: str = "") -> str:
        """Decrypt a file with Ansible Vault."""
        return await _ansible_vault_decrypt_impl(file, vault_password_file)

    @auto_heal()
    @registry.tool()
    async def ansible_version() -> str:
        """Get Ansible version information."""
        return await _ansible_version_impl()

    logger.info(f"Registered {registry.count} core Ansible tools")
    return registry.count
