#!/usr/bin/env python3
"""
Analyze Q1 2026 score distributions across peer levels.
Data: ~/.config/aa-workflow/performance/2026/q1/performance/
"""
import json
import os
from collections import defaultdict
from pathlib import Path

PEERS_DIR = Path.home() / ".config/aa-workflow/performance/2026/q1/performance/peers"
SELF_SUMMARY = (
    Path.home() / ".config/aa-workflow/performance/2026/q1/performance/summary.json"
)
BENCHMARKS = PEERS_DIR / "benchmarks.json"

BUCKETS = [
    (0, 5),
    (5, 10),
    (10, 20),
    (20, 30),
    (30, 40),
    (40, 50),
    (50, 60),
    (60, 70),
    (70, 80),
    (80, 90),
    (90, 100),
]


def bucket_label(lo, hi):
    return f"{lo}-{hi}%"


def get_bucket(pct):
    for lo, hi in BUCKETS:
        if lo <= pct < hi:
            return bucket_label(lo, hi)
    if pct == 100:
        return "90-100%"
    return "0-5%"


def load_all_peers():
    """Load all peer summaries with level mapping from benchmarks."""
    with open(BENCHMARKS) as f:
        benchmarks = json.load(f)
    level_to_engineers = benchmarks["levels"]
    username_to_level = {}
    for level, level_data in level_to_engineers.items():
        for username in level_data.get("engineers", []):
            username_to_level[username] = level

    peers = []
    for path in PEERS_DIR.iterdir():
        if path.is_dir() and not path.name.startswith("."):
            summary_path = path / "summary.json"
            if summary_path.exists():
                with open(summary_path) as f:
                    data = json.load(f)
                username = data.get("username", path.name)
                data["level"] = username_to_level.get(username, "unknown")
                peers.append(data)
    return peers


def load_self():
    with open(SELF_SUMMARY) as f:
        return json.load(f)


