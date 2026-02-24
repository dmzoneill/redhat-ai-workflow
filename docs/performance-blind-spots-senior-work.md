# Performance Scoring System: Blind Spots for Senior Engineering Work

**Purpose:** Identify systematic gaps in the data collection pipeline that create blind spots for senior/principal engineering work, and propose implementable improvements to reduce bias.

---

## Executive Summary

The performance scoring system collects events from Git, GitLab, GitHub, Jira, Google Calendar/Meet, Google Drive, executive emails, and session logs. Despite having 63+ event types and strong meeting/document pathways for leadership and mentorship competencies, **senior engineers who shift from hands-on coding to architecture, mentoring, strategy, and coordination are systematically under-scored** in several critical dimensions. The system favors **artifact-producing activities** over **conversation-driven, invisible work**.

---

## 1. Communication Channels NOT Captured

| Channel | What's Lost | Competencies Affected |
|---------|-------------|----------------------|
| **Slack messages** | Engineering discussions, help given to others, announcements, technical Q&A, unblocking teammates | mentorship, collaboration, technical_knowledge, leadership |
| **Email threads** | Technical discussions, cross-team coordination, stakeholder alignment, RFC feedback | collaboration, leadership, customer_focus, portfolio_impact |
| **Chat/DMs** | Ad-hoc mentoring, career coaching, sensitive feedback | mentorship, growth_impact |
| **Confluence/wiki comments** | Knowledge sharing, documentation review, feedback on ADRs | technical_knowledge, collaboration |
| **Informal conversations** | Hallway/virtual discussions that drive decisions | leadership, creativity_innovation, continuous_improvement |

**Impact:** A senior engineer who spends 2 hours daily answering questions in Slack, coordinating via email, and commenting on Confluence pages generates **zero events** for that work. A junior who commits 5 times generates 5 events.

---

## 2. Leadership Activities Hard to Capture

| Activity | Why It's Invisible | Competency |
|----------|-------------------|------------|
| **Unblocking team members** | Interruption-driven; no artifact. "Can you look at this?" → 15-min debug → "Try X" | work_impact, collaboration |
| **Strategic thinking in conversations** | Decisions made in 1:1s, hallway chats, Slack threads—not written down | leadership, opportunity_recognition |
| **Influencing without authority** | Persuading across teams via multiple conversations; no single doc | leadership, portfolio_impact |
| **Representing team in management meetings** | Attending meetings where they're not organizer; impact not captured | work_impact, scope |
| **Building consensus** | Multiple conversations to align stakeholders; no traceable artifact | leadership, collaboration |
| **Defining technical direction through discussions** | Architecture decisions made verbally, documented later (or never) | technical_knowledge, creativity_innovation |

**Current partial capture:** `meeting_organized_*` and `meeting_attended_*` capture presence, but not **who drove the decision** or **who unblocked whom**.

---

## 3. Mentorship Activities Hard to Capture

| Activity | Current Capture | Gap |
|----------|-----------------|-----|
| Ad-hoc mentoring in Slack | None | Zero events |
| Pairing sessions (no calendar event) | None | Zero events |
| Code review discussions beyond the review | `mr_review_given` (1 event) | Depth/quality not differentiated |
| Answering questions in team channels | None | Zero events |
| Career coaching conversations | `meeting_attended_one_on_one` if on calendar | Often ad-hoc, not scheduled |
| Onboarding walkthroughs | `meeting_organized_onboarding` if titled | Many are informal |

**Impact:** A senior who mentors 3 people daily via Slack and 1:1s may generate 1–2 meeting events. A junior who receives that mentoring gets `mr_review_received` when their MR is reviewed—asymmetry favors the mentee.

---

## 4. Code Review Depth Problem

**Current behavior:** Each `mr_review_given` or `pr_reviewed` event is a single event regardless of:
- Comment count (1 vs 15)
- Line count reviewed (50 vs 2000)
- Time spent (5 min vs 2 hours)
- Depth of feedback (LGTM vs architectural critique)
- Review decision (APPROVED vs CHANGES_REQUESTED)

**Partial mitigation:** The scorer applies a `review_decision` bonus: `CHANGES_REQUESTED` → +1 signal for mentorship and collaboration. This only applies when the event includes `review_decision`—currently **GitHub PR reviews** have it; **GitLab mr_review_given** events do not consistently pass it.

**Gap:** A 5-minute "LGTM" and a 2-hour deep review that finds architectural issues both generate 1 event. The senior providing the deep review gets minimal extra credit (only if CHANGES_REQUESTED is passed).

**Data available but unused:** GitLab/GitHub APIs expose:
- Comment/thread count per review
- Lines changed in the MR
- Review body length
- Approval state

---

## 5. Meeting Quality vs Quantity

**What the system captures:**
- Organized vs attended (different event types) ✓
- Meeting classification (standup, architecture_review, etc.) ✓
- Attendee count, actual participants (Meet data) ✓

**What it does NOT capture:**
- Whether the person drove key decisions
- Follow-up actions they owned
- Whether they were a key contributor or passive observer
- Speaking time or participation level
- Whether they unblocked someone in the meeting

