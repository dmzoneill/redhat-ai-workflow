# Performance Scoring System: Event Type Bias Analysis

**Purpose:** Determine whether the performance scoring system disproportionately favors code-producing activities over communication/leadership activities, and whether Senior+ engineers who primarily do meetings, mentoring, code reviews, strategy discussions, and architecture oversight would be systematically disadvantaged.

---

## 1. All Unique Event Types by Bucket

| Event Type | Bucket | # Competencies |
|------------|--------|----------------|
| mr_merged | Code/Artifact | 4 |
| mr_opened | Code/Artifact | 3 |
| pr_opened | Code/Artifact | 4 |
| pr_merged | Code/Artifact | 4 |
| commit | Code/Artifact | 4 |
| issue_resolved | Jira/Tracking | 4 |
| issue_created | Jira/Tracking | 3 |
| issue_opened | Jira/Tracking | 3 |
| issue_closed | Jira/Tracking | 5 |
| meeting_participated | Meeting/Communication | 3 |
| meeting_organized_architecture_review | Meeting/Communication | 3 |
| meeting_attended_architecture_review | Meeting/Communication | 3 |
| meeting_organized_training | Meeting/Communication | 2 |
| meeting_attended_training | Meeting/Communication | 2 |
| meeting_organized_incident_response | Meeting/Communication | 2 |
| meeting_attended_incident_response | Meeting/Communication | 2 |
| meeting_organized_code_review | Meeting/Communication | 2 |
| meeting_attended_code_review | Meeting/Communication | 3 |
| meeting_organized_retrospective | Meeting/Communication | 2 |
| meeting_attended_retrospective | Meeting/Communication | 2 |
| meeting_organized_planning | Meeting/Communication | 3 |
| meeting_attended_planning | Meeting/Communication | 3 |
| meeting_organized_sprint_planning | Meeting/Communication | 3 |
| meeting_attended_sprint_planning | Meeting/Communication | 3 |
| meeting_organized_all_hands | Meeting/Communication | 3 |
| meeting_attended_all_hands | Meeting/Communication | 2 |
| meeting_organized_one_on_one | Meeting/Communication | 3 |
| meeting_attended_one_on_one | Meeting/Communication | 3 |
| meeting_attended_cross_team | Meeting/Communication | 2 |
| meeting_organized_cross_team | Meeting/Communication | 2 |
| meeting_organized_presentation | Meeting/Communication | 1 |
| meeting_attended_presentation | Meeting/Communication | 1 |
| meeting_organized_sprint_review | Meeting/Communication | 2 |
| meeting_attended_sprint_review | Meeting/Communication | 2 |
| meeting_organized_standup | Meeting/Communication | 2 |
| meeting_attended_standup | Meeting/Communication | 1 |
| meeting_organized_customer_meeting | Meeting/Communication | 1 |
| meeting_attended_customer_meeting | Meeting/Communication | 1 |
| meeting_organized_interview | Meeting/Communication | 1 |
| meeting_attended_interview | Meeting/Communication | 1 |
| meeting_organized_onboarding | Meeting/Communication | 1 |
| meeting_attended_onboarding | Meeting/Communication | 1 |
| meeting_attended_general_meeting | Meeting/Communication | 1 |
| meeting_organized_general_meeting | Meeting/Communication | 1 |
| gdrive_doc_created | Document/Knowledge | 3 |
| gdrive_doc_contributed | Document/Knowledge | 3 |
| gdrive_sheet_created | Document/Knowledge | 3 |
| gdrive_sheet_contributed | Document/Knowledge | 3 |
| gdrive_slides_created | Document/Knowledge | 3 |
| gdrive_slides_contributed | Document/Knowledge | 3 |
| session_documented | Document/Knowledge | 2 |
| architecture_decision | Document/Knowledge | 3 |
| review_given | Review/Collaboration | 1 |
| pr_reviewed | Review/Collaboration | 2 |
| mr_review_given | Review/Collaboration | 2 |
| mr_review_received | Review/Collaboration | 1 |
| recognition_given | Review/Collaboration | 2 |
| collaboration_activity | Review/Collaboration | 2 |
| leadership_activity | Review/Collaboration | 2 |
| alert_investigated | Other | 3 |
| debugging_outcome | Other | 3 |
| process_improvement | Other | 3 |
| customer_engagement | Other | 2 |

**Total unique event types:** 63

---

## 2. Distribution by Bucket (Competency–Event Type Mappings)

| Bucket | Mappings | % of Total | Unique Event Types |
|--------|---------|------------|--------------------|
| **Code/Artifact** | 19 | **12.7%** | 5 |
| **Jira/Tracking** | 15 | **10.0%** | 4 |
| **Meeting/Communication** | 70 | **46.7%** | 35 |
| **Document/Knowledge** | 23 | **15.3%** | 8 |
| **Review/Collaboration** | 12 | **8.0%** | 7 |
| **Other** | 11 | **7.3%** | 4 |

**Total mappings:** 150

**Combined totals:**
- **Code/Artifact + Jira/Tracking:** 34 mappings (22.7%)
- **Meeting/Communication + Document/Knowledge:** 93 mappings (62.0%)
- **Review/Collaboration:** 12 mappings (8.0%)

---

## 3. Competencies with Zero or Few Meeting/Communication/Document Event Types

| Competency | Meeting/Doc Events | Code/Jira Events | Total | % Meeting/Doc |
|------------|--------------------|------------------|-------|---------------|
| **technical_contribution** | 0 | 6 | 7 | **0%** |
| **end_to_end_delivery** | 0 | 4 | 4 | **0%** |
| **opportunity_recognition** | 0 | 4 | 5 | **0%** |
| **portfolio_impact** | 0 | 0 | 0 | N/A (empty) |
| **execution_as_mentee** | 0 | 0 | 2 | 0% (review-only) |
| **customer_focus** | 2 | 3 | 7 | 29% |
| **scope** | 4 | 7 | 11 | 36% |

