# Common utilities for skills and @me command system

# @me Command System exports
from scripts.common.command_parser import (
    CommandParser,
    ParsedCommand,
    TriggerType,
    parse_command,
)
from scripts.common.command_registry import (
    CommandHelp,
    CommandInfo,
    CommandRegistry,
    CommandType,
    get_command_help,
    get_registry,
    list_commands,
)
from scripts.common.context_extractor import (
    ContextExtractor,
    ConversationContext,
    extract_context,
)
from scripts.common.response_router import (
    CommandContext,
    ResponseConfig,
    ResponseFormatter,
    ResponseMode,
    ResponseRouter,
    get_router,
    route_response,
)

__all__ = [
    # Command Parser
    "CommandParser",
    "ParsedCommand",
    "TriggerType",
    "parse_command",
    # Command Registry
    "CommandRegistry",
    "CommandInfo",
    "CommandHelp",
    "CommandType",
    "get_registry",
    "list_commands",
    "get_command_help",
    # Context Extractor
    "ContextExtractor",
    "ConversationContext",
    "extract_context",
    # Response Router
    "ResponseRouter",
    "ResponseFormatter",
    "ResponseConfig",
    "CommandContext",
    "ResponseMode",
    "get_router",
    "route_response",
]
