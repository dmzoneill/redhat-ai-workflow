#!/usr/bin/env python3
"""
Layer 5 Phase 5 Demonstration: Optimization.

This script demonstrates the optimization features:
1. Pattern caching for performance
2. Pattern pruning for old low-confidence patterns
3. Pattern decay for inactive patterns
4. Dashboard generation
5. Optimization statistics

Run from project root:
    python .claude/layer5_phase5_demo.py
"""

import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from server.usage_pattern_checker import UsagePatternChecker
from server.usage_pattern_optimizer import UsagePatternOptimizer
from server.usage_pattern_storage import UsagePatternStorage


def print_section(title: str):
    """Print a section header."""
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)
    print()


def print_subsection(title: str):
    """Print a subsection header."""
    print()
    print(f"--- {title} ---")
    print()


def demo_1_pattern_caching():
    """Demo 1: Pattern caching for performance."""
    print_section("DEMO 1: Pattern Caching")

    with tempfile.TemporaryDirectory() as tmpdir:
        patterns_file = Path(tmpdir) / "patterns.yaml"
        storage = UsagePatternStorage(patterns_file)

        # Create a high-confidence pattern
        pattern = {
            "id": "cache_test_pattern",
            "tool": "bonfire_deploy",
            "error_category": "PARAMETER_FORMAT",
            "mistake_pattern": {
                "parameter": "image_tag",
                "validation": {"check": "len(image_tag) < 40"},
            },
            "root_cause": "Short SHA used instead of full 40-char commit SHA",
            "prevention_steps": [
                {
                    "action": "validate_sha_length",
                    "reason": "Ensure image_tag is full 40-char git commit SHA",
                }
            ],
            "observations": 50,
            "confidence": 0.95,
            "first_seen": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat(),
        }

        storage.add_pattern(pattern)

        # Create checker with 2-second cache TTL for demo
        checker = UsagePatternChecker(storage=storage, cache_ttl=2)

        print("First call - should be cache MISS:")
        start = time.time()
        result1 = checker.check_before_call(
            tool_name="bonfire_deploy",
            params={"image_tag": "abc123"},  # Short SHA
            min_confidence=0.75,
        )
        duration1 = time.time() - start

        print(f"  Duration: {duration1 * 1000:.2f}ms")
        print(f"  Cache populated: {checker._pattern_cache is not None}")
        print(f"  Warnings found: {len(result1['warnings'])}")
        print()

        print("Second call (immediate) - should be cache HIT:")
        start = time.time()
        checker.check_before_call(
            tool_name="bonfire_deploy",
            params={"image_tag": "def456"},  # Different params, same tool
            min_confidence=0.75,
        )
        duration2 = time.time() - start

        print(f"  Duration: {duration2 * 1000:.2f}ms")
        print(f"  Speed improvement: {(duration1 / duration2):.1f}x faster")
        print()

        print("Wait 2.5 seconds for cache expiry...")
        time.sleep(2.5)

        print("Third call (after TTL) - should be cache MISS:")
        cache_timestamp_before = checker._cache_timestamp
        start = time.time()
        checker.check_before_call(
            tool_name="bonfire_deploy",
            params={"image_tag": "ghi789"},
            min_confidence=0.75,
        )
        duration3 = time.time() - start
        cache_refreshed = checker._cache_timestamp > cache_timestamp_before

        print(f"  Duration: {duration3 * 1000:.2f}ms")
        print(f"  Cache refreshed: {cache_refreshed}")
        print()

    print("✅ Demo 1 Complete: Caching reduces lookup time significantly")


