"""AWS CLI tool definitions - Amazon Web Services management.

Provides:
S3 tools:
- aws_s3_ls: List S3 buckets or objects
- aws_s3_cp: Copy files to/from S3
- aws_s3_sync: Sync directories with S3
- aws_s3_rm: Remove S3 objects
- aws_s3_mb: Create S3 bucket
- aws_s3_rb: Remove S3 bucket

EC2 tools:
- aws_ec2_describe_instances: List EC2 instances
- aws_ec2_start_instances: Start EC2 instances
- aws_ec2_stop_instances: Stop EC2 instances
- aws_ec2_describe_security_groups: List security groups

IAM tools:
- aws_iam_list_users: List IAM users
- aws_iam_list_roles: List IAM roles
- aws_iam_get_user: Get IAM user details

General tools:
- aws_sts_get_caller_identity: Get current AWS identity
- aws_configure_list: Show AWS configuration
- aws_regions_list: List available AWS regions
"""

import logging
import os

from fastmcp import FastMCP

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import run_cmd, truncate_output

logger = logging.getLogger(__name__)


def _get_aws_env() -> dict:
    """Get environment variables for AWS commands."""
    env = os.environ.copy()
    # Disable pager for non-interactive use
    env.setdefault("AWS_PAGER", "")
    return env


@auto_heal()
async def _aws_s3_ls_impl(
    path: str = "",
    recursive: bool = False,
    human_readable: bool = True,
    profile: str = "",
) -> str:
    """List S3 buckets or objects."""
    cmd = ["aws", "s3", "ls"]
    if path:
        cmd.append(path)
    if recursive:
        cmd.append("--recursive")
    if human_readable:
        cmd.append("--human-readable")
    if profile:
        cmd.extend(["--profile", profile])

    success, output = await run_cmd(cmd, timeout=60, env=_get_aws_env())
    if success:
        return f"## S3 Listing\n\n```\n{truncate_output(output, max_length=5000, mode='tail')}\n```"
    return f"❌ Failed to list S3: {output}"


@auto_heal()
async def _aws_s3_cp_impl(
    source: str,
    destination: str,
    recursive: bool = False,
    profile: str = "",
    timeout: int = 300,
) -> str:
    """Copy files to/from S3."""
    cmd = ["aws", "s3", "cp", source, destination]
    if recursive:
        cmd.append("--recursive")
    if profile:
        cmd.extend(["--profile", profile])

    success, output = await run_cmd(cmd, timeout=timeout, env=_get_aws_env())
    if success:
        return f"✅ Copied {source} to {destination}\n\n{output}"
    return f"❌ Copy failed: {output}"


@auto_heal()
async def _aws_s3_sync_impl(
    source: str,
    destination: str,
    delete: bool = False,
    exclude: str = "",
    include: str = "",
    profile: str = "",
    timeout: int = 600,
) -> str:
    """Sync directories with S3."""
    cmd = ["aws", "s3", "sync", source, destination]
    if delete:
        cmd.append("--delete")
    if exclude:
        cmd.extend(["--exclude", exclude])
    if include:
        cmd.extend(["--include", include])
    if profile:
        cmd.extend(["--profile", profile])

    success, output = await run_cmd(cmd, timeout=timeout, env=_get_aws_env())
    if success:
        return f"✅ Synced {source} to {destination}\n\n{truncate_output(output, max_length=3000, mode='tail')}"
    return f"❌ Sync failed: {output}"


@auto_heal()
async def _aws_s3_rm_impl(
    path: str,
    recursive: bool = False,
    profile: str = "",
) -> str:
    """Remove S3 objects."""
    cmd = ["aws", "s3", "rm", path]
    if recursive:
        cmd.append("--recursive")
    if profile:
        cmd.extend(["--profile", profile])

    success, output = await run_cmd(cmd, timeout=120, env=_get_aws_env())
    if success:
        return f"✅ Removed {path}\n\n{output}"
    return f"❌ Remove failed: {output}"


