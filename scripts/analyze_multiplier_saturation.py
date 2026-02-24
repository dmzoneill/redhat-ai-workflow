#!/usr/bin/env python3
"""Analyze multiplier stacking, target saturation, and duplication impact on Q1 2026 scoring.

Data-driven report on whether formula changes are needed.
"""
from __future__ import annotations

import json
import re
import statistics
from pathlib import Path

PERF_BASE = Path.home() / ".config/aa-workflow/performance/2026/q1/performance"
SELF_DAILY = PERF_BASE / "daily"
SELF_SUMMARY = PERF_BASE / "summary.json"
PEERS_DIR = PERF_BASE / "peers"

# PSE effective_target = 100 * 1.6 = 160
PSE_TARGET_CURRENT = 160
PSE_TARGET_SIMULATED = 250


def load_json(p: Path) -> dict:
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def count_saturated(summary: dict, key: str = "cumulative_percentage") -> int:
    """Count competencies at 100% (saturated)."""
    pct = summary.get(key, {})
    return sum(1 for v in pct.values() if v >= 100)


def extract_jira_key(ev: dict) -> str | None:
    """Extract Jira key from event (item_id or title pattern AAP-XXXXX)."""
    key = ev.get("item_id")
    if key and re.match(r"[A-Z]+-\d+", str(key)):
        return str(key)
    title = ev.get("title", "")
    m = re.search(r"([A-Z]+-\d+)", title)
    return m.group(1) if m else None


