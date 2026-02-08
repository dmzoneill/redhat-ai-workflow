"""Skill Execution Engine - Multi-step workflow execution.

Provides:
- skill_list: List available skills
- skill_run: Execute a skill
- SkillExecutor: Class that handles step-by-step execution

This module is workspace-aware: skill execution context includes workspace_uri
for proper isolation of skill state and events per workspace.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml
from fastmcp import Context, FastMCP
from mcp.types import TextContent

from server.tool_registry import ToolRegistry
from server.utils import load_config
from tool_modules.aa_workflow.src.skill_auto_healer import SkillAutoHealer
from tool_modules.aa_workflow.src.skill_compute_engine import SkillComputeEngine
from tool_modules.aa_workflow.src.skill_template_engine import SkillTemplateEngine

# Setup project path for server imports (auto-setup on import)
from tool_modules.common import PROJECT_ROOT

# Support both package import and direct loading
try:
    from .constants import SKILLS_DIR, TOOL_MODULES_DIR
except ImportError:
    TOOL_MODULES_DIR = Path(__file__).parent.parent.parent
    PROJECT_DIR = TOOL_MODULES_DIR.parent
    SKILLS_DIR = PROJECT_DIR / "skills"

logger = logging.getLogger(__name__)


class AttrDict(dict):
    """Dictionary that allows attribute-style access to keys.

    This allows skill YAML compute blocks to use `inputs.repo` instead of `inputs["repo"]`.
    """

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(f"'AttrDict' object has no attribute '{key}'")

    def __setattr__(self, key, value):
        self[key] = value

    def __delattr__(self, key):
        try:
            del self[key]
        except KeyError:
            raise AttributeError(f"'AttrDict' object has no attribute '{key}'")


# Layer 5: Usage Pattern Learning integration
try:
    from server.usage_pattern_learner import UsagePatternLearner

    LAYER5_AVAILABLE = True
except ImportError:
    LAYER5_AVAILABLE = False
    logger.warning(
        "Layer 5 (Usage Pattern Learning) not available - errors won't be learned from"
    )

# WebSocket server for real-time updates
try:
    from server.websocket_server import get_websocket_server

    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False
    logger.debug("WebSocket server not available - real-time updates disabled")


# Agent stats helper - handles import in both package and direct load contexts
def _get_agent_stats_module():
    """Get the agent_stats module, handling both package and direct load contexts."""
    try:
        # Try relative import first (works when loaded as package)
        from . import agent_stats

        return agent_stats
    except ImportError:
        # Fall back to direct file loading (works when loaded dynamically)
        # Force fresh load by removing from sys.modules cache
        import importlib.util
        import sys

        agent_stats_path = Path(__file__).parent / "agent_stats.py"

        # Remove cached version to force fresh load
        if "agent_stats" in sys.modules:
            del sys.modules["agent_stats"]

        spec = importlib.util.spec_from_file_location("agent_stats", agent_stats_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules["agent_stats"] = (
            module  # Register before exec to handle circular imports
        )
        spec.loader.exec_module(module)
        return module


# Known issues checking - loads patterns from memory
def _check_known_issues_sync(tool_name: str = "", error_text: str = "") -> list:
    """Check memory for known issues matching this tool/error."""
    matches = []
    error_lower = error_text.lower() if error_text else ""
    tool_lower = tool_name.lower() if tool_name else ""

    try:
        memory_dir = PROJECT_ROOT / "memory" / "learned"

        patterns_file = memory_dir / "patterns.yaml"
        if patterns_file.exists():
            with open(patterns_file) as f:
                patterns = yaml.safe_load(f) or {}

            # Check all pattern categories
            for category in [
                "error_patterns",
                "auth_patterns",
                "bonfire_patterns",
                "pipeline_patterns",
            ]:
                for pattern in patterns.get(category, []):
                    pattern_text = pattern.get("pattern", "").lower()
                    if pattern_text and (
                        pattern_text in error_lower or pattern_text in tool_lower
                    ):
                        matches.append(
                            {
                                "source": category,
                                "pattern": pattern.get("pattern"),
                                "meaning": pattern.get("meaning", ""),
                                "fix": pattern.get("fix", ""),
                                "commands": pattern.get("commands", []),
                            }
                        )

        # Check tool_fixes.yaml
        fixes_file = memory_dir / "tool_fixes.yaml"
        if fixes_file.exists():
            with open(fixes_file) as f:
                fixes = yaml.safe_load(f) or {}

            for fix in fixes.get("tool_fixes", []):
                if tool_name and fix.get("tool_name", "").lower() == tool_lower:
                    matches.append(
                        {
                            "source": "tool_fixes",
                            "tool_name": fix.get("tool_name"),
                            "pattern": fix.get("error_pattern", ""),
                            "fix": fix.get("fix_applied", ""),
                        }
                    )
                elif error_text:
                    fix_pattern = fix.get("error_pattern", "").lower()
                    if fix_pattern and fix_pattern in error_lower:
                        matches.append(
                            {
                                "source": "tool_fixes",
                                "tool_name": fix.get("tool_name"),
                                "pattern": fix.get("error_pattern", ""),
                                "fix": fix.get("fix_applied", ""),
                            }
                        )

    except Exception as e:
        logger.debug(f"Suppressed error in _check_known_issues_sync: {e}")

    return matches


def _format_known_issues(matches: list) -> str:
    """Format known issues for display."""
    if not matches:
        return ""

    lines = ["\n## 💡 Known Issues Found!\n"]
    for match in matches[:3]:  # Limit to 3
        lines.append(f"**Pattern:** `{match.get('pattern', '?')}`")
        if match.get("meaning"):
            lines.append(f"*{match.get('meaning')}*")
        if match.get("fix"):
            lines.append(f"**Fix:** {match.get('fix')}")
        if match.get("commands"):
            lines.append("**Try:**")
            for cmd in match.get("commands", [])[:2]:
                lines.append(f"- `{cmd}`")
        lines.append("")

    return "\n".join(lines)


# Allowed modules for compute block `import` statements.
# Skill YAML compute blocks should use the modules already provided in
# safe_globals (re, os, json, yaml, datetime, pathlib, etc.) rather than
# importing arbitrary packages.  This allowlist keeps exec() functional
# for common patterns like ``from datetime import datetime`` while
# blocking dangerous imports (e.g., subprocess, socket, shutil).
_ALLOWED_COMPUTE_MODULES = frozenset(
    {
        "re",
        "os",
        "os.path",
        "pathlib",
        "datetime",
        "json",
        "yaml",
        "math",
        "collections",
        "itertools",
        "functools",
        "textwrap",
        "string",
        "hashlib",
        "base64",
        "copy",
        "time",
        "zoneinfo",
        "urllib",
        "urllib.parse",
        "gzip",
        "subprocess",
    }
)


def _restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
    """A restricted __import__ that only allows pre-approved modules.

    This is used in skill compute block exec() to prevent arbitrary code
    from importing dangerous modules (e.g., ctypes, socket) while still
    allowing common stdlib patterns like ``from datetime import datetime``
    or ``import json``.
    """
    if level != 0:
        # Relative imports are not supported in compute blocks
        raise ImportError(f"Relative imports not allowed in compute blocks: {name}")
    if name not in _ALLOWED_COMPUTE_MODULES:
        raise ImportError(
            f"Import of '{name}' is not allowed in skill compute blocks. "
            f"Use the modules already provided in the execution context "
            f"(re, os, json, yaml, datetime, Path, etc.) or use MCP tools."
        )
    return __import__(name, globals, locals, fromlist, level)


class SprintSafetyGuard:
    """Safety guard for Sprint Bot to protect worktree from data loss.

    Before the bot starts work on an issue, this guard:
    1. Checks git_status for uncommitted changes
    2. Auto-stashes with descriptive message via git_stash tool
    3. Verifies not on main/master branch
    4. Checks for rebase/merge in progress

    Usage:
        guard = SprintSafetyGuard(server, repo_path)
        result = await guard.check_and_prepare(issue_key)
        if not result["safe"]:
            # Handle unsafe state
            print(result["reason"])
    """

    # Branches that should never be worked on directly
    PROTECTED_BRANCHES = {"main", "master", "develop", "production", "staging"}

    def __init__(
        self,
        server: FastMCP | None = None,
        repo_path: str = ".",
        auto_stash: bool = True,
    ):
        """Initialize the safety guard.

        Args:
            server: FastMCP server for calling git tools
            repo_path: Path to the repository
            auto_stash: Whether to automatically stash uncommitted changes
        """
        self.server = server
        self.repo_path = repo_path
        self.auto_stash = auto_stash
        self._stash_created = False
        self._original_branch: str | None = None

    async def check_git_status(self) -> dict[str, Any]:
        """Check git status for uncommitted changes.

        Returns:
            Dict with status info:
            - clean: bool - True if worktree is clean
            - modified: list - Modified files
            - staged: list - Staged files
            - untracked: list - Untracked files
            - branch: str - Current branch name
            - in_progress: str | None - "rebase", "merge", or None
        """
        result: dict[str, Any] = {
            "clean": True,
            "modified": [],
            "staged": [],
            "untracked": [],
            "branch": "",
            "in_progress": None,
        }

        if not self.server:
            logger.warning("No server available for git_status check")
            return result

        try:
            # Call git_status tool
            status_result = await self.server.call_tool(
                "git_status", {"repo": self.repo_path}
            )

            # Parse the result
            if status_result and len(status_result.content) > 0:
                first = status_result.content[0]
                text = first.text if hasattr(first, "text") else str(first)

                # Check for modifications
                if "modified:" in text.lower() or "changes not staged" in text.lower():
                    result["clean"] = False
                    # Extract modified files (simplified parsing)
                    for line in text.split("\n"):
                        if "modified:" in line.lower():
                            result["modified"].append(line.strip())

                if "changes to be committed" in text.lower():
                    result["clean"] = False
                    result["staged"].append("(staged changes present)")

                if "untracked files" in text.lower():
                    # Untracked files don't make it "dirty" for our purposes
                    result["untracked"].append("(untracked files present)")

                # Check for rebase/merge in progress
                if "rebase in progress" in text.lower():
                    result["in_progress"] = "rebase"
                    result["clean"] = False
                elif (
                    "merge in progress" in text.lower()
                    or "you have unmerged paths" in text.lower()
                ):
                    result["in_progress"] = "merge"
                    result["clean"] = False

                # Extract branch name
                if "on branch" in text.lower():
                    for line in text.split("\n"):
                        if "on branch" in line.lower():
                            parts = line.split()
                            if len(parts) >= 3:
                                result["branch"] = parts[-1]
                                break

        except Exception as e:
            logger.error(f"Error checking git status: {e}")

        self._original_branch = result["branch"]
        return result

    async def stash_changes(self, issue_key: str) -> dict[str, Any]:
        """Stash uncommitted changes with a descriptive message.

        Args:
            issue_key: Jira issue key for the stash message

        Returns:
            Dict with stash result:
            - success: bool
            - message: str
        """
        if not self.server:
            return {"success": False, "message": "No server available"}

        try:
            stash_message = f"Auto-stash before {issue_key} - Sprint Bot"
            result = await self.server.call_tool(
                "git_stash",
                {
                    "repo": self.repo_path,
                    "action": "push",
                    "message": stash_message,
                },
            )

            first = result.content[0] if result and result.content else None
            text = first.text if first and hasattr(first, "text") else str(result)
            self._stash_created = "saved" in text.lower() or "stash" in text.lower()

            return {
                "success": self._stash_created,
                "message": (
                    f"Stashed changes: {stash_message}"
                    if self._stash_created
                    else "No changes to stash"
                ),
            }

        except Exception as e:
            logger.error(f"Error stashing changes: {e}")
            return {"success": False, "message": str(e)}

    async def check_and_prepare(self, issue_key: str) -> dict[str, Any]:
        """Check safety and prepare worktree for work.

        This is the main entry point. It:
        1. Checks git status
        2. Validates we're not on a protected branch
        3. Auto-stashes if needed and enabled
        4. Returns safety status

        Args:
            issue_key: Jira issue key for context

        Returns:
            Dict with:
            - safe: bool - True if safe to proceed
            - reason: str - Explanation if not safe
            - stashed: bool - True if changes were stashed
            - branch: str - Current branch
            - warnings: list - Non-blocking warnings
        """
        result: dict[str, Any] = {
            "safe": True,
            "reason": "",
            "stashed": False,
            "branch": "",
            "warnings": [],
        }

        # Check git status
        status = await self.check_git_status()
        result["branch"] = status["branch"]

        # Check for rebase/merge in progress
        if status["in_progress"]:
            result["safe"] = False
            result["reason"] = (
                f"A {status['in_progress']} is in progress. Please complete or abort it first."
            )
            return result

        # Check for protected branch
        if status["branch"].lower() in self.PROTECTED_BRANCHES:
            result["safe"] = False
            result["reason"] = (
                f"Currently on protected branch '{status['branch']}'. "
                "Please create a feature branch first."
            )
            return result

        # Handle uncommitted changes
        if not status["clean"]:
            if self.auto_stash:
                stash_result = await self.stash_changes(issue_key)
                if stash_result["success"]:
                    result["stashed"] = True
                    result["warnings"].append(
                        f"Stashed uncommitted changes: {stash_result['message']}"
                    )
                else:
                    result["safe"] = False
                    result["reason"] = (
                        f"Failed to stash uncommitted changes: {stash_result['message']}"
                    )
                    return result
            else:
                result["safe"] = False
                result["reason"] = (
                    "Uncommitted changes detected. Please commit or stash them first, "
                    "or enable auto_stash."
                )
                return result

        # Add warnings for untracked files
        if status["untracked"]:
            result["warnings"].append("Untracked files present (not stashed)")

        return result

    async def restore_stash(self) -> dict[str, Any]:
        """Restore stashed changes after work is complete or aborted.

        Returns:
            Dict with restore result
        """
        if not self._stash_created:
            return {"success": True, "message": "No stash to restore"}

        if not self.server:
            return {"success": False, "message": "No server available"}

        try:
            result = await self.server.call_tool(
                "git_stash",
                {
                    "repo": self.repo_path,
                    "action": "pop",
                },
            )

            first = result.content[0] if result and result.content else None
            text = first.text if first and hasattr(first, "text") else str(result)
            success = "dropped" in text.lower() or "applied" in text.lower()

            return {
                "success": success,
                "message": "Restored stashed changes" if success else text,
            }

        except Exception as e:
            logger.error(f"Error restoring stash: {e}")
            return {"success": False, "message": str(e)}


@dataclass
class SkillExecutorConfig:
    """Configuration parameters for SkillExecutor.

    Groups the many optional parameters that control execution behavior,
    session tracking, and workspace isolation.
    """

    debug: bool = False
    enable_interactive_recovery: bool = True
    emit_events: bool = True
    workspace_uri: str = "default"
    session_id: str | None = None
    session_name: str | None = None
    source: str = "chat"  # "chat", "cron", "slack", "api"
    source_details: str | None = None  # e.g., cron job name


class SkillExecutor:
    """Full skill execution engine with debug support.

    Workspace-aware: tracks workspace_uri for proper isolation of skill
    state and events per workspace.
    """

    def __init__(
        self,
        skill: dict,
        inputs: dict,
        config: SkillExecutorConfig | None = None,
        server: FastMCP | None = None,
        create_issue_fn=None,
        ask_question_fn=None,
        ctx: Optional["Context"] = None,
        # Legacy kwargs — accepted for backward compatibility
        **kwargs,
    ):
        if config is None:
            # Build config from legacy keyword arguments for backward compatibility
            config = SkillExecutorConfig(
                debug=kwargs.get("debug", False),
                enable_interactive_recovery=kwargs.get(
                    "enable_interactive_recovery", True
                ),
                emit_events=kwargs.get("emit_events", True),
                workspace_uri=kwargs.get("workspace_uri", "default"),
                session_id=kwargs.get("session_id", None),
                session_name=kwargs.get("session_name", None),
                source=kwargs.get("source", "chat"),
                source_details=kwargs.get("source_details", None),
            )
        self.skill = skill
        self.inputs = inputs
        self.debug = config.debug
        self.server = server
        self.create_issue_fn = create_issue_fn
        self.ask_question_fn = ask_question_fn
        self.enable_interactive_recovery = config.enable_interactive_recovery
        self.emit_events = config.emit_events
        self.workspace_uri = config.workspace_uri
        self.ctx = ctx
        self.session_id = config.session_id
        self.session_name = config.session_name
        self.source = config.source
        self.source_details = config.source_details
        # Load config.json config for compute blocks
        self.config = load_config()
        # Add today's date for templating (YYYY-MM-DD format)
        from datetime import date

        self.context: dict[str, Any] = {
            "inputs": inputs,
            "config": self.config,
            "workspace_uri": self.workspace_uri,
            "today": date.today().isoformat(),
        }

        # Template engine handles Jinja2 rendering, conditions, and link formatting.
        # It shares the context dict (by reference) so updates propagate automatically.
        self.template_engine = SkillTemplateEngine(
            context=self.context,
            config=self.config,
            inputs=self.inputs,
            debug_fn=self._debug,
        )

        # Compute engine handles sandboxed Python execution in compute blocks.
        self.compute_engine = SkillComputeEngine(executor=self)

        # Auto healer handles error detection, pattern matching, and recovery.
        self.auto_healer = SkillAutoHealer(executor=self)

        self.log: list[str] = []
        self.step_results: list[dict] = []
        self.start_time: float | None = None
        self.error_recovery: Any = None  # Initialized when needed

        # Event emitter for VS Code extension (workspace-aware, multi-execution)
        self.event_emitter = None
        if self.emit_events:
            try:
                # Use absolute import to avoid relative import issues
                from tool_modules.aa_workflow.src.skill_execution_events import (
                    SkillExecutionEmitter,
                    set_emitter,
                )

                self.event_emitter = SkillExecutionEmitter(
                    skill.get("name", "unknown"),
                    skill.get("steps", []),
                    workspace_uri=self.workspace_uri,
                    session_id=self.session_id,
                    session_name=self.session_name,
                    source=self.source,
                    source_details=self.source_details,
                )
                set_emitter(self.event_emitter, self.workspace_uri)
                skill_name = skill.get("name", "unknown")
                logger.info(
                    f"Event emitter initialized for skill: {skill_name} (workspace: {self.workspace_uri}, source: {self.source})"  # noqa: E501
                )
            except Exception as e:
                logger.warning(f"Failed to initialize event emitter: {e}")

        # Layer 5: Initialize usage pattern learner
        self.usage_learner = None
        if LAYER5_AVAILABLE:
            try:
                self.usage_learner = UsagePatternLearner()
            except Exception as e:
                logger.warning(f"Failed to initialize Layer 5 learner: {e}")

        # WebSocket server for real-time updates
        self.ws_server = None
        if WEBSOCKET_AVAILABLE:
            try:
                self.ws_server = get_websocket_server()
            except Exception as e:
                logger.debug(f"WebSocket server not available: {e}")

        # Generate unique skill execution ID
        import uuid

        self.skill_id = str(uuid.uuid4())[:8]

    def _debug(self, msg: str):
        """Add debug message."""
        if self.debug:
            import time

            elapsed = (
                f"[{time.time() - self.start_time:.2f}s]" if self.start_time else ""
            )
            self.log.append(f"🔍 {elapsed} {msg}")

    def _emit_event(self, event_type: str, **kwargs):
        """Emit a file-based event to the VS Code extension.

        Delegates to the SkillExecutionEmitter which writes events to a JSON file
        that the VS Code extension watches. No-ops silently if no emitter is set.
        """
        if self.event_emitter:
            try:
                method = getattr(self.event_emitter, event_type, None)
                if method:
                    method(**kwargs)
            except Exception as e:
                logger.debug(f"Suppressed file event emission error: {e}")

    def _emit_ws_event_async(self, event_type: str, **kwargs):
        """Emit an async WebSocket event via asyncio.create_task.

        This is used for WebSocket events that are coroutines and need to be
        scheduled as background tasks.
        """
        import asyncio

        if self.ws_server and self.ws_server.is_running:
            try:
                method = getattr(self.ws_server, event_type, None)
                if method:
                    asyncio.create_task(method(**kwargs))
            except Exception as e:
                logger.debug(f"Suppressed async WS event emission error: {e}")

    def _notify(self, notification_fn_name: str, *args):
        """Emit a toast notification, suppressing any errors."""
        try:
            import importlib

            mod = importlib.import_module(
                "tool_modules.aa_workflow.src.notification_emitter"
            )
            fn = getattr(mod, notification_fn_name, None)
            if fn:
                fn(*args)
        except Exception as e:
            logger.debug(f"Suppressed notification error: {e}")

    async def _learn_from_error(self, tool_name: str, params: dict, error_msg: str):
        """Send error to Layer 5 learning system (async).

        This is called when on_error: continue swallows an error.
        Layer 5 will:
        1. Classify the error (usage vs infrastructure)
        2. Extract patterns and prevention steps
        3. Merge with similar patterns
        4. Build confidence over time
        """
        if not self.usage_learner:
            return

        try:
            # Learn from this error asynchronously
            await self.usage_learner.learn_from_observation(  # type: ignore[attr-defined]
                tool_name=tool_name,
                params=params,
                error_message=error_msg,
                context={},
                success=False,
            )
            self._debug(f"Layer 5: Learned from error in {tool_name}")
        except Exception as e:
            # Don't let learning failure break the skill
            logger.warning(f"Layer 5 learning failed: {e}")

    # -- Auto-healer delegation -----------------------------------------------
    # These methods delegate to the SkillAutoHealer instance.
    # They preserve the original underscore-prefixed signatures for backward
    # compatibility with tests and internal callers.

    def _find_matched_pattern(self, error_lower: str) -> tuple[dict | None, str | None]:
        """Find a matching pattern from memory based on error text."""
        return self.auto_healer.find_matched_pattern(error_lower)

    def _determine_fix_type(
        self, error_lower: str, matched_pattern: dict | None, matches: list
    ) -> str | None:
        """Determine which fix type to apply based on patterns."""
        return self.auto_healer.determine_fix_type(
            error_lower, matched_pattern, matches
        )

    async def _apply_network_fix(self) -> bool:
        """Apply VPN connect fix."""
        return await self.auto_healer._apply_network_fix()

    async def _apply_auth_fix(self, error_lower: str) -> bool:
        """Apply kube login fix."""
        return await self.auto_healer._apply_auth_fix(error_lower)

    async def _try_auto_fix(self, error_msg: str, matches: list) -> bool:
        """Try to auto-fix based on known patterns."""
        return await self.auto_healer.try_auto_fix(error_msg, matches)

    def _update_pattern_usage_stats(
        self,
        category: str,
        pattern_text: str,
        matched: bool = True,
        fixed: bool = False,
    ) -> None:
        """Update usage statistics for a pattern."""
        return self.auto_healer.update_pattern_usage_stats(
            category, pattern_text, matched, fixed
        )

    # -- Template engine delegation ------------------------------------------
    # These methods delegate to the SkillTemplateEngine instance.
    # They preserve the original underscore-prefixed signatures for backward
    # compatibility with tests and the SkillTestHarness.

    def _linkify_jira_keys(self, text):
        """Convert Jira keys to clickable links (Slack or Markdown format)."""
        return self.template_engine._linkify_jira_keys(text)

    def _linkify_mr_ids(self, text, project=None):
        """Convert MR IDs to clickable links (Slack or Markdown format)."""
        return self.template_engine._linkify_mr_ids(text, project)

    def _create_jinja_filters(self):
        """Create Jinja2 custom filters for template rendering."""
        return self.template_engine._create_jinja_filters()

    def _template_with_regex_fallback(self, text: str) -> str:
        """Template replacement using regex (fallback when Jinja2 unavailable)."""
        return self.template_engine._template_with_regex_fallback(text)

    def _check_error_patterns(self, error: str) -> str | None:
        """Check if error matches known patterns and return fix suggestion."""
        try:
            patterns_file = SKILLS_DIR.parent / "memory" / "learned" / "patterns.yaml"
            if not patterns_file.exists():
                return None

            with open(patterns_file) as f:
                patterns_data = yaml.safe_load(f) or {}

            error_patterns = patterns_data.get("error_patterns", [])
            error_lower = error.lower()

            for pattern in error_patterns:
                pattern_text = pattern.get("pattern", "").lower()
                if pattern_text and pattern_text in error_lower:
                    # Track pattern match
                    self._update_pattern_usage_stats(
                        "error_patterns", pattern_text, matched=True
                    )

                    fix = pattern.get("fix", "")
                    meaning = pattern.get("meaning", "")
                    commands = pattern.get("commands", [])

                    suggestion = f"\n   💡 **Known pattern: {pattern.get('pattern')}**"
                    if meaning:
                        suggestion += f"\n   *{meaning}*"
                    if fix:
                        suggestion += f"\n   **Fix:** {fix}"
                    if commands:
                        suggestion += "\n   **Try:**"
                        for cmd in commands[:3]:
                            suggestion += f"\n   - `{cmd}`"
                    return suggestion

            return None
        except Exception as e:
            self._debug(f"Pattern lookup failed: {e}")
            return None

    def _template(self, text: str) -> str:
        """Resolve {{ variable }} templates in text using Jinja2 if available."""
        return self.template_engine.template(text)

    def _template_dict(self, d: dict) -> dict:
        """Recursively template a dictionary."""
        return self.template_engine.template_dict(d)

    def _eval_condition(self, condition: str) -> bool:
        """Safely evaluate a condition expression using Jinja2 if available."""
        return self.template_engine.eval_condition(condition)

    def _handle_auto_fix_action(self, error_info: dict, step_name: str):
        """Handle auto_fix action for interactive recovery."""
        fix_code = error_info.get("fix_code")
        if not fix_code:
            self._debug("Auto-fix not available despite user selection")
            return None

        # Re-execute with fixed code
        try:
            self._debug("Retrying with fixed code...")
            fixed_result = self._exec_compute_internal(fix_code, step_name)

            # Log successful fix
            self.error_recovery.log_fix_attempt(
                error_info,
                action="auto_fix",
                success=not isinstance(fixed_result, str)
                or not fixed_result.startswith("<compute error:"),
                details=f"Auto-fixed {error_info.get('pattern_id')}",
            )

            return fixed_result
        except Exception as e:
            self._debug(f"Auto-fix failed: {e}")
            self.error_recovery.log_fix_attempt(
                error_info, action="auto_fix", success=False, details=str(e)
            )
            return None

    def _handle_edit_action(self, error_info: dict, error_msg: str, step_name: str):
        """Handle edit action for interactive recovery."""
        skill_name = self.skill.get("name", "unknown")
        skill_path = SKILLS_DIR / f"{skill_name}.yaml"

        print(
            f"\n🔧 Please edit the skill file: {skill_path}\n"
            f"   Step: {step_name}\n"
            f"   Error: {error_msg}\n"
            f"   Suggestion: {error_info.get('suggestion')}\n"
        )
        input("Press Enter after saving your changes...")

        # Log manual edit
        self.error_recovery.log_fix_attempt(
            error_info,
            action="manual_edit",
            success=True,
            details="User manually edited skill",
        )

        # Return None to signal skill should be aborted and re-run
        return None

    def _handle_skip_action(self, error_info: dict, step_name: str):
        """Handle skip action for interactive recovery."""
        print(f"\n⏭️  Skipping skill execution.\n" f"   Error in step: {step_name}\n")

        self.error_recovery.log_fix_attempt(
            error_info, action="skip", success=False, details="User chose to skip"
        )
        return None

    def _handle_abort_action(self, error_info: dict, error_msg: str, step_name: str):
        """Handle abort action for interactive recovery."""
        # Create GitHub issue if possible
        if self.create_issue_fn:
            try:
                import asyncio

                issue_result = asyncio.get_event_loop().run_until_complete(
                    self.create_issue_fn(
                        tool="skill_compute",
                        error=error_msg,
                        context=f"Skill: {self.skill.get('name')}, Step: {step_name}",
                        skill=self.skill.get("name", "unknown"),
                    )
                )
                if issue_result.get("success"):
                    print(f"\n🐛 GitHub issue created: {issue_result.get('issue_url')}")
            except Exception as e:
                self._debug(f"Could not create issue: {e}")

        self.error_recovery.log_fix_attempt(
            error_info,
            action="abort",
            success=False,
            details="User aborted with issue creation",
        )
        return None

    def _handle_continue_action(self, error_info: dict, error_msg: str):
        """Handle continue action for interactive recovery."""
        # Debug mode - let broken data propagate
        self.error_recovery.log_fix_attempt(
            error_info,
            action="continue",
            success=False,
            details="User chose to continue with error",
        )
        return f"<compute error: {error_msg}>"

    def _initialize_error_recovery(self):
        """Initialize error recovery system if not already loaded."""
        if self.error_recovery:
            return True

        try:
            from scripts.common.skill_error_recovery import SkillErrorRecovery

            # Pass memory helpers if available
            memory_helper = None
            try:
                from scripts.common import memory as memory_helpers

                memory_helper = memory_helpers
            except ImportError:
                pass

            self.error_recovery = SkillErrorRecovery(memory_helper=memory_helper)
            return True
        except ImportError as e:
            self._debug(f"Could not load error recovery: {e}")
            return False

    def _try_interactive_recovery(self, code: str, error_msg: str, step_name: str):
        """
        Attempt interactive recovery from compute error.

        Returns:
            The computed result if recovery successful, None if user chose to abort/skip
        """
        # Lazy import to avoid circular dependencies
        if not self._initialize_error_recovery():
            return None

        # Detect error pattern
        error_info = self.error_recovery.detect_error(code, error_msg, step_name)
        self._debug(f"Error detected: {error_info.get('pattern_id', 'unknown')}")

        # Show error to user and get action
        import asyncio

        try:
            # Call ask_question_fn which is already async
            action_result = asyncio.get_event_loop().run_until_complete(
                self.error_recovery.prompt_user_for_action(
                    error_info, self.ask_question_fn
                )
            )
        except Exception as e:
            self._debug(f"Interactive prompt failed: {e}")
            return None

        action = action_result.get("action")
        self._debug(f"User chose: {action}")

        # Dispatch to action handlers
        if action == "auto_fix":
            return self._handle_auto_fix_action(error_info, step_name)
        elif action == "edit":
            return self._handle_edit_action(error_info, error_msg, step_name)
        elif action == "skip":
            return self._handle_skip_action(error_info, step_name)
        elif action == "abort":
            return self._handle_abort_action(error_info, error_msg, step_name)
        elif action == "continue":
            return self._handle_continue_action(error_info, error_msg)

        return None

    # -- Compute engine delegation ---------------------------------------------
    # These methods delegate to the SkillComputeEngine instance.
    # They preserve the original underscore-prefixed signatures for backward
    # compatibility with tests, harness, and error recovery.

    def _create_nested_skill_runner(self):
        """Create a helper function for running nested skills from compute blocks."""
        return self.compute_engine.create_nested_skill_runner()

    def _exec_compute_internal(self, code: str, output_name: str):
        """Internal compute execution without error recovery."""
        return self.compute_engine.exec_compute_internal(code, output_name)

    def _exec_compute(self, code: str, output_name: str):
        """Execute a compute block (limited Python) with error recovery."""
        return self.compute_engine.exec_compute(code, output_name)

    def _get_module_for_tool(self, tool_name: str) -> str | None:
        """Map tool name to module name using the discovery system."""
        from server.tool_discovery import get_module_for_tool

        return get_module_for_tool(tool_name)

    def _format_tool_result(self, result, duration: float) -> dict:
        """Format tool execution result into standard dict.

        Detects error indicators in the result text to properly set success=False
        for tools that return error messages instead of raising exceptions.
        """
        if isinstance(result, tuple):
            result = result[0]

        # Handle FastMCP ToolResult objects
        if hasattr(result, "content") and isinstance(result.content, list):
            # ToolResult from FastMCP - extract text from content
            if result.content and hasattr(result.content[0], "text"):
                text = result.content[0].text
            else:
                text = str(result)
        elif isinstance(result, list) and result:
            text = result[0].text if hasattr(result[0], "text") else str(result[0])
        else:
            text = str(result)

        # Check for error indicators in the result text
        # Tools often return error messages with these prefixes instead of raising
        text_lower = text.lower()
        is_error = (
            text.startswith("❌")
            or text_lower.startswith("error:")
            or "❌ error" in text_lower
            or "❌ failed" in text_lower
            or "connection may have failed" in text_lower
            or "script not found" in text_lower
        )

        return {"success": not is_error, "result": text, "duration": duration}

    async def _execute_workflow_tool(
        self, tool_name: str, args: dict, start_time: float
    ) -> dict:
        """Execute a tool from the workflow module."""
        import time

        try:
            assert self.server is not None, "No server available for tool execution"
            result = await self.server.call_tool(tool_name, args)
            duration = time.time() - start_time
            duration_ms = int(duration * 1000)
            self._debug(f"  → Completed in {duration:.2f}s")

            # Record tool call stats
            try:
                agent_stats = _get_agent_stats_module()
                agent_stats.record_tool_call(tool_name, True, duration_ms)
            except Exception as stats_err:
                logger.debug(f"Failed to record tool stats: {stats_err}")

            return self._format_tool_result(result, duration)
        except Exception as e:
            # Record failed tool call
            try:
                agent_stats = _get_agent_stats_module()
                agent_stats.record_tool_call(tool_name, False, 0)
            except Exception as e2:
                logger.debug(f"Suppressed error in recording failed tool stats: {e2}")
            return {"success": False, "error": str(e)}

    async def _load_and_execute_module_tool(
        self, module: str, tool_name: str, args: dict, start_time: float
    ) -> dict:
        """Load a tool module and execute the specified tool."""
        import importlib.util
        import time

        self._debug(f"  → Loading module: {module}")
        self._debug(f"  → TOOL_MODULES_DIR: {TOOL_MODULES_DIR}")

        # Try tools_basic.py first (new structure), then tools.py (legacy)
        tools_file = TOOL_MODULES_DIR / f"aa_{module}" / "src" / "tools_basic.py"
        self._debug(f"  → Trying: {tools_file} (exists: {tools_file.exists()})")
        if not tools_file.exists():
            tools_file = TOOL_MODULES_DIR / f"aa_{module}" / "src" / "tools.py"
            self._debug(f"  → Fallback: {tools_file} (exists: {tools_file.exists()})")

        if not tools_file.exists():
            return {
                "success": False,
                "error": f"Module not found: {module} (checked {TOOL_MODULES_DIR / f'aa_{module}' / 'src'})",
            }

        try:
            temp_server = FastMCP(f"skill-{module}")
            spec = importlib.util.spec_from_file_location(f"skill_{module}", tools_file)
            if spec is None or spec.loader is None:
                return {"success": False, "error": f"Could not load: {module}"}

            loaded_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(loaded_module)

            if hasattr(loaded_module, "register_tools"):
                loaded_module.register_tools(temp_server)

            result = await temp_server.call_tool(tool_name, args)
            duration = time.time() - start_time
            duration_ms = int(duration * 1000)
            self._debug(f"  → Completed in {duration:.2f}s")

            # Record tool call stats
            try:
                agent_stats = _get_agent_stats_module()
                agent_stats.record_tool_call(tool_name, True, duration_ms)
            except Exception as stats_err:
                logger.debug(f"Failed to record tool stats: {stats_err}")

            return self._format_tool_result(result, duration)

        except Exception as e:
            # Record failed tool call
            try:
                agent_stats = _get_agent_stats_module()
                agent_stats.record_tool_call(tool_name, False, 0)
            except Exception as e2:
                logger.debug(
                    f"Suppressed error in recording failed module tool stats: {e2}"
                )
            return {
                "success": False,
                "error": str(e),
                "_temp_server": temp_server if "temp_server" in locals() else None,
            }

    async def _exec_tool(self, tool_name: str, args: dict) -> dict:
        """Execute a tool and return its result."""
        import time

        start = time.time()

        self._debug(f"Calling tool: {tool_name}")
        self._debug(f"  → Args: {json.dumps(args)[:200]}")

        module = self._get_module_for_tool(tool_name)
        if not module:
            return {"success": False, "error": f"Unknown tool: {tool_name}"}

        # Execute workflow tools directly through server
        if module == "workflow" and self.server:
            return await self._execute_workflow_tool(tool_name, args, start)

        # Execute other module tools with error recovery
        result = await self._load_and_execute_module_tool(
            module, tool_name, args, start
        )

        # If there was an error, try auto-fix and retry
        if not result.get("success"):
            # Error message can be in 'error' key or 'result' key (for tools that return error text)
            error_msg = result.get("error") or result.get("result", "Unknown error")
            temp_server = result.get("_temp_server")

            if temp_server:
                self._debug(f"  → Error: {error_msg}")

                # Check for known issues and attempt auto-fix
                matches = _check_known_issues_sync(
                    tool_name=tool_name, error_text=error_msg
                )
                known_text = _format_known_issues(matches)

                if matches:
                    self._debug(
                        f"  → Found {len(matches)} known issue(s), attempting auto-fix"
                    )
                    fix_applied = await self._try_auto_fix(error_msg, matches)

                    if fix_applied:
                        self._debug("  → Auto-fix applied, retrying tool")
                        # Emit auto-heal event
                        fix_type = self._determine_fix_type(
                            error_msg.lower(), None, matches
                        )
                        step_idx = (
                            self.event_emitter.current_step_index
                            if self.event_emitter
                            else 0
                        )
                        self._emit_event(
                            "auto_heal",
                            step_index=step_idx,
                            details=f"Applied {fix_type or 'auto'} fix for: {error_msg[:50]}",
                        )
                        try:
                            # Emit retry event
                            self._emit_event(
                                "retry",
                                step_index=step_idx,
                                retry_count=1,
                            )
                            retry_result = await temp_server.call_tool(tool_name, args)
                            duration = time.time() - start
                            duration_ms = int(duration * 1000)
                            self._debug(f"  → Retry completed in {duration:.2f}s")

                            # Record successful retry
                            try:
                                agent_stats = _get_agent_stats_module()
                                agent_stats.record_tool_call(
                                    tool_name, True, duration_ms
                                )
                            except Exception as e:
                                logger.debug(
                                    f"Suppressed error in recording retry tool stats: {e}"
                                )

                            return self._format_tool_result(retry_result, duration)
                        except Exception as retry_e:
                            error_msg = f"{error_msg}\n\n(Retry after auto-fix also failed: {retry_e})"

                if known_text:
                    error_msg = f"{error_msg}\n{known_text}"

                result["error"] = error_msg

        # Remove internal _temp_server key if present
        result.pop("_temp_server", None)
        return result

    def _detect_auto_heal_type(self, error_msg: str) -> tuple[str | None, str]:
        """Detect if error is auto-healable and what type."""
        return self.auto_healer.detect_auto_heal_type(error_msg)

    async def _attempt_auto_heal(
        self,
        heal_type: str,
        cluster: str,
        tool: str,
        step: dict,
        output_lines: list[str],
    ) -> dict | None:
        """Attempt to auto-heal and retry the tool."""
        return await self.auto_healer.attempt_auto_heal(
            heal_type, cluster, tool, step, output_lines
        )

    async def _log_auto_heal_to_memory(
        self,
        tool: str,
        heal_type: str,
        error_snippet: str,
        success: bool,
    ) -> None:
        """Log auto-heal attempt to memory for learning."""
        return await self.auto_healer.log_auto_heal_to_memory(
            tool, heal_type, error_snippet, success
        )

    async def _handle_tool_error(
        self,
        tool: str,
        step: dict,
        step_name: str,
        error_msg: str,
        output_lines: list[str],
    ) -> bool:
        """Handle tool execution error.

        Returns:
            True if processing should continue, False if skill should stop
        """
        output_lines.append(f"   ❌ Error: {error_msg}")

        # Check for known error patterns
        pattern_hint = self._check_error_patterns(error_msg)
        if pattern_hint:
            output_lines.append(pattern_hint)

        on_error = step.get("on_error", "fail")

        # Handle auto_heal mode - try to fix and retry before giving up
        if on_error == "auto_heal":
            heal_type, cluster = self._detect_auto_heal_type(error_msg)

            if heal_type:
                output_lines.append(
                    f"   🩹 Detected {heal_type} error, attempting auto-heal..."
                )

                # Emit auto-heal triggered event (WebSocket)
                step_idx = (
                    self.event_emitter.current_step_index if self.event_emitter else 0
                )
                fix_action = (
                    f"kube_login({cluster})" if heal_type == "auth" else "vpn_connect()"
                )
                self._emit_ws_event_async(
                    "auto_heal_triggered",
                    skill_id=self.skill_id,
                    step_index=step_idx,
                    error_type=heal_type,
                    fix_action=fix_action,
                    error_snippet=error_msg[:200],
                )

                # Emit toast notification for auto-heal triggered
                self._notify(
                    "notify_auto_heal_triggered", step_name, heal_type, fix_action
                )

                retry_result = await self._attempt_auto_heal(
                    heal_type, cluster, tool, step, output_lines
                )

                if retry_result and retry_result.get("success"):
                    # Auto-heal worked! Store result and continue
                    output_lines.append("   ✅ Auto-heal successful!")
                    output_name = step.get("output", step_name)
                    self.context[output_name] = retry_result["result"]
                    self._parse_and_store_tool_result(
                        retry_result["result"], output_name
                    )

                    # Log success to memory
                    await self._log_auto_heal_to_memory(
                        tool, heal_type, error_msg[:100], success=True
                    )

                    # Emit auto-heal completed event (WebSocket)
                    step_idx = (
                        self.event_emitter.current_step_index
                        if self.event_emitter
                        else 0
                    )
                    self._emit_ws_event_async(
                        "auto_heal_completed",
                        skill_id=self.skill_id,
                        step_index=step_idx,
                        fix_action=heal_type,
                        success=True,
                    )

                    # Emit toast notification for auto-heal success
                    self._notify("notify_auto_heal_succeeded", step_name, heal_type)

                    self.step_results.append(
                        {
                            "step": step_name,
                            "tool": tool,
                            "success": True,
                            "auto_healed": True,
                            "heal_type": heal_type,
                        }
                    )
                    return True
                else:
                    # Auto-heal failed, log and continue
                    output_lines.append("   ⚠️ Auto-heal failed, continuing anyway...")
                    await self._log_auto_heal_to_memory(
                        tool, heal_type, error_msg[:100], success=False
                    )

                    # Emit auto-heal completed (failed) event (WebSocket)
                    step_idx = (
                        self.event_emitter.current_step_index
                        if self.event_emitter
                        else 0
                    )
                    self._emit_ws_event_async(
                        "auto_heal_completed",
                        skill_id=self.skill_id,
                        step_index=step_idx,
                        fix_action=heal_type,
                        success=False,
                    )

                    # Emit toast notification for auto-heal failure
                    self._notify("notify_auto_heal_failed", step_name, error_msg[:100])
            else:
                output_lines.append("   ℹ️ Error not auto-healable, continuing...")

            # Fall through to continue behavior
            output_lines.append("   *Continuing despite error (on_error: auto_heal)*\n")

            # Layer 5: Learn from this error
            tool_params = {}
            if "args" in step:
                args_data = step["args"]
                if isinstance(args_data, dict):
                    tool_params = {
                        k: self._template(str(v)) for k, v in args_data.items()
                    }

            await self._learn_from_error(
                tool_name=tool, params=tool_params, error_msg=error_msg
            )

            self.step_results.append(
                {
                    "step": step_name,
                    "tool": tool,
                    "success": False,
                    "error": error_msg,
                    "auto_heal_attempted": heal_type is not None,
                }
            )
            return True

        if self.create_issue_fn:
            skill_name = self.skill.get("name", "unknown")
            context = f"Skill: {skill_name}, Step: {step_name}"

            try:
                issue_result = await self.create_issue_fn(
                    tool=tool,
                    error=error_msg,
                    context=context,
                    skill=skill_name,
                )

                if issue_result["success"]:
                    output_lines.append(
                        f"\n   🐛 **Issue created:** {issue_result['issue_url']}"
                    )
                elif issue_result["issue_url"]:
                    output_lines.append("\n   💡 **Report this error:**")
                    output_lines.append(
                        f"   📝 [Create GitHub Issue]({issue_result['issue_url']})"
                    )
            except Exception as e:
                self._debug(f"Failed to create issue: {e}")

        if on_error == "continue":
            output_lines.append("   *Continuing despite error (on_error: continue)*\n")

            # Log to Python logger for journalctl visibility
            skill_name = self.skill.get("name", "unknown")
            logger.warning(
                f"Skill '{skill_name}' step '{step_name}' failed with on_error=continue: "
                f"tool={tool}, error={error_msg[:200]}"
            )

            # Layer 5: Learn from this error
            tool_params = {}
            if "args" in step:
                args_data = step["args"]
                if isinstance(args_data, dict):
                    tool_params = {
                        k: self._template(str(v)) for k, v in args_data.items()
                    }

            await self._learn_from_error(
                tool_name=tool, params=tool_params, error_msg=error_msg
            )

            # Emit toast notification for continue-mode failures (helps visibility)
            self._notify("notify_step_failed", skill_name, step_name, error_msg[:150])

            self.step_results.append(
                {
                    "step": step_name,
                    "tool": tool,
                    "success": False,
                    "error": error_msg,
                }
            )
            return True
        else:
            return False

    def _parse_and_store_tool_result(self, result_text: str, output_name: str):
        """Parse key:value output from tool result and store in context."""
        try:
            if ":" in result_text:
                parsed = {}
                for line in result_text.split("\n"):
                    if ":" in line and not line.strip().startswith("#"):
                        key, _, val = line.partition(":")
                        parsed[key.strip().lower().replace(" ", "_")] = val.strip()
                if parsed:
                    self.context[f"{output_name}_parsed"] = parsed
        except Exception as e:
            logger.debug(f"Suppressed error in result text parsing: {e}")

    def _detect_soft_failure(self, result_text: str) -> tuple[bool, str | None]:
        """Detect if a successful tool result actually contains an error (soft failure).

        Many tools return success=True but include error messages in the result text.
        This method detects those cases so auto-heal can be triggered.

        Returns:
            (is_soft_failure, error_message) - True if result contains error patterns
        """
        if not result_text:
            return False, None

        result_lower = result_text.lower()

        # Patterns that indicate a soft failure (tool returned success but result is an error)
        soft_failure_patterns = [
            # Explicit failure markers
            ("❌ failed", "Tool returned failure marker"),
            ("❌ error", "Tool returned error marker"),
            # Network/DNS errors
            ("no such host", "DNS resolution failed - VPN may be disconnected"),
            ("dial tcp", "TCP connection failed - network issue"),
            ("connection refused", "Connection refused - service may be down"),
            ("no route to host", "No route to host - VPN may be disconnected"),
            ("network unreachable", "Network unreachable - VPN may be disconnected"),
            # Auth errors
            ("unauthorized", "Authentication failed - token may be expired"),
            ("forbidden", "Access forbidden - permissions issue"),
            ("401", "HTTP 401 - authentication required"),
            ("403", "HTTP 403 - access forbidden"),
            ("token expired", "Token expired - need to re-authenticate"),
            # Cluster errors
            (
                "the server has asked for the client to provide credentials",
                "Kubernetes auth required",
            ),
            ("error from server", "Kubernetes API error"),
            # Bonfire/ephemeral errors
            ("traceback (most recent call last)", "Python exception in tool"),
        ]

        for pattern, error_desc in soft_failure_patterns:
            if pattern in result_lower:
                # Extract a snippet around the error for context
                idx = result_lower.find(pattern)
                start = max(0, idx - 50)
                end = min(len(result_text), idx + len(pattern) + 100)
                snippet = result_text[start:end].strip()
                return True, f"{error_desc}: ...{snippet}..."

        return False, None

    def _validate_tool_args(
        self, tool: str, raw_args: dict, args: dict, step_name: str
    ) -> str | None:
        """Validate tool arguments after template rendering.

        Returns:
            Error message if validation fails, None if valid.
        """
        # Check for empty required arguments that came from templates
        # Skip validation for args that use 'default' or 'or' in the template (these are optional)
        for key, raw_value in raw_args.items():
            if isinstance(raw_value, str) and "{{" in raw_value:
                # Skip if template has a default/fallback (e.g., "{{ x | default('') }}" or "{{ x or '' }}")
                if "default(" in raw_value or " or " in raw_value:
                    continue
                rendered_value = args.get(key, "")
                if rendered_value == "" or rendered_value is None:
                    # Extract variable name from template for better error message
                    import re

                    var_match = re.search(r"\{\{\s*([^}]+)\s*\}\}", raw_value)
                    var_name = var_match.group(1).strip() if var_match else raw_value
                    return (
                        f"Required argument '{key}' is empty. "
                        f"Template '{raw_value}' rendered to empty string. "
                        f"Check if '{var_name}' is defined in a previous step."
                    )
        return None

    async def _process_tool_step(
        self, step: dict, step_num: int, step_name: str, output_lines: list[str]
    ) -> bool:
        """Process a 'tool' step and append results to output_lines.

        Returns:
            True if processing should continue, False if skill should stop
        """
        tool = step["tool"]
        raw_args = step.get("args", {})
        args = self._template_dict(raw_args)

        # Validate that template rendering produced valid arguments
        validation_error = self._validate_tool_args(tool, raw_args, args, step_name)
        if validation_error:
            self._debug(f"Argument validation failed for {tool}: {validation_error}")
            output_lines.append(f"🔧 **Step {step_num}: {step_name}**")
            output_lines.append(f"   *Tool: `{tool}`*")
            output_lines.append(f"   ❌ {validation_error}")

            # Check on_error handling
            on_error = step.get("on_error", "fail")
            if on_error == "continue":
                output_lines.append("   ⏭️ Continuing (on_error: continue)")
                return True

            # Record step failure
            self.step_results.append(
                {
                    "step": step_name,
                    "tool": tool,
                    "success": False,
                    "error": validation_error,
                }
            )
            return False

        output_lines.append(f"🔧 **Step {step_num}: {step_name}**")
        output_lines.append(f"   *Tool: `{tool}`*")

        result = await self._exec_tool(tool, args)

        if result["success"]:
            output_name = step.get("output", step_name)
            result_text = result["result"]

            # Check for soft failures - tool returned success but result contains error
            is_soft_failure, soft_error = self._detect_soft_failure(result_text)

            if is_soft_failure and step.get("on_error") == "auto_heal":
                # Treat as error and trigger auto-heal
                output_lines.append(
                    f"   ⚠️ Soft failure detected: {(soft_error or '')[:100]}"
                )
                self._debug(f"Soft failure in {tool}: {soft_error}")

                # Store result anyway (some steps may need it even if failed)
                self.context[output_name] = result_text
                self._parse_and_store_tool_result(result_text, output_name)

                # Trigger auto-heal flow
                should_continue = await self._handle_tool_error(
                    tool,
                    step,
                    step_name,
                    soft_error or "Soft failure detected",
                    output_lines,
                )
                if not should_continue:
                    output_lines.append(f"\n⛔ **Skill failed at step {step_num}**")
                return should_continue

            # Normal success path
            self.context[output_name] = result_text
            self._parse_and_store_tool_result(result_text, output_name)

            duration = result.get("duration", 0)
            output_lines.append(f"   ✅ Success ({duration:.2f}s)")

            result_preview = result_text[:300]
            if len(result_text) > 300:
                result_preview += "..."
            output_lines.append(f"   ```\n   {result_preview}\n   ```\n")

            self.step_results.append(
                {"step": step_name, "tool": tool, "success": True, "duration": duration}
            )
            return True

        # Handle error - error message can be in 'error' key or 'result' key
        error_msg = result.get("error") or result.get("result", "Unknown error")
        should_continue = await self._handle_tool_error(
            tool, step, step_name, error_msg, output_lines
        )
        if not should_continue:
            output_lines.append(f"\n⛔ **Skill failed at step {step_num}**")
        return should_continue

    def _format_skill_outputs(self, output_lines: list[str]):
        """Format and append skill outputs section."""
        if not self.skill.get("outputs"):
            return

        output_lines.append("\n### 📤 Outputs\n")
        for out in self.skill["outputs"]:
            out_name = out.get("name", "output")
            if "value" in out:
                val = out["value"]
                output_value: Any
                if isinstance(val, str):
                    output_value = self._template(val)
                elif isinstance(val, (dict, list)):
                    output_value = (
                        self._template_dict(val)
                        if isinstance(val, dict)
                        else [
                            self._template(i) if isinstance(i, str) else i for i in val
                        ]
                    )
                else:
                    output_value = val

                self.context[out_name] = output_value
                output_lines.append(f"**{out_name}:**\n{output_value}\n")
            elif "compute" in out:
                result = self._exec_compute(out["compute"], out_name)
                output_lines.append(f"**{out_name}:** {result}\n")

    def _process_then_block(self, step: dict, output_lines: list[str]) -> str | None:
        """Process a 'then' block with early return.

        Returns:
            Final output string if early return, None to continue execution
        """
        import time

        self._debug("Processing 'then' block")
        for then_item in step["then"]:
            if "return" in then_item:
                ret = then_item["return"]
                templated = (
                    self._template_dict(ret)
                    if isinstance(ret, dict)
                    else self._template(str(ret))
                )
                self._debug(f"Early return: {templated}")

                total_time = time.time() - (self.start_time or 0.0)
                output_lines.append(f"✅ **Early Exit**\n{templated}\n")
                output_lines.append(f"\n---\n⏱️ *Completed in {total_time:.2f}s*")

                if self.debug and self.log:
                    output_lines.append("\n\n### 🔍 Debug Log\n```")
                    output_lines.extend(self.log)
                    output_lines.append("```")

                return "\n".join(output_lines)
        return None

    async def execute(self) -> str:  # noqa: C901
        """Execute all steps and return the result."""
        import time

        self.start_time = time.time()

        skill_name = self.skill.get("name", "unknown")
        total_steps = len(self.skill.get("steps", []))
        self._debug(f"Starting skill: {skill_name}")
        self._debug(f"Inputs: {json.dumps(self.inputs)}")

        # Emit skill start event (file-based)
        self._emit_event("skill_start")

        # Emit skill start event (WebSocket)
        self._emit_ws_event_async(
            "skill_started",
            skill_id=self.skill_id,
            skill_name=skill_name,
            total_steps=total_steps,
            inputs=self.inputs,
            source=self.source,
        )

        for inp in self.skill.get("inputs", []):
            name = inp["name"]
            if name not in self.inputs and "default" in inp:
                # Template the default value to resolve variables like {{ today }}
                default_val = inp["default"]
                if isinstance(default_val, str) and "{{" in default_val:
                    default_val = self._template(default_val)
                self.inputs[name] = default_val
                self.context["inputs"] = self.inputs
                self._debug(f"Applied default: {name} = {default_val}")

        defaults = self.skill.get("defaults", {})
        self.context["defaults"] = defaults

        output_lines = [f"## 🚀 Executing Skill: {skill_name}\n"]
        output_lines.append(f"*{self.skill.get('description', '')}*\n")

        if self.debug:
            output_lines.append("### 📋 Inputs")
            for k, v in self.inputs.items():
                output_lines.append(f"- `{k}`: {v}")
            output_lines.append("")

        output_lines.append("### 📝 Execution Log\n")

        step_num = 0
        for step in self.skill.get("steps", []):
            step_index = step_num  # 0-based index for events
            step_num += 1
            step_name = step.get("name", f"step_{step_num}")
            step_start_time = time.time()

            if "condition" in step:
                if not self._eval_condition(step["condition"]):
                    self._debug(f"Skipping step '{step_name}' - condition false")
                    output_lines.append(
                        f"⏭️ **Step {step_num}: {step_name}** - *skipped (condition false)*\n"
                    )
                    # Emit step skipped event
                    self._emit_event(
                        "step_skipped",
                        step_index=step_index,
                        reason="condition false",
                    )
                    continue

            # Emit step start event (file-based)
            self._emit_event("step_start", step_index=step_index)

            # Emit step start event (WebSocket)
            description = step.get("description", "")
            self._emit_ws_event_async(
                "step_started",
                skill_id=self.skill_id,
                step_index=step_index,
                step_name=step_name,
                description=description[:200] if description else "",
            )

            if "then" in step:
                early_return = self._process_then_block(step, output_lines)
                if early_return is not None:
                    # Emit skill complete (early return)
                    total_time = time.time() - (self.start_time or 0.0)
                    self._emit_event(
                        "skill_complete",
                        success=True,
                        total_duration_ms=int(total_time * 1000),
                    )
                    return early_return
                continue

            step_success = True
            step_error = None

            if "tool" in step:
                # Check for memory operations
                tool_name = step.get("tool", "")
                if self.event_emitter:
                    self._emit_memory_events_for_tool(
                        step_index, tool_name, step.get("args", {})
                    )

                should_continue = await self._process_tool_step(
                    step, step_num, step_name, output_lines
                )

                # Check step result
                if self.step_results:
                    last_result = self.step_results[-1]
                    step_success = last_result.get("success", True)
                    if not step_success:
                        step_error = last_result.get("error", "Unknown error")

                if not should_continue:
                    # Emit step failed event
                    duration_ms = int((time.time() - step_start_time) * 1000)
                    self._emit_event(
                        "step_failed",
                        step_index=step_index,
                        duration_ms=duration_ms,
                        error=step_error or "Step failed",
                    )
                    break

            elif "compute" in step:
                output_name = step.get("output", step_name)
                output_lines.append(f"🧮 **Step {step_num}: {step_name}** (compute)")

                try:
                    result = self._exec_compute(step["compute"], output_name)

                    # Check if compute returned an error string
                    if isinstance(result, str) and result.startswith("<compute error:"):
                        step_success = False
                        step_error = result
                        output_lines.append(f"   ❌ {result}\n")
                        self._debug(f"Compute step '{step_name}' failed: {result}")

                        # Store error result in context so dependent steps can check
                        self.context[output_name] = None
                        self.context[f"{output_name}_error"] = result

                        # Record step failure
                        self.step_results.append(
                            {
                                "step": step_name,
                                "compute": True,
                                "success": False,
                                "error": result,
                            }
                        )
                    else:
                        self.context[output_name] = result
                        output_lines.append(
                            f"   → `{output_name}` = {str(result)[:100]}\n"
                        )
                except Exception as e:
                    step_success = False
                    step_error = str(e)
                    output_lines.append(f"   ❌ Error: {e}\n")

            elif "description" in step:
                output_lines.append(f"📝 **Step {step_num}: {step_name}** (manual)")
                output_lines.append(f"   {self._template(step['description'])}\n")

            # Emit step complete/failed events (file-based + WebSocket)
            duration_ms = int((time.time() - step_start_time) * 1000)
            if step_success:
                self._emit_event(
                    "step_complete", step_index=step_index, duration_ms=duration_ms
                )
                self._emit_ws_event_async(
                    "step_completed",
                    skill_id=self.skill_id,
                    step_index=step_index,
                    step_name=step_name,
                    duration_ms=duration_ms,
                )
            else:
                self._emit_event(
                    "step_failed",
                    step_index=step_index,
                    duration_ms=duration_ms,
                    error=step_error or "Unknown error",
                )
                self._emit_ws_event_async(
                    "step_failed",
                    skill_id=self.skill_id,
                    step_index=step_index,
                    step_name=step_name,
                    error=step_error or "Unknown error",
                )

        self._format_skill_outputs(output_lines)

        total_time = time.time() - (self.start_time or 0.0)
        success_count = sum(1 for r in self.step_results if r.get("success"))
        fail_count = sum(1 for r in self.step_results if not r.get("success"))

        output_lines.append(
            f"\n---\n⏱️ *Completed in {total_time:.2f}s* | "
            f"✅ {success_count} succeeded | ❌ {fail_count} failed"
        )

        # Emit skill complete event (file-based)
        overall_success = fail_count == 0
        self._emit_event(
            "skill_complete",
            success=overall_success,
            total_duration_ms=int(total_time * 1000),
        )
        # Clear the global emitter
        if self.event_emitter:
            try:
                from .skill_execution_events import set_emitter

                set_emitter(None)
            except Exception as e:
                logger.debug(f"Suppressed error in clearing event emitter: {e}")

        # Emit skill complete event (WebSocket)
        if overall_success:
            self._emit_ws_event_async(
                "skill_completed",
                skill_id=self.skill_id,
                total_duration_ms=int(total_time * 1000),
            )
        else:
            # Get last error from step_results
            last_error = "Skill failed"
            for r in reversed(self.step_results):
                if not r.get("success") and r.get("error"):
                    last_error = r["error"]
                    break
            self._emit_ws_event_async(
                "skill_failed",
                skill_id=self.skill_id,
                error=last_error,
                total_duration_ms=int(total_time * 1000),
            )

        # Track skill execution in agent stats
        try:
            agent_stats = _get_agent_stats_module()
            overall_success = fail_count == 0
            agent_stats.record_skill_execution(
                skill_name=skill_name,
                success=overall_success,
                duration_ms=int(total_time * 1000),
                steps_completed=success_count,
                total_steps=len(self.skill.get("steps", [])),
            )
        except Exception as e:
            self._debug(f"Failed to record skill stats: {e}")

        # Extract and save learnings from successful skill execution
        if fail_count == 0:
            await self._extract_and_save_learnings(output_lines)

        if self.debug and self.log:
            output_lines.append("\n\n### 🔍 Debug Log\n```")
            output_lines.extend(self.log)
            output_lines.append("```")

        return "\n".join(output_lines)

    def _emit_memory_events_for_tool(
        self, step_index: int, tool_name: str, args: dict
    ) -> None:
        """Emit memory read/write events based on tool being called."""
        if not self.event_emitter:
            return

        # Memory read tools
        memory_read_tools = [
            "memory_read",
            "memory_query",
            "check_known_issues",
            "memory_stats",
        ]
        if any(t in tool_name for t in memory_read_tools):
            key = args.get("key", tool_name)
            self.event_emitter.memory_read(step_index, key)

        # Memory write tools
        memory_write_tools = [
            "memory_write",
            "memory_update",
            "memory_append",
            "memory_session_log",
            "learn_tool_fix",
        ]
        if any(t in tool_name for t in memory_write_tools):
            key = args.get("key", tool_name)
            self.event_emitter.memory_write(step_index, key)

        # Semantic search tools
        semantic_search_tools = [
            "code_search",
            "knowledge_query",
            "semantic_search",
            "vector_search",
        ]
        if any(t in tool_name for t in semantic_search_tools):
            query = args.get("query", args.get("section", tool_name))
            self.event_emitter.semantic_search(step_index, query)

    async def _extract_and_save_learnings(self, output_lines: list[str]) -> None:
        """Extract learnings from successful skill execution and save to knowledge.

        This is called after a skill completes successfully. It analyzes the
        execution context and results to extract potential learnings.
        """
        skill_name = self.skill.get("name", "unknown")

        # Skip skills that don't produce learnable outcomes
        non_learning_skills = [
            "memory_view",
            "memory_cleanup",
            "coffee",
            "beer",
            "standup_summary",
            "weekly_summary",
        ]
        if skill_name in non_learning_skills:
            return

        # Try to detect project and persona
        try:
            from .knowledge_tools import (
                _detect_project_from_path,
                _get_current_persona,
                _load_knowledge,
                _save_knowledge,
            )

            project = _detect_project_from_path()
            if not project:
                self._debug("No project detected, skipping learning extraction")
                return

            persona = _get_current_persona() or "developer"

            # Load existing knowledge
            knowledge = _load_knowledge(persona, project)
            if not knowledge:
                self._debug(f"No knowledge file for {project}/{persona}, skipping")
                return

            # Extract learning based on skill type
            learning = None
            task = self.inputs.get("issue_key", skill_name)

            # Skills that produce learnable outcomes
            if skill_name == "start_work":
                issue_key = self.inputs.get("issue_key", "")
                if issue_key:
                    learning = f"Started work on {issue_key}"

            elif skill_name == "create_mr":
                issue_key = self.inputs.get("issue_key", "")
                if issue_key:
                    learning = f"Created MR for {issue_key}"

            elif skill_name in ["review_pr", "review_all_prs"]:
                # Extract review insights
                mr_id = self.inputs.get("mr_id", "")
                if mr_id:
                    learning = f"Reviewed MR !{mr_id}"

            elif skill_name == "test_mr_ephemeral":
                mr_id = self.inputs.get("mr_id", "")
                if mr_id:
                    learning = f"Tested MR !{mr_id} in ephemeral environment"

            elif skill_name == "investigate_alert":
                alert = self.inputs.get("alert_name", "")
                if alert:
                    learning = f"Investigated alert: {alert}"

            elif skill_name == "close_issue":
                issue_key = self.inputs.get("issue_key", "")
                if issue_key:
                    learning = f"Closed issue {issue_key}"

            # Save learning if we extracted one
            if learning:
                # Ensure learned_from_tasks exists
                if "learned_from_tasks" not in knowledge:
                    knowledge["learned_from_tasks"] = []

                # Add the learning
                knowledge["learned_from_tasks"].append(
                    {
                        "date": datetime.now().strftime("%Y-%m-%d"),
                        "task": task,
                        "learning": learning,
                        "skill": skill_name,
                    }
                )

                # Limit to last 50 learnings
                knowledge["learned_from_tasks"] = knowledge["learned_from_tasks"][-50:]

                # Slightly increase confidence
                current_confidence = knowledge.get("metadata", {}).get(
                    "confidence", 0.5
                )
                knowledge["metadata"]["confidence"] = min(
                    current_confidence + 0.01, 1.0
                )

                # Save
                _save_knowledge(persona, project, knowledge)
                self._debug(f"Saved learning: {learning}")

                # Add note to output
                output_lines.append(f"\n📚 *Learning recorded: {learning}*")

        except Exception as e:
            self._debug(f"Failed to extract/save learnings: {e}")


def _skill_list_impl() -> list[TextContent]:
    """Implementation of skill_list tool."""
    skills = []
    if SKILLS_DIR.exists():
        for f in SKILLS_DIR.glob("*.yaml"):
            if f.name == "README.md":
                continue
            try:
                with open(f) as fp:
                    data = yaml.safe_load(fp)
                skills.append(
                    {
                        "name": data.get("name", f.stem),
                        "description": data.get("description", "No description"),
                        "inputs": [i["name"] for i in data.get("inputs", [])],
                    }
                )
            except Exception as e:
                skills.append(
                    {"name": f.stem, "description": f"Error loading: {e}", "inputs": []}
                )

    if not skills:
        return [
            TextContent(
                type="text",
                text="No skills found. Create .yaml files in skills/ directory.",
            )
        ]

    lines = ["## Available Skills\n"]
    for s in skills:
        inputs = ", ".join(s["inputs"]) if s["inputs"] else "none"
        lines.append(f"### {s['name']}")
        lines.append(f"{s['description']}")
        lines.append(f"**Inputs:** {inputs}\n")

    return [TextContent(type="text", text="\n".join(lines))]


def _validate_skill_inputs(skill: dict, input_data: dict) -> list[str]:
    """Validate required skill inputs and return list of missing inputs."""
    missing = []
    for inp in skill.get("inputs", []):
        if inp.get("required", False) and inp["name"] not in input_data:
            if "default" not in inp:
                missing.append(inp["name"])
    return missing


def _format_skill_plan(
    skill: dict, skill_name: str, input_data: dict
) -> list[TextContent]:
    """Format skill execution plan (preview mode)."""
    lines = [f"## 📋 Skill Plan: {skill.get('name', skill_name)}\n"]
    lines.append(f"*{skill.get('description', '')}*\n")
    lines.append("### Inputs")
    for k, v in input_data.items():
        lines.append(f"- `{k}`: {v}")
    lines.append("\n### Steps to Execute\n")

    step_num = 0
    for step in skill.get("steps", []):
        step_num += 1
        name = step.get("name", f"step_{step_num}")

        if "tool" in step:
            lines.append(f"{step_num}. **{name}** → `{step['tool']}`")
            if step.get("condition"):
                lines.append(f"   *Condition: {step['condition']}*")
        elif "compute" in step:
            lines.append(f"{step_num}. **{name}** → compute")
        elif "description" in step:
            lines.append(f"{step_num}. **{name}** → manual step")

    lines.append("\n*Run with `execute=True` to execute this plan*")
    return [TextContent(type="text", text="\n".join(lines))]


async def _skill_run_impl(
    skill_name: str,
    inputs: str,
    execute: bool,
    debug: bool,
    server: "FastMCP",
    create_issue_fn=None,
    ask_question_fn=None,
    ctx: Optional["Context"] = None,
    source: str = "chat",
    source_details: str | None = None,
) -> list[TextContent]:
    """Implementation of skill_run tool.

    Args:
        skill_name: Name of the skill to run.
        inputs: JSON string of input parameters.
        execute: Whether to execute (True) or just preview (False).
        debug: Whether to show debug output.
        server: FastMCP server instance.
        create_issue_fn: Function to create Jira issues.
        ask_question_fn: Function to ask user questions.
        ctx: MCP Context for workspace/session info.
        source: Source of execution ("chat", "cron", "slack", "api").
        source_details: Additional source info (e.g., cron job name).
    """
    skill_file = SKILLS_DIR / f"{skill_name}.yaml"
    if not skill_file.exists():
        available = (
            [f.stem for f in SKILLS_DIR.glob("*.yaml")] if SKILLS_DIR.exists() else []
        )
        return [
            TextContent(
                type="text",
                text=f"❌ Skill not found: {skill_name}\n\n"
                f"Available: {', '.join(available) or 'none'}",
            )
        ]

    try:
        with open(skill_file) as f:
            skill = yaml.safe_load(f)

        try:
            input_data = json.loads(inputs) if inputs else {}
        except json.JSONDecodeError:
            return [TextContent(type="text", text=f"❌ Invalid inputs JSON: {inputs}")]

        # Validate inputs
        missing = _validate_skill_inputs(skill, input_data)
        if missing:
            lines = [f"❌ Missing required inputs: {', '.join(missing)}\n"]
            lines.append("### Required Inputs\n")
            for inp in skill.get("inputs", []):
                req = "**required**" if inp.get("required") else "optional"
                default = f" (default: {inp['default']})" if "default" in inp else ""
                lines.append(
                    f"- `{inp['name']}` ({inp.get('type', 'string')}) - {req}{default}"
                )
                if inp.get("description"):
                    lines.append(f"  {inp['description']}")
            return [TextContent(type="text", text="\n".join(lines))]

        # Preview mode: just show the plan
        if not execute:
            return _format_skill_plan(skill, skill_name, input_data)

        # Get session context from workspace if available
        workspace_uri = "default"
        session_id = None
        session_name = None

        if ctx:
            try:
                from server.workspace_state import WorkspaceRegistry

                workspace = await WorkspaceRegistry.get_for_ctx(ctx)
                workspace_uri = workspace.workspace_uri
                session = workspace.get_active_session()
                if session:
                    session_id = session.session_id
                    session_name = session.name
            except Exception as e:
                logger.debug(f"Could not get session context: {e}")

        # Execute mode: run the skill
        exec_config = SkillExecutorConfig(
            debug=debug,
            enable_interactive_recovery=True,
            emit_events=True,  # Enable VS Code extension events
            workspace_uri=workspace_uri,
            session_id=session_id,
            session_name=session_name,
            source=source,
            source_details=source_details,
        )
        executor = SkillExecutor(
            skill,
            input_data,
            config=exec_config,
            server=server,
            create_issue_fn=create_issue_fn,
            ask_question_fn=ask_question_fn,
            ctx=ctx,
        )
        result = await executor.execute()

        return [TextContent(type="text", text=result)]

    except Exception as e:
        import traceback

        if debug:
            return [
                TextContent(
                    type="text",
                    text=f"❌ Error: {e}\n\n```\n{traceback.format_exc()}\n```",
                )
            ]
        return [TextContent(type="text", text=f"❌ Error loading skill: {e}")]


def register_skill_tools(
    server: "FastMCP", create_issue_fn=None, ask_question_fn=None
) -> int:
    """Register skill tools with the MCP server."""
    registry = ToolRegistry(server)

    @registry.tool()
    async def skill_list() -> list[TextContent]:
        """
        List all available skills (reusable workflows).

        Skills are multi-step workflows that combine MCP tools with logic.
        Use skill_run() to execute a skill.

        Returns:
            List of available skills with descriptions.
        """
        return _skill_list_impl()

    @registry.tool()
    async def skill_run(
        ctx: "Context",
        skill_name: str,
        inputs: str = "{}",
        args: str = "",
        execute: bool = True,
        debug: bool = False,
    ) -> list[TextContent]:
        """
        Execute a skill (multi-step workflow).

        Skills chain multiple MCP tools together with logic and conditions.

        Args:
            skill_name: Name of the skill (e.g., "start_work", "investigate_alert")
            inputs: JSON object with input parameters (preferred)
            args: Alias for inputs (for convenience)
            execute: If True (default), run the tools. If False, just show the plan.
            debug: If True, show detailed execution trace with timing.

        Returns:
            Execution results or plan preview.
        """
        # Support both 'inputs' and 'args' parameter names
        actual_inputs = args if args else inputs
        return await _skill_run_impl(
            skill_name,
            actual_inputs,
            execute,
            debug,
            server,
            create_issue_fn,
            ask_question_fn,
            ctx=ctx,
            source="chat",
        )

    return registry.count