@auto_heal()
async def _aws_s3_mb_impl(bucket: str, profile: str = "") -> str:
    """Create S3 bucket."""
    cmd = ["aws", "s3", "mb", bucket]
    if profile:
        cmd.extend(["--profile", profile])

    success, output = await run_cmd(cmd, timeout=60, env=_get_aws_env())
    if success:
        return f"✅ Created bucket {bucket}"
    return f"❌ Failed to create bucket: {output}"


@auto_heal()
async def _aws_s3_rb_impl(bucket: str, force: bool = False, profile: str = "") -> str:
    """Remove S3 bucket."""
    cmd = ["aws", "s3", "rb", bucket]
    if force:
        cmd.append("--force")
    if profile:
        cmd.extend(["--profile", profile])

    success, output = await run_cmd(cmd, timeout=120, env=_get_aws_env())
    if success:
        return f"✅ Removed bucket {bucket}"
    return f"❌ Failed to remove bucket: {output}"


@auto_heal()
async def _aws_ec2_describe_instances_impl(
    instance_ids: str = "",
    filters: str = "",
    profile: str = "",
) -> str:
    """List EC2 instances."""
    cmd = ["aws", "ec2", "describe-instances", "--output", "table"]
    if instance_ids:
        cmd.extend(["--instance-ids"] + instance_ids.split())
    if filters:
        cmd.extend(["--filters", filters])
    if profile:
        cmd.extend(["--profile", profile])

    success, output = await run_cmd(cmd, timeout=60, env=_get_aws_env())
    if success:
        return f"## EC2 Instances\n\n```\n{truncate_output(output, max_length=5000, mode='head')}\n```"
    return f"❌ Failed to describe instances: {output}"


@auto_heal()
async def _aws_ec2_start_instances_impl(instance_ids: str, profile: str = "") -> str:
    """Start EC2 instances."""
    cmd = ["aws", "ec2", "start-instances", "--instance-ids"] + instance_ids.split()
    if profile:
        cmd.extend(["--profile", profile])

    success, output = await run_cmd(cmd, timeout=60, env=_get_aws_env())
    if success:
        return f"✅ Started instances: {instance_ids}\n\n{output}"
    return f"❌ Failed to start instances: {output}"


@auto_heal()
async def _aws_ec2_stop_instances_impl(instance_ids: str, profile: str = "") -> str:
    """Stop EC2 instances."""
    cmd = ["aws", "ec2", "stop-instances", "--instance-ids"] + instance_ids.split()
    if profile:
        cmd.extend(["--profile", profile])

    success, output = await run_cmd(cmd, timeout=60, env=_get_aws_env())
    if success:
        return f"✅ Stopped instances: {instance_ids}\n\n{output}"
    return f"❌ Failed to stop instances: {output}"


@auto_heal()
async def _aws_ec2_describe_security_groups_impl(
    group_ids: str = "",
    profile: str = "",
) -> str:
    """List security groups."""
    cmd = ["aws", "ec2", "describe-security-groups", "--output", "table"]
    if group_ids:
        cmd.extend(["--group-ids"] + group_ids.split())
    if profile:
        cmd.extend(["--profile", profile])

    success, output = await run_cmd(cmd, timeout=60, env=_get_aws_env())
    if success:
        return f"## Security Groups\n\n```\n{truncate_output(output, max_length=5000, mode='head')}\n```"
    return f"❌ Failed to describe security groups: {output}"


@auto_heal()
async def _aws_iam_list_users_impl(profile: str = "") -> str:
    """List IAM users."""
    cmd = ["aws", "iam", "list-users", "--output", "table"]
    if profile:
        cmd.extend(["--profile", profile])

    success, output = await run_cmd(cmd, timeout=60, env=_get_aws_env())
    if success:
        return f"## IAM Users\n\n```\n{output}\n```"
    return f"❌ Failed to list users: {output}"


