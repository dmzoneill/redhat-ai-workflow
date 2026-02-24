#!/usr/bin/env python3
"""
Audit benchmark math for Q1 2026 peer backfill.
Verifies: peer_count, avg_overall_pct, stats_overall, comparable values,
self exclusion, score distributions, per-competency benchmarks, effective_target.
"""
import json
import statistics
from pathlib import Path

BASE = Path.home() / ".config/aa-workflow/performance/2026/q1/performance"
PEERS_DIR = BASE / "peers"
BENCHMARKS_PATH = PEERS_DIR / "benchmarks.json"
SELF_SUMMARY_PATH = BASE / "summary.json"

EXPECTED_EFFECTIVE_TARGET = {
    "ase": 65,
    "se": 90,
    "sse": 125,
    "pse": 160,
    "spse": 200,
    "de": 250,
}


def load_json(p: Path) -> dict:
    with open(p) as f:
        return json.load(f)


def main():
    benchmarks = load_json(BENCHMARKS_PATH)
    levels = benchmarks["levels"]

    errors = []
    report = []

    # 1. Benchmark math verification
    report.append("=" * 60)
    report.append("1. BENCHMARK MATH VERIFICATION")
    report.append("=" * 60)

    for level_name, level_data in levels.items():
        engineers = level_data["engineers"]
        peer_count = level_data["peer_count"]
        roster_count = level_data["roster_count"]
        avg_overall_pct = level_data["avg_overall_pct"]
        comparable_avg_overall_pct = level_data["comparable_avg_overall_pct"]
        stats = level_data["stats_overall"]
        comp_stats = level_data.get("comparable_stats_overall", {})

        # peer_count vs engineers list
        actual_count = len(engineers)
        if peer_count != actual_count:
            errors.append(
                f"{level_name}: peer_count={peer_count} but engineers list has {actual_count}"
            )
            report.append(
                f"  {level_name}: peer_count MISMATCH: {peer_count} vs {actual_count} engineers"
            )
        else:
            report.append(f"  {level_name}: peer_count={peer_count} ✓")

        # roster_count: should be peer_count (total peers at level, self excluded from benchmarks)
        if roster_count != peer_count:
            report.append(
                f"  {level_name}: roster_count={roster_count} (expected {peer_count})"
            )

        # Load peer summaries and compute expected values
        overall_pcts = []
        comparable_overalls = []
        for uname in engineers:
            summary_path = PEERS_DIR / uname / "summary.json"
            if not summary_path.exists():
                errors.append(f"{level_name}: Missing summary for {uname}")
                continue
            s = load_json(summary_path)
            overall_pcts.append(s.get("overall_percentage", 0))
            comparable_overalls.append(s.get("comparable_overall", 0))

        if overall_pcts:
            expected_avg = round(statistics.mean(overall_pcts), 1)
            if abs(expected_avg - avg_overall_pct) > 0.5:
                errors.append(
                    f"{level_name}: avg_overall_pct: expected {expected_avg}, got {avg_overall_pct}"
                )
                report.append(
                    f"  {level_name}: avg_overall_pct MISMATCH: expected {expected_avg}, got {avg_overall_pct}"
                )
            else:
                report.append(f"  {level_name}: avg_overall_pct={avg_overall_pct} ✓")

            expected_comp_avg = round(statistics.mean(comparable_overalls), 1)
            if abs(expected_comp_avg - comparable_avg_overall_pct) > 0.5:
                errors.append(
                    f"{level_name}: comparable_avg_overall_pct: expected {expected_comp_avg}, got {comparable_avg_overall_pct}"
                )
                report.append(
                    f"  {level_name}: comparable_avg_overall_pct MISMATCH: expected {expected_comp_avg}, got {comparable_avg_overall_pct}"
                )
            else:
                report.append(
                    f"  {level_name}: comparable_avg_overall_pct={comparable_avg_overall_pct} ✓"
                )

            # stats_overall verification
            expected_min = min(overall_pcts)
            expected_max = max(overall_pcts)
            expected_median = statistics.median(overall_pcts)
            expected_mean = round(statistics.mean(overall_pcts), 1)

            if stats["min"] != expected_min:
                errors.append(
                    f"{level_name}: stats_overall.min: expected {expected_min}, got {stats['min']}"
                )
            if stats["max"] != expected_max:
                errors.append(
                    f"{level_name}: stats_overall.max: expected {expected_max}, got {stats['max']}"
                )
            if abs(stats["median"] - expected_median) > 0.5:
                errors.append(
                    f"{level_name}: stats_overall.median: expected {expected_median}, got {stats['median']}"
                )
            if abs(stats["avg"] - expected_mean) > 0.5:
                errors.append(
                    f"{level_name}: stats_overall.avg: expected {expected_mean}, got {stats['avg']}"
                )
            if stats["count"] != len(overall_pcts):
                errors.append(
                    f"{level_name}: stats_overall.count: expected {len(overall_pcts)}, got {stats['count']}"
                )

            report.append(
                f"  {level_name}: stats_overall: min={stats['min']}, max={stats['max']}, "
                f"median={stats['median']}, avg={stats['avg']}, count={stats['count']}"
            )

    # 2. Self exclusion
    report.append("")
    report.append("=" * 60)
    report.append("2. SELF EXCLUSION (daoneill)")
    report.append("=" * 60)

    self_in_any = False
    for level_name, level_data in levels.items():
        if "daoneill" in level_data["engineers"]:
            self_in_any = True
            errors.append(f"daoneill appears in {level_name} engineers list!")
            report.append(f"  FAIL: daoneill in {level_name}")
    if not self_in_any:
        report.append("  ✓ daoneill does NOT appear in any level's engineers list")

    # 3. Score distribution analysis
    report.append("")
    report.append("=" * 60)
    report.append("3. SCORE DISTRIBUTION ANALYSIS")
    report.append("=" * 60)

    self_summary = load_json(SELF_SUMMARY_PATH)
    self_overall = self_summary.get("overall_percentage", 0)
    # daoneill is PSE from peers/daoneill/summary.json
    self_level = "pse"
    report.append(
        f"  Self (daoneill): overall_percentage={self_overall}, level={self_level}"
    )

    for level_name, level_data in levels.items():
        engineers = level_data["engineers"]
        overall_pcts = []
        for uname in engineers:
            s = load_json(PEERS_DIR / uname / "summary.json")
            overall_pcts.append(s.get("overall_percentage", 0))

        # Histogram
        bins = [0] * 10  # 0-10, 10-20, ..., 90-100
        for p in overall_pcts:
            idx = min(int(p / 10), 9) if p < 100 else 9
            bins[idx] += 1

        at_0 = sum(1 for p in overall_pcts if p == 0)
        at_100 = sum(1 for p in overall_pcts if p >= 100)

        report.append(f"\n  {level_name} (n={len(overall_pcts)}):")
        report.append(
            f"    Histogram: 0-10%:{bins[0]} 10-20%:{bins[1]} 20-30%:{bins[2]} 30-40%:{bins[3]} "
            f"40-50%:{bins[4]} 50-60%:{bins[5]} 60-70%:{bins[6]} 70-80%:{bins[7]} 80-90%:{bins[8]} 90-100%:{bins[9]}"
        )
        report.append(f"    At 0%: {at_0}, At 100%: {at_100}")

        # Where would self rank if compared to this level?
        if level_name == "pse":
            sorted_pcts = sorted(overall_pcts, reverse=True)
            rank = 1
            for i, p in enumerate(sorted_pcts):
                if self_overall > p:
                    rank = i + 1
                    break
                rank = i + 2
            report.append(
                f"    Self (77%) would rank ~{rank} of {len(overall_pcts)+1} (including self)"
            )

    # 4. Per-competency benchmark verification (ASE: collaboration, leadership)
    report.append("")
    report.append("=" * 60)
    report.append("4. PER-COMPETENCY BENCHMARK (ASE: collaboration, leadership)")
    report.append("=" * 60)

    ase_data = levels["ase"]
    ase_engineers = ase_data["engineers"]
    avg_comp = ase_data["avg_competency_pct"]

    for comp in ["collaboration", "leadership"]:
        pcts = []
        for uname in ase_engineers:
            s = load_json(PEERS_DIR / uname / "summary.json")
            cp = s.get("cumulative_percentage", {})
            pcts.append(cp.get(comp, 0))
        expected = round(statistics.mean(pcts), 1) if pcts else 0
        actual = avg_comp.get(comp, 0)
        if abs(expected - actual) > 1:
            errors.append(f"ASE {comp}: expected {expected}, got {actual}")
            report.append(f"  {comp}: MISMATCH expected {expected}, got {actual}")
        else:
            report.append(f"  {comp}: expected {expected}, got {actual} ✓")

    # 5. Comparable vs raw gap
    report.append("")
    report.append("=" * 60)
    report.append("5. COMPARABLE VS RAW GAP (should be small)")
    report.append("=" * 60)

    for level_name, level_data in levels.items():
        gap = level_data["avg_overall_pct"] - level_data["comparable_avg_overall_pct"]
        status = "✓" if abs(gap) <= 3 else "⚠ LARGE GAP"
        report.append(
            f"  {level_name}: avg_overall_pct={level_data['avg_overall_pct']}, "
            f"comparable_avg={level_data['comparable_avg_overall_pct']}, gap={gap} {status}"
        )
        if abs(gap) > 5:
            errors.append(f"{level_name}: Large comparable/raw gap: {gap}")

    # 6. effective_target audit
    report.append("")
    report.append("=" * 60)
    report.append("6. EFFECTIVE_TARGET AUDIT (5 peers from different levels)")
    report.append("=" * 60)

    sampled = []
    for level_name in levels:
        engineers = levels[level_name]["engineers"]
        if engineers:
            sampled.append((level_name, engineers[0]))

    for level_name, uname in sampled[:6]:
        s = load_json(PEERS_DIR / uname / "summary.json")
        et = s.get("effective_target")
        expected = EXPECTED_EFFECTIVE_TARGET.get(level_name)
        if et != expected:
            errors.append(
                f"{uname} ({level_name}): effective_target={et}, expected {expected}"
            )
            report.append(
                f"  {uname} ({level_name}): effective_target={et}, expected {expected} FAIL"
            )
        else:
            report.append(f"  {uname} ({level_name}): effective_target={et} ✓")

    # Summary
    report.append("")
    report.append("=" * 60)
    report.append("OVERALL VERDICT")
    report.append("=" * 60)

    if errors:
        report.append("INVALID: Math errors found")
        report.append("")
        report.append("Specific errors:")
        for e in errors:
            report.append(f"  - {e}")
    else:
        report.append("VALID: No math errors detected")

    report.append("")
    report.append(
        "Benchmarks trustworthy for comparison: " + ("NO" if errors else "YES")
    )

    print("\n".join(report))


if __name__ == "__main__":
    main()
