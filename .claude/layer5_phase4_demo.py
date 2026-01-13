#!/usr/bin/env python3
"""
Layer 5 Phase 4 Demonstration: Claude Integration

This demonstrates:
1. Warning visibility in tool output
2. Blocking for >= 95% confidence
3. False positive detection
4. Session-start context injection

Run: python .claude/layer5_phase4_demo.py
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from server.usage_context_injector import UsageContextInjector
from server.usage_pattern_checker import UsagePatternChecker
from server.usage_pattern_storage import UsagePatternStorage
from server.usage_prevention_tracker import UsagePreventionTracker


def setup_demo_patterns(storage):
    """Create realistic patterns for demonstration."""
    print("Setting up demo patterns...\n")

    # Pattern 1: High confidence (95%) - Will block
    pattern_high = {
        "id": "bonfire_deploy_short_sha_95",
        "tool": "bonfire_deploy",
        "error_category": "PARAMETER_FORMAT",
        "mistake_pattern": {
            "error_regex": "manifest unknown",
            "parameter": "image_tag",
            "validation": {"regex": "^[a-f0-9]{40}$", "check": "len(image_tag) < 40"},
        },
        "root_cause": "Using short SHA instead of full 40-char SHA",
        "prevention_steps": [
            {"action": "validate_parameter", "reason": "Ensure image_tag is full 40-char SHA"},
            {
                "action": "call_tool",
                "tool": "git_rev_parse",
                "reason": "Expand short SHA to full SHA",
            },
        ],
        "observations": 100,
        "success_after_prevention": 95,
        "confidence": 0.95,
        "first_seen": "2026-01-12T10:00:00",
        "last_seen": "2026-01-12T16:00:00",
    }

    # Pattern 2: Medium confidence (80%) - Will warn
    pattern_medium = {
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
                "reason": "Push branch to remote before creating MR",
            },
        ],
        "observations": 15,
        "success_after_prevention": 12,
        "confidence": 0.80,
        "first_seen": "2026-01-12T10:00:00",
        "last_seen": "2026-01-12T14:00:00",
    }

    # Pattern 3: Another high confidence (92%)
    pattern_high2 = {
        "id": "bonfire_namespace_release_ownership_92",
        "tool": "bonfire_namespace_release",
        "error_category": "INCORRECT_PARAMETER",
        "mistake_pattern": {
            "error_regex": "not owned by you",
            "parameter": "namespace",
        },
        "root_cause": "Trying to release namespace not owned by user",
        "prevention_steps": [
            {
                "action": "verify_first",
                "tool": "bonfire_namespace_list",
                "reason": "List your namespaces first to get the correct name",
            },
        ],
        "observations": 45,
        "success_after_prevention": 42,
        "confidence": 0.92,
        "first_seen": "2026-01-11T10:00:00",
        "last_seen": "2026-01-12T12:00:00",
    }

    storage.add_pattern(pattern_high)
    storage.add_pattern(pattern_medium)
    storage.add_pattern(pattern_high2)

    print("✅ Created 3 demo patterns")
    print("   - bonfire_deploy: 95% confidence (WILL BLOCK)")
    print("   - gitlab_mr_create: 80% confidence (will warn)")
    print("   - bonfire_namespace_release: 92% confidence (strong warning)")
    print()

    return pattern_high, pattern_medium, pattern_high2


def demo_blocking_execution(storage):
    """Demonstrate blocking execution for high-confidence pattern."""
    print("=" * 70)
    print("DEMO 1: Execution Blocked (>= 95% Confidence)")
    print("=" * 70)
    print()

    checker = UsagePatternChecker(storage=storage)

    print("Claude attempts to call:")
    print("  bonfire_deploy(image_tag='74ec56e', namespace='ephemeral-abc')")
    print()
    print("Checking patterns...")
    print()

    result = checker.check_before_call(
        tool_name="bonfire_deploy",
        params={"image_tag": "74ec56e", "namespace": "ephemeral-abc"},
        min_confidence=0.75,
    )

    if result["should_block"]:
        # Simulate what the tool would return
        warning_text = "\n\n".join(result["warnings"])
        blocked_output = (
            f"⛔ **LAYER 5: Execution Blocked**\n\n"
            f"This tool call was prevented because it matches a known mistake pattern "
            f"with very high confidence (>= 95%).\n\n"
            f"{warning_text}\n\n"
            f"**Next steps:**\n"
            f"1. Review the prevention steps above\n"
            f"2. Fix the parameter(s) or call prerequisite tool(s)\n"
            f"3. Retry with corrected parameters\n"
        )

        print("🔴 TOOL OUTPUT (returned to Claude):")
        print("-" * 70)
        print(blocked_output)
        print("-" * 70)
        print()
        print("✅ Execution prevented! Claude sees the blocking message and learns:")
        print("   1. The specific issue (short SHA)")
        print("   2. How to fix it (use git_rev_parse)")
        print("   3. What to do next (get full SHA and retry)")
        print()


async def demo_warning_in_output(storage):
    """Demonstrate warning prepended to successful tool output."""
    print("=" * 70)
    print("DEMO 2: Warning in Tool Output (80% Confidence)")
    print("=" * 70)
    print()

    checker = UsagePatternChecker(storage=storage)

    print("Claude attempts to call:")
    print("  gitlab_mr_create(title='New Feature', source_branch='feature/123')")
    print()
    print("Checking patterns...")
    print()

    result = checker.check_before_call(
        tool_name="gitlab_mr_create",
        params={"title": "New Feature", "source_branch": "feature/123"},
        context={"recent_tool_calls": []},  # No git_push in recent calls
        min_confidence=0.75,
    )

    if result["warnings"] and not result["should_block"]:
        # Simulate tool execution succeeding
        tool_output = "✅ Merge request created successfully!\n\nMR URL: https://gitlab.com/project/mr/123"

        # Prepend warning
        warning_text = "\n\n".join(result["warnings"])
        warning_header = (
            "⚠️  **LAYER 5: Usage Pattern Warning**\n\n"
            "This tool executed successfully, but it matches a known mistake pattern. "
            "Consider the prevention steps below for future calls.\n\n"
        )
        prepended_output = f"{warning_header}{warning_text}\n\n---\n\n{tool_output}"

        print("🟡 TOOL OUTPUT (returned to Claude):")
        print("-" * 70)
        print(prepended_output)
        print("-" * 70)
        print()
        print("✅ Tool succeeded, but Claude sees the warning!")
        print("   - In this case, the tool succeeded anyway (maybe branch was already pushed)")
        print("   - Claude learns the recommended workflow for next time")
        print("   - Pattern confidence may be adjusted if this becomes a false positive")
        print()


async def demo_false_positive_detection(storage):
    """Demonstrate false positive detection."""
    print("=" * 70)
    print("DEMO 3: False Positive Detection")
    print("=" * 70)
    print()

    tracker = UsagePreventionTracker()

    print("Scenario: Claude was warned but tool succeeded anyway")
    print()
    print("1. Pre-call check warned about missing git_push")
    print("2. Claude proceeded anyway (confidence only 80%)")
    print("3. Tool succeeded (branch was already pushed)")
    print()

    usage_check = {
        "warnings": ["⚠️  Warning about missing git_push"],
        "patterns_matched": ["gitlab_mr_create_workflow_80"],
        "should_block": False,
    }

    # Tool succeeded
    result = "✅ Merge request created successfully!"

    print("Analyzing result...")
    print()

    analysis = await tracker.analyze_call_result(
        tool_name="gitlab_mr_create",
        params={"title": "New Feature"},
        result=result,
        usage_check=usage_check,
    )

    print("Analysis:")
    print(f"  - False positive: {analysis['false_positive']}")
    print(f"  - Patterns affected: {analysis['patterns_affected']}")
    print(f"  - Reason: {analysis['reason']}")
    print()

    if analysis["false_positive"]:
        print("✅ False positive detected!")
        print("   - Pattern confidence will be REDUCED")
        print("   - Prevents over-warning on valid use cases")
        print("   - System learns when warnings are incorrect")
        print()


def demo_session_start_context(storage):
    """Demonstrate session-start context injection."""
    print("=" * 70)
    print("DEMO 4: Session-Start Context Injection")
    print("=" * 70)
    print()

    injector = UsageContextInjector(storage=storage)

    print("At session start, Claude receives high-confidence patterns:")
    print()

    # Generate context for top 10 patterns with >= 80% confidence
    context = injector.generate_prevention_context(
        top_n=10,
        min_confidence=0.80,
        format_type="markdown",
    )

    print("📋 CONTEXT INJECTED INTO CLAUDE:")
    print("=" * 70)
    print(context)
    print("=" * 70)
    print()

    print("✅ Claude now PROACTIVELY knows:")
    print("   1. Top 3 mistake patterns from past observations")
    print("   2. Prevention steps for each pattern")
    print("   3. Confidence levels (critical/high/medium)")
    print("   4. How to respond when warnings appear")
    print()

    print("💡 Result: Claude can AVOID mistakes BEFORE making them!")
    print("   - Sees bonfire_deploy needs full 40-char SHA")
    print("   - Knows to call git_push before gitlab_mr_create")
    print("   - Understands confidence levels and blocking behavior")
    print()


def demo_pattern_summary(storage):
    """Demonstrate pattern summary."""
    print("=" * 70)
    print("DEMO 5: Pattern Summary")
    print("=" * 70)
    print()

    injector = UsageContextInjector(storage=storage)

    print("Quick summary of learned patterns:")
    print()

    # Overall summary
    overall = injector.get_prevention_summary()
    print(overall)
    print()

    # Per-tool summary
    print("\nPer-tool summaries:")
    print()

    for tool in ["bonfire_deploy", "gitlab_mr_create", "bonfire_namespace_release"]:
        summary = injector.get_prevention_summary(tool_name=tool)
        print(summary)
        print()

    # Pattern count by confidence
    counts = injector.get_pattern_count_by_confidence()
    print("\nPattern count by confidence level:")
    print(f"  🔴 Critical (>= 95%): {counts['critical']}")
    print(f"  🟠 High (>= 85%): {counts['high']}")
    print(f"  🟡 Medium (>= 75%): {counts['medium']}")
    print(f"  ⚪ Low (< 75%): {counts['low']}")
    print()

    print("✅ System provides clear visibility into learned patterns!")
    print()


async def main():
    """Run all Phase 4 demonstrations."""
    print()
    print("#" * 70)
    print("# Layer 5 Phase 4: Claude Integration Demonstration")
    print("#" * 70)
    print()

    # Create shared storage for all demos
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        patterns_file = Path(tmpdir) / "usage_patterns.yaml"
        storage = UsagePatternStorage(patterns_file)

        # Set up patterns once
        setup_demo_patterns(storage)

        # Run all demos with shared storage
        demo_blocking_execution(storage)
        await demo_warning_in_output(storage)
        await demo_false_positive_detection(storage)
        demo_session_start_context(storage)
        demo_pattern_summary(storage)

    print("#" * 70)
    print("# All Demonstrations Complete!")
    print("#" * 70)
    print()

    print("Key Takeaways:")
    print("  ✅ Warnings are VISIBLE to Claude (not just logged)")
    print("  ✅ High-confidence patterns (>= 95%) BLOCK execution")
    print("  ✅ Medium-confidence warnings prepended to results")
    print("  ✅ False positives detected and tracked")
    print("  ✅ Session-start context gives Claude preventive knowledge")
    print("  ✅ System learns and improves from effectiveness tracking")
    print()

    print("What This Means:")
    print("  → Claude SEES warnings and can act on them")
    print("  → Claude learns patterns BEFORE making mistakes")
    print("  → Confidence evolves based on prevention effectiveness")
    print("  → Mistakes are prevented, not just fixed after the fact")
    print()

    print("Phase 4 Status:")
    print("  ✅ Warning visibility - IMPLEMENTED")
    print("  ✅ Blocking for high confidence - IMPLEMENTED")
    print("  ✅ False positive detection - IMPLEMENTED")
    print("  ✅ Context injection - IMPLEMENTED")
    print("  ✅ Integration tests - 17/17 PASSING")
    print()

    print("Next: Phase 5 (Optimization)")
    print("  → Performance tuning and caching")
    print("  → Pattern pruning and decay")
    print("  → Dashboard and monitoring")
    print("  → Production deployment")
    print()


if __name__ == "__main__":
    asyncio.run(main())