def main():
    print("=" * 70)
    print("Q1 2026 PERFORMANCE SCORE DISTRIBUTION ANALYSIS")
    print("=" * 70)

    peers = load_all_peers()
    self_data = load_self()

    self_overall = self_data["overall_percentage"]
    self_comparable = self_data["peer_comparable_overall"]
    self_events = self_data["total_events"]

    # Override daoneill in peers with self summary values (77% overall, 70% comparable)
    for p in peers:
        if p["username"] == "daoneill":
            p["overall_percentage"] = self_overall
            p["comparable_overall"] = self_comparable
            p["level"] = "pse"  # self is PSE level
            break
    self_days = self_data.get("days_with_events")  # may not exist in main summary

    # Get self days from peer summary if available
    self_peer_path = PEERS_DIR / "daoneill" / "summary.json"
    if self_peer_path.exists():
        with open(self_peer_path) as f:
            self_peer = json.load(f)
        self_days = self_peer.get("days_with_events")
    else:
        self_days = None

    print(
        f"\nSELF (daoneill, PSE): overall={self_overall}%, comparable={self_comparable}%"
    )
    print(f"  total_events={self_events} (main summary), days_with_events={self_days}")

    # 1. Score histogram per level
    print("\n" + "=" * 70)
    print("1. SCORE HISTOGRAM PER LEVEL")
    print("=" * 70)

    for level in ["ase", "se", "sse", "pse", "spse", "de"]:
        level_peers = [p for p in peers if p["level"] == level]
        if not level_peers:
            continue

        hist_overall = defaultdict(int)
        hist_comparable = defaultdict(int)
        for p in level_peers:
            hist_overall[get_bucket(p["overall_percentage"])] += 1
            hist_comparable[
                get_bucket(p.get("comparable_overall", p["overall_percentage"]))
            ] += 1

        print(f"\n--- {level.upper()} (n={len(level_peers)}) ---")
        print("  overall_percentage:")
        for lo, hi in BUCKETS:
            lbl = bucket_label(lo, hi)
            count = hist_overall[lbl]
            bar = "█" * count + "░" * (max(0, 15 - count))
            print(f"    {lbl:8} {count:3} {bar}")
        print("  comparable_overall:")
        for lo, hi in BUCKETS:
            lbl = bucket_label(lo, hi)
            count = hist_comparable[lbl]
            bar = "█" * count + "░" * (max(0, 15 - count))
            print(f"    {lbl:8} {count:3} {bar}")

    # 2. PSE peer rankings (use main self summary: 77% overall, 70% comparable)
    print("\n" + "=" * 70)
    print("2. PSE PEER RANKINGS (where self ranks)")
    print("=" * 70)

    pse_peers = [p for p in peers if p["level"] == "pse"]
    pse_by_overall = sorted(
        pse_peers, key=lambda p: p["overall_percentage"], reverse=True
    )
    pse_by_comparable = sorted(
        pse_peers,
        key=lambda p: p.get("comparable_overall", p["overall_percentage"]),
        reverse=True,
    )

    print("\nPSE peers by overall_percentage (descending):")
    for i, p in enumerate(pse_by_overall, 1):
        comp = p.get("comparable_overall", p["overall_percentage"])
        marker = " <-- SELF" if p["username"] == "daoneill" else ""
        print(
            f"  {i:2}. {p['username']:12} overall={p['overall_percentage']:3}% comparable={comp:3}% events={p.get('total_events',0):5}{marker}"
        )

    self_overall_rank = next(
        i for i, p in enumerate(pse_by_overall, 1) if p["username"] == "daoneill"
    )
    self_comparable_rank = next(
        i for i, p in enumerate(pse_by_comparable, 1) if p["username"] == "daoneill"
    )
    print(
        f"\n  Self rank: {self_overall_rank}/{len(pse_peers)} by overall ({self_overall}%)"
    )
    print(
        f"  Self rank: {self_comparable_rank}/{len(pse_peers)} by comparable ({self_comparable}%)"
    )

    # 3. Cross-level percentile
    print("\n" + "=" * 70)
    print("3. CROSS-LEVEL PERCENTILE (all 135 peers)")
    print("=" * 70)

    all_comparable = []
    for p in peers:
        comp = p.get("comparable_overall", p["overall_percentage"])
        all_comparable.append((p["username"], p["level"], comp))

    all_comparable.sort(key=lambda x: x[2], reverse=True)
    n = len(all_comparable)
    self_global_rank = next(
        i for i, (u, _, _) in enumerate(all_comparable, 1) if u == "daoneill"
    )
    percentile = 100 * (n - self_global_rank) / n if n > 0 else 0
    print(f"\n  All peers sorted by comparable_overall (descending):")
    print(f"  Self (70%) ranks #{self_global_rank} of {n} peers")
    print(f"  Percentile: {percentile:.1f}th (top {100-percentile:.1f}%)")

    # 4. Top performers per level
    print("\n" + "=" * 70)
    print("4. TOP 3 PERFORMERS PER LEVEL")
    print("=" * 70)

    for level in ["ase", "se", "sse", "pse", "spse", "de"]:
        level_peers = [p for p in peers if p["level"] == level]
        if not level_peers:
            continue
        top = sorted(
            level_peers,
            key=lambda p: p.get("comparable_overall", p["overall_percentage"]),
            reverse=True,
        )[:3]
        print(f"\n  {level.upper()}:")
        for p in top:
            comp = p.get("comparable_overall", p["overall_percentage"])
            events = p.get("total_events", 0)
            days = p.get("days_with_events", "?")
            above_60 = " *** >60%" if comp > 60 else ""
            print(
                f"    {p['username']:12} comparable={comp:3}% events={events:5} days={days}{above_60}"
            )

    # 5. Event count vs score correlation
    print("\n" + "=" * 70)
    print("5. EVENT COUNT vs SCORE CORRELATION")
    print("=" * 70)

    with_events = [
        (p["total_events"], p.get("comparable_overall", p["overall_percentage"]))
        for p in peers
        if p.get("total_events", 0) > 0
    ]
    if with_events:
        n = len(with_events)
        events_list = [e for e, _ in with_events]
        scores_list = [s for _, s in with_events]
        mean_e = sum(events_list) / n
        mean_s = sum(scores_list) / n
        var_e = sum((e - mean_e) ** 2 for e in events_list) / n
        var_s = sum((s - mean_s) ** 2 for s in scores_list) / n
        cov = sum((e - mean_e) * (s - mean_s) for e, s in with_events) / n
        if var_e > 0 and var_s > 0:
            corr = cov / (var_e**0.5 * var_s**0.5)
        else:
            corr = 0
        print(f"\n  Peers with >0 events: {n}")
        print(f"  Pearson correlation (total_events, comparable_overall): {corr:.3f}")
        print(f"  Mean events: {mean_e:.1f}, Mean score: {mean_s:.1f}%")
        # Binned view
        bins = [(0, 50), (50, 150), (150, 300), (300, 500), (500, 1000), (1000, 10000)]
        print("\n  Score by event bin:")
        for lo, hi in bins:
            subset = [s for e, s in with_events if lo <= e < hi]
            if subset:
                avg = sum(subset) / len(subset)
                print(
                    f"    {lo:4}-{hi:4} events: n={len(subset):3} avg_score={avg:.1f}%"
                )

    # 6. Days with events analysis
    print("\n" + "=" * 70)
    print("6. DAYS WITH EVENTS ANALYSIS")
    print("=" * 70)

    peers_with_days = [p for p in peers if p.get("days_with_events") is not None]
    days_list = [p["days_with_events"] for p in peers_with_days]
    if days_list:
        days_list.sort()
        n = len(days_list)
        mean_d = sum(days_list) / n
        median_d = (
            days_list[n // 2]
            if n % 2
            else (days_list[n // 2 - 1] + days_list[n // 2]) / 2
        )
        print(f"\n  Peers with days_with_events: {n}")
        print(f"  Mean days_with_events: {mean_d:.1f}")
        print(f"  Median days_with_events: {median_d:.1f}")

    print("\n  Per level:")
    for level in ["ase", "se", "sse", "pse", "spse", "de"]:
        level_peers = [
            p
            for p in peers
            if p["level"] == level and p.get("days_with_events") is not None
        ]
        if not level_peers:
            continue
        days = [p["days_with_events"] for p in level_peers]
        scores = [
            p.get("comparable_overall", p["overall_percentage"]) for p in level_peers
        ]
        mean_d = sum(days) / len(days)
        median_d = sorted(days)[len(days) // 2]
        mean_s = sum(scores) / len(scores)
        # Correlation days vs score
        n = len(level_peers)
        mean_days = sum(days) / n
        mean_sc = sum(scores) / n
        cov = sum((d - mean_days) * (s - mean_sc) for d, s in zip(days, scores)) / n
        var_d = sum((d - mean_days) ** 2 for d in days) / n
        var_s = sum((s - mean_sc) ** 2 for s in scores) / n
        corr = cov / (var_d**0.5 * var_s**0.5) if var_d > 0 and var_s > 0 else 0
        print(
            f"    {level.upper()}: mean_days={mean_d:.1f} median_days={median_d} mean_score={mean_s:.1f}% corr(days,score)={corr:.3f}"
        )

    print("\n" + "=" * 70)
    print("END REPORT")
    print("=" * 70)


if __name__ == "__main__":
    main()
