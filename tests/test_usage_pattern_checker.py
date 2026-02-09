"""
Tests for Usage Pattern Checker (Layer 5 Phase 3).

Tests prevention warnings before tool execution.
"""

import pytest

from server.usage_pattern_checker import UsagePatternChecker


@pytest.fixture
def temp_storage(usage_pattern_storage):
    """Alias shared fixture for backward compatibility."""
    return usage_pattern_storage


@pytest.fixture
def checker(temp_storage):
    """Create checker with temp storage."""
    return UsagePatternChecker(storage=temp_storage)


@pytest.fixture
def short_sha_pattern(temp_storage):
    """Create a short SHA pattern for testing."""
    pattern = {
        "id": "bonfire_deploy_short_sha_test",
        "tool": "bonfire_deploy",
        "error_category": "PARAMETER_FORMAT",
        "mistake_pattern": {
            "error_regex": "manifest unknown|image not found",
            "parameter": "image_tag",
            "validation": {
                "regex": "^[a-f0-9]{40}$",
                "check": "len(image_tag) < 40",
                "expected": "40-character full git SHA",
            },
            "common_mistakes": [
                "using 8-char short SHA",
                "using 7-char abbreviated SHA",
            ],
        },
        "root_cause": "Claude used short SHA instead of full 40-char SHA",
        "prevention_steps": [
            {
                "action": "validate_parameter",
                "parameter": "image_tag",
                "reason": "Ensure full 40-char SHA",
            },
            {
                "action": "call_tool_if_invalid",
                "tool": "git_rev_parse",
                "reason": "Expand short SHA to full",
            },
        ],
        "observations": 50,
        "success_after_prevention": 45,
        "confidence": 0.92,
        "first_seen": "2026-01-12T10:00:00",
        "last_seen": "2026-01-12T15:00:00",
    }

    temp_storage.add_pattern(pattern)
    return pattern


@pytest.fixture
def workflow_pattern(temp_storage):
    """Create a workflow sequence pattern for testing."""
    pattern = {
        "id": "gitlab_mr_workflow_test",
        "tool": "gitlab_mr_create",
        "error_category": "WORKFLOW_SEQUENCE",
        "mistake_pattern": {
            "error_regex": "branch.*not.*on.*remote",
            "missing_step": ["git_push"],
            "correct_sequence": ["git_commit", "git_push", "gitlab_mr_create"],
        },
        "root_cause": "Claude called gitlab_mr_create without first calling git_push",
        "prevention_steps": [
            {
                "action": "call_tool_first",
                "tool": "git_push",
                "reason": "Push branch before creating MR",
            },
        ],
        "observations": 10,
        "success_after_prevention": 8,
        "confidence": 0.80,
        "first_seen": "2026-01-12T10:00:00",
        "last_seen": "2026-01-12T12:00:00",
    }

    temp_storage.add_pattern(pattern)
    return pattern


class TestBasicChecking:
    """Test basic pattern checking."""

    def test_no_patterns_no_warnings(self, checker):
        """Should return no warnings if no patterns exist."""
        result = checker.check_before_call(
            tool_name="bonfire_deploy",
            params={"image_tag": "short"},
        )

        assert result["warnings"] == []
        assert result["should_block"] is False
        assert result["patterns_matched"] == []

    def test_different_tool_no_warnings(self, checker, short_sha_pattern):
        """Should not warn for different tool."""
        result = checker.check_before_call(
            tool_name="different_tool",
            params={"image_tag": "short"},
        )

        assert result["warnings"] == []

    def test_low_confidence_filtered_out(self, checker, temp_storage):
        """Should filter out patterns below min_confidence."""
        # Create low-confidence pattern
        pattern = {
            "id": "low_conf_test",
            "tool": "test_tool",
            "error_category": "PARAMETER_FORMAT",
            "mistake_pattern": {"parameter": "test_param"},
            "root_cause": "test",
            "prevention_steps": [],
            "observations": 1,
            "confidence": 0.50,  # Below 0.75 threshold
        }
        temp_storage.add_pattern(pattern)

        result = checker.check_before_call(
            tool_name="test_tool",
            params={"test_param": "value"},
            min_confidence=0.75,  # Explicit threshold
        )

        assert result["warnings"] == []


