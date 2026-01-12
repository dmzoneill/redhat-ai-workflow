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
            {"action": "call_tool", "tool": "git_rev_parse", "reason": "Expand short SHA"},
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
            {"action": "call_tool_first", "tool": "git_push", "reason": "Push branch to remote"},
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

    def test_generate_markdown_context(self, temp_storage, high_conf_pattern, medium_conf_pattern):
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

    def test_generate_text_context(self, temp_storage, high_conf_pattern, medium_conf_pattern):
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

    def test_min_confidence_filter(self, temp_storage, high_conf_pattern, medium_conf_pattern):
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

    def test_get_pattern_count_by_confidence(self, temp_storage, high_conf_pattern, medium_conf_pattern):
        """Should count patterns by confidence level."""
        injector = UsageContextInjector(storage=temp_storage)

        counts = injector.get_pattern_count_by_confidence()

        assert counts["critical"] == 1  # 95% pattern
        assert counts["high"] == 0  # None in 85-94% range
        assert counts["medium"] == 1  # 80% pattern
        assert counts["low"] == 0

    def test_get_prevention_summary_all_tools(self, temp_storage, high_conf_pattern, medium_conf_pattern):
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
