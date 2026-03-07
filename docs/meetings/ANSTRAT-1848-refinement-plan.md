# ANSTRAT-1848 Refinement: Suggested Updates for Review

**Epic:** [AAP-66639](https://issues.redhat.com/browse/AAP-66639) – ANSTRAT-1848 Refinement actions
**Meeting:** 2026-03-05 – Shane McDonald, David O Neill, Zvika Sadeh
**Meeting notes:** [Google Doc](https://docs.google.com/document/d/1ILmwwMW2tiYcHGHgtLC6en_Iep_Fpev_Q54gzNwqg4Y/edit?tab=t.ukbxs0wui6lo)
**Fetched copy:** [docs/meetings/anstrat1848-notes-fetched.txt](anstrat1848-notes-fetched.txt)
**SDP:** [ansible/handbook PR #1223](https://github.com/ansible/handbook/pull/1223) – review for alignment with this plan.

---

## SDP alignment (PR #1223)

The System Design Proposal is in the handbook PR above. This plan is based on the 2026-03-05 refinement meeting; the SDP was not accessible from this environment (repo may be private), so **please verify the following against the actual PR** and adjust task comments if needed:

- **Architecture (AAP-66641):** Confirm the PR reflects “SDP open, proposals will follow”; any blocking problem statements and their status.
- **Test plan (AAP-66645):** Confirm the SDP/proposals describe Phase 1 verification (connectivity + receiving data, Prometheus/Grafana, “receive” defined) and that Phase 2 is out of scope for this initiative.
- **CI/CD (AAP-66646):** Confirm whether the SDP mentions SAS pipeline changes or assertions for data showing up in staging; align the task comment with what’s in the PR.
- **Security (AAP-66644):** If the SDP describes external IPs or network changes, ensure the task comment’s Thomas Eagle review is consistent with the written design.
- **Docs / SAS (AAP-66642):** If the PR adds or references handbook/docs for hub–spoke or SAS-owned work, ensure the “SAS team owns internal docs” comment still matches.

After checking the PR, add any SDP-specific wording into the suggested comments (e.g. “Per SDP in handbook PR #1223 …”) where it helps.

---

## Summary from meeting notes

- **Keep open (4):** Architecture Definition (AAP-66641), Security Assessment (AAP-66644), Test Plan (AAP-66645), Downstream CI/CD Pipeline Adjustments (AAP-66646).
- **Close with comment (8):** Kickoff (66640), Engage with Docs (66642), Engage with UX (66643), Build and Release (66647), Installer (66648), Release Eng (66649), Perf and Scale (66650), Cloud Assessment (66651).
- **Security (66644):** Assessment is necessary; consult Thomas Eagle (product security architect, Ansible) re: external IPs before proceeding.
- **Phase 1:** Verification = establishing connectivity and receiving data; Phase 2 (data validation / end-to-end) is a separate initiative.

---

## Epic AAP-66639 – Update

```
Refinement meeting 2026-03-05 (Shane McDonald, David O Neill, Zvika Sadeh).

Reviewed all refinement action tasks for Stage Connectivity Initiative (1848). Decisions:
- Keep open: Architecture Definition (SDP in progress), Test Plan (to be addressed in SDP/proposals), Downstream CI/CD (pending SAS side changes).
- Close with detailed comments: Kickoff, Engage with Docs, Engage with UX, Security (see Security task), Build and Release, Installer, Release Eng, Perf and Scale, Cloud Assessment.

Meeting notes: https://docs.google.com/document/d/1ILmwwMW2tiYcHGHgtLC6en_Iep_Fpev_Q54gzNwqg4Y/edit
SDP: https://github.com/ansible/handbook/pull/1223
```

---

## Acceptance criteria from Jira (fetched via jira_view_issue)

Below is the **exact** description and acceptance criteria from each task (developer persona loaded). Where the tool output was truncated, the note "(truncated in tool output)" is added—verify full text in Jira if needed.

### AAP-66640 – Schedule Initial Kickoff and establish communication plan
- **AC (tool output truncated):** "Ongoing sync is scheduled... (truncated)"
- **Description:** PM schedules initial kickoff with Feature Team (Feature Assignee/Developer/Architect, Outcome Leads, UX Lead, Docs Lead, Build and Release, Perf and Scale, plus reps from PDTS). Establish communication plan: recurring sync with notes, slack channel, weekly comment summarizing status (including what happened last week, what is coming this week, and a dated milestone plan for getting out of Refinement or getting to Done), Jira view(s). Feature description and acceptance criteria are reviewed by functional SMEs. Confirm scope and rank w/ feature team.

### AAP-66641 – Architecture Definition
- **AC (tool output truncated):** "Investigation and design work needed to deliver the SDP and proposals is tracked in one or more Epics and child Spikes and Stories under the Feature/Initiative... (truncated)"
- **Description:** Create a System Design Plan for your Feature/Initiative, present it to Staff Engineering at a Staff Engineering Proposal Review call, identify and add required reviewers, and shepherd your SDP through approval and merge. If any changes to the Feature definition are discovered during this process, you must work with your fellow Feature Leads to reflect the changes in the Jira feature. Proposals must be created for every problem statement in the SDP. For any problem statements that jeopardize the feasibility of the Feature or materially impact the size or scope of the Feature (including but not limited to which components are impacted), these proposals MUST be written, approved, and merged before closing this ticket and exiting refinement. These problem statements MUST be marked as "Blocking" in the SDP. Low risk problem statements may be completed while the feature is In Progress, but MUST have Jira issues created for them before closing this issue. Expectations: Feature Architect works to deliver the SDP; Feature Architect and feature delivery team engineers work to deliver at least the blocking proposals. Create a design and investigation Epic with stories and spikes needed to author the SDPs and Proposals. (Plus resources/guidance links.)

### AAP-66642 – Engage with Docs
- **AC (tool output truncated):** "Docs Lead is identified and added as the Doc Contact on the Feature... (truncated)"
- **Description:** Have you collaborated with the Docs team, prior to development, about requirements or expectations for this feature so they can properly scope the documentation impact? If doc work is required, collaborate with the doc team to define the work in JIRA, and then add Issue Links (depends on) to those doc Issues.

### AAP-66643 – Engage with UX
- **AC (tool output truncated):** "UX or UI contact is specified for the Feature... (truncated)"
- **Description:** The UX team should already have been involved to progress the Feature from New --> Refinement (e.g. providing user research and/or user feedback). This step is to ensure that engagement happened, and we have identified additional UX effort needed to refine the feature. UX team contact: ansible-ux@redhat.com, #ansible-ux-feedback.

### AAP-66644 – Security Assessment
- **AC (exact):** (1) If any security work is needed for the feature, reflect in the Feature Acceptance Criteria and create child issue(s) in the feature. (2) Add a comment to this issue linking to issue(s) created, or confirm no actions are needed.
- **Description:** Refer to "When to reach ProdSec." Have you assessed the increased/decreased security risks/vectors that this Feature will present? Have you ensured that any new code added for this Feature will be properly scanned and results reported and saved for future reference? If your change is significant, have you reached out to Thomas Eagle (platform/content/everything non-cloud) or Juan Perez de Algaba (cloud) for guidance and next steps? If you're not sure if your change is significant wrt product security, always reach out.

### AAP-66645 – Test Plan
- **AC (tool output truncated):** "QA Contact is identified and set on the Feature or Initiative... (truncated)"
- **Description:** This issue focuses on creating a comprehensive test plan for the feature (feature requirements, AAP topologies to validate, test environment specs, test cases including integration positive/negative, tier categorization, ATF library requirements, hackathon if needed). The test plan must adhere to the standard template and be generated using an AI-powered tool; engage PM, EM, SWEs, SQEs for review and sign-off before implementation. Once finalized, store in central repository (test plans accessible from the referenced site after merge).

### AAP-66646 – Downstream CI/CD Pipeline Adjustments
- **AC (exact):** (1) Create issues for any pipeline automation to validate the given feature. (2) Create issues for any new pipeline job configurations. (3) Notify PDE (Product Delivery Engineering) of these new issues to allow ample time for planning and delivery.
- **Description:** Identify and implement any necessary adjustments to downstream CI/CD pipelines or infrastructure managed by PDE: adapting pipeline automation for new installer inputs if required, identifying/setting up additional external services for testing, outlining pipeline changes beyond standard promotion for feature validation, configuring additional pipeline jobs tailored to the feature beyond standard AAP topologies.

### AAP-66647 – Build and Release
- **AC (exact):** (1) Documentation on how to onboard AAP GA build, or build tech preview containers or dev preview containers are reviewed. (2) A tracking epic is created and a comment is left here to highlight the identified build and release needs as well as the tracking epic.
- **Description:** Identify build and release needs by reviewing handbook links (Konflux GA onboarding, Tech Preview containers, Dev Preview). If needs don't match existing patterns, coordinate with PDE. Create a tracking epic and close this one with a comment listing build/release needs and the tracking epic.

### AAP-66648 – Installer
- **AC (exact):** (1) Create child issue(s) for any actions needed to support installer changes. (2) Add comment linking to issue(s) created, or comment stating why no installer changes are needed.
- **Description:** Installer changes are often needed when: new component introduced to AAP; new settings to existing components; change in how components communicate; additional infrastructure/services (DB, caching, etc.). Review the feature needs and identify if potential installer changes are required. Contact: #forum-ansible-product-delivery-engineering, @aap-pde-installers.

### AAP-66649 – Engage with Release Engineering team (non-AAP specific)
- **AC (exact):** (1) If any Release Engineering engagement is needed for non-AAP specific releases, appropriate tracking epic/issues are created or related SPMM issues are created and shared as part of the closing comment for this issue. (2) If no Release Engineering engagement is needed, a closing comment has been added to this issue explaining WHY [release engineering engagement is] not needed.
- **Description:** For non-AAP specific releases (e.g. RHDH, Portal), Release Engineering engagement is needed when: any content will be published on access.redhat.com/downloads; any content should be entitled to customers other than "all current & future AAP customers". If so, communicate @ahills & @jostone on #spmm or #forum-ansible-product-delivery-engineering. Engage 4+ weeks before desired release date (longer if new product/entitlement).

### AAP-66650 – Engage with Performance and Scale
- **AC (tool output truncated):** "Performance KPIs/SLOs and Observability methods documented... (truncated)"
- **Description:** During refinement, define performance characteristics before consulting Perf/Scale team. Document: Performance KPIs/SLOs and how measured/observed; Scale targets (partner with PM, use TeleSense, support trends, precedent); Scaling factors; Architectural impact on performance; Minimum testing requirements (large-scale and nightly regression). Then schedule consultation with Perf/Scale to validate assumptions and identify risks.

### AAP-66651 – Complete a Cloud Assessment
- **AC (tool output truncated):** "If managed offerings impacts are identified:... (truncated)"
- **Description:** Assess whether this feature impacts AAP's managed offerings (SaaS/Cloud). Contact managed offerings team if the feature: adds new services/pods/containers; materially impacts infrastructure or resource requirements; introduces customer-facing settings (read-only/hidden for managed); needs install-time vs runtime configuration; creates new data types or backup/DR considerations; introduces new metrics/logs/health checks; has data residency/compliance/regional constraints; affects upgrade/migration; requires new support procedures; or when in doubt. Reach out via #team-ansible-on-clouds-saas and @aoc-leads.

---

## How to use this section

For each task we list **AC alignment**: each Jira acceptance criterion is marked **Satisfied**, **N/A** (not applicable with reason), or **Gap** (not yet met, with what’s missing). The **Reworked comment** is then written so each bullet maps to an AC point and states how we meet it or why it’s N/A. Where Jira AC was truncated, we align to the description and note that full AC should be verified in Jira.

---

## Tasks – AC alignment and reworked comments

### AAP-66640 – Schedule Initial Kickoff and establish communication plan | **Close**

**Jira description (summary):** PM schedules kickoff with Feature Team; establish communication plan (recurring sync, slack, weekly status comment, Jira view(s)); feature description and AC reviewed by functional SMEs; confirm scope and rank.
**AC alignment:**

| Expectation | Alignment | Notes |
|-------------|-----------|--------|
| Kickoff scheduled with Feature Team | **Satisfied** | Multiple prior calls between Razique and SAS team = kickoff; coordination in place. |
| Communication plan (recurring sync, slack, weekly comment, Jira view) | **Satisfied** | Coordination via existing channels; no separate recurring sync or Jira view required for this refinement-only initiative. |
| Feature description and AC reviewed by functional SMEs | **Satisfied** | Scope and approach confirmed in kickoff discussions. |
| Scope and rank confirmed w/ feature team | **Satisfied** | Confirmed in those discussions. |

**Comment:**

```
Refinement 2026-03-05: Closing as complete.

* Kickoff — Satisfied: Multiple prior calls between Razique and the SAS team are considered the kickoff; ongoing coordination is in place.
* Communication plan — Satisfied: Coordination via existing channels; no separate recurring sync, slack, weekly comment, or Jira view required for this refinement initiative.
* SME review / scope & rank — Satisfied: Feature scope and approach confirmed in those discussions. No additional SME review needed before exiting refinement.
```

### AAP-66641 – Architecture Definition | **Keep open**

**Jira description (summary):** Create SDP; present at Staff Engineering Proposal Review; shepherd through approval/merge. Proposals for every problem statement; blocking ones must be written/approved/merged before closing and exiting refinement. Create design epic with stories/spikes.
**AC alignment:**

| Expectation | Alignment | Notes |
|-------------|-----------|--------|
| SDP created and presented | **Satisfied (in progress)** | SDP open (handbook PR #1223); may need slight tweaks. |
| Blocking proposals written/approved/merged before closing | **Gap** | Not yet done; outstanding questions; proposals will follow once we have clarity. Task kept open for this reason. |
| Design epic with stories/spikes for SDP and proposals | **Satisfied (in progress)** | SDP work will be story-pointed and assigned to current sprint. |
| Other AC (if any) | — | Verify full AC in Jira. |

**Comment:**

```
Refinement 2026-03-05: Keeping open – in progress.

* SDP — Satisfied (in progress): Open (handbook PR #1223). May need slight tweaks based on ongoing discussions.
* Blocking proposals — Gap: Not all approved/merged yet. Outstanding questions; we are engaging; proposals will follow once we have more clarity. This task stays open until blocking proposals are done.
* Design epic / stories — Satisfied (in progress): SDP work will be story-pointed and assigned to current sprint. Close this task when SDP is approved/merged and blocking proposals are done.
```

---

### AAP-66642 – Engage with Docs | **Close**

**Jira description (summary):** Collaborate with Docs team prior to development; if doc work required, define work in JIRA and add Issue Links. *(AC truncated—likely “Docs Lead identified as Doc Contact”; verify in Jira.)*

**AC alignment:**

| Expectation | Alignment | Notes |
|-------------|-----------|--------|
| Collaborate with Docs team on requirements/expectations | **Satisfied** | No doc work required for analytics team for this initiative. |
| If doc work required: define in JIRA, add Issue Links | **N/A** | No doc work required for us; no JIRA doc issues to create. |
| Docs Lead / Doc Contact (if in AC) | **N/A** | We are not the doc owner; SAS team owns internal docs (hub–spoke, private link). Consider epic for SAS doc work. |

**Comment:**

```
Refinement 2026-03-05: Closing.

* Collaborate with Docs team — Satisfied: We confirmed no customer-facing documentation is required for this initiative.
* Doc work in JIRA / Issue Links — N/A: No doc work required for analytics team; no doc issues to create or link.
* Doc ownership — N/A: Internal docs (hub–spoke, private link) are the responsibility of the SAS team; they own the infrastructure. Analytics team will not own this architecture. Consider creating an epic for SAS team changes and documentation.
```

---

### AAP-66643 – Engage with UX | **Close**

**Jira description (summary):** Ensure UX was involved (New → Refinement); identify additional UX effort. Contact: ansible-ux@redhat.com, #ansible-ux-feedback. *(AC truncated—likely “UX or UI contact is specified”; verify in Jira.)*

**AC alignment:**

| Expectation | Alignment | Notes |
|-------------|-----------|--------|
| UX involvement / additional UX effort identified | **N/A** | No UX impact; initiative is network connectivity only, no UI changes. |
| UX or UI contact specified (if in AC) | **N/A** | No UX/UI contact needed; no UI changes. |

**Comment:**

```
Refinement 2026-03-05: Closing.

* UX involvement / additional UX effort — N/A: This initiative is purely network connectivity with no UI changes. No UX engagement required.
* UX or UI contact — N/A: No contact needed; no UI impact.
```
---

### AAP-66644 – Security Assessment | **Keep open**

**Jira AC (exact):** (1) If any security work is needed for the feature, reflect in the Feature Acceptance Criteria and create child issue(s) in the feature. (2) Add a comment to this issue linking to issue(s) created, or confirm no actions are needed.

**AC alignment:**

| AC | Alignment | Notes |
|----|-----------|--------|
| (1) Security work needed → reflect in Feature AC, create child issue(s) | **Gap** | Security work is needed (external IPs). We will consult Thomas Eagle. After review we will either create child issue(s) and reflect in Feature AC, or confirm no actions needed. Task kept open until then. |
| (2) Add comment linking to issue(s) or confirm no actions needed | **Gap** | Will add this comment when we close (after Thomas Eagle review). |

**Comment:**

```
Refinement 2026-03-05: Keeping open – security review pending.

* AC (1) Security work needed — Gap (in progress): Security assessment is necessary; opening external IPs could present risk. Same restrictions as normal inbound interface apply. Plan to consult Thomas Eagle (product security architect, Ansible) once the plan is in place. After review we will reflect in Feature AC and create child issue(s) if needed, or confirm no actions needed.
* AC (2) Comment linking to issue(s) or confirm no actions — Gap: Will add that comment when we close this task after Thomas Eagle review.
```
---

### AAP-66645 – Test Plan | **Keep open**

**Jira description (summary):** Test plan (requirements, topologies, test env, test cases, tiers, ATF library, hackathon if needed); standard template + AI tool; review/sign-off from PM, EM, SWEs, SQEs; store in central repo. *(AC truncated—includes “QA Contact is identified and set on the Feature or Initiative”; verify full AC in Jira.)*

**AC alignment:**

| Expectation | Alignment | Notes |
|-------------|-----------|--------|
| QA Contact identified and set on Feature/Initiative | **Satisfied** | Engineers (per refinement discussion). |
| Test plan created (requirements, verification approach, etc.) | **Gap** | Test plan will be captured in SDP/proposals (handbook PR #1223). Phase 1 = connectivity + receive data (Prometheus/Grafana; non-firing alerts as validation); Phase 2 out of scope. “Receive” to be qualified in proposal. Task kept open until proposal outlines Phase 1 mechanics. |
| Other AC (template, sign-off, central repo) | — | Verify full AC in Jira; will be addressed when test plan is finalized in SDP. |

**Comment:**

```
Refinement 2026-03-05: Keeping open – test plan to be captured in SDP/proposals.

* QA contact — Satisfied: Identified (engineers; per refinement discussion).
* Test plan / verification — Gap (in progress): Phase 1 = establish connectivity and confirm we receive data; Prometheus/Grafana for telemetry; non-firing alerts as validation for now. Phase 2 (end-to-end / data accuracy) out of scope. “Receive” to be qualified in proposal (e.g. billing code vs subwatch). Test plan is part of the SDP (handbook PR #1223). Task stays open until proposal outlines mechanics of Phase 1 verification. ```

---

### AAP-66646 – Downstream CI/CD Pipeline Adjustments | **Keep open**

**Jira AC (exact):** (1) Create issues for any pipeline automation to validate the given feature. (2) Create issues for any new pipeline job configurations. (3) Notify PDE of these new issues to allow ample time for planning and delivery.

**AC alignment:**

| AC | Alignment | Notes |
|----|-----------|--------|
| (1) Create issues for pipeline automation to validate feature | **N/A (AAP side)** | We do not have AAP downstream pipeline automation for this feature. Open question: do SAS pipelines need updates/assertions for data in staging? Task kept open until SAS side is understood; may hand to SAS team. |
| (2) Create issues for new pipeline job configurations | **N/A (AAP side)** | No new AAP pipeline job configs for this initiative. SAS side TBD. |
| (3) Notify PDE of new issues | **N/A** | No AAP downstream CI/CD issues to create; notifying PDE is not applicable. We use CI/CD for build/deploy, not monitoring. |

**Comment:**

```
Refinement 2026-03-05: Keeping open – pending SAS side.

* AC (1) Pipeline automation to validate feature — N/A for AAP: We do not have AAP downstream pipeline automation for this feature. Open question: Do SAS nightly pipelines need to be updated to include assertions that data is successfully showing up in the staging service? Task stays open until SAS side changes are understood; may be handed to SAS team (they are part of the initiative).
* AC (2) New pipeline job configurations — N/A for AAP: No new AAP pipeline job configs for this initiative.
* AC (3) Notify PDE — N/A: No new AAP issues to create; notifying PDE is not applicable. We use CI/CD for build/deploy, not monitoring. Will add comment when SAS pipeline needs are clear; then close or reassign.
```

---

### AAP-66647 – Build and Release | **Close**

**Jira AC (exact):** (1) Documentation on how to onboard AAP GA build, or build tech preview containers or dev preview containers are reviewed. (2) A tracking epic is created and a comment is left here to highlight the identified build and release needs as well as the tracking epic.

**AC alignment:**

| AC | Alignment | Notes |
|----|-----------|--------|
| (1) Review GA/tech preview/dev preview build documentation | **N/A** | No build or release needs for this initiative; no functionality released in the traditional sense. Review not applicable. |
| (2) Tracking epic + comment with build/release needs and epic | **N/A** | No build/release needs identified; no tracking epic required. This comment satisfies AC (2) by stating that no actions are needed. |

**Comment:**

```
Refinement 2026-03-05: Closing.

* AC (1) Review build/release documentation — N/A: This initiative does not involve functionality that will be released in the traditional sense. No build or release process changes required; review not applicable.
* AC (2) Tracking epic and comment — Satisfied: No build or release needs identified; no tracking epic required. This comment serves as the required comment: no build/release actions needed for this initiative.
```

---

### AAP-66648 – Installer | **Close**

**Jira AC (exact):** (1) Create child issue(s) for any actions needed to support installer changes. (2) Add comment linking to issue(s) created, or comment stating why no installer changes are needed.

**AC alignment:**

| AC | Alignment | Notes |
|----|-----------|--------|
| (1) Create child issue(s) for installer changes | **N/A** | No installer changes needed for this initiative. |
| (2) Add comment linking to issue(s) or stating why no installer changes needed | **Satisfied** | This comment states why no installer changes are needed (below). |

**Comment:**

```
Refinement 2026-03-05: Closing.

* AC (1) Child issue(s) for installer changes — N/A: No installer changes required for this initiative (no new component, new settings, component interaction changes, or additional infra for this connectivity work).
* AC (2) Comment — Satisfied: This comment states why no installer changes are needed: no installer impact for this initiative.
```

---

### AAP-66649 – Engage with Release Engineering team (non-AAP specific) | **Close**

**Jira AC (exact):** (1) If any Release Engineering engagement is needed for non-AAP specific releases, appropriate tracking epic/issues or SPMM issues are created and shared in the closing comment. (2) If no Release Engineering engagement is needed, a closing comment has been added explaining WHY.

**AC alignment:**

| AC | Alignment | Notes |
|----|-----------|--------|
| (1) If engagement needed: tracking epic/issues created and shared in closing comment | **N/A** | No Release Engineering engagement needed. |
| (2) If not needed: closing comment explaining WHY | **Satisfied** | This comment explains why (below). |

**Comment:**

```
Refinement 2026-03-05: Closing.

* AC (1) Tracking epic/issues if engagement needed — N/A: No Release Engineering engagement is needed for this initiative.
* AC (2) Closing comment explaining WHY — Satisfied: No engagement needed because this initiative does not publish content on access.redhat.com/downloads and does not create entitlement for customers other than “all current & future AAP customers.” No RHDH/Portal or other non-AAP release content; not relevant to this initiative.
```

---

### AAP-66650 – Engage with Performance and Scale | **Close**

**Jira description (summary):** Define performance characteristics; document KPIs/SLOs, scale targets, scaling factors, architectural impact, minimum testing; schedule consultation with Perf/Scale.
**AC alignment:**

| Expectation | Alignment | Notes |
|-------------|-----------|--------|
| Performance KPIs/SLOs and observability documented | **N/A** | Not required for the initial pass; focus is stage connectivity testing. |
| Scale targets, consultation with Perf/Scale | **N/A** | Not needed for first pass; may be considered in a later initiative. |

**Comment:**

```
Refinement 2026-03-05: Closing.

* Performance KPIs/SLOs, observability, scale targets — N/A: Not required for the initial pass. Current focus is testing connectivity in the stage environment. No Perf/Scale consultation needed for this refinement exit.
* Perf/Scale engagement — N/A: Performance/scale testing may be considered in a later initiative.
```

---

### AAP-66651 – Complete a Cloud Assessment | **Close**

**Jira description (summary):** Assess whether feature impacts managed offerings (SaaS/Cloud); contact managed offerings team if feature adds services, impacts infra, etc. Reach out via #team-ansible-on-clouds-saas, @aoc-leads.
**AC alignment:**

| Expectation | Alignment | Notes |
|-------------|-----------|--------|
| Assess impact on managed offerings | **Satisfied** | Cloud/managed-offerings team is already part of the overall project; we are already engaging with them. |
| Contact / engagement with cloud team | **Satisfied** | Engagement is in progress as part of the initiative; no separate refinement task needed. |
| If impacts identified: (full AC truncated) | — | Verify full AC in Jira; any follow-up is covered by ongoing engagement. |

**Comment:**

```
Refinement 2026-03-05: Closing.

* Cloud/managed-offerings assessment — Satisfied: Cloud team is already part of the overall project; we are already engaging with them. Assessment is in progress as part of the initiative.
* Contact / engagement — Satisfied: No separate refinement task needed; engagement covered by existing project participation.
```

---

## Jira updates

1. **Epic AAP-66639:** Epic comment above added. **Done.**
2. **Tasks closed:** AAP-66640, AAP-66642, AAP-66643, AAP-66647, AAP-66648, AAP-66649, AAP-66650, AAP-66651. Comment added to each; status set to **Closed**. **Done.**
3. **Tasks kept open:** AAP-66641, AAP-66644, AAP-66645, AAP-66646. Comment added to each; status unchanged. **Done.**
4. **Follow-up:** Story-point and assign SDP work to the current sprint where applicable (per meeting).
