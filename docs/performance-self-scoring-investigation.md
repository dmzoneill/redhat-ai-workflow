# Deep Investigation: Self-Scoring Pipeline Inflation

**Date:** 2026-02-23
**Context:** User scores 77% with 1172 events; peers score 0-3%. Investigation into whether the user's score is inflated.

---

## Executive Summary

**Yes, the 77% score is inflated** relative to a fair peer-comparable baseline. The system already computes a **peer-comparable score of 70%** by excluding primary-only events (session, personal GDrive) and stripping the strategy bonus. The **7-point gap (77% → 70%)** is the direct inflation from:

1. **Session events** (321 events, 27% of total): 759 raw points from a source peers don't have
2. **Strategy alignment bonus** (1.5x): 32% of total points come from strategy-boosted events

**Additional inflation sources** (not yet normalized):

3. **Duplicate counting**: Same work unit (e.g., AAP-58394) counted 4× across git, gitlab, jira, session
4. **Multiplier stacking**: Scope × role × pillar × strategy can reach 180 points for a single event
5. **Target calibration**: Effective target (160 for PSE) may be achievable with routine activity

**Peer 0-3% scores** are likely due to **lack of peer data** (peers don't have session logs, may have limited git/gitlab/jira collection), not scoring bugs.

---

## 1. Event Source Breakdown

### Session Events (321 events, 27% of total)

**What are session events?**
Session events come from `memory/sessions/YYYY-MM-DD.yaml` — the daily session logs written by the AI workflow (session_close, skill completions, manual logs). The collector maps entries to event types like:

- `session_documented` — session_close summaries, skill completions (create_mr, close_issue, deploy_to_ephemeral, etc.)
- `meeting_participated` — schedule_meeting, calendar entries
- `alert_investigated` — investigate_alert skill
- `architecture_decision` — research_topic, compare_options

**Are they inflating the score?**
**Yes.** Session events are **primary-only** — peers have no equivalent. The system excludes them for `peer_comparable` scoring.

| Metric | Full (77%) | Peer-Comparable (70%) |
|--------|------------|------------------------|
| Total events | 1172 | 840 |
| Excluded | 332 (session + personal gdrive) | — |
| Session events | 321 | 0 (excluded) |

**Session contribution:** 168 of 321 session events have non-empty points, contributing **759 raw points** (before daily cap). After daily cap, the impact is distributed across competencies. Removing session would reduce the score by roughly **7 percentage points** (77% → 70%), which matches the peer_comparable gap.

**Example of low-quality session events:**
- `Scheduled meeting: Monthly 1:1 with Nigel Weather` — created 3 near-duplicate events (same meeting, different timestamps) with `meeting_participated` type. Most have `points: {}` (below min_signals) but still count toward total_events.
- `schedule_meeting` skill → `meeting_participated` — scheduling a meeting is scored like attending one.

---

## 2. Multiplier Stacking

**Formula:** `points = base × scope_mult × role_weight × pillar_weight × strategy_bonus`

All multipliers **compound**. There is no cap.

| Multiplier | Source | Example values (SSE) |
|------------|--------|----------------------|
| scope_mult | scope_multipliers | commit:1, story:2, epic:4, anstrat:7, **strategy:10** |
| role_weight | role_weights by scope | story/assignee: 0.8, strategy/assignee: **3.0** |
| pillar_weight | category | Technical: 1.0, Leadership: 1.0 |
| strategy_bonus | strategy_aligned | 1.0 or **1.5** |

**Maximum single event (creativity_innovation, base=4):**
```
4 × 10 (strategy scope) × 3.0 (assignee) × 1.0 (pillar) × 1.5 (strategy) = 180 points
```

**Concrete example from 2026-02-12:**
- Git commit `AAP-65345 - feat(ingress): extract bundles to Snowpipe S3` — scope=story, role=assignee
- Points: technical_contribution:1, creativity_innovation:3, scope:2
- Same work also appears as: gitlab MR, jira issue_resolved — each scored separately.

**Issue:** No cap on compounded multipliers. A single high-scope, strategy-aligned event can contribute 100+ points to one competency in one day (before daily_cap limits it to 15).

---

## 3. Strategy Bonus Impact

**Config:** `strategy_alignment.bonus_multiplier: 1.5`, `enabled: true`
**Executive emails loaded:** 5 (from myerskr@redhat.com, ikhan@redhat.com)

| Metric | Value |
|--------|-------|
| Strategy-aligned events | 88 |
| Points from strategy-aligned events | 1,759 |
| Total points (all events) | 5,469 |
| **Strategy % of total points** | **32.2%** |

**Interpretation:** Nearly one-third of raw points come from events that match executive email priorities (issue key or text overlap). The 1.5× bonus applies to every competency the event maps to. Peers can also get strategy bonuses if their Jira work matches the strategy index, but the user has more Jira/GitLab coverage, so they benefit more.

**peer_comparable** strips the strategy bonus from all events for fair comparison. That’s why peer_comparable_overall (70%) is lower than overall (77%).

---

## 4. Target Calibration

**User config:** `engineering_level: "pse"`, `target_per_competency: 100`
**competencies.yaml:** PSE `target_scale: 1.6`
**Effective target per competency:** `100 × 1.6 = 160` points

**Cumulative points vs target (sample):**

| Competency | Points | Target | % |
|------------|--------|--------|---|
| creativity_innovation | 486 | 160 | 100 (capped) |
| end_to_end_delivery | 388 | 160 | 100 |
| scope | 390 | 160 | 100 |
| technical_contribution | 252 | 160 | 100 |
| collaboration | 117 | 160 | 73 |
| technical_knowledge | 114 | 160 | 71 |
| evidence_record | 119 | 160 | 74 |
| leadership | 141 | 160 | 88 |
| execution_as_mentee | 30 | 160 | 19 |
| speaking_publicity | 15 | 160 | 9 |
| mentorship | 5 | 160 | 3 |

**Observation:** Many competencies hit 100% at 160 points. With 1172 events, daily_cap 15, and 38 days, the ceiling is 38 × 15 = 570 points per competency. Reaching 160 is ~28% of that ceiling. Routine activity (commits, MRs, Jira) can reach 100% on several competencies, so targets may be low for active engineers.

---

## 5. Event Quality

**Low-quality events scored like significant work:**

| Event | Source | Type | Points | Issue |
|-------|--------|------|--------|-------|
| "Scheduled meeting: Monthly 1:1 with Nigel Weather" | session | meeting_participated | 0 (min_signals) | Scheduling ≠ attending; near-duplicates |
| "investigated prometheus alert..." | session | alert_investigated | creativity_innovation: 3 | Alert check scored as innovation |
| GitHub PR "fix: handle missing interval key" (external org) | github | pr_opened | technical_contribution: 2, planning: 2 | Small fix, cross-org bonus |
| Jira "Update local build of pdf-generator" | jira | issue_resolved | {} (below threshold) | Minor task |

**High-quality events:** MR merged, issue resolved, commit with clear scope — these are appropriate. The problem is **parity**: trivial events (viewing a doc, scheduling a meeting) can score similarly to substantial work when they hit the same keywords/phrases.

---

## 6. Duplicate / Redundant Events

**Same work unit counted multiple times:**

| Issue | Events | Sources | Total raw pts |
|-------|--------|---------|---------------|
| AAP-58394 | 64 | git, gitlab, jira, session | 870 |
| AAP-62200 | 46 | git, gitlab, jira | 355 |
| AAP-61661 | 12 | git, gitlab | 204 |
| AAP-61679 | 11 | git, gitlab, jira | 88 |
| AAP-52095 | 6 | git, gitlab, jira | 47 |

**Pattern:** One unit of work (e.g., "Create staging environment with mock billing") produces:
1. **Git:** Multiple commits
2. **GitLab:** MR opened, MR merged, possibly review events
3. **Jira:** issue_resolved, issue_closed
4. **Session:** session_documented (session_close), skill completions (create_mr, close_issue)

So one story can generate **4+ event sources** and **10–60+ events**. Daily cap limits per-competency points per day, but the same work still drives multiple events and can max out several competencies on the same day.

---

## Quantified Inflation Summary

| Source | Estimated impact |
|--------|-------------------|
| Session events (primary-only) | ~7 pts (77% → 70% peer_comparable) |
| Strategy bonus (1.5×) | ~5–7 pts of the gap |
| Duplicate counting | Unbounded; daily_cap masks some impact |
| Multiplier stacking | Enables single-event spikes up to 180 pts |
| Low-quality event parity | Qualitative; no direct % |

**Total quantified:** 77% → 70% when using peer_comparable (session excluded, strategy stripped). The remaining 70% may still be high vs. peers if peer data is sparse.

---

## Recommended Fixes

### High priority

1. **Surface peer_comparable as primary metric**
   Use 70% (peer_comparable) as the main score in the UI when comparing to peers. Keep 77% as "full" score with a clear explanation.

2. **Session event quality filters**
   - Skip `schedule_meeting` → meeting_participated (scheduling ≠ attending)
   - Deduplicate near-identical session entries (e.g., same meeting, multiple timestamps)
   - Consider excluding session from overall score, or cap session points per day

3. **Deduplicate cross-source events**
   When the same Jira key or MR appears in git + gitlab + jira + session, either:
   - Merge into one event with enriched text, or
   - Count only the highest-scoring source per work unit per day

### Medium priority

4. **Cap compounded multiplier**
   E.g., `min(computed_points, base * 5)` to avoid single events dominating.

5. **Strategy bonus transparency**
   Show which events received the strategy bonus and how much it contributed.

6. **Revisit target calibration**
   Consider raising effective targets for PSE or adding a "stretch" target for 100%.

### Lower priority

7. **Event quality tiers**
   Weight events by type (e.g., mr_merged > commit > meeting_attended).

8. **Peer data collection**
   Investigate why peers show 0–3% — likely missing git/gitlab/session. Improve peer data coverage for meaningful comparison.

---

## Files Referenced

- `services/stats/daemon.py` — Summary computation, peer_comparable, primary-only exclusion
- `services/stats/scorer.py` — Competency mapping, multipliers, formula
- `services/stats/collector.py` — Session event collection, dedup logic
- `services/stats/strategy.py` — Strategy alignment matching
- `services/stats/competencies.yaml` — Level weights, target_scale
- `~/.config/aa-workflow/performance/2026/q1/performance/summary.json` — User summary
- `~/.config/aa-workflow/performance/2026/q1/performance/daily/*.json` — Daily events
