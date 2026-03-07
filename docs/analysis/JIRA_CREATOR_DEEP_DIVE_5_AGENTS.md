# Jira Creator & Hygiene Deep Dive — 5-Agent Consolidated Report

**Date:** 2026-03-06
**Method:** Five parallel analysis agents; findings synthesized into this single report.
**Scope:** Jira-related memory learnings, aa_jira create flow, failure classification, and hygiene recommendations for the jira-creator and create_jira_issue skill.

---

## Executive Summary

All 11 Jira-related failures in `tool_failures.yaml` are **transient** (401 auth or VPN/network); there are **no ongoing** Jira tool bugs. Effort should focus on **creator flow gaps**, **hygiene defaults** (Acceptance Criteria, Epic link, description formatting), and **code/skill fixes** (transition param, `jira_update_issue` args, `supporting_documentation`, docstrings)—not on treating 401 as an ongoing bug in jira-creator.

---

## 1. Sources and Method

| Source | Content |
|--------|---------|
| **Memory/learned** | `memory/learned/patterns.yaml`, `tool_fixes.yaml`, `tool_failures.yaml`; Jira-related entries classified as transient vs ongoing; implications for jira-creator. |
| **Codebase** | aa_jira create flow, required AAP fields, `create_jira_issue` skill flow; gaps and suggested code/skill changes. |
| **Failure classification** | All 11 Jira-related failures in `tool_failures.yaml` reviewed; 100% transient (401 auth or VPN/network); 0 ongoing. |
| **Hygiene** | Recommendations derived from patterns and AAP requirements: high vs low priority; auth/network treated as possibly transient. |

---

## 2. Transient vs Ongoing — Summary

| Category | Count | Examples | Action |
|----------|--------|----------|--------|
| **Transient** | 11 | 401 Unauthorized, VPN/network unreachable | Retry / user env check; do not over-prioritize as jira-creator bugs. |
| **Ongoing** | 0 | — | No Jira tool bugs classified as ongoing. |

Conclusion: Do **not** treat 401 or VPN issues as ongoing bugs to fix in jira-creator; focus on creator logic, skill wiring, and hygiene.

---

## 3. Memory Learnings That Imply Jira-Creator Changes

- **patterns.yaml / tool_fixes.yaml / tool_failures.yaml:** Jira-related learnings are either transient (auth/network) or about **required AAP fields and workflow** (e.g. AC, Epic link, description).
- **Takeaways for jira-creator:**
  - Encode **required AAP fields** in creator defaults and validation (Acceptance Criteria, Epic link, description formatting).
  - Rely on memory learnings for **field presence and formatting**, not for 401/VPN handling (those are environment/transient).

*(No new findings; synthesized from Report 1.)*

---

## 4. Code/Skill Gaps and Suggested Fixes

| Gap | Location | Suggested fix |
|-----|----------|----------------|
| Transition param wrong | aa_jira / create flow or skill | Correct the transition parameter name/value used when moving the issue to the intended status after create. |
| `jira_update_issue` args + not loaded | aa_jira / persona | Fix `jira_update_issue` argument schema and ensure the tool is loaded in the persona used by create_jira_issue (or the step that updates the issue). |
| `supporting_documentation` not passed | create_jira_issue skill / aa_jira | Pass `supporting_documentation` through the skill inputs into the Jira create/update call so AAP requirement is satisfied. |
| Docstring "missing required AAP fields" | aa_jira (create/validation) | Update docstring and/or validation to list required AAP fields explicitly and align with patterns.yaml/AAP requirements. |

### 4.1 Transition parameter — exact fix

- **File:** `skills/create_jira_issue.yaml` lines 422–429, step `transition_to_progress`
- **Current:** `args.transition: "Start Progress"`
- **Tool:** `jira_transition(issue_key: str, status: str)` in `tool_modules/aa_jira/src/tools_basic.py` line 1100
- **Fix:** Use **`status: "In Progress"`** (not `transition`). AAP uses status name "In Progress".

```yaml
# Before
args:
  issue_key: "{{ create_status.issue_key }}"
  transition: "Start Progress"

# After
args:
  issue_key: "{{ create_status.issue_key }}"
  status: "In Progress"
```

