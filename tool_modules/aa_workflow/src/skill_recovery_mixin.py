# pylint: disable=duplicate-code,cyclic-import
"""Split from skill_engine.py so the public module stays importable."""

import logging
from typing import Any, Optional

import yaml

from .skill_paths import skills_dir

logger = logging.getLogger(__name__)


class SkillRecoveryMixin:  # pylint: disable=too-few-public-methods
    """SkillExecutor behavior split out of skill_engine."""

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
        except Exception as e:  # pylint: disable=broad-exception-caught
            self._debug(f"Auto-fix failed: {e}")
            self.error_recovery.log_fix_attempt(
                error_info, action="auto_fix", success=False, details=str(e)
            )
            return None

    def _handle_edit_action(self, error_info: dict, error_msg: str, step_name: str):
        """Handle edit action for interactive recovery."""
        skill_name = self.skill.get("name", "unknown")
        skill_path = skills_dir() / f"{skill_name}.yaml"

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

    def _handle_skip_action(self, error_info: dict, step_name: str):
        """Handle skip action for interactive recovery."""
        print(f"\n⏭️  Skipping skill execution.\n   Error in step: {step_name}\n")

        self.error_recovery.log_fix_attempt(
            error_info, action="skip", success=False, details="User chose to skip"
        )

    def _handle_abort_action(self, error_info: dict, error_msg: str, step_name: str):
        """Handle abort action for interactive recovery."""
        # Create GitHub issue if possible
        if self.create_issue_fn:
            try:
                import asyncio  # pylint: disable=import-outside-toplevel

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
            except Exception as e:  # pylint: disable=broad-exception-caught
                self._debug(f"Could not create issue: {e}")

        self.error_recovery.log_fix_attempt(
            error_info,
            action="abort",
            success=False,
            details="User aborted with issue creation",
        )

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
            from scripts.common.skill_error_recovery import (  # pylint: disable=import-outside-toplevel
                SkillErrorRecovery,
            )  # pylint: disable=import-outside-toplevel

            # Pass memory helpers if available
            memory_helper = None
            try:
                from scripts.common import (  # pylint: disable=import-outside-toplevel
                    memory as memory_helpers,
                )  # pylint: disable=import-outside-toplevel

                memory_helper = memory_helpers
            except ImportError as exc:
                logger.debug("Optional import not available: %s", exc)

            self.error_recovery = SkillErrorRecovery(memory_helper=memory_helper)
            return True
        except ImportError as e:
            self._debug(f"Could not load error recovery: {e}")
            return False

    def _try_interactive_recovery(self, code: str, error_msg: str, step_name: str):  # pylint: disable=too-many-return-statements
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
        import asyncio  # pylint: disable=import-outside-toplevel

        try:
            # Call ask_question_fn which is already async
            action_result = asyncio.get_event_loop().run_until_complete(
                self.error_recovery.prompt_user_for_action(
                    error_info, self.ask_question_fn
                )
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            self._debug(f"Interactive prompt failed: {e}")
            return None

        action = action_result.get("action")
        self._debug(f"User chose: {action}")

        # Dispatch to action handlers
        if action == "auto_fix":
            return self._handle_auto_fix_action(error_info, step_name)
        if action == "edit":
            return self._handle_edit_action(error_info, error_msg, step_name)
        if action == "skip":
            return self._handle_skip_action(error_info, step_name)
        if action == "abort":
            return self._handle_abort_action(error_info, error_msg, step_name)
        if action == "continue":
            return self._handle_continue_action(error_info, error_msg)

        return None

    def _create_nested_skill_runner(self):
        """Create a helper function that compute blocks can use to run nested skills.

        Returns a function that can be called like:
            run_skill("jira_hygiene", {"issue_key": "AAP-12345"})
        """
        import asyncio  # pylint: disable=import-outside-toplevel

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
                skill_file = skills_dir() / f"{skill_name}.yaml"
                if not skill_file.exists():
                    return {"success": False, "error": f"Skill not found: {skill_name}"}

                with open(skill_file, encoding="utf-8") as f:
                    nested_skill = yaml.safe_load(f)

                # Imported here so this mixin does not import skill_executor at load time.
                from .skill_executor import (  # pylint: disable=import-outside-toplevel
                    SkillExecutor,
                )

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

            except Exception as e:  # pylint: disable=broad-exception-caught
                return {"success": False, "error": str(e)}

        return run_skill_sync
