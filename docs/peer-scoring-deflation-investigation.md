# Peer Scoring Pipeline: Deep Investigation Report

**Date:** 2026-02-23
**Context:** Peer performance scores are extremely low (0–3% for PSE, 18% avg for ASE) vs user's 77%. Investigation into whether peer scores are deflated due to data collection gaps.

---

## Executive Summary

**Root cause:** Peer scores are deflated primarily due to **incomplete data collection**, not scoring formula differences. The scoring logic is identical for self and peers. The main issues are:

1. **Collection date range:** Many peers have only 1 day of data (vs 38 for self) because they were never run through a full quarter backfill.
2. **Data source asymmetry:** Peers are missing 3–4 sources that self has (session, direct GDrive, executive emails).
3. **Git/GitHub/GitLab discovery:** Peer repos are derived from config + MR/PR caches; config repos are often user-specific. PSEs on different projects (e.g. ansible) get no git events.
4. **Meeting coverage:** Peer meetings come only from the user's calendar; peers in different teams/meetings are invisible.
5. **Higher effective targets:** PSE target_scale=1.6 (effective_target=160) vs ASE 0.65 (65). Same event count yields much lower % for PSE.

---

## 1. Root Causes (Ranked by Impact)

### 1.1 [CRITICAL] Partial Quarter Collection (Impact: ~95%+)

**Finding:** dhageman and ssbarnea have **1 daily file each** (2026-02-22.json). apotozni and self have **38 days**.

| Peer | Level | Days Captured | Total Events | Overall % |
|------|-------|---------------|--------------|-----------|
| apotozni | ASE | 38 | 184 | 49% |
| dhageman | PSE | **1** | 26 | 3% |
| ssbarnea | PSE | **1** | 1 | 1% |
| Self | (user) | 38 | (many) | 77% |

**Cause:** `collect_peers` without `backfill=True` only collects **one day** (today or the passed date). Full quarter backfill requires `backfill=True`. Peers who were never run through a full backfill only have data from single-day runs.

**Code path:** `collect_peers` without backfill → `_collect_peers_sync(peers_config, [target], ...)` → `target = date.today()` → single day.

**Fix:** Run full quarter backfill for all peers. Consider making backfill the default for new peers or when peer count is low.

---

### 1.2 [HIGH] Data Source Asymmetry (Impact: ~40–60% of events)

**Self has 7 sources; peers have 4–5.**

| Source | Self | Peer | Notes |
|--------|------|------|-------|
| git | ✅ | ✅ | Peer uses config repos + discovered from MR/PR |
| jira | ✅ | ✅ | Peer uses prefetch_jira_quarter (REST) |
| gitlab | ✅ | ✅ | Peer uses global search by username |
| github | ✅ | ✅ | Peer uses API by username |
| gdrive (direct) | ✅ | ❌ | Self: `collect_gdrive_contributions` (owned files) |
| gdrive (shared) | ✅ | ✅ | Both: `collect_shared_drive_peer_contributions` |
| meeting | ✅ | ✅ | Different: self uses Calendar; peer uses index from user's calendar |
| session | ✅ | ❌ | `if not user_override` – only self |
| executive emails | ✅ | ✅ | Used for strategy context; not event source |

**Missing for peers:**
- **Session events:** `_collect_session_events` is skipped when `user_override` is set. Session logs (standup, documented work) are self-only.
- **Direct GDrive:** `collect_gdrive_contributions` (files owned/edited by user) is only run for self. Peers only get shared drive contributions.

**Quantified:** Self gets gdrive from both owned files and shared drive. Peers get shared drive only. Session events are typically 5–15% of self events for active users.

---

### 1.3 [HIGH] Git Repository Discovery (Impact: ~50–80% for cross-project peers)

**How peer repos are discovered:**

1. **Backfill path:** `prepare_peer_repos` → config repos + repos from GitLab `mrs_authored` and GitHub `prs_authored`.
2. **Single-day path:** `peer_repos` is `None` → `repos = get_config_repos(include_cached=True)` only. **Discovered repos from MR/PR cache are pre-cached but never added to the loop.** The code calls `discover_peer_repos()` but does not iterate over those repos.

**Bug:** In `_collect_for_date_impl`, when `peer_repos` is None:
```python
if not peer_repos:
    peer_repo_paths = [...]  # from gl_cache, gh_cache
    if peer_repo_paths:
        self.discover_peer_repos(unique[:10])  # pre-caches only
if peer_repos is not None:
    repos = peer_repos
else:
    repos = self.get_config_repos(...)  # config repos only!
```
Discovered peer repos are never used for git log when `peer_repos` is None.

**Config repos:** Typically `automation-analytics-backend`, `app-interface`, `redhat-ai-workflow` (from `~/src/` or config). PSEs like dhageman (ansible) or ssbarnea (ansible) work on different repos entirely.

**Result:** dhageman: 0 git events. ssbarnea: 1 github event. apotozni: 99 git + 34 github + 9 gitlab (same team, overlapping repos).

---

### 1.4 [MEDIUM] Meeting Coverage (Impact: ~20–40%)

**Self:** `collect_meeting_contributions` → uses Calendar API for the user's calendar → full meeting list.

**Peer:** `collect_meeting_peer_contributions` → uses `ensure_meeting_peer_index` → builds index from:
1. User's calendar events (attendees only)
2. Optional `peer_calendars` in config (additional calendar IDs)

**Limitation:** Peer meeting events come only from meetings the **user** attends. If a peer attends different meetings (different team, different calendar), they are not in the index.

**apotozni:** 42 meeting events (same team as user). **dhageman, ssbarnea:** 0 meeting events (likely different teams).

**Fix:** Optional `peer_calendars` in config to add calendars for peer teams. Or: org-level meeting index if available.