class TestParameterFormatMatching:
    """Test parameter format validation matching."""

    def test_short_sha_detected(self, checker, short_sha_pattern):
        """Should detect short SHA and warn."""
        result = checker.check_before_call(
            tool_name="bonfire_deploy",
            params={"image_tag": "74ec56e"},  # 7 chars
        )

        assert len(result["warnings"]) == 1
        assert "short sha" in result["warnings"][0].lower()  # lowercase "sha"
        assert result["patterns_matched"] == [short_sha_pattern["id"]]
        assert len(result["preventions"]) == 2

    def test_full_sha_passes(self, checker, short_sha_pattern):
        """Should NOT warn for full 40-char SHA."""
        result = checker.check_before_call(
            tool_name="bonfire_deploy",
            params={"image_tag": "a" * 40},  # 40 chars
        )

        assert result["warnings"] == []
        assert result["should_block"] is False

    def test_regex_validation(self, checker, short_sha_pattern):
        """Should validate against regex pattern."""
        result = checker.check_before_call(
            tool_name="bonfire_deploy",
            params={"image_tag": "xyz123"},  # Invalid chars for SHA
        )

        # Should warn because it doesn't match ^[a-f0-9]{40}$
        assert len(result["warnings"]) == 1


class TestWorkflowSequenceMatching:
    """Test workflow sequence detection."""

    def test_missing_prerequisite_detected(self, checker, workflow_pattern):
        """Should detect missing prerequisite in workflow."""
        result = checker.check_before_call(
            tool_name="gitlab_mr_create",
            params={"title": "Test MR"},
            context={"recent_tool_calls": []},  # No git_push in recent calls
        )

        assert len(result["warnings"]) == 1
        assert "git_push" in result["warnings"][0].lower()
        assert result["patterns_matched"] == [workflow_pattern["id"]]

    def test_prerequisite_present_passes(self, checker, workflow_pattern):
        """Should NOT warn if prerequisite was called."""
        result = checker.check_before_call(
            tool_name="gitlab_mr_create",
            params={"title": "Test MR"},
            context={"recent_tool_calls": ["git_commit", "git_push"]},
        )

        # git_push was called, so no warning
        assert result["warnings"] == []


class TestConfidenceLevels:
    """Test confidence-based behavior."""

    def test_medium_confidence_warning(self, checker, temp_storage):
        """Should warn but not block for medium confidence (75-84%)."""
        pattern = {
            "id": "medium_conf_test",
            "tool": "test_tool",
            "error_category": "PARAMETER_FORMAT",
            "mistake_pattern": {
                "parameter": "test_param",
                "validation": {"regex": "^valid$"},
            },
            "root_cause": "test issue",
            "prevention_steps": [],
            "observations": 10,
            "confidence": 0.75,
        }
        temp_storage.add_pattern(pattern)

        result = checker.check_before_call(
            tool_name="test_tool",
            params={"test_param": "invalid"},
        )

        assert len(result["warnings"]) == 1
        assert result["should_block"] is False  # Not 95%

    def test_high_confidence_suggests_block(self, checker, temp_storage):
        """Should suggest blocking for high confidence (85-94%)."""
        pattern = {
            "id": "high_conf_test",
            "tool": "test_tool",
            "error_category": "PARAMETER_FORMAT",
            "mistake_pattern": {
                "parameter": "test_param",
                "validation": {"regex": "^valid$"},
            },
            "root_cause": "test issue",
            "prevention_steps": [],
            "observations": 20,
            "confidence": 0.85,
        }
        temp_storage.add_pattern(pattern)

        result = checker.check_before_call(
            tool_name="test_tool",
            params={"test_param": "invalid"},
        )

        assert len(result["warnings"]) == 1
        assert result["should_block"] is False  # Still not 95%

    def test_very_high_confidence_blocks(self, checker, short_sha_pattern):
        """Should block for very high confidence (>= 95%)."""
        # Update pattern to 95%
        short_sha_pattern["confidence"] = 0.95
        checker.storage.update_pattern(short_sha_pattern["id"], {"confidence": 0.95})

        result = checker.check_before_call(
            tool_name="bonfire_deploy",
            params={"image_tag": "short"},
        )

        assert len(result["warnings"]) == 1
        assert result["should_block"] is True  # >= 95%
        assert "blocked" in result["warnings"][0].lower()


