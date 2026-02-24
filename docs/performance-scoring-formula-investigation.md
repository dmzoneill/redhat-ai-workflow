# Performance Scoring Formula Investigation Report

**Date:** 2026-02-23
**Context:** User scores 77% while PSE peers score 0–3%. Investigation of whether the scoring formula is fair or biased.

---

## 1. Point Calculation Formula (End-to-End)

### 1.1 Core Formula

```
points = round(base_points × scope_mult × role_weight × pillar_weight × strategy_bonus)
points = max(points, 1)  # floor at 1
```

**Source:** `scorer.py` lines 871–874, 1000–1002.

### 1.2 Signal Threshold (Gate)

An event only scores if `signals >= min_signals` (default 2). Signals come from:

| Signal Type | Count |
|-------------|-------|
| event_type in competency's event_types | +1 |
| Each matching phrase in text | +1 per phrase |
| Each matching keyword in text | +1 per keyword |
| NPU classifier bonus (if enabled) | +0 to N |
| contribution_type=upstream/fork | +1 for opportunity_recognition, scope |
| contribution_type=cross-org | +1 for scope, collaboration |
| is_cross_team=True | +1 for scope, collaboration, leadership |
| review_decision=CHANGES_REQUESTED | +1 for mentorship, collaboration |
| review_decision=APPROVED | +1 for collaboration |
| source in (github, gitlab) | +1 for opportunity_recognition (extra path) |

### 1.3 Multiplier Values (PSE Level)

**Scope multipliers** (`scorer.py` DEFAULT_GLOBALS):

| Scope | Multiplier |
|-------|------------|
| commit | 1 |
| doc | 2 |
| meeting | 1 |
| story | 2 |
| epic | 4 |
| anstrat | 7 |
| strategy | 10 |

**Role weights** (`competencies.yaml` level_weights.pse):

| Scope | Reporter | Assignee | Contributor |
|-------|----------|----------|-------------|
| commit | 0.4 | 0.4 | 0.2 |
| doc | 0.5 | 0.5 | 0.25 |
| meeting | 0.5 | 0.4 | 0.2 |
| story | 0.5 | 0.4 | 0.2 |
| epic | 1.0 | 0.8 | 0.4 |
| anstrat | 1.5 | 1.2 | 0.6 |
| strategy | 2.0 | 1.5 | 0.8 |

**Pillar weights** (PSE):

| Category | Weight |
|----------|--------|
| Technical Contribution | 0.8 |
| Leadership | 1.3 |
| Mentorship | 1.1 |
| End-to-End Delivery | 1.25 |

**Strategy bonus:** 1.5× when `strategy_aligned=True` (event matches exec priorities).

### 1.4 Example Calculation

Event: ANSTRAT-linked Jira issue, user is assignee, Technical Contribution competency, strategy-aligned.

- base_points = 4 (e.g. creativity_innovation)
- scope = anstrat → 7
- role = assignee → 1.2
- pillar = Technical Contribution → 0.8
- strategy_bonus = 1.5

```
points = round(4 × 7 × 1.2 × 0.8 × 1.5) = round(40.32) = 40
```

### 1.5 Daily Cap

Points per competency per day are capped at `daily_cap` (default 15). Applied when aggregating events into `daily_points`.

---

## 2. Multiplier Compounding

### 2.1 Multiplicative Stacking

All multipliers are multiplied together. Example:

- scope=2, role=1.5, pillar=1.5, strategy=1.5
- Total: 2 × 1.5 × 1.5 × 1.5 = **6.75×** base points

This is intentional: scope, role, pillar, and strategy are treated as independent factors.

### 2.2 Maximum Theoretical Multiplier (PSE)

- scope = strategy → 10
- role = reporter (strategy) → 2.0
- pillar = End-to-End Delivery → 1.25
- strategy_bonus = 1.5

**Max = 10 × 2.0 × 1.25 × 1.5 = 37.5×** base points.

For base_points=4: **150 points per event** (before daily cap).

### 2.3 Highest Observed in Practice