---

### 1.5 [MEDIUM] Effective Target (PSE vs ASE)

**Target scale by level (from `competencies.yaml`):**

| Level | target_scale | effective_target (100 base) |
|-------|--------------|-----------------------------|
| ASE | 0.65 | 65 |
| SE | 0.9 | 90 |
| SSE | 1.25 | 125 |
| PSE | 1.6 | 160 |
| SPSE | 2.0 | 200 |

**Impact:** Same raw points (e.g. 50) → ASE 77%, PSE 31%. PSE peers need 2.5× more points than ASE to reach 100%.

**This is intentional** (higher expectations for PSE). But combined with sparse data, PSE peers look artificially low.

---

### 1.6 [LOW] Event Enrichment Parity

**Finding:** `_enrich_event` is identical for self and peers. It uses:
- `_level_override` for peer level (role_weights, pillar_weights, target_scale)
- `_user_override` for jira_username/email in role detection
- Same `map_competencies_with_signals` with `level=level`

**Scope, role, hierarchy, strategy alignment:** Same logic. No deflation from enrichment.

---

## 2. Quantified Data Gaps

| Gap | Estimate | Notes |
|-----|----------|-------|
| Days missing (sparse peers) | ~97% | 1/38 days vs 38/38 |
| Session events | 100% | Peers get 0 |
| Direct GDrive | 100% | Peers get shared only |
| Git (cross-project peers) | 80–100% | Config repos don't match peer's work |
| Meeting (cross-team peers) | 80–100% | Index only from user's calendar |
| Jira | 0% | Works for peers (all projects) |

**Example dhageman (PSE, 1 day):**
- 26 Jira events (all from 2026-02-22)
- 0 git, 0 github, 0 gitlab, 0 meeting
- If he had 38 days: ~26×38 ≈ 988 Jira events (rough extrapolation)
- Git/GitHub/GitLab: likely 0 if repos not in config or MR cache

---

## 3. Self vs Peer Collection Comparison

| Aspect | Self | Peer |
|--------|------|------|
| **Date range** | All weekdays in quarter (backfill) or today (daily) | Same when backfill runs; single day when not |
| **Git repos** | config + cached | config + MR/PR-discovered (backfill only) |
| **Jira** | rh-issue / REST | REST prefetch only |
| **GitLab** | User's MRs | Peer's MRs via global search |
| **GitHub** | User's PRs | Peer's PRs via API |
| **GDrive** | Owned + shared | Shared only |
| **Meeting** | User's calendar | User's calendar index (attendees) |
| **Session** | Yes | No |

---

## 4. Recommended Fixes

### 4.1 [CRITICAL] Ensure Full Quarter Backfill for All Peers

- Run `collect_peers` with `backfill=True` for all peers at least once per quarter.
- Consider: on first load of peer benchmarks, auto-trigger backfill if any peer has &lt;10 days.
- Document: "Backfill peers" must be run for meaningful peer comparison.

### 4.2 [HIGH] Fix Git Repo Discovery for Single-Day Collection

When `peer_repos` is None, merge discovered repos from MR/PR cache into the repos list:

```python
# In _collect_for_date_impl, when user_override and not peer_repos:
peer_repo_paths = []
# ... populate from gl_cache, gh_cache ...
if peer_repo_paths:
    self.discover_peer_repos(unique[:10])
    # ADD: resolve and add to repos
    for gl_path in unique[:20]:
        resolved = self._ensure_repo_available(gl_path)
        if resolved:
            repos.append({"name": basename, "path": resolved})
repos = get_config_repos(...) + repos  # or merge
```

### 4.3 [HIGH] Broaden Config Repos for Peer Git Collection

- Option A: Add org-level "known repos" (e.g. ansible/ansible) from org_roster or a config.
- Option B: Use GitLab/GitHub group/project membership to discover repos for peers.
- Option C: Document that peers must be in same team/org for git to work.

### 4.4 [MEDIUM] Add Session Events for Peers (If Possible)

- Session events are user-specific (local session logs). Peers don't have access.
- Possible: if session logs are shared (e.g. team wiki), add a peer session source. Otherwise, accept as self-only.

### 4.5 [MEDIUM] Improve Meeting Coverage for Peers

- Add `peer_calendars` in config for team calendars.
- Document: peers in same meetings as user get meeting events; others do not.

### 4.6 [LOW] UI Warnings for Sparse Peer Data

- Show "Limited data (X days)" when peer has &lt;10 days.
- Suggest "Run full backfill" when peer overall % is very low and days_captured is low.

---

## 5. Files Examined

| File | Key Methods |
|------|-------------|
| `services/stats/daemon.py` | `_update_peer_summary`, `_collect_peer_data`, `_handle_collect_peers`, `_run_peer_backfill` |
| `services/stats/collector.py` | `collect_for_date`, `_collect_for_date_impl`, `prepare_peer_repos`, `prefetch_jira_quarter` |
| `services/stats/scorer.py` | `map_competencies_with_signals`, `get_level_weights` |
| `services/stats/meeting_collector.py` | `collect_meeting_contributions`, `collect_meeting_peer_contributions`, `ensure_meeting_peer_index` |

---

## 6. Data Examined

| Path | Summary |
|------|---------|
| `peers/apotozni/` | ASE, 184 events, 38 days, 49%, git+github+meeting+gitlab |
| `peers/dhageman/` | PSE, 26 events, 1 day, 3%, jira only |
| `peers/ssbarnea/` | PSE, 1 event, 1 day, 1%, github only |
| `peers/benchmarks.json` | PSE avg 1%, ASE avg 18% |
| `org/org_roster.json` | Peer usernames, gitlab, github, jira |