class TestWarningGeneration:
    """Test warning message generation."""

    def test_warning_includes_confidence(self, checker, short_sha_pattern):
        """Warning should include confidence percentage."""
        result = checker.check_before_call(
            tool_name="bonfire_deploy",
            params={"image_tag": "short"},
        )

        warning = result["warnings"][0]
        assert "92%" in warning

    def test_warning_includes_observations(self, checker, short_sha_pattern):
        """Warning should include observation count."""
        result = checker.check_before_call(
            tool_name="bonfire_deploy",
            params={"image_tag": "short"},
        )

        warning = result["warnings"][0]
        assert "50 observations" in warning

    def test_warning_includes_root_cause(self, checker, short_sha_pattern):
        """Warning should include root cause."""
        result = checker.check_before_call(
            tool_name="bonfire_deploy",
            params={"image_tag": "short"},
        )

        warning = result["warnings"][0]
        assert "short SHA" in warning

    def test_warning_includes_prevention_steps(self, checker, short_sha_pattern):
        """Warning should include prevention steps."""
        result = checker.check_before_call(
            tool_name="bonfire_deploy",
            params={"image_tag": "short"},
        )

        warning = result["warnings"][0]
        assert "Prevention steps:" in warning
        assert "Ensure full 40-char SHA" in warning
        assert "Expand short SHA" in warning

    def test_confidence_emoji(self, checker, temp_storage):
        """Should use appropriate emoji for confidence level."""
        # Test high confidence (>= 85%)
        pattern = {
            "id": "high_test",
            "tool": "test_tool",
            "error_category": "PARAMETER_FORMAT",
            "mistake_pattern": {
                "parameter": "test",
                "validation": {"regex": "^x$"},
            },
            "root_cause": "test",
            "prevention_steps": [],
            "observations": 20,
            "confidence": 0.90,
        }
        temp_storage.add_pattern(pattern)

        result = checker.check_before_call(
            tool_name="test_tool",
            params={"test": "y"},
        )

        warning = result["warnings"][0]
        assert "🟠" in warning or "HIGH" in warning


class TestPreventionSummary:
    """Test prevention summary generation."""

    def test_summary_with_patterns(self, checker, short_sha_pattern):
        """Should generate summary with patterns."""
        summary = checker.get_prevention_summary("bonfire_deploy")

        assert summary != ""
        assert "bonfire_deploy" in summary
        assert "short SHA" in summary
        assert "92%" in summary

    def test_summary_empty_no_patterns(self, checker):
        """Should return empty string if no patterns."""
        summary = checker.get_prevention_summary("nonexistent_tool")

        assert summary == ""


class TestMultiplePatterns:
    """Test behavior with multiple patterns."""

    def test_multiple_patterns_all_warned(self, checker, temp_storage):
        """Should warn for all matching patterns."""
        # Create two different patterns for same tool
        pattern1 = {
            "id": "pattern1",
            "tool": "test_tool",
            "error_category": "PARAMETER_FORMAT",
            "mistake_pattern": {
                "parameter": "param1",
                "validation": {"regex": "^valid1$"},
            },
            "root_cause": "issue 1",
            "prevention_steps": [],
            "observations": 10,
            "confidence": 0.75,
        }

        pattern2 = {
            "id": "pattern2",
            "tool": "test_tool",
            "error_category": "PARAMETER_FORMAT",
            "mistake_pattern": {
                "parameter": "param2",
                "validation": {"regex": "^valid2$"},
            },
            "root_cause": "issue 2",
            "prevention_steps": [],
            "observations": 10,
            "confidence": 0.75,
        }

        temp_storage.add_pattern(pattern1)
        temp_storage.add_pattern(pattern2)

        result = checker.check_before_call(
            tool_name="test_tool",
            params={"param1": "invalid1", "param2": "invalid2"},
        )

        # Should warn for both patterns
        assert len(result["warnings"]) == 2
        assert len(result["patterns_matched"]) == 2


# ============================================================================
# Additional coverage tests targeting uncovered lines
# ============================================================================