With daily_cap=15, the effective max per competency per day is 15. The compounding mainly affects which events contribute and how quickly competencies saturate, not the raw per-event ceiling after capping.

---

## 3. Effective Target per Level

**Formula:** `effective_target = max(round(target_per_competency × target_scale), 1)`
**Base:** `target_per_competency = 100` (from `scorer.py` DEFAULT_GLOBALS)

| Level | target_scale | Effective Target |
|-------|--------------|------------------|
| ASE | 0.65 | 65 |
| SE | 0.9 | 90 |
| SSE | 1.25 | 125 |
| **PSE** | **1.6** | **160** |
| SPSE | 2.0 | 200 |
| DE | 2.5 | 250 |
| SDE | 3.1 | 310 |
| Fellow | 3.75 | 375 |

**Source:** `competencies.yaml` level_weights, `daemon.py` lines 623–624.

---

## 4. Saturation Analysis

### 4.1 Math

- 1172 events over 53 days ≈ 22 events/day
- 16 competencies
- daily_cap = 15 per competency per day
- Max points per competency over 53 days = 53 × 15 = **795**
- PSE target = **160**

So 795 / 160 ≈ **497%** of target per competency. Any competency with regular activity will saturate at 100%.

### 4.2 Saturation Bias

With many events and a low target, most competencies reach 100% quickly. The system then emphasizes the few that do not (e.g. mentorship, speaking_publicity, execution_as_mentee), which are harder to evidence from automated sources.

### 4.3 Event-to-Points Ratio

If average event yields ~3 points across matched competencies and events match ~3 competencies each:

- 1172 × 3 / 16 ≈ 220 points per competency
- Target 160 → 220/160 ≈ 138% → capped at 100%

So saturation is expected for most competencies with typical activity.

---

## 5. Overall Percentage Computation

### 5.1 Formula

```python
cumulative_pct[comp_id] = min(round(points[comp_id] / effective_target * 100), 100)
overall = round(sum(cumulative_pct.values()) / max(len(cumulative_pct), 1))
```

**Source:** `daemon.py` lines 626–630.

### 5.2 Interpretation

- **Per-competency %:** `min(100, round(points/target × 100))`
- **Overall:** Mean of per-competency percentages
- **Scope:** Only competencies with at least one point are included

### 5.3 Why 77% vs ~80%?

With 11 competencies at 100% and 5 below 100% (e.g. 73, 71, 19, 9, 3):

- (11×100 + 73 + 71 + 19 + 9 + 3) / 16 = 1275/16 ≈ 79.7%

Possible reasons for 77%:

1. Rounding: each `cumulative_pct` is rounded before averaging
2. Different competency set: some competencies may have 0 points and be excluded
3. Slightly different point totals than assumed

---

## 6. Level-Scaled Targets and Peer Scores

### 6.1 PSE vs ASE

- PSE target: 160
- ASE target: 65
- Ratio: 160/65 ≈ 2.46

For the same raw points, PSE needs ~2.5× more to reach the same percentage.

### 6.2 Why Peers Score 0–3%

1. **Higher targets:** PSE target (160) is much higher than ASE (65).
2. **Fewer events:** Peers may have fewer collected events (Jira, Git, meetings, etc.).
3. **Different data access:** Self has session logs, personal GDrive; peers do not.
4. **Peer-comparable normalization:** Session and personal GDrive are excluded for peer_comparable, but peers may still have far fewer events from shared sources.

### 6.3 Role Weight Design

PSE role weights are lower for routine work (commit, story) and higher for strategic work (epic, anstrat, strategy). If peers have more routine events and fewer strategic ones, they earn fewer points per event at PSE.

---

## 7. Customer Focus Competency

### 7.1 Definition

`customer_focus` is a standard competency in `scorer.py` (lines 519–541) and `competencies.yaml`.

### 7.2 Event Types

- issue_resolved, issue_closed, issue_opened
- alert_investigated
- customer_engagement
- meeting_organized_customer_meeting
- meeting_attended_customer_meeting

### 7.3 Why Peers May Lack It

