"""
Interactive error recovery for skill execution failures.

This module provides:
1. Pattern detection for common skill errors
2. Interactive user prompts for recovery options
3. Memory-based learning from previous fixes
4. Auto-fix capabilities for known patterns
"""

import asyncio
import logging
import re
from datetime import datetime

import yaml

logger = logging.getLogger(__name__)

# Errors a memory helper or user-question callback can raise; anything else is a real bug and propagates.
_RECOVERABLE_ERRORS = (OSError, KeyError, TypeError, ValueError, RuntimeError, AttributeError)

# User-facing option label -> recovery action
_LABEL_TO_ACTION = {
    "Auto-fix (Recommended)": "auto_fix",
    "Edit skill file": "edit",
    "Skip skill": "skip",
    "Create GitHub issue": "abort",
    "Continue anyway": "continue",
}


class SkillErrorRecovery:
    """Handle skill execution errors with interactive recovery and memory."""

    def __init__(self, memory_helper=None):
        """
        Initialize error recovery system.

        Args:
            memory_helper: Memory helper for storing/retrieving learned fixes
        """
        self.memory = memory_helper
        self.patterns = self._load_known_patterns()

    def _load_known_patterns(self) -> dict:
        """Load known error patterns from memory or defaults."""
        default_patterns = {
            "dict_attribute_access": {
                "signature": r"'dict' object has no attribute '(\w+)'",
                "description": "Using dot notation on dict instead of get()",
                "fix_template": "inputs.{attr} → inputs.get('{attr}')",
                "auto_fixable": True,
                "confidence": "high",
            },
            "key_error": {
                "signature": r"KeyError: '(\w+)'",
                "description": "Missing required key in dict",
                "fix_template": "Check if '{key}' exists or use .get() with default",
                "auto_fixable": False,
                "confidence": "medium",
            },
            "undefined_variable": {
                "signature": r"name '(\w+)' is not defined",
                "description": "Variable not defined in compute block",
                "fix_template": "Define {var} or check for typos",
                "auto_fixable": False,
                "confidence": "high",
            },
            "template_not_resolved": {
                "signature": r"\{\{.*?\}\}",
                "description": "Jinja template variable not resolved",
                "fix_template": "Check if variable exists in context",
                "auto_fixable": False,
                "confidence": "medium",
            },
            "missing_import": {
                "signature": r"No module named '(\w+)'",
                "description": "Missing Python import",
                "fix_template": "Add 'from ... import {module}'",
                "auto_fixable": False,
                "confidence": "high",
            },
        }

        # Try to load learned patterns from memory
        if self.memory:
            try:
                learned = self.memory.read("learned/skill_error_patterns")
                if learned and "patterns" in learned:
                    # Merge learned patterns with defaults
                    default_patterns.update(learned["patterns"])
            except _RECOVERABLE_ERRORS as e:
                # Log but continue with defaults
                logger.debug("Could not load learned patterns: %s", e)

        return default_patterns

    def detect_error(self, code: str, error_msg: str, step_name: str) -> dict:
        """
        Analyze error and detect pattern.

        Args:
            code: The compute block code that failed
            error_msg: The error message
            step_name: Name of the failed step

        Returns:
            dict with:
                - pattern_id: str or None
                - description: str
                - suggestion: str
                - auto_fixable: bool
                - fix_code: str or None (if auto-fixable)
                - previous_fixes: list (from memory)
        """
        matched_pattern, extracted_data = self._match_pattern(error_msg)

        # Check memory for this specific error
        previous_fixes = self._get_previous_fixes(error_msg, step_name)

        result = {
            "pattern_id": matched_pattern,
            "description": (
                self.patterns[matched_pattern]["description"] if matched_pattern else "Unknown error pattern"
            ),
            "error_msg": error_msg[:200],
            "step_name": step_name,
            "previous_fixes": previous_fixes,
            "timestamp": datetime.now().astimezone().isoformat(),
        }

        # Generate suggestion and fix code if pattern matched
        if matched_pattern:
            pattern = self.patterns[matched_pattern]
            result["auto_fixable"] = pattern["auto_fixable"]
            result["confidence"] = pattern.get("confidence", "medium")

            # Special handling for dict attribute access
            if matched_pattern == "dict_attribute_access" and extracted_data:
                attr = extracted_data.get("group0", "")
                result["suggestion"] = f"Change inputs.{attr} to inputs.get('{attr}')"
                result["fix_code"] = self._generate_dict_access_fix(code, attr)

            else:
                # Generic template-based suggestion
                suggestion = pattern["fix_template"]
                for key, val in extracted_data.items():
                    suggestion = suggestion.replace(f"{{{key[5:]}}}", val)
                result["suggestion"] = suggestion
                result["fix_code"] = None

        else:
            result["auto_fixable"] = False
            result["confidence"] = "low"
            result["suggestion"] = "Unknown error - manual inspection needed"
            result["fix_code"] = None

        return result

    def _match_pattern(self, error_msg: str) -> tuple[str | None, dict]:
        """Return (pattern_id, captured groups as {"groupN": value}) for the first matching known pattern."""
        for pattern_id, pattern_info in self.patterns.items():
            match = re.search(pattern_info["signature"], error_msg)
            if match:
                return pattern_id, {f"group{i}": g for i, g in enumerate(match.groups())}
        return None, {}

    def _generate_dict_access_fix(self, code: str, attr: str) -> str:
        """
        Generate fixed code for dict attribute access pattern.

        Args:
            code: Original code
            attr: Attribute name that was accessed

        Returns:
            Fixed code with inputs.attr replaced by inputs.get("attr")
        """
        # Replace inputs.attr with inputs.get("attr")
        # Handle common cases: inputs.attr, inputs.attr.upper(), etc.
        fixed = re.sub(
            rf"\binputs\.{attr}\b",
            f'inputs.get("{attr}")',
            code,
        )

        # Also handle cases where there might be chained calls
        # e.g., inputs.attr.upper() -> inputs.get("attr", "").upper()
        fixed = re.sub(
            rf'\binputs\.get\("{attr}"\)\.(upper|lower|strip)\(\)',
            f'inputs.get("{attr}", "").\\1()',
            fixed,
        )

        return fixed

    def _get_previous_fixes(self, error_msg: str, step_name: str) -> list:
        """
        Get previous fixes for similar errors from memory.

        Args:
            error_msg: Current error message
            step_name: Current step name

        Returns:
            List of previous fix attempts with outcomes
        """
        if not self.memory:
            return []

        try:
            history = self.memory.read("learned/skill_error_fixes")
            if not history or "fixes" not in history:
                return []

            # Find similar errors (same step or same error message)
            similar = []
            for fix in history["fixes"]:
                if fix.get("step_name") == step_name or error_msg[:50] in fix.get("error_msg", ""):
                    similar.append(
                        {
                            "timestamp": fix.get("timestamp"),
                            "action": fix.get("action"),
                            "success": fix.get("success"),
                            "description": fix.get("description", "")[:100],
                        }
                    )

            return similar[:5]  # Return last 5 similar fixes

        except _RECOVERABLE_ERRORS as e:
            logger.debug("Could not get similar fixes: %s", e)
            return []

    async def prompt_user_for_action(self, error_info: dict, ask_question_fn=None) -> dict:
        """
        Prompt user for recovery action (via AskUserQuestion or CLI fallback).

        Args:
            error_info: Error detection result from detect_error()
            ask_question_fn: Optional function to call AskUserQuestion tool
                            If None, falls back to command-line input

        Returns:
            dict with:
                - action: str (auto_fix, edit, skip, abort, continue)
                - user_input: any additional user input
        """
        context_msg = self._build_context_message(error_info)
        options = self._build_options(error_info.get("auto_fixable", False), error_info["suggestion"])

        selected = None
        if ask_question_fn:
            selected = await self._ask_via_tool(ask_question_fn, error_info["step_name"], context_msg, options)
        if selected is None:
            selected = await self._ask_via_cli(error_info["step_name"], context_msg, options)

        return {
            "action": _LABEL_TO_ACTION.get(selected, "abort"),
            "selected_option": selected,
            "error_info": error_info,
        }

    @staticmethod
    def _build_context_message(error_info: dict) -> str:
        """Human-readable summary of the error, suggestion and previous fixes."""
        context_lines = [
            f"**Step:** {error_info['step_name']}",
            f"**Error:** {error_info['error_msg']}",
            f"**Suggestion:** {error_info['suggestion']}",
        ]
        previous_fixes = error_info.get("previous_fixes", [])
        if previous_fixes:
            context_lines.append("\n**Previous fixes for similar errors:**")
            for fix in previous_fixes:
                status = "✅" if fix.get("success") else "❌"
                context_lines.append(f"  {status} {fix.get('action')} - {fix.get('description', 'N/A')[:50]}")
        return "\n".join(context_lines)

    @staticmethod
    def _build_options(auto_fixable: bool, suggestion: str) -> list[dict]:
        """Recovery options; auto-fix is offered first when available."""
        options = []
        if auto_fixable:
            options.append(
                {
                    "label": "Auto-fix (Recommended)",
                    "description": f"Apply automatic fix: {suggestion[:60]}",
                }
            )
        options.extend(
            [
                {"label": "Edit skill file", "description": "Open skill YAML in editor for manual fix"},
                {"label": "Skip skill", "description": "Stop execution and show manual tool commands"},
                {"label": "Create GitHub issue", "description": "Report bug and abort execution"},
                {"label": "Continue anyway", "description": "Debug mode - let broken data propagate"},
            ]
        )
        return options

    @staticmethod
    async def _ask_via_tool(ask_question_fn, step_name: str, context_msg: str, options: list[dict]) -> str | None:
        """Ask through AskUserQuestion; returns the selected label, or None to fall back to the CLI."""
        try:
            response = await ask_question_fn(
                {
                    "questions": [
                        {
                            "question": f"Skill error in step '{step_name}'. How should I proceed?\n\n{context_msg}",
                            "header": "Skill Error",
                            "options": options,
                            "multiSelect": False,
                        }
                    ]
                }
            )
        except _RECOVERABLE_ERRORS as e:
            print(f"\n⚠️  AskUserQuestion failed: {e}")
            print("Falling back to command-line input...\n")
            return None
        answers = response.get("answers", {}) if isinstance(response, dict) else {}
        return next(iter(answers.values()), "Create GitHub issue")

    @staticmethod
    async def _ask_via_cli(step_name: str, context_msg: str, options: list[dict]) -> str:
        """Present options on the terminal; input() runs in a thread so the event loop is not blocked."""
        rule = "=" * 70
        print(f"\n{rule}\n🔴 SKILL ERROR IN STEP: {step_name}\n{rule}\n\n{context_msg}\n\n{rule}")
        print("\nWhat would you like to do?\n")
        for i, opt in enumerate(options, 1):
            print(f"  {i}. {opt['label']}")
            print(f"     {opt['description']}\n")

        while True:
            try:
                choice = await asyncio.to_thread(input, f"Enter choice (1-{len(options)}): ")
                choice_num = int(choice)
            except (ValueError, KeyboardInterrupt, EOFError):
                print("\nAborting...")
                return "Aborted"
            if 1 <= choice_num <= len(options):
                return str(options[choice_num - 1]["label"])
            print(f"Invalid choice. Please enter 1-{len(options)}")

    def log_fix_attempt(self, error_info: dict, action: str, success: bool, details: str = "") -> None:
        """
        Log a fix attempt to memory for future learning.

        Args:
            error_info: Original error detection result
            action: Action taken (auto_fix, edit, skip, etc.)
            success: Whether the fix worked
            details: Additional details about the fix
        """
        if not self.memory:
            return

        fix_entry = {
            "timestamp": datetime.now().astimezone().isoformat(),
            "pattern_id": error_info.get("pattern_id"),
            "step_name": error_info["step_name"],
            "error_msg": error_info["error_msg"],
            "action": action,
            "success": success,
            "description": details,
            "suggestion": error_info.get("suggestion", ""),
        }

        try:
            # Append to fix history
            self.memory.append("learned/skill_error_fixes", "fixes", fix_entry)

            # Update success stats
            if success:
                self.memory.increment("learned/skill_error_fixes", f"stats.{action}_success")
            else:
                self.memory.increment("learned/skill_error_fixes", f"stats.{action}_failed")

        except _RECOVERABLE_ERRORS as e:
            # Best-effort logging - don't fail the main operation
            logger.debug("Could not log fix to memory: %s", e)

    def apply_auto_fix(self, skill_path: str, step_name: str, fix_code: str) -> dict:
        """
        Apply auto-fix to skill YAML file.

        Args:
            skill_path: Path to skill YAML file
            step_name: Name of the step to fix
            fix_code: Fixed code to replace

        Returns:
            dict with success status and details
        """
        try:
            # Read skill file
            with open(skill_path, encoding="utf-8") as f:
                content = f.read()

            # Parse YAML while preserving formatting
            skill_data = yaml.safe_load(content)

            # Find the step and update compute block
            steps = skill_data.get("steps", [])
            step_found = False

            for step in steps:
                if step.get("name") == step_name and "compute" in step:
                    step["compute"] = fix_code
                    step_found = True
                    break

            if not step_found:
                return {
                    "success": False,
                    "error": f"Step '{step_name}' not found in skill",
                }

            # Write back (WARNING: loses YAML comments/formatting; ruamel.yaml would preserve them)
            with open(skill_path, "w", encoding="utf-8") as f:
                yaml.dump(
                    skill_data,
                    f,
                    default_flow_style=False,
                    sort_keys=False,
                    allow_unicode=True,
                )

            return {
                "success": True,
                "message": f"Auto-fixed step '{step_name}' in {skill_path}",
                "backup_note": "Original formatting may be lost. Consider manual review.",
            }

        except (OSError, yaml.YAMLError, AttributeError, TypeError) as e:
            return {"success": False, "error": str(e)}