**Example:** Two engineers attend the same architecture review. Engineer A asks one clarifying question. Engineer B leads the discussion, proposes the design, and drives consensus. Both generate `meeting_attended_architecture_review`—identical events.

---

## 6. "Invisible Work" – 10+ High-Value Senior Activities with Zero/Minimal Events

| # | Activity | What Happens | Competency It Should Feed | Events Generated |
|---|----------|--------------|---------------------------|------------------|
| 1 | **Unblocking a stuck junior** | Junior DMs "I'm stuck on X." Senior spends 20 min debugging, suggests fix. Junior commits. | mentorship, collaboration | 0 (junior gets commit) |
| 2 | **RFC feedback in Slack** | Senior reads RFC doc, provides 500 words of architectural feedback in Slack thread. Author incorporates it. | technical_knowledge, leadership | 0 |
| 3 | **Resolving team conflict** | Two engineers disagree on approach. Senior facilitates 1:1 conversations, finds middle ground. | leadership, collaboration | 0–1 (if 1:1 was on calendar) |
| 4 | **Interview debrief influence** | Senior participates in hiring debrief, advocates for strong candidate, shapes hiring decision. | mentorship, leadership | 1 (`meeting_attended_interview`) |
| 5 | **Explaining system to new hire** | 45-min walkthrough of architecture—no formal meeting, just screen share. | mentorship, technical_knowledge | 0 |
| 6 | **Coordinating cross-team dependency** | Senior emails/Slacks 3 teams to align on API contract. No doc created; verbal agreement. | portfolio_impact, collaboration | 0 |
| 7 | **Incident triage and delegation** | Senior joins war room, assigns tasks, coordinates. Doesn't write code; drives resolution. | continuous_improvement, work_impact | 1 (`meeting_attended_incident_response`) |
| 8 | **Strategic input in skip-level** | Senior provides product feedback to director in 1:1. Influences roadmap. | leadership, opportunity_recognition | 1 (`meeting_attended_one_on_one`) |
| 9 | **Reviewing design doc (not in GDrive)** | Design lives in Confluence. Senior leaves 10 comments. Author updates. | technical_knowledge, creativity_innovation | 0 |
| 10 | **Mentoring through code review discussion** | 30-min call to walk through review comments, teach patterns. No MR merged that day. | mentorship, technical_knowledge | 0–1 (mr_review_given if they left comments) |
| 11 | **Removing organizational impediments** | Senior escalates to management about tooling/licensing blocking the team. Gets it resolved. | continuous_improvement, work_impact | 0 |
| 12 | **Customer escalation triage** | Senior joins customer call, diagnoses issue, delegates fix to junior. Doesn't touch code. | customer_focus, work_impact | 1 (`meeting_attended_customer_meeting`) |

**Summary:** 7 of 12 activities generate **zero** events. The rest generate 1 event each, with no differentiation for impact.

---

## 7. Volume Disparity: Estimated Daily Event Counts

### Assumptions
- **Junior/Mid:** 70% coding, 20% meetings, 10% reviews
- **Senior/Principal:** 30% coding, 40% meetings/reviews/mentoring, 30% strategy/coordination/invisible work

### Junior/Mid Engineer (Typical Day)

| Source | Events | Notes |
|--------|--------|------|
| **Git** | 3–6 | 3–6 commits |
| **GitLab** | 0–1 mr_opened, 0–1 mr_merged | 1 MR in progress |
| **GitHub** | 0–1 | If OSS contributor |
| **Jira** | 1–3 | issue_resolved, issue_created, issue_closed |
| **Meetings** | 2–4 | standup, sprint planning, 1–2 others |
| **GDrive** | 0–1 | Occasional doc/sheet |
| **Session** | 0–2 | start_work, create_mr, etc. |
| **Reviews** | 0–1 | mr_review_given (light) |
| **Total** | **8–19** | **~12 avg** |

### Senior/Principal Engineer (Typical Day)

| Source | Events | Notes |
|--------|--------|------|
| **Git** | 0–2 | Fewer commits; more oversight |
| **GitLab** | 0–1 mr_merged | May merge less |
| **GitHub** | 0 | Often internal only |
| **Jira** | 0–2 | issue_created, issue_closed; fewer resolved |
| **Meetings** | 4–7 | More 1:1s, architecture, planning, customer |
| **GDrive** | 0–2 | Strategy docs, architecture |
| **Session** | 0–1 | Less AI-assisted workflow |
| **Reviews** | 2–5 | More reviews, but 1 event each |
| **Total** | **6–22** | **~11 avg** |

### The Gap

- **Junior:** Higher volume from **code + Jira** (technical_contribution, end_to_end_delivery)
- **Senior:** Higher volume from **meetings + reviews** (leadership, mentorship, collaboration)

But:
1. **technical_contribution** and **end_to_end_delivery** have **no** meeting pathways
2. **portfolio_impact** has **zero** event types
3. Senior "invisible work" (Slack, email, unblocking) = **0 events**
4. Review depth is not differentiated

**Result:** Senior can have similar or higher *total* events but **lower scores** in code-heavy competencies and **no credit** for portfolio_impact or invisible work.

---

