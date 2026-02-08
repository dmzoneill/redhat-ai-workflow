"""
Base utilities for command handler modules.

Provides a HandlerContext dataclass to bundle shared dependencies
that handler functions receive from the CommandHandler dispatcher.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Coroutine

if TYPE_CHECKING:
    from scripts.common.command_parser import ParsedCommand  # noqa: F401
    from scripts.common.context_extractor import ConversationContext

logger = logging.getLogger(__name__)


@dataclass
class HandlerContext:
    """Shared dependencies passed from CommandHandler to handler functions."""

    call_dbus: Callable[..., Coroutine[Any, Any, dict]]
    extract_context: Callable[..., Coroutine[Any, Any, "ConversationContext"]]
    run_skill: Callable[..., Coroutine[Any, Any, str]]
    run_tool: Callable[..., Coroutine[Any, Any, str]]
    claude_agent: Any  # ClaudeAgent or None
