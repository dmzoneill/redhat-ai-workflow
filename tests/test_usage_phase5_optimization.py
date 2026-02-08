"""
Tests for Layer 5 Phase 5: Optimization.

Tests pattern caching, pruning, decay, and optimization.
"""

import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from server.usage_pattern_checker import UsagePatternChecker
from server.usage_pattern_optimizer import UsagePatternOptimizer
from server.usage_pattern_storage import UsagePatternStorage


@pytest.fixture
def temp_storage():
    """Create temporary storage for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        patterns_file = Path(tmpdir) / "usage_patterns.yaml"
        storage = UsagePatternStorage(patterns_file)
        yield storage


@pytest.fixture
def old_pattern(temp_storage):
    """Create an old, low-confidence pattern for testing."""
    old_date = (datetime.now() - timedelta(days=100)).isoformat()

    pattern = {
        "id": "old_pattern_test",
        "tool": "test_tool",
        "error_category": "PARAMETER_FORMAT",
        "mistake_pattern": {},
        "root_cause": "Old issue",
        "prevention_steps": [],
        "observations": 5,
        "confidence": 0.65,  # Low confidence
        "first_seen": old_date,
        "last_seen": old_date,
    }

    temp_storage.add_pattern(pattern)
    return pattern


@pytest.fixture
def recent_pattern(temp_storage):
    """Create a recent, high-confidence pattern for testing."""
    recent_date = (datetime.now() - timedelta(days=1)).isoformat()

    pattern = {
        "id": "recent_pattern_test",
        "tool": "test_tool",
        "error_category": "PARAMETER_FORMAT",
        "mistake_pattern": {},
        "root_cause": "Recent issue",
        "prevention_steps": [],
        "observations": 50,
        "confidence": 0.95,  # High confidence
        "first_seen": recent_date,
        "last_seen": recent_date,
    }

    temp_storage.add_pattern(pattern)
    return pattern


@pytest.fixture
def inactive_pattern(temp_storage):
    """Create an inactive pattern for decay testing."""
    inactive_date = (datetime.now() - timedelta(days=45)).isoformat()

    pattern = {
        "id": "inactive_pattern_test",
        "tool": "test_tool",
        "error_category": "PARAMETER_FORMAT",
        "mistake_pattern": {},
        "root_cause": "Inactive issue",
        "prevention_steps": [],
        "observations": 20,
        "confidence": 0.85,
        "first_seen": inactive_date,
        "last_seen": inactive_date,
    }

    temp_storage.add_pattern(pattern)
    return pattern


class TestPatternCaching:
    """Test pattern caching functionality."""

    def test_cache_enabled_by_default(self):
        """Should enable caching by default."""
        checker = UsagePatternChecker()
        assert checker._cache_ttl == 300  # 5 minutes default

    def test_cache_miss_on_first_call(self, temp_storage, recent_pattern):
        """Should have cache miss on first call."""
        checker = UsagePatternChecker(storage=temp_storage)

        # First call - cache miss (will load from storage)
        checker.check_before_call(
            tool_name="test_tool",
            params={},
            min_confidence=0.75,
        )

        # Cache should now be populated
        assert checker._pattern_cache is not None
        assert checker._cache_timestamp is not None

    def test_cache_hit_on_second_call(self, temp_storage, recent_pattern):
        """Should have cache hit on second call."""
        checker = UsagePatternChecker(storage=temp_storage)

        # First call - cache miss
        checker.check_before_call(
            tool_name="test_tool",
            params={},
            min_confidence=0.75,
        )

        # Second call - should hit cache
        cache_timestamp_before = checker._cache_timestamp

        checker.check_before_call(
            tool_name="test_tool",
            params={},
            min_confidence=0.75,
        )

        # Cache timestamp should not change (cache was used)
        assert checker._cache_timestamp == cache_timestamp_before

    def test_cache_expiry(self, temp_storage, recent_pattern):
        """Should expire cache after TTL."""
        checker = UsagePatternChecker(storage=temp_storage, cache_ttl=1)  # 1 second TTL

        fake_time = 1000.0

        with patch("server.usage_pattern_checker.time") as mock_time:
            mock_time.time.return_value = fake_time

            # First call - populates cache at fake_time=1000
            checker.check_before_call(
                tool_name="test_tool",
                params={},
                min_confidence=0.75,
            )

            cache_timestamp_before = checker._cache_timestamp

            # Advance time past TTL (1s TTL + 0.1s buffer)
            mock_time.time.return_value = fake_time + 1.1

            # Second call - cache should be expired
            checker.check_before_call(
                tool_name="test_tool",
                params={},
                min_confidence=0.75,
            )

            # Cache should have been refreshed (new timestamp)
            assert checker._cache_timestamp > cache_timestamp_before

    def test_clear_cache(self, temp_storage, recent_pattern):
        """Should clear cache when requested."""
        checker = UsagePatternChecker(storage=temp_storage)

        # Populate cache
        checker.check_before_call(tool_name="test_tool", params={})

        assert checker._pattern_cache is not None

        # Clear cache
        checker.clear_cache()

        assert checker._pattern_cache is None
        assert checker._cache_timestamp is None


class TestPatternPruning:
    """Test pattern pruning functionality."""

    def test_prune_old_low_confidence(self, temp_storage, old_pattern, recent_pattern):
        """Should prune old low-confidence patterns."""
        optimizer = UsagePatternOptimizer(storage=temp_storage)

        result = optimizer.prune_old_patterns(
            max_age_days=90,
            min_confidence=0.70,
            dry_run=False,
        )

        # Should prune the old pattern (100 days old, 65% confidence)
        assert result["pruned_count"] == 1
        assert old_pattern["id"] in result["pruned_ids"]

        # Verify pattern was actually deleted
        remaining = temp_storage.get_pattern(old_pattern["id"])
        assert remaining is None

        # Recent pattern should still exist
        remaining_recent = temp_storage.get_pattern(recent_pattern["id"])
        assert remaining_recent is not None

    def test_keep_recent_patterns(self, temp_storage, recent_pattern):
        """Should keep recent patterns regardless of confidence."""
        optimizer = UsagePatternOptimizer(storage=temp_storage)

        result = optimizer.prune_old_patterns(
            max_age_days=90,
            min_confidence=0.70,
            dry_run=False,
        )

        # Should not prune recent pattern
        assert result["pruned_count"] == 0

    def test_dry_run_no_changes(self, temp_storage, old_pattern):
        """Should not make changes in dry run mode."""
        optimizer = UsagePatternOptimizer(storage=temp_storage)

        result = optimizer.prune_old_patterns(
            max_age_days=90,
            min_confidence=0.70,
            dry_run=True,
        )

        # Should identify pattern for pruning
        assert result["pruned_count"] == 1

        # But pattern should still exist
        remaining = temp_storage.get_pattern(old_pattern["id"])
        assert remaining is not None

    def test_prune_very_low_confidence(self, temp_storage):
        """Should prune very low confidence patterns regardless of age."""
        # Add very low confidence pattern (recent)
        recent_date = datetime.now().isoformat()
        pattern = {
            "id": "very_low_conf_test",
            "tool": "test_tool",
            "error_category": "PARAMETER_FORMAT",
            "mistake_pattern": {},
            "root_cause": "Very unreliable",
            "prevention_steps": [],
            "observations": 10,
            "confidence": 0.45,  # Very low
            "first_seen": recent_date,
            "last_seen": recent_date,
        }
        temp_storage.add_pattern(pattern)

        optimizer = UsagePatternOptimizer(storage=temp_storage)

        result = optimizer.prune_old_patterns(dry_run=False)

        # Should prune the very low confidence pattern
        assert result["pruned_count"] == 1
        assert pattern["id"] in result["pruned_ids"]


class TestPatternDecay:
    """Test pattern decay functionality."""

    def test_decay_inactive_patterns(self, temp_storage, inactive_pattern):
        """Should apply decay to inactive patterns."""
        optimizer = UsagePatternOptimizer(storage=temp_storage)

        original_confidence = inactive_pattern["confidence"]

        result = optimizer.apply_decay(
            decay_rate=0.05,
            inactive_months=1,
            dry_run=False,
        )

        # Should decay the inactive pattern (45 days old)
        assert result["decayed_count"] == 1
        assert inactive_pattern["id"] in result["decayed_ids"]

        # Check that confidence was actually reduced
        updated = temp_storage.get_pattern(inactive_pattern["id"])
        assert updated["confidence"] < original_confidence

    def test_no_decay_recent_patterns(self, temp_storage, recent_pattern):
        """Should not decay recent patterns."""
        optimizer = UsagePatternOptimizer(storage=temp_storage)

        result = optimizer.apply_decay(
            decay_rate=0.05,
            inactive_months=1,
            dry_run=False,
        )

        # Should not decay recent pattern (1 day old)
        assert result["decayed_count"] == 0

    def test_decay_dry_run(self, temp_storage, inactive_pattern):
        """Should not make changes in dry run mode."""
        optimizer = UsagePatternOptimizer(storage=temp_storage)

        original_confidence = inactive_pattern["confidence"]

        result = optimizer.apply_decay(
            decay_rate=0.05,
            inactive_months=1,
            dry_run=True,
        )

        # Should identify pattern for decay
        assert result["decayed_count"] == 1

        # But confidence should not have changed
        updated = temp_storage.get_pattern(inactive_pattern["id"])
        assert updated["confidence"] == original_confidence

    def test_decay_multiple_periods(self, temp_storage):
        """Should apply multiple decay periods for very old patterns."""
        # Add pattern that's 3 months old
        old_date = (datetime.now() - timedelta(days=90)).isoformat()
        pattern = {
            "id": "very_old_test",
            "tool": "test_tool",
            "error_category": "PARAMETER_FORMAT",
            "mistake_pattern": {},
            "root_cause": "Very old",
            "prevention_steps": [],
            "observations": 20,
            "confidence": 0.90,
            "first_seen": old_date,
            "last_seen": old_date,
        }
        temp_storage.add_pattern(pattern)

        optimizer = UsagePatternOptimizer(storage=temp_storage)

        result = optimizer.apply_decay(
            decay_rate=0.05,  # 5% per month
            inactive_months=1,
            dry_run=False,
        )

        # Should apply decay (3 periods of 5% = 15% total)
        assert result["decayed_count"] == 1

        updated = temp_storage.get_pattern(pattern["id"])
        # Confidence should be reduced by ~15%
        assert updated["confidence"] < 0.80  # Started at 90%, decayed ~15%
        assert updated["confidence"] > 0.70  # But capped at 50% minimum


class TestOptimizationStats:
    """Test optimization statistics."""

    def test_get_optimization_stats(
        self, temp_storage, old_pattern, recent_pattern, inactive_pattern
    ):
        """Should calculate optimization stats correctly."""
        optimizer = UsagePatternOptimizer(storage=temp_storage)

        stats = optimizer.get_optimization_stats()

        assert stats["total_patterns"] == 3
        assert stats["old_patterns"] >= 1  # old_pattern is >90 days
        assert stats["low_confidence"] >= 1  # old_pattern is <70%
        assert stats["inactive_patterns"] >= 1  # inactive_pattern is >30 days
        assert stats["candidates_for_pruning"] >= 1  # old + low conf
        assert stats["candidates_for_decay"] >= 1  # inactive

    def test_empty_stats(self, temp_storage):
        """Should handle empty pattern list."""
        optimizer = UsagePatternOptimizer(storage=temp_storage)

        stats = optimizer.get_optimization_stats()

        assert stats["total_patterns"] == 0
        assert stats["old_patterns"] == 0
        assert stats["low_confidence"] == 0


class TestFullOptimization:
    """Test full optimization (prune + decay)."""

    def test_optimize_all(
        self, temp_storage, old_pattern, inactive_pattern, recent_pattern
    ):
        """Should run both pruning and decay."""
        optimizer = UsagePatternOptimizer(storage=temp_storage)

        result = optimizer.optimize(
            prune_old=True,
            apply_decay=True,
            dry_run=False,
        )

        # Should have optimized at least 1 pattern (decayed and/or pruned)
        assert result["total_optimized"] >= 1
        # At minimum, the inactive pattern should be decayed
        assert result["decayed"]["decayed_count"] >= 1

    def test_optimize_prune_only(self, temp_storage, old_pattern, inactive_pattern):
        """Should only prune when decay disabled."""
        optimizer = UsagePatternOptimizer(storage=temp_storage)

        result = optimizer.optimize(
            prune_old=True,
            apply_decay=False,
            dry_run=False,
        )

        assert result["pruned"]["pruned_count"] >= 1
        assert result["decayed"]["decayed_count"] == 0

    def test_optimize_decay_only(self, temp_storage, old_pattern, inactive_pattern):
        """Should only decay when pruning disabled."""
        optimizer = UsagePatternOptimizer(storage=temp_storage)

        result = optimizer.optimize(
            prune_old=False,
            apply_decay=True,
            dry_run=False,
        )

        assert result["pruned"]["pruned_count"] == 0
        assert result["decayed"]["decayed_count"] >= 1