@auto_heal()
async def _aws_iam_list_roles_impl(profile: str = "") -> str:
    """List IAM roles."""
    cmd = ["aws", "iam", "list-roles", "--output", "table"]
    if profile:
        cmd.extend(["--profile", profile])

    success, output = await run_cmd(cmd, timeout=60, env=_get_aws_env())
    if success:
        return f"## IAM Roles\n\n```\n{truncate_output(output, max_length=5000, mode='head')}\n```"
    return f"❌ Failed to list roles: {output}"


@auto_heal()
async def _aws_iam_get_user_impl(user_name: str = "", profile: str = "") -> str:
    """Get IAM user details."""
    cmd = ["aws", "iam", "get-user"]
    if user_name:
        cmd.extend(["--user-name", user_name])
    if profile:
        cmd.extend(["--profile", profile])

    success, output = await run_cmd(cmd, timeout=60, env=_get_aws_env())
    if success:
        return f"## IAM User\n\n```json\n{output}\n```"
    return f"❌ Failed to get user: {output}"


@auto_heal()
async def _aws_sts_get_caller_identity_impl(profile: str = "") -> str:
    """Get current AWS identity."""
    cmd = ["aws", "sts", "get-caller-identity"]
    if profile:
        cmd.extend(["--profile", profile])

    success, output = await run_cmd(cmd, timeout=30, env=_get_aws_env())
    if success:
        return f"## AWS Identity\n\n```json\n{output}\n```"
    return f"❌ Failed to get identity: {output}"


@auto_heal()
async def _aws_configure_list_impl(profile: str = "") -> str:
    """Show AWS configuration."""
    cmd = ["aws", "configure", "list"]
    if profile:
        cmd.extend(["--profile", profile])

    success, output = await run_cmd(cmd, timeout=30, env=_get_aws_env())
    if success:
        return f"## AWS Configuration\n\n```\n{output}\n```"
    return f"❌ Failed to list configuration: {output}"


@auto_heal()
async def _aws_regions_list_impl(profile: str = "") -> str:
    """List available AWS regions."""
    cmd = ["aws", "ec2", "describe-regions", "--output", "table"]
    if profile:
        cmd.extend(["--profile", profile])

    success, output = await run_cmd(cmd, timeout=30, env=_get_aws_env())
    if success:
        return f"## AWS Regions\n\n```\n{output}\n```"
    return f"❌ Failed to list regions: {output}"


