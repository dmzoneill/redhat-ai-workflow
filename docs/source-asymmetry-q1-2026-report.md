# Data Source Asymmetry Analysis: Self vs Peers (Q1 2026 Backfill Complete)

**Date:** 2026-02-23
**Goal:** Quantify how much of the scoring gap between self and peers comes from data sources that peers lack vs genuine performance difference.

---

## Executive Summary

| Metric | Finding |
|--------|---------|
| **Source asymmetry impact** | 7 percentage points (77% → 70% when session+gdrive excluded) |
| **Session events** | 321 events (27% of self total); 0 for peers |
| **Self-only sources** | `session` (321 events), personal `gdrive` (11 events) |
| **Shared-source event volume** | Self: 840; Peer mean: 118.5; Peer max: 658 |
| **Self events/day** | 30.8 vs peer mean 3.1 (10x); top peers reach 16–17/day |
| **peer_comparable gap** | Self 70% vs peer level averages 12–22% (48–58 point gap) |

**Conclusion:** The 7-point drop from full score (77%) to peer_comparable (70%) is the direct impact of source asymmetry. The remaining gap (70% vs peer averages 12–22%) is driven by event volume and performance on shared sources, not by sources peers lack.

---

## 1. Source Breakdown: Self vs Peers by Level

### Self event counts by source

| Source | Count | % of Total |
|--------|-------|------------|
| session | 321 | 27.4% |
| git | 286 | 24.4% |
| github | 255 | 21.8% |
| gitlab | 138 | 11.8% |
| meeting | 98 | 8.4% |
| jira | 63 | 5.4% |
| gdrive | 11 | 0.9% |
| **Total** | **1172** | 100% |

### Peer average event counts by source (by level)

| Source | ASE | SE | SSE | PSE | SPSE | Peers get? |
|--------|-----|-----|-----|-----|------|------------|
| git | 22.2 | 18.0 | 30.2 | 35.0 | 35.2 | ✓ |
| github | 8.8 | 20.1 | 28.3 | 40.5 | 41.8 | ✓ |
| gitlab | 37.9 | 4.8 | 10.6 | 26.6 | 2.5 | ✓ |
| jira | 18.1 | 29.9 | 40.9 | 32.9 | 11.4 | ✓ |
| meeting | 17.0 | 17.8 | 12.2 | 13.0 | 25.6 | ✓ |
| gdrive | 0.4 | 0.9 | 0.8 | 1.0 | 1.4 | Shared-drive only |
| **session** | **0** | **0** | **0** | **0** | **0** | ✗ Self-only |

**Sources peers lack:** `session` (0 for all peers). Personal `gdrive` (non–shared-drive) is also self-only; peer gdrive is shared-drive only (~0.4–1.4 events avg).

---

## 2. Session Event Impact

- **Self:** 321 session events (27% of 1172 total)
- **Peers:** 0 session events
- **peer_comparable_overall:** 70% (excludes session + personal gdrive)
- **overall_percentage:** 77%
- **Direct gap:** 7 percentage points

### Double-counting question

Session events contribute competency points. If the same competencies also receive points from git/gitlab/jira/etc., daily caps can limit how much session adds. In that case:

- The 7-point gap is the **observed** impact of excluding session+gdrive.
- The **true** session impact could be **less** than 7 points if session often hits capped competencies.
- Or **more** than 7 points if session fills competencies that other sources rarely touch.

**Raw point contribution:** Session contributes 759 competency points (14% of self total 5469). Gdrive contributes 35. So 794 points (14.5%) come from self-only sources.

---

## 3. Event Volume Comparison

| Metric | Self | Peer Mean | Top 10 Peers |
|--------|------|-----------|--------------|
| Events/day | 30.8 | 3.1 | 9.0–16.9 |
| Total events | 1172 | ~118 | 316–658 |

**Top 10 peers by events/day:**

1. dvernier (sse): 16.9/day (658 total)
2. simaishi (pse): 16.6/day (648 total)
3. dsavinea (sse): 10.8/day (423 total)
4. ssbarnea (pse): 10.2/day (399 total)
5. smcdonal (spse): 9.9/day (385 total)
6. audgirka (pse): 9.4/day (365 total)
7. nmalik (spse): 9.3/day (362 total)
8. nmonk (ase): 9.0/day (351 total)
9. jowestco (pse): 8.8/day (343 total)
10. olebaran (sse): 8.1/day (316 total)

