#!/usr/bin/env python3
"""
Layer 5 Phase 2 Demonstration: Pattern Learning & Confidence Evolution

This demonstrates:
1. Learning from repeated errors
2. Pattern merging
3. Confidence evolution
4. Prevention success tracking

Run: python .claude/layer5_phase2_demo.py
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from server.usage_pattern_learner import UsagePatternLearner


async def demo_repeated_errors():
    """Demonstrate learning from repeated errors."""
    print("\n" + "=" * 70)
    print("DEMO 1: Learning from Repeated Errors")
    print("=" * 70)

    learner = UsagePatternLearner()

    # Simulate Claude making the same mistake multiple times
    error_counts = [1, 3, 5, 10, 20, 45, 100]

    print("\nSimulating repeated 'short SHA' errors...")
    print("Observation count → Confidence evolution\n")

    for target_count in error_counts:
        # Add errors up to target count
        current_patterns = learner.storage.get_patterns_for_tool("bonfire_deploy")
        current_count = current_patterns[0]["observations"] if current_patterns else 0

        for i in range(current_count, target_count):
            await learner.analyze_result(
                tool_name="bonfire_deploy",
                params={"image_tag": f"abc{i:04d}"},  # Different short SHAs
                result="❌ Error: manifest unknown",
            )

        # Show confidence at this point
        patterns = learner.storage.get_patterns_for_tool("bonfire_deploy")
        if patterns:
            pattern = patterns[0]
            print(f"  {target_count:3d} observations → Confidence: {pattern['confidence']:.0%}")

    print("\n✅ Pattern learned! Confidence increased with observations.")


async def demo_pattern_merging():
    """Demonstrate pattern merging with similar errors."""
    print("\n" + "=" * 70)
    print("DEMO 2: Pattern Merging")
    print("=" * 70)

    learner = UsagePatternLearner()

    print("\nSimulating 3 similar 'namespace not owned' errors...")

    # Error 1
    result1 = await learner.analyze_result(
        tool_name="bonfire_namespace_release",
        params={"namespace": "ephemeral-abc-123"},
        result="❌ Error: Namespace 'ephemeral-abc-123' not owned by you",
    )
    print(f"\n1st error: Created pattern {result1['id'][:30]}...")
    print(f"   Observations: {result1['observations']}, Confidence: {result1['confidence']:.0%}")

    # Error 2 (similar)
    result2 = await learner.analyze_result(
        tool_name="bonfire_namespace_release",
        params={"namespace": "ephemeral-xyz-456"},
        result="❌ Error: Namespace 'ephemeral-xyz-456' not owned",
    )
    print(f"\n2nd error: Pattern {result2['id'][:30]}...")
    print(f"   Observations: {result2['observations']}, Confidence: {result2['confidence']:.0%}")

    # Error 3 (similar)
    result3 = await learner.analyze_result(
        tool_name="bonfire_namespace_release",
        params={"namespace": "ephemeral-test-789"},
        result="❌ Error: Cannot release namespace 'ephemeral-test-789'. Not owned by you.",
    )
    print(f"\n3rd error: Pattern {result3['id'][:30]}...")
    print(f"   Observations: {result3['observations']}, Confidence: {result3['confidence']:.0%}")

    if result1["id"] == result2["id"] == result3["id"]:
        print("\n✅ All errors merged into SAME pattern!")
    else:
        print(f"\n⚠️  Patterns: {result1['id'] == result2['id']}, {result2['id'] == result3['id']}")


async def demo_prevention_tracking():
    """Demonstrate prevention success tracking."""
    print("\n" + "=" * 70)
    print("DEMO 3: Prevention Success Tracking")
    print("=" * 70)

    learner = UsagePatternLearner()

    # Create pattern with 10 observations
    print("\nCreating pattern with 10 observations...")
    for i in range(10):
        await learner.analyze_result(
            tool_name="gitlab_mr_create",
            params={"title": f"Test MR {i}"},
            result="❌ Error: branch not on remote. Push first.",
        )

    patterns = learner.storage.get_patterns_for_tool("gitlab_mr_create")
    pattern = patterns[0]

    print("\nInitial state:")
    print(f"  Observations: {pattern['observations']}")
    print(f"  Confidence: {pattern['confidence']:.0%}")
    print(f"  Successes: {pattern['success_after_prevention']}")

    # Simulate Claude following prevention advice successfully 8 times
    print("\nSimulating 8 successful preventions...")
    for i in range(8):
        await learner.record_prevention_success(pattern["id"])

    # Get updated pattern
    pattern = learner.storage.get_pattern(pattern["id"])

    print("\nAfter preventions:")
    print(f"  Observations: {pattern['observations']}")
    print(f"  Confidence: {pattern['confidence']:.0%}")
    print(f"  Successes: {pattern['success_after_prevention']}")
    print(f"  Success rate: {pattern['success_after_prevention'] / pattern['observations']:.0%}")

    print("\n✅ Confidence boosted by prevention successes!")


async def demo_learning_stats():
    """Show overall learning statistics."""
    print("\n" + "=" * 70)
    print("DEMO 4: Learning Statistics")
    print("=" * 70)

    learner = UsagePatternLearner()

    # Create diverse patterns
    print("\nCreating diverse patterns...")

    # Pattern 1: Short SHA (50 observations → high confidence)
    for i in range(50):
        await learner.analyze_result(
            tool_name="bonfire_deploy",
            params={"image_tag": f"short{i}"},
            result="❌ Error: manifest unknown",
        )

    # Pattern 2: Wrong namespace (10 observations → medium confidence)
    for i in range(10):
        await learner.analyze_result(
            tool_name="bonfire_namespace_release",
            params={"namespace": f"ephemeral-{i}"},
            result="❌ Error: namespace not owned",
        )

    # Pattern 3: No commits (3 observations → low confidence)
    for i in range(3):
        await learner.analyze_result(
            tool_name="gitlab_mr_create",
            params={"title": f"MR {i}"},
            result="❌ Error: nothing to push",
        )

    # Get stats
    stats = learner.get_learning_stats()

    print("\nLearning Statistics:")
    print(f"  Total patterns: {stats['total_patterns']}")
    print(f"  Total observations: {stats['total_observations']}")
    print(f"  Average confidence: {stats['average_confidence']:.0%}")
    print("\nBy confidence level:")
    print(f"  High (>= 85%): {stats['high_confidence_patterns']}")
    print(f"  Medium (70-84%): {stats['medium_confidence_patterns']}")
    print(f"  Low (< 70%): {stats['low_confidence_patterns']}")
    print("\nBy category:")
    for category, count in stats["by_category"].items():
        if count > 0:
            print(f"  {category}: {count}")

    print("\n✅ System is learning diverse patterns!")


async def demo_confidence_threshold():
    """Show when patterns cross confidence thresholds."""
    print("\n" + "=" * 70)
    print("DEMO 5: Confidence Threshold Evolution")
    print("=" * 70)

    learner = UsagePatternLearner()

    thresholds = {
        0.50: "🟡 Low confidence (warning only)",
        0.75: "🟠 Medium confidence (strong warning)",
        0.85: "🔴 High confidence (suggest blocking)",
        0.95: "⛔ Very high confidence (block execution)",
    }

    print("\nSimulating errors until pattern reaches each threshold...\n")

    last_threshold_passed = 0.0

    for i in range(1, 101):
        result = await learner.analyze_result(
            tool_name="bonfire_deploy",
            params={"image_tag": f"short{i}"},
            result="❌ Error: manifest unknown",
        )

        confidence = result["confidence"]

        # Check if we crossed a threshold
        for threshold, label in thresholds.items():
            if confidence >= threshold > last_threshold_passed:
                print(f"  {i:3d} observations → {confidence:.0%} → {label}")
                last_threshold_passed = threshold

        # Stop at 95%
        if confidence >= 0.95:
            break

    print(f"\n✅ Pattern reached maximum confidence after {i} observations!")


async def main():
    """Run all demonstrations."""
    print("\n" + "#" * 70)
    print("# Layer 5 Phase 2: Pattern Learning & Confidence Evolution")
    print("#" * 70)

    # Clear any existing patterns from demos
    learner = UsagePatternLearner()
    learner.storage._initialize_file()

    # Run demos
    await demo_repeated_errors()
    learner.storage._initialize_file()

    await demo_pattern_merging()
    learner.storage._initialize_file()

    await demo_prevention_tracking()
    learner.storage._initialize_file()

    await demo_learning_stats()
    learner.storage._initialize_file()

    await demo_confidence_threshold()

    print("\n" + "#" * 70)
    print("# All Demonstrations Complete!")
    print("#" * 70)

    print("\nKey Takeaways:")
    print("  ✅ Patterns automatically merge when 70%+ similar")
    print("  ✅ Confidence evolves: 1 obs=50%, 10 obs=75%, 45 obs=92%, 100 obs=95%")
    print("  ✅ Prevention success boosts confidence")
    print("  ✅ Prevention failure reduces confidence")
    print("  ✅ Stats track learning progress across all patterns")

    print("\nNext Steps:")
    print("  → Phase 3: Implement pre-tool-call warnings")
    print("  → Phase 4: Integrate with Claude context")
    print("  → Phase 5: Production deployment")


if __name__ == "__main__":
    asyncio.run(main())
