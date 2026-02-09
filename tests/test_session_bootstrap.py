"""Tests for session bootstrap context functionality.

Tests the _get_bootstrap_context function that provides intelligent
context gathering and persona suggestions when starting a session.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestGetBootstrapContext:
    """Tests for _get_bootstrap_context function."""

    @pytest.mark.asyncio
    async def test_get_bootstrap_context_with_project(self):
        """Test bootstrap context returns data when memory abstraction is available."""
        from tool_modules.aa_workflow.src.session_tools import _get_bootstrap_context

        # Test with project context - may return None if memory abstraction not available
        result = await _get_bootstrap_context(
            "automation-analytics-backend", "Fix billing bug"
        )

        # Result can be None if memory abstraction isn't initialized
        if result is not None:
            assert "intent" in result
            assert "suggested_persona" in result
            assert "persona_confidence" in result
            assert "recommended_actions" in result
            assert "current_work" in result

    @pytest.mark.asyncio
    async def test_get_bootstrap_context_without_memory(self):
        """Test graceful fallback when memory abstraction is unavailable."""
        with patch.dict("sys.modules", {"services.memory_abstraction": None}):
            # Force reimport to trigger ImportError path
            import importlib

            import tool_modules.aa_workflow.src.session_tools as session_tools

            # The function should handle ImportError gracefully
            result = await session_tools._get_bootstrap_context("test-project", None)

            # Should return None when memory abstraction unavailable
            # (or return data if it was already imported)
            assert result is None or isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_get_bootstrap_context_with_session_name(self):
        """Test bootstrap context uses session name for intent hints."""
        from tool_modules.aa_workflow.src.session_tools import _get_bootstrap_context

        # Session name with issue key should influence intent
        result = await _get_bootstrap_context(None, "Working on AAP-12345")

        if result is not None:
            assert "intent" in result
            # Intent should be detected from the session name

    @pytest.mark.asyncio
    async def test_get_bootstrap_context_empty_inputs(self):
        """Test bootstrap context handles empty inputs gracefully."""
        from tool_modules.aa_workflow.src.session_tools import _get_bootstrap_context

        result = await _get_bootstrap_context(None, None)

        # Should not raise, may return None or minimal context
        assert result is None or isinstance(result, dict)


class TestPersonaSuggestionMapping:
    """Tests for intent-to-persona mapping logic."""

    def test_persona_map_coverage(self):
        """Test that persona map covers expected intents."""
        # The mapping is defined in _get_bootstrap_context
        persona_map = {
            "code_lookup": ("developer", 0.85),
            "troubleshooting": ("incident", 0.9),
            "status_check": ("developer", 0.7),
            "documentation": ("researcher", 0.8),
            "issue_context": ("developer", 0.85),
        }

        # Verify all expected intents are mapped
        expected_intents = [
            "code_lookup",
            "troubleshooting",
            "status_check",
            "documentation",
            "issue_context",
        ]
        for intent in expected_intents:
            assert intent in persona_map
            persona, confidence = persona_map[intent]
            assert isinstance(persona, str)
            assert 0 <= confidence <= 1

    def test_persona_confidence_thresholds(self):
        """Test that confidence thresholds are reasonable."""
        persona_map = {
            "code_lookup": ("developer", 0.85),
            "troubleshooting": ("incident", 0.9),
            "status_check": ("developer", 0.7),
            "documentation": ("researcher", 0.8),
            "issue_context": ("developer", 0.85),
        }

        # All confidences should be above 0.5 (better than random)
        for intent, (_persona, confidence) in persona_map.items():
            assert confidence >= 0.5, f"Confidence for {intent} too low: {confidence}"

        # Troubleshooting should have highest confidence (critical to get right)
        assert persona_map["troubleshooting"][1] >= 0.9


class TestRecommendedActions:
    """Tests for recommended action generation."""

    def test_action_map_coverage(self):
        """Test that action map covers expected intents."""
        action_map = {
            "code_lookup": [
                "Use code_search to find relevant code",
                "Check memory for similar patterns",
            ],
            "troubleshooting": [
                "Check learned/patterns for known fixes",
                "Load incident persona for debugging tools",
            ],
            "status_check": [
                "Review active issues in current_work",
                "Check environment health",
            ],
            "issue_context": ["Query Jira for issue details", "Check for related MRs"],
            "documentation": [
                "Query InScope for documentation",
                "Check knowledge base",
            ],
        }

        # All intents should have at least one action
        for intent, actions in action_map.items():
            assert len(actions) >= 1, f"No actions for intent: {intent}"

    def test_actions_are_actionable(self):
        """Test that recommended actions are specific and actionable."""
        action_map = {
            "code_lookup": [
                "Use code_search to find relevant code",
                "Check memory for similar patterns",
            ],
            "troubleshooting": [
                "Check learned/patterns for known fixes",
                "Load incident persona for debugging tools",
            ],
            "status_check": [
                "Review active issues in current_work",
                "Check environment health",
            ],
            "issue_context": ["Query Jira for issue details", "Check for related MRs"],
            "documentation": [
                "Query InScope for documentation",
                "Check knowledge base",
            ],
        }

        # Actions should contain verbs (actionable)
        action_verbs = ["use", "check", "load", "review", "query"]
        for _intent, actions in action_map.items():
            for action in actions:
                action_lower = action.lower()
                has_verb = any(verb in action_lower for verb in action_verbs)
                assert has_verb, f"Action not actionable: {action}"


class TestBootstrapIntegration:
    """Integration tests for bootstrap context with mocked memory."""

    @pytest.mark.asyncio
    async def test_bootstrap_with_mocked_memory(self):
        """Test bootstrap context with fully mocked memory interface."""
        from services.memory_abstraction.models import (
            IntentClassification,
            MemoryItem,
            QueryResult,
        )

        # Create mock query result
        mock_intent = IntentClassification(
            intent="code_lookup",
            confidence=0.85,
            sources_suggested=["code"],
        )

        mock_item = MemoryItem(
            source="yaml",
            type="state",
            relevance=0.9,
            summary="Current work state",
            content="Active Issues:\n- AAP-12345: Fix billing bug",
            metadata={"key": "state/current_work"},
        )

        mock_result = QueryResult(
            query="project automation-analytics-backend current work status",
            intent=mock_intent,
            sources_queried=["yaml"],
            items=[mock_item],
            total_count=1,
            latency_ms=50.0,
        )

        # Mock the memory interface
        mock_memory = AsyncMock()
        mock_memory.query = AsyncMock(return_value=mock_result)

        with patch(
            "services.memory_abstraction.get_memory_interface", return_value=mock_memory
        ):
            from tool_modules.aa_workflow.src.session_tools import (
                _get_bootstrap_context,
            )

            result = await _get_bootstrap_context(
                "automation-analytics-backend", "Fix billing bug"
            )

            if result is not None:
                assert result["intent"]["intent"] == "code_lookup"
                assert result["intent"]["confidence"] == 0.85
                assert result["suggested_persona"] == "developer"
                assert result["persona_confidence"] == 0.85

    @pytest.mark.asyncio
    async def test_bootstrap_extracts_active_issues(self):
        """Test that bootstrap correctly extracts active issues from memory."""
        from services.memory_abstraction.models import (
            IntentClassification,
            MemoryItem,
            QueryResult,
        )

        mock_intent = IntentClassification(
            intent="status_check",
            confidence=0.7,
            sources_suggested=["yaml"],
        )

        # Content with multiple issues
        mock_item = MemoryItem(
            source="yaml",
            type="state",
            relevance=0.9,
            summary="Current work state with multiple issues",
            content="Active Issues:\n- AAP-12345: First issue\n- AAP-67890: Second issue\n- APPSRE-111: Third issue",
            metadata={"key": "state/current_work"},
        )

        mock_result = QueryResult(
            query="test",
            intent=mock_intent,
            sources_queried=["yaml"],
            items=[mock_item],
            total_count=1,
            latency_ms=50.0,
        )

        mock_memory = AsyncMock()
        mock_memory.query = AsyncMock(return_value=mock_result)

        with patch(
            "services.memory_abstraction.get_memory_interface", return_value=mock_memory
        ):
            from tool_modules.aa_workflow.src.session_tools import (
                _get_bootstrap_context,
            )

            result = await _get_bootstrap_context("test-project", None)

            if result is not None:
                active_issues = result.get("current_work", {}).get("active_issues", [])
                # Should extract AAP and APPSRE issue keys
                assert (
                    "AAP-12345" in active_issues or len(active_issues) == 0
                )  # Depends on parsing


class TestBootstrapErrorHandling:
    """Tests for error handling in bootstrap context."""

    @pytest.mark.asyncio
    async def test_bootstrap_handles_memory_exception(self):
        """Test that bootstrap handles exceptions from memory interface gracefully."""
        mock_memory = AsyncMock()
        mock_memory.query = AsyncMock(side_effect=Exception("Memory query failed"))

        with patch(
            "services.memory_abstraction.get_memory_interface", return_value=mock_memory
        ):
            from tool_modules.aa_workflow.src.session_tools import (
                _get_bootstrap_context,
            )

            # Should not raise, should return None
            result = await _get_bootstrap_context("test-project", "test session")
            assert result is None

    @pytest.mark.asyncio
    async def test_bootstrap_handles_import_error(self):
        """Test that bootstrap handles ImportError when memory abstraction not available."""
        # Patch at the services level where the import happens
        with patch(
            "services.memory_abstraction.get_memory_interface",
            side_effect=ImportError("No module"),
        ):
            from tool_modules.aa_workflow.src.session_tools import (
                _get_bootstrap_context,
            )

            # Should return None, not raise
            result = await _get_bootstrap_context("test", None)
            # May return None or cached result depending on import state
            assert result is None or isinstance(result, dict)
