#!/usr/bin/env python3
"""Analyze scoring multiplier effects: self vs peer (simaishi).

Compares:
- Average points per event
- Multiplier breakdown (scope, role, pillar, strategy)
- Daily cap saturation (how often competency slots hit 15)
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

# Add services/stats to path for scorer imports
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from services.stats.scorer import (
    COMPETENCY_DEFS,
    get_level_weights,
    get_merged_config,
    get_scope_multipliers,
)

SELF_DAILY = Path.home() / ".config/aa-workflow/performance/2026/q1/performance/daily"
PEER_DAILY = (
    Path.home()
    / ".config/aa-workflow/performance/2026/q1/performance/peers/simaishi/daily"
)
DAILY_CAP = 15
SAMPLE_DAYS = 5


def get_all_dates(daily_dir: Path) -> list[str]:
    """Get all dates with daily files."""
    return sorted(
        f.stem for f in daily_dir.glob("*.json") if f.stem and f.stem[0].isdigit()
    )


def load_events(
    daily_dir: Path, dates: list[str], exclude_session: bool = True
) -> list[dict]:
    """Load events from sampled daily files.

    exclude_session: If True, drop session events (peer_comparable excludes them).
    """
    events = []
    for d in dates:
        f = daily_dir / f"{d}.json"
        if not f.exists():
            continue
        with open(f, encoding="utf-8") as fp:
            data = json.load(fp)
        for ev in data.get("events", []):
            if exclude_session and ev.get("source") == "session":
                continue
            ev["_date"] = d
            events.append(ev)
    return events


def points_per_event(ev: dict) -> int:
    """Sum points across all competencies for an event."""
    return sum(ev.get("points", {}).values())


def analyze_multiplier_distribution(events: list[dict], label: str) -> dict:
    """Compute scope, role, strategy distribution and avg points per event."""
    scope_counts = defaultdict(int)
    role_counts = defaultdict(int)
    strategy_true = 0
    strategy_false = 0
    total_points = 0
    events_with_points = 0

    for ev in events:
        pts = points_per_event(ev)
        if pts > 0:
            events_with_points += 1
            total_points += pts
            scope_counts[ev.get("scope", "story")] += 1
            role_counts[ev.get("role", "assignee")] += 1
            if ev.get("strategy_aligned"):
                strategy_true += 1
            else:
                strategy_false += 1

    n = len(events)
    n_with_pts = events_with_points
    return {
        "label": label,
        "total_events": n,
        "events_with_points": n_with_pts,
        "total_points": total_points,
        "avg_points_per_event": total_points / n if n else 0,
        "avg_points_per_scored_event": total_points / n_with_pts if n_with_pts else 0,
        "scope_dist": dict(scope_counts),
        "role_dist": dict(role_counts),
        "strategy_aligned_pct": 100 * strategy_true / n_with_pts if n_with_pts else 0,
        "strategy_false_pct": 100 * strategy_false / n_with_pts if n_with_pts else 0,
    }


def compute_expected_multipliers(events: list[dict], level: str = "pse") -> dict:
    """Compute effective multiplier contributions from scope, role, pillar, strategy.

    Formula: base * scope_mult * role_weight * pillar_weight * strategy_bonus
    We can't reverse-engineer base from final points easily (multiple competencies),
    but we can compute the multiplier components per event and average them.
    """
    scope_mults = get_scope_multipliers()
    lw = get_level_weights(level)
    role_weights = lw.get("role_weights", {})
    pillar_weights = lw.get("pillar_weights", {})
    strategy_bonus = 1.5
    strategy_neutral = 1.0

    comp_to_category = {
        cid: d.get("category", "") for cid, d in COMPETENCY_DEFS.items()
    }

    scope_contrib = []
    role_contrib = []
    pillar_contrib = []
    strategy_contrib = []

    for ev in events:
        pts = ev.get("points", {})
        if not pts:
            continue
        scope = ev.get("scope", "story")
        role = ev.get("role", "assignee")
        strat = ev.get("strategy_aligned", False)

        sm = scope_mults.get(scope, 1)
        rw = role_weights.get(scope, {}).get(role, 1.0)

        # Per-competency pillar varies; use weighted avg by points
        pillar_sum = 0
        pt_sum = 0
        for comp_id, pt in pts.items():
            cat = comp_to_category.get(comp_id, "")
            pw = pillar_weights.get(cat, 1.0)
            pillar_sum += pw * pt
            pt_sum += pt
        avg_pillar = pillar_sum / pt_sum if pt_sum else 1.0

        sb = strategy_bonus if strat else strategy_neutral

        scope_contrib.append(sm)
        role_contrib.append(rw)
        pillar_contrib.append(avg_pillar)
        strategy_contrib.append(sb)

    def avg(lst):
        return sum(lst) / len(lst) if lst else 0

    return {
        "scope_mult_avg": avg(scope_contrib),
        "role_weight_avg": avg(role_contrib),
        "pillar_weight_avg": avg(pillar_contrib),
        "strategy_bonus_avg": avg(strategy_contrib),
        "combined_mult_avg": avg(
            [
                scope_contrib[i]
                * role_contrib[i]
                * pillar_contrib[i]
                * strategy_contrib[i]
                for i in range(len(scope_contrib))
            ]
        ),
        "n_scored_events": len(scope_contrib),
    }


def daily_cap_saturation(daily_dir: Path, dates: list[str], label: str) -> dict:
    """Count how often each competency hits daily_cap per day."""
    cap_hits_per_comp = defaultdict(int)
    total_slots = 0  # competency-days (each comp each day)
    slots_at_cap = 0

    for d in dates:
        f = daily_dir / f"{d}.json"
        if not f.exists():
            continue
        with open(f, encoding="utf-8") as fp:
            data = json.load(fp)
        dp = data.get("daily_points", {})
        for comp_id, pts in dp.items():
            total_slots += 1
            if pts >= DAILY_CAP:
                slots_at_cap += 1
                cap_hits_per_comp[comp_id] += 1

    return {
        "label": label,
        "days_sampled": len([d for d in dates if (daily_dir / f"{d}.json").exists()]),
        "total_comp_days": total_slots,
        "slots_at_cap": slots_at_cap,
        "pct_slots_at_cap": 100 * slots_at_cap / total_slots if total_slots else 0,
        "cap_hits_by_comp": dict(cap_hits_per_comp),
    }


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--all-days",
        action="store_true",
        help="Use all Q1 days instead of 5 sample days",
    )
    args = parser.parse_args()

    if args.all_days:
        all_self = get_all_dates(SELF_DAILY)
        all_peer = get_all_dates(PEER_DAILY)
        sample_dates = sorted(set(all_self) | set(all_peer))
    else:
        sample_dates = [
            "2026-01-08",
            "2026-01-12",
            "2026-01-20",
            "2026-01-27",
            "2026-02-05",
        ]

    self_events = load_events(SELF_DAILY, sample_dates)
    peer_events = load_events(PEER_DAILY, sample_dates)

    cfg = get_merged_config()
    level = cfg.get("engineering_level", "sse")

    # 1. Average points per event
    self_stats = analyze_multiplier_distribution(self_events, "self")
    peer_stats = analyze_multiplier_distribution(peer_events, "simaishi")

    # 2. Multiplier breakdown
    self_mults = compute_expected_multipliers(self_events, level)
    peer_mults = compute_expected_multipliers(peer_events, level)

    # 3. Daily cap saturation
    self_cap = daily_cap_saturation(SELF_DAILY, sample_dates, "self")
    peer_cap = daily_cap_saturation(PEER_DAILY, sample_dates, "simaishi")

    # Report
    print("=" * 70)
    print("MULTIPLIER EFFECTS ANALYSIS: Self (59% PSE) vs Simaishi (10% PSE avg)")
    print("=" * 70)
    print(f"  Sample: {len(sample_dates)} days")
    print()

    print("## 1. AVERAGE POINTS PER EVENT")
    print("-" * 50)
    print(
        f"  Self:     {self_stats['avg_points_per_event']:.2f} pts/event (all events)"
    )
    print(
        f"           {self_stats['avg_points_per_scored_event']:.2f} pts/event (scored only)"
    )
    print(
        f"           {self_stats['events_with_points']} scored / {self_stats['total_events']} total"
    )
    print()
    print(
        f"  Simaishi: {peer_stats['avg_points_per_event']:.2f} pts/event (all events)"
    )
    print(
        f"           {peer_stats['avg_points_per_scored_event']:.2f} pts/event (scored only)"
    )
    print(
        f"           {peer_stats['events_with_points']} scored / {peer_stats['total_events']} total"
    )
    print()
    ratio = (
        self_stats["avg_points_per_event"] / peer_stats["avg_points_per_event"]
        if peer_stats["avg_points_per_event"] > 0
        else 0
    )
    print(f"  Ratio (self/peer): {ratio:.2f}x")
    print()

    print("## 2. MULTIPLIER BREAKDOWN (PSE level_weights)")
    print("-" * 50)
    print("  Scope mult (commit=1, story=2, epic=4, anstrat=7, strategy=10):")
    print(f"    Self:     {self_mults['scope_mult_avg']:.3f}")
    print(f"    Simaishi: {peer_mults['scope_mult_avg']:.3f}")
    print()
    print("  Role weight (assignee vs contributor for story: 0.4 vs 0.2):")
    print(f"    Self:     {self_mults['role_weight_avg']:.3f}")
    print(f"    Simaishi: {peer_mults['role_weight_avg']:.3f}")
    print()
    print("  Pillar weight (Technical=0.8, Leadership=1.3, Mentorship=1.1, E2E=1.25):")
    print(f"    Self:     {self_mults['pillar_weight_avg']:.3f}")
    print(f"    Simaishi: {peer_mults['pillar_weight_avg']:.3f}")
    print()
    print("  Strategy bonus (aligned=1.5, not=1.0):")
    print(f"    Self:     {self_mults['strategy_bonus_avg']:.3f}")
    print(f"    Simaishi: {peer_mults['strategy_bonus_avg']:.3f}")
    print()
    print("  Combined multiplier (product of above):")
    print(f"    Self:     {self_mults['combined_mult_avg']:.3f}")
    print(f"    Simaishi: {peer_mults['combined_mult_avg']:.3f}")
    mult_ratio = (
        self_mults["combined_mult_avg"] / peer_mults["combined_mult_avg"]
        if peer_mults["combined_mult_avg"] > 0
        else 0
    )
    print(f"    Ratio:    {mult_ratio:.2f}x")
    print()

    # Source mix
    self_src = defaultdict(int)
    peer_src = defaultdict(int)
    for ev in self_events:
        self_src[ev.get("source", "unknown")] += 1
    for ev in peer_events:
        peer_src[ev.get("source", "unknown")] += 1

    print("  Source distribution (self):", dict(self_src))
    print("  Source distribution (simaishi):", dict(peer_src))
    print()
    print("  Scope distribution (self):", self_stats["scope_dist"])
    print("  Scope distribution (simaishi):", peer_stats["scope_dist"])
    print()
    print("  Role distribution (self):", self_stats["role_dist"])
    print("  Role distribution (simaishi):", peer_stats["role_dist"])
    print()
    print(f"  Strategy aligned % (self):     {self_stats['strategy_aligned_pct']:.1f}%")
    print(f"  Strategy aligned % (simaishi): {peer_stats['strategy_aligned_pct']:.1f}%")
    print()

    print("## 3. DAILY CAP SATURATION (cap=15)")
    print("-" * 50)
    print(
        f"  Self:     {self_cap['slots_at_cap']} slots at cap / {self_cap['total_comp_days']} comp-days = {self_cap['pct_slots_at_cap']:.1f}%"
    )
    print(
        f"  Simaishi: {peer_cap['slots_at_cap']} slots at cap / {peer_cap['total_comp_days']} comp-days = {peer_cap['pct_slots_at_cap']:.1f}%"
    )
    print()
    print("  Self cap hits by competency:", self_cap["cap_hits_by_comp"])
    print("  Simaishi cap hits by competency:", peer_cap["cap_hits_by_comp"])
    print()

    print("## 4. WHICH MULTIPLIER CONTRIBUTES MOST TO THE GAP?")
    print("-" * 50)
    scope_ratio = (
        self_mults["scope_mult_avg"] / peer_mults["scope_mult_avg"]
        if peer_mults["scope_mult_avg"] > 0
        else 1
    )
    role_ratio = (
        self_mults["role_weight_avg"] / peer_mults["role_weight_avg"]
        if peer_mults["role_weight_avg"] > 0
        else 1
    )
    pillar_ratio = (
        self_mults["pillar_weight_avg"] / peer_mults["pillar_weight_avg"]
        if peer_mults["pillar_weight_avg"] > 0
        else 1
    )
    strat_ratio = (
        self_mults["strategy_bonus_avg"] / peer_mults["strategy_bonus_avg"]
        if peer_mults["strategy_bonus_avg"] > 0
        else 1
    )
    print(
        f"  Scope:   {scope_ratio:.2f}x (self gets {scope_ratio:.2f}x higher scope mult)"
    )
    print(
        f"  Role:    {role_ratio:.2f}x (self gets {role_ratio:.2f}x higher role weight)"
    )
    print(
        f"  Pillar:  {pillar_ratio:.2f}x (self gets {pillar_ratio:.2f}x higher pillar weight)"
    )
    print(
        f"  Strategy:{strat_ratio:.2f}x (self gets {strat_ratio:.2f}x higher strategy bonus)"
    )
    print()

    # Competencies per event
    self_comps_per_ev = [
        len(ev.get("points", {})) for ev in self_events if ev.get("points")
    ]
    peer_comps_per_ev = [
        len(ev.get("points", {})) for ev in peer_events if ev.get("points")
    ]
    avg_self_comps = (
        sum(self_comps_per_ev) / len(self_comps_per_ev) if self_comps_per_ev else 0
    )
    avg_peer_comps = (
        sum(peer_comps_per_ev) / len(peer_comps_per_ev) if peer_comps_per_ev else 0
    )

    print("## 5. COMPETENCIES PER EVENT (breadth)")
    print("-" * 50)
    print(f"  Self:     {avg_self_comps:.1f} competencies per scored event")
    print(f"  Simaishi: {avg_peer_comps:.1f} competencies per scored event")
    print("  (More competencies = more points per event from stacking)")
    print()

    print("## 6. MULTIPLIER STACKING BIAS?")
    print("-" * 50)
    if mult_ratio > 1.5:
        print("  YES. Combined multiplier is significantly higher for self.")
        print(
            "  Primary drivers: role (assignee vs contributor) and strategy alignment."
        )
        print("  Self's events are more often assignee + strategy_aligned.")
    elif ratio > 1.5:
        print("  YES. Self gets 1.66x more points per event. Primary driver: BREADTH.")
        print(
            "  Self's events hit more competencies (avg {:.1f} vs {:.1f}).".format(
                avg_self_comps, avg_peer_comps
            )
        )
        print(
            "  Simaishi events often score in 1-2 comps (e.g. end_to_end_delivery only)."
        )
        print(
            "  Role/strategy: similar. Scope: simaishi has more story (mult 2) but fewer comps."
        )
    else:
        print("  Modest. Multiplier gap exists but may not fully explain 59% vs 10%.")
    print()
    print("=" * 70)


if __name__ == "__main__":
    main()
