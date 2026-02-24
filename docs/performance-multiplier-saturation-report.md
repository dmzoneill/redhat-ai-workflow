# Multiplier Stacking & Target Saturation Analysis — Q1 2026

**Data-driven report** on whether multiplier stacking, saturation, and duplication are real problems requiring formula changes. Analysis uses full Q1 2026 peer data.

---

## Executive Summary

| Finding | Severity | Recommendation |
|---------|----------|----------------|
| **Competency saturation** | High | Self has 9/16 at 100% vs 0–3 for top PSE peers. Saturation is uncommon among peers. |
| **Points overshoot** | High | 9 competencies 1.4–3.0× above target; creativity_innovation at 3×. Raising targets would reduce inflation. |
| **Multiplier stacking** | Moderate | Self has more high-point events (max 31 vs 26 for dvernier); 5 vs 1 outliers >20 pts. |
| **Strategy bonus** | Mixed | Self 32% of points from strategy; simaishi 51%. Peer-comparable normalization is important. |
| **Cross-source duplication** | High | Self: 5.1 events/issue, max 57; peers: 1.8, max 6. Duplication is much worse for self. |
| **Target simulation** | Informative | PSE target 250 → self 69% (from 77%); top PSE peer 34% (from 40%). Both drop similarly. |

---

## 1. Competency Saturation Analysis

**Question:** How many competencies are at 100%? Is saturation common or unique to self?

| Person | Level | Saturated | Total | Overall % | Events |
|--------|-------|-----------|-------|----------|--------|
| **Self** | PSE | **9** | 16 | 77% | 1,172 |
| daoneill (peer copy) | PSE | 8 | 15 | 68% | 782 |
| tshinhar | SSE | 5 | 10 | 68% | 167 |
| dvernier | SSE | 6 | 15 | 67% | 658 |
| olebaran | SSE | 5 | 13 | 60% | 316 |
| dsavinea | SSE | 3 | 13 | 53% | 423 |

**Top 5 PSE peers (same level as self):**

| Person | Saturated | Total | Overall % |
|--------|-----------|-------|-----------|
| simaishi | 3 | 13 | 40% |
| ssbarnea | 1 | 13 | 38% |
| mabashia | 0 | 12 | 37% |
| audgirka | 0 | 14 | 30% |
| jowestco | 1 | 15 | 30% |

**Conclusion:** Saturation is uncommon among peers. Self has 9 of 16 competencies at 100%; top PSE peers have 0–3. High-volume contributors (dvernier, SSE) have more saturation than low-volume PSE peers, but self’s saturation is still above typical peers.

---

## 2. Points per Competency vs Effective Target

**Question:** How far above target are saturated competencies?

**Self (effective_target = 160):**

| Competency | Points | Target | Ratio |
|------------|--------|--------|-------|
| creativity_innovation | 486 | 160 | **3.0×** |
| scope | 390 | 160 | **2.4×** |
| end_to_end_delivery | 388 | 160 | **2.4×** |
| continuous_improvement | 313 | 160 | **2.0×** |
| planning_execution | 302 | 160 | **1.9×** |
| customer_focus | 272 | 160 | **1.7×** |
| portfolio_impact | 268 | 160 | **1.7×** |
| technical_contribution | 252 | 160 | **1.6×** |
| opportunity_recognition | 216 | 160 | **1.4×** |
| leadership | 141 | 160 | 0.9× |
| evidence_record | 119 | 160 | 0.7× |
| collaboration | 117 | 160 | 0.7× |
| technical_knowledge | 114 | 160 | 0.7× |

**Top PSE peer (simaishi):**

| Competency | Points | Target | Ratio |
|------------|--------|--------|-------|
| end_to_end_delivery | 402 | 160 | **2.5×** |
| creativity_innovation | 294 | 160 | **1.8×** |
| scope | 289 | 160 | **1.8×** |
| opportunity_recognition | 98 | 160 | 0.6× |
| portfolio_impact | 91 | 160 | 0.6× |

**Conclusion:** Self has larger overshoots (e.g. creativity_innovation 3× vs 1.8× for simaishi). Points above 100% do not increase overall score; raising targets would make 100% harder to reach and reduce inflation.

---

## 3. Multiplier Impact from Daily Files

