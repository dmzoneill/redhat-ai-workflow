# Peer Data Backfill Audit Report – Q1 2026

**Date:** 2026-02-23
**Scope:** 135 peers, Jan 1 – Feb 22, 2026
**Data:** `~/.config/aa-workflow/performance/2026/q1/performance/peers/`

---

## Overall Verdict

**VERDICT: LIKELY VALID (with expected gaps and minor issues)**

The backfill produced usable event data. No critical collection bugs were found. Source coverage gaps are consistent with known design limits (session local-only, peer repo discovery from MR/PR caches, meeting index from user calendar). Event content quality is good: required fields present, no duplicates, scoring consistent between self and peers.

---

## 1. Source Coverage by Level

### Self baseline
- **Sources:** git, gitlab, github, jira, gdrive, session, meeting
- **Event counts:** git 286, gitlab 138, meeting 98, jira 63, gdrive 11, session 321, github 255
- **Total:** 1,172 events

### Peer coverage by level

| Level | Peers | git | github | gitlab | jira | meeting | gdrive |
|-------|-------|-----|-------|--------|------|---------|--------|
| ASE   | 9     | 89% | 67%   | 67%    | 78%  | 89%     | 22%    |
| SE    | 26    | 69% | 65%   | 46%    | 92%  | 88%     | 35%    |
| SSE   | 59    | 80% | 86%   | 41%    | 95%  | 81%     | 41%    |
| PSE   | 27    | 89% | 89%   | 67%    | 89%  | 85%     | 59%    |
| SPSE  | 13    | 100%| 100%  | 23%    | 77%  | 77%     | 69%    |
| DE    | 1     | 0%  | 100%  | 0%     | 100% | 100%    | 0%     |

### Gaps and interpretation

| Source   | Missing for peers? | Interpretation |
|----------|--------------------|----------------|
| **session** | All peers | **Expected.** Session logs are local-only; peers never get session events. |
| **gdrive**  | 75/135 peers (56%) | **Expected.** Peers only get shared-drive contributions. Many peers may not contribute to shared drives. |
| **meeting** | 22 peers | **Expected.** Peer meetings come from the user’s calendar attendee index. Peers in different teams/calendars are not visible. |
| **git**     | 15 peers (incl. DE majones) | **Expected.** Repos come from config + MR/PR caches. Peers on different projects (e.g. ansible vs AAP) may have no overlapping repos. |
| **gitlab**  | 81 peers (60%) | **Expected.** GitLab coverage depends on MRs in cache; many peers work primarily on GitHub (ansible). |
| **jira**    | 9 peers | **Expected.** Jira uses prefetch by username; some peers may have no AAP/ANSTRAT activity. |

**Conclusion:** Source gaps are consistent with known design and not evidence of a new bug.

---

## 2. Event Content Quality

### Sample: 5 peers with >100 events (one per level)

| Peer     | Level | Events | Days | Issues |
|----------|-------|--------|------|--------|
| nmonk    | ASE   | 351    | 39   | None   |
| lyasin   | SE    | 260    | 39   | None   |
| dvernier | SSE   | 658    | 39   | None   |
| daoneill | PSE   | 782    | 39   | None   |
| smcdonal | SPSE  | 385    | 39   | None   |

### Checks performed

- **Required fields:** All sampled events have `title`, `source`, `type`; git events have `item_id`.
- **Attribution:** Events look correct (e.g. dvernier: `git:devaiflow`, `jira:AAP-62714`; daoneill: `git:redhat-ai-workflow`, `git:automation-analytics-backend`).
- **Git commits:** Spot-checked `c7942d36` in redhat-ai-workflow – commit exists and message matches.
- **Jira:** AAP-63891, AAP-62714, etc. are plausible AAP issues.
- **Duplicates:** No duplicate event IDs in sampled daily files (daoneill 2026-01-15, 2026-01-22).

**Conclusion:** Event content quality is good; no misattribution or structural issues found.

---

## 3. Scoring Sanity Check

### Git commit points (self vs peer)

| Source | Sample | Points | Total |
|--------|--------|--------|-------|
| Self   | `[automation-analytics-backend] Merge branch 'konfl...` | creativity_innovation:1, end_to_end_delivery:1, scope:1 | 3 |
| Peer daoneill | Same commit | Same | 3 |

**Conclusion:** Scoring is consistent between self and peers for the same event type.

---

## 4. Meeting Event Audit

### Self
- 98 meeting events

### Peers
- 113 peers have meeting events
- Top 5 by count: smcdonal (149), pbohmill (68), palonso (52), daoneill (48), bthomass (45)

