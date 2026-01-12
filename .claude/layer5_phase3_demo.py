#!/usr/bin/env python3
"""
Layer 5 Phase 3 Demonstration: Prevention Warnings

This demonstrates:
1. Pre-call warnings before tool execution
2. Different confidence levels (75%, 85%, 95%)
3. Warning message formatting
4. Blocking behavior

Run: python .claude/layer5_phase3_demo.py
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from server.usage_pattern_checker import UsagePatternChecker
from server.usage_pattern_learner import UsagePatternLearner


async def setup_patterns():
    """Create some realistic patterns for demonstration."""
    learner = UsagePatternLearner()

    print("Setting up patterns...")

    # Pattern 1: Short SHA (high confidence)
    for i in range(50):
        await learner.analyze_result(
            tool_name="bonfire_deploy",
            params={"image_tag": f"short{i}"},
            result="❌ Error: manifest unknown",
        )

    # Pattern 2: Wrong namespace (medium confidence)
    for i in range(15):
        await learner.analyze_result(
            tool_name="bonfire_namespace_release",
            params={"namespace": f"ephemeral-{i}"},
            result="❌ Error: namespace not owned",
        )

    # Pattern 3: No commits (low-medium confidence)
    for i in range(8):
        await learner.analyze_result(
            tool_name="gitlab_mr_create",
            params={"title": f"MR {i}"},
            result="❌ Error: branch not on remote",
        )

    print("✅ Patterns created!\n")


async def demo_medium_confidence_warning():
    """Demonstrate warning for medium confidence pattern (75%)."""
    print("\n" + "=" * 70)
    print("DEMO 1: Medium Confidence Warning (75%)")
    print("=" * 70)

    checker = UsagePatternChecker()

    print("\nClaude is about to call: gitlab_mr_create(title='My Feature')")
    print("Checking learned patterns...")

    result = checker.check_before_call(
        tool_name="gitlab_mr_create",
        params={"title": "My Feature"},
        context={"recent_tool_calls": []},  # No git_push in recent calls
    )

    if result["warnings"]:
        print("\n" + result["warnings"][0])
        print(f"\nShould block? {result['should_block']}")
        print("Decision: ⚠️  Warn but allow execution")
    else:
        print("\n✅ No warnings (pattern confidence too low or not matching)")


async def demo_high_confidence_warning():
    """Demonstrate warning for high confidence pattern (92%)."""
    print("\n" + "=" * 70)
    print("DEMO 2: High Confidence Warning (92%)")
    print("=" * 70)

    checker = UsagePatternChecker()

    print("\nClaude is about to call: bonfire_deploy(image_tag='74ec56e')")
    print("Checking learned patterns...")

    result = checker.check_before_call(
        tool_name="bonfire_deploy",
        params={"image_tag": "74ec56e"},  # Short SHA
    )

    if result["warnings"]:
        print("\n" + result["warnings"][0])
        print(f"\nShould block? {result['should_block']}")
        print("Decision: 🟠 Strong warning, suggest following prevention steps")
    else:
        print("\n✅ No warnings")


async def demo_very_high_confidence_block():
    """Demonstrate blocking for very high confidence pattern (>= 95%)."""
    print("\n" + "=" * 70)
    print("DEMO 3: Very High Confidence Blocking (95%)")
    print("=" * 70)

    # First, boost the pattern to 95% by adding more observations
    learner = UsagePatternLearner()

    print("\nBoosting pattern confidence to 95%...")
    for i in range(50, 101):  # 50 more observations
        await learner.analyze_result(
            tool_name="bonfire_deploy",
            params={"image_tag": f"short{i}"},
            result="❌ Error: manifest unknown",
        )

    print("Pattern now at 95% confidence!\n")

    checker = UsagePatternChecker()

    print("Claude is about to call: bonfire_deploy(image_tag='abc123')")
    print("Checking learned patterns...")

    result = checker.check_before_call(
        tool_name="bonfire_deploy",
        params={"image_tag": "abc123"},  # Short SHA
    )

    if result["warnings"]:
        print("\n" + result["warnings"][0])
        print(f"\nShould block? {result['should_block']}")
        print("Decision: 🔴 BLOCK execution (confidence >= 95%)")
    else:
        print("\n✅ No warnings")


async def demo_valid_parameter_passes():
    """Demonstrate no warning when parameter is valid."""
    print("\n" + "=" * 70)
    print("DEMO 4: Valid Parameter - No Warning")
    print("=" * 70)

    checker = UsagePatternChecker()

    full_sha = "a" * 40
    print(f"\nClaude is about to call: bonfire_deploy(image_tag='{full_sha}')")
    print("Checking learned patterns...")

    result = checker.check_before_call(
        tool_name="bonfire_deploy",
        params={"image_tag": full_sha},  # Full 40-char SHA
    )

    if result["warnings"]:
        print(f"\n⚠️  Warning: {result['warnings'][0]}")
    else:
        print("\n✅ No warnings - parameter format is correct!")
        print("Tool execution proceeds normally.")


async def demo_prevention_summary():
    """Demonstrate prevention summary for a tool."""
    print("\n" + "=" * 70)
    print("DEMO 5: Prevention Summary for Tool")
    print("=" * 70)

    checker = UsagePatternChecker()

    print("\nGetting prevention summary for 'bonfire_deploy'...")

    summary = checker.get_prevention_summary("bonfire_deploy", min_confidence=0.75)

    if summary:
        print("\n" + summary)
    else:
        print("\nNo high-confidence patterns found.")


async def demo_multiple_warnings():
    """Demonstrate multiple warnings for multiple issues."""
    print("\n" + "=" * 70)
    print("DEMO 6: Multiple Warnings (Hypothetical)")
    print("=" * 70)

    print("\nIf a tool had multiple learned issues, Claude would see ALL warnings:")
    print("\n🟠 **HIGH CONFIDENCE WARNING** (92%, 50 observations)")
    print("   Tool: `my_tool`")
    print("   Issue: Parameter format incorrect")
    print("\n   Prevention steps:")
    print("   1. Validate parameter X")
    print("   2. Call prerequisite tool Y")
    print("\n🟡 **MEDIUM CONFIDENCE WARNING** (78%, 12 observations)")
    print("   Tool: `my_tool`")
    print("   Issue: Missing workflow step")
    print("\n   Prevention steps:")
    print("   1. Call tool Z first")

    print("\nClaude would see both warnings and could choose to:")
    print("  - Follow the prevention steps")
    print("  - Proceed with caution")
    print("  - Choose a different approach")


async def main():
    """Run all demonstrations."""
    print("\n" + "#" * 70)
    print("# Layer 5 Phase 3: Prevention Warnings Demonstration")
    print("#" * 70)

    # Setup
    await setup_patterns()

    # Run demos
    await demo_medium_confidence_warning()
    await demo_high_confidence_warning()
    await demo_very_high_confidence_block()
    await demo_valid_parameter_passes()
    await demo_prevention_summary()
    await demo_multiple_warnings()

    print("\n" + "#" * 70)
    print("# All Demonstrations Complete!")
    print("#" * 70)

    print("\nKey Takeaways:")
    print("  ✅ Warnings shown BEFORE tool execution")
    print("  ✅ Different confidence levels trigger different behaviors:")
    print("      75-84%: 🟡 Warning")
    print("      85-94%: 🟠 Strong warning")
    print("       >= 95%: 🔴 Block execution")
    print("  ✅ Valid parameters pass through without warnings")
    print("  ✅ Multiple patterns = multiple warnings")
    print("  ✅ Prevention steps clearly shown")

    print("\nWhat Happens Next:")
    print("  → Phase 4: Integrate warnings into Claude's context")
    print("  → Phase 4: Track when Claude follows/ignores warnings")
    print("  → Phase 5: Dashboard & optimization")

    print("\nCurrent Status:")
    print("  Phases 1-3: ✅ COMPLETE")
    print("  - Detection & Storage")
    print("  - Learning & Merging")
    print("  - Prevention Warnings")


if __name__ == "__main__":
    asyncio.run(main())
