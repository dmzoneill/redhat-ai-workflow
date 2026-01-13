"""Skill Execution Engine - Multi-step workflow execution.

Provides:
- skill_list: List available skills
- skill_run: Execute a skill
- SkillExecutor: Class that handles step-by-step execution
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from mcp.server.fastmcp import FastMCP
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

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Layer 5: Usage Pattern Learning integration
try:
    from server.usage_pattern_learner import UsagePatternLearner

    LAYER5_AVAILABLE = True
except ImportError:
    LAYER5_AVAILABLE = False
    logger.warning("Layer 5 (Usage Pattern Learning) not available - errors won't be learned from")


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
            for category in ["error_patterns", "auth_patterns", "bonfire_patterns", "pipeline_patterns"]:
                for pattern in patterns.get(category, []):
                    pattern_text = pattern.get("pattern", "").lower()
                    if pattern_text and (pattern_text in error_lower or pattern_text in tool_lower):
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


class SkillExecutor:
    """Full skill execution engine with debug support."""

    def __init__(
        self,
        skill: dict,
        inputs: dict,
        debug: bool = False,
        server: FastMCP | None = None,
        create_issue_fn=None,
        ask_question_fn=None,
        enable_interactive_recovery: bool = True,
    ):
        self.skill = skill
        self.inputs = inputs
        self.debug = debug
        self.server = server
        self.create_issue_fn = create_issue_fn
        self.ask_question_fn = ask_question_fn
        self.enable_interactive_recovery = enable_interactive_recovery
        # Load config.json config for compute blocks
        self.config = load_config()
        self.context = {
            "inputs": inputs,
            "config": self.config,
        }
        self.log: list[str] = []
        self.step_results: list[dict] = []
        self.start_time: float | None = None
        self.error_recovery = None  # Initialized when needed

        # Layer 5: Initialize usage pattern learner
        self.usage_learner = None
        if LAYER5_AVAILABLE:
            try:
                self.usage_learner = UsagePatternLearner()
            except Exception as e:
                logger.warning(f"Failed to initialize Layer 5 learner: {e}")

    def _debug(self, msg: str):
        """Add debug message."""
        if self.debug:
            import time

            elapsed = f"[{time.time() - self.start_time:.2f}s]" if self.start_time else ""
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
            await self.usage_learner.learn_from_observation(
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
            for cat in ["auth_patterns", "error_patterns", "bonfire_patterns", "pipeline_patterns"]:
                for pattern in patterns_data.get(cat, []):
                    pattern_text = pattern.get("pattern", "").lower()
                    if pattern_text and pattern_text in error_lower:
                        # Track that pattern was matched
                        self._update_pattern_usage_stats(cat, pattern_text, matched=True)
                        return pattern, cat
        except Exception as e:
            self._debug(f"Pattern lookup failed: {e}")

        return None, None

    def _determine_fix_type(self, error_lower: str, matched_pattern: dict | None, matches: list) -> str | None:
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
                if "login" in cmd.lower() or "auth" in cmd.lower() or "kube" in cmd.lower():
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
        """Apply VPN connect fix."""
        import asyncio

        try:
            proc = await asyncio.create_subprocess_shell(
                "nmcli connection up 'Red Hat Global VPN' 2>/dev/null || true",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.wait(), timeout=30)
            self._debug(f"  → VPN connect result: {proc.returncode}")
            await asyncio.sleep(2)  # Wait for VPN to establish
            return True
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
            self._update_pattern_usage_stats(pattern_category, pattern_text, matched=False, fixed=True)

        return fix_success

    def _update_pattern_usage_stats(
        self, category: str, pattern_text: str, matched: bool = True, fixed: bool = False
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
                                stats["times_matched"] = stats.get("times_matched", 0) + 1
                                stats["last_matched"] = datetime.now().isoformat()

                            if fixed:
                                stats["times_fixed"] = stats.get("times_fixed", 0) + 1

                            # Recalculate success rate
                            if stats["times_matched"] > 0:
                                stats["success_rate"] = round(stats["times_fixed"] / stats["times_matched"], 2)

                            # Write back
                            f.seek(0)
                            f.truncate()
                            yaml.dump(patterns_data, f, default_flow_style=False, sort_keys=False)
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
        gitlab_url = self.config.get("gitlab", {}).get("url", "https://gitlab.cee.redhat.com")
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
                    self._update_pattern_usage_stats("error_patterns", pattern_text, matched=True)

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
        if not isinstance(text, str) or "{{" not in text:
            return text

        try:
            from jinja2 import Environment

            env = Environment(autoescape=True)
            env.filters.update(self._create_jinja_filters())

            template = env.from_string(text)
            return template.render(**self.context)
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

            env = Environment(autoescape=True)
            # Wrap condition in {{ }} if not already there for Jinja evaluation
            if "{{" not in condition:
                expr = "{{ " + condition + " }}"
            else:
                expr = condition

            result_str = env.from_string(expr).render(**self.context).strip()
            # If it's a boolean-like string, convert it
            if result_str.lower() in ("true", "1", "yes"):
                return True
            if result_str.lower() in ("false", "0", "no", ""):
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
                success=not isinstance(fixed_result, str) or not fixed_result.startswith("<compute error:"),
                details=f"Auto-fixed {error_info.get('pattern_id')}",
            )

            return fixed_result
        except Exception as e:
            self._debug(f"Auto-fix failed: {e}")
            self.error_recovery.log_fix_attempt(error_info, action="auto_fix", success=False, details=str(e))
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
            error_info, action="manual_edit", success=True, details="User manually edited skill"
        )

        # Return None to signal skill should be aborted and re-run
        return None

    def _handle_skip_action(self, error_info: dict, step_name: str):
        """Handle skip action for interactive recovery."""
        print(f"\n⏭️  Skipping skill execution.\n" f"   Error in step: {step_name}\n")

        self.error_recovery.log_fix_attempt(error_info, action="skip", success=False, details="User chose to skip")
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
            error_info, action="abort", success=False, details="User aborted with issue creation"
        )
        return None

    def _handle_continue_action(self, error_info: dict, error_msg: str):
        """Handle continue action for interactive recovery."""
        # Debug mode - let broken data propagate
        self.error_recovery.log_fix_attempt(
            error_info, action="continue", success=False, details="User chose to continue with error"
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
                self.error_recovery.prompt_user_for_action(error_info, self.ask_question_fn)
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

    def _exec_compute_internal(self, code: str, output_name: str):
        """Internal compute execution without error recovery (used by recovery itself)."""
        # This is the actual compute logic extracted from _exec_compute
        # to avoid infinite recursion during auto-fix retries
        local_vars = dict(self.context)
        local_vars["inputs"] = self.inputs
        local_vars["config"] = self.config

        import os
        import re
        from datetime import datetime, timedelta
        from pathlib import Path

        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            ZoneInfo = None

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
            parsers = None
            jira_utils = None
            load_skill_config = None
            get_timezone = None
            emit_event_sync = None
            memory_helpers = None
            config_loader = None
            lint_utils = None
            repo_utils = None
            slack_utils = None

        try:
            from google.oauth2.credentials import Credentials as GoogleCredentials
            from googleapiclient.discovery import build as google_build
        except ImportError:
            GoogleCredentials = None
            google_build = None

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
                recovery_result = self._try_interactive_recovery(code, str(e), output_name)
                if recovery_result is not None:
                    return recovery_result

            return f"<compute error: {e}>"

    def _get_module_for_tool(self, tool_name: str) -> str | None:
        """Map tool name to module name based on prefix."""
        module_prefixes = {
            "git_": "git",
            "jira_": "jira",
            "gitlab_": "gitlab",
            "slack_": "slack",
            "kubectl_": "k8s",
            "k8s_": "k8s",
            "prometheus_": "prometheus",
            "alertmanager_": "alertmanager",
            "kibana_": "kibana",
            "konflux_": "konflux",
            "tkn_": "konflux",
            "bonfire_": "bonfire",
            "quay_": "quay",
            "appinterface_": "appinterface",
            # Lint module tools (developer-specific)
            "lint_": "lint",
            "test_": "lint",
            "security_": "lint",
            "precommit_": "lint",
            # Dev-workflow module tools (developer-specific)
            "workflow_": "dev_workflow",
            # Core workflow module tools (always loaded)
            "memory_": "workflow",
            "persona_": "workflow",
            "skill_": "workflow",
            "session_": "workflow",
            "tool_": "workflow",
            "vpn_": "workflow",
            "kube_": "workflow",
            "debug_": "workflow",
        }

        for prefix, mod in module_prefixes.items():
            if tool_name.startswith(prefix):
                return mod
        return None

    def _format_tool_result(self, result, duration: float) -> dict:
        """Format tool execution result into standard dict."""
        if isinstance(result, tuple):
            result = result[0]
        if isinstance(result, list) and result:
            text = result[0].text if hasattr(result[0], "text") else str(result[0])
            return {"success": True, "result": text, "duration": duration}
        return {"success": True, "result": str(result), "duration": duration}

    async def _execute_workflow_tool(self, tool_name: str, args: dict, start_time: float) -> dict:
        """Execute a tool from the workflow module."""
        import time

        try:
            result = await self.server.call_tool(tool_name, args)
            duration = time.time() - start_time
            self._debug(f"  → Completed in {duration:.2f}s")
            return self._format_tool_result(result, duration)
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _load_and_execute_module_tool(self, module: str, tool_name: str, args: dict, start_time: float) -> dict:
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
            self._debug(f"  → Completed in {duration:.2f}s")
            return self._format_tool_result(result, duration)

        except Exception as e:
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
        result = await self._load_and_execute_module_tool(module, tool_name, args, start)

        # If there was an error, try auto-fix and retry
        if not result.get("success"):
            error_msg = result["error"]
            temp_server = result.get("_temp_server")

            if temp_server:
                self._debug(f"  → Error: {error_msg}")

                # Check for known issues and attempt auto-fix
                matches = _check_known_issues_sync(tool_name=tool_name, error_text=error_msg)
                known_text = _format_known_issues(matches)

                if matches:
                    self._debug(f"  → Found {len(matches)} known issue(s), attempting auto-fix")
                    fix_applied = await self._try_auto_fix(error_msg, matches)

                    if fix_applied:
                        self._debug("  → Auto-fix applied, retrying tool")
                        try:
                            retry_result = await temp_server.call_tool(tool_name, args)
                            duration = time.time() - start
                            self._debug(f"  → Retry completed in {duration:.2f}s")
                            return self._format_tool_result(retry_result, duration)
                        except Exception as retry_e:
                            error_msg = f"{error_msg}\n\n(Retry after auto-fix also failed: {retry_e})"

                if known_text:
                    error_msg = f"{error_msg}\n{known_text}"

                result["error"] = error_msg

        # Remove internal _temp_server key if present
        result.pop("_temp_server", None)
        return result

    async def _handle_tool_error(
        self, tool: str, step: dict, step_name: str, error_msg: str, output_lines: list[str]
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
                    output_lines.append(f"\n   🐛 **Issue created:** {issue_result['issue_url']}")
                elif issue_result["issue_url"]:
                    output_lines.append("\n   💡 **Report this error:**")
                    output_lines.append(f"   📝 [Create GitHub Issue]({issue_result['issue_url']})")
            except Exception as e:
                self._debug(f"Failed to create issue: {e}")

        on_error = step.get("on_error", "fail")
        if on_error == "continue":
            output_lines.append("   *Continuing despite error (on_error: continue)*\n")

            # Layer 5: Learn from this error
            tool_params = {}
            if "args" in step:
                args_data = step["args"]
                if isinstance(args_data, dict):
                    tool_params = {k: self._template(str(v)) for k, v in args_data.items()}

            await self._learn_from_error(tool_name=tool, params=tool_params, error_msg=error_msg)

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

    async def _process_tool_step(self, step: dict, step_num: int, step_name: str, output_lines: list[str]) -> bool:
        """Process a 'tool' step and append results to output_lines.

        Returns:
            True if processing should continue, False if skill should stop
        """
        tool = step["tool"]
        raw_args = step.get("args", {})
        args = self._template_dict(raw_args)

        output_lines.append(f"🔧 **Step {step_num}: {step_name}**")
        output_lines.append(f"   *Tool: `{tool}`*")

        result = await self._exec_tool(tool, args)

        if result["success"]:
            output_name = step.get("output", step_name)
            self.context[output_name] = result["result"]

            # Try to parse key:value output
            self._parse_and_store_tool_result(result["result"], output_name)

            duration = result.get("duration", 0)
            output_lines.append(f"   ✅ Success ({duration:.2f}s)")

            result_preview = result["result"][:300]
            if len(result["result"]) > 300:
                result_preview += "..."
            output_lines.append(f"   ```\n   {result_preview}\n   ```\n")

            self.step_results.append({"step": step_name, "tool": tool, "success": True, "duration": duration})
            return True

        # Handle error
        should_continue = await self._handle_tool_error(tool, step, step_name, result["error"], output_lines)
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
                        else [self._template(i) if isinstance(i, str) else i for i in val]
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
                templated = self._template_dict(ret) if isinstance(ret, dict) else self._template(str(ret))
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

    async def execute(self) -> str:
        """Execute all steps and return the result."""
        import time

        self.start_time = time.time()

        skill_name = self.skill.get("name", "unknown")
        self._debug(f"Starting skill: {skill_name}")
        self._debug(f"Inputs: {json.dumps(self.inputs)}")

        for inp in self.skill.get("inputs", []):
            name = inp["name"]
            if name not in self.inputs and "default" in inp:
                self.inputs[name] = inp["default"]
                self.context["inputs"] = self.inputs
                self._debug(f"Applied default: {name} = {inp['default']}")

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
            step_num += 1
            step_name = step.get("name", f"step_{step_num}")

            if "condition" in step:
                if not self._eval_condition(step["condition"]):
                    self._debug(f"Skipping step '{step_name}' - condition false")
                    output_lines.append(f"⏭️ **Step {step_num}: {step_name}** - *skipped (condition false)*\n")
                    continue

            if "then" in step:
                early_return = self._process_then_block(step, output_lines)
                if early_return is not None:
                    return early_return
                continue

            if "tool" in step:
                should_continue = await self._process_tool_step(step, step_num, step_name, output_lines)
                if not should_continue:
                    break

            elif "compute" in step:
                output_name = step.get("output", step_name)
                output_lines.append(f"🧮 **Step {step_num}: {step_name}** (compute)")

                result = self._exec_compute(step["compute"], output_name)
                self.context[output_name] = result

                output_lines.append(f"   → `{output_name}` = {str(result)[:100]}\n")

            elif "description" in step:
                output_lines.append(f"📝 **Step {step_num}: {step_name}** (manual)")
                output_lines.append(f"   {self._template(step['description'])}\n")

        self._format_skill_outputs(output_lines)

        total_time = time.time() - (self.start_time or 0.0)
        success_count = sum(1 for r in self.step_results if r.get("success"))
        fail_count = sum(1 for r in self.step_results if not r.get("success"))

        output_lines.append(
            f"\n---\n⏱️ *Completed in {total_time:.2f}s* | " f"✅ {success_count} succeeded | ❌ {fail_count} failed"
        )

        if self.debug and self.log:
            output_lines.append("\n\n### 🔍 Debug Log\n```")
            output_lines.extend(self.log)
            output_lines.append("```")

        return "\n".join(output_lines)


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
                skills.append({"name": f.stem, "description": f"Error loading: {e}", "inputs": []})

    if not skills:
        return [TextContent(type="text", text="No skills found. Create .yaml files in skills/ directory.")]

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


def _format_skill_plan(skill: dict, skill_name: str, input_data: dict) -> list[TextContent]:
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
) -> list[TextContent]:
    """Implementation of skill_run tool."""
    skill_file = SKILLS_DIR / f"{skill_name}.yaml"
    if not skill_file.exists():
        available = [f.stem for f in SKILLS_DIR.glob("*.yaml")] if SKILLS_DIR.exists() else []
        return [
            TextContent(
                type="text",
                text=f"❌ Skill not found: {skill_name}\n\n" f"Available: {', '.join(available) or 'none'}",
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
                lines.append(f"- `{inp['name']}` ({inp.get('type', 'string')}) - {req}{default}")
                if inp.get("description"):
                    lines.append(f"  {inp['description']}")
            return [TextContent(type="text", text="\n".join(lines))]

        # Preview mode: just show the plan
        if not execute:
            return _format_skill_plan(skill, skill_name, input_data)

        # Execute mode: run the skill
        executor = SkillExecutor(
            skill,
            input_data,
            debug=debug,
            server=server,
            create_issue_fn=create_issue_fn,
            ask_question_fn=ask_question_fn,
            enable_interactive_recovery=True,
        )
        result = await executor.execute()

        return [TextContent(type="text", text=result)]

    except Exception as e:
        import traceback

        if debug:
            return [TextContent(type="text", text=f"❌ Error: {e}\n\n```\n{traceback.format_exc()}\n```")]
        return [TextContent(type="text", text=f"❌ Error loading skill: {e}")]


def register_skill_tools(server: "FastMCP", create_issue_fn=None, ask_question_fn=None) -> int:
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
        skill_name: str, inputs: str = "{}", execute: bool = True, debug: bool = False
    ) -> list[TextContent]:
        """
        Execute a skill (multi-step workflow).

        Skills chain multiple MCP tools together with logic and conditions.

        Args:
            skill_name: Name of the skill (e.g., "start_work", "investigate_alert")
            inputs: JSON object with input parameters
            execute: If True (default), run the tools. If False, just show the plan.
            debug: If True, show detailed execution trace with timing.

        Returns:
            Execution results or plan preview.
        """
        return await _skill_run_impl(skill_name, inputs, execute, debug, server, create_issue_fn, ask_question_fn)

    return registry.count