**Question:** What is the distribution of points per event? Are there extreme outliers?

**Points per scored event (3 busiest days each):**

| Person | n | Mean | Median | Max | Outliers (>20 pts) |
|--------|---|------|--------|-----|--------------------|
| Self | 227 | 4.0 | 2.0 | **31** | **5** |
| dvernier (SSE) | 121 | 3.9 | 2.0 | 26 | 1 |

**Conclusion:** Self has more high-point events (max 31 vs 26) and more outliers (5 vs 1). This suggests scope/strategy/epic multipliers stack more often for self, but the difference is moderate.

---

## 4. Strategy Bonus Analysis

**Question:** How many events have strategy_aligned=true? What fraction of points come from strategy-boosted events?

| Person | Strategy events | Total scored | % events | Strategy points | Total points | % points |
|--------|-----------------|--------------|----------|-----------------|--------------|----------|
| **Self** | 86 | 958 | 9.0% | 1,759 | 5,469 | **32.2%** |
| dvernier | 5 | 500 | 1.0% | 24 | 1,707 | 1.4% |
| simaishi | 101 | 483 | 20.9% | 1,143 | 2,247 | **50.9%** |

**Conclusion:** Self gets 32% of points from strategy-boosted events; simaishi gets 51%. Strategy bonus varies strongly by person. Peer-comparable normalization (stripping strategy bonus) is important for fairness. Self is not the highest beneficiary of strategy bonus.

---

## 5. Cross-Source Duplication

**Question:** How many distinct Jira issues account for events? What is the average events per issue? Is duplication worse for self?

| Person | Total events | Distinct Jira issues | Mean events/issue | Median | Max |
|--------|--------------|----------------------|-------------------|--------|-----|
| **Self** | 1,172 | 65 | **5.1** | 2 | **57** |
| dvernier | 658 | 217 | 1.8 | 2 | 6 |
| smcdonal | 385 | 25 | 1.8 | 1 | 6 |

**Self — issues with 5+ events:**

| Issue | Events |
|-------|--------|
| AAP-58394 | 57 |
| AAP-62200 | 44 |
| AAP-65345 | 35 |
| AAP-61939 | 13 |
| AAP-63841 | 11 |

**Conclusion:** Duplication is much worse for self. Self has 5.1 events per Jira issue vs 1.8 for peers; max 57 vs 6. Self’s event mix (git + gitlab + jira + session) likely counts the same work multiple times. AAP-58394 alone has 57 events.

---

## 6. Effective Target Simulation

**Question:** If PSE target were raised from 160 to 250, what would scores become?

| Person | Target 160 | Target 250 | Delta |
|--------|------------|------------|-------|
| Self | 77% | 69% | −8% |
| simaishi (top PSE peer) | 40% | 34% | −6% |

**Conclusion:** Raising targets reduces both scores. Self drops more in absolute terms (−8% vs −6%) but remains well above the top PSE peer. Higher targets would make 100% harder to reach and reduce saturation.

---

## Recommendations

1. **Raise effective targets** — PSE target 250 (or 200) would reduce saturation and overshoot. Consider level-specific targets.
2. **Reduce duplication** — Deduplicate by Jira issue (e.g. cap events per issue or aggregate by issue before scoring).
3. **Keep peer-comparable normalization** — Strategy bonus varies strongly; stripping it for peer comparison is appropriate.
4. **Monitor multiplier stacking** — Self has more high-point events; consider caps or diminishing returns for scope/strategy/epic multipliers.
5. **Consider competency caps** — Cap points per competency at 100% of target to avoid wasted points and encourage breadth.

---

## Data Sources

- Self daily: `~/.config/aa-workflow/performance/2026/q1/performance/daily/*.json`
- Self summary: `~/.config/aa-workflow/performance/2026/q1/performance/summary.json`
- Peer daily: `~/.config/aa-workflow/performance/2026/q1/performance/peers/{username}/daily/*.json`
- Peer summaries: `~/.config/aa-workflow/performance/2026/q1/performance/peers/{username}/summary.json`
- Scorer: `services/stats/scorer.py`
- Competencies: `services/stats/competencies.yaml`

## Reproduction

```bash
python scripts/analyze_multiplier_saturation.py
```
