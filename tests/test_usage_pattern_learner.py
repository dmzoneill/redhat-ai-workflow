"""
Integration tests for Usage Pattern Learner (Layer 5 Phase 2).

Tests pattern learning, merging, and confidence evolution.
"""

import tempfile
from pathlib import Path

import pytest

from server.usage_pattern_learner import UsagePatternLearner
from server.usage_pattern_storage import UsagePatternStorage


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


class TestPatternLearning:
    """Test basic pattern learning."""

    @pytest.mark.asyncio
    async def test_learn_new_pattern(self, learner):
        """Should learn a new pattern from error."""
        result = await learner.analyze_result(
            tool_name="bonfire_namespace_release",
            params={"namespace": "ephemeral-abc"},
            result="❌ Error: Namespace 'ephemeral-abc' not owned by you",
            context={},
        )

        assert result is not None
        assert result["tool"] == "bonfire_namespace_release"
        assert result["error_category"] == "INCORRECT_PARAMETER"
        assert result["observations"] == 1
        assert result["confidence"] == 0.5  # 1 observation = 50%

    @pytest.mark.asyncio
    async def test_ignore_infrastructure_error(self, learner):
        """Should not learn from infrastructure errors."""
        result = await learner.analyze_result(
            tool_name="bonfire_deploy",
            params={},
            result="❌ Error: Unauthorized. Token expired.",
            context={},
        )

        assert result is None  # Not a usage error

    @pytest.mark.asyncio
    async def test_ignore_non_error(self, learner):
        """Should not learn from successful results."""
        result = await learner.analyze_result(
            tool_name="bonfire_deploy",
            params={},
            result="✅ Deployed successfully",
            context={},
        )

        assert result is None


class TestPatternMerging:
    """Test pattern merging with similar patterns."""

    @pytest.mark.asyncio
    async def test_merge_identical_patterns(self, learner):
        """Identical errors should merge into one pattern."""
        # First observation
        pattern1 = await learner.analyze_result(
            tool_name="bonfire_namespace_release",
            params={"namespace": "ephemeral-abc"},
            result="❌ Error: Namespace 'ephemeral-abc' not owned by you",
        )

        assert pattern1["observations"] == 1
        assert pattern1["confidence"] == 0.5

        # Second identical observation
        pattern2 = await learner.analyze_result(
            tool_name="bonfire_namespace_release",
            params={"namespace": "ephemeral-xyz"},  # Different value, same error
            result="❌ Error: Namespace 'ephemeral-xyz' not owned by you",
        )

        # Should merge (same pattern ID)
        assert pattern2["id"] == pattern1["id"]
        assert pattern2["observations"] == 2
        assert pattern2["confidence"] == 0.5  # 2 obs still = 50%

    @pytest.mark.asyncio
    async def test_merge_increases_confidence(self, learner):
        """Multiple observations should increase confidence."""
        # Simulate 10 observations of the same error
        for i in range(10):
            await learner.analyze_result(
                tool_name="bonfire_deploy",
                params={"image_tag": f"abc{i}"},  # Different short SHAs
                result="❌ Error: manifest unknown",
            )

        # Check final pattern
        patterns = learner.storage.get_patterns_for_tool("bonfire_deploy")
        assert len(patterns) == 1

        pattern = patterns[0]
        assert pattern["observations"] == 10
        assert pattern["confidence"] == 0.75  # 10 obs = 75%

    @pytest.mark.asyncio
    async def test_different_errors_create_separate_patterns(self, learner):
        """Different error types should create separate patterns."""
        # Error 1: Wrong namespace
        await learner.analyze_result(
            tool_name="bonfire_namespace_release",
            params={"namespace": "ephemeral-abc"},
            result="❌ Error: Namespace not owned",
        )

        # Error 2: Short SHA
        await learner.analyze_result(
            tool_name="bonfire_deploy",
            params={"image_tag": "abc123"},
            result="❌ Error: manifest unknown",
        )

        # Should have 2 separate patterns
        data = learner.storage.load()
        assert len(data["usage_patterns"]) == 2


class TestConfidenceEvolution:
    """Test confidence score evolution."""

    @pytest.mark.asyncio
    async def test_confidence_progression(self, learner):
        """Confidence should increase with observations."""
        tool_name = "bonfire_deploy"
        error = "❌ Error: manifest unknown"

        expected_confidence = {
            1: 0.50,  # 1-2 obs
            3: 0.60,  # 3-4 obs
            5: 0.70,  # 5-9 obs
            10: 0.75,  # 10-19 obs
            20: 0.85,  # 20-44 obs
            45: 0.92,  # 45-99 obs
            100: 0.95,  # 100+ obs
        }

        for count in expected_confidence.keys():
            # Simulate observations up to count
            for _ in range(count):
                await learner.analyze_result(
                    tool_name=tool_name,
                    params={"image_tag": "short"},
                    result=error,
                )

            # Check confidence
            patterns = learner.storage.get_patterns_for_tool(tool_name)
            assert len(patterns) == 1
            assert patterns[0]["confidence"] == expected_confidence[count]

            # Reset for next test
            learner.storage._initialize_file()

    @pytest.mark.asyncio
    async def test_success_rate_affects_confidence(self, learner):
        """Prevention success should boost confidence."""
        # Create pattern with 10 observations
        for _ in range(10):
            await learner.analyze_result(
                tool_name="bonfire_deploy",
                params={"image_tag": "short"},
                result="❌ Error: manifest unknown",
            )

        patterns = learner.storage.get_patterns_for_tool("bonfire_deploy")
        pattern = patterns[0]
        base_conf = pattern["confidence"]  # Should be 0.75

        # Record 9 successes
        for _ in range(9):
            await learner.record_prevention_success(pattern["id"])

        # Check updated confidence
        pattern = learner.storage.get_pattern(pattern["id"])
        # Success rate: 9/10 = 0.9
        # Final = 0.75 * 0.7 + 0.9 * 0.3 = 0.525 + 0.27 = 0.795
        assert pattern["confidence"] > base_conf
        assert pattern["confidence"] >= 0.79