class TestIncorrectParameterMatching:
    """Test INCORRECT_PARAMETER category matching (lines 206-225)."""

    def test_incorrect_parameter_no_param(self, checker, temp_storage):
        """Should return False when parameter is not in params."""
        pattern = {
            "id": "incorrect_param_test",
            "tool": "test_tool",
            "error_category": "INCORRECT_PARAMETER",
            "mistake_pattern": {
                "parameter": "namespace",
                "common_mistakes": ["using arbitrary namespace name"],
            },
            "root_cause": "Wrong namespace used",
            "prevention_steps": [],
            "observations": 10,
            "confidence": 0.80,
        }
        temp_storage.add_pattern(pattern)

        result = checker.check_before_call(
            tool_name="test_tool",
            params={"other_param": "value"},
        )
        assert result["warnings"] == []

    def test_incorrect_parameter_arbitrary_namespace(self, checker, temp_storage):
        """Should not falsely flag arbitrary ephemeral namespace."""
        pattern = {
            "id": "incorrect_param_ns",
            "tool": "bonfire_ns_release",
            "error_category": "INCORRECT_PARAMETER",
            "mistake_pattern": {
                "parameter": "namespace",
                "common_mistakes": ["using arbitrary namespace name"],
            },
            "root_cause": "Wrong namespace",
            "prevention_steps": [],
            "observations": 5,
            "confidence": 0.80,
        }
        temp_storage.add_pattern(pattern)

        result = checker.check_before_call(
            tool_name="bonfire_ns_release",
            params={"namespace": "ephemeral-abc123"},
        )
        # Should not warn for INCORRECT_PARAMETER to avoid false positives
        assert result["warnings"] == []

    def test_incorrect_parameter_no_common_mistakes(self, checker, temp_storage):
        """Should not warn when no common_mistakes defined."""
        pattern = {
            "id": "incorrect_no_common",
            "tool": "test_tool",
            "error_category": "INCORRECT_PARAMETER",
            "mistake_pattern": {
                "parameter": "value",
                "common_mistakes": [],
            },
            "root_cause": "Wrong value",
            "prevention_steps": [],
            "observations": 5,
            "confidence": 0.80,
        }
        temp_storage.add_pattern(pattern)

        result = checker.check_before_call(
            tool_name="test_tool",
            params={"value": "anything"},
        )
        assert result["warnings"] == []


class TestMissingPrerequisiteMatching:
    """Test MISSING_PREREQUISITE category matching (lines 269-279)."""

    def test_missing_prerequisite_no_commits(self, checker, temp_storage):
        """Should detect missing commits prerequisite."""
        pattern = {
            "id": "missing_prereq_test",
            "tool": "git_push",
            "error_category": "MISSING_PREREQUISITE",
            "mistake_pattern": {
                "context": "branch created but no commits",
            },
            "root_cause": "Pushing empty branch",
            "prevention_steps": [
                {"action": "commit_first", "reason": "Make commits before pushing"},
            ],
            "observations": 10,
            "confidence": 0.80,
        }
        temp_storage.add_pattern(pattern)

        result = checker.check_before_call(
            tool_name="git_push",
            params={"branch": "feature/new"},
            context={"recent_tool_calls": ["git_branch"]},
        )
        assert len(result["warnings"]) == 1

    def test_missing_prerequisite_with_commits(self, checker, temp_storage):
        """Should not warn when commits exist."""
        pattern = {
            "id": "missing_prereq_ok",
            "tool": "git_push",
            "error_category": "MISSING_PREREQUISITE",
            "mistake_pattern": {
                "context": "branch created but no commits",
            },
            "root_cause": "Pushing empty branch",
            "prevention_steps": [],
            "observations": 10,
            "confidence": 0.80,
        }
        temp_storage.add_pattern(pattern)

        result = checker.check_before_call(
            tool_name="git_push",
            params={"branch": "feature/new"},
            context={"recent_tool_calls": ["git_commit"]},
        )
        assert result["warnings"] == []

    def test_missing_prerequisite_unrecognized_context(self, checker, temp_storage):
        """Should not warn for unrecognized prerequisite context."""
        pattern = {
            "id": "missing_prereq_unknown",
            "tool": "test_tool",
            "error_category": "MISSING_PREREQUISITE",
            "mistake_pattern": {
                "context": "some other prerequisite",
            },
            "root_cause": "Unknown prerequisite",
            "prevention_steps": [],
            "observations": 5,
            "confidence": 0.80,
        }
        temp_storage.add_pattern(pattern)

        result = checker.check_before_call(
            tool_name="test_tool",
            params={"param": "value"},
            context={},
        )
        assert result["warnings"] == []