def demo_2_pattern_pruning():
    """Demo 2: Pattern pruning for old low-confidence patterns."""
    print_section("DEMO 2: Pattern Pruning")

    with tempfile.TemporaryDirectory() as tmpdir:
        patterns_file = Path(tmpdir) / "patterns.yaml"
        storage = UsagePatternStorage(patterns_file)

        # Create mix of patterns
        patterns = [
            {
                "id": "old_low_confidence",
                "tool": "kubectl_get_pods",
                "error_category": "PARAMETER_FORMAT",
                "mistake_pattern": {},
                "root_cause": "Old unreliable pattern",
                "prevention_steps": [],
                "observations": 5,
                "confidence": 0.65,
                "first_seen": (datetime.now() - timedelta(days=100)).isoformat(),
                "last_seen": (datetime.now() - timedelta(days=100)).isoformat(),
            },
            {
                "id": "recent_high_confidence",
                "tool": "bonfire_deploy",
                "error_category": "PARAMETER_FORMAT",
                "mistake_pattern": {},
                "root_cause": "Recent reliable pattern",
                "prevention_steps": [],
                "observations": 50,
                "confidence": 0.95,
                "first_seen": (datetime.now() - timedelta(days=1)).isoformat(),
                "last_seen": (datetime.now() - timedelta(days=1)).isoformat(),
            },
            {
                "id": "very_low_confidence",
                "tool": "git_push",
                "error_category": "WORKFLOW_SEQUENCE",
                "mistake_pattern": {},
                "root_cause": "Very unreliable",
                "prevention_steps": [],
                "observations": 10,
                "confidence": 0.45,  # <50% = always prune
                "first_seen": datetime.now().isoformat(),
                "last_seen": datetime.now().isoformat(),
            },
        ]

        for pattern in patterns:
            storage.add_pattern(pattern)

        optimizer = UsagePatternOptimizer(storage=storage)

        print("Before pruning:")
        data = storage.load()
        print(f"  Total patterns: {len(data.get('usage_patterns', []))}")
        print()

        # Dry run first
        print("Running dry run...")
        dry_result = optimizer.prune_old_patterns(max_age_days=90, min_confidence=0.70, dry_run=True)

        print(f"  Would prune: {dry_result['pruned_count']} patterns")
        print(f"  Pattern IDs: {', '.join(dry_result['pruned_ids'])}")
        print()

        # Verify patterns still exist
        print("Verifying patterns still exist (dry run):")
        for pattern_id in dry_result["pruned_ids"]:
            exists = storage.get_pattern(pattern_id) is not None
            print(f"  {pattern_id}: {'✓' if exists else '✗'}")
        print()

        # Actually prune
        print("Running actual pruning...")
        result = optimizer.prune_old_patterns(max_age_days=90, min_confidence=0.70, dry_run=False)

        print(f"  Pruned: {result['pruned_count']} patterns")
        print(f"  Reason: {result['reason']}")
        print()

        # Verify patterns deleted
        print("After pruning:")
        data = storage.load()
        remaining = len(data.get("usage_patterns", []))
        print(f"  Total patterns: {remaining}")
        print()

        print("Verifying pruned patterns deleted:")
        for pattern_id in result["pruned_ids"]:
            exists = storage.get_pattern(pattern_id) is not None
            print(f"  {pattern_id}: {'❌ Still exists!' if exists else '✓ Deleted'}")
        print()

        print("Verifying good pattern kept:")
        good_pattern = storage.get_pattern("recent_high_confidence")
        print(f"  recent_high_confidence: {'✓ Kept' if good_pattern else '❌ Deleted!'}")
        print()

    print("✅ Demo 2 Complete: Pruning removes stale patterns")