def main() -> None:
    print("=" * 80)
    print("MULTIPLIER STACKING & TARGET SATURATION ANALYSIS - Q1 2026")
    print("=" * 80)

    # --- 1. Competency saturation analysis ---
    print("\n## 1. COMPETENCY SATURATION ANALYSIS")
    print("-" * 60)

    self_summary = load_json(SELF_SUMMARY)
    self_saturated = count_saturated(self_summary)
    self_total_comp = len(self_summary.get("cumulative_percentage", {}))
    print(f"Self: {self_saturated}/{self_total_comp} competencies at 100%")

    # Load all peer summaries, get top 5 by overall_percentage
    peer_summaries: list[tuple[str, dict]] = []
    for peer_dir in PEERS_DIR.iterdir():
        if not peer_dir.is_dir():
            continue
        summary_file = peer_dir / "summary.json"
        if not summary_file.exists():
            continue
        try:
            s = load_json(summary_file)
            if s.get("total_events", 0) < 10:  # Skip low-activity peers
                continue
            peer_summaries.append((peer_dir.name, s))
        except Exception:
            continue

    peer_summaries.sort(key=lambda x: x[1].get("overall_percentage", 0), reverse=True)
    top5 = peer_summaries[:5]

    print("\nTop 5 peers by overall_percentage (min 10 events):")
    for username, s in top5:
        sat = count_saturated(s)
        total = len(s.get("cumulative_percentage", {}))
        pct = s.get("overall_percentage", 0)
        ev = s.get("total_events", 0)
        level = s.get("level", "?")
        print(
            f"  {username} ({level}): {sat}/{total} at 100%, overall={pct}%, events={ev}"
        )

    pse_peers = [
        (u, s) for u, s in peer_summaries if s.get("level") == "pse" and u != "daoneill"
    ]
    pse_peers.sort(key=lambda x: x[1].get("overall_percentage", 0), reverse=True)
    top5_pse = pse_peers[:5]
    print("\nTop 5 PSE peers (same level as self):")
    for username, s in top5_pse:
        sat = count_saturated(s)
        total = len(s.get("cumulative_percentage", {}))
        pct = s.get("overall_percentage", 0)
        print(f"  {username}: {sat}/{total} at 100%, overall={pct}%")

    # --- 2. Points per competency vs effective_target ---
    print("\n## 2. POINTS PER COMPETENCY VS EFFECTIVE TARGET")
    print("-" * 60)

    self_points = self_summary.get("cumulative_points", {})
    self_et = self_summary.get("effective_target", PSE_TARGET_CURRENT)
    print(f"\nSelf (effective_target={self_et}):")
    overshoots = []
    for comp, pts in sorted(self_points.items(), key=lambda x: -x[1]):
        ratio = pts / self_et if self_et else 0
        overshoots.append((comp, pts, ratio))
        status = f"{ratio:.1f}x overshoot" if ratio > 1 else f"{ratio:.1f}x"
        print(f"  {comp}: {pts} pts (target {self_et}) = {status}")

    # Top 3 overshoots
    top_overshoots = sorted(overshoots, key=lambda x: -x[2])[:5]
    print(
        f"\n  Highest overshoots: {', '.join(f'{c}={r:.1f}x' for c, pts, r in top_overshoots)}"
    )

    # Compare with top PSE peer
    if top5_pse:
        peer_user, peer_s = top5_pse[0]
        peer_pts = peer_s.get("cumulative_points", {})
        peer_et = peer_s.get("effective_target", PSE_TARGET_CURRENT)
        print(f"\nTop PSE peer {peer_user} (effective_target={peer_et}):")
        for comp, pts in sorted(peer_pts.items(), key=lambda x: -x[1])[:8]:
            ratio = pts / peer_et if peer_et else 0
            print(f"  {comp}: {pts} pts = {ratio:.1f}x")

    # --- 3. Multiplier impact from daily files ---
    print("\n## 3. POINTS PER EVENT (from daily files)")
    print("-" * 60)

    def event_total_points(ev: dict) -> int:
        return sum(ev.get("points", {}).values())

    # Self: 3 busiest daily files (by scored event count)
    def scored_count(data: dict) -> int:
        return sum(1 for ev in data.get("events", []) if event_total_points(ev) > 0)

    self_all = list(SELF_DAILY.glob("*.json"))
    self_daily_files = sorted(
        self_all,
        key=lambda f: scored_count(load_json(f)),
        reverse=True,
    )[:3]
    self_event_pts: list[int] = []
    for df in self_daily_files:
        data = load_json(df)
        for ev in data.get("events", []):
            pt = event_total_points(ev)
            if pt > 0:
                self_event_pts.append(pt)

    # dvernier: 3 busiest daily files (658 events total)
    dvernier_daily = PEERS_DIR / "dvernier" / "daily"
    dvernier_pts: list[int] = []
    if dvernier_daily.exists():
        dvernier_all = list(dvernier_daily.glob("*.json"))
        files = sorted(
            dvernier_all,
            key=lambda f: scored_count(load_json(f)),
            reverse=True,
        )[:3]
        for df in files:
            data = load_json(df)
            for ev in data.get("events", []):
                pt = event_total_points(ev)
                if pt > 0:
                    dvernier_pts.append(pt)

    def stats(pts: list[int], label: str) -> None:
        if not pts:
            print(f"  {label}: no scored events")
            return
        print(
            f"  {label}: n={len(pts)}, mean={statistics.mean(pts):.1f}, "
            f"median={statistics.median(pts):.1f}, max={max(pts)}"
        )
        # Outliers > 20
        outliers = [p for p in pts if p > 20]
        if outliers:
            print(
                f"    Outliers (>20 pts/event): {len(outliers)} events, max={max(outliers)}"
            )

    print("\nPoints per scored event (3 daily files each):")
    stats(self_event_pts, "Self")
    stats(dvernier_pts, "dvernier (SSE, 658 events)")

    # --- 4. Strategy bonus analysis ---
    print("\n## 4. STRATEGY BONUS ANALYSIS")
    print("-" * 60)

    def strategy_stats(daily_dir: Path, label: str) -> tuple[int, int, int, int]:
        strategy_events = 0
        total_scored = 0
        strategy_pts = 0
        total_pts = 0
        for df in daily_dir.glob("*.json"):
            data = load_json(df)
            for ev in data.get("events", []):
                pts = ev.get("points", {})
                if not pts:
                    continue
                pt_sum = sum(pts.values())
                total_scored += 1
                total_pts += pt_sum
                if ev.get("strategy_aligned"):
                    strategy_events += 1
                    strategy_pts += pt_sum
        return strategy_events, total_scored, strategy_pts, total_pts

    s_ev, s_tot, s_pts, s_total_pts = strategy_stats(SELF_DAILY, "Self")
    print(
        f"Self: {s_ev}/{s_tot} events strategy_aligned ({100*s_ev/max(s_tot,1):.1f}%)"
    )
    print(
        f"      {s_pts}/{s_total_pts} points from strategy-boosted events ({100*s_pts/max(s_total_pts,1):.1f}%)"
    )

    # Compare with high-scoring peer (dvernier) and top PSE peer (simaishi)
    for username in ["dvernier", "simaishi"]:
        peer_daily = PEERS_DIR / username / "daily"
        if peer_daily.exists():
            p_ev, p_tot, p_pts, p_total_pts = strategy_stats(peer_daily, username)
            print(
                f"{username}: {p_ev}/{p_tot} events strategy_aligned ({100*p_ev/max(p_tot,1):.1f}%)"
            )
            print(
                f"         {p_pts}/{p_total_pts} points from strategy-boosted ({100*p_pts/max(p_total_pts,1):.1f}%)"
            )

    # --- 5. Cross-source duplication (events per Jira issue) ---
    print("\n## 5. CROSS-SOURCE DUPLICATION (events per Jira issue)")
    print("-" * 60)

    def events_per_issue(daily_dir: Path) -> tuple[dict[str, int], int, int]:
        by_issue: dict[str, list] = {}
        total_events = 0
        for df in daily_dir.glob("*.json"):
            data = load_json(df)
            for ev in data.get("events", []):
                total_events += 1
                key = extract_jira_key(ev)
                if key:
                    by_issue.setdefault(key, []).append(ev)
        counts = {k: len(v) for k, v in by_issue.items()}
        return counts, len(by_issue), total_events

    self_counts, self_issues, self_ev_total = events_per_issue(SELF_DAILY)
    self_ev_per_issue = list(self_counts.values()) if self_counts else []
    print(f"Self: {self_ev_total} events, {self_issues} distinct Jira issues")
    if self_ev_per_issue:
        print(
            f"      mean events/issue: {statistics.mean(self_ev_per_issue):.1f}, "
            f"median: {statistics.median(self_ev_per_issue):.0f}, max: {max(self_ev_per_issue)}"
        )
        high = [(k, v) for k, v in self_counts.items() if v >= 5]
        if high:
            print(f"      Issues with 5+ events: {len(high)}")
            for k, v in sorted(high, key=lambda x: -x[1])[:5]:
                print(f"        {k}: {v} events")

    # 2 well-populated peers
    for username in ["dvernier", "smcdonal"]:
        peer_daily = PEERS_DIR / username / "daily"
        if peer_daily.exists():
            counts, issues, ev_total = events_per_issue(peer_daily)
            ev_per = list(counts.values()) if counts else []
            print(f"\n{username}: {ev_total} events, {issues} distinct Jira issues")
            if ev_per:
                print(
                    f"         mean: {statistics.mean(ev_per):.1f}, median: {statistics.median(ev_per):.0f}, max: {max(ev_per)}"
                )

    # --- 6. Effective target simulation ---
    print("\n## 6. EFFECTIVE TARGET SIMULATION (PSE 250 vs 160)")
    print("-" * 60)

    def simulate_score(
        points: dict[str, int], target: int
    ) -> tuple[dict[str, int], float]:
        pct = {k: min(round(v / target * 100), 100) for k, v in points.items()}
        overall = sum(pct.values()) / max(len(pct), 1)
        return pct, overall

    self_pts = self_summary.get("cumulative_points", {})
    _, self_overall_160 = simulate_score(self_pts, PSE_TARGET_CURRENT)
    _, self_overall_250 = simulate_score(self_pts, PSE_TARGET_SIMULATED)
    print(f"Self: current target 160 -> overall {self_overall_160:.0f}%")
    print(
        f"      simulated target 250 -> overall {self_overall_250:.0f}% (delta: {self_overall_250 - self_overall_160:.0f}%)"
    )

    # Top PSE peer
    if top5_pse:
        peer_user, peer_s = top5_pse[0]
        peer_pts = peer_s.get("cumulative_points", {})
        _, p_overall_160 = simulate_score(peer_pts, PSE_TARGET_CURRENT)
        _, p_overall_250 = simulate_score(peer_pts, PSE_TARGET_SIMULATED)
        print(f"\nTop PSE peer {peer_user}: target 160 -> {p_overall_160:.0f}%")
        print(
            f"                    target 250 -> {p_overall_250:.0f}% (delta: {p_overall_250 - p_overall_160:.0f}%)"
        )

    # --- Summary / Conclusions ---
    print("\n" + "=" * 80)
    print("CONCLUSIONS")
    print("=" * 80)
    print(
        """
1. SATURATION: Self has more competencies at 100% than most peers. Top PSE peers
   typically have fewer saturated competencies. Saturation is more common for
   high-volume contributors but self's 9-11/16 is above average.

2. OVERSHOOT: Self's creativity_innovation, end_to_end_delivery, scope, etc.
   are 2-3x above target. Points above 100% cap are "wasted" — they don't
   increase overall score. Raising targets would reduce inflation.

3. POINTS PER EVENT: Distribution of points per event (mean, median, max) shows
   whether multiplier stacking creates extreme outliers. High max values
   indicate scope/strategy/epic multipliers stacking.

4. STRATEGY BONUS: Self's fraction of strategy-aligned events vs peers affects
   fairness. If self has significantly more strategy-boosted events, the
   peer_comparable normalization (which strips strategy) is important.

5. DUPLICATION: Events per Jira issue — high mean/median indicates the same
   work is being counted multiple times (git + gitlab + jira + session).
   Self vs peer comparison shows if duplication is worse for self.

6. TARGET SIMULATION: Raising PSE target from 160 to 250 would lower both self
   and top peer scores. The relative delta shows who benefits more from
   current low targets.
"""
    )


if __name__ == "__main__":
    main()
