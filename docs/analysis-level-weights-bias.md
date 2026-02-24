# Level Weights Bias Analysis: Code vs. Leadership at Senior Levels

**Date:** 2026-02-22
**Purpose:** Analyze whether level weights adequately compensate for bias toward code-producing activities at senior engineering levels (SSE, PSE, SPSE, DE).

---

## 1. Scoring Formula and Parameters

**Formula:** `points = round(base_points × scope_mult × role_weight × pillar_weight × strategy_bonus)` with `min(1)` floor.

**Scope multipliers:**
| Scope   | Mult |
|---------|------|
| commit  | 1    |
| doc     | 2    |
| meeting | 1    |
| story   | 2    |
| epic    | 4    |
| anstrat | 7    |
| strategy| 10   |

**Base points by competency (from scorer):**
- Technical Contribution: 2
- Leadership: 3
- Mentorship: 3
- End-to-End Delivery: 3
- Collaboration: 2
- Technical Knowledge: 3
- Planning & Execution: 2
- Evidence & Record: 2

---

## 2. Effective Points Calculation (PSE Level)

### 2.1 PSE Role Weights
| Scope   | Reporter | Assignee | Contributor |
|---------|----------|----------|-------------|
| commit  | 0.4      | 0.4      | 0.2         |
| meeting | 0.5      | 0.4      | 0.2         |
| story   | 0.5      | 0.4      | 0.2         |
| epic    | 1.0      | 0.8      | 0.4         |

### 2.2 PSE Pillar Weights
- Technical Contribution: 0.8
- Leadership: 1.3
- Mentorship: 1.1
- End-to-End Delivery: 1.25

### 2.3 Sample Calculations (PSE, assignee role, no strategy bonus)

| Activity                    | Base | Scope | Mult | Role | Pillar | Raw    | Rounded |
|----------------------------|------|-------|------|------|--------|--------|---------|
| Commit (Tech Contrib)      | 2    | 1     | 1    | 0.4  | 0.8    | 0.64   | **1**   |
| Meeting (Leadership)       | 3    | 1     | 1    | 0.4  | 1.3    | 1.56   | **2**   |
| Epic leadership (Epic)     | 3    | 4     | 4    | 0.8  | 1.3    | 12.48  | **12**  |
| Doc (Tech Knowledge)       | 3    | 2     | 2    | 0.5  | 0.8    | 2.40   | **2**   |
| Story resolution (E2E)     | 3    | 2     | 2    | 0.4  | 1.25   | 3.00   | **3**   |
| Anstrat (Leadership)       | 3    | 7     | 7    | 1.2  | 1.3    | 32.76  | **33**  |
| MR merged (Tech Contrib)   | 2    | 1     | 1    | 0.4  | 0.8    | 0.64   | **1**   |
| MR merged (E2E Delivery)    | 3    | 1     | 1    | 0.4  | 1.25   | 1.50   | **2**   |

**Note:** A single event can match multiple competencies; e.g. an MR merge typically earns points for both technical_contribution and end_to_end_delivery.

---

## 3. The Fundamental Problem: Volume vs. Weight

### 3.1 Volume Asymmetry

| Activity Type        | Typical Weekly Volume | Points/Event (PSE) | Weekly Points (approx) |
|----------------------|------------------------|--------------------|------------------------|
| Commits              | 25–50                  | 1                  | **25–50**              |
| MRs merged           | 2–5                    | 1–2 each × 2 comps | **4–20**               |
| Jira resolutions     | 3–8                    | 2–3 each           | **6–24**               |
| Meetings attended    | 10–20                  | 2 each             | **20–40**              |
| Architecture reviews | 1–3                    | 2 (scope=meeting!) | **2–6**                |
| Mentoring sessions   | 1–2                    | 2–3 each           | **2–6**                |
| Epic-level work      | 0–1                    | 12                 | **0–12**               |

**Code-heavy path (PSE):**
- 40 commits × 1 = 40
- 3 MRs × (1 + 2) = 9 (tech + E2E)
- 5 Jira resolutions × 3 = 15
- 10 meetings × 2 = 20
- **Total: ~84 points** from high-volume, low-per-event activities

