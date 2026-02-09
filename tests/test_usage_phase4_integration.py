"""
Tests for Layer 5 Phase 4: Claude Integration.

Tests warning visibility, prevention tracking, and context injection.
"""

import tempfile
from pathlib import Path

import pytest

from server.usage_context_injector import UsageContextInjector
from server.usage_pattern_storage import UsagePatternStorage
from server.usage_prevention_tracker import UsagePreventionTracker


@pytest.fixture
def temp_storage():
    """Create temporary storage for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        patterns_file = Path(tmpdir) / "usage_patterns.yaml"
        storage = UsagePatternStorage(patterns_file)
        yield storage


@pytest.fixture
def high_conf_pattern(temp_storage):
    """Create a high-confidence pattern for testing."""
    pattern = {
        "id": "bonfire_deploy_short_sha_95",
        "tool": "bonfire_deploy",
        "error_category": "PARAMETER_FORMAT",
        "mistake_pattern": {
            "error_regex": "manifest unknown",
            "parameter": "image_tag",
            "validation": {
                "regex": "^[a-f0-9]{40}$",
                "check": "len(image_tag) < 40",
            },
        },
        "root_cause": "Using short SHA instead of full 40-char SHA",
        "prevention_steps": [
            {"action": "validate_parameter", "reason": "Ensure full 40-char SHA"},
            {
                "action": "call_tool",
                "tool": "git_rev_parse",
                "reason": "Expand short SHA",
            },
        ],
        "observations": 100,
        "success_after_prevention": 95,
        "confidence": 0.95,
        "first_seen": "2026-01-12T10:00:00",
        "last_seen": "2026-01-12T16:00:00",
    }

    temp_storage.add_pattern(pattern)
    return pattern


@pytest.fixture
def medium_conf_pattern(temp_storage):
    """Create a medium-confidence pattern for testing."""
    pattern = {
        "id": "gitlab_mr_create_workflow_80",
        "tool": "gitlab_mr_create",
        "error_category": "WORKFLOW_SEQUENCE",
        "mistake_pattern": {
            "error_regex": "branch.*not.*on.*remote",
            "missing_step": ["git_push"],
        },
        "root_cause": "Calling gitlab_mr_create without git_push first",
        "prevention_steps": [
            {
                "action": "call_tool_first",
                "tool": "git_push",
                "reason": "Push branch to remote",
            },
        ],
        "observations": 15,
        "success_after_prevention": 12,
        "confidence": 0.80,
        "first_seen": "2026-01-12T10:00:00",
        "last_seen": "2026-01-12T14:00:00",
    }

    temp_storage.add_pattern(pattern)
    return pattern


class TestPreventionTracker:
    """Test prevention tracking functionality."""

    @pytest.mark.asyncio
    async def test_false_positive_detection_success_result(self):
        """Should detect false positive when tool succeeds despite warning."""
        tracker = UsagePreventionTracker()

        # Simulate a warning was shown
        usage_check = {
            "warnings": ["Warning: potential issue"],
            "patterns_matched": ["test_pattern_1"],
            "should_block": False,
        }

        # Tool succeeded
        result = "✅ Success! Deployed successfully."

        analysis = await tracker.analyze_call_result(
            tool_name="test_tool",
            params={"param": "value"},
            result=result,
            usage_check=usage_check,
        )

        assert analysis["false_positive"] is True
        assert analysis["patterns_affected"] == ["test_pattern_1"]
        assert "succeeded_despite_warning" in analysis["reason"]

    @pytest.mark.asyncio
    async def test_no_false_positive_on_failure(self):
        """Should NOT detect false positive when tool fails after warning."""
        tracker = UsagePreventionTracker()

        usage_check = {
            "warnings": ["Warning: potential issue"],
            "patterns_matched": ["test_pattern_1"],
            "should_block": False,
        }

        # Tool failed (warning was correct)
        result = "❌ Error: manifest unknown"

        analysis = await tracker.analyze_call_result(
            tool_name="test_tool",
            params={"param": "value"},
            result=result,
            usage_check=usage_check,
        )

        assert analysis["false_positive"] is False
        assert analysis["patterns_affected"] == []

    @pytest.mark.asyncio
    async def test_no_analysis_when_no_warnings(self):
        """Should skip analysis when no warnings were shown."""
        tracker = UsagePreventionTracker()

        # No warnings
        usage_check = {"warnings": [], "patterns_matched": [], "should_block": False}

        result = "✅ Success!"

        analysis = await tracker.analyze_call_result(
            tool_name="test_tool",
            params={"param": "value"},
            result=result,
            usage_check=usage_check,
        )

        assert analysis["false_positive"] is False
        assert analysis["prevention_success"] is False

    def test_success_detection_with_error_marker(self):
        """Should detect error with ❌ marker."""
        tracker = UsagePreventionTracker()

        assert tracker._is_success("✅ Success!") is True
        assert tracker._is_success("❌ Error occurred") is False
        assert tracker._is_success("Error: something went wrong") is False
        assert tracker._is_success("failed to deploy") is False
        assert tracker._is_success("Exception: invalid parameter") is False

    def test_success_detection_with_auth_errors(self):
        """Should detect auth errors as failures."""
        tracker = UsagePreventionTracker()

        assert tracker._is_success("Unauthorized: token expired") is False
        assert tracker._is_success("403 Forbidden") is False
        assert tracker._is_success("401 Unauthorized") is False


class TestContextInjector:
    """Test context injection functionality."""

    def test_generate_markdown_context(
        self, temp_storage, high_conf_pattern, medium_conf_pattern
    ):
        """Should generate markdown formatted context."""
        injector = UsageContextInjector(storage=temp_storage)

        context = injector.generate_prevention_context(
            top_n=10,
            min_confidence=0.75,
            format_type="markdown",
        )

        assert context != ""
        assert "Layer 5: Learned Usage Patterns" in context
        assert "bonfire_deploy" in context
        assert "gitlab_mr_create" in context
        assert "95%" in context  # High confidence pattern
        assert "80%" in context  # Medium confidence pattern
        assert "CRITICAL" in context  # >= 95%
        assert "MEDIUM" in context  # 80%
        assert "Ensure full 40-char SHA" in context
        assert "Push branch to remote" in context

    def test_generate_text_context(
        self, temp_storage, high_conf_pattern, medium_conf_pattern
    ):
        """Should generate plain text formatted context."""
        injector = UsageContextInjector(storage=temp_storage)

        context = injector.generate_prevention_context(
            top_n=10,
            min_confidence=0.75,
            format_type="text",
        )

        assert context != ""
        assert "LAYER 5: LEARNED USAGE PATTERNS" in context
        assert "bonfire_deploy" in context
        assert "gitlab_mr_create" in context

    def test_top_n_limit(self, temp_storage, high_conf_pattern, medium_conf_pattern):
        """Should limit to top N patterns."""
        injector = UsageContextInjector(storage=temp_storage)

        # Request only top 1
        context = injector.generate_prevention_context(
            top_n=1,
            min_confidence=0.75,
            format_type="markdown",
        )

        # Should only include the highest confidence pattern (95%)
        assert "bonfire_deploy" in context
        assert "gitlab_mr_create" not in context  # Second pattern excluded

    def test_min_confidence_filter(
        self, temp_storage, high_conf_pattern, medium_conf_pattern
    ):
        """Should filter patterns by min confidence."""
        injector = UsageContextInjector(storage=temp_storage)

        # Set min confidence to 90% (excludes 80% pattern)
        context = injector.generate_prevention_context(
            top_n=10,
            min_confidence=0.90,
            format_type="markdown",
        )

        assert "bonfire_deploy" in context  # 95% included
        assert "gitlab_mr_create" not in context  # 80% excluded

    def test_empty_context_no_patterns(self, temp_storage):
        """Should return empty string when no patterns meet criteria."""
        injector = UsageContextInjector(storage=temp_storage)

        context = injector.generate_prevention_context(
            top_n=10,
            min_confidence=0.99,  # No patterns this high
            format_type="markdown",
        )

        assert context == ""

    def test_get_pattern_count_by_confidence(
        self, temp_storage, high_conf_pattern, medium_conf_pattern
    ):
        """Should count patterns by confidence level."""
        injector = UsageContextInjector(storage=temp_storage)

        counts = injector.get_pattern_count_by_confidence()

        assert counts["critical"] == 1  # 95% pattern
        assert counts["high"] == 0  # None in 85-94% range
        assert counts["medium"] == 1  # 80% pattern
        assert counts["low"] == 0

    def test_get_prevention_summary_all_tools(
        self, temp_storage, high_conf_pattern, medium_conf_pattern
    ):
        """Should generate summary for all tools."""
        injector = UsageContextInjector(storage=temp_storage)

        summary = injector.get_prevention_summary()

        assert "Prevention patterns: 2 total" in summary
        assert "🔴 Critical (>= 95%): 1" in summary
        assert "🟡 Medium (>= 75%): 1" in summary

    def test_get_prevention_summary_single_tool(self, temp_storage, high_conf_pattern):
        """Should generate summary for specific tool."""
        injector = UsageContextInjector(storage=temp_storage)

        summary = injector.get_prevention_summary(tool_name="bonfire_deploy")

        assert "bonfire_deploy" in summary
        assert "1 total" in summary
        assert "🔴 Critical" in summary

    def test_get_prevention_summary_no_patterns(self, temp_storage):
        """Should handle no patterns gracefully."""
        injector = UsageContextInjector(storage=temp_storage)

        summary = injector.get_prevention_summary()

        assert "No prevention patterns found" in summary


class TestContextFormatting:
    """Test context formatting details."""

    def test_patterns_grouped_by_tool(self, temp_storage):
        """Should group multiple patterns for same tool."""
        # Add multiple patterns for same tool
        pattern1 = {
            "id": "bonfire_1",
            "tool": "bonfire_deploy",
            "error_category": "PARAMETER_FORMAT",
            "mistake_pattern": {},
            "root_cause": "Issue 1",
            "prevention_steps": [],
            "observations": 100,
            "confidence": 0.95,
        }

        pattern2 = {
            "id": "bonfire_2",
            "tool": "bonfire_deploy",
            "error_category": "MISSING_PREREQUISITE",
            "mistake_pattern": {},
            "root_cause": "Issue 2",
            "prevention_steps": [],
            "observations": 50,
            "confidence": 0.85,
        }

        temp_storage.add_pattern(pattern1)
        temp_storage.add_pattern(pattern2)

        injector = UsageContextInjector(storage=temp_storage)
        context = injector.generate_prevention_context(format_type="markdown")

        # Should have one section for bonfire_deploy with both patterns
        assert context.count("### Tool: `bonfire_deploy`") == 1
        assert "Issue 1" in context
        assert "Issue 2" in context

    def test_confidence_emoji_levels(self, temp_storage):
        """Should use correct emoji for each confidence level."""
        patterns = [
            {
                "id": "test_critical",
                "tool": "test_tool",
                "error_category": "PARAMETER_FORMAT",
                "mistake_pattern": {},
                "root_cause": "Critical issue",
                "prevention_steps": [],
                "observations": 100,
                "confidence": 0.95,
            },
            {
                "id": "test_high",
                "tool": "test_tool",
                "error_category": "PARAMETER_FORMAT",
                "mistake_pattern": {},
                "root_cause": "High issue",
                "prevention_steps": [],
                "observations": 50,
                "confidence": 0.85,
            },
            {
                "id": "test_medium",
                "tool": "test_tool",
                "error_category": "PARAMETER_FORMAT",
                "mistake_pattern": {},
                "root_cause": "Medium issue",
                "prevention_steps": [],
                "observations": 20,
                "confidence": 0.75,
            },
        ]

        for p in patterns:
            temp_storage.add_pattern(p)

        injector = UsageContextInjector(storage=temp_storage)
        context = injector.generate_prevention_context(
            format_type="markdown",
            min_confidence=0.75,  # Include all patterns down to 75%
        )

        assert "🔴 **CRITICAL**" in context
        assert "🟠 **HIGH**" in context
        assert "🟡 **MEDIUM**" in context

    def test_includes_usage_guidelines(self, temp_storage, high_conf_pattern):
        """Should include usage guidelines at the end."""
        injector = UsageContextInjector(storage=temp_storage)
        context = injector.generate_prevention_context(format_type="markdown")

        assert "When you see warnings during tool execution:" in context
        assert "If execution is blocked (>= 95% confidence):" in context
        assert "Following prevention steps is strongly recommended" in context


# ============================================================================
# Additional coverage tests for UsagePatternStorage (lines 73-340)
# ============================================================================


class TestUsagePatternStorageLoad:
    """Tests for UsagePatternStorage load/save operations."""

    def test_load_initial_file(self, temp_storage):
        """Should load initial file with empty patterns."""
        data = temp_storage.load()
        assert "usage_patterns" in data
        assert "stats" in data
        assert data["usage_patterns"] == []

    def test_load_empty_file_reinitializes(self, temp_storage):
        """Should reinitialize if file is empty."""
        # Write empty file
        temp_storage.patterns_file.write_text("")
        data = temp_storage.load()
        assert "usage_patterns" in data

    def test_load_corrupt_file(self, temp_storage):
        """Should return defaults for corrupt YAML file."""
        temp_storage.patterns_file.write_text(": : invalid yaml {{{{")
        data = temp_storage.load()
        assert data == {"usage_patterns": [], "stats": {}}

    def test_save_and_reload(self, temp_storage):
        """Should save and reload data correctly."""
        pattern = {
            "id": "save_test",
            "tool": "test_tool",
            "error_category": "PARAMETER_FORMAT",
            "mistake_pattern": {},
            "root_cause": "test",
            "prevention_steps": [],
            "observations": 5,
            "confidence": 0.80,
        }

        temp_storage.add_pattern(pattern)
        data = temp_storage.load()
        assert len(data["usage_patterns"]) == 1
        assert data["usage_patterns"][0]["id"] == "save_test"


class TestUsagePatternStorageCRUD:
    """Tests for CRUD operations on UsagePatternStorage."""

    def test_add_pattern(self, temp_storage):
        """Should add a pattern."""
        pattern = {
            "id": "crud_add",
            "tool": "test_tool",
            "error_category": "PARAMETER_FORMAT",
            "mistake_pattern": {},
            "root_cause": "test",
            "prevention_steps": [],
            "observations": 5,
            "confidence": 0.80,
        }
        assert temp_storage.add_pattern(pattern) is True

    def test_add_duplicate_pattern(self, temp_storage):
        """Should reject duplicate pattern ID."""
        pattern = {
            "id": "crud_dup",
            "tool": "test_tool",
            "error_category": "PARAMETER_FORMAT",
            "mistake_pattern": {},
            "root_cause": "test",
            "prevention_steps": [],
            "observations": 5,
            "confidence": 0.80,
        }
        assert temp_storage.add_pattern(pattern) is True
        assert temp_storage.add_pattern(pattern) is False

    def test_get_pattern(self, temp_storage):
        """Should get a specific pattern by ID."""
        pattern = {
            "id": "crud_get",
            "tool": "test_tool",
            "error_category": "PARAMETER_FORMAT",
            "mistake_pattern": {},
            "root_cause": "test",
            "prevention_steps": [],
            "observations": 5,
            "confidence": 0.80,
        }
        temp_storage.add_pattern(pattern)

        result = temp_storage.get_pattern("crud_get")
        assert result is not None
        assert result["id"] == "crud_get"

    def test_get_nonexistent_pattern(self, temp_storage):
        """Should return None for nonexistent pattern."""
        result = temp_storage.get_pattern("nonexistent")
        assert result is None

    def test_update_pattern(self, temp_storage):
        """Should update an existing pattern."""
        pattern = {
            "id": "crud_update",
            "tool": "test_tool",
            "error_category": "PARAMETER_FORMAT",
            "mistake_pattern": {},
            "root_cause": "original",
            "prevention_steps": [],
            "observations": 5,
            "confidence": 0.80,
        }
        temp_storage.add_pattern(pattern)

        assert (
            temp_storage.update_pattern("crud_update", {"root_cause": "updated"})
            is True
        )

        result = temp_storage.get_pattern("crud_update")
        assert result["root_cause"] == "updated"
        assert "last_seen" in result

    def test_update_nonexistent_pattern(self, temp_storage):
        """Should return False for nonexistent pattern update."""
        assert temp_storage.update_pattern("nonexistent", {"root_cause": "x"}) is False

    def test_delete_pattern(self, temp_storage):
        """Should delete an existing pattern."""
        pattern = {
            "id": "crud_delete",
            "tool": "test_tool",
            "error_category": "PARAMETER_FORMAT",
            "mistake_pattern": {},
            "root_cause": "test",
            "prevention_steps": [],
            "observations": 5,
            "confidence": 0.80,
        }
        temp_storage.add_pattern(pattern)

        assert temp_storage.delete_pattern("crud_delete") is True
        assert temp_storage.get_pattern("crud_delete") is None

    def test_delete_nonexistent_pattern(self, temp_storage):
        """Should return False for nonexistent pattern delete."""
        assert temp_storage.delete_pattern("nonexistent") is False


class TestUsagePatternStorageQuery:
    """Tests for query operations on UsagePatternStorage."""

    def test_get_patterns_for_tool(self, temp_storage):
        """Should get patterns for a specific tool."""
        patterns = [
            {
                "id": f"query_{i}",
                "tool": "target_tool" if i < 2 else "other_tool",
                "error_category": "PARAMETER_FORMAT",
                "mistake_pattern": {},
                "root_cause": "test",
                "prevention_steps": [],
                "observations": 5,
                "confidence": 0.80,
            }
            for i in range(3)
        ]
        for p in patterns:
            temp_storage.add_pattern(p)

        result = temp_storage.get_patterns_for_tool("target_tool")
        assert len(result) == 2

    def test_get_patterns_for_tool_with_confidence(self, temp_storage):
        """Should filter patterns by confidence."""
        patterns = [
            {
                "id": "high_conf",
                "tool": "test_tool",
                "error_category": "PARAMETER_FORMAT",
                "mistake_pattern": {},
                "root_cause": "test",
                "prevention_steps": [],
                "observations": 5,
                "confidence": 0.90,
            },
            {
                "id": "low_conf",
                "tool": "test_tool",
                "error_category": "PARAMETER_FORMAT",
                "mistake_pattern": {},
                "root_cause": "test",
                "prevention_steps": [],
                "observations": 5,
                "confidence": 0.50,
            },
        ]
        for p in patterns:
            temp_storage.add_pattern(p)

        result = temp_storage.get_patterns_for_tool("test_tool", min_confidence=0.75)
        assert len(result) == 1
        assert result[0]["id"] == "high_conf"

    def test_get_high_confidence_patterns(self, temp_storage):
        """Should get all high-confidence patterns."""
        patterns = [
            {
                "id": "hc_1",
                "tool": "tool1",
                "error_category": "PARAMETER_FORMAT",
                "mistake_pattern": {},
                "root_cause": "test",
                "prevention_steps": [],
                "observations": 50,
                "confidence": 0.90,
            },
            {
                "id": "hc_2",
                "tool": "tool2",
                "error_category": "PARAMETER_FORMAT",
                "mistake_pattern": {},
                "root_cause": "test",
                "prevention_steps": [],
                "observations": 5,
                "confidence": 0.50,
            },
        ]
        for p in patterns:
            temp_storage.add_pattern(p)

        result = temp_storage.get_high_confidence_patterns(min_confidence=0.85)
        assert len(result) == 1
        assert result[0]["id"] == "hc_1"


class TestUsagePatternStorageStats:
    """Tests for stats computation in UsagePatternStorage."""

    def test_update_stats(self, temp_storage):
        """Should update stats when saving."""
        patterns = [
            {
                "id": "stat_1",
                "tool": "tool1",
                "error_category": "PARAMETER_FORMAT",
                "mistake_pattern": {},
                "root_cause": "test",
                "prevention_steps": [],
                "observations": 10,
                "success_after_prevention": 8,
                "confidence": 0.90,
            },
            {
                "id": "stat_2",
                "tool": "tool2",
                "error_category": "WORKFLOW_SEQUENCE",
                "mistake_pattern": {},
                "root_cause": "test",
                "prevention_steps": [],
                "observations": 5,
                "success_after_prevention": 2,
                "confidence": 0.75,
            },
            {
                "id": "stat_3",
                "tool": "tool3",
                "error_category": "INCORRECT_PARAMETER",
                "mistake_pattern": {},
                "root_cause": "test",
                "prevention_steps": [],
                "observations": 3,
                "confidence": 0.50,
            },
        ]
        for p in patterns:
            temp_storage.add_pattern(p)

        data = temp_storage.load()
        stats = data["stats"]

        assert stats["total_usage_patterns"] == 3
        assert stats["high_confidence"] == 1  # >= 0.85
        assert stats["medium_confidence"] == 1  # 0.70-0.85
        assert stats["low_confidence"] == 1  # < 0.70
        assert stats["by_category"]["PARAMETER_FORMAT"] == 1
        assert stats["by_category"]["WORKFLOW_SEQUENCE"] == 1
        assert stats["by_category"]["INCORRECT_PARAMETER"] == 1
        # Prevention success rate: (8+2) / (10+5+3) = 10/18
        assert stats["prevention_success_rate"] > 0

    def test_stats_zero_observations(self, temp_storage):
        """Should handle zero observations gracefully."""
        data = {"usage_patterns": [], "stats": {}}
        temp_storage.save(data)

        loaded = temp_storage.load()
        assert loaded["stats"]["prevention_success_rate"] == 0.0


class TestUsagePatternStoragePruning:
    """Tests for prune_old_patterns in UsagePatternStorage."""

    def test_prune_old_low_confidence(self, temp_storage):
        """Should prune old low-confidence patterns."""
        from datetime import datetime, timedelta

        old_date = (datetime.now() - timedelta(days=100)).isoformat()
        recent_date = datetime.now().isoformat()

        patterns = [
            {
                "id": "old_low",
                "tool": "tool1",
                "error_category": "PARAMETER_FORMAT",
                "mistake_pattern": {},
                "root_cause": "old pattern",
                "prevention_steps": [],
                "observations": 2,
                "confidence": 0.50,
                "last_seen": old_date,
            },
            {
                "id": "recent_low",
                "tool": "tool2",
                "error_category": "PARAMETER_FORMAT",
                "mistake_pattern": {},
                "root_cause": "recent pattern",
                "prevention_steps": [],
                "observations": 2,
                "confidence": 0.50,
                "last_seen": recent_date,
            },
            {
                "id": "old_high",
                "tool": "tool3",
                "error_category": "PARAMETER_FORMAT",
                "mistake_pattern": {},
                "root_cause": "high conf",
                "prevention_steps": [],
                "observations": 50,
                "confidence": 0.90,
                "last_seen": old_date,
            },
        ]
        for p in patterns:
            temp_storage.add_pattern(p)

        pruned = temp_storage.prune_old_patterns(max_age_days=90, min_confidence=0.70)
        assert pruned == 1  # Only old_low should be pruned

        # Verify old_high is kept (high confidence)
        assert temp_storage.get_pattern("old_high") is not None
        # Verify recent_low is kept (recent)
        assert temp_storage.get_pattern("recent_low") is not None
        # Verify old_low is removed
        assert temp_storage.get_pattern("old_low") is None

    def test_prune_no_patterns(self, temp_storage):
        """Should return 0 when no patterns to prune."""
        pruned = temp_storage.prune_old_patterns()
        assert pruned == 0

    def test_prune_corrupt_file(self, temp_storage):
        """Should handle corrupt file gracefully."""
        temp_storage.patterns_file.write_text("invalid: {{{{ yaml")
        pruned = temp_storage.prune_old_patterns()
        assert pruned == 0


# ============================================================================
# Additional coverage tests for UsagePreventionTracker (lines 30-35, 54, 81-132, 214, 233)
# ============================================================================


class TestPreventionTrackerSingleton:
    """Tests for UsagePreventionTracker singleton pattern."""

    def test_get_instance_returns_same(self):
        """Should return same instance (singleton)."""
        # Reset singleton
        UsagePreventionTracker._instance = None
        tracker1 = UsagePreventionTracker.get_instance()
        tracker2 = UsagePreventionTracker.get_instance()
        assert tracker1 is tracker2
        # Cleanup
        UsagePreventionTracker._instance = None

    def test_get_prevention_tracker_function(self):
        """Should return singleton via convenience function."""
        from server.usage_prevention_tracker import get_prevention_tracker

        UsagePreventionTracker._instance = None
        tracker = get_prevention_tracker()
        assert isinstance(tracker, UsagePreventionTracker)
        UsagePreventionTracker._instance = None


class TestPreventionTrackerWarningTracking:
    """Tests for warning tracking in UsagePreventionTracker."""

    @pytest.mark.asyncio
    async def test_track_warning_shown(self):
        """Should log warning shown without error."""
        tracker = UsagePreventionTracker()
        await tracker.track_warning_shown(
            tool_name="test_tool",
            params={"param": "value"},
            patterns_matched=["pattern_1"],
            was_blocked=False,
        )
        # Test verifies no exception is raised
        assert True

    @pytest.mark.asyncio
    async def test_track_warning_shown_blocked(self):
        """Should log blocked warning."""
        tracker = UsagePreventionTracker()
        await tracker.track_warning_shown(
            tool_name="test_tool",
            params={"param": "value"},
            patterns_matched=["pattern_1"],
            was_blocked=True,
        )
        assert True  # Test verifies no exception is raised


class TestPreventionTrackerSuccess:
    """Tests for prevention success tracking."""

    @pytest.mark.asyncio
    async def test_track_prevention_success(self):
        """Should track prevention success."""
        tracker = UsagePreventionTracker()

        # This will try to call learner.record_prevention_success
        # which may fail if pattern doesn't exist, but should handle gracefully
        result = await tracker.track_prevention_success(
            pattern_id="nonexistent_pattern",
            tool_name="test_tool",
            original_params={"param": "bad"},
            corrected_params={"param": "good"},
        )
        # May return True or False depending on learner
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_track_prevention_success_error(self):
        """Should handle errors in prevention success tracking."""
        tracker = UsagePreventionTracker()
        # Force an error by using a mock that raises
        from unittest.mock import AsyncMock

        tracker.learner.record_prevention_success = AsyncMock(
            side_effect=TypeError("test error")
        )
        result = await tracker.track_prevention_success(
            pattern_id="test",
            tool_name="tool",
            original_params={},
            corrected_params={},
        )
        assert result is False


class TestPreventionTrackerFalsePositive:
    """Tests for false positive tracking."""

    @pytest.mark.asyncio
    async def test_track_false_positive(self):
        """Should track false positive."""
        tracker = UsagePreventionTracker()
        result = await tracker.track_false_positive(
            pattern_id="nonexistent_pattern",
            tool_name="test_tool",
            params={"param": "value"},
            reason="tool_succeeded_despite_warning",
        )
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_track_false_positive_error(self):
        """Should handle errors in false positive tracking."""
        tracker = UsagePreventionTracker()
        from unittest.mock import AsyncMock

        tracker.learner.record_prevention_failure = AsyncMock(
            side_effect=ValueError("test")
        )
        result = await tracker.track_false_positive(
            pattern_id="test",
            tool_name="tool",
            params={},
        )
        assert result is False


class TestPreventionTrackerIsSuccess:
    """Tests for _is_success method edge cases."""

    def test_empty_result_is_failure(self):
        """Should treat empty result as failure."""
        tracker = UsagePreventionTracker()
        assert tracker._is_success("") is False
        assert tracker._is_success(None) is False

    def test_normal_text_is_success(self):
        """Should treat normal text as success."""
        tracker = UsagePreventionTracker()
        assert tracker._is_success("Deployment complete. All good.") is True

    def test_error_at_start(self):
        """Should detect 'Error' at start of result."""
        tracker = UsagePreventionTracker()
        assert tracker._is_success("Error: something went wrong") is False

    def test_failed_in_first_200_chars(self):
        """Should detect 'failed' in first 200 chars."""
        tracker = UsagePreventionTracker()
        assert tracker._is_success("Pipeline failed to start") is False

    def test_failed_after_200_chars_is_success(self):
        """Should not detect 'failed' after 200 chars."""
        tracker = UsagePreventionTracker()
        text = "x" * 201 + " failed"
        assert tracker._is_success(text) is True


class TestPreventionTrackerAnalyzeResult:
    """Tests for analyze_call_result edge cases."""

    @pytest.mark.asyncio
    async def test_no_usage_check(self):
        """Should skip analysis when no usage_check provided."""
        tracker = UsagePreventionTracker()
        analysis = await tracker.analyze_call_result(
            tool_name="test",
            params={},
            result="success",
            usage_check=None,
        )
        assert analysis["false_positive"] is False
        assert analysis["prevention_success"] is False

    @pytest.mark.asyncio
    async def test_tool_failed_after_warning(self):
        """Should not mark false positive when tool failed."""
        tracker = UsagePreventionTracker()
        usage_check = {
            "warnings": ["Warning!"],
            "patterns_matched": ["p1"],
        }
        analysis = await tracker.analyze_call_result(
            tool_name="test",
            params={},
            result="Error: something went wrong",
            usage_check=usage_check,
        )
        assert analysis["false_positive"] is False
        assert analysis["patterns_affected"] == []

    @pytest.mark.asyncio
    async def test_tool_succeeded_false_positive(self):
        """Should mark false positive when tool succeeded despite warning."""
        tracker = UsagePreventionTracker()
        usage_check = {
            "warnings": ["Warning!"],
            "patterns_matched": ["p1", "p2"],
        }
        analysis = await tracker.analyze_call_result(
            tool_name="test",
            params={},
            result="Deployment successful!",
            usage_check=usage_check,
        )
        assert analysis["false_positive"] is True
        assert analysis["patterns_affected"] == ["p1", "p2"]
        assert "succeeded_despite_warning" in analysis["reason"]


# ============================================================================
# Additional coverage tests for UsagePatternStorage error paths
# ============================================================================


class TestUsagePatternStorageSaveErrors:
    """Tests for save error handling in UsagePatternStorage."""

    def test_save_with_missing_stats_key(self, temp_storage):
        """Should handle data without stats key."""
        data = {"usage_patterns": []}
        # Should not raise - save should add stats
        temp_storage.save(data)
        loaded = temp_storage.load()
        assert "stats" in loaded
        assert "last_updated" in loaded["stats"]

    def test_save_to_readonly_file(self, temp_storage):
        """Should handle save error gracefully."""
        import os

        # Make file read-only
        os.chmod(temp_storage.patterns_file, 0o444)
        try:
            data = {"usage_patterns": [], "stats": {}}
            # Should not raise, just log error
            temp_storage.save(data)
        finally:
            os.chmod(temp_storage.patterns_file, 0o644)
        assert True

    def test_save_updates_stats(self, temp_storage):
        """Should update stats before saving."""
        data = {
            "usage_patterns": [
                {
                    "id": "p1",
                    "tool": "t1",
                    "error_category": "PARAMETER_FORMAT",
                    "confidence": 0.90,
                    "observations": 10,
                    "success_after_prevention": 8,
                },
                {
                    "id": "p2",
                    "tool": "t2",
                    "error_category": "MISSING_PREREQUISITE",
                    "confidence": 0.60,
                    "observations": 5,
                    "success_after_prevention": 0,
                },
            ],
        }
        temp_storage.save(data)
        loaded = temp_storage.load()
        assert loaded["stats"]["total_usage_patterns"] == 2
        assert loaded["stats"]["high_confidence"] == 1
        assert loaded["stats"]["low_confidence"] == 1


class TestUsagePatternStorageAddErrors:
    """Tests for add_pattern error handling."""

    def test_add_pattern_creates_usage_patterns_key(self, temp_storage):
        """Should create usage_patterns key if missing."""
        # Write data without usage_patterns key
        import yaml

        with open(temp_storage.patterns_file, "w") as f:
            yaml.dump({"stats": {}}, f)

        pattern = {
            "id": "add_key_test",
            "tool": "t",
            "error_category": "PARAMETER_FORMAT",
            "confidence": 0.80,
            "observations": 5,
            "mistake_pattern": {},
            "root_cause": "test",
            "prevention_steps": [],
        }
        result = temp_storage.add_pattern(pattern)
        assert result is True

    def test_add_pattern_with_key_error(self, temp_storage):
        """Should handle KeyError in add_pattern gracefully."""
        # A pattern missing 'id' key should trigger KeyError
        result = temp_storage.add_pattern({})  # Missing 'id' key
        assert result is False


class TestUsagePatternStorageUpdateErrors:
    """Tests for update_pattern error handling."""

    def test_update_error_handling(self, temp_storage):
        """Should handle update error gracefully."""
        import os

        pattern = {
            "id": "update_err",
            "tool": "t",
            "error_category": "PARAMETER_FORMAT",
            "confidence": 0.80,
            "observations": 5,
            "mistake_pattern": {},
            "root_cause": "test",
            "prevention_steps": [],
        }
        temp_storage.add_pattern(pattern)

        os.chmod(temp_storage.patterns_file, 0o000)
        try:
            result = temp_storage.update_pattern("update_err", {"confidence": 0.99})
            assert result is False
        finally:
            os.chmod(temp_storage.patterns_file, 0o644)


class TestUsagePatternStorageDeleteErrors:
    """Tests for delete_pattern error handling."""

    def test_delete_error_handling(self, temp_storage):
        """Should handle delete error gracefully."""
        import os

        pattern = {
            "id": "del_err",
            "tool": "t",
            "error_category": "PARAMETER_FORMAT",
            "confidence": 0.80,
            "observations": 5,
            "mistake_pattern": {},
            "root_cause": "test",
            "prevention_steps": [],
        }
        temp_storage.add_pattern(pattern)

        os.chmod(temp_storage.patterns_file, 0o000)
        try:
            result = temp_storage.delete_pattern("del_err")
            assert result is False
        finally:
            os.chmod(temp_storage.patterns_file, 0o644)


class TestUsagePatternStorageStatsEdgeCases:
    """Tests for _update_stats edge cases."""

    def test_stats_no_stats_key(self, temp_storage):
        """Should create stats key if missing."""
        data = {"usage_patterns": []}
        result = temp_storage._update_stats(data)
        assert "stats" in result
        assert result["stats"]["total_usage_patterns"] == 0
        assert result["stats"]["prevention_success_rate"] == 0.0

    def test_stats_no_by_category(self, temp_storage):
        """Should create by_category key if missing."""
        data = {
            "usage_patterns": [
                {
                    "id": "p1",
                    "error_category": "WRONG_TOOL_SELECTION",
                    "confidence": 0.80,
                    "observations": 5,
                    "success_after_prevention": 3,
                }
            ],
            "stats": {},
        }
        result = temp_storage._update_stats(data)
        assert "by_category" in result["stats"]
        assert result["stats"]["by_category"]["WRONG_TOOL_SELECTION"] == 1

    def test_stats_all_categories(self, temp_storage):
        """Should count all categories correctly."""
        data = {
            "usage_patterns": [],
            "stats": {},
        }
        result = temp_storage._update_stats(data)
        for cat in [
            "INCORRECT_PARAMETER",
            "PARAMETER_FORMAT",
            "MISSING_PREREQUISITE",
            "WORKFLOW_SEQUENCE",
            "WRONG_TOOL_SELECTION",
        ]:
            assert cat in result["stats"]["by_category"]
            assert result["stats"]["by_category"][cat] == 0