### Sample meeting titles (5 peers)

| Peer     | Sample meetings |
|----------|-----------------|
| smcdonal | Office Hours: aap-dev; Ansible Staff Engineering Weekly; AoC Architecture Review Board; Staff Engineering Proposal Review |
| pbohmill | ANSTRAT-1736 check-in; ANSTRAT-1738 check-in; Emily Figures It Out |
| palonso | Ansible PDE EMEA Office Hour; Controller Architecture Sync |
| daoneill | David / Ben; SIG AAP AI; Automation Analytics Daily Standup; PM Backlog Refinement |
| bthomass | Automation Analytics Daily Standup; PM Backlog Refinement; Analytics team meeting; Sprint Planning |

**Conclusion:** Meeting events look reasonable (standups, planning, architecture, office hours). No obvious noise. Peer meetings come from calendar attendance; coverage is limited to meetings the user attends.

---

## 5. GDrive Event Audit

### Self
- 11 gdrive events

### Peers
- 60 peers have gdrive events
- Sample types: `gdrive_doc_created`, `gdrive_doc_contributed`, `gdrive_sheet_contributed`, `gdrive_doc_commented`, `gdrive_slides_contributed`

### Sample titles
- `[Google Doc] Platform UI Q1/2026`
- `[Google Doc] Ansible Priority Review - Format and Schedule`
- `[Google Sheet] Emerging Services Team Health Check 2025 Data Sheet`
- `[Google Doc] Controller Architecture Sync`

**Conclusion:** GDrive events look like real shared-drive contributions (docs, sheets, slides). No obvious noise. 75 peers with no gdrive events is expected if they do not contribute to shared drives.

---

## 6. Cross-Peer Consistency

### PSE: bbhavsar (14 events) vs daoneill (782 events)

| Peer     | Events | Sources |
|----------|--------|---------|
| bbhavsar | 14     | git, github, gdrive |
| daoneill | 782    | git, github, gitlab, jira, meeting |

**bbhavsar missing:** meeting, jira, gitlab.

**Possible reasons:**
1. **Different project:** bbhavsar may work on different repos/projects; GitLab MR cache may be empty or not overlap with config repos.
2. **Calendar:** bbhavsar may not appear in the user’s meeting attendee index.
3. **Jira:** May have no AAP/ANSTRAT activity in the quarter.
4. **Activity level:** 14 events over 39 days is low but plausible for some roles.

**Conclusion:** The difference is consistent with known collection limits (repo discovery, meeting index, Jira scope), not necessarily a bug.

### SSE: kcase (15 events) vs dvernier (658 events)

| Peer     | Events | Sources |
|----------|--------|---------|
| kcase    | 15     | git, github, jira, meeting |
| dvernier | 658    | git, github, jira, meeting |

Both have the same four sources. The large event-count difference is consistent with different activity levels rather than a collection bug.

---

## 7. Specific Quality Issues Found

### Minor

1. **Empty daily files:** 135 peers have at least one empty daily file (e.g. bbhavsar: 32/39 empty). Expected when a peer has no activity on that day.
2. **Sudden stop:** 7 peers have last event date before 2026-02-20 (bbhavsar, erezende, mkrizek, mmartz, msandova, qiding, soli). Could be PTO, role change, or collection cutoff; not clearly a bug.
3. **Few sources:** 9 peers have 1–2 sources when their level median is 4–5 (bcoca, chagrawa, eclarizi, gosriniv, kodesai, mandkulk, mipospis, ssydoren, tgeetika). Consistent with project/team differences.

### None found

- No summary vs daily `total_events` mismatches
- No malformed JSON
- No peers with 0 events across all files
- No duplicate event IDs in sampled files

---

## 8. Recommendations

1. **Document expected gaps:** Add a short note that peers do not get session events and that gdrive/meeting/git/gitlab coverage depends on shared drives, calendar, and MR/PR caches.
2. **Investigate “sudden stop” peers:** For the 7 peers with last event before Feb 20, confirm whether this is PTO, role change, or a collection issue.
3. **DE peer (majones):** Single DE with 0 git, 0 gitlab. Verify whether this is expected for a director-level role (more meetings/jira, less code).
4. **Reuse audit script:** `scripts/audit_peer_event_quality.py` can be run after future backfills for regression checks.

---

## Appendix: Audit Scripts

- `scripts/audit_peer_backfill.py` – Daily file count, empty files, date gaps, summary vs daily
- `scripts/audit_peer_event_quality.py` – Source coverage, event quality, meeting/gdrive, scoring, cross-peer consistency
