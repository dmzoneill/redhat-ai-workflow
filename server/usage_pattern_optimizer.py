"""
Usage Pattern Optimizer - Layer 5 Phase 5.

Handles pattern pruning, decay, and optimization.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from server.usage_pattern_storage import UsagePatternStorage

logger = logging.getLogger(__name__)


class UsagePatternOptimizer:
    """Optimize usage patterns through pruning and decay."""

    def __init__(self, storage: Optional[UsagePatternStorage] = None):
        """Initialize optimizer.

        Args:
            storage: UsagePatternStorage instance. If None, creates default.
        """
        self.storage = storage or UsagePatternStorage()

    def prune_old_patterns(
        self,
        max_age_days: int = 90,
        min_confidence: float = 0.70,
        dry_run: bool = False,
    ) -> dict:
        """Remove old patterns with low confidence.

        Args:
            max_age_days: Maximum pattern age in days (default: 90)
            min_confidence: Minimum confidence to keep (default: 0.70)
            dry_run: If True, don't actually delete, just report

        Returns:
            {
                "pruned_count": int,
                "pruned_ids": list[str],
                "reason": str
            }
        """
        data = self.storage.load()
        patterns = data.get("usage_patterns", [])

        pruned_ids = []
        now = datetime.now()
        cutoff_date = now - timedelta(days=max_age_days)

        for pattern in patterns:
            pattern_id = pattern["id"]
            confidence = pattern.get("confidence", 0)
            last_seen_str = pattern.get("last_seen")

            # Parse last_seen date
            try:
                last_seen = (
                    datetime.fromisoformat(last_seen_str) if last_seen_str else None
                )
            except (ValueError, TypeError):
                last_seen = None

            # Check if pattern should be pruned
            should_prune = False
            reason = []

            # Too old and low confidence
            if last_seen and last_seen < cutoff_date and confidence < min_confidence:
                should_prune = True
                reason.append(
                    f"old (>{max_age_days} days) and low confidence (<{min_confidence:.0%})"
                )

            # Very low confidence regardless of age
            elif confidence < 0.50:
                should_prune = True
                reason.append("very low confidence (<50%)")

            # Very low observations and low confidence
            elif pattern.get("observations", 0) < 3 and confidence < min_confidence:
                should_prune = True
                reason.append("too few observations (<3) and low confidence")

            if should_prune:
                pruned_ids.append(pattern_id)
                logger.info(
                    f"Pruning pattern {pattern_id} ({pattern['tool']}): {', '.join(reason)}"
                )

        result = {
            "pruned_count": len(pruned_ids),
            "pruned_ids": pruned_ids,
            "reason": "old and low confidence patterns",
        }

        if not dry_run and pruned_ids:
            # Actually delete the patterns
            for pattern_id in pruned_ids:
                self.storage.delete_pattern(pattern_id)

            logger.info(f"Pruned {len(pruned_ids)} patterns")
        elif dry_run and pruned_ids:
            logger.info(f"DRY RUN: Would prune {len(pruned_ids)} patterns")

        return result

    def apply_decay(
        self,
        decay_rate: float = 0.05,
        inactive_months: int = 1,
        dry_run: bool = False,
    ) -> dict:
        """Apply confidence decay to inactive patterns.

        Args:
            decay_rate: Decay rate per period (default: 0.05 = 5%)
            inactive_months: Months of inactivity before decay (default: 1)
            dry_run: If True, don't actually update, just report

        Returns:
            {
                "decayed_count": int,
                "decayed_ids": list[str],
                "avg_decay": float
            }
        """
        data = self.storage.load()
        patterns = data.get("usage_patterns", [])

        decayed_ids = []
        total_decay = 0.0
        now = datetime.now()
        inactive_cutoff = now - timedelta(days=inactive_months * 30)

        for pattern in patterns:
            pattern_id = pattern["id"]
            confidence = pattern.get("confidence", 0)
            last_seen_str = pattern.get("last_seen")

            # Parse last_seen date
            try:
                last_seen = (
                    datetime.fromisoformat(last_seen_str) if last_seen_str else None
                )
            except (ValueError, TypeError):
                last_seen = None

            # Check if pattern is inactive
            if last_seen and last_seen < inactive_cutoff:
                # Calculate decay
                months_inactive = (now - last_seen).days / 30
                decay_periods = max(1, int(months_inactive / inactive_months))
                total_decay_amount = min(decay_rate * decay_periods, confidence - 0.50)

                if total_decay_amount > 0:
                    new_confidence = confidence - total_decay_amount
                    decayed_ids.append(pattern_id)
                    total_decay += total_decay_amount

                    logger.info(
                        f"Decaying pattern {pattern_id} ({pattern['tool']}): "
                        f"{confidence:.0%} -> {new_confidence:.0%} "
                        f"(inactive for {months_inactive:.1f} months)"
                    )

                    if not dry_run:
                        # Update pattern confidence
                        self.storage.update_pattern(
                            pattern_id,
                            {
                                "confidence": new_confidence,
                                "decay_applied": now.isoformat(),
                            },
                        )

        result = {
            "decayed_count": len(decayed_ids),
            "decayed_ids": decayed_ids,
            "avg_decay": total_decay / len(decayed_ids) if decayed_ids else 0.0,
        }

        if not dry_run and decayed_ids:
            logger.info(
                f"Applied decay to {len(decayed_ids)} patterns "
                f"(avg: {result['avg_decay']:.1%})"
            )
        elif dry_run and decayed_ids:
            logger.info(
                f"DRY RUN: Would decay {len(decayed_ids)} patterns "
                f"(avg: {result['avg_decay']:.1%})"
            )

        return result

    def optimize(
        self,
        prune_old: bool = True,
        apply_decay: bool = True,
        max_age_days: int = 90,
        min_confidence: float = 0.70,
        decay_rate: float = 0.05,
        inactive_months: int = 1,
        dry_run: bool = False,
    ) -> dict:
        """Run full optimization (prune + decay).

        Args:
            prune_old: Whether to prune old patterns
            apply_decay: Whether to apply decay
            max_age_days: Maximum pattern age in days
            min_confidence: Minimum confidence to keep
            decay_rate: Decay rate per period (5% = 0.05)
            inactive_months: Months of inactivity before decay
            dry_run: If True, don't actually change anything

        Returns:
            {
                "pruned": dict,
                "decayed": dict,
                "total_optimized": int
            }
        """
        result = {
            "pruned": {"pruned_count": 0, "pruned_ids": []},
            "decayed": {"decayed_count": 0, "decayed_ids": []},
            "total_optimized": 0,
        }

        # Apply decay first (before pruning)
        if apply_decay:
            result["decayed"] = self.apply_decay(
                decay_rate=decay_rate,
                inactive_months=inactive_months,
                dry_run=dry_run,
            )

        # Then prune old patterns
        if prune_old:
            result["pruned"] = self.prune_old_patterns(
                max_age_days=max_age_days,
                min_confidence=min_confidence,
                dry_run=dry_run,
            )

        result["total_optimized"] = result["pruned"].get("pruned_count", 0) + result[
            "decayed"
        ].get("decayed_count", 0)

        logger.info(
            f"Optimization complete: {result['total_optimized']} patterns optimized "
            f"({result['pruned'].get('pruned_count', 0)} pruned, "
            f"{result['decayed'].get('decayed_count', 0)} decayed)"
        )

        return result

    def get_optimization_stats(self) -> dict:
        """Get statistics about patterns that could be optimized.

        Returns:
            {
                "total_patterns": int,
                "old_patterns": int,  # >90 days old
                "low_confidence": int,  # <70%
                "inactive_patterns": int,  # not seen in 30 days
                "candidates_for_pruning": int,
                "candidates_for_decay": int
            }
        """
        data = self.storage.load()
        patterns = data.get("usage_patterns", [])

        now = datetime.now()
        old_cutoff = now - timedelta(days=90)
        inactive_cutoff = now - timedelta(days=30)

        stats = {
            "total_patterns": len(patterns),
            "old_patterns": 0,
            "low_confidence": 0,
            "inactive_patterns": 0,
            "candidates_for_pruning": 0,
            "candidates_for_decay": 0,
        }

        for pattern in patterns:
            confidence = pattern.get("confidence", 0)
            last_seen_str = pattern.get("last_seen")

            try:
                last_seen = (
                    datetime.fromisoformat(last_seen_str) if last_seen_str else None
                )
            except (ValueError, TypeError):
                last_seen = None

            # Count old patterns
            if last_seen and last_seen < old_cutoff:
                stats["old_patterns"] += 1

            # Count low confidence
            if confidence < 0.70:
                stats["low_confidence"] += 1

            # Count inactive
            if last_seen and last_seen < inactive_cutoff:
                stats["inactive_patterns"] += 1

            # Candidates for pruning (old AND low confidence)
            if last_seen and last_seen < old_cutoff and confidence < 0.70:
                stats["candidates_for_pruning"] += 1

            # Candidates for decay (inactive)
            if last_seen and last_seen < inactive_cutoff:
                stats["candidates_for_decay"] += 1

        return stats
