"""Skill Execution Engine - Multi-step workflow execution.

Provides:
- skill_list: List available skills
- skill_run: Execute a skill
- SkillExecutor: Class that handles step-by-step execution

This module is workspace-aware: skill execution context includes workspace_uri
for proper isolation of skill state and events per workspace.
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml
from fastmcp import Context, FastMCP
from mcp.types import TextContent

from server.tool_registry import ToolRegistry
from server.utils import load_config

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
        patterns_file = SKILLS_DIR.parent / "memory" / "learned" / "patterns.yaml"
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
        fixes_file = SKILLS_DIR.parent / "memory" / "learned" / "tool_fixes.yaml"
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

    except Exception:
        pass

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


class SkillExecutor:
    """Full skill execution engine with debug support.

    Workspace-aware: tracks workspace_uri for proper isolation of skill
    state and events per workspace.
    """

    def __init__(
        self,
        skill: dict,
        inputs: dict,
        debug: bool = False,
        server: FastMCP | None = None,
        create_issue_fn=None,
        ask_question_fn=None,
        enable_interactive_recovery: bool = True,
        emit_events: bool = True,
        workspace_uri: str = "default",
        ctx: Optional["Context"] = None,
        # Session context for multi-execution tracking
        session_id: str | None = None,
        session_name: str | None = None,
        source: str = "chat",  # "chat", "cron", "slack", "api"
        source_details: str | None = None,  # e.g., cron job name
    ):
        self.skill = skill
        self.inputs = inputs
        self.debug = debug
        self.server = server
        self.create_issue_fn = create_issue_fn
        self.ask_question_fn = ask_question_fn
        self.enable_interactive_recovery = enable_interactive_recovery
        self.emit_events = emit_events
        self.workspace_uri = workspace_uri
        self.ctx = ctx
        self.session_id = session_id
        self.session_name = session_name
        self.source = source
        self.source_details = source_details
        # Load config.json config for compute blocks
        self.config = load_config()
        # Add today's date for templating (YYYY-MM-DD format)
        from datetime import date

        self.context: dict[str, Any] = {
            "inputs": inputs,
            "config": self.config,
            "workspace_uri": workspace_uri,
            "today": date.today().isoformat(),
        }
        self.log: list[str] = []
        self.step_results: list[dict] = []
        self.start_time: float | None = None
        self.error_recovery: Any = None  # Initialized when needed

        # Event emitter for VS Code extension (workspace-aware, multi-execution)
        self.event_emitter = None
        if emit_events:
            try:
                # Use absolute import to avoid relative import issues
                from tool_modules.aa_workflow.src.skill_execution_events import (
                    SkillExecutionEmitter,
                    set_emitter,
                )

                self.event_emitter = SkillExecutionEmitter(
                    skill.get("name", "unknown"),
                    skill.get("steps", []),
                    workspace_uri=workspace_uri,
                    session_id=session_id,
                    session_name=session_name,
                    source=source,
                    source_details=source_details,
                )
                set_emitter(self.event_emitter, workspace_uri)
                skill_name = skill.get("name", "unknown")
                logger.info(
                    f"Event emitter initialized for skill: {skill_name} (workspace: {workspace_uri}, source: {source})"
                )
                # Debug: write to a file to confirm emitter is created
                from pathlib import Path

                debug_file = (
                    Path.home() / ".config" / "aa-workflow" / "emitter_debug.log"
                )
                debug_file.parent.mkdir(parents=True, exist_ok=True)
                with open(debug_file, "a") as f:
                    from datetime import datetime

                    skill_name = skill.get("name", "unknown")
                    f.write(
                        f"{datetime.now().isoformat()} - Emitter created for {skill_name} (source: {source})\n"
                    )
            except Exception as e:
                logger.warning(f"Failed to initialize event emitter: {e}")
                # Also write to debug file on failure
                try:
                    from datetime import datetime
                    from pathlib import Path

                    debug_file = (
                        Path.home() / ".config" / "aa-workflow" / "emitter_debug.log"
                    )
                    debug_file.parent.mkdir(parents=True, exist_ok=True)
                    with open(debug_file, "a") as f:
                        f.write(
                            f"{datetime.now().isoformat()} - FAILED to create emitter: {e}\n"
                        )
                except Exception:
                    pass

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

    def _find_matched_pattern(self, error_lower: str) -> tuple[dict | None, str | None]:
        """Find a matching pattern from memory based on error text.

        Returns:
            (matched_pattern, pattern_category) tuple or (None, None)
        """
        try:
            patterns_file = SKILLS_DIR.parent / "memory" / "learned" / "patterns.yaml"
            if not patterns_file.exists():
                return None, None

            with open(patterns_file) as f:
                patterns_data = yaml.safe_load(f) or {}

            # Check each category for matches
            for cat in [
                "auth_patterns",
                "error_patterns",
                "bonfire_patterns",
                "pipeline_patterns",
            ]:
                for pattern in patterns_data.get(cat, []):
                    pattern_text = pattern.get("pattern", "").lower()
                    if pattern_text and pattern_text in error_lower:
                        # Track that pattern was matched
                        self._update_pattern_usage_stats(
                            cat, pattern_text, matched=True
                        )
                        return pattern, cat
        except Exception as e:
            self._debug(f"Pattern lookup failed: {e}")

        return None, None

    def _determine_fix_type(
        self, error_lower: str, matched_pattern: dict | None, matches: list
    ) -> str | None:
        """Determine which fix type to apply based on patterns.

        Returns:
            "network", "auth", or None
        """
        # Priority 1: Use matched pattern from learned memory
        if matched_pattern:
            commands = matched_pattern.get("commands", [])
            for cmd in commands:
                if "vpn" in cmd.lower() or "connect" in cmd.lower():
                    return "network"
                if (
                    "login" in cmd.lower()
                    or "auth" in cmd.lower()
                    or "kube" in cmd.lower()
                ):
                    return "auth"

        # Priority 2: Hardcoded patterns
        auth_patterns = ["unauthorized", "401", "403", "forbidden", "token expired"]
        network_patterns = ["no route to host", "connection refused", "timeout"]

        if any(p in error_lower for p in auth_patterns):
            return "auth"
        elif any(p in error_lower for p in network_patterns):
            return "network"

        # Priority 3: Check matches from known issues
        for match in matches:
            fix = match.get("fix", "").lower()
            if "vpn" in fix or "connect" in fix:
                return "network"
            if "login" in fix or "auth" in fix or "kube" in fix:
                return "auth"

        return None

    async def _apply_network_fix(self) -> bool:
        """Apply VPN connect fix using the configured VPN script or nmcli fallback."""
        import asyncio
        import os

        try:
            # Try to use the configured VPN script first (same as vpn_connect tool)
            from server.utils import load_config

            config = load_config()
            paths = config.get("paths", {})
            vpn_script = paths.get("vpn_connect_script")

            if not vpn_script:
                vpn_script = os.path.expanduser(
                    "~/src/redhatter/src/redhatter_vpn/vpn-connect"
                )
            else:
                vpn_script = os.path.expanduser(vpn_script)

            if os.path.exists(vpn_script):
                self._debug(f"  → Using VPN script: {vpn_script}")
                proc = await asyncio.create_subprocess_exec(
                    vpn_script,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(proc.wait(), timeout=120)
                self._debug(f"  → VPN connect result: {proc.returncode}")
                await asyncio.sleep(2)  # Wait for VPN to establish
                return proc.returncode == 0
            else:
                # Fallback to nmcli with common VPN connection names
                self._debug("  → VPN script not found, trying nmcli fallback")
                vpn_names = [
                    "Red Hat Global VPN",
                    "Red Hat VPN",
                    "redhat-vpn",
                    "RH-VPN",
                ]
                for vpn_name in vpn_names:
                    proc = await asyncio.create_subprocess_shell(
                        f"nmcli connection up '{vpn_name}' 2>/dev/null",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=30)
                        if proc.returncode == 0:
                            self._debug(
                                f"  → VPN connect result: success with {vpn_name}"
                            )
                            await asyncio.sleep(2)
                            return True
                    except asyncio.TimeoutError:
                        continue

                self._debug("  → All VPN connection attempts failed")
                return False

        except Exception as e:
            self._debug(f"  → Auto-fix failed: {e}")
            return False

    async def _apply_auth_fix(self, error_lower: str) -> bool:
        """Apply kube login fix."""
        import asyncio

        try:
            # Guess cluster from error
            cluster = "stage"  # default
            if "ephemeral" in error_lower or "bonfire" in error_lower:
                cluster = "ephemeral"
            elif "konflux" in error_lower or "tekton" in error_lower:
                cluster = "konflux"
            elif "prod" in error_lower:
                cluster = "prod"

            # Call oc login using asyncio subprocess
            kubeconfig = f"~/.kube/config.{cluster[0]}"
            cluster_urls = {
                "stage": "api.c-rh-c-eph.8p0c.p1.openshiftapps.com:6443",
                "ephemeral": "api.c-rh-c-eph.8p0c.p1.openshiftapps.com:6443",
                "prod": "api.crcp01ue1.o9m8.p1.openshiftapps.com:6443",
                "konflux": "api.stone-prd-rh01.pg1f.p1.openshiftapps.com:6443",
            }
            url = cluster_urls.get(cluster, cluster_urls["stage"])

            proc = await asyncio.create_subprocess_exec(
                "oc",
                "login",
                f"--kubeconfig={kubeconfig}",
                f"https://{url}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.wait(), timeout=30)
            self._debug(f"  → Kube login result: {proc.returncode}")
            await asyncio.sleep(1)
            return proc.returncode == 0
        except Exception as e:
            self._debug(f"  → Auto-fix failed: {e}")
            return False

    async def _try_auto_fix(self, error_msg: str, matches: list) -> bool:
        """Try to auto-fix based on known patterns.

        Returns True if a fix was applied, False otherwise.
        """
        error_lower = error_msg.lower()

        # Find matching pattern from memory
        matched_pattern, pattern_category = self._find_matched_pattern(error_lower)

        # Determine which fix to apply
        fix_type = self._determine_fix_type(error_lower, matched_pattern, matches)

        if not fix_type:
            return False

        self._debug(f"  → Detected {fix_type} issue, applying auto-fix")

        # Apply the appropriate fix
        if fix_type == "network":
            fix_success = await self._apply_network_fix()
        elif fix_type == "auth":
            fix_success = await self._apply_auth_fix(error_lower)
        else:
            fix_success = False

        # Track fix success for matched pattern
        if fix_success and matched_pattern and pattern_category:
            pattern_text = matched_pattern.get("pattern", "")
            self._update_pattern_usage_stats(
                pattern_category, pattern_text, matched=False, fixed=True
            )

        return fix_success

    def _update_pattern_usage_stats(
        self,
        category: str,
        pattern_text: str,
        matched: bool = True,
        fixed: bool = False,
    ) -> None:
        """Update usage statistics for a pattern.

        Args:
            category: Pattern category (e.g., "auth_patterns", "error_patterns")
            pattern_text: The pattern text to find
            matched: Whether the pattern was matched (default: True)
            fixed: Whether the fix succeeded (default: False)
        """
        try:
            import fcntl

            patterns_file = SKILLS_DIR.parent / "memory" / "learned" / "patterns.yaml"
            if not patterns_file.exists():
                return

            # Atomic read-modify-write with file locking
            with open(patterns_file, "r+") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)

                try:
                    f.seek(0)
                    patterns_data = yaml.safe_load(f.read()) or {}

                    if category not in patterns_data:
                        return

                    # Find and update the pattern
                    for pattern in patterns_data[category]:
                        if pattern.get("pattern", "").lower() == pattern_text.lower():
                            # Initialize usage_stats if not present
                            if "usage_stats" not in pattern:
                                pattern["usage_stats"] = {
                                    "times_matched": 0,
                                    "times_fixed": 0,
                                    "success_rate": 0.0,
                                }

                            stats = pattern["usage_stats"]

                            # Update counters
                            if matched:
                                stats["times_matched"] = (
                                    stats.get("times_matched", 0) + 1
                                )
                                stats["last_matched"] = datetime.now().isoformat()

                            if fixed:
                                stats["times_fixed"] = stats.get("times_fixed", 0) + 1

                            # Recalculate success rate
                            if stats["times_matched"] > 0:
                                stats["success_rate"] = round(
                                    stats["times_fixed"] / stats["times_matched"], 2
                                )

                            # Write back
                            f.seek(0)
                            f.truncate()
                            yaml.dump(
                                patterns_data,
                                f,
                                default_flow_style=False,
                                sort_keys=False,
                            )
                            break

                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        except Exception as e:
            self._debug(f"Failed to update pattern stats: {e}")

    def _linkify_jira_keys(self, text):
        """Convert Jira keys to clickable links (Slack or Markdown format)."""
        import re

        if not text:
            return text

        is_slack = self.inputs.get("slack_format", False)
        jira_url = self.config.get("jira", {}).get("url", "https://issues.redhat.com")

        pattern = re.compile(r"\b([A-Z]+-\d+)(-[\w-]+)?\b")

        def replace(match):
            key = match.group(1)
            suffix = match.group(2) or ""
            if is_slack:
                return f"<{jira_url}/browse/{key}|{key}{suffix}>"
            return f"[{key}{suffix}]({jira_url}/browse/{key})"

        return pattern.sub(replace, str(text))

    def _linkify_mr_ids(self, text):
        """Convert MR IDs to clickable links (Slack or Markdown format)."""
        import re

        if not text:
            return text

        is_slack = self.inputs.get("slack_format", False)
        gitlab_url = self.config.get("gitlab", {}).get(
            "url", "https://gitlab.cee.redhat.com"
        )
        project = "automation-analytics/automation-analytics-backend"

        pattern = re.compile(r"!(\d+)")

        def replace(match):
            mr_id = match.group(1)
            url = f"{gitlab_url}/{project}/-/merge_requests/{mr_id}"
            if is_slack:
                return f"<{url}|!{mr_id}>"
            return f"[!{mr_id}]({url})"

        return pattern.sub(replace, str(text))

    def _create_jinja_filters(self):
        """Create Jinja2 custom filters for template rendering."""
        return {
            "jira_link": self._linkify_jira_keys,
            "mr_link": self._linkify_mr_ids,
            "length": len,
        }

    def _template_with_regex_fallback(self, text: str) -> str:
        """Template replacement using regex (fallback when Jinja2 unavailable)."""
        import re

        def replace_var(match):
            var_path = match.group(1).strip()
            try:
                value = self.context
                parts = var_path.split(".")

                for part in parts:
                    array_match = re.match(r"^(\w+)\[(\d+)\]$", part)
                    if array_match:
                        var_name, index = array_match.groups()
                        index = int(index)
                        if isinstance(value, dict):
                            value = value.get(var_name)
                        elif hasattr(value, var_name):
                            value = getattr(value, var_name)
                        else:
                            return match.group(0)
                        if isinstance(value, (list, tuple)) and index < len(value):
                            value = value[index]
                        else:
                            return match.group(0)
                    elif isinstance(value, dict):
                        value = value.get(part, match.group(0))
                        if value == match.group(0):
                            return value
                    elif hasattr(value, part):
                        value = getattr(value, part)
                    else:
                        return match.group(0)
                return str(value) if value is not None else ""
            except Exception:
                return match.group(0)

        return re.sub(r"\{\{\s*([^}]+)\s*\}\}", replace_var, str(text))

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
        """Resolve {{ variable }} templates in text using Jinja2 if available.

        Uses ChainableUndefined to allow attribute access on undefined variables
        (returns empty string) while still catching completely missing variables
        in debug mode.
        """
        if not isinstance(text, str) or "{{" not in text:
            return text

        try:
            from jinja2 import ChainableUndefined, Environment

            # autoescape=False to preserve Slack link format <url|text>
            # Skills don't generate HTML, they generate plain text and Slack markdown
            # ChainableUndefined allows {{ foo.bar.baz }} to return "" if foo is undefined
            # but still allows chained attribute access without errors
            env = Environment(autoescape=False, undefined=ChainableUndefined)
            env.filters.update(self._create_jinja_filters())

            template = env.from_string(text)
            rendered = template.render(**self.context)

            # Warn if template rendered to empty when it had variables
            # This helps catch cases where context variables are missing
            if rendered == "" and "{{" in text:
                self._debug(f"WARNING: Template rendered to empty string: {text[:100]}")

            return rendered
        except ImportError:
            return self._template_with_regex_fallback(text)
        except Exception as e:
            self._debug(f"Template error: {e}")
            return text

    def _template_dict(self, d: dict) -> dict:
        """Recursively template a dictionary."""
        result: dict = {}
        for k, v in d.items():
            if isinstance(v, str):
                result[k] = self._template(v)
            elif isinstance(v, dict):
                result[k] = self._template_dict(v)
            elif isinstance(v, list):
                result[k] = [self._template(i) if isinstance(i, str) else i for i in v]
            else:
                result[k] = v
        return result

    def _eval_condition(self, condition: str) -> bool:
        """Safely evaluate a condition expression using Jinja2 if available."""
        self._debug(f"Evaluating condition: {condition}")

        try:
            from jinja2 import Environment

            # autoescape=False - conditions don't need HTML escaping
            env = Environment(autoescape=False)
            # Wrap condition in {{ }} if not already there for Jinja evaluation
            if "{{" not in condition:
                expr = "{{ " + condition + " }}"
            else:
                expr = condition

            result_str = env.from_string(expr).render(**self.context).strip()
            self._debug(f"  → Rendered condition: '{condition}' = '{result_str}'")
            # If it's a boolean-like string, convert it
            if result_str.lower() in ("true", "1", "yes"):
                return True
            if result_str.lower() in ("false", "0", "no", "", "none"):
                return False
            # Otherwise check if it's non-empty
            return bool(result_str)
        except ImportError:
            # Fallback to eval
            templated = self._template(condition)
            self._debug(f"  → Templated (fallback): {templated}")

            safe_context = {
                "len": len,
                "any": any,
                "all": all,
                "isinstance": isinstance,
                "type": type,
                "hasattr": hasattr,
                "dir": dir,
                "str": str,
                "int": int,
                "float": float,
                "list": list,
                "dict": dict,
                "bool": bool,
                "True": True,
                "False": False,
                "None": None,
                **self.context,
            }

            try:
                result = eval(templated, {"__builtins__": {}}, safe_context)
                self._debug(f"  → Result: {result}")
                return bool(result)
            except Exception as e:
                self._debug(f"  → Error: {e}, defaulting to False")
                return False
        except Exception as e:
            self._debug(f"  → Jinja eval error: {e}, defaulting to False")
            return False

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

    def _create_nested_skill_runner(self):
        """Create a helper function that compute blocks can use to run nested skills.

        Returns a function that can be called like:
            run_skill("jira_hygiene", {"issue_key": "AAP-12345"})
        """
        import asyncio

        def run_skill_sync(skill_name: str, inputs: Optional[dict] = None) -> dict:
            """Run a nested skill synchronously from within a compute block.

            Args:
                skill_name: Name of the skill to run (e.g., "jira_hygiene")
                inputs: Input parameters for the skill

            Returns:
                dict with 'success', 'result', and optionally 'error' keys
            """
            inputs = inputs or {}

            try:
                # Load the skill definition
                skill_file = SKILLS_DIR / f"{skill_name}.yaml"
                if not skill_file.exists():
                    return {"success": False, "error": f"Skill not found: {skill_name}"}

                with open(skill_file) as f:
                    nested_skill = yaml.safe_load(f)

                # Create a new executor for the nested skill
                nested_executor = SkillExecutor(
                    skill=nested_skill,
                    inputs=inputs,
                    debug=self.debug,
                    server=self.server,
                    create_issue_fn=self.create_issue_fn,
                    ask_question_fn=self.ask_question_fn,
                    enable_interactive_recovery=False,  # Don't prompt in nested skills
                    emit_events=False,  # Don't emit events for nested skills
                    workspace_uri=self.workspace_uri,
                    ctx=self.ctx,
                )

                # Run the nested skill - handle async properly
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

                outputs: Any = None
                if loop and loop.is_running():
                    # We're already in an async context, schedule on the existing loop
                    # Use run_coroutine_threadsafe to safely run from sync context
                    future = asyncio.run_coroutine_threadsafe(
                        nested_executor.execute(), loop
                    )
                    outputs, _ = future.result(timeout=300)  # type: ignore[misc]
                else:
                    # No running loop, can use asyncio.run directly
                    outputs, _ = asyncio.run(nested_executor.execute())  # type: ignore[misc]

                return {"success": True, "result": outputs}

            except Exception as e:
                return {"success": False, "error": str(e)}

        return run_skill_sync

    def _exec_compute_internal(self, code: str, output_name: str):
        """Internal compute execution without error recovery (used by recovery itself)."""
        # This is the actual compute logic extracted from _exec_compute
        # to avoid infinite recursion during auto-fix retries
        local_vars = dict(self.context)
        # Wrap inputs in AttrDict to allow attribute-style access (inputs.repo vs inputs["repo"])
        local_vars["inputs"] = AttrDict(self.inputs)
        local_vars["config"] = self.config

        import os
        import re
        from datetime import datetime, timedelta
        from pathlib import Path

        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            ZoneInfo = None  # type: ignore[misc,assignment]

        # Use module-level PROJECT_ROOT
        if str(PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT))

        try:
            from scripts.common import config_loader, jira_utils, lint_utils
            from scripts.common import memory as memory_helpers
            from scripts.common import parsers, repo_utils, slack_utils
            from scripts.common.config_loader import get_timezone
            from scripts.common.config_loader import load_config as load_skill_config
            from scripts.skill_hooks import emit_event_sync
        except ImportError:
            parsers = None  # type: ignore[assignment]
            jira_utils = None  # type: ignore[assignment]
            load_skill_config = None  # type: ignore[assignment]
            get_timezone = None  # type: ignore[assignment]
            emit_event_sync = None  # type: ignore[assignment]
            memory_helpers = None  # type: ignore[assignment]
            config_loader = None  # type: ignore[assignment]
            lint_utils = None  # type: ignore[assignment]
            repo_utils = None  # type: ignore[assignment]
            slack_utils = None  # type: ignore[assignment]

        try:
            from google.oauth2.credentials import Credentials as GoogleCredentials
            from googleapiclient.discovery import build as google_build
        except ImportError:
            GoogleCredentials = None  # type: ignore[misc,assignment]
            google_build = None

        # Create the nested skill runner for compute blocks
        run_skill = self._create_nested_skill_runner()

        safe_globals = {
            "__builtins__": {
                "len": len,
                "str": str,
                "int": int,
                "float": float,
                "list": list,
                "dict": dict,
                "bool": bool,
                "tuple": tuple,
                "set": set,
                "range": range,
                "enumerate": enumerate,
                "zip": zip,
                "map": map,
                "filter": filter,
                "sorted": sorted,
                "min": min,
                "max": max,
                "sum": sum,
                "any": any,
                "all": all,
                "isinstance": isinstance,
                "type": type,
                "hasattr": hasattr,
                "getattr": getattr,
                "repr": repr,
                "print": print,
                "dir": dir,
                "vars": vars,
                "Exception": Exception,
                "ValueError": ValueError,
                "TypeError": TypeError,
                "KeyError": KeyError,
                "AttributeError": AttributeError,
                "IndexError": IndexError,
                "ImportError": ImportError,
                "True": True,
                "False": False,
                "None": None,
                "open": open,
                "__import__": __import__,
            },
            "re": re,
            "os": os,
            "Path": Path,
            "datetime": datetime,
            "timedelta": timedelta,
            "ZoneInfo": ZoneInfo,
            "parsers": parsers,
            "jira_utils": jira_utils,
            "memory": memory_helpers,
            "emit_event": emit_event_sync,
            "load_config": load_skill_config,
            "get_timezone": get_timezone,
            "GoogleCredentials": GoogleCredentials,
            "google_build": google_build,
            # New shared utilities
            "config_loader": config_loader,
            "lint_utils": lint_utils,
            "repo_utils": repo_utils,
            "slack_utils": slack_utils,
            # Nested skill runner - allows compute blocks to run other skills
            "run_skill": run_skill,
        }

        templated_code = self._template(code)
        namespace = {**safe_globals, **local_vars}
        exec(templated_code, namespace)

        if output_name in namespace:
            result = namespace[output_name]
        elif "result" in namespace:
            result = namespace["result"]
        elif "return" in templated_code:
            for line in reversed(templated_code.split("\n")):
                if line.strip().startswith("return "):
                    expr = line.strip()[7:]
                    result = eval(expr, namespace)
                    break
            else:
                result = None
        else:
            result = None

        # Update context with any new variables defined in the code
        for key in namespace:
            if key not in safe_globals and not key.startswith("_"):
                local_vars[key] = namespace[key]

        return result

    def _exec_compute(self, code: str, output_name: str):
        """Execute a compute block (limited Python) with error recovery."""
        self._debug(f"Executing compute block for '{output_name}'")

        try:
            result = self._exec_compute_internal(code, output_name)
            self._debug(f"  → Result: {str(result)[:100]}")
            return result

        except Exception as e:
            self._debug(f"  → Compute error: {e}")

            # Try interactive recovery if enabled
            if self.enable_interactive_recovery and self.ask_question_fn:
                recovery_result = self._try_interactive_recovery(
                    code, str(e), output_name
                )
                if recovery_result is not None:
                    return recovery_result

            return f"<compute error: {e}>"

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
            except Exception:
                pass
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
            except Exception:
                pass
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
                        if self.event_emitter:
                            fix_type = self._determine_fix_type(
                                error_msg.lower(), None, matches
                            )
                            self.event_emitter.auto_heal(
                                self.event_emitter.current_step_index,
                                f"Applied {fix_type or 'auto'} fix for: {error_msg[:50]}",
                            )
                        try:
                            # Emit retry event
                            if self.event_emitter:
                                self.event_emitter.retry(
                                    self.event_emitter.current_step_index,
                                    1,  # First retry
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
                            except Exception:
                                pass

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
        """Detect if error is auto-healable and what type.

        Returns:
            (heal_type, cluster_hint) where heal_type is 'auth', 'network', or None
        """
        error_lower = error_msg.lower()

        # Auth patterns that can be fixed with kube_login
        auth_patterns = [
            "unauthorized",
            "401",
            "forbidden",
            "403",
            "token expired",
            "authentication required",
            "not authorized",
            "permission denied",
            "the server has asked for the client to provide credentials",
        ]

        # Network patterns that can be fixed with vpn_connect
        network_patterns = [
            "no route to host",
            "no such host",  # DNS resolution failure
            "connection refused",
            "network unreachable",
            "timeout",
            "dial tcp",
            "connection reset",
            "eof",
            "cannot connect",
            "name or service not known",  # Another DNS failure pattern
        ]

        # Determine cluster from error context
        cluster = "stage"  # default
        if "ephemeral" in error_lower or "bonfire" in error_lower:
            cluster = "ephemeral"
        elif "konflux" in error_lower:
            cluster = "konflux"
        elif "prod" in error_lower:
            cluster = "prod"

        if any(p in error_lower for p in auth_patterns):
            return "auth", cluster
        if any(p in error_lower for p in network_patterns):
            return "network", cluster

        return None, cluster

    async def _attempt_auto_heal(
        self,
        heal_type: str,
        cluster: str,
        tool: str,
        step: dict,
        output_lines: list[str],
    ) -> dict | None:
        """Attempt to auto-heal and retry the tool.

        Returns:
            Retry result dict if successful, None if heal failed
        """
        try:
            if heal_type == "auth":
                output_lines.append(
                    f"   🔧 Auto-healing: running kube_login({cluster})..."
                )
                self._debug(f"Auto-heal: kube_login({cluster})")

                # Emit remediation step event
                if self.event_emitter:
                    self.event_emitter.remediation_step(
                        self.event_emitter.current_step_index,
                        "kube_login",
                        f"Auth error on {tool}",
                    )

                # Call kube_login tool
                heal_result = await self._exec_tool("kube_login", {"cluster": cluster})
                if not heal_result.get("success"):
                    # Get error from either 'error' key or 'result' key (for tools that return error text)
                    error_msg = heal_result.get("error") or heal_result.get(
                        "result", "unknown"
                    )
                    # Truncate long error messages
                    if len(error_msg) > 200:
                        error_msg = error_msg[:200] + "..."
                    output_lines.append(f"   ⚠️ kube_login failed: {error_msg}")
                    return None
                output_lines.append("   ✅ kube_login successful")

            elif heal_type == "network":
                output_lines.append("   🔧 Auto-healing: running vpn_connect()...")
                self._debug("Auto-heal: vpn_connect()")

                # Emit remediation step event
                if self.event_emitter:
                    self.event_emitter.remediation_step(
                        self.event_emitter.current_step_index,
                        "vpn_connect",
                        f"Network error on {tool}",
                    )

                # Call vpn_connect tool
                heal_result = await self._exec_tool("vpn_connect", {})
                if not heal_result.get("success"):
                    # Get error from either 'error' key or 'result' key (for tools that return error text)
                    error_msg = heal_result.get("error") or heal_result.get(
                        "result", "unknown"
                    )
                    # Truncate long error messages
                    if len(error_msg) > 200:
                        error_msg = error_msg[:200] + "..."
                    output_lines.append(f"   ⚠️ vpn_connect failed: {error_msg}")
                    return None
                output_lines.append("   ✅ vpn_connect successful")

                # Wait for VPN connection to stabilize before retrying
                # Network routes need time to propagate after VPN connects
                output_lines.append("   ⏳ Waiting 3s for VPN to stabilize...")
                await asyncio.sleep(3)

            else:
                return None

            # Retry the original tool
            output_lines.append(f"   🔄 Retrying {tool}...")
            raw_args = step.get("args", {})
            args = self._template_dict(raw_args)
            retry_result = await self._exec_tool(tool, args)

            return retry_result

        except Exception as e:
            self._debug(f"Auto-heal failed: {e}")
            output_lines.append(f"   ⚠️ Auto-heal exception: {e}")
            return None

    async def _log_auto_heal_to_memory(
        self,
        tool: str,
        heal_type: str,
        error_snippet: str,
        success: bool,
    ) -> None:
        """Log auto-heal attempt to memory for learning."""
        try:
            from datetime import datetime

            import yaml

            # Find memory directory
            memory_dir = SKILLS_DIR.parent / "memory" / "learned"
            memory_dir.mkdir(parents=True, exist_ok=True)

            failures_file = memory_dir / "tool_failures.yaml"

            # Load or create
            if failures_file.exists():
                with open(failures_file) as f:
                    data = yaml.safe_load(f) or {}
            else:
                data = {
                    "failures": [],
                    "stats": {
                        "total_failures": 0,
                        "auto_fixed": 0,
                        "manual_required": 0,
                    },
                }

            if "failures" not in data:
                data["failures"] = []
            if "stats" not in data:
                data["stats"] = {
                    "total_failures": 0,
                    "auto_fixed": 0,
                    "manual_required": 0,
                }

            # Add entry
            entry = {
                "tool": tool,
                "error_type": heal_type,
                "error_snippet": error_snippet[:100],
                "fix_applied": "kube_login" if heal_type == "auth" else "vpn_connect",
                "success": success,
                "source": "skill_engine",
                "timestamp": datetime.now().isoformat(),
            }
            data["failures"].append(entry)

            # Update stats
            data["stats"]["total_failures"] = data["stats"].get("total_failures", 0) + 1
            if success:
                data["stats"]["auto_fixed"] = data["stats"].get("auto_fixed", 0) + 1
            else:
                data["stats"]["manual_required"] = (
                    data["stats"].get("manual_required", 0) + 1
                )

            # Keep only last 100 entries
            if len(data["failures"]) > 100:
                data["failures"] = data["failures"][-100:]

            # Write back
            with open(failures_file, "w") as f:
                yaml.dump(data, f, default_flow_style=False)

            self._debug(f"Logged auto-heal for {tool} to memory (success={success})")

        except Exception as e:
            self._debug(f"Failed to log auto-heal to memory: {e}")

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
                if self.ws_server and self.ws_server.is_running:
                    import asyncio

                    # Get current step index from event_emitter or calculate it
                    step_idx = (
                        self.event_emitter.current_step_index
                        if self.event_emitter
                        else 0
                    )
                    asyncio.create_task(
                        self.ws_server.auto_heal_triggered(
                            skill_id=self.skill_id,
                            step_index=step_idx,
                            error_type=heal_type,
                            fix_action=(
                                f"kube_login({cluster})"
                                if heal_type == "auth"
                                else "vpn_connect()"
                            ),
                            error_snippet=error_msg[:200],
                        )
                    )

                # Emit toast notification for auto-heal triggered
                try:
                    from tool_modules.aa_workflow.src.notification_emitter import (
                        notify_auto_heal_triggered,
                    )

                    fix_action = (
                        f"kube_login({cluster})"
                        if heal_type == "auth"
                        else "vpn_connect()"
                    )
                    notify_auto_heal_triggered(step_name, heal_type, fix_action)
                except Exception:
                    pass

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
                    if self.ws_server and self.ws_server.is_running:
                        import asyncio

                        step_idx = (
                            self.event_emitter.current_step_index
                            if self.event_emitter
                            else 0
                        )
                        asyncio.create_task(
                            self.ws_server.auto_heal_completed(
                                skill_id=self.skill_id,
                                step_index=step_idx,
                                fix_action=heal_type,
                                success=True,
                            )
                        )

                    # Emit toast notification for auto-heal success
                    try:
                        from tool_modules.aa_workflow.src.notification_emitter import (
                            notify_auto_heal_succeeded,
                        )

                        notify_auto_heal_succeeded(step_name, heal_type)
                    except Exception:
                        pass

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
                    if self.ws_server and self.ws_server.is_running:
                        import asyncio

                        step_idx = (
                            self.event_emitter.current_step_index
                            if self.event_emitter
                            else 0
                        )
                        asyncio.create_task(
                            self.ws_server.auto_heal_completed(
                                skill_id=self.skill_id,
                                step_index=step_idx,
                                fix_action=heal_type,
                                success=False,
                            )
                        )

                    # Emit toast notification for auto-heal failure
                    try:
                        from tool_modules.aa_workflow.src.notification_emitter import (
                            notify_auto_heal_failed,
                        )

                        notify_auto_heal_failed(step_name, error_msg[:100])
                    except Exception:
                        pass
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
            try:
                from tool_modules.aa_workflow.src.notification_emitter import (
                    notify_step_failed,
                )

                notify_step_failed(skill_name, step_name, error_msg[:150])
            except Exception:
                pass

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
        except Exception:
            pass

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
        if self.event_emitter:
            self.event_emitter.skill_start()

        # Emit skill start event (WebSocket)
        if self.ws_server and self.ws_server.is_running:
            import asyncio

            asyncio.create_task(
                self.ws_server.skill_started(
                    skill_id=self.skill_id,
                    skill_name=skill_name,
                    total_steps=total_steps,
                    inputs=self.inputs,
                    source=self.source,
                )
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
                    if self.event_emitter:
                        self.event_emitter.step_skipped(step_index, "condition false")
                    continue

            # Emit step start event (file-based)
            if self.event_emitter:
                self.event_emitter.step_start(step_index)

            # Emit step start event (WebSocket)
            if self.ws_server and self.ws_server.is_running:
                import asyncio

                description = step.get("description", "")
                asyncio.create_task(
                    self.ws_server.step_started(
                        skill_id=self.skill_id,
                        step_index=step_index,
                        step_name=step_name,
                        description=description[:200] if description else "",
                    )
                )

            if "then" in step:
                early_return = self._process_then_block(step, output_lines)
                if early_return is not None:
                    # Emit skill complete (early return)
                    if self.event_emitter:
                        total_time = time.time() - (self.start_time or 0.0)
                        self.event_emitter.skill_complete(True, int(total_time * 1000))
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
                    if self.event_emitter:
                        duration_ms = int((time.time() - step_start_time) * 1000)
                        self.event_emitter.step_failed(
                            step_index, duration_ms, step_error or "Step failed"
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

            # Emit step complete/failed event (file-based)
            if self.event_emitter:
                duration_ms = int((time.time() - step_start_time) * 1000)
                if step_success:
                    self.event_emitter.step_complete(step_index, duration_ms)
                else:
                    self.event_emitter.step_failed(
                        step_index, duration_ms, step_error or "Unknown error"
                    )

            # Emit step complete/failed event (WebSocket)
            if self.ws_server and self.ws_server.is_running:
                import asyncio

                duration_ms = int((time.time() - step_start_time) * 1000)
                if step_success:
                    asyncio.create_task(
                        self.ws_server.step_completed(
                            skill_id=self.skill_id,
                            step_index=step_index,
                            step_name=step_name,
                            duration_ms=duration_ms,
                        )
                    )
                else:
                    asyncio.create_task(
                        self.ws_server.step_failed(
                            skill_id=self.skill_id,
                            step_index=step_index,
                            step_name=step_name,
                            error=step_error or "Unknown error",
                        )
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
        if self.event_emitter:
            overall_success = fail_count == 0
            self.event_emitter.skill_complete(overall_success, int(total_time * 1000))
            # Clear the global emitter
            try:
                from .skill_execution_events import set_emitter

                set_emitter(None)
            except Exception:
                pass

        # Emit skill complete event (WebSocket)
        if self.ws_server and self.ws_server.is_running:
            import asyncio

            overall_success = fail_count == 0
            if overall_success:
                asyncio.create_task(
                    self.ws_server.skill_completed(
                        skill_id=self.skill_id,
                        total_duration_ms=int(total_time * 1000),
                    )
                )
            else:
                # Get last error from step_results
                last_error = "Skill failed"
                for r in reversed(self.step_results):
                    if not r.get("success") and r.get("error"):
                        last_error = r["error"]
                        break
                asyncio.create_task(
                    self.ws_server.skill_failed(
                        skill_id=self.skill_id,
                        error=last_error,
                        total_duration_ms=int(total_time * 1000),
                    )
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
        executor = SkillExecutor(
            skill,
            input_data,
            debug=debug,
            server=server,
            create_issue_fn=create_issue_fn,
            ask_question_fn=ask_question_fn,
            enable_interactive_recovery=True,
            emit_events=True,  # Enable VS Code extension events
            workspace_uri=workspace_uri,
            ctx=ctx,
            session_id=session_id,
            session_name=session_name,
            source=source,
            source_details=source_details,
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
