# Performance Scoring: Keyword/Phrase Bias Analysis

## Executive Summary

The competency scoring system **does bias toward code-producing activities** over communication and leadership activities. The bias stems from:

1. **Inherent source bias**: Commit messages and Jira titles naturally contain high-density technical keywords; meeting titles and Slack discussions do not.
2. **Keyword overlap / double-counting**: Code events trigger many competencies simultaneously; meeting events trigger fewer.
3. **Meeting boost insufficiency**: The classification boost helps some meeting types (1:1, architecture review) but not others (standup, general meeting).
4. **min_signals=2 threshold**: Code events easily exceed it; meetings without strong boost often fall short.

---

## 1. Where Keywords Come From (Source Bias)

| Source | Typical Content | Keyword Density |
|-------|-----------------|-----------------|
| **Commit messages** | "fix:", "feat:", "implement", "migrate", "schema", "patch", "merge" | **Very high** – conventional commits and technical terms |
| **Jira titles** | "Implement X", "Fix Y", "AAP-12345", "issue", "task", "deploy", "release" | **High** – workflow + technical terms |
| **Meeting titles** | "Standup", "1:1 with John", "Sprint Planning", "Weekly Sync" | **Low** – short, generic labels |
| **Slack/email** | Not captured as events | **Zero** – leadership discussions invisible |

**Critical gap**: Significant leadership work (cross-team coordination, stakeholder alignment, strategy discussions) happens in Slack, email, and ad-hoc conversations. These are **never** captured as events and thus never scored.

---

## 2. Keyword Overlap (Double-Counting for Code Work)

Many competencies share keywords with `technical_contribution` and other code-oriented competencies. A single commit message can activate multiple competencies.

### Overlap with technical_contribution

| Competency | Shared Keywords | Shared Phrases |
|------------|-----------------|----------------|
| end_to_end_delivery | — | hotfix |
| opportunity_recognition | upstream | — |
| evidence_record | — | resolved |

### Broader overlap (code events trigger many competencies)

Example commit: **"fix(billing): migrate database schema to add subscription field"**

| Competency | Signals | Matches |
|------------|---------|---------|
| technical_contribution | 2 | event_type=commit, "fix" |
| technical_knowledge | 2 | "schema", "doc" (in schema) |
| continuous_improvement | 2 | "migrate", "migrate" (keyword) |
| scope | 3 | "migration", "database", "schema" |
| portfolio_impact | 2 | "schema", "schema" |
| customer_focus | 5 | "billing", "subscription", "billing", "subscription", "subscription" |

**Result**: One commit activates **6 competencies** and scores **18 points**.

---

## 3. Meeting Classification Boost

The meeting collector appends boost text based on classification:

```python
_CLASSIFICATION_BOOST = {
    "one_on_one": "mentorship coaching leadership one-on-one feedback",
    "architecture_review": "architecture design review technical documentation",
    "sprint_planning": "sprint planning capacity backlog agile ceremony",
    "standup": "standup scrum daily sync agile ceremony",
    "general_meeting": "meeting collaboration team",
    # ...
}
```

### Boost sufficiency by meeting type

| Meeting | Classification | Boost | Competencies Activated | Adequate? |
|---------|----------------|-------|-------------------------|-----------|
| 1:1 with John | one_on_one | mentorship, coaching, leadership, feedback | 5 (mentorship, leadership, collaboration, execution_as_mentee, end_to_end_delivery) | **Yes** |
| Weekly Architecture Review | architecture_review | architecture, design review, documentation | 3 (leadership, technical_knowledge, collaboration) | **Yes** |
| Sprint Planning | sprint_planning | sprint, planning, backlog, agile, ceremony | 1 (planning_execution only) | **Marginal** – many signals but only 1 competency |
| Team Standup | standup | standup, scrum, daily sync, agile, ceremony | 1 (planning_execution) | **No** – "standup" matches planning_execution only |
| Weekly Sync | general_meeting | meeting, collaboration, team | 2 (evidence_record, collaboration) | **Marginal** |

**Conclusion**: The boost helps 1:1s and architecture reviews. Standups and generic meetings get minimal activation. The boost text for `standup` and `general_meeting` does not include keywords for leadership, mentorship, or collaboration.

---

## 4. min_signals=2 Threshold

With `min_signals=2`, the threshold behaves differently by event type:

| Event Type | Typical Signal Count | Crosses Threshold? |
|------------|----------------------|--------------------|
| Commit (technical) | 2–6+ per competency | **Easily** |
| Jira resolved | 2–4 per competency | **Easily** |
| Meeting (1:1, arch review) | 2–5 with boost | **Yes** |
| Meeting (standup, general) | 1–2 | **Often no** |
| Slack/email | N/A | **Never** |

A commit like `"fix: resolve billing bug"` matches: fix (phrase+keyword), resolved (phrase), billing (customer_focus). That’s 2+ signals for technical_contribution, evidence_record, customer_focus.

A meeting titled `"Team Standup"` with boost `"standup scrum daily sync agile ceremony"` matches planning_execution (standup, daily sync, ceremony) = 3 signals. But leadership, mentorship, collaboration get 0–1 signals from that text.

