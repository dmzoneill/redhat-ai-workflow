# Competency Keyword Matching Bias: Self vs PSE Peer (simaishi)

**Context**: Self peer-comparable score is 59% vs PSE peer average of 10%. This report investigates whether self's events match **more competencies per event** than peers, which would inflate self's score even with similar event counts.

**Methodology**: Sampled 5 days (2026-01-05, 01-13, 01-22, 01-26, 02-02) from self and simaishi daily files. Analyzed `points` dict (competencies matched), `signal_counts`, `classification_text`, and event types.

---

## 1. Average Competencies Matched per Event

| Metric | Self | Simaishi | Ratio |
|--------|------|----------|-------|
| **Avg competencies/event** | **2.25** | **0.83** | **2.70x** |
| Avg competencies per *scored* event (events with points > 0) | 2.71 | 1.66 | 1.63x |

**Finding**: Self's events match **2.7x more competencies** on average than simaishi's. This is a major bias: each self event yields more points because it activates more competency keyword/phrase/event_type matches.

---

## 2. Competencies-per-Event Distribution

| Competencies Hit | Self | Simaishi |
|------------------|------|----------|
| 0 | 18 | **60** |
| 1 | 29 | 41 |
| 2 | 16 | 4 |
| 3 | 14 | 12 |
| 4 | 21 | 4 |
| 5 | 4 | 0 |
| 6 | 1 | 0 |
| 7 | 4 | 0 |

**Finding**:
- **60 of 121** simaishi events (50%) score **zero** competencies. Only **18 of 107** self events (17%) score zero.
- Self has **30 events** hitting 4+ competencies; simaishi has **4**.
- Self has events hitting 5, 6, 7 competencies; simaishi has none above 4.

---

## 3. Average Signals per Event

| Metric | Self | Simaishi | Ratio |
|--------|------|----------|-------|
| **Avg total signals/event** (sum of `signal_counts`) | **17.2** | **11.8** | **1.46x** |

**Finding**: Self's events generate 46% more signals (phrase + keyword + event_type matches) before the min_signals threshold. More signals → more competencies exceed the threshold → more points.

---

## 4. Classification Text Analysis

| Metric | Self | Simaishi | Ratio |
|--------|------|----------|-------|
| **Avg text length (chars)** | **310** | **152** | **2.04x** |
| Keyword density (signals/100 chars) | 5.55 | 7.75 | 0.72x |

**Finding**: Self's `classification_text` is **2x longer** than simaishi's. Longer text spans more competency keyword sets, so more competencies get phrase/keyword hits. Simaishi's shorter text is actually *more* keyword-dense per character, but the absolute signal count is lower because there's less text to match against.

**Root cause of longer self text** (from code analysis):
1. **Session integration (self-only)**: Session log entries append `[Session: {action}] {details}` + accomplished/decisions/next_steps to existing events. Peers have no session data.
2. **Jira hierarchy**: Both get epic/ANSTRAT when Jira keys are in titles, but self's events may reference more AAP issues with full hierarchy.
3. **Commit body / MR description**: Both get these when available; self may write more verbose messages.

---

## 5. Event Type Diversity

| Metric | Self | Simaishi |
|--------|------|----------|
| **Unique event types** | **15** | **8** |
| Top types (self) | commit (27), alert_investigated (17), leadership_activity (13), mr_review_received (8), mr_opened (7), meeting_attended_* (15) | — |
| Top types (simaishi) | mr_opened (58), mr_merged (37), issue_resolved (11), commit (5), pr_merged (4) | — |

**Finding**: Self has **15 unique event types** vs simaishi's **8**. Self's mix includes:
- `alert_investigated` (17) – from **session integration** (investigate_alert, debug_prod skills)
- `leadership_activity` (13) – from **session integration** (plan_implementation, research_topic, etc.)
- `process_improvement` (3) – from **session integration** (slop_scan, cve_fix, etc.)
- `meeting_attended_*` (15) – self gets meeting events; simaishi has only 2

These session-sourced event types are in `event_types` for multiple competencies (e.g. `alert_investigated` → technical_contribution, continuous_improvement, technical_knowledge; `leadership_activity` → leadership). Peers never get these event types because **session collection is skipped when `user_override` is set** (`collector.py` line 2849).

---

## 6. Event Counts (5 days)