def register_tools(server: FastMCP) -> int:
    """Register AWS tools with the MCP server."""
    registry = ToolRegistry(server)

    @auto_heal()
    @registry.tool()
    async def aws_s3_ls(
        path: str = "",
        recursive: bool = False,
        human_readable: bool = True,
        profile: str = "",
    ) -> str:
        """List S3 buckets or objects.

        Args:
            path: S3 path (s3://bucket/prefix) or empty for all buckets
            recursive: List recursively
            human_readable: Show sizes in human-readable format
            profile: AWS profile to use
        """
        return await _aws_s3_ls_impl(path, recursive, human_readable, profile)

    @auto_heal()
    @registry.tool()
    async def aws_s3_cp(
        source: str,
        destination: str,
        recursive: bool = False,
        profile: str = "",
    ) -> str:
        """Copy files to/from S3.

        Args:
            source: Source path (local or s3://)
            destination: Destination path (local or s3://)
            recursive: Copy recursively
            profile: AWS profile to use
        """
        return await _aws_s3_cp_impl(source, destination, recursive, profile)

    @auto_heal()
    @registry.tool()
    async def aws_s3_sync(
        source: str,
        destination: str,
        delete: bool = False,
        profile: str = "",
    ) -> str:
        """Sync directories with S3.

        Args:
            source: Source path
            destination: Destination path
            delete: Delete files in destination not in source
            profile: AWS profile to use
        """
        return await _aws_s3_sync_impl(source, destination, delete, "", "", profile)

    @auto_heal()
    @registry.tool()
    async def aws_s3_rm(path: str, recursive: bool = False, profile: str = "") -> str:
        """Remove S3 objects.

        Args:
            path: S3 path to remove
            recursive: Remove recursively
            profile: AWS profile to use
        """
        return await _aws_s3_rm_impl(path, recursive, profile)

    @auto_heal()
    @registry.tool()
    async def aws_s3_mb(bucket: str, profile: str = "") -> str:
        """Create S3 bucket.

        Args:
            bucket: Bucket name (s3://bucket-name)
            profile: AWS profile to use
        """
        return await _aws_s3_mb_impl(bucket, profile)

    @auto_heal()
    @registry.tool()
    async def aws_s3_rb(bucket: str, force: bool = False, profile: str = "") -> str:
        """Remove S3 bucket.

        Args:
            bucket: Bucket name (s3://bucket-name)
            force: Force removal (delete all objects first)
            profile: AWS profile to use
        """
        return await _aws_s3_rb_impl(bucket, force, profile)

    @auto_heal()
    @registry.tool()
    async def aws_ec2_describe_instances(
        instance_ids: str = "",
        profile: str = "",
    ) -> str:
        """List EC2 instances.

        Args:
            instance_ids: Space-separated instance IDs (optional)
            profile: AWS profile to use
        """
        return await _aws_ec2_describe_instances_impl(instance_ids, "", profile)

    @auto_heal()
    @registry.tool()
    async def aws_ec2_start_instances(instance_ids: str, profile: str = "") -> str:
        """Start EC2 instances.

        Args:
            instance_ids: Space-separated instance IDs
            profile: AWS profile to use
        """
        return await _aws_ec2_start_instances_impl(instance_ids, profile)

    @auto_heal()
    @registry.tool()
    async def aws_ec2_stop_instances(instance_ids: str, profile: str = "") -> str:
        """Stop EC2 instances.

        Args:
            instance_ids: Space-separated instance IDs
            profile: AWS profile to use
        """
        return await _aws_ec2_stop_instances_impl(instance_ids, profile)

    @auto_heal()
    @registry.tool()
    async def aws_ec2_describe_security_groups(
        group_ids: str = "",
        profile: str = "",
    ) -> str:
        """List security groups.

        Args:
            group_ids: Space-separated security group IDs (optional)
            profile: AWS profile to use
        """
        return await _aws_ec2_describe_security_groups_impl(group_ids, profile)

    @auto_heal()
    @registry.tool()
    async def aws_iam_list_users(profile: str = "") -> str:
        """List IAM users.

        Args:
            profile: AWS profile to use
        """
        return await _aws_iam_list_users_impl(profile)

    @auto_heal()
    @registry.tool()
    async def aws_iam_list_roles(profile: str = "") -> str:
        """List IAM roles.

        Args:
            profile: AWS profile to use
        """
        return await _aws_iam_list_roles_impl(profile)

    @auto_heal()
    @registry.tool()
    async def aws_iam_get_user(user_name: str = "", profile: str = "") -> str:
        """Get IAM user details.

        Args:
            user_name: User name (default: current user)
            profile: AWS profile to use
        """
        return await _aws_iam_get_user_impl(user_name, profile)

    @auto_heal()
    @registry.tool()
    async def aws_sts_get_caller_identity(profile: str = "") -> str:
        """Get current AWS identity.

        Args:
            profile: AWS profile to use
        """
        return await _aws_sts_get_caller_identity_impl(profile)

    @auto_heal()
    @registry.tool()
    async def aws_configure_list(profile: str = "") -> str:
        """Show AWS configuration.

        Args:
            profile: AWS profile to use
        """
        return await _aws_configure_list_impl(profile)

    @auto_heal()
    @registry.tool()
    async def aws_regions_list(profile: str = "") -> str:
        """List available AWS regions.

        Args:
            profile: AWS profile to use
        """
        return await _aws_regions_list_impl(profile)

    return registry.count
