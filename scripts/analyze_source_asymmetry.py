#!/usr/bin/env python3
"""Analyze data source asymmetry between self and peers after Q1 2026 backfill.

Usage:
  python scripts/analyze_source_asymmetry.py

Output: Data-driven report quantifying how much of the self-vs-peer gap
comes from source asymmetry vs genuine performance difference.
"""

import json
from collections import defaultdict
from pathlib import Path

PERF_DIR = Path.home() / ".config/aa-workflow/performance/2026/q1/performance"
SELF_SUMMARY = PERF_DIR / "summary.json"
SELF_DAILY = PERF_DIR / "daily"
PEERS_DIR = PERF_DIR / "peers"
BENCHMARKS = PEERS_DIR / "benchmarks.json"

# Shared sources (both self and peers have)
SHARED_SOURCES = {"git", "github", "gitlab", "jira", "meeting"}
# Self-only sources (peers lack)
SELF_ONLY_SOURCES = {"session", "gdrive"}


def load_json(p: Path) -> dict:
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    self_summary = load_json(SELF_SUMMARY)
    benchmarks = load_json(BENCHMARKS)

    # Get peer summaries (exclude daoneill and benchmarks.json)
    peer_summaries: list[dict] = []
    for peer_dir in PEERS_DIR.iterdir():
        if not peer_dir.is_dir() or peer_dir.name == "benchmarks.json":
            continue
        summary_path = peer_dir / "summary.json"
        if summary_path.exists():
            try:
                s = load_json(summary_path)
                if s.get("username") != "daoneill":
                    peer_summaries.append(s)
            except Exception:
                pass

    # Build level -> peers mapping
    level_peers: dict[str, list[dict]] = defaultdict(list)
    for p in peer_summaries:
        level = p.get("level", "unknown")
        level_peers[level].append(p)

    # --- 1. Source breakdown self vs peers ---
    self_sources = self_summary.get("event_counts_by_source", {})
    print("=" * 60)
    print("1. SOURCE BREAKDOWN: SELF vs PEERS (avg per source by level)")
    print("=" * 60)
    print("Self event_counts_by_source:", self_sources)
    print()

    for level in ["ase", "se", "sse", "pse", "spse"]:
        if level not in benchmarks.get("levels", {}):
            continue
        peers = level_peers.get(level, [])
        if not peers:
            continue
        level_data = benchmarks["levels"][level]
        avg_by_source = level_data.get("avg_event_counts_by_source", {})
        print(f"  Level {level.upper()} (n={len(peers)}):")
        for src in ["git", "github", "gitlab", "jira", "meeting", "gdrive", "session"]:
            self_val = self_sources.get(src, 0)
            peer_avg = avg_by_source.get(src, 0)
            marker = "  [SELF-ONLY]" if src in SELF_ONLY_SOURCES else ""
            print(f"    {src}: self={self_val}, peer_avg={peer_avg:.1f}{marker}")
        print()

    # --- 2. Session event impact ---
    print("=" * 60)
    print("2. SESSION EVENT IMPACT")
    print("=" * 60)
    print("Self: 321 session events (27% of 1172 total)")
    print("Peers: 0 session events (session is self-only)")
    print()
    print("peer_comparable_overall: 70% (excludes session + personal gdrive)")
    print("overall_percentage: 77% (full score)")
    print("Gap: 7 points")
    print()
    print(
        "Session events may also boost competencies that OTHER sources contribute to."
    )
    print("To check: session events contribute points to competencies; if those same")
    print("competencies get points from git/gitlab/etc, the 7-point gap undercounts")
    print("session impact (double-counting).")

    # --- 3. Event volume comparison ---
    print()
    print("=" * 60)
    print("3. EVENT VOLUME COMPARISON")
    print("=" * 60)
    self_total = self_summary.get("total_events", 0)
    self_days = self_summary.get("day_of_quarter", 53)  # or days_captured
    # Try to get days from daily file count
    self_daily_files = list(SELF_DAILY.glob("*.json")) if SELF_DAILY.exists() else []
    self_days_with_data = len(self_daily_files)
    # Use days_captured from peers; self might use day_of_quarter
    self_events_per_day = self_total / 38 if self_total else 0  # 38 days in Q1
    print(f"Self: {self_total} events over ~38 days = {self_total/38:.1f} events/day")
    print()

    # Per-peer events/day
    events_per_day: list[tuple[str, str, float, int]] = []
    for p in peer_summaries:
        total = p.get("total_events", 0)
        days = p.get("days_captured", 1) or 1
        epd = total / days
        events_per_day.append((p["username"], p.get("level", "?"), epd, total))

    events_per_day.sort(key=lambda x: -x[2])
    print("Top 10 peers by events/day:")
    for i, (u, l, epd, tot) in enumerate(events_per_day[:10], 1):
        print(f"  {i}. {u} ({l}): {epd:.1f}/day ({tot} total)")
    print()
    print("Self events/day:", f"{self_total/38:.1f}")
    peer_epds = [x[2] for x in events_per_day]
    mean_peer_epd = sum(peer_epds) / len(peer_epds) if peer_epds else 0
    print(f"Mean peer events/day: {mean_peer_epd:.1f}")
    print(
        f"Self vs mean peer: {self_total/38:.1f} vs {mean_peer_epd:.1f} (self is {self_total/38/max(mean_peer_epd,0.1):.1f}x)"
    )

    # --- 4. Source-normalized comparison ---
    print()
    print("=" * 60)
    print("4. SOURCE-NORMALIZED COMPARISON (shared sources only)")
    print("=" * 60)
    self_shared = sum(self_sources.get(s, 0) for s in SHARED_SOURCES)
    print(
        f"Self events from shared sources (git, github, gitlab, jira, meeting): {self_shared}"
    )
    print()

    peer_shared_counts: list[int] = []
    for p in peer_summaries:
        ec = p.get("event_counts_by_source", {})
        shared = sum(ec.get(s, 0) for s in SHARED_SOURCES)
        peer_shared_counts.append(shared)

    if peer_shared_counts:
        mean_peer_shared = sum(peer_shared_counts) / len(peer_shared_counts)
        print(f"Peer mean shared-source events: {mean_peer_shared:.1f}")
        print(f"Peer max shared-source events: {max(peer_shared_counts)}")
        print(
            f"Self shared-source events: {self_shared} (vs peer mean {mean_peer_shared:.1f})"
        )

    # --- 5. Per-source scoring contribution ---
    print()
    print("=" * 60)
    print("5. PER-SOURCE SCORING CONTRIBUTION (competency points by source)")
    print("=" * 60)

    def points_by_source(daily_dir: Path) -> dict[str, int]:
        """Sum competency points per source (each event's points dict summed)."""
        by_src: dict[str, int] = defaultdict(int)
        if not daily_dir.exists():
            return dict(by_src)
        for f in daily_dir.glob("*.json"):
            try:
                data = load_json(f)
                for ev in data.get("events", []):
                    src = ev.get("source", "unknown")
                    pts = ev.get("points", {})
                    by_src[src] += sum(pts.values())
            except Exception:
                pass
        return dict(by_src)

    self_points_by_src = points_by_source(SELF_DAILY)
    print("Self competency points by source:")
    for src in sorted(self_points_by_src.keys()):
        print(f"  {src}: {self_points_by_src[src]}")
    print(f"  TOTAL: {sum(self_points_by_src.values())}")

    # Find 2 well-populated peers
    peer_totals = [(p, p.get("total_events", 0)) for p in peer_summaries]
    peer_totals.sort(key=lambda x: -x[1])
    for p, _ in peer_totals[:2]:
        uname = p["username"]
        daily_dir = PEERS_DIR / uname / "daily"
        pts = points_by_source(daily_dir)
        if sum(pts.values()) > 0:
            print(f"\nPeer {uname} ({p.get('level','?')}) competency points by source:")
            for src in sorted(pts.keys()):
                print(f"  {src}: {pts[src]}")
            print(f"  TOTAL: {sum(pts.values())}")

    # --- 6. Peer_comparable effectiveness ---
    print()
    print("=" * 60)
    print("6. PEER_COMPARABLE EFFECTIVENESS")
    print("=" * 60)
    self_pc = self_summary.get("peer_comparable_overall", 0)
    print(f"Self peer_comparable_overall: {self_pc}%")
    print()

    for level in ["ase", "se", "sse", "pse", "spse"]:
        if level not in benchmarks.get("levels", {}):
            continue
        ld = benchmarks["levels"][level]
        comp_avg = ld.get("comparable_avg_overall_pct", 0)
        comp_stats = ld.get("comparable_stats_overall", {})
        print(
            f"  {level.upper()}: comparable_avg={comp_avg}%, min={comp_stats.get('min',0)}, max={comp_stats.get('max',0)}, median={comp_stats.get('median',0)}"
        )
    print()
    print(
        "Self (70%) vs level averages: 22% (ase), 21% (se), 18% (sse), 15% (pse), 12% (spse)"
    )
    print("Gap: Self is 48-58 points above peer averages in peer_comparable.")

    # --- 7. What would fair look like ---
    print()
    print("=" * 60)
    print("7. WHAT WOULD FAIR LOOK LIKE?")
    print("=" * 60)
    session_pts = self_points_by_src.get("session", 0)
    gdrive_pts = self_points_by_src.get("gdrive", 0)
    total_pts = sum(self_points_by_src.values())
    shared_pts = total_pts - session_pts - gdrive_pts
    print(f"Self total competency points: {total_pts}")
    print(f"  From session: {session_pts}")
    print(f"  From gdrive (personal): {gdrive_pts}")
    print(f"  From shared sources: {shared_pts}")
    print()
    print("peer_comparable already strips session + personal gdrive from points.")
    print("So self's 70% peer_comparable IS the 'fair' score (same sources as peers).")
    print()
    print("If we simulated self with ONLY shared sources (no session/gdrive events):")
    print(
        f"  Self would have {self_shared} events (vs {self_total} with session+gdrive)"
    )
    print(
        f"  Points would be ~{shared_pts} (peer_comparable_points already reflect this)"
    )
    print()
    print("Conclusion: The 70% peer_comparable IS the source-normalized score.")
    print("The 7-point drop (77->70) is the direct session+gdrive impact.")
    print(
        "Session events may also boost competencies that OTHER sources contribute to,"
    )
    print(
        "so the true session impact could be >7 points if session points overlap with"
    )
    print("competencies that git/gitlab/etc also fill.")

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(
        """
- Peers get: git, github, gitlab, jira, meeting, (gdrive shared-drive only, ~0.4-1.4 avg)
- Self gets: all above PLUS session (321) and personal gdrive (11)

- Session: 27% of self events, 0 for peers. peer_comparable excludes it.
- The 7-point gap (77->70) is the direct exclusion of session+gdrive.
- Session may double-count with other sources: same competencies get points from
  both session and git/gitlab, so removing session might not fully remove 7 points
  if those competencies were already capped by other sources.

- Self events/day (30.8) is high vs peer mean (~3-4); top peers reach 16-17/day.
- Self's peer_comparable (70%) is 48-58 points above peer level averages (12-22%).
- Source asymmetry explains the 77 vs 70 gap; the remaining 70 vs peer-avg gap
  is either genuine performance difference or other factors (e.g. volume).
"""
    )


if __name__ == "__main__":
    main()