| Metric | Self | Simaishi |
|--------|------|----------|
| Total events | 107 | 121 |
| Events with points | 89 (83%) | 61 (50%) |

**Finding**: Simaishi has *more* total events (121 vs 107) but **fewer** that score (61 vs 89). Self's events are more likely to cross the min_signals threshold.

---

## 7. Root Causes of Bias

### A. Session Integration (Self-Only)
- **Location**: `collector.py` lines 2849–2866: `if not user_override:` before session collect
- **Effect**: Self gets (1) new events (alert_investigated, leadership_activity, process_improvement) and (2) enrichment of existing events with session narrative. Peers get neither.
- **Impact**: Session events and enrichment add keywords (e.g. "investigated", "decision", "architecture", "fix") that match multiple competencies.

### B. Richer Classification Text for Self
- Session enrichment appends `[Session: {action}] {details}` + accomplished/decisions/next_steps
- Longer text → more phrase/keyword matches across competency definitions
- Example: A commit with session text "Fixed auth bug. Decision: Use JWT refresh." matches technical_contribution, creativity_innovation, evidence_record, etc.

### C. Event Type Mix
- Self's event types (alert_investigated, leadership_activity, process_improvement) are in `event_types` for many competencies
- Simaishi's events are mostly mr_opened, mr_merged, issue_resolved – fewer event_type-based matches

### D. Zero-Score Event Rate
- 50% of simaishi events score zero vs 17% for self
- Simaishi's Jira titles (e.g. "AAP 2.4 Async Release - Stage RPM Advisory") and MR titles may lack competency keywords
- Self's commit messages (fix:, feat:, refactor) and session-enriched text hit more keywords

---

## 8. Is Keyword Matching Breadth a Remaining Bias?

**Yes.** The data shows:
1. **2.7x more competencies per event** for self
2. **2x longer classification text** for self
3. **1.46x more signals per event** for self
4. **Session integration** and **event type diversity** favor self

This bias directly contributes to the score gap (59% vs 10%): self accumulates more points per event through broader keyword/phrase/event_type matching.

---

## 9. Recommendations

### Short-term (Reduce Bias)

1. **Cap competencies per event**
   Limit the number of competencies that can score per event (e.g. max 3–4). Prevents a single event from dominating via keyword sprawl.

2. **Normalize classification text length**
   Truncate or sample `classification_text` to a fixed max length (e.g. 200 chars) before scoring. Reduces advantage from longer, session-enriched text.

3. **Exclude or down-weight session-sourced events in peer comparison**
   When computing peer-comparable score, exclude events with `source="session"` or event types that only exist via session (alert_investigated, leadership_activity, process_improvement). Alternatively, cap their contribution.

4. **Peer session proxy (optional)**
   If peers had a lightweight "work log" (e.g. from Jira comments or similar), use that to enrich peer events. High effort; only if parity is critical.

### Medium-term (Structural)

5. **Separate self vs peer scoring paths**
   Use different min_signals or competency caps for peer comparison to correct for enrichment asymmetry.

6. **Event-type normalization**
   Map session event types to the closest "peer-visible" type (e.g. alert_investigated → issue_resolved) when comparing, so self doesn't benefit from types peers can't have.

7. **Keyword density ceiling**
   If signals/char exceeds a threshold, cap or down-weight. Reduces benefit from very long, keyword-rich text.

### Long-term (Design)

8. **Unify enrichment for self and peers**
   Ensure peers get equivalent context (e.g. Jira hierarchy, MR descriptions) where possible. Session is inherently self-only, but other enrichments could be aligned.

9. **Revisit competency definitions**
   Audit phrases/keywords for overlap and reduce double-counting (see `docs/performance-keyword-bias-analysis.md`).

---

## 10. Appendix: Competency Definitions (Relevant Excerpts)

Competencies use three signal sources:
- **event_types**: e.g. commit, mr_merged, alert_investigated
- **phrases**: e.g. "fix:", "feat:", "architecture decision"
- **keywords**: e.g. fix, feat, patch, implement, code

Each competency needs `signals >= min_signals` (default 2) to score. More text + more event types → more signals → more competencies score.

Key overlap: `technical_contribution`, `creativity_innovation`, `continuous_improvement`, `scope`, `end_to_end_delivery` share many keywords. A single commit can hit 5–7 competencies.