## 8. Recommendations: 5–7 Implementable Improvements

### R1: Slack Message Collector (Medium Complexity)

| Aspect | Detail |
|--------|--------|
| **Data source** | Slack API (conversations.history, users.conversations) |
| **Events** | `slack_help_given`, `slack_discussion_contributed`, `slack_announcement` |
| **Logic** | Heuristic: messages in #help channels, replies to questions, threads where user is not OP |
| **Competencies** | mentorship, collaboration, technical_knowledge |
| **Complexity** | **Medium** – OAuth, rate limits, channel discovery, privacy (opt-in) |

### R2: Code Review Depth Scoring (Low Complexity)

| Aspect | Detail |
|--------|--------|
| **Data source** | Existing GitLab/GitHub API – add comment count, line count, body length |
| **Events** | Same `mr_review_given`, `pr_reviewed` but with **metadata**: `review_comment_count`, `review_body_length`, `mr_lines_changed` |
| **Logic** | Tiered multiplier or extra signals: e.g. 5+ comments OR 500+ chars → +1 mentorship signal |
| **Competencies** | mentorship, collaboration, technical_knowledge |
| **Complexity** | **Low** – enrich existing events; scorer already accepts metadata |

### R3: Pass review_decision for GitLab mr_review_given (Low Complexity)

| Aspect | Detail |
|--------|--------|
| **Data source** | GitLab Merge Request Approvals API – get approval state per user |
| **Events** | `mr_review_given` with `review_decision`: APPROVED | CHANGES_REQUESTED |
| **Logic** | Map GitLab approval state to review_decision; scorer already uses it |
| **Competencies** | mentorship (CHANGES_REQUESTED bonus) |
| **Complexity** | **Low** – API exists; wire through collector |

### R4: Confluence/Wiki Comment Collector (Medium Complexity)

| Aspect | Detail |
|--------|--------|
| **Data source** | Confluence REST API – user's comments on pages |
| **Events** | `confluence_comment_authored`, `confluence_page_contributed` |
| **Logic** | Comments on pages in team spaces; optional: page type (ADR, design, runbook) |
| **Competencies** | technical_knowledge, collaboration |
| **Complexity** | **Medium** – API, space discovery, pagination |

### R5: Meeting Participation Metadata (Medium–High Complexity)

| Aspect | Detail |
|--------|--------|
| **Data source** | Google Meet API (already used) – extend to track speaker time or "active" segments |
| **Events** | Same meeting events with `meeting_speak_time_seconds` or `meeting_was_organizer` (already have organizer) |
| **Logic** | Meet API may expose participant activity; or: integrate with transcription tools |
| **Competencies** | leadership, speaking_publicity, evidence_record |
| **Complexity** | **Medium–High** – Meet API limits; may need third-party (Otter, etc.) |

### R6: Session Log → "Unblocking" / "Mentoring" Classification (Low Complexity)

| Aspect | Detail |
|--------|--------|
| **Data source** | Existing session logs |
| **Events** | New: `session_mentoring`, `session_unblocking` (or expand `collaboration_activity`, `leadership_activity`) |
| **Logic** | Classify session entries: "explain", "debug", "pair", "review" → mentorship/collaboration |
| **Competencies** | mentorship, collaboration |
| **Complexity** | **Low** – extend `_classify_session_entry` rules |

### R7: Portfolio Impact Event Types (Low–Medium Complexity)

| Aspect | Detail |
|--------|--------|
| **Data source** | Existing + new mappings |
| **Events** | Add to portfolio_impact: `gdrive_doc_created` (when classification=architecture_doc), `meeting_organized_cross_team`, `issue_created` (when epic/ANSTRAT scope) |
| **Logic** | portfolio_impact has **empty** event_types; add phrase/keyword + event_type matches |
| **Competencies** | portfolio_impact |
| **Complexity** | **Low–Medium** – config change + ensure cross-team/API phrases in classification text |

---

## 9. Priority Matrix

| Recommendation | Impact | Complexity | Priority |
|-----------------|--------|------------|----------|
| R2: Review depth scoring | High | Low | **P0** |
| R3: GitLab review_decision | Medium | Low | **P0** |
| R7: Portfolio impact events | High | Low | **P0** |
| R6: Session mentoring classification | Medium | Low | **P1** |
| R4: Confluence comments | Medium | Medium | **P2** |
| R1: Slack collector | High | Medium | **P2** |
| R5: Meeting participation quality | High | High | **P3** |

---

## 10. Conclusion

The performance scoring system has **structural blind spots** for senior engineering work:

1. **Communication channels** (Slack, email, Confluence comments) are uncaptured.
2. **Leadership and mentorship** that happen in conversations, not artifacts, generate zero events.
3. **Code review depth** is flat—one event per review regardless of impact.
4. **Meeting quality** (who drove decisions, who spoke) is not captured.
5. **Portfolio impact** has no event types at all.
6. **Volume disparity** favors juniors in code-heavy competencies despite level weights.

**Quick wins:** R2, R3, R7 (all low complexity) would immediately reduce bias. R6 extends existing session classification. R1 and R4 require new integrations but would capture significant invisible work.
