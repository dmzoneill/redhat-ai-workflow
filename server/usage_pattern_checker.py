"""
Usage Pattern Checker - Layer 5 of Auto-Heal System.

This module checks learned patterns before tool execution and generates warnings.

Part of Layer 5: Usage Pattern Learning - Phase 3 & 5
"""

import logging
import re
import time
from typing import Optional

from server.usage_pattern_storage import UsagePatternStorage

logger = logging.getLogger(__name__)

# Cache TTL in seconds (5 minutes)
CACHE_TTL = 300


class UsagePatternChecker:
    """Check learned usage patterns before tool execution."""

    def __init__(self, storage: Optional[UsagePatternStorage] = None, cache_ttl: int = CACHE_TTL):
        """Initialize checker.

        Args:
            storage: UsagePatternStorage instance. If None, creates default.
            cache_ttl: Cache time-to-live in seconds (default: 300 = 5 minutes)
        """
        self.storage = storage or UsagePatternStorage()
        self._pattern_cache = None
        self._cache_timestamp = None
        self._cache_ttl = cache_ttl
        self._max_cache_entries = 100  # Prevent unbounded memory growth

    def check_before_call(
        self,
        tool_name: str,
        params: dict,
        context: Optional[dict] = None,
        min_confidence: float = 0.75,
    ) -> dict:
        """Check for learned patterns before calling tool.

        Args:
            tool_name: Name of tool about to be called
            params: Parameters to be passed to tool
            context: Additional context (recent tool calls, etc.)
            min_confidence: Minimum confidence to trigger warning (default: 0.75)

        Returns:
            {
                "warnings": list[str],
                "preventions": list[dict],
                "should_block": bool,
                "patterns_matched": list[str],
                "suggestions": list[dict]
            }
        """
        if context is None:
            context = {}

        result = {
            "warnings": [],
            "preventions": [],
            "should_block": False,
            "patterns_matched": [],
            "suggestions": [],
        }

        # Try to get patterns from cache first (Phase 5 optimization)
        tool_patterns = self._get_cached_patterns(tool_name, min_confidence)

        if tool_patterns is None:
            # Cache miss - load from storage
            tool_patterns = self.storage.get_patterns_for_tool(tool_name, min_confidence=min_confidence)
            # Cache the results
            self._cache_patterns(tool_name, min_confidence, tool_patterns)

        if not tool_patterns:
            logger.debug(f"No patterns found for {tool_name} (min_conf: {min_confidence:.0%})")
            return result

        # Check each pattern
        for pattern in tool_patterns:
            if self._matches_mistake_pattern(params, pattern, context):
                # Pattern matched!
                logger.info(f"Pattern matched: {pattern['id']} for {tool_name} " f"(conf: {pattern['confidence']:.0%})")

                # Generate warning
                warning = self._generate_warning(pattern)
                result["warnings"].append(warning)

                # Add prevention steps
                for step in pattern["prevention_steps"]:
                    result["preventions"].append(
                        {
                            "action": step["action"],
                            "details": step,
                            "pattern_id": pattern["id"],
                        }
                    )

                # Add to matched patterns
                result["patterns_matched"].append(pattern["id"])

                # Check if should block
                if pattern["confidence"] >= 0.95:
                    result["should_block"] = True
                    logger.warning(
                        f"High-confidence pattern matched ({pattern['confidence']:.0%}), "
                        f"suggesting block for {tool_name}"
                    )

        return result

    def _matches_mistake_pattern(self, params: dict, pattern: dict, context: dict) -> bool:
        """Check if current params match a learned mistake pattern.

        Args:
            params: Parameters about to be passed to tool
            pattern: Pattern to check against
            context: Additional context

        Returns:
            True if params match the mistake pattern
        """
        mistake = pattern["mistake_pattern"]
        category = pattern["error_category"]

        # Match based on category
        if category == "PARAMETER_FORMAT":
            return self._match_parameter_format(params, mistake)

        elif category == "INCORRECT_PARAMETER":
            return self._match_incorrect_parameter(params, mistake)

        elif category == "WORKFLOW_SEQUENCE":
            return self._match_workflow_sequence(params, mistake, context)

        elif category == "MISSING_PREREQUISITE":
            return self._match_missing_prerequisite(params, mistake, context)

        # Unknown category
        return False

    def _match_parameter_format(self, params: dict, mistake: dict) -> bool:
        """Check if parameter format matches known mistake.

        Args:
            params: Tool parameters
            mistake: Mistake pattern

        Returns:
            True if format matches mistake
        """
        param_name = mistake.get("parameter")
        if not param_name or param_name not in params:
            return False

        param_value = params[param_name]
        validation = mistake.get("validation", {})

        # Check regex validation
        if "regex" in validation:
            pattern = validation["regex"]
            if not re.match(pattern, str(param_value)):
                logger.debug(
                    f"Parameter '{param_name}' value '{param_value}' " f"does not match expected pattern '{pattern}'"
                )
                return True

        # Check length validation (e.g., short SHA)
        if "check" in validation:
            check_str = validation["check"]
            # Simple eval for checks like "len(image_tag) < 40"
            try:
                if "len(" in check_str:
                    # Extract the check
                    if len(str(param_value)) < 40 and "< 40" in check_str:
                        logger.debug(
                            f"Parameter '{param_name}' value '{param_value}' "
                            f"failed length check (expected >= 40 chars)"
                        )
                        return True
            except (AttributeError, TypeError, ValueError, KeyError) as e:
                logger.debug(f"Error checking validation: {e}")

        return False

    def _match_incorrect_parameter(self, params: dict, mistake: dict) -> bool:
        """Check if parameter value is likely incorrect.

        For ownership issues, we can't know at check-time,
        so we use heuristics.

        Args:
            params: Tool parameters
            mistake: Mistake pattern

        Returns:
            True if parameter likely incorrect
        """
        param_name = mistake.get("parameter")
        if not param_name or param_name not in params:
            return False

        # For namespace ownership, we can't validate without calling bonfire
        # So we check for common mistake patterns
        common_mistakes = mistake.get("common_mistakes", [])
        param_value = str(params[param_name])

        # Check if value matches common mistake patterns
        for common_mistake in common_mistakes:
            if "arbitrary" in common_mistake.lower() and "ephemeral-" in param_value:
                # User provided arbitrary namespace name
                # This is a potential mistake, but we can't be 100% sure
                # Return False to avoid false positives
                # (Better to suggest checking than block incorrectly)
                return False

        # Default: Can't reliably detect incorrect parameter before execution
        return False

    def _match_workflow_sequence(self, params: dict, mistake: dict, context: dict) -> bool:
        """Check if workflow sequence error is likely.

        Args:
            params: Tool parameters
            mistake: Mistake pattern
            context: Context with recent tool calls

        Returns:
            True if sequence error likely
        """
        # Check if required prerequisite tools were called
        missing_steps = mistake.get("missing_step", [])
        if not missing_steps:
            return False

        # Get recent tool calls from context
        recent_tools = context.get("recent_tool_calls", [])

        # Check if any required prerequisite was called recently
        for required_tool in missing_steps:
            if required_tool in recent_tools:
                # Prerequisite was called, sequence is OK
                return False

        # No prerequisite found in recent calls
        logger.debug(f"Workflow sequence issue: missing prerequisite {missing_steps}, " f"recent calls: {recent_tools}")
        return True

    def _match_missing_prerequisite(self, params: dict, mistake: dict, context: dict) -> bool:
        """Check if prerequisite is likely missing.

        Args:
            params: Tool parameters
            mistake: Mistake pattern
            context: Context

        Returns:
            True if prerequisite likely missing
        """
        # Similar to workflow sequence, but more generic
        # Check context for signs of missing setup
        error_context = mistake.get("context", "")

        if "branch created but no commits" in error_context:
            # Check if branch is new
            recent_tools = context.get("recent_tool_calls", [])
            if "git_commit" not in recent_tools:
                logger.debug("Likely missing prerequisite: no commits detected")
                return True

        # Can't reliably detect before execution in most cases
        return False

    def _generate_warning(self, pattern: dict) -> str:
        """Generate human-readable warning message.

        Args:
            pattern: Pattern that matched

        Returns:
            Formatted warning string
        """
        # Confidence emoji
        confidence = pattern["confidence"]
        if confidence >= 0.95:
            emoji = "🔴"  # Very high - block
            level = "CRITICAL"
        elif confidence >= 0.85:
            emoji = "🟠"  # High - strong warning
            level = "HIGH"
        elif confidence >= 0.75:
            emoji = "🟡"  # Medium - warning
            level = "MEDIUM"
        else:
            emoji = "⚪"  # Low
            level = "LOW"

        # Build warning message
        warning = f"{emoji} **{level} CONFIDENCE WARNING** ({confidence:.0%}, {pattern['observations']} observations)\n"
        warning += f"   Tool: `{pattern['tool']}`\n"
        warning += f"   Issue: {pattern['root_cause']}\n"
        warning += "\n   Prevention steps:\n"

        for i, step in enumerate(pattern["prevention_steps"], 1):
            reason = step.get("reason", step.get("action", "Unknown"))
            warning += f"   {i}. {reason}\n"

        if confidence >= 0.95:
            warning += "\n   ⛔ **Execution blocked** to prevent known mistake (confidence >= 95%)\n"
        elif confidence >= 0.85:
            warning += "\n   ⚠️  **Strongly suggest** following prevention steps\n"

        return warning

    def get_prevention_summary(self, tool_name: str, min_confidence: float = 0.75) -> str:
        """Get a summary of prevention patterns for a tool.

        Args:
            tool_name: Tool name to get summary for
            min_confidence: Minimum confidence threshold

        Returns:
            Summary string or empty if no patterns
        """
        patterns = self.storage.get_patterns_for_tool(tool_name, min_confidence=min_confidence)

        if not patterns:
            return ""

        summary = f"## ⚠️ Known Issues for {tool_name}\n\n"
        summary += f"Found {len(patterns)} high-confidence patterns:\n\n"

        for i, pattern in enumerate(patterns, 1):
            summary += f"{i}. **{pattern['root_cause']}** ({pattern['confidence']:.0%} confidence)\n"
            summary += f"   Observations: {pattern['observations']}\n"
            if pattern.get("success_after_prevention", 0) > 0:
                success_rate = pattern["success_after_prevention"] / pattern["observations"]
                summary += f"   Prevention success rate: {success_rate:.0%}\n"
            summary += "\n"

        return summary

    def clear_cache(self):
        """Clear the pattern cache."""
        self._pattern_cache = None
        self._cache_timestamp = None
        logger.debug("Pattern cache cleared")

    def _get_cached_patterns(self, tool_name: str, min_confidence: float) -> Optional[list[dict]]:
        """Get cached patterns for a tool.

        Args:
            tool_name: Tool name
            min_confidence: Minimum confidence threshold

        Returns:
            Cached patterns or None if cache is stale/empty
        """
        # Check if cache exists and is fresh
        if self._pattern_cache is None or self._cache_timestamp is None:
            return None

        # Check if cache is expired
        age = time.time() - self._cache_timestamp
        if age > self._cache_ttl:
            logger.debug(f"Pattern cache expired (age: {age:.1f}s, TTL: {self._cache_ttl}s)")
            self.clear_cache()
            return None

        # Get patterns from cache
        cache_key = (tool_name, min_confidence)
        cached = self._pattern_cache.get(cache_key)

        if cached is not None:
            logger.debug(f"Cache hit for {tool_name} (min_conf: {min_confidence:.0%})")
        else:
            logger.debug(f"Cache miss for {tool_name} (min_conf: {min_confidence:.0%})")

        return cached

    def _cache_patterns(self, tool_name: str, min_confidence: float, patterns: list[dict]) -> None:
        """Cache patterns for a tool.

        Args:
            tool_name: Tool name
            min_confidence: Minimum confidence threshold
            patterns: Patterns to cache
        """
        # Initialize cache if needed
        if self._pattern_cache is None:
            self._pattern_cache = {}
            self._cache_timestamp = time.time()
            logger.debug("Pattern cache initialized")

        # Enforce max cache size - remove oldest entries if over limit
        if len(self._pattern_cache) >= self._max_cache_entries:
            # Remove first (oldest) entry
            oldest_key = next(iter(self._pattern_cache))
            del self._pattern_cache[oldest_key]

        # Store in cache
        cache_key = (tool_name, min_confidence)
        self._pattern_cache[cache_key] = patterns

        logger.debug(f"Cached {len(patterns)} patterns for {tool_name} " f"(min_conf: {min_confidence:.0%})")
