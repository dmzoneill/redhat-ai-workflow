#!/usr/bin/env python3
"""
Optimize Usage Patterns.

Runs pruning and decay on learned patterns to keep the system lean.

Usage:
    python scripts/optimize_patterns.py [OPTIONS]

Options:
    --prune          Prune old low-confidence patterns
    --decay          Apply decay to inactive patterns
    --dry-run        Show what would be done without making changes
    --max-age DAYS   Maximum pattern age in days (default: 90)
    --min-conf PCT   Minimum confidence to keep (default: 0.70)
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def main():
    """Main entry point."""
    from server.usage_pattern_optimizer import UsagePatternOptimizer

    parser = argparse.ArgumentParser(description="Optimize Usage Patterns")

    parser.add_argument(
        "--prune",
        action="store_true",
        help="Prune old low-confidence patterns",
    )

    parser.add_argument(
        "--decay",
        action="store_true",
        help="Apply confidence decay to inactive patterns",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )

    parser.add_argument(
        "--max-age",
        type=int,
        default=90,
        help="Maximum pattern age in days (default: 90)",
    )

    parser.add_argument(
        "--min-conf",
        type=float,
        default=0.70,
        help="Minimum confidence to keep (default: 0.70)",
    )

    parser.add_argument(
        "--decay-rate",
        type=float,
        default=0.05,
        help="Decay rate per period (default: 0.05 = 5%%)",
    )

    parser.add_argument(
        "--inactive-months",
        type=int,
        default=1,
        help="Months of inactivity before decay (default: 1)",
    )

    args = parser.parse_args()

    # If no action specified, do everything
    if not args.prune and not args.decay:
        args.prune = True
        args.decay = True

    print("=" * 70)
    print("Layer 5: Pattern Optimization")
    print("=" * 70)
    print()

    if args.dry_run:
        print("🔍 DRY RUN MODE - No changes will be made")
        print()

    try:
        optimizer = UsagePatternOptimizer()

        # Get stats before
        stats_before = optimizer.get_optimization_stats()

        print("📊 Current State:")
        print(f"  Total patterns: {stats_before['total_patterns']}")
        print(f"  Old patterns (>{args.max_age} days): {stats_before['old_patterns']}")
        print(
            f"  Low confidence (<{args.min_conf:.0%}): {stats_before['low_confidence']}"
        )
        print(f"  Inactive (>30 days): {stats_before['inactive_patterns']}")
        print()
        print(f"  Candidates for pruning: {stats_before['candidates_for_pruning']}")
        print(f"  Candidates for decay: {stats_before['candidates_for_decay']}")
        print()

        # Run optimization
        result = optimizer.optimize(
            prune_old=args.prune,
            apply_decay=args.decay,
            max_age_days=args.max_age,
            min_confidence=args.min_conf,
            decay_rate=args.decay_rate,
            inactive_months=args.inactive_months,
            dry_run=args.dry_run,
        )

        # Print results
        print("✨ Optimization Results:")
        print()

        if args.decay:
            decayed = result["decayed"]
            print("  🔄 Decay Applied:")
            print(f"    Patterns decayed: {decayed['decayed_count']}")
            if decayed["decayed_count"] > 0:
                print(f"    Average decay: {decayed['avg_decay']:.1%}")
                print(f"    Pattern IDs: {', '.join(decayed['decayed_ids'][:5])}")
                if len(decayed["decayed_ids"]) > 5:
                    print(f"      ... and {len(decayed['decayed_ids']) - 5} more")
            print()

        if args.prune:
            pruned = result["pruned"]
            print("  🗑️  Pruning:")
            print(f"    Patterns pruned: {pruned['pruned_count']}")
            if pruned["pruned_count"] > 0:
                print(f"    Reason: {pruned['reason']}")
                print(f"    Pattern IDs: {', '.join(pruned['pruned_ids'][:5])}")
                if len(pruned["pruned_ids"]) > 5:
                    print(f"      ... and {len(pruned['pruned_ids']) - 5} more")
            print()

        print(f"  Total optimized: {result['total_optimized']} patterns")
        print()

        if args.dry_run:
            print("💡 Run without --dry-run to apply changes")
        else:
            print("✅ Optimization complete!")

        print()

    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