**Leadership-heavy path (PSE):**
- 5 commits × 1 = 5
- 1 MR × 3 = 3
- 2 Jira resolutions × 3 = 6
- 30 meetings × 2 = 60
- 2 epic-level leadership × 12 = 24
- 2 mentoring × 3 = 6
- **Total: ~104 points** — but only if they get 30 meetings and 2 epic-level activities

The leadership path requires **6× more meetings** than the code path has commits to approach similar totals. Most seniors do not have 30 scorable meetings per week. The code path wins on volume.

### 3.2 Quantified Bias

**Break-even analysis (PSE):**
- 1 commit ≈ 1 point (Technical Contribution)
- 1 meeting ≈ 2 points (Leadership)
- So 2 commits ≈ 1 meeting in Leadership pillar

But commits are **5–10× more frequent** than meetings for most engineers. A code-heavy PSE doing 40 commits + 10 meetings earns:
- Tech Contrib: 40 × 1 = 40
- Leadership: 10 × 2 = 20
- E2E (from MRs/Jira): ~15

A meeting-heavy PSE doing 5 commits + 25 meetings earns:
- Tech Contrib: 5 × 1 = 5
- Leadership: 25 × 2 = 50
- E2E: ~5

The meeting-heavy engineer scores higher in Leadership (50 vs 20) but **much lower** in Technical Contribution (5 vs 40). Since Technical Contribution has 7 competencies and Leadership has 4, the code-heavy engineer still accumulates more **total pillar points** across the board. The system favors volume.

---

## 4. Scenario Modeling: Two SSE Engineers (One Week)

### 4.1 SSE Parameters
- **Role weights:** commit 0.8, meeting 0.7, story 0.8, epic 1.2
- **Pillar weights:** Tech Contrib 1.0, Leadership 1.0, Mentorship 0.8, E2E 1.0

### 4.2 Engineer A (Code-Heavy)
| Activity           | Count | Scope | Base | Formula                    | Pts/Event | Total   |
|-------------------|-------|-------|------|----------------------------|-----------|---------|
| Commits           | 25    | commit| 2    | 2×1×0.8×1.0 = 1.6 → 2      | 2         | **50**  |
| MRs merged        | 2     | story | 2,3  | Tech: 2×2×0.8×1.0=3.2→3; E2E: 3×2×0.8×1.0=4.8→5 | 8         | **16**  |
| Jira resolutions  | 3     | story | 3    | 3×2×0.8×1.0 = 4.8 → 5      | 5         | **15**  |
| Meetings          | 10    | meet  | 3    | 3×1×0.7×1.0 = 2.1 → 2      | 2         | **20**  |

**Engineer A weekly total: ~101 points** (Tech-heavy: ~66 from code, ~20 from meetings)

### 4.3 Engineer B (Leadership-Heavy)
| Activity              | Count | Scope | Base | Formula                    | Pts/Event | Total   |
|-----------------------|-------|-------|------|----------------------------|-----------|---------|
| Commits               | 5     | commit| 2    | 2×1×0.8×1.0 = 1.6 → 2      | 2         | **10**  |
| MRs merged            | 1     | story | 2,3  | 3+5 = 8                    | 8         | **8**   |
| Jira resolutions      | 1     | story | 3    | 5                           | 5         | **5**   |
| Meetings              | 30    | meet  | 3    | 3×1×0.7×1.0 = 2.1 → 2      | 2         | **60**  |
| Architecture reviews  | 3     | meet  | 3    | 2 (same as meeting!)       | 2         | **6**   |
| Mentoring sessions    | 2     | meet  | 3    | 3×1×0.7×0.8 = 1.68 → 2     | 2         | **4**   |

**Engineer B weekly total: ~93 points** (Leadership-heavy: ~70 from meetings, ~23 from code)

### 4.4 Verdict
- Engineer A (code-heavy): **~101 points**
- Engineer B (leadership-heavy): **~93 points**

Engineer B needs **30 meetings** to stay close. In practice, 30 scorable meetings/week is rare. With 15 meetings instead: 15×2 = 30, so Engineer B would drop to ~63 from meetings, **~78 total** — meaning the code-heavy engineer outscores by ~23 points (~23%).

---

## 5. Meeting Scope Problem

### 5.1 Current Behavior
All meetings use `scope = "meeting"` and `scope_mult = 1`:
- Standup (15 min)
- Architecture review (90 min, cross-team)
- 1:1 mentoring
- Sprint planning
- All-hands