class TestUnknownCategory:
    """Test unknown error_category handling (line 147)."""

    def test_unknown_category_no_match(self, checker, temp_storage):
        """Should not match for unknown error category."""
        pattern = {
            "id": "unknown_cat_test",
            "tool": "test_tool",
            "error_category": "UNKNOWN_CATEGORY",
            "mistake_pattern": {
                "parameter": "test",
            },
            "root_cause": "Unknown",
            "prevention_steps": [],
            "observations": 5,
            "confidence": 0.80,
        }
        temp_storage.add_pattern(pattern)

        result = checker.check_before_call(
            tool_name="test_tool",
            params={"test": "value"},
        )
        assert result["warnings"] == []


class TestCaching:
    """Test pattern caching (lines 352-406)."""

    def test_cache_hit(self, checker, short_sha_pattern):
        """Should use cached patterns on second call."""
        # First call populates cache
        checker.check_before_call(
            tool_name="bonfire_deploy",
            params={"image_tag": "short"},
        )

        # Second call should hit cache
        result = checker.check_before_call(
            tool_name="bonfire_deploy",
            params={"image_tag": "short2"},
        )
        assert len(result["warnings"]) == 1

    def test_cache_clear(self, checker, short_sha_pattern):
        """Should clear cache properly."""
        # Populate cache
        checker.check_before_call(
            tool_name="bonfire_deploy",
            params={"image_tag": "short"},
        )

        # Clear cache
        checker.clear_cache()
        assert checker._pattern_cache is None
        assert checker._cache_timestamp is None

    def test_cache_expiry(self, temp_storage):
        """Should expire cache after TTL."""
        from unittest.mock import patch

        checker = UsagePatternChecker(storage=temp_storage, cache_ttl=0)

        pattern = {
            "id": "cache_exp_test",
            "tool": "test_tool",
            "error_category": "PARAMETER_FORMAT",
            "mistake_pattern": {
                "parameter": "test",
                "validation": {"regex": "^valid$"},
            },
            "root_cause": "test",
            "prevention_steps": [],
            "observations": 5,
            "confidence": 0.80,
        }
        temp_storage.add_pattern(pattern)

        fake_time = 1000.0

        with patch("server.usage_pattern_checker.time") as mock_time:
            mock_time.time.return_value = fake_time

            # First call - populates cache
            checker.check_before_call(tool_name="test_tool", params={"test": "x"})

            # Advance time past TTL (TTL=0, any advance expires)
            mock_time.time.return_value = fake_time + 0.01

            # Second call should find cache expired
            result = checker.check_before_call(
                tool_name="test_tool", params={"test": "x"}
            )
            assert len(result["warnings"]) == 1

    def test_cache_miss_for_different_tool(self, checker, short_sha_pattern):
        """Should miss cache for different tool."""
        # Populate cache for bonfire_deploy
        checker.check_before_call(
            tool_name="bonfire_deploy",
            params={"image_tag": "short"},
        )

        # Different tool should be a cache miss
        result = checker.check_before_call(
            tool_name="other_tool",
            params={"param": "value"},
        )
        assert result["warnings"] == []

    def test_cache_eviction_max_entries(self, temp_storage):
        """Should evict oldest entry when max cache entries exceeded."""
        checker = UsagePatternChecker(storage=temp_storage, cache_ttl=300)
        checker._max_cache_entries = 2

        # Create pattern
        pattern = {
            "id": "eviction_test",
            "tool": "test_tool",
            "error_category": "PARAMETER_FORMAT",
            "mistake_pattern": {"parameter": "p", "validation": {"regex": "^x$"}},
            "root_cause": "test",
            "prevention_steps": [],
            "observations": 5,
            "confidence": 0.80,
        }
        temp_storage.add_pattern(pattern)

        # Fill cache with 3 entries (max is 2)
        checker.check_before_call(
            tool_name="test_tool", params={"p": "a"}, min_confidence=0.70
        )
        checker.check_before_call(
            tool_name="test_tool", params={"p": "b"}, min_confidence=0.60
        )
        checker.check_before_call(
            tool_name="test_tool", params={"p": "c"}, min_confidence=0.50
        )

        # Cache should have evicted oldest
        assert len(checker._pattern_cache) <= 2


