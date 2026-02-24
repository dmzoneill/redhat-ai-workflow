# Multiplier Effects Analysis: Self (59%) vs PSE Peer Simaishi (10%)

**Investigation:** How do multipliers (scope, role, pillar, strategy) affect point totals differently for self vs peers? Does multiplier stacking explain the 59% vs 10% gap?

**Data:** Q1 2026 daily files (39 days), self vs simaishi. Session events excluded (peer_comparable excludes them).

---

## Executive Summary

| Finding | Result |
|---------|--------|
| **Multiplier stacking bias** | **NO.** Simaishi has *higher* combined multiplier (0.91 vs 0.72). Multipliers do NOT inflate self. |
| **Primary driver of gap** | **Competency breadth.** Self's events hit 2.5 competencies on average vs 1.7 for simaishi. |
| **Points per event** | Self: 4.67 pts/event (all), 5.71 (scored). Simaishi: 3.36 / 4.72. Ratio: 1.39×. |
| **Daily cap saturation** | Simaishi hits cap *more* often (25% vs 16.7% of comp-days). Cap is not limiting peers. |
| **Event volume** | Self: 851 events (excl. session). Simaishi: 648. ~1.3× more events. |

---

## 1. Scoring Formula (from `scorer.py`)

```
points = base_points × scope_mult × role_weight × pillar_weight × strategy_bonus
```

**Multipliers (PSE level, from `competencies.yaml`):**

| Factor | Values |
|--------|--------|
| **scope_mult** | commit=1, doc=2, meeting=1, story=2, epic=4, anstrat=7, strategy=10 |
| **role_weight** | reporter/assignee/contributor per scope (e.g. story: 0.5/0.4/0.2) |
| **pillar_weight** | Technical=0.8, Leadership=1.3, Mentorship=1.1, E2E=1.25 |
| **strategy_bonus** | 1.5 if aligned, 1.0 otherwise |

---

## 2. Average Points per Event

| Metric | Self | Simaishi | Ratio |
|--------|------|----------|-------|
| Total events (excl. session) | 851 | 648 | 1.31× |
| Scored events | 790 | 461 | 1.71× |
| Avg pts/event (all) | 5.53 | 3.36 | 1.65× |
| Avg pts/event (scored) | 5.96 | 4.72 | 1.26× |

---

## 3. Multiplier Breakdown

**Average multiplier components (scored events only):**

| Multiplier | Self | Simaishi | Self/Peer |
|------------|------|----------|-----------|
| Scope mult | 1.77 | 1.90 | 0.93× |
| Role weight | 0.40 | 0.39 | 1.02× |
| Pillar weight | 0.91 | 1.12 | 0.82× |
| Strategy bonus | 1.05 | 1.11 | 0.95× |
| **Combined** | **0.69** | **0.91** | **0.76×** |

**Conclusion:** Simaishi's events get *higher* multipliers on average. Self does NOT benefit from multiplier inflation.

**Why?** Simaishi has more story-scope events (414 vs 730 for self, but self also has 168 commit). Story has mult 2; commit has mult 1. Simaishi's events also land in higher-pillar competencies (E2E=1.25) more often.

---

## 4. Scope, Role, Strategy Distribution

| Factor | Self | Simaishi |
|--------|------|----------|
| **Scope** | commit 168, story 563, doc 11, epic 12, meeting 36 | story 414, commit 47 |
| **Role** | assignee 518, contributor 110, reporter 162 | assignee 387, contributor 41, reporter 33 |
| **Strategy aligned %** | 10.1% | 21.9% |

Simaishi has *more* strategy-aligned events (21.9% vs 9.0%). Strategy bonus is not inflating self.

---

## 5. Source Mix (Event Types)

| Source | Self | Simaishi |
|--------|------|----------|
| git | 286 | 65 |
| gitlab | 138 | 477 |
| github | 255 | 32 |
| jira | 63 | 69 |
| meeting | 98 | 5 |
| gdrive | 11 | 0 |
| session | 321 (excluded) | 0 |

Self has rich git/github/gitlab + meetings. Simaishi is heavily gitlab (477). Git commits with detailed messages hit more competencies (technical_contribution, creativity_innovation, scope, etc.).

---

## 6. Competency Breadth (Key Driver)

| Metric | Self | Simaishi |
|--------|------|----------|
| Competencies per scored event | **2.7** | **1.7** |
| Ratio | — | 1.59× |

Self's events trigger more competency matches. Each event contributes to more buckets. Simaishi events often score in 1–2 competencies (e.g. end_to_end_delivery only for Jira issue_resolved).

---

## 7. Daily Cap Saturation (cap=15)

| Metric | Self | Simaishi |
|--------|------|----------|
| Comp-days at cap | 65 / 390 | 42 / 168 |
| % slots at cap | 16.7% | **25.0%** |

Simaishi hits the daily cap *more* often. The cap is not suppressing peer scores.

**Cap hits by competency:**

- Self: creativity_innovation (21), continuous_improvement (9), end_to_end_delivery (11), etc.
- Simaishi: end_to_end_delivery (19), creativity_innovation (11), scope (9)

---

## 8. Which Multiplier Contributes Most to the Gap?

**None.** All multiplier components are similar or favor simaishi:

- Scope: simaishi slightly higher (more story)
- Role: nearly identical
- Pillar: simaishi higher (more E2E)
- Strategy: simaishi higher (21.9% vs 9.0% aligned)

---

## 9. Is Multiplier Stacking a Remaining Bias?

**No.** Multiplier stacking does not explain the 59% vs 10% gap.

**Actual drivers:**

1. **Competency breadth** — Self's events hit 2.5 competencies vs 1.7. Richer event text (git commits, MRs) triggers more phrase/keyword matches.
2. **Event volume** — Self has ~1.3× more events (excluding session).
3. **Source mix** — Self has git, github, gitlab, meetings, gdrive. Simaishi is mostly gitlab + jira. Git commits with commit messages and MR descriptions produce more signals.

---

## 10. Recommendations

1. **Do not adjust multipliers** — They are not biased toward self.
2. **Consider competency breadth normalization** — If desired, cap competencies-per-event or normalize by breadth to reduce the advantage of rich, multi-topic events.
3. **Cross-source duplication** — Per `performance-multiplier-saturation-report.md`, self has 5.1 events/issue vs 1.8 for peers. Deduplication may be more impactful than multiplier changes.
4. **Daily cap** — Current cap (15) is not limiting peers; simaishi hits it more often than self.

---

## Appendix: Script

Run: `python scripts/analyze_multiplier_effects.py [--all-days]`