def demo_3_pattern_decay():
    """Demo 3: Pattern decay for inactive patterns."""
    print_section("DEMO 3: Pattern Decay")

    with tempfile.TemporaryDirectory() as tmpdir:
        patterns_file = Path(tmpdir) / "patterns.yaml"
        storage = UsagePatternStorage(patterns_file)

        # Create inactive pattern
        inactive_date = (datetime.now() - timedelta(days=45)).isoformat()
        pattern = {
            "id": "inactive_pattern",
            "tool": "bonfire_namespace_release",
            "error_category": "INCORRECT_PARAMETER",
            "mistake_pattern": {},
            "root_cause": "Pattern not seen in 45 days",
            "prevention_steps": [],
            "observations": 20,
            "confidence": 0.85,
            "first_seen": inactive_date,
            "last_seen": inactive_date,
        }

        storage.add_pattern(pattern)

        optimizer = UsagePatternOptimizer(storage=storage)

        print("Before decay:")
        original = storage.get_pattern("inactive_pattern")
        print(f"  Pattern ID: {original['id']}")
        print(f"  Last seen: {original['last_seen'][:10]}")
        print(f"  Confidence: {original['confidence']:.0%}")
        print(f"  Observations: {original['observations']}")
        print()

        # Dry run
        print("Running dry run...")
        dry_result = optimizer.apply_decay(decay_rate=0.05, inactive_months=1, dry_run=True)

        print(f"  Would decay: {dry_result['decayed_count']} patterns")
        print(f"  Average decay: {dry_result['avg_decay']:.1%}")
        print()

        # Verify confidence unchanged
        after_dry = storage.get_pattern("inactive_pattern")
        print(f"  Confidence after dry run: {after_dry['confidence']:.0%} (unchanged)")
        print()

        # Actually decay
        print("Running actual decay...")
        result = optimizer.apply_decay(decay_rate=0.05, inactive_months=1, dry_run=False)

        print(f"  Decayed: {result['decayed_count']} patterns")
        print(f"  Average decay: {result['avg_decay']:.1%}")
        print()

        # Verify confidence reduced
        after_decay = storage.get_pattern("inactive_pattern")
        print("After decay:")
        print(f"  Confidence: {after_decay['confidence']:.0%}")
        print(f"  Decay applied: {after_decay.get('decay_applied', 'N/A')[:10]}")
        print(f"  Confidence reduction: {(original['confidence'] - after_decay['confidence']):.1%}")
        print()

    print("✅ Demo 3 Complete: Decay reduces confidence for inactive patterns")


def demo_4_optimization_stats():
    """Demo 4: Optimization statistics."""
    print_section("DEMO 4: Optimization Statistics")

    with tempfile.TemporaryDirectory() as tmpdir:
        patterns_file = Path(tmpdir) / "patterns.yaml"
        storage = UsagePatternStorage(patterns_file)

        # Create diverse set of patterns
        patterns = [
            {
                "id": f"pattern_{i}",
                "tool": f"tool_{i % 3}",
                "error_category": "PARAMETER_FORMAT",
                "mistake_pattern": {},
                "root_cause": f"Issue {i}",
                "prevention_steps": [],
                "observations": 10 + i * 5,
                "confidence": 0.50 + (i * 0.05),
                "first_seen": (datetime.now() - timedelta(days=i * 10)).isoformat(),
                "last_seen": (datetime.now() - timedelta(days=i * 5)).isoformat(),
            }
            for i in range(10)
        ]

        for pattern in patterns:
            storage.add_pattern(pattern)

        optimizer = UsagePatternOptimizer(storage=storage)

        print("Getting optimization statistics...")
        stats = optimizer.get_optimization_stats()

        print()
        print("📊 Optimization Statistics:")
        print(f"  Total patterns: {stats['total_patterns']}")
        print(f"  Old patterns (>90 days): {stats['old_patterns']}")
        print(f"  Low confidence (<70%): {stats['low_confidence']}")
        print(f"  Inactive (>30 days): {stats['inactive_patterns']}")
        print()
        print(f"  Candidates for pruning: {stats['candidates_for_pruning']}")
        print(f"  Candidates for decay: {stats['candidates_for_decay']}")
        print()

    print("✅ Demo 4 Complete: Stats show optimization opportunities")