class TestSimilarityCalculation:
    """Test pattern similarity calculation."""

    def test_identical_patterns_100_similar(self, learner):
        """Identical patterns should have 100% similarity."""
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
        assert similarity >= 0.99  # Account for floating point precision

    def test_completely_different_patterns_low_similarity(self, learner):
        """Completely different patterns should have low similarity."""
        pattern1 = {
            "tool": "tool1",
            "mistake_pattern": {
                "error_regex": "error A",
                "parameter": "param_a",
            },
            "root_cause": "cause A",
            "prevention_steps": [{"action": "action_a"}],
        }

        pattern2 = {
            "tool": "tool2",
            "mistake_pattern": {
                "error_regex": "error B",
                "parameter": "param_b",
            },
            "root_cause": "cause B",
            "prevention_steps": [{"action": "action_b"}, {"action": "action_c"}],
        }

        similarity = learner._calculate_similarity(pattern1, pattern2)
        assert similarity < 0.5

    def test_similar_patterns_above_threshold(self, learner):
        """Similar patterns should exceed 70% threshold."""
        pattern1 = {
            "tool": "bonfire_deploy",
            "mistake_pattern": {
                "error_regex": "manifest unknown|image not found",
                "parameter": "image_tag",
            },
            "root_cause": "Claude used short SHA instead of full SHA",
            "prevention_steps": [
                {"action": "validate"},
                {"action": "expand"},
            ],
        }

        pattern2 = {
            "tool": "bonfire_deploy",
            "mistake_pattern": {
                "error_regex": "manifest unknown",  # Partial match
                "parameter": "image_tag",
            },
            "root_cause": "Claude used wrong SHA format",
            "prevention_steps": [
                {"action": "validate"},
                {"action": "expand"},
            ],
        }

        similarity = learner._calculate_similarity(pattern1, pattern2)
        assert similarity >= 0.70


class TestPreventionTracking:
    """Test prevention success/failure tracking."""

    @pytest.mark.asyncio
    async def test_record_prevention_success(self, learner):
        """Recording success should increment counter."""
        # Create pattern
        pattern = await learner.analyze_result(
            tool_name="bonfire_deploy",
            params={"image_tag": "short"},
            result="❌ Error: manifest unknown",
        )

        assert pattern["success_after_prevention"] == 0

        # Record success
        success = await learner.record_prevention_success(pattern["id"])
        assert success is True

        # Check updated
        updated = learner.storage.get_pattern(pattern["id"])
        assert updated["success_after_prevention"] == 1

    @pytest.mark.asyncio
    async def test_record_prevention_failure(self, learner):
        """Recording failure should reduce confidence."""
        # Create pattern with some confidence
        for _ in range(10):
            await learner.analyze_result(
                tool_name="bonfire_deploy",
                params={"image_tag": "short"},
                result="❌ Error: manifest unknown",
            )

        patterns = learner.storage.get_patterns_for_tool("bonfire_deploy")
        pattern = patterns[0]
        original_conf = pattern["confidence"]

        # Record failure (false positive)
        success = await learner.record_prevention_failure(pattern["id"], "Not applicable")
        assert success is True

        # Check confidence reduced
        updated = learner.storage.get_pattern(pattern["id"])
        assert updated["confidence"] < original_conf
        assert updated["confidence"] >= 0.30  # Floor at 30%


class TestLearningStats:
    """Test learning statistics."""

    @pytest.mark.asyncio
    async def test_learning_stats(self, learner):
        """Should return comprehensive stats."""
        # Create multiple patterns
        await learner.analyze_result(
            tool_name="bonfire_deploy",
            params={"image_tag": "short"},
            result="❌ Error: manifest unknown",
        )

        await learner.analyze_result(
            tool_name="bonfire_namespace_release",
            params={"namespace": "wrong"},
            result="❌ Error: namespace not owned",
        )

        stats = learner.get_learning_stats()

        assert stats["total_patterns"] == 2
        assert stats["total_observations"] == 2
        assert stats["average_confidence"] == 0.5
        assert stats["low_confidence_patterns"] == 2
        assert stats["high_confidence_patterns"] == 0


class TestEndToEndFlow:
    """Test complete learning flow."""

    @pytest.mark.asyncio
    async def test_repeated_error_learning(self, learner):
        """Simulate repeated errors and verify learning."""
        # User makes same mistake 50 times
        for i in range(50):
            await learner.analyze_result(
                tool_name="bonfire_deploy",
                params={"image_tag": f"short{i}"},
                result="❌ Error: manifest unknown",
            )

        # Check learned pattern
        patterns = learner.storage.get_patterns_for_tool("bonfire_deploy")
        assert len(patterns) == 1

        pattern = patterns[0]
        assert pattern["observations"] == 50
        assert pattern["confidence"] == 0.92  # 45-99 obs = 92%
        assert pattern["error_category"] == "PARAMETER_FORMAT"
        assert len(pattern["prevention_steps"]) >= 2

        # Verify stats
        stats = learner.get_learning_stats()
        assert stats["total_patterns"] == 1
        assert stats["total_observations"] == 50
        assert stats["high_confidence_patterns"] == 1  # >= 0.85
