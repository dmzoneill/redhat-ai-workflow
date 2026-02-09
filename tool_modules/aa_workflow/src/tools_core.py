"""Workflow core tools - essential session, persona, skill, and memory operations.

This module provides the minimal set of workflow tools needed by ALL personas:
- Session management: session_start, session_info
- Persona management: persona_load, persona_list
- Skill execution: skill_run, skill_list
- Memory (YAML): memory_read, memory_write, memory_session_log
- Memory (Unified): memory_ask, memory_search, memory_list_adapters, memory_health
- Meta: tool_list, tool_exec
- Infra: vpn_connect, kube_login (required for auto-healing)

For additional tools (knowledge, project, scheduler, sprint), use:
- workflow_basic: Loads core + basic tools
- tool_exec("knowledge_search", {...}): Call specific tools on-demand

Total: ~25 core tools (down from 54 in basic)
"""

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

# Setup project path for server imports (must be before server imports)
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

# Add this directory to path for direct loading support
_TOOLS_DIR = Path(__file__).parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

# Import registration functions from sub-modules
# Support both package import and direct loading
try:
    from .infra_tools import register_infra_tools
    from .memory_tools import register_memory_tools
    from .persona_tools import register_persona_tools
    from .resources import register_resources
    from .session_tools import register_prompts, register_session_tools
    from .skill_engine import register_skill_tools
except ImportError:
    from infra_tools import register_infra_tools
    from memory_tools import register_memory_tools
    from persona_tools import register_persona_tools
    from resources import register_resources
    from session_tools import register_prompts, register_session_tools
    from skill_engine import register_skill_tools

from server.utils import load_config  # noqa: E402

if TYPE_CHECKING:
    from fastmcp import FastMCP

__project_root__ = PROJECT_ROOT  # Module initialization

logger = logging.getLogger(__name__)

# GitHub configuration for error reporting (used by skill_engine)
GITHUB_REPO = "dmzoneill/redhat-ai-workflow"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/issues"


async def create_github_issue(
    tool: str,
    error: str,
    context: str = "",
    skill: str = "",
    labels: list[str] | None = None,
) -> dict:
    """Create a GitHub issue for tool/skill failure (stub for core module)."""
    # This is a simplified version - full implementation in tools_basic.py
    return {
        "success": False,
        "message": "GitHub issue creation requires workflow_basic module",
    }


def register_tools(server: "FastMCP") -> int:
    """
    Register CORE workflow tools with the MCP server.

    Core tools (~20 tools):
    - persona_tools: 2 tools (persona_load, persona_list)
    - session_tools: 5 tools (session_start, session_info, session_list, session_switch, session_rename)
    - skill_engine: 2 tools (skill_run, skill_list)
    - memory_tools: 9 tools (memory_read, memory_write, memory_list, memory_append, memory_delete,
                             memory_session_log, memory_search, memory_backup, memory_restore)
    - infra_tools: 2 tools (vpn_connect, kube_login) - required for auto-healing

    Note: This is a subset of the full workflow module. For additional tools
    (knowledge, project, scheduler, sprint, meta), load workflow_basic.

    Args:
        server: FastMCP server instance

    Returns:
        Number of tools registered
    """
    tool_count = 0

    # Detect Claude Code and set up AskUserQuestion integration
    ask_question_fn = None
    try:
        try:
            from .claude_code_integration import (
                create_ask_question_wrapper,
                get_claude_code_capabilities,
            )
        except ImportError:
            from claude_code_integration import (
                create_ask_question_wrapper,
                get_claude_code_capabilities,
            )

        capabilities = get_claude_code_capabilities()
        logger.info(f"Claude Code detection: {capabilities}")

        ask_question_fn = create_ask_question_wrapper(server)
        if ask_question_fn:
            logger.info("✅ AskUserQuestion integration enabled")
    except ImportError:
        logger.debug("Claude Code integration module not available")

    # Register CORE tools only
    tool_count += register_memory_tools(server)
    tool_count += register_persona_tools(server)
    tool_count += register_session_tools(server)
    tool_count += register_prompts(server)
    tool_count += register_resources(server, load_config)
    tool_count += register_skill_tools(server, create_github_issue, ask_question_fn)
    tool_count += register_infra_tools(
        server
    )  # vpn_connect, kube_login for auto-healing

    # Register unified memory abstraction tools (memory_ask, memory_search, etc.)
    try:
        try:
            from .memory_unified import register_tools as register_unified_memory_tools
        except ImportError:
            from memory_unified import register_tools as register_unified_memory_tools
        tool_count += register_unified_memory_tools(server)
        logger.info("✅ Unified memory abstraction tools registered")
    except ImportError as e:
        logger.warning(f"Unified memory tools not available: {e}")

    logger.info(f"Registered {tool_count} core workflow tools")
    return tool_count