1. **customer_engagement** is often inferred from **session** logs (manual entries with “customer”, “stakeholder”, etc.). Session is primary-only and excluded from peer_comparable.
2. **meeting_organized_customer_meeting** is organizer-only; peers are often attendees.
3. Peers may have less Jira coverage for customer-facing work.
4. GDrive customer docs are often personal (primary-only).

So `customer_focus` is not self-only by design, but the main evidence sources (session, personal GDrive) are primary-only, which effectively makes it self-biased.

---

## 8. Peer Comparable Score

### 8.1 What Is Stripped

**Primary-only events** (`_is_primary_only_event`):

- `source == "session"`
- `source == "gdrive"` and `not gdrive_shared_drive`

**Strategy bonus:** Removed for both self and peers in peer_comparable (`_normalize_strategy_bonus`).

### 8.2 Self 77% vs peer_comparable 70%

The ~7% drop comes from excluding session and personal GDrive events. That is a meaningful normalization.

### 8.3 Possible Gaps

1. **Meeting data asymmetry:** Self may have richer meeting metadata (organizer vs attendee, customer meetings).
2. **Jira hierarchy:** Self may have better epic/ANSTRAT linkage (scope=epic/anstrat) than peers.
3. **Git/GitLab:** Self repos vs peer repos may differ in coverage.
4. **Shared Drive:** Only shared-drive GDrive events are peer-comparable; personal GDrive is excluded.

---

## 9. Bias Summary

| Bias | Description | Impact |
|------|-------------|--------|
| **Data asymmetry** | Session + personal GDrive only for self | +7%+ for self |
| **Target scaling** | PSE target 2.5× ASE; same points → lower % at PSE | Peers at PSE score lower |
| **Saturation** | Low targets + many events → most competencies at 100% | Overstates “well-rounded” performance |
| **customer_focus** | Heavily session-driven; session is primary-only | Self-only in practice |
| **Role weights** | PSE devalues routine work | Favors strategic, cross-team work |
| **Competency exclusion** | 0-point competencies excluded from overall mean | Can inflate overall if weak areas are never scored |

---

## 10. Recommended Calibration Changes

### 10.1 Target and Saturation

1. **Raise base target** for higher levels, e.g. `target_per_competency = 150` or level-dependent.
2. **Cap saturation** so 100% requires more evidence, e.g. `min(100, points/target * 100)` with a higher effective target.
3. **Include all competencies in overall** with 0% for unscored competencies to avoid inflating the mean.

### 10.2 Peer Comparability

4. **Expand primary-only exclusions** if more self-only sources are identified.
5. **Audit meeting and Jira coverage** for peers to ensure comparable data.
6. **Document** which sources feed each competency and whether they are peer-visible.

### 10.3 customer_focus

7. **Add peer-visible event types** for customer_focus (e.g. Jira labels, meeting titles).
8. **Reduce weight of session-driven customer_engagement** or flag it as self-only in reporting.

### 10.4 Level Fairness

9. **Review target_scale progression** so PSE/SPSE targets are not disproportionately high relative to typical event volume.
10. **Consider percentile-within-level** instead of raw percentage for peer comparison.

---

## Appendix A: Competency List (16 total)

1. technical_contribution
2. technical_knowledge
3. creativity_innovation
4. continuous_improvement
5. leadership
6. collaboration
7. mentorship
8. speaking_publicity
9. portfolio_impact
10. planning_execution
11. end_to_end_delivery
12. opportunity_recognition
13. customer_focus
14. scope
15. evidence_record
16. execution_as_mentee

---

## Appendix B: Key Code References

| Concept | File | Lines |
|---------|------|-------|
| Point formula | scorer.py | 871–874, 1000–1002 |
| Scope multipliers | scorer.py | 669–677 |
| Level weights | competencies.yaml | 531–852 |
| Target scale | daemon.py | 623–624 |
| Overall % | daemon.py | 626–630 |
| Peer comparable | daemon.py | 538–550, 599–611 |
| Primary-only | daemon.py | 538–550 |