**Interpretation:** Self at 30.8 events/day is ~2x the top peer and ~10x the peer mean. Self is a high-volume outlier even on shared sources.

---

## 4. Source-Normalized Comparison

**Shared sources only:** git, github, gitlab, jira, meeting

| Metric | Self | Peer Mean | Peer Max |
|--------|------|-----------|----------|
| Events (shared sources) | 840 | 118.5 | 658 |
| % of self total | 72% | — | — |

Self has 840 events from shared sources vs peer mean 118.5. Even without session/gdrive, self has ~7x the shared-source event volume of the average peer.

---

## 5. Per-Source Scoring Contribution (Competency Points)

### Self

| Source | Points | % of Total |
|--------|--------|------------|
| gitlab | 2027 | 37.1% |
| git | 1427 | 26.1% |
| session | 759 | 13.9% |
| github | 811 | 14.8% |
| meeting | 307 | 5.6% |
| jira | 103 | 1.9% |
| gdrive | 35 | 0.6% |
| **Total** | **5469** | 100% |

### Sample peers (2 well-populated)

**dvernier (sse):** git 315, github 703, jira 378, meeting 311 → **1707 total** (no gitlab, no session)

**simaishi (pse):** git 88, github 262, gitlab 1830, jira 67, meeting 0 → **2247 total** (no session)

**Observation:** Session contributes 759 points (14%) to self. Gitlab is the largest single source for both self and simaishi. Peer sources lack session entirely.

---

## 6. peer_comparable Effectiveness

After full Q1 2026 backfill:

| Level | Self | Peer Mean | Peer Min | Peer Max | Peer Median |
|-------|------|-----------|----------|----------|-------------|
| — | **70%** | — | — | — | — |
| ASE | 70% | 22% | 5 | 48 | 21 |
| SE | 70% | 21% | 2 | 49 | 22 |
| SSE | 70% | 18% | 2 | 67 | 14 |
| PSE | 70% | 15% | 2 | 38 | 11 |
| SPSE | 70% | 12% | 3 | 41 | 9 |

**Gap:** Self is 48–58 percentage points above peer level averages in peer_comparable.

**peer_comparable** strips: session events, personal gdrive, and strategy bonus. So the 70% is already source-normalized.

---

## 7. What Would Fair Look Like?

**peer_comparable (70%) is the fair score.** It uses the same sources as peers (git, github, gitlab, jira, meeting, shared-drive gdrive only).

### Simulated removal of session + personal gdrive

| Metric | With session+gdrive | Without (peer_comparable) |
|--------|---------------------|----------------------------|
| Events | 1172 | 840 |
| Raw points from excluded sources | 794 (session 759 + gdrive 35) | 0 |
| Overall % | 77% | 70% |

**Conclusion:** The 7-point drop (77 → 70) is the direct effect of excluding session and personal gdrive. The 70% peer_comparable score is the appropriate source-normalized comparison.

---

## Summary: Source Asymmetry vs Performance

| Question | Answer |
|----------|--------|
| How much of the gap is source asymmetry? | **7 percentage points** (77% → 70%) from session + personal gdrive |
| Do peers get session? | **No** (0 events) |
| Do peers get personal gdrive? | **No** (only shared-drive gdrive, ~0.4–1.4 avg) |
| Is the 7-point gap the full session impact? | **Yes** for the observed drop. Session may overlap with other sources (daily caps), so true impact could be slightly different |
| Is self an outlier in volume? | **Yes.** 30.8 events/day vs peer mean 3.1; even on shared sources, 840 vs peer mean 118.5 |
| What is the fair comparison? | **peer_comparable (70%)** — already source-normalized |
| Remaining gap (70% vs peer 12–22%)? | Driven by **event volume** and **performance on shared sources**, not by sources peers lack |

---

## Recommendations

1. **Use peer_comparable (70%)** for any self-vs-peer comparison; it removes source asymmetry.
2. **Interpret the 70% vs peer averages** as reflecting both higher event volume and stronger performance on shared sources.
3. **Session** is the main asymmetry (321 events, 759 points); consider whether session events should be down-weighted or excluded in future scoring if peer parity is a goal.
4. **Volume** is a confound: self has ~10x peer mean events. Consider volume-normalized metrics (e.g., points per event) for a more balanced comparison.