---

## 5. Calculated Examples (Exact Counts)

### Example 1: Commit

**Text**: `AAP-12345 - fix(billing): migrate database schema to add subscription field`
**Event type**: `commit`

| Competency | Signals | Base Pts | Activated? |
|------------|---------|----------|-------------|
| technical_contribution | 2 | 2 | ✓ |
| technical_knowledge | 2 | 3 | ✓ |
| continuous_improvement | 2 | 3 | ✓ |
| scope | 3 | 3 | ✓ |
| portfolio_impact | 2 | 4 | ✓ |
| customer_focus | 5 | 3 | ✓ |

**Total: 6 competencies, 18 points**

---

### Example 2: Jira Resolved

**Text**: `AAP-12345: Implement Redis caching for API endpoint`
**Event type**: `issue_resolved`

| Competency | Signals | Base Pts | Activated? |
|------------|---------|----------|-------------|
| technical_contribution | 3 | 2 | ✓ |
| portfolio_impact | 3 | 4 | ✓ |

**Total: 2 competencies, 6 points**

---

### Example 3: Meeting – Weekly Architecture Review (attended)

**Text**: `Weekly Architecture Review architecture_review architecture design review technical documentation`
**Event type**: `meeting_attended_architecture_review`

| Competency | Signals | Base Pts | Activated? |
|------------|---------|----------|-------------|
| leadership | 5 | 3 | ✓ |
| technical_knowledge | 3 | 3 | ✓ |
| collaboration | 2 | 2 | ✓ |

**Total: 3 competencies, 8 points**

---

### Example 4: Meeting – 1:1 with John (attended)

**Text**: `1:1 with John one_on_one mentorship coaching leadership one-on-one feedback`
**Event type**: `meeting_attended_one_on_one`

| Competency | Signals | Base Pts | Activated? |
|------------|---------|----------|-------------|
| mentorship | 5 | 3 | ✓ |
| leadership | 3 | 3 | ✓ |
| execution_as_mentee | 4 | 2 | ✓ |
| collaboration | 2 | 2 | ✓ |
| end_to_end_delivery | 2 | 3 | ✓ |

**Total: 5 competencies, 13 points**

---

### Example 5: Meeting – Sprint Planning (attended)

**Text**: `Sprint Planning sprint_planning sprint planning capacity backlog agile ceremony`
**Event type**: `meeting_attended_sprint_planning`

| Competency | Signals | Base Pts | Activated? |
|------------|---------|----------|-------------|
| planning_execution | 8 | 2 | ✓ |

**Total: 1 competency, 2 points**

---

### Example 6: Google Doc – Technical Design

**Text**: `ANSTRAT-123 Technical Design - Redis Migration architecture design review adr rfc documentation`
**Event type**: `gdrive_doc_created`

| Competency | Signals | Base Pts | Activated? |
|------------|---------|----------|-------------|
| leadership | 6 | 3 | ✓ |
| technical_knowledge | 5 | 3 | ✓ |
| scope | 3 | 3 | ✓ |
| collaboration | 2 | 2 | ✓ |

**Total: 4 competencies, 11 points**

---

## 6. Summary: Code vs Communication/Leadership

| Event | Competencies | Total Points | Category |
|-------|--------------|--------------|----------|
| Commit (fix + migrate schema) | 6 | 18 | **Code** |
| Jira resolved (Implement Redis API) | 2 | 6 | **Code** |
| Meeting: Architecture Review | 3 | 8 | **Leadership/Communication** |
| Meeting: 1:1 with John | 5 | 13 | **Leadership/Communication** (note: end_to_end_delivery is a false positive—"ship" matches inside "leader**ship**") |
| Meeting: Sprint Planning | 1 | 2 | **Leadership/Communication** |
| Google Doc: Technical Design | 4 | 11 | **Hybrid** |

**Observations**:

1. **Commit wins on breadth**: One commit activates 6 competencies; Sprint Planning activates only 1.
2. **1:1s score well** when the boost adds mentorship/leadership keywords.
3. **Sprint Planning under-scores**: Despite being central to planning, it only activates planning_execution (2 pts).
4. **Slack/email leadership work is invisible**: No events, no points.

---

## 7. Recommendations

1. **Expand meeting boost text** for `standup` and `general_meeting` to include leadership/collaboration keywords (e.g. "team coordination", "alignment", "communication").
2. **Consider event_type-only activation** for certain meeting types (e.g. `meeting_attended_standup` → planning_execution) so they don’t depend on phrase/keyword density.
3. **Capture Slack/email leadership events** if a mechanism exists (e.g. session logs, manual tagging).
4. **Review keyword overlap** to reduce double-counting for code events, or accept it as intentional recognition of multi-faceted contributions.
5. **Lower min_signals for meeting event_types** so that `meeting_attended_X` alone can activate the intended competency when the event_type is in that competency's list.
6. **Fix substring false positives**: Keywords like "ship" match inside "leader**ship**", causing spurious end_to_end_delivery activation for 1:1 meetings. Consider word-boundary matching for short keywords.