**Impact:** A 90-minute architecture review and a 15-minute standup both yield the same scope multiplier (1). The system does not distinguish meeting impact.

### 5.2 Comparison to Code/Story Scope
| Activity              | Scope   | Mult | Role (PSE) | Effective weight |
|-----------------------|---------|------|------------|------------------|
| Standup               | meeting | 1    | 0.4        | 0.4              |
| Architecture review   | meeting | 1    | 0.4        | 0.4              |
| Commit                | commit  | 1    | 0.4        | 0.4              |
| Jira story resolution | story   | 2    | 0.4        | 0.8              |

Architecture reviews are leadership at scope similar to epic-level work, but they are scored as `meeting` (mult 1) instead of `epic` (mult 4). A proper epic-level leadership activity would score 12 points; the same activity as a meeting scores 2.

**Recommendation:** Introduce meeting sub-scopes (e.g. `meeting_ceremony`, `meeting_architecture`, `meeting_planning`) with multipliers 1, 2, 4 to align with story/epic impact.

---

## 6. Target Scale Gap

### 6.1 Target Scale vs. Role Weights

| Level | target_scale | Meeting role_weight (assignee) | Implied weekly target |
|-------|--------------|-------------------------------|------------------------|
| ASE   | 0.65         | 0.8                           | Lower bar              |
| SE    | 0.9          | 0.8                           | Moderate               |
| SSE   | 1.25         | 0.7                           | Higher                 |
| PSE   | 1.6          | 0.4                           | Much higher            |
| SPSE  | 2.0          | 0.3                           | Very high              |
| DE    | 2.5          | 0.2                           | Highest                |

### 6.2 The Problem
As level increases:
- `target_scale` increases (expectation goes up)
- Meeting `role_weight` decreases (each meeting is worth less)

For a DE with `target_scale = 2.5` and meeting `role_weight = 0.2`:
- 1 meeting (Leadership, base 3): 3 × 1 × 0.2 × 1.65 = **0.99 → 1 point**
- To reach a target comparable to an SSE (e.g. 100 pts/week), a DE would need far more meetings than are realistic, since each meeting yields only 1 point.

### 6.3 Impossibility for Communication-Heavy Seniors
A DE is expected to operate at strategy/anstrat scope. But:
- Strategy-level work is rare (maybe 1–2 events/quarter)
- Most observable work is meetings
- Meeting scope is fixed at 1 with low role weights

So a DE who spends 80% of time in high-impact meetings (architecture, customer, strategy) is scored the same as one who spends 80% in standups. The system cannot distinguish them, and both are under-rewarded relative to `target_scale`.

---

## 7. Summary and Recommendations

### 7.1 Findings
1. **Volume dominates:** Code events (commits, MRs) occur 5–10× more often than leadership events. Even with pillar weights favoring Leadership at PSE+, code-heavy engineers accumulate more total points.
2. **Meeting scope is flat:** All meetings use scope=1. Architecture reviews and standups are scored identically.
3. **Target scale vs. role weights:** Higher levels have higher `target_scale` but lower meeting `role_weight`, making it harder for meeting-heavy seniors to reach their targets.
4. **Scenario outcome:** In the SSE comparison, the code-heavy engineer scored ~101 vs ~93 for the leadership-heavy engineer, who needed 30 meetings to get close.

### 7.2 Recommendations
1. **Differentiate meeting scope:** Add sub-scopes (e.g. `meeting_architecture`, `meeting_planning`) with multipliers 2–4 so high-impact meetings are weighted appropriately.
2. **Increase meeting role weights at senior levels:** Consider raising PSE/SPSE/DE meeting weights (e.g. 0.5–0.6 for assignee) so that meeting-heavy work is not penalized.
3. **Cap or dampen commit volume:** Apply a daily or weekly cap on commit points, or use a sub-linear function (e.g. sqrt) to reduce the advantage of very high commit counts.
4. **Revisit target_scale:** Ensure `target_scale` is achievable for both code-heavy and meeting-heavy profiles at each level, possibly with different target curves per pillar mix.
5. **Epic-level meeting mapping:** Map architecture reviews, design reviews, and similar meetings to `epic` or a new `meeting_epic` scope when they are cross-team and strategic.
