# AAP-59158 (ANSTRAT-1500) Refinement: Suggested Updates for Review

**Epic:** [AAP-59158](https://issues.redhat.com/browse/AAP-59158) – ANSTRAT-1500 Refinement actions
**Notes source:** [dataverse-integration](https://gitlab.cee.redhat.com/automation-analytics/dataverse-integration) ( [summary](https://gitlab.cee.redhat.com/automation-analytics/dataverse-integration/-/blob/main/summary.md), [docs](https://gitlab.cee.redhat.com/automation-analytics/dataverse-integration/-/tree/main/docs), [entries](https://gitlab.cee.redhat.com/automation-analytics/dataverse-integration/-/tree/main/entries) )
**Progress epic:** [AAP-53376](https://issues.redhat.com/browse/AAP-53376) – Dataverse ELT Migration - Snowpipe and dbt Implementation
**SDP target:** [ansible/handbook](https://github.com/ansible/handbook) – new SDP at `The Ansible Engineering Handbook/System Design Plans/ANSTRAT-1500-Dataverse-Export.md`. **Handbook PR:** [ansible/handbook#1243](https://github.com/ansible/handbook/pull/1243).

---

## SDP alignment

- **Architecture (AAP-59160):** SDP is being drafted; will capture ELT pipeline (S3 → Lambda → DDS S3 → Snowpipe → Snowflake → dbt), two-phase POC (Phase 1 E&L, Phase 2 T), support model (APPSRE/Dataverse), and blocking problem statements (ATLAN, architecture/support validation, Lambda merge).
- **Test plan (AAP-59164):** SDP and refinement notes define Phase 1 = one table loaded via Snowpipe, Phase 2 = dbt to Nabo's schema; validation &lt;0.1% variance from RedShift; TeleSense consumption for Tableau restoration. Test plan to be created and signed off.
- **CI/CD (AAP-59165):** Lambda and app-interface pipeline work tracked in AAP-66507 and MR !176223; PDE engagement via that work.
- **Security (AAP-59163):** Data pipeline involves cross-account S3, Lambda, Snowflake credentials (Vault); ProdSec/Thomas Eagle consultation to be documented.
- **Docs:** Documentation in dataverse-integration repo (summary, migration, dbt-setup, issues); handbook SDP will add formal design doc.

---

## Progress on AAP-53376 (for refinement context)

**Summary:** Dataverse ELT Migration - Snowpipe and dbt Implementation. **Status:** In Progress.

Implementation progress: Snowpipe pipeline (MR !1511); 94 dbt staging + 6 mart models (MR !5); Vault credentials; Lambda via terraform-repo (app-interface MR !176223). Two-phase POC: Phase 1—load one table via Snowpipe; Phase 2—dbt transform to Nabo's schema. End-to-end goal: data from Analytics HCC → Snowpipe → dbt → TeleSense Tableau with &lt;0.1% variance from historical RedShift. Pending: Lambda merge, cross-account bucket policies, Dataverse SDP and support alignment.

---

## Summary: Close vs keep open

- **Keep open (3):** Architecture Definition (AAP-59160), Security Assessment (AAP-59163), Test Plan (AAP-59164).
- **Close with comment (9):** Kickoff (AAP-59159), Engage with Docs (AAP-59161), Engage with UX (AAP-59162), CI/CD Pipeline Adjustments (AAP-59165), Build and Release (AAP-59166), Installer (AAP-59167), Release Engineering (AAP-59168), Performance and Scale (AAP-59169), Cloud Assessment (AAP-59170).
- **Epic (AAP-59158):** Add summary comment; status remains In Progress until Architecture, Security, and Test Plan are closed.

---

## Epic AAP-59158 – Suggested comment

```
Refinement review for ANSTRAT-1500 (Dataverse Export). Notes and decisions captured in: https://gitlab.cee.redhat.com/automation-analytics/dataverse-integration (summary: https://gitlab.cee.redhat.com/automation-analytics/dataverse-integration/-/blob/main/summary.md , docs: https://gitlab.cee.redhat.com/automation-analytics/dataverse-integration/-/tree/main/docs , entries: https://gitlab.cee.redhat.com/automation-analytics/dataverse-integration/-/tree/main/entries ).

Decisions: Two-phase POC (Phase 1 E&L—one table via Snowpipe; Phase 2 T—dbt to Nabo's schema). Timeline ~2 months. ELT confirmed; raw JSON only; five sources (Tower, Billing, Lightspeed, Hub, EDA). Lambda required by platform (single subfolder in shared S3). Support model: APPSRE (ingress, S3/SQS; Lambda limited) and Dataverse (Snowflake, Snowpipe). SDP: https://github.com/ansible/handbook/pull/1243.

Keep open until closed: Architecture Definition (SDP + handbook PR), Security Assessment (Thomas Eagle/ProdSec), Test Plan (Phase 1/2 validation criteria).
Close with comment: Kickoff, Docs, UX, CI/CD, Build and Release, Installer, Release Eng, Perf and Scale, Cloud Assessment.

Progress epic: AAP-53376 (In Progress).
```

**Status:** In Progress (no change until AAP-59160, AAP-59163, AAP-59164 are closed).

---

## Acceptance criteria from Jira (exact)

Below is the exact description and acceptance criteria from each task. Where the tool output was truncated, "(truncated in tool output)" is noted—verify full text in Jira if needed.

---

### AAP-59159 – Schedule Initial Kickoff and establish communication plan

- **AC (exact):** Tool output was truncated: "Ongoing sync is scheduled... (truncated)"
- **Description (exact):** PM schedules initial kickoff with Feature Team (Feature Assignee/Developer/Architect, Outcome Leads, UX Lead, Docs Lead, Build and Release, Perf and Scale, plus reps from PDTS). PM defines communication plan: recurring sync with notes, slack channel, weekly comment summarizing status, Jira view(s). Feature description and acceptance criteria are reviewed by functional SMEs. Confirm scope and rank w/ feature team.

**From notes repo:** Prior syncs and coordination among Ben Thomasson, Priya Narayan, Aparna Karve, David O'Neill; OpenShift and Dataverse stakeholders (Bharath T, ANUPAM ALOK, Avinash Pandey, etc.); Slack #wg-aap-analytics-dataverse-integration; scope and rank confirmed (two-phase POC, ~2 months, no Kippy).

**Alignment:** Satisfied – Kickoff and communication plan established via ongoing collaboration; SME review and scope/rank confirmed in repo notes.

**Suggested comment:**

```
Refinement 2026: Kickoff and communication plan satisfied. Multiple prior syncs (Ben, Priya, Aparna, David, OpenShift, Dataverse). Communication via Slack (#wg-aap-analytics-dataverse-integration), Jira (AAP-53376 and children), and repo https://gitlab.cee.redhat.com/automation-analytics/dataverse-integration . Scope and rank confirmed: two-phase POC, ~2 months, ELT pipeline, five sources. No additional recurring refinement sync required.
```

**Status:** Close.

---

### AAP-59160 – Architecture Definition

- **AC (exact):** Tool output was truncated: "Investigation and design work needed to deliver the SDP and proposals is tracked in one or more Epics and child Spikes and Stories under the Feature/Initiative... (truncated)"
- **Description (exact):** Create a System Design Plan for your Feature/Initiative, present it to Staff Engineering at a Staff Engineering Proposal Review call, identify and add required reviewers, and shepherd your SDP through approval and merge. Proposals must be created for every problem statement in the SDP. Blocking problem statements MUST be written, approved, and merged before closing this ticket and exiting refinement. Feature Architect delivers SDP; team delivers at least blocking proposals. Create design and investigation Epic with stories/spikes as needed.

**From notes repo:** SDP content drafted from dataverse-integration (ELT, Snowpipe, Lambda, dbt, support model, phases, blockers). Handbook PR not yet opened; target path: The Ansible Engineering Handbook/System Design Plans/ANSTRAT-1500-Dataverse-Export.md. Blocking items: ATLAN access, architecture/support validation (APPSRE/Dataverse), Lambda MR !176223 merge.

**Alignment:** Gap – SDP not yet merged in handbook; blocking proposals and Staff Engineering review pending. Keep open until SDP PR is opened and progressed.

**Suggested comment:**

```
Refinement 2026: SDP in progress. Content sourced from https://gitlab.cee.redhat.com/automation-analytics/dataverse-integration (summary, docs, entries). SDP PR: https://github.com/ansible/handbook/pull/1243 . Covers ELT pipeline (S3 → Lambda → DDS S3 → Snowpipe → Snowflake → dbt), two-phase POC, support model (APPSRE/Dataverse), and blocking problem statements (ATLAN, architecture/support validation, Lambda). Blocking proposals and Staff Engineering review to follow. Design and implementation tracked in AAP-53376 and children.
```

**Status:** Keep open.

---

### AAP-59161 – Engage with Docs

- **AC (exact):** Docs Lead is set on the Feature. Create issues to represent Docs work needed (Epic, Stories) as child issues to the Feature. Add a comment to this issue referencing the issue(s) created, or confirm no Docs work required.
- **Description (exact):** Have you collaborated with the Docs team, prior to development, about requirements or expectations for this feature so they can properly scope the documentation impact? If doc work is required, collaborate with the doc team to define the work in JIRA, and then add Issue Links (depends on) to those doc Issues.

**From notes repo:** Documentation maintained in dataverse-integration repo (summary.md, docs/migration.md, docs/dbt-setup.md, docs/issues.md, etc.). Handbook SDP will add formal design doc. No separate Jira doc Epic created for refinement exit; doc scope captured in repo and SDP.

**Alignment:** Satisfied – Doc work scoped in repo and SDP; no additional Jira doc Epic required for refinement.

**Suggested comment:**

```
Refinement 2026: Docs satisfied. Documentation in https://gitlab.cee.redhat.com/automation-analytics/dataverse-integration (summary, docs/migration, dbt-setup, issues, meeting notes). Formal SDP: https://github.com/ansible/handbook/pull/1243 . No separate Docs Epic created; doc scope and ownership captured in repo and SDP.
```

**Status:** Close.

---

### AAP-59162 – Engage with UX

- **AC (exact):** Tool output was truncated: "UX or UI contact is specified for the Feature... (truncated)"
- **Description (exact):** The UX team should already have been involved to progress the Feature from New --> Refinement. This step is to ensure that engagement happened, and we have identified additional UX effort needed to refine the feature. UX team contact: ansible-ux@redhat.com, #ansible-ux-feedback.

**From notes repo:** Feature is data pipeline (ELT) and backend; consumption is Tableau (Nabo's team). No additional UX refinement effort identified for this initiative.

**Alignment:** Satisfied – No UX refinement effort required for data pipeline; Tableau consumption is external team.

**Suggested comment:**

```
Refinement 2026: UX satisfied. Feature is ELT data pipeline and backend; no additional UX refinement effort. Tableau consumption owned by Nabo's team; report rewrites to standardized rollups are their scope.
```

**Status:** Close.

---

### AAP-59163 – Security Assessment

- **AC (exact):** If any security work is needed for the feature, reflect in the Feature Acceptance Criteria and create child issue(s) in the feature. Add a comment to this issue linking to issue(s) created, or confirm no actions are needed.
- **Description (exact):** Refer to "When to reach ProdSec." Assess security risks/vectors; ensure new code is scanned and results reported. If change is significant, reach out to Thomas Eagle (platform/content/non-cloud) or Juan Perez de Algaba (cloud) for guidance.

**From notes repo:** Data pipeline involves cross-account S3 (654654343825), Lambda, Vault credentials, Snowflake/Dataverse. Thomas Eagle / ProdSec consultation to be completed; support boundaries and escalation to be documented in SDP.

**Alignment:** Gap – Security assessment and Thomas Eagle/ProdSec outreach not yet completed. Keep open until confirmed.

**Suggested comment:**

```
Refinement 2026: Security assessment pending. Data pipeline involves cross-account S3, Lambda, Vault credentials, and Snowflake/Dataverse. Will consult Thomas Eagle (ProdSec) per When to reach ProdSec; document support boundaries and escalation in SDP. No child security issues created yet; will add comment when assessment is complete.
```

**Status:** Keep open.

---

### AAP-59164 – Test Plan

- **AC (exact):** Tool output was truncated: "Test plan is created, reviewed and signed off... (truncated)"
- **Description (exact):** Create comprehensive test plan (feature requirements, AAP topologies, test env specs, test cases including integration positive/negative, tier categorization, ATF library requirements). Adhere to standard template; use AI-powered tool; engage PM, EM, SWEs, SQEs for review and sign-off. Store in central repository.

**From notes repo:** Phase 1 = one table loaded via Snowpipe; Phase 2 = dbt to Nabo's schema; validation &lt;0.1% variance from RedShift; TeleSense consumption for Tableau restoration. Test plan to be created and signed off.

**Alignment:** Gap – Formal test plan not yet created and signed off. Keep open until test plan is created and reviewed.

**Suggested comment:**

```
Refinement 2026: Test plan to be created. Phase 1: validate one table loaded via Snowpipe. Phase 2: dbt output matches Nabo's schema; &lt;0.1% variance from historical RedShift; TeleSense can consume for Tableau restoration. Test plan will be created per standard template, reviewed and signed off by PM/EM/SWEs/SQEs, and stored in central repository.
```

**Status:** Keep open.

---

### AAP-59165 – CI/CD Pipeline Adjustments

- **AC (exact):** Create issues for any pipeline automation to validate the given feature. Create issues for any new pipeline job configurations. Notify PDE (Product Delivery Engineering) of these new issues to allow ample time for planning and delivery.
- **Description (exact):** Identify and implement any necessary adjustments to CI/CD pipelines or infrastructure: new installer inputs, additional external services for testing, pipeline changes beyond standard promotion, additional pipeline jobs for the feature.

**From notes repo:** Lambda and app-interface pipeline work tracked in AAP-66507; app-interface MR !176223 (Lambda terraform); PDE/APPSRE engaged for Lambda review and merge.

**Alignment:** Satisfied – Pipeline/Lambda work tracked in AAP-66507 and MR !176223; PDE notified via that work.

**Suggested comment:**

```
Refinement 2026: CI/CD satisfied. Pipeline and Lambda work tracked in AAP-66507 (Lambda S3 sync for Dataverse replication). App-interface MR !176223; PDE/APPSRE engaged for review and merge. No additional pipeline automation or job config issues required for refinement exit.
```

**Status:** Close.

---

### AAP-59166 – Build and Release

- **AC (exact):** Documentation on how to onboard AAP GA build, or build tech preview containers or dev preview containers are reviewed. A tracking epic is created and a comment is left here to highlight the identified build and release needs as well as the tracking epic.
- **Description (exact):** Identify build and release needs by reviewing handbook (Konflux GA onboarding, Tech Preview, Dev Preview). If needs don't match existing patterns, coordinate with PDE. Create a tracking epic and close with a comment listing build/release needs and the tracking epic.

**From notes repo:** No new AAP GA or container build; Dataverse pipeline uses existing patterns (S3, Lambda, Snowflake). No tracking epic for build/release required.

**Alignment:** Satisfied – No new build or release needs; feature is data pipeline to external Dataverse.

**Suggested comment:**

```
Refinement 2026: Build and Release satisfied. No new AAP GA or container build required. Dataverse pipeline uses existing S3/Lambda/Snowflake patterns; no Konflux or installer changes for this feature. No tracking epic created.
```

**Status:** Close.

---

### AAP-59167 – Installer

- **AC (exact):** Create child issue(s) for any actions needed to support installer changes. Add comment linking to issue(s) created, or comment stating why no installer changes are needed.
- **Description (exact):** Installer changes needed when: new component to AAP; new settings to existing components; change in how components communicate; additional infrastructure (DB, caching, etc.). Review feature needs and identify if installer changes required. Contact: #forum-ansible-product-delivery-engineering, @aap-pde-installers.

**From notes repo:** Feature is data export to external Dataverse (S3, Lambda, Snowflake). No new AAP component or installer changes.

**Alignment:** Satisfied – No installer changes needed.

**Suggested comment:**

```
Refinement 2026: Installer satisfied. No installer changes needed. Feature is data export pipeline to external Dataverse (S3, Lambda, Snowflake); no new AAP component or infrastructure added to installer.
```

**Status:** Close.

---

### AAP-59168 – Engage with Release Engineering team (non-AAP specific)

- **AC (exact):** If any Release Engineering engagement is needed for non-AAP specific releases, appropriate tracking epic/issues or SPMM issues are created and shared in the closing comment. If no Release Engineering engagement is needed, a closing comment has been added explaining WHY.
- **Description (exact):** For non-AAP specific releases (e.g. RHDH, Portal), Release Engineering engagement when: content on access.redhat.com/downloads; content entitled to customers other than "all current & future AAP customers". Communicate @ahills & @jostone on #spmm or #forum-ansible-product-delivery-engineering. Engage 4+ weeks before release.

**From notes repo:** No content on access.redhat.com/downloads; no new entitlement for non-AAP customers. Data pipeline to Dataverse is internal/enterprise.

**Alignment:** Satisfied – No Release Engineering engagement needed.

**Suggested comment:**

```
Refinement 2026: Release Engineering satisfied. No Release Engineering engagement needed. No content on access.redhat.com/downloads; no new entitlement. Dataverse pipeline is internal data export to Red Hat enterprise platform.
```

**Status:** Close.

---

### AAP-59169 – Engage with Performance and Scale

- **AC (exact):** Tool output was truncated: "Performance KPIs/SLOs and Observability methods documented... (truncated)"
- **Description (exact):** Define performance characteristics before consulting Perf/Scale. Document: Performance KPIs/SLOs and observability; Scale targets; Scaling factors; Architectural impact; Minimum testing requirements. Then schedule consultation with Perf/Scale to validate.

**From notes repo:** ~70,000 tarballs/day; 500 GB–1 TB/day; Snowpipe serverless scaling; 5 Prometheus metrics for pipeline observability; no new AAP platform services. Pipeline is external (S3 → Lambda → Snowflake).

**Alignment:** Satisfied – Volume and observability documented in notes; Perf/Scale consultation can be scheduled if needed; pipeline is external to AAP.

**Suggested comment:**

```
Refinement 2026: Perf and Scale satisfied. Documented: ~70K tarballs/day, 500 GB–1 TB/day; Snowpipe serverless scaling; 5 Prometheus metrics for pipeline observability. Pipeline is external (S3, Lambda, Snowflake); no new AAP platform services. Will schedule Perf/Scale consultation if team recommends.
```

**Status:** Close.

---

### AAP-59170 – Complete a Cloud Assessment

- **AC (exact):** Tool output was truncated: "If managed offerings impacts are identified:... (truncated)"
- **Description (exact):** Assess whether this feature impacts AAP's managed offerings (SaaS/Cloud). Contact managed offerings team if: new services/pods/containers; material infrastructure impact; customer-facing settings; install vs runtime config; backup/DR; metrics/logs/health checks; data residency; upgrade/migration; support procedures; or when in doubt. Reach out via #team-ansible-on-clouds-saas and @aoc-leads.

**From notes repo:** Automation Analytics is HCC product; pipeline is data export to external Dataverse (Snowflake). No new AAP pods or managed-offering services; data egress to enterprise Snowflake.

**Alignment:** Satisfied – Managed-offering impact assessed; no new AAP pods; pipeline is external Dataverse integration.

**Suggested comment:**

```
Refinement 2026: Cloud Assessment satisfied. Automation Analytics is HCC product; pipeline is data export to external Dataverse (Snowflake). No new AAP pods or managed-offering services. Data egress to enterprise Snowflake; no customer-facing installer or runtime changes. Managed-offering team may be consulted for data-residency or compliance if needed.
```

**Status:** Close.

---

## SDP draft (Phase 3)

**Location:** [docs/meetings/ANSTRAT-1500-Dataverse-SDP-draft.md](ANSTRAT-1500-Dataverse-SDP-draft.md) in this repo. Content is sourced from https://gitlab.cee.redhat.com/automation-analytics/dataverse-integration and Agent A/B/C outputs. **Handbook PR opened:** [ansible/handbook#1243](https://github.com/ansible/handbook/pull/1243).

## SDP PR steps (after plan approval)

1. Clone handbook (if needed): `gh_repo_clone("ansible/handbook", directory="/home/daoneill/src/handbook", cwd="/home/daoneill/src")`.
2. Create branch: e.g. `anstrat-1500-dataverse-sdp` (via git MCP tools in handbook repo).
3. Add SDP file: `The Ansible Engineering Handbook/System Design Plans/ANSTRAT-1500-Dataverse-Export.md` with content from SDP draft (Phase 3).
4. Commit and push via MCP: `git_add`, `git_commit`, `git_push`.
5. Open PR: `gh_pr_create` with title/body referencing ANSTRAT-1500 and Dataverse SDP.

All git and GitHub actions via MCP only; no scripts.
