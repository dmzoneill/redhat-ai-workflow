"""AWS core tools - essential cloud operations.

This module provides the minimal set of AWS tools needed for most workflows:
- aws_s3_ls, aws_s3_cp: S3 operations
- aws_ec2_describe_instances: EC2 info
- aws_sts_get_caller_identity: Auth check
- aws_configure_list: Config info
- aws_regions_list: Available regions

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
        _aws_configure_list_impl,
        _aws_ec2_describe_instances_impl,
        _aws_regions_list_impl,
        _aws_s3_cp_impl,
        _aws_s3_ls_impl,
        _aws_sts_get_caller_identity_impl,
    )
except ImportError:
    # Direct loading - use importlib to avoid sys.path pollution
    _basic_file = Path(__file__).parent / "tools_basic.py"
    _spec = importlib.util.spec_from_file_location("aws_tools_basic", _basic_file)
    _basic_module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_basic_module)
    _aws_configure_list_impl = _basic_module._aws_configure_list_impl
    _aws_ec2_describe_instances_impl = _basic_module._aws_ec2_describe_instances_impl
    _aws_regions_list_impl = _basic_module._aws_regions_list_impl
    _aws_s3_cp_impl = _basic_module._aws_s3_cp_impl
    _aws_s3_ls_impl = _basic_module._aws_s3_ls_impl
    _aws_sts_get_caller_identity_impl = _basic_module._aws_sts_get_caller_identity_impl

logger = logging.getLogger(__name__)


def register_tools(server: FastMCP) -> int:
    """Register core AWS tools."""
    registry = ToolRegistry(server)

    @auto_heal()
    @registry.tool()
    async def aws_s3_ls(
        path: str = "", recursive: bool = False, profile: str = ""
    ) -> str:
        """List S3 buckets or objects."""
        return await _aws_s3_ls_impl(path, recursive, profile)

    @auto_heal()
    @registry.tool()
    async def aws_s3_cp(
        source: str, destination: str, recursive: bool = False, profile: str = ""
    ) -> str:
        """Copy files to/from S3."""
        return await _aws_s3_cp_impl(source, destination, recursive, profile)

    @auto_heal()
    @registry.tool()
    async def aws_ec2_describe_instances(
        instance_ids: str = "", filters: str = "", profile: str = ""
    ) -> str:
        """Describe EC2 instances."""
        return await _aws_ec2_describe_instances_impl(instance_ids, filters, profile)

    @auto_heal()
    @registry.tool()
    async def aws_sts_get_caller_identity(profile: str = "") -> str:
        """Get current AWS identity."""
        return await _aws_sts_get_caller_identity_impl(profile)

    @auto_heal()
    @registry.tool()
    async def aws_configure_list(profile: str = "") -> str:
        """List AWS configuration."""
        return await _aws_configure_list_impl(profile)

    @auto_heal()
    @registry.tool()
    async def aws_regions_list(profile: str = "") -> str:
        """List available AWS regions."""
        return await _aws_regions_list_impl(profile)

    logger.info(f"Registered {registry.count} core AWS tools")
    return registry.count