class TestWarningLevels:
    """Test warning generation for different confidence levels (lines 302-303)."""

    def test_low_confidence_warning(self, checker, temp_storage):
        """Should generate LOW level warning for < 75% confidence."""
        pattern = {
            "id": "low_conf_warn",
            "tool": "test_tool",
            "error_category": "PARAMETER_FORMAT",
            "mistake_pattern": {
                "parameter": "test",
                "validation": {"regex": "^valid$"},
            },
            "root_cause": "test issue",
            "prevention_steps": [{"action": "check", "reason": "Verify value"}],
            "observations": 3,
            "confidence": 0.60,
        }
        temp_storage.add_pattern(pattern)

        result = checker.check_before_call(
            tool_name="test_tool",
            params={"test": "invalid"},
            min_confidence=0.50,
        )
        assert len(result["warnings"]) == 1
        warning = result["warnings"][0]
        assert "LOW" in warning

    def test_critical_confidence_warning(self, checker, temp_storage):
        """Should generate CRITICAL level warning for >= 95% confidence."""
        pattern = {
            "id": "critical_conf_warn",
            "tool": "test_tool",
            "error_category": "PARAMETER_FORMAT",
            "mistake_pattern": {
                "parameter": "test",
                "validation": {"regex": "^valid$"},
            },
            "root_cause": "critical issue",
            "prevention_steps": [{"action": "fix", "reason": "Must fix"}],
            "observations": 100,
            "confidence": 0.96,
        }
        temp_storage.add_pattern(pattern)

        result = checker.check_before_call(
            tool_name="test_tool",
            params={"test": "invalid"},
        )
        assert len(result["warnings"]) == 1
        warning = result["warnings"][0]
        assert "CRITICAL" in warning
        assert "blocked" in warning.lower()


class TestPreventionSummaryExtended:
    """Test prevention summary with success rate (lines 343-346)."""

    def test_summary_with_success_rate(self, checker, short_sha_pattern):
        """Should show prevention success rate in summary."""
        summary = checker.get_prevention_summary("bonfire_deploy")
        assert "90%" in summary  # 45/50 = 90%

    def test_summary_without_success(self, checker, temp_storage):
        """Should handle pattern with no success_after_prevention."""
        pattern = {
            "id": "no_success_test",
            "tool": "test_tool",
            "error_category": "PARAMETER_FORMAT",
            "mistake_pattern": {},
            "root_cause": "test",
            "prevention_steps": [],
            "observations": 10,
            "success_after_prevention": 0,
            "confidence": 0.80,
        }
        temp_storage.add_pattern(pattern)

        summary = checker.get_prevention_summary("test_tool")
        assert summary != ""
        assert "test" in summary


class TestParameterFormatValidation:
    """Test parameter format validation edge cases (lines 176-189)."""

    def test_validation_check_length_passes(self, checker, temp_storage):
        """Should detect parameter failing length check."""
        pattern = {
            "id": "len_check_test",
            "tool": "test_tool",
            "error_category": "PARAMETER_FORMAT",
            "mistake_pattern": {
                "parameter": "sha",
                "validation": {
                    "check": "len(sha) < 40",
                },
            },
            "root_cause": "Short value",
            "prevention_steps": [{"action": "fix", "reason": "Use full value"}],
            "observations": 5,
            "confidence": 0.80,
        }
        temp_storage.add_pattern(pattern)

        result = checker.check_before_call(
            tool_name="test_tool",
            params={"sha": "abc123"},  # Less than 40 chars
        )
        assert len(result["warnings"]) == 1

    def test_validation_check_length_full(self, checker, temp_storage):
        """Should not warn when value is long enough."""
        pattern = {
            "id": "len_check_ok",
            "tool": "test_tool",
            "error_category": "PARAMETER_FORMAT",
            "mistake_pattern": {
                "parameter": "sha",
                "validation": {
                    "check": "len(sha) < 40",
                },
            },
            "root_cause": "Short value",
            "prevention_steps": [],
            "observations": 5,
            "confidence": 0.80,
        }
        temp_storage.add_pattern(pattern)

        result = checker.check_before_call(
            tool_name="test_tool",
            params={"sha": "a" * 40},
        )
        assert result["warnings"] == []

    def test_missing_parameter_no_match(self, checker, temp_storage):
        """Should not match when param is missing from params dict."""
        pattern = {
            "id": "missing_param_test",
            "tool": "test_tool",
            "error_category": "PARAMETER_FORMAT",
            "mistake_pattern": {
                "parameter": "missing_param",
                "validation": {"regex": "^x$"},
            },
            "root_cause": "test",
            "prevention_steps": [],
            "observations": 5,
            "confidence": 0.80,
        }
        temp_storage.add_pattern(pattern)

        result = checker.check_before_call(
            tool_name="test_tool",
            params={"other": "value"},
        )
        assert result["warnings"] == []