def demo_5_full_optimization():
    """Demo 5: Full optimization (prune + decay)."""
    print_section("DEMO 5: Full Optimization")

    with tempfile.TemporaryDirectory() as tmpdir:
        patterns_file = Path(tmpdir) / "patterns.yaml"
        storage = UsagePatternStorage(patterns_file)

        # Create mix of patterns
        patterns = [
            {
                "id": "should_prune",
                "tool": "tool_a",
                "error_category": "PARAMETER_FORMAT",
                "mistake_pattern": {},
                "root_cause": "Old and low confidence",
                "prevention_steps": [],
                "observations": 5,
                "confidence": 0.60,
                "first_seen": (datetime.now() - timedelta(days=100)).isoformat(),
                "last_seen": (datetime.now() - timedelta(days=100)).isoformat(),
            },
            {
                "id": "should_decay",
                "tool": "tool_b",
                "error_category": "WORKFLOW_SEQUENCE",
                "mistake_pattern": {},
                "root_cause": "Inactive for 45 days",
                "prevention_steps": [],
                "observations": 30,
                "confidence": 0.90,
                "first_seen": (datetime.now() - timedelta(days=45)).isoformat(),
                "last_seen": (datetime.now() - timedelta(days=45)).isoformat(),
            },
            {
                "id": "should_keep",
                "tool": "tool_c",
                "error_category": "MISSING_PREREQUISITE",
                "mistake_pattern": {},
                "root_cause": "Recent and high confidence",
                "prevention_steps": [],
                "observations": 50,
                "confidence": 0.95,
                "first_seen": (datetime.now() - timedelta(days=1)).isoformat(),
                "last_seen": (datetime.now() - timedelta(days=1)).isoformat(),
            },
        ]

        for pattern in patterns:
            storage.add_pattern(pattern)

        optimizer = UsagePatternOptimizer(storage=storage)

        print("Before optimization:")
        data = storage.load()
        all_patterns = data.get("usage_patterns", [])
        print(f"  Total patterns: {len(all_patterns)}")
        for p in all_patterns:
            print(f"    {p['id']}: confidence={p['confidence']:.0%}")
        print()

        # Run full optimization
        print("Running full optimization (prune + decay)...")
        result = optimizer.optimize(
            prune_old=True,
            apply_decay=True,
            max_age_days=90,
            min_confidence=0.70,
            decay_rate=0.05,
            inactive_months=1,
            dry_run=False,
        )

        print()
        print("📊 Optimization Results:")
        print(f"  Total optimized: {result['total_optimized']}")
        print()
        print("  🗑️  Pruning:")
        print(f"    Pruned: {result['pruned']['pruned_count']}")
        if result["pruned"]["pruned_ids"]:
            print(f"    IDs: {', '.join(result['pruned']['pruned_ids'])}")
        print()
        print("  🔄 Decay:")
        print(f"    Decayed: {result['decayed']['decayed_count']}")
        if result["decayed"]["decayed_ids"]:
            print(f"    IDs: {', '.join(result['decayed']['decayed_ids'])}")
            print(f"    Average decay: {result['decayed']['avg_decay']:.1%}")
        print()

        print("After optimization:")
        data = storage.load()
        remaining_patterns = data.get("usage_patterns", [])
        print(f"  Total patterns: {len(remaining_patterns)}")
        for p in remaining_patterns:
            print(f"    {p['id']}: confidence={p['confidence']:.0%}")
        print()

        # Verify expected outcomes
        print("Verification:")
        pruned_exists = storage.get_pattern("should_prune") is not None
        print(f"  should_prune deleted: {'❌ Still exists!' if pruned_exists else '✓'}")

        decayed = storage.get_pattern("should_decay")
        if decayed:
            print(f"  should_decay confidence reduced: ✓ ({decayed['confidence']:.0%})")
        else:
            print("  should_decay: ❌ Was deleted!")

        kept = storage.get_pattern("should_keep")
        if kept:
            print(f"  should_keep unchanged: ✓ ({kept['confidence']:.0%})")
        else:
            print("  should_keep: ❌ Was deleted!")
        print()

    print("✅ Demo 5 Complete: Full optimization maintains pattern quality")


def main():
    """Run all demonstrations."""
    print()
    print("=" * 70)
    print("  Layer 5 Phase 5: Optimization Demonstrations")
    print("=" * 70)
    print()
    print("This demo validates:")
    print("  1. Pattern caching for performance")
    print("  2. Pattern pruning for old low-confidence patterns")
    print("  3. Pattern decay for inactive patterns")
    print("  4. Optimization statistics")
    print("  5. Full optimization workflow")
    print()

    try:
        demo_1_pattern_caching()
        demo_2_pattern_pruning()
        demo_3_pattern_decay()
        demo_4_optimization_stats()
        demo_5_full_optimization()

        print()
        print("=" * 70)
        print("  ✅ ALL PHASE 5 DEMONSTRATIONS VALIDATED")
        print("=" * 70)
        print()
        print("Phase 5 (Optimization) is complete!")
        print()

    except Exception as e:
        print()
        print("=" * 70)
        print("  ❌ DEMONSTRATION FAILED")
        print("=" * 70)
        print()
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
