"""
Usage Pattern Learner - Layer 5 of Auto-Heal System.

This module learns from tool failures and updates patterns with confidence evolution.

Part of Layer 5: Usage Pattern Learning - Phase 2
"""

import logging
from datetime import datetime
from difflib import SequenceMatcher
from typing import Optional

from server.usage_pattern_classifier import classify_error_type, is_learnable_error
from server.usage_pattern_extractor import extract_usage_pattern
from server.usage_pattern_storage import UsagePatternStorage

logger = logging.getLogger(__name__)


class UsagePatternLearner:
    """Learn and update usage patterns from observations."""

    def __init__(self, storage: Optional[UsagePatternStorage] = None):
        """Initialize learner.

        Args:
            storage: UsagePatternStorage instance. If None, creates default.
        """
        self.storage = storage or UsagePatternStorage()

    async def analyze_result(
        self,
        tool_name: str,
        params: dict,
        result: str,
        context: Optional[dict] = None,
    ) -> Optional[dict]:
        """Analyze tool result for usage errors and learn.

        Args:
            tool_name: Name of tool that was called
            params: Parameters that were passed
            result: Result/output from the tool
            context: Additional context (previous tool calls, etc.)

        Returns:
            Pattern dict if learned, None if not a usage error
        """
        if context is None:
            context = {}

        # Step 1: Classify error
        classification = classify_error_type(
            tool_name=tool_name,
            params=params,
            error_message=result,
            result=result,
        )

        if not classification["is_usage_error"]:
            logger.debug(f"Not a usage error for {tool_name}, skipping learning")
            return None

        if not is_learnable_error(classification):
            logger.debug(f"Error not learnable for {tool_name}, skipping")
            return None

        logger.info(
            f"Usage error detected: {tool_name} - {classification['error_category']} "
            f"(confidence: {classification['confidence']:.0%})"
        )

        # Step 2: Extract pattern
        new_pattern = extract_usage_pattern(
            tool_name=tool_name,
            params=params,
            error_message=result,
            classification=classification,
            context=context,
        )

        # Step 3: Merge with existing patterns or add new
        merged_pattern = await self._merge_or_add_pattern(new_pattern)

        logger.info(
            f"Pattern updated: {merged_pattern['id']} "
            f"(obs: {merged_pattern['observations']}, conf: {merged_pattern['confidence']:.0%})"
        )

        return merged_pattern

    async def _merge_or_add_pattern(self, new_pattern: dict) -> dict:
        """Merge with existing pattern or add new.

        Args:
            new_pattern: New pattern to merge or add

        Returns:
            The merged or added pattern
        """
        data = self.storage.load()
        existing_patterns = data.get("usage_patterns", [])

        # Find similar pattern (70% similarity threshold)
        similar = None
        max_similarity = 0.0

        for existing in existing_patterns:
            # Must be same tool and category
            if existing["tool"] != new_pattern["tool"]:
                continue

            if existing["error_category"] != new_pattern["error_category"]:
                continue

            # Calculate similarity
            similarity = self._calculate_similarity(existing, new_pattern)

            if similarity > max_similarity and similarity >= 0.70:
                max_similarity = similarity
                similar = existing

        if similar:
            # Merge with existing
            logger.debug(
                f"Merging pattern (similarity: {max_similarity:.0%}): "
                f"{similar['id']} + {new_pattern['id']}"
            )
            merged = await self._merge_patterns(similar, new_pattern)
            self.storage.save(data)
            return merged
        else:
            # Add as new pattern
            logger.debug(f"Adding new pattern: {new_pattern['id']}")
            existing_patterns.append(new_pattern)
            data["usage_patterns"] = existing_patterns
            self.storage.save(data)
            return new_pattern

    async def _merge_patterns(self, existing: dict, new: dict) -> dict:
        """Merge new observation into existing pattern.

        Args:
            existing: Existing pattern to merge into
            new: New pattern to merge from

        Returns:
            The merged pattern (existing, modified in place)
        """
        # Increment observations
        existing["observations"] += 1

        # Update last_seen
        existing["last_seen"] = datetime.now().isoformat()

        # Merge common mistakes
        if "common_mistakes" in new["mistake_pattern"]:
            if "common_mistakes" not in existing["mistake_pattern"]:
                existing["mistake_pattern"]["common_mistakes"] = []

            for mistake in new["mistake_pattern"]["common_mistakes"]:
                if mistake not in existing["mistake_pattern"]["common_mistakes"]:
                    existing["mistake_pattern"]["common_mistakes"].append(mistake)

        # Update confidence
        existing["confidence"] = self._calculate_confidence(existing)

        logger.debug(
            f"Pattern merged: {existing['id']} - "
            f"obs: {existing['observations']}, conf: {existing['confidence']:.0%}"
        )

        return existing

    def _calculate_confidence(self, pattern: dict) -> float:
        """Calculate confidence score based on observations and success rate.

        Confidence evolution:
        - 1-2 obs: 50%
        - 3-4 obs: 60%
        - 5-9 obs: 70%
        - 10-19 obs: 75%
        - 20-44 obs: 85%
        - 45-99 obs: 92%
        - 100+ obs: 95%

        Adjusted by success rate (if prevention was attempted).

        Args:
            pattern: Pattern dict with observations and success_after_prevention

        Returns:
            Confidence score (0.0-0.99)
        """
        obs = pattern["observations"]
        success = pattern.get("success_after_prevention", 0)

        # Base confidence from observation count
        if obs >= 100:
            base = 0.95
        elif obs >= 45:
            base = 0.92
        elif obs >= 20:
            base = 0.85
        elif obs >= 10:
            base = 0.75
        elif obs >= 5:
            base = 0.70
        elif obs >= 3:
            base = 0.60
        else:
            base = 0.50

        # Adjust by success rate (if we have prevention attempts)
        if obs > 0 and success > 0:
            success_rate = success / obs
            # Weight: 70% base, 30% success rate
            final = (base * 0.7) + (success_rate * 0.3)
        else:
            final = base

        return min(final, 0.99)  # Cap at 99%

    def _calculate_similarity(self, p1: dict, p2: dict) -> float:
        """Calculate similarity between two patterns (0.0-1.0).

        Args:
            p1: First pattern
            p2: Second pattern

        Returns:
            Similarity score (0.0-1.0)
        """
        score = 0.0
        weights = {
            "error_regex": 0.4,
            "parameter": 0.3,
            "root_cause": 0.2,
            "prevention_steps": 0.1,
        }

        # Compare error regex
        regex1 = p1["mistake_pattern"].get("error_regex", "")
        regex2 = p2["mistake_pattern"].get("error_regex", "")

        if regex1 and regex2:
            if regex1 == regex2:
                score += weights["error_regex"]
            else:
                # Partial match using set overlap
                patterns1 = set(regex1.split("|"))
                patterns2 = set(regex2.split("|"))
                if patterns1 and patterns2:
                    overlap = len(patterns1 & patterns2) / max(
                        len(patterns1), len(patterns2)
                    )
                    score += weights["error_regex"] * overlap

        # Compare parameter
        param1 = p1["mistake_pattern"].get("parameter")
        param2 = p2["mistake_pattern"].get("parameter")

        if param1 and param2:
            if param1 == param2:
                score += weights["parameter"]
            else:
                # Fuzzy match for similar param names
                similarity = SequenceMatcher(None, str(param1), str(param2)).ratio()
                score += weights["parameter"] * similarity

        # Compare root cause (fuzzy)
        cause1 = p1.get("root_cause", "")
        cause2 = p2.get("root_cause", "")

        if cause1 and cause2:
            cause_sim = SequenceMatcher(None, cause1, cause2).ratio()
            score += weights["root_cause"] * cause_sim

        # Compare prevention steps count (rough indicator)
        steps1 = len(p1.get("prevention_steps", []))
        steps2 = len(p2.get("prevention_steps", []))

        if steps1 > 0 and steps2 > 0:
            steps_sim = min(steps1, steps2) / max(steps1, steps2)
            score += weights["prevention_steps"] * steps_sim

        return score

    async def record_prevention_success(self, pattern_id: str) -> bool:
        """Record that a prevention was successful.

        This should be called when a pattern warning was shown and
        the user followed the prevention steps successfully.

        Args:
            pattern_id: ID of pattern that was used for prevention

        Returns:
            True if updated successfully
        """
        pattern = self.storage.get_pattern(pattern_id)
        if not pattern:
            logger.warning(f"Pattern {pattern_id} not found for success recording")
            return False

        # Increment success counter
        success = pattern.get("success_after_prevention", 0)
        updates = {
            "success_after_prevention": success + 1,
        }

        # Recalculate confidence
        pattern.update(updates)
        updates["confidence"] = self._calculate_confidence(pattern)

        success = self.storage.update_pattern(pattern_id, updates)

        if success:
            logger.info(
                f"Recorded prevention success for {pattern_id} "
                f"(new conf: {updates['confidence']:.0%})"
            )

        return success

    async def record_prevention_failure(
        self, pattern_id: str, reason: str = ""
    ) -> bool:
        """Record that a prevention failed (false positive).

        This should be called when a pattern warning was shown but was
        incorrect or not helpful.

        Args:
            pattern_id: ID of pattern that failed
            reason: Optional reason for failure

        Returns:
            True if updated successfully
        """
        pattern = self.storage.get_pattern(pattern_id)
        if not pattern:
            logger.warning(f"Pattern {pattern_id} not found for failure recording")
            return False

        # Reduce confidence slightly for false positives
        current_conf = pattern.get("confidence", 0.5)
        new_conf = max(current_conf - 0.05, 0.3)  # Reduce by 5%, floor at 30%

        updates = {
            "confidence": new_conf,
        }

        success = self.storage.update_pattern(pattern_id, updates)

        if success:
            logger.warning(
                f"Recorded prevention failure for {pattern_id}: {reason} "
                f"(conf: {current_conf:.0%} → {new_conf:.0%})"
            )

        return success

    def get_learning_stats(self) -> dict:
        """Get learning statistics.

        Returns:
            Stats dict with learning metrics
        """
        data = self.storage.load()
        patterns = data.get("usage_patterns", [])
        stats = data.get("stats", {})

        # Calculate additional metrics
        total_obs = sum(p.get("observations", 0) for p in patterns)
        total_success = sum(p.get("success_after_prevention", 0) for p in patterns)

        avg_confidence = (
            sum(p.get("confidence", 0.0) for p in patterns) / len(patterns)
            if patterns
            else 0.0
        )

        return {
            "total_patterns": len(patterns),
            "total_observations": total_obs,
            "total_preventions_successful": total_success,
            "average_confidence": avg_confidence,
            "high_confidence_patterns": stats.get("high_confidence", 0),
            "medium_confidence_patterns": stats.get("medium_confidence", 0),
            "low_confidence_patterns": stats.get("low_confidence", 0),
            "prevention_success_rate": stats.get("prevention_success_rate", 0.0),
            "by_category": stats.get("by_category", {}),
        }
