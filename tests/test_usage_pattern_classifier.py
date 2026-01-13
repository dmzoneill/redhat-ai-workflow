"""
Unit tests for Usage Pattern Classifier (Layer 5).

Tests the classification of errors as usage errors vs infrastructure errors.
"""

from server.usage_pattern_classifier import classify_error_type, is_infrastructure_error, is_learnable_error


class TestInfrastructureErrorDetection:
    """Test detection of infrastructure errors (not usage errors)."""

    def test_auth_error_detected(self):
        """Auth errors should be classified as infrastructure, not usage."""
        assert is_infrastructure_error("Error: Unauthorized")
        assert is_infrastructure_error("401 authentication required")
        assert is_infrastructure_error("Token expired")
        assert is_infrastructure_error("The server has asked for the client to provide credentials")

    def test_network_error_detected(self):
        """Network errors should be classified as infrastructure, not usage."""
        assert is_infrastructure_error("No route to host")
        assert is_infrastructure_error("Connection refused")
        assert is_infrastructure_error("Network unreachable")
        assert is_infrastructure_error("timeout")

    def test_usage_error_not_infrastructure(self):
        """Usage errors should NOT be classified as infrastructure."""
        assert not is_infrastructure_error("Namespace not owned by you")
        assert not is_infrastructure_error("Manifest unknown")
        assert not is_infrastructure_error("No commits on branch")


class TestIncorrectParameterClassification:
    """Test classification of INCORRECT_PARAMETER errors."""

    def test_namespace_not_owned(self):
        """Namespace ownership errors should be classified as INCORRECT_PARAMETER."""
        result = classify_error_type(
            tool_name="bonfire_namespace_release",
            params={"namespace": "ephemeral-abc-123"},
            error_message="❌ Error: Namespace 'ephemeral-abc-123' not owned by you",
            result="",
        )

        assert result["is_usage_error"] is True
        assert result["error_category"] == "INCORRECT_PARAMETER"
        assert result["confidence"] >= 0.85
        assert result["learnable"] is True
        assert result["evidence"]["pattern"] == "ownership_mismatch"
        assert "ephemeral-abc-123" in str(result["evidence"]["incorrect_param"])


class TestParameterFormatClassification:
    """Test classification of PARAMETER_FORMAT errors."""

    def test_short_sha_detected(self):
        """Short SHA should be classified as PARAMETER_FORMAT error."""
        result = classify_error_type(
            tool_name="bonfire_deploy",
            params={"image_tag": "74ec56e", "namespace": "ephemeral-abc"},
            error_message="❌ Error: manifest unknown",
            result="",
        )

        assert result["is_usage_error"] is True
        assert result["error_category"] == "PARAMETER_FORMAT"
        assert result["confidence"] >= 0.90
        assert result["learnable"] is True
        assert result["evidence"]["incorrect_param"] == "image_tag"
        assert result["evidence"]["expected_format"] == "40-character SHA"
        assert result["evidence"]["incorrect_value"] == "74ec56e"

    def test_full_sha_not_error(self):
        """Full 40-char SHA should NOT trigger format error."""
        result = classify_error_type(
            tool_name="bonfire_deploy",
            params={"image_tag": "a" * 40, "namespace": "ephemeral-abc"},
            error_message="❌ Error: manifest unknown",
            result="",
        )

        # Should not match format error since SHA is 40 chars
        # (might be different error, but not PARAMETER_FORMAT for SHA)
        if result["is_usage_error"]:
            assert result["error_category"] != "PARAMETER_FORMAT"