---

## 4. Competencies Most Dependent on Code/Jira Events

| Competency | Code/Jira Events | Total | % Code/Jira |
|------------|-----------------|-------|-------------|
| end_to_end_delivery | 4 | 4 | **100%** |
| technical_contribution | 6 | 7 | **86%** |
| opportunity_recognition | 4 | 5 | **80%** |
| scope | 7 | 11 | **64%** |
| customer_focus | 3 | 7 | 43% |
| planning_execution | 3 | 11 | 27% |
| creativity_innovation | 2 | 10 | 20% |
| evidence_record | 4 | 28 | 14% |
| technical_knowledge | 1 | 16 | 6% |
| continuous_improvement | 0 | 7 | 0% |

---

## 5. Assessment: Senior+ Engineer Disadvantage

### Summary

**Yes — a Senior+ engineer who primarily does meetings, mentoring, code reviews, strategy discussions, and architecture oversight would be systematically disadvantaged** in several high-impact competencies, despite the overall mapping distribution favoring meeting/document events.

### Key Findings

#### 1. Critical Competencies Are Code/Jira-Only

Three competencies have **zero** pathways for meeting/communication/document events:

- **technical_contribution** (base_points: 2) — 100% code/artifact + Jira
- **end_to_end_delivery** (base_points: 3) — 100% code/artifact + Jira
- **opportunity_recognition** (base_points: 4) — 80% code/Jira (only `process_improvement` is non-code)

A Senior+ doing strategy, architecture oversight, and mentoring would generate almost no events for these competencies.

#### 2. Level Weights vs. Event Availability

From `competencies.yaml` level_weights, at PSE and above:

- **Technical Contribution** pillar weight decreases (0.8 → 0.35)
- **Leadership** and **Mentorship** pillar weights increase (1.3 → 1.8)

However, **technical_contribution** and **end_to_end_delivery** remain in the Technical Contribution pillar. Even with lower pillar weight, a Senior+ with near-zero events in these competencies will still underperform relative to peers who ship code.

#### 3. What a Senior+ Would Generate vs. What They Would Not

| Activity | Events Generated | Competencies Fed |
|----------|------------------|------------------|
| Meetings (planning, architecture, 1:1s, etc.) | meeting_* | leadership, mentorship, collaboration, evidence_record, technical_knowledge, etc. |
| Code reviews | mr_review_given, pr_reviewed | collaboration, mentorship, execution_as_mentee |
| Architecture decisions | architecture_decision | technical_knowledge, creativity_innovation, leadership |
| Docs/slides | gdrive_* | technical_knowledge, creativity_innovation, evidence_record, speaking_publicity |
| Strategy discussions | meeting_participated, leadership_activity | leadership, evidence_record |

| Activity | Events NOT Generated | Competencies Missed |
|----------|----------------------|---------------------|
| Writing/merging code | commit, mr_merged, pr_merged | technical_contribution, end_to_end_delivery, scope |
| Resolving Jira issues | issue_resolved, issue_closed | technical_contribution, end_to_end_delivery, customer_focus |
| Opening PRs/MRs | pr_opened, mr_opened | technical_contribution, opportunity_recognition, scope |

#### 4. Numeric Impact

- **6 of 16 competencies** (37.5%) have **≤2** meeting/document event types.
- **3 competencies** have **0** meeting/document pathways and are heavily code/Jira-dependent.
- **portfolio_impact** has **0** event types — it cannot be scored from events at all.

#### 5. Competencies That *Do* Reward Senior+ Work

These competencies have strong meeting/document/review pathways:

- **leadership** — 100% meeting + collaboration/leadership
- **mentorship** — 100% meeting + review
- **collaboration** — meeting + review heavy
- **continuous_improvement** — meeting + other (no code/Jira)
- **technical_knowledge** — mixed, strong doc/meeting
- **evidence_record** — broad, includes meetings and docs
- **speaking_publicity** — slides + presentations

---

## 6. Recommendations

1. **Add meeting/document pathways to code-heavy competencies**
   - **technical_contribution:** Consider `architecture_decision`, `meeting_organized_code_review`, or `session_documented` for design/oversight work.
   - **end_to_end_delivery:** Consider `meeting_organized_sprint_review`, `session_documented`, or release-planning meetings.
   - **opportunity_recognition:** Consider `architecture_decision`, `meeting_organized_planning`, or `gdrive_doc_created` for strategy/opportunity docs.

2. **Define event types for portfolio_impact**
   - Currently unscored; add events for cross-service work, API design, or architecture docs.

3. **Calibrate by level**
   - Ensure Senior+ profiles (PSE, SPSE, DE) have sufficient pathways in leadership/mentorship competencies to offset lower technical_contribution event volume.

4. **Review base_points**
   - High base_points competencies (opportunity_recognition: 4, creativity_innovation: 4) that are code-heavy may need meeting/document pathways to avoid penalizing Senior+ engineers.

---

## 7. Conclusion

The system has **many** meeting and document event types (62% of mappings), but they are concentrated in leadership, mentorship, and evidence_record. The competencies that measure **direct technical output** (technical_contribution, end_to_end_delivery, opportunity_recognition) have **no or very few** meeting/document pathways.

A Senior+ engineer focused on meetings, mentoring, reviews, strategy, and architecture would score well on leadership and mentorship competencies but would receive **little or no credit** for technical_contribution, end_to_end_delivery, and opportunity_recognition. This creates a structural bias toward engineers who produce code and Jira activity, even though Senior+ roles are expected to shift toward leadership and communication.
