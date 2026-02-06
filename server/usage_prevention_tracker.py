"""
Usage Prevention Tracker - Layer 5 Phase 4.

Tracks when Claude follows or ignores prevention warnings.
Updates pattern confidence based on effectiveness.
"""

import logging
import threading
from typing import Optional

from server.usage_pattern_learner import UsagePatternLearner

logger = logging.getLogger(__name__)


class UsagePreventionTracker:
    """Track prevention success and update pattern confidence."""

    _instance: Optional["UsagePreventionTracker"] = None
    _lock = threading.Lock()

    def __init__(self):
        """Initialize tracker."""
        self.learner = UsagePatternLearner()

    @classmethod
    def get_instance(cls) -> "UsagePreventionTracker":
        """Get singleton instance (thread-safe)."""
        if cls._instance is None:
            with cls._lock:
                # Double-check pattern to avoid race condition
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    async def track_warning_shown(
        self,
        tool_name: str,
        params: dict,
        patterns_matched: list[str],
        was_blocked: bool,
    ) -> None:
        """Record that a warning was shown to Claude.

        Args:
            tool_name: Tool that was about to be called
            params: Parameters that triggered warning
            patterns_matched: IDs of patterns that matched
            was_blocked: Whether execution was blocked
        """
        # Store in temporary tracking (could use in-memory dict or file)
        # For now, just log it
        logger.info(
            f"Layer 5 prevention: Warned about {tool_name} " f"(patterns: {patterns_matched}, blocked: {was_blocked})"
        )

    async def track_prevention_success(
        self,
        pattern_id: str,
        tool_name: str,
        original_params: dict,
        corrected_params: dict,
    ) -> bool:
        """Record that Claude followed prevention steps and succeeded.

        This is called when we detect that Claude:
        1. Received a warning
        2. Fixed the parameters
        3. Called the tool successfully

        Args:
            pattern_id: ID of pattern that was warned about
            tool_name: Tool that was called
            original_params: Original parameters that triggered warning
            corrected_params: Corrected parameters used in successful call

        Returns:
            True if prevention success recorded
        """
        try:
            # Update pattern: increase confidence
            success = await self.learner.record_prevention_success(pattern_id)

            if success:
                logger.info(f"Layer 5: Prevention success for pattern {pattern_id} " f"(tool: {tool_name})")
                logger.debug(f"Original params: {original_params}, " f"Corrected params: {corrected_params}")

            return success

        except (AttributeError, TypeError, ValueError, KeyError, OSError) as e:
            logger.warning(f"Failed to track prevention success: {e}")
            return False

    async def track_false_positive(
        self,
        pattern_id: str,
        tool_name: str,
        params: dict,
        reason: str = "tool_succeeded_despite_warning",
    ) -> bool:
        """Record that a warning was a false positive.

        This is called when:
        1. Claude was warned about a pattern
        2. Claude ignored the warning
        3. The tool succeeded anyway (warning was wrong)

        Args:
            pattern_id: ID of pattern that warned incorrectly
            tool_name: Tool that was called
            params: Parameters that were warned about
            reason: Reason for false positive

        Returns:
            True if false positive recorded
        """
        try:
            # Update pattern: decrease confidence
            success = await self.learner.record_prevention_failure(pattern_id, reason)

            if success:
                logger.info(
                    f"Layer 5: False positive for pattern {pattern_id} " f"(tool: {tool_name}, reason: {reason})"
                )
                logger.debug(f"Params: {params}")

            return success

        except (AttributeError, TypeError, ValueError, KeyError, OSError) as e:
            logger.warning(f"Failed to track false positive: {e}")
            return False

    async def analyze_call_result(
        self,
        tool_name: str,
        params: dict,
        result: str,
        usage_check: Optional[dict] = None,
    ) -> dict:
        """Analyze tool call result and detect prevention success or false positive.

        Args:
            tool_name: Tool that was called
            params: Parameters used
            result: Tool result
            usage_check: Pre-call usage check result (warnings, patterns_matched, etc.)

        Returns:
            {
                "prevention_success": bool,
                "false_positive": bool,
                "patterns_affected": list[str],
                "reason": str
            }
        """
        analysis = {
            "prevention_success": False,
            "false_positive": False,
            "patterns_affected": [],
            "reason": "",
        }

        if not usage_check or not usage_check.get("warnings"):
            # No warnings were shown, nothing to track
            return analysis

        # Check if tool succeeded
        tool_succeeded = self._is_success(result)

        if tool_succeeded:
            # Tool succeeded after warning
            # This could be:
            # 1. False positive (warning was wrong)
            # 2. Prevention success (Claude fixed parameters, but we can't easily detect this)

            # For now, if warned but succeeded, treat as potential false positive
            # In future, could compare params to pattern to see if they match
            patterns_matched = usage_check.get("patterns_matched", [])

            # Check if params still match mistake pattern
            # If they match but tool succeeded → false positive
            # If they don't match → prevention success (Claude fixed it)

            # For Phase 4 MVP: Log as potential false positive
            # Can refine detection logic later
            analysis["false_positive"] = True
            analysis["patterns_affected"] = patterns_matched
            analysis["reason"] = "tool_succeeded_despite_warning"

            logger.info(
                f"Layer 5: Potential false positive - {tool_name} succeeded "
                f"despite warning (patterns: {patterns_matched})"
            )

        else:
            # Tool failed after warning
            # This confirms the warning was correct
            # Don't need to do anything (pattern already has observations)
            pass

        return analysis

    def _is_success(self, result: str) -> bool:
        """Check if tool result indicates success.

        Args:
            result: Tool result string

        Returns:
            True if result indicates success
        """
        if not result:
            return False

        result_lower = result.lower()

        # Check for error indicators
        is_error = (
            "❌" in result
            or result_lower.startswith("error")
            or "failed" in result_lower[:200]
            or "exception" in result_lower[:200]
            or "unauthorized" in result_lower
            or "forbidden" in result_lower
        )

        return not is_error


def get_prevention_tracker() -> UsagePreventionTracker:
    """Get singleton prevention tracker instance."""
    return UsagePreventionTracker.get_instance()