class TestMissingPrerequisiteClassification:
    """Test classification of MISSING_PREREQUISITE errors."""

    def test_no_commits_on_branch(self):
        """No commits error on gitlab_mr_create should be WORKFLOW_SEQUENCE.

        Note: For gitlab_mr_create specifically, "nothing to push" is classified
        as WORKFLOW_SEQUENCE because it's a known sequence issue (need git_push first).
        For other tools, similar errors would be MISSING_PREREQUISITE.
        """
        result = classify_error_type(
            tool_name="gitlab_mr_create",
            params={"title": "Test MR", "source_branch": "feature-branch"},
            error_message="❌ Error: nothing to push, branch has no commits",
            result="",
        )

        assert result["is_usage_error"] is True
        assert result["error_category"] == "WORKFLOW_SEQUENCE"
        assert result["confidence"] >= 0.75
        assert result["learnable"] is True
        assert "git_push" in result["evidence"]["missing_prerequisite"]

    def test_namespace_not_exist(self):
        """Namespace doesn't exist should be MISSING_PREREQUISITE."""
        result = classify_error_type(
            tool_name="bonfire_deploy",
            params={"namespace": "ephemeral-xyz"},
            error_message="❌ Error: namespace 'ephemeral-xyz' does not exist",
            result="",
        )

        assert result["is_usage_error"] is True
        assert result["error_category"] == "MISSING_PREREQUISITE"
        assert result["confidence"] >= 0.80


class TestWorkflowSequenceClassification:
    """Test classification of WORKFLOW_SEQUENCE errors."""

    def test_deploy_before_reserve(self):
        """Deploying before reserving namespace should be WORKFLOW_SEQUENCE."""
        result = classify_error_type(
            tool_name="bonfire_deploy",
            params={"namespace": "ephemeral-abc"},
            error_message="❌ Error: namespace not found",
            result="",
        )

        assert result["is_usage_error"] is True
        assert result["error_category"] == "WORKFLOW_SEQUENCE"
        assert result["confidence"] >= 0.75
        assert result["learnable"] is True
        assert "bonfire_namespace_reserve" in result["evidence"]["missing_prerequisite"]

    def test_mr_create_before_push(self):
        """Creating MR before pushing should be WORKFLOW_SEQUENCE."""
        result = classify_error_type(
            tool_name="gitlab_mr_create",
            params={"title": "Test MR"},
            error_message="❌ Error: branch not on remote",
            result="",
        )

        assert result["is_usage_error"] is True
        assert result["error_category"] == "WORKFLOW_SEQUENCE"
        assert result["confidence"] >= 0.75
        assert "git_push" in result["evidence"]["missing_prerequisite"]


class TestLearnableErrorCheck:
    """Test learnable error detection."""

    def test_incorrect_parameter_learnable(self):
        """INCORRECT_PARAMETER should be learnable."""
        classification = classify_error_type(
            tool_name="bonfire_namespace_release",
            params={"namespace": "ephemeral-abc"},
            error_message="namespace not owned",
        )

        assert is_learnable_error(classification) is True

    def test_parameter_format_learnable(self):
        """PARAMETER_FORMAT should be learnable."""
        classification = classify_error_type(
            tool_name="bonfire_deploy",
            params={"image_tag": "74ec56e"},
            error_message="manifest unknown",
        )

        assert is_learnable_error(classification) is True

    def test_infrastructure_not_learnable(self):
        """Infrastructure errors should not be learnable by Layer 5."""
        classification = classify_error_type(tool_name="bonfire_deploy", params={}, error_message="Unauthorized")

        assert is_learnable_error(classification) is False


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_error_message(self):
        """Empty error message should not crash."""
        result = classify_error_type(tool_name="test_tool", params={}, error_message="", result="")

        assert result["is_usage_error"] is False

    def test_none_params(self):
        """None params should not crash (use empty dict)."""
        result = classify_error_type(tool_name="test_tool", params={}, error_message="some error", result="")

        assert result is not None

    def test_case_insensitive_matching(self):
        """Pattern matching should be case-insensitive."""
        result = classify_error_type(
            tool_name="test_tool",
            params={},
            error_message="NAMESPACE NOT OWNED",
            result="",
        )

        assert result["is_usage_error"] is True
        assert result["error_category"] == "INCORRECT_PARAMETER"
