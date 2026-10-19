"""Slack MCP tool definitions.

Re-exports the module API so existing imports keep working.
"""

from tool_modules.aa_slack.src.slack_query_impl import (
    _find_channel_from_config,
    _query_knowledge_cache,
    _query_via_dbus,
    _resolve_target_from_config,
    _slack_cache_stats_impl,
    _slack_find_channel_impl,
    _slack_find_user_impl,
    _slack_list_groups_impl,
    _slack_list_my_channels_impl,
    _slack_resolve_target_impl,
    register_tools,
)
from tool_modules.aa_slack.src.slack_tools_impl import (
    _TOOLS_DIR,
    TOOL_MODULES_DIR,
    __project_root__,
    _get_slack_config,
    _manager,
    _manager_lock,
    _send_via_dbus,
    _shared__send_via_dbus,
    _shared_get_manager,
    _slack_dm_gitlab_user_impl,
    _slack_get_user_impl,
    _slack_list_channels_impl,
    _slack_post_team_impl,
    _slack_search_messages_impl,
    _slack_send_message_impl,
    get_manager,
    logger,
)

_REEXPORT_SLACK = "slack"

__all__ = [
    "TOOL_MODULES_DIR",
    "_TOOLS_DIR",
    "__project_root__",
    "_find_channel_from_config",
    "_get_slack_config",
    "_manager",
    "_manager_lock",
    "_query_knowledge_cache",
    "_query_via_dbus",
    "_resolve_target_from_config",
    "_send_via_dbus",
    "_shared__send_via_dbus",
    "_shared_get_manager",
    "_slack_cache_stats_impl",
    "_slack_dm_gitlab_user_impl",
    "_slack_find_channel_impl",
    "_slack_find_user_impl",
    "_slack_get_user_impl",
    "_slack_list_channels_impl",
    "_slack_list_groups_impl",
    "_slack_list_my_channels_impl",
    "_slack_post_team_impl",
    "_slack_resolve_target_impl",
    "_slack_search_messages_impl",
    "_slack_send_message_impl",
    "get_manager",
    "logger",
    "register_tools",
]
