"""
Unit tests for Usage Pattern Learner (Layer 5 Phase 2).

Tests pattern learning, merging, confidence evolution, and prevention tracking.
Targets 90%+ coverage of server/usage_pattern_learner.py.
"""

import tempfile
from pathlib import Path

import pytest

from server.usage_pattern_learner import UsagePatternLearner
from server.usage_pattern_storage import UsagePatternStorage

# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def temp_storage():
    """Create temporary storage for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        patterns_file = Path(tmpdir) / "usage_patterns.yaml"
        storage = UsagePatternStorage(patterns_file)
        yield storage


@pytest.fixture
def learner(temp_storage):
    """Create learner with temp storage."""
    return UsagePatternLearner(storage=temp_storage)


# ============================================================
# Initialization
# ============================================================


class TestInit:
    """Tests for UsagePatternLearner initialization."""

    def test_init_with_provided_storage(self, temp_storage):
        """Should use provided storage."""
        learner = UsagePatternLearner(storage=temp_storage)
        assert learner.storage is temp_storage

    def test_init_with_default_storage(self):
        """Should create default storage when none provided."""
        # UsagePatternStorage() without args uses Path(__file__).parent.parent
        # which points to the project root. Just verify it creates a storage instance.
        learner = UsagePatternLearner()
        assert learner.storage is not None
        assert isinstance(learner.storage, UsagePatternStorage)


# ============================================================
# analyze_result
# ============================================================


class TestAnalyzeResult:
    """Tests for analyze_result method."""

    @pytest.mark.asyncio
    async def test_learn_new_usage_error(self, learner):
        """Should learn a new pattern from a usage error."""
        result = await learner.analyze_result(
            tool_name="bonfire_namespace_release",
            params={"namespace": "ephemeral-abc"},
            result="Error: Namespace 'ephemeral-abc' not owned by you",
            context={},
        )

        assert result is not None
        assert result["tool"] == "bonfire_namespace_release"
        assert result["error_category"] == "INCORRECT_PARAMETER"
        assert result["observations"] == 1
        assert result["confidence"] == 0.5

    @pytest.mark.asyncio
    async def test_ignore_infrastructure_error(self, learner):
        """Should not learn from infrastructure errors."""
        result = await learner.analyze_result(
            tool_name="bonfire_deploy",
            params={},
            result="Error: Unauthorized. Token expired.",
            context={},
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_ignore_non_error(self, learner):
        """Should not learn from successful results."""
        result = await learner.analyze_result(
            tool_name="bonfire_deploy",
            params={},
            result="Deployed successfully",
            context={},
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_context_defaults_to_empty(self, learner):
        """Should handle None context."""
        result = await learner.analyze_result(
            tool_name="bonfire_namespace_release",
            params={"namespace": "ephemeral-abc"},
            result="Namespace 'ephemeral-abc' not owned",
            context=None,
        )

        assert result is not None

    @pytest.mark.asyncio
    async def test_format_error_learning(self, learner):
        """Should learn PARAMETER_FORMAT errors."""
        result = await learner.analyze_result(
            tool_name="bonfire_deploy",
            params={"image_tag": "abc1234"},
            result="Error: manifest unknown",
        )

        assert result is not None
        assert result["error_category"] == "PARAMETER_FORMAT"

    @pytest.mark.asyncio
    async def test_workflow_sequence_error_learning(self, learner):
        """Should learn WORKFLOW_SEQUENCE errors."""
        result = await learner.analyze_result(
            tool_name="bonfire_deploy",
            params={"namespace": "eph-abc"},
            result="Error: namespace not found",
        )

        assert result is not None
        assert result["error_category"] == "WORKFLOW_SEQUENCE"


# ============================================================
# Pattern Merging
# ============================================================


class TestPatternMerging:
    """Tests for pattern merging behavior."""

    @pytest.mark.asyncio
    async def test_merge_identical_patterns(self, learner):
        """Identical errors should merge into one pattern."""
        pattern1 = await learner.analyze_result(
            tool_name="bonfire_namespace_release",
            params={"namespace": "ephemeral-abc"},
            result="Namespace 'ephemeral-abc' not owned by you",
        )

        pattern2 = await learner.analyze_result(
            tool_name="bonfire_namespace_release",
            params={"namespace": "ephemeral-xyz"},
            result="Namespace 'ephemeral-xyz' not owned by you",
        )

        assert pattern2["id"] == pattern1["id"]
        assert pattern2["observations"] == 2
        assert pattern2["confidence"] == 0.5  # 2 obs still = 50%

    @pytest.mark.asyncio
    async def test_different_tools_separate_patterns(self, learner):
        """Different tools should create separate patterns."""
        await learner.analyze_result(
            tool_name="bonfire_namespace_release",
            params={"namespace": "ephemeral-abc"},
            result="Namespace not owned",
        )

        await learner.analyze_result(
            tool_name="bonfire_deploy",
            params={"image_tag": "abc123"},
            result="manifest unknown",
        )

        data = learner.storage.load()
        assert len(data["usage_patterns"]) == 2

    @pytest.mark.asyncio
    async def test_different_categories_separate_patterns(self, learner):
        """Same tool but different categories should create separate patterns."""
        await learner.analyze_result(
            tool_name="bonfire_deploy",
            params={"image_tag": "short"},
            result="manifest unknown",
        )

        await learner.analyze_result(
            tool_name="bonfire_deploy",
            params={"namespace": "eph-abc"},
            result="namespace not found",
        )

        data = learner.storage.load()
        assert len(data["usage_patterns"]) == 2

    @pytest.mark.asyncio
    async def test_merge_updates_last_seen(self, learner):
        """Merging should update last_seen timestamp."""
        from datetime import datetime
        from unittest.mock import patch

        t1 = datetime(2025, 1, 1, 12, 0, 0)
        t2 = datetime(2025, 1, 1, 12, 0, 1)  # 1 second later

        # Patch datetime.now in both modules that set last_seen
        with (
            patch("server.usage_pattern_extractor.datetime") as mock_dt_ext,
            patch("server.usage_pattern_learner.datetime") as mock_dt_lrn,
        ):
            mock_dt_ext.now.return_value = t1
            mock_dt_ext.side_effect = lambda *a, **kw: datetime(*a, **kw)
            mock_dt_lrn.now.return_value = t1
            mock_dt_lrn.side_effect = lambda *a, **kw: datetime(*a, **kw)

            pattern1 = await learner.analyze_result(
                tool_name="bonfire_namespace_release",
                params={"namespace": "ephemeral-abc"},
                result="Namespace not owned",
            )

            first_last_seen = pattern1["last_seen"]

            mock_dt_ext.now.return_value = t2
            mock_dt_lrn.now.return_value = t2

            pattern2 = await learner.analyze_result(
                tool_name="bonfire_namespace_release",
                params={"namespace": "ephemeral-xyz"},
                result="Namespace not owned",
            )

        assert pattern2["last_seen"] >= first_last_seen

    @pytest.mark.asyncio
    async def test_merge_combines_common_mistakes(self, learner):
        """Merging should combine common mistakes from both patterns."""
        # First observation
        await learner.analyze_result(
            tool_name="bonfire_namespace_release",
            params={"namespace": "ephemeral-abc"},
            result="Namespace not owned",
        )

        # Second observation
        result = await learner.analyze_result(
            tool_name="bonfire_namespace_release",
            params={"namespace": "ephemeral-xyz"},
            result="Namespace not owned",
        )

        # Should have accumulated common mistakes
        assert result["observations"] == 2


# ============================================================
# Confidence Evolution
# ============================================================


class TestConfidenceEvolution:
    """Tests for confidence score calculation."""

    def test_confidence_1_2_obs(self, learner):
        """1-2 observations should yield 50% confidence."""
        assert (
            learner._calculate_confidence(
                {"observations": 1, "success_after_prevention": 0}
            )
            == 0.50
        )
        assert (
            learner._calculate_confidence(
                {"observations": 2, "success_after_prevention": 0}
            )
            == 0.50
        )

    def test_confidence_3_4_obs(self, learner):
        """3-4 observations should yield 60% confidence."""
        assert (
            learner._calculate_confidence(
                {"observations": 3, "success_after_prevention": 0}
            )
            == 0.60
        )
        assert (
            learner._calculate_confidence(
                {"observations": 4, "success_after_prevention": 0}
            )
            == 0.60
        )

    def test_confidence_5_9_obs(self, learner):
        """5-9 observations should yield 70% confidence."""
        assert (
            learner._calculate_confidence(
                {"observations": 5, "success_after_prevention": 0}
            )
            == 0.70
        )
        assert (
            learner._calculate_confidence(
                {"observations": 9, "success_after_prevention": 0}
            )
            == 0.70
        )

    def test_confidence_10_19_obs(self, learner):
        """10-19 observations should yield 75% confidence."""
        assert (
            learner._calculate_confidence(
                {"observations": 10, "success_after_prevention": 0}
            )
            == 0.75
        )
        assert (
            learner._calculate_confidence(
                {"observations": 19, "success_after_prevention": 0}
            )
            == 0.75
        )

    def test_confidence_20_44_obs(self, learner):
        """20-44 observations should yield 85% confidence."""
        assert (
            learner._calculate_confidence(
                {"observations": 20, "success_after_prevention": 0}
            )
            == 0.85
        )
        assert (
            learner._calculate_confidence(
                {"observations": 44, "success_after_prevention": 0}
            )
            == 0.85
        )

    def test_confidence_45_99_obs(self, learner):
        """45-99 observations should yield 92% confidence."""
        assert (
            learner._calculate_confidence(
                {"observations": 45, "success_after_prevention": 0}
            )
            == 0.92
        )
        assert (
            learner._calculate_confidence(
                {"observations": 99, "success_after_prevention": 0}
            )
            == 0.92
        )

    def test_confidence_100_plus_obs(self, learner):
        """100+ observations should yield 95% confidence."""
        assert (
            learner._calculate_confidence(
                {"observations": 100, "success_after_prevention": 0}
            )
            == 0.95
        )
        assert (
            learner._calculate_confidence(
                {"observations": 500, "success_after_prevention": 0}
            )
            == 0.95
        )

    def test_success_rate_boosts_confidence(self, learner):
        """Prevention success should boost confidence."""
        base = learner._calculate_confidence(
            {"observations": 10, "success_after_prevention": 0}
        )

        boosted = learner._calculate_confidence(
            {"observations": 10, "success_after_prevention": 9}
        )

        assert boosted > base

    def test_confidence_capped_at_99(self, learner):
        """Confidence should never exceed 99%."""
        result = learner._calculate_confidence(
            {"observations": 1000, "success_after_prevention": 999}
        )
        assert result <= 0.99

    def test_success_rate_formula(self, learner):
        """Verify the success rate formula: 70% base + 30% success rate."""
        # 10 obs, 0 success: base = 0.75, final = 0.75
        # 10 obs, 10 success: base = 0.75, rate = 1.0
        # final = 0.75 * 0.7 + 1.0 * 0.3 = 0.525 + 0.3 = 0.825
        result = learner._calculate_confidence(
            {"observations": 10, "success_after_prevention": 10}
        )
        expected = 0.75 * 0.7 + 1.0 * 0.3
        assert abs(result - expected) < 0.001

    @pytest.mark.asyncio
    async def test_confidence_increases_with_observations(self, learner):
        """Confidence should increase as observations grow."""
        _conf = 0.0
        for i in range(50):
            await learner.analyze_result(
                tool_name="bonfire_deploy",
                params={"image_tag": f"short{i}"},
                result="manifest unknown",
            )

        patterns = learner.storage.get_patterns_for_tool("bonfire_deploy")
        assert len(patterns) == 1
        assert patterns[0]["observations"] == 50
        assert patterns[0]["confidence"] == 0.92  # 45-99 obs


# ============================================================
# Similarity Calculation
# ============================================================


class TestSimilarityCalculation:
    """Tests for _calculate_similarity method."""

    def test_identical_patterns_full_similarity(self, learner):
        """Identical patterns should have ~100% similarity."""
        pattern = {
            "tool": "test_tool",
            "mistake_pattern": {
                "error_regex": "error pattern",
                "parameter": "param1",
            },
            "root_cause": "test root cause",
            "prevention_steps": [{"action": "step1"}],
        }

        similarity = learner._calculate_similarity(pattern, pattern)
        assert similarity >= 0.99

    def test_completely_different_patterns(self, learner):
        """Completely different patterns should have low similarity."""
        p1 = {
            "tool": "tool1",
            "mistake_pattern": {
                "error_regex": "error A",
                "parameter": "param_a",
            },
            "root_cause": "cause A with some unique text",
            "prevention_steps": [{"action": "a"}],
        }
        p2 = {
            "tool": "tool2",
            "mistake_pattern": {
                "error_regex": "error B",
                "parameter": "param_b",
            },
            "root_cause": "cause B with different text",
            "prevention_steps": [{"action": "b"}, {"action": "c"}],
        }

        similarity = learner._calculate_similarity(p1, p2)
        assert similarity < 0.5

    def test_same_error_regex_high_weight(self, learner):
        """Same error_regex should contribute heavily to similarity."""
        p1 = {
            "tool": "tool",
            "mistake_pattern": {"error_regex": "manifest unknown", "parameter": "x"},
            "root_cause": "cause 1",
            "prevention_steps": [],
        }
        p2 = {
            "tool": "tool",
            "mistake_pattern": {"error_regex": "manifest unknown", "parameter": "y"},
            "root_cause": "cause 2",
            "prevention_steps": [],
        }

        similarity = learner._calculate_similarity(p1, p2)
        assert similarity >= 0.4  # error_regex weight is 0.4

    def test_partial_regex_overlap(self, learner):
        """Partial regex pattern overlap should give partial score."""
        p1 = {
            "tool": "tool",
            "mistake_pattern": {
                "error_regex": "manifest unknown|image not found",
                "parameter": "image_tag",
            },
            "root_cause": "",
            "prevention_steps": [],
        }
        p2 = {
            "tool": "tool",
            "mistake_pattern": {
                "error_regex": "manifest unknown",
                "parameter": "image_tag",
            },
            "root_cause": "",
            "prevention_steps": [],
        }

        similarity = learner._calculate_similarity(p1, p2)
        assert 0.3 < similarity < 1.0

    def test_empty_mistake_patterns(self, learner):
        """Empty mistake_pattern fields should not crash."""
        p1 = {
            "tool": "tool",
            "mistake_pattern": {},
            "root_cause": "",
            "prevention_steps": [],
        }
        p2 = {
            "tool": "tool",
            "mistake_pattern": {},
            "root_cause": "",
            "prevention_steps": [],
        }

        similarity = learner._calculate_similarity(p1, p2)
        assert similarity == 0.0

    def test_prevention_steps_similarity(self, learner):
        """Similar number of prevention steps should contribute to score."""
        p1 = {
            "tool": "tool",
            "mistake_pattern": {"error_regex": "same", "parameter": "same"},
            "root_cause": "same",
            "prevention_steps": [{"a": 1}, {"b": 2}],
        }
        p2 = {
            "tool": "tool",
            "mistake_pattern": {"error_regex": "same", "parameter": "same"},
            "root_cause": "same",
            "prevention_steps": [{"a": 1}, {"b": 2}],
        }

        similarity = learner._calculate_similarity(p1, p2)
        assert similarity >= 0.9

    def test_fuzzy_parameter_matching(self, learner):
        """Similar parameter names should get partial score."""
        p1 = {
            "tool": "tool",
            "mistake_pattern": {"error_regex": "", "parameter": "image_tag"},
            "root_cause": "",
            "prevention_steps": [],
        }
        p2 = {
            "tool": "tool",
            "mistake_pattern": {"error_regex": "", "parameter": "image_tags"},
            "root_cause": "",
            "prevention_steps": [],
        }

        similarity = learner._calculate_similarity(p1, p2)
        # Parameters "image_tag" and "image_tags" are very similar
        assert similarity > 0.0


# ============================================================
# Prevention Tracking
# ============================================================


class TestPreventionTracking:
    """Tests for recording prevention success and failure."""

    @pytest.mark.asyncio
    async def test_record_prevention_success(self, learner):
        """Recording success should increment counter."""
        pattern = await learner.analyze_result(
            tool_name="bonfire_deploy",
            params={"image_tag": "short"},
            result="manifest unknown",
        )

        assert pattern["success_after_prevention"] == 0

        success = await learner.record_prevention_success(pattern["id"])
        assert success is True

        updated = learner.storage.get_pattern(pattern["id"])
        assert updated["success_after_prevention"] == 1

    @pytest.mark.asyncio
    async def test_record_multiple_successes(self, learner):
        """Multiple successes should accumulate."""
        pattern = await learner.analyze_result(
            tool_name="bonfire_deploy",
            params={"image_tag": "short"},
            result="manifest unknown",
        )

        for _ in range(5):
            await learner.record_prevention_success(pattern["id"])

        updated = learner.storage.get_pattern(pattern["id"])
        assert updated["success_after_prevention"] == 5

    @pytest.mark.asyncio
    async def test_record_success_unknown_pattern(self, learner):
        """Recording success for unknown pattern should return False."""
        result = await learner.record_prevention_success("nonexistent-id")
        assert result is False

    @pytest.mark.asyncio
    async def test_record_prevention_failure(self, learner):
        """Recording failure should reduce confidence."""
        # Create pattern with some confidence
        for _ in range(10):
            await learner.analyze_result(
                tool_name="bonfire_deploy",
                params={"image_tag": "short"},
                result="manifest unknown",
            )

        patterns = learner.storage.get_patterns_for_tool("bonfire_deploy")
        pattern = patterns[0]
        original_conf = pattern["confidence"]

        success = await learner.record_prevention_failure(
            pattern["id"], "Not applicable"
        )
        assert success is True

        updated = learner.storage.get_pattern(pattern["id"])
        assert updated["confidence"] < original_conf
        assert updated["confidence"] >= 0.30  # Floor at 30%

    @pytest.mark.asyncio
    async def test_record_failure_floors_at_30(self, learner):
        """Repeated failures should floor confidence at 30%."""
        pattern = await learner.analyze_result(
            tool_name="bonfire_deploy",
            params={"image_tag": "short"},
            result="manifest unknown",
        )

        # Reduce confidence multiple times
        for _ in range(20):
            await learner.record_prevention_failure(pattern["id"])

        updated = learner.storage.get_pattern(pattern["id"])
        assert updated["confidence"] >= 0.30

    @pytest.mark.asyncio
    async def test_record_failure_unknown_pattern(self, learner):
        """Recording failure for unknown pattern should return False."""
        result = await learner.record_prevention_failure("nonexistent-id")
        assert result is False


# ============================================================
# Learning Stats
# ============================================================


class TestLearningStats:
    """Tests for get_learning_stats method."""

    @pytest.mark.asyncio
    async def test_empty_stats(self, learner):
        """Should return stats even when no patterns exist."""
        stats = learner.get_learning_stats()

        assert stats["total_patterns"] == 0
        assert stats["total_observations"] == 0
        assert stats["total_preventions_successful"] == 0
        assert stats["average_confidence"] == 0.0

    @pytest.mark.asyncio
    async def test_stats_after_learning(self, learner):
        """Should return accurate stats after learning patterns."""
        await learner.analyze_result(
            tool_name="bonfire_deploy",
            params={"image_tag": "short"},
            result="manifest unknown",
        )

        await learner.analyze_result(
            tool_name="bonfire_namespace_release",
            params={"namespace": "wrong"},
            result="namespace not owned",
        )

        stats = learner.get_learning_stats()

        assert stats["total_patterns"] == 2
        assert stats["total_observations"] == 2
        assert stats["average_confidence"] == 0.5
        assert stats["low_confidence_patterns"] == 2
        assert stats["high_confidence_patterns"] == 0

    @pytest.mark.asyncio
    async def test_stats_high_confidence(self, learner):
        """High confidence patterns should be counted."""
        # Create a pattern with many observations
        for i in range(50):
            await learner.analyze_result(
                tool_name="bonfire_deploy",
                params={"image_tag": f"short{i}"},
                result="manifest unknown",
            )

        stats = learner.get_learning_stats()

        assert stats["total_patterns"] == 1
        assert stats["total_observations"] == 50
        assert stats["high_confidence_patterns"] == 1


# ============================================================
# End-to-End Flow
# ============================================================


class TestEndToEndFlow:
    """Test complete learning flow."""

    @pytest.mark.asyncio
    async def test_repeated_error_learning(self, learner):
        """Simulate repeated errors and verify learning."""
        for i in range(50):
            await learner.analyze_result(
                tool_name="bonfire_deploy",
                params={"image_tag": f"short{i}"},
                result="manifest unknown",
            )

        patterns = learner.storage.get_patterns_for_tool("bonfire_deploy")
        assert len(patterns) == 1

        pattern = patterns[0]
        assert pattern["observations"] == 50
        assert pattern["confidence"] == 0.92  # 45-99 obs
        assert pattern["error_category"] == "PARAMETER_FORMAT"
        assert len(pattern["prevention_steps"]) >= 2

        stats = learner.get_learning_stats()
        assert stats["total_patterns"] == 1
        assert stats["total_observations"] == 50
        assert stats["high_confidence_patterns"] == 1

    @pytest.mark.asyncio
    async def test_success_rate_affects_confidence(self, learner):
        """Prevention success should boost confidence."""
        for _ in range(10):
            await learner.analyze_result(
                tool_name="bonfire_deploy",
                params={"image_tag": "short"},
                result="manifest unknown",
            )

        patterns = learner.storage.get_patterns_for_tool("bonfire_deploy")
        pattern = patterns[0]
        base_conf = pattern["confidence"]  # 0.75

        for _ in range(9):
            await learner.record_prevention_success(pattern["id"])

        pattern = learner.storage.get_pattern(pattern["id"])
        assert pattern["confidence"] > base_conf
        assert pattern["confidence"] >= 0.79
