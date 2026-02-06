#!/usr/bin/env python3
"""Tests for the HybridToolFilter.

Run with: pytest tool_modules/aa_ollama/tests/test_tool_filter.py -v
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

import pytest  # noqa: E402


class TestSkillDetection:
    """Test fast skill detection via regex."""

    def test_detect_test_mr_ephemeral(self):
        from tool_modules.aa_ollama.src.skill_discovery import detect_skill

        assert detect_skill("deploy MR 1459 to ephemeral") == "test_mr_ephemeral"
        assert detect_skill("test MR 1459") == "test_mr_ephemeral"
        assert detect_skill("spin up MR 1459") == "test_mr_ephemeral"
        assert detect_skill("deploy to ephemeral") == "test_mr_ephemeral"

    def test_detect_start_work(self):
        from tool_modules.aa_ollama.src.skill_discovery import detect_skill

        assert detect_skill("start work on AAP-12345") == "start_work"
        assert detect_skill("begin AAP-12345") == "start_work"

    def test_detect_review_pr(self):
        from tool_modules.aa_ollama.src.skill_discovery import detect_skill

        assert detect_skill("review MR 1459") == "review_pr"
        assert detect_skill("review !1459") == "review_pr"

    def test_no_skill_detected(self):
        from tool_modules.aa_ollama.src.skill_discovery import detect_skill

        assert detect_skill("hello") is None
        assert detect_skill("what is the status of AAP-12345") is None


class TestToolRegistry:
    """Test tool registry and category lookups."""

    def test_load_registry(self):
        from tool_modules.aa_ollama.src.tool_registry import load_registry

        registry = load_registry()
        assert len(registry.categories) > 0
        assert "jira_read" in registry.categories
        assert "gitlab_mr_read" in registry.categories

    def test_get_tools_for_categories(self):
        from tool_modules.aa_ollama.src.tool_registry import load_registry

        registry = load_registry()
        tools = registry.get_tools_for_categories(["jira_read"])
        assert "jira_view_issue" in tools
        assert "jira_search" in tools

    def test_keyword_match(self):
        from tool_modules.aa_ollama.src.tool_registry import load_registry

        registry = load_registry()
        matches = registry.keyword_match("check AAP-12345")
        assert "jira_read" in matches

        matches = registry.keyword_match("MR 1459")
        assert "gitlab_mr_read" in matches


class TestHybridToolFilter:
    """Test the 4-layer tool filtering."""

    def test_layer1_core_always_included(self):
        from tool_modules.aa_ollama.src.tool_filter import HybridToolFilter

        filter_instance = HybridToolFilter()
        result = filter_instance.filter("hello", persona="developer")

        # Core tools should always be included
        assert "skill_run" in result["tools"] or "skill_list" in result["tools"]
        assert "layer1_core" in result["methods"]

    def test_layer2_persona_baseline(self):
        from tool_modules.aa_ollama.src.tool_filter import HybridToolFilter

        filter_instance = HybridToolFilter()
        result = filter_instance.filter("hello", persona="developer")

        # Developer baseline should include jira and gitlab
        assert "layer2_persona" in result["methods"]
        # Check that we got some tools (baseline varies by config)
        assert result["tool_count"] > 5

    def test_layer3_skill_discovery(self):
        from tool_modules.aa_ollama.src.tool_filter import HybridToolFilter

        filter_instance = HybridToolFilter()
        result = filter_instance.filter("deploy MR 1459 to ephemeral", persona="developer")

        # Should detect test_mr_ephemeral skill
        assert result["skill_detected"] == "test_mr_ephemeral"
        assert "layer3_skill" in result["methods"]

    def test_fast_path_mr_reference(self):
        from tool_modules.aa_ollama.src.tool_filter import HybridToolFilter

        filter_instance = HybridToolFilter()
        result = filter_instance.filter("check MR 1459", persona="developer")

        # Should use fast path for MR reference
        assert "fast_path" in result["methods"]

    def test_fast_path_jira_reference(self):
        from tool_modules.aa_ollama.src.tool_filter import HybridToolFilter

        filter_instance = HybridToolFilter()
        result = filter_instance.filter("what is AAP-12345", persona="developer")

        # Should use fast path for Jira reference
        assert "fast_path" in result["methods"]

    def test_significant_reduction(self):
        from tool_modules.aa_ollama.src.tool_filter import HybridToolFilter

        filter_instance = HybridToolFilter()
        result = filter_instance.filter("check MR 1459", persona="developer")

        # Should achieve significant reduction
        assert result["reduction_pct"] > 50

    def test_caching(self):
        from tool_modules.aa_ollama.src.tool_filter import HybridToolFilter

        filter_instance = HybridToolFilter()

        # First call
        result1 = filter_instance.filter("hello", persona="developer")

        # Second call should hit cache
        result2 = filter_instance.filter("hello", persona="developer")

        assert "cache_hit" in result2["methods"]
        assert result2["latency_ms"] < result1["latency_ms"]


class TestFilterStats:
    """Test statistics collection."""

    def test_stats_recording(self):
        from tool_modules.aa_ollama.src.stats import FilterStats

        stats = FilterStats()

        # Record a result
        stats.record(
            {
                "tools": ["tool1", "tool2"],
                "tool_count": 2,
                "reduction_pct": 90,
                "methods": ["layer1_core", "layer2_persona"],
                "persona": "developer",
                "skill_detected": None,
                "latency_ms": 5,
            }
        )

        assert stats.total_requests == 1
        assert "developer" in stats.by_persona
        assert stats.by_persona["developer"]["requests"] == 1

    def test_persona_stats(self):
        from tool_modules.aa_ollama.src.stats import FilterStats

        stats = FilterStats()

        # Record multiple results
        for i in range(5):
            stats.record(
                {
                    "tools": ["tool1"] * (10 + i),
                    "tool_count": 10 + i,
                    "reduction_pct": 90,
                    "methods": ["layer1_core"],
                    "persona": "developer",
                    "skill_detected": None,
                    "latency_ms": 5,
                }
            )

        persona_stats = stats.get_persona_stats("developer")
        assert persona_stats["requests"] == 5
        assert persona_stats["tools_min"] == 10
        assert persona_stats["tools_max"] == 14


class TestOllamaClient:
    """Test Ollama client (requires running Ollama instance)."""

    @pytest.mark.skip(reason="Requires running Ollama instance")
    def test_client_availability(self):
        from tool_modules.aa_ollama.src.client import get_client

        client = get_client("npu")
        # This will fail if Ollama isn't running, which is expected
        assert client.is_available() in [True, False]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
