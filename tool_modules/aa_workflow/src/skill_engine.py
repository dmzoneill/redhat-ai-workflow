# pylint: disable=duplicate-code,cyclic-import
"""Skill Execution Engine - Multi-step workflow execution.

Provides:
- skill_list: List available skills
- skill_run: Execute a skill
- SkillExecutor: Class that handles step-by-step execution

This module is workspace-aware: skill execution context includes workspace_uri
for proper isolation of skill state and events per workspace.

Implementation lives in sibling modules. Names are re-exported so existing
imports keep working. ``SKILLS_DIR`` stays here because tests patch it.
"""

import logging
from pathlib import Path

from tool_modules.common import PROJECT_ROOT

try:
    from .constants import SKILLS_DIR, TOOL_MODULES_DIR
except ImportError:
    TOOL_MODULES_DIR = Path(__file__).parent.parent.parent
    SKILLS_DIR = TOOL_MODULES_DIR.parent / "skills"

# Sibling imports follow the constants fallback, which may assign SKILLS_DIR.
from .skill_api import (  # pylint: disable=wrong-import-position
    _format_skill_plan,
    _skill_list_impl,
    _skill_run_impl,
    _validate_skill_inputs,
    register_skill_tools,
)
from .skill_executor import SkillExecutor  # pylint: disable=wrong-import-position
from .skill_safety import SprintSafetyGuard  # pylint: disable=wrong-import-position
from .skill_support import (  # pylint: disable=wrong-import-position
    AttrDict,
    _check_known_issues_sync,
    _format_known_issues,
    _get_agent_stats_module,
)

logger = logging.getLogger(__name__)

# Older callers import the previous private name.
_shared__format_known_issues = _format_known_issues

__all__ = [
    "AttrDict",
    "PROJECT_ROOT",
    "SKILLS_DIR",
    "TOOL_MODULES_DIR",
    "SkillExecutor",
    "SprintSafetyGuard",
    "_check_known_issues_sync",
    "_format_known_issues",
    "_format_skill_plan",
    "_get_agent_stats_module",
    "_shared__format_known_issues",
    "_skill_list_impl",
    "_skill_run_impl",
    "_validate_skill_inputs",
    "register_skill_tools",
]