### 4.2 `jira_update_issue` — exact fix

- **File:** `skills/create_jira_issue.yaml` lines 408–417, step `update_issue`
- **Current:** `fields: "labels"`, `values: "{{ inputs.labels }}"`
- **Tool:** `jira_update_issue(issue_key, fields="", summary="", description="", labels="", components="")` in `tool_modules/aa_jira/src/tools_extra.py` 737–765. No `values` param.
- **Fix:** Use **`labels: "{{ inputs.labels }}"`** only; remove `fields` and `values`. Note: `jira_update_issue` is in **tools_extra.py**; if the skill engine only loads tools_basic for jira, this step can fail — either load jira extra or remove the step (create already accepts `labels`).

```yaml
# After
args:
  issue_key: "{{ create_status.issue_key }}"
  labels: "{{ inputs.labels }}"
```

### 4.3 `supporting_documentation`

- **File:** `skills/create_jira_issue.yaml` — add optional input `supporting_documentation`; in step `create_issue` (lines 340–355) add `supporting_documentation: "{{ inputs.supporting_documentation or '' }}"`

### 4.4 Docstring

- **File:** `tool_modules/aa_jira/src/tools_basic.py` ~1073–1078 — Document required AAP fields (Summary, Problem Description, Definition of Done; for Story: User Story, Acceptance Criteria, Supporting Documentation) and that the skill/tool use fallbacks when omitted.

---

## 5. Prioritized Recommendations

### High priority (creator/hygiene/code)

- **Acceptance Criteria (AC):** Ensure jira-creator and create_jira_issue set or prompt for AC so new AAP issues are compliant.
- **Epic link:** Ensure Epic link is set or validated when creating AAP issues.
- **Description formatting:** Apply or enforce description formatting (e.g. from patterns/memory) so issues meet AAP standards.
- **Code/skill fixes:** Implement the four items in Section 4 (transition param, `jira_update_issue` args + loading, `supporting_documentation`, docstring/validation).

### Low priority

- **Fix version:** Set or prompt for fix version where applicable.
- **link_to:** Set or prompt for link_to when relevant; lower impact than AC/Epic/description.

### Explicitly excluded

- **401 / auth / VPN:** Treat as **transient**; do not prioritize as ongoing jira-creator bugs (user env, retry, connectivity).

---

## 6. Next Steps / Suggested Tickets

| # | Action | Owner / area |
|---|--------|----------------|
| 1 | Fix transition param in `create_jira_issue.yaml`: use `status: "In Progress"` instead of `transition: "Start Progress"` | Skills |
| 2 | Fix update_issue step: use `labels: "{{ inputs.labels }}"` and remove `fields`/`values`; resolve tools_extra loading for jira (skill engine or persona) or remove step | Skills / aa_workflow |
| 3 | Add `supporting_documentation` input to create_jira_issue skill and pass it in create_issue step | Skills |
| 4 | Update `jira_create_issue` docstring in tools_basic.py with required AAP fields and fallbacks | aa_jira |
| 5 | Creator hygiene: prompt or default for Acceptance Criteria when issue_type is Story | Skills / agent rules |
| 6 | Creator hygiene: add optional `epic_key` input and post-create `jira_set_epic` step for Stories | Skills |
| 7 | Creator hygiene: description template (e.g. headers) when description is empty or minimal | Skills |
| 8 | (Low) Optional `fix_version` input and/or suggest jira_hygiene after create | Skills |
| 9 | (Low) Recommend `link_to` in skill description / agent rules when user mentions parent/Epic | Docs / agent rules |

---

## 7. Conclusion

Jira-related failures in the learned data are **all transient** (401/VPN). The 5-agent deep dive recommends focusing on **creator behavior and hygiene**: required AAP fields (AC, Epic link, description), correct skill/code wiring (transition, `jira_update_issue`, `supporting_documentation`, docstrings), and high-value hygiene (AC, Epic, description) over fix version/link_to. Auth and network issues should be handled as environment/transient, not as defects in the jira-creator or create_jira_issue skill.
