# Audit Report: Google Drive and Meeting Collectors

**Date:** 2026-02-22
**Scope:** `services/stats/gdrive_collector.py`, `services/stats/meeting_collector.py`
**Cross-reference:** `services/stats/collector.py` (_enrich_event), `services/stats/scorer.py`

---

## 1. gdrive_collector.py

### 1.1 File Discovery (`discover_files`)

**Status: ✅ Complete**

- **Lines 195–206:** Correctly filters by MIME types for Docs, Sheets, Slides (`GOOGLE_MIME_TYPES`).
- **Lines 206–208:** Uses `modifiedTime >= quarter_start` and `trashed = false`; optional `quarter_end`.
- **Lines 205–209:** Requests `modifiedByMeTime`, `owners`, `lastModifyingUser`, `webViewLink`, `description`.
- **Lines 214–224:** Paginates with `pageSize=200` and `nextPageToken`.

**Minor:** No explicit handling for `sharedWithMe` files. The Drive API `files.list()` returns files the user can access; `modifiedByMeTime` is used to detect edits. Files shared with the user but never edited will be skipped (lines 266–267), which is intended.

### 1.2 Shared Drive Discovery (`discover_shared_drive_files`)

**Status: ✅ Complete**

- **Lines 509–531:** Uses `corpora="drive"`, `driveId=drive_id`, `includeItemsFromAllDrives=True`, `supportsAllDrives=True`.
- **Lines 519–521:** Same MIME filter and quarter range as personal discovery.
- **Lines 749–756:** `_get_shared_drive_ids()` reads `config.json` → `google.shared_drives[].id`.
- **Config:** `config.json` lines 753–759 define shared drives; structure is correct.

### 1.3 Classification (`FILENAME_CLASSIFICATION_RULES`)

**Status: ✅ Broad coverage**

- **Lines 47–117:** 11 rule groups: presentation, architecture, operational, planning, process, mentorship, status, planning_sheet, customer, research.
- **Lines 119–124:** `MIME_TYPE_DEFAULT_COMPETENCIES` for unmatched files.
- **Lines 127–138:** First-match wins; patterns are case-insensitive substring matches.

**Potential gaps (low priority):**

- No explicit patterns for: "proposal", "spec", "changelog", "release notes", "blog", "article".
- Some of these may still match via "design proposal", "research", "status report", etc.

### 1.4 Event Generation (`generate_events`)

**Status: ✅ Complete**

Events include all fields expected by `_enrich_event`:

| Field | Line | Notes |
|-------|------|-------|
| `id` | 354 | `gdrive:{file_id}:{event_type}` – stable |
| `source` | 364 | `"gdrive"` |
| `type` | 365 | e.g. `gdrive_doc_created`, `gdrive_sheet_contributed` |
| `item_id` | 366 | File ID |
| `title` | 368 | `[Google Doc] {name}` |
| `timestamp` | 365 | `modified_by_me_time` or `modified_time` |
| `gdrive_role` | 367 | `owner` or `contributor` |
| `extra_classification_text` | 369 | From `_build_classification_text` |

**Lines 358–363:** `_enrich_event` uses `title` for Jira key extraction; `item_id` is file ID (not Jira). Jira keys in filenames are picked up via `_extract_jira_key(title)` in the collector.

### 1.5 Peer Data (`collect_shared_drive_peer_contributions`)

**Status: ✅ Correct**

- **Lines 698–764:** `build_user_index_from_revisions` builds per-user attribution from revision history.
- **Lines 627–673:** `generate_peer_events_from_index` produces events in the same shape as `generate_events`.
- **Lines 766–776:** `ensure_shared_drive_index` aggregates across all configured drives.
- **Lines 779–813:** `collect_shared_drive_peer_contributions` uses the index and filters by peer email.

### 1.6 Caching

**Status: ✅ Implemented**

- **Lines 384–416:** `load_cache` / `save_cache` with 24-hour TTL (lines 399–402).
- **Lines 479–521:** Shared drive cache with same TTL (lines 494–497).
- **Lines 523–538:** User index saved separately; TTL checked via shared drive cache load.

**Note:** `load_shared_drive_cache` and `load_shared_drive_user_index` are separate. If the main cache is expired but the index file exists, `ensure_shared_drive_index` will still rebuild (lines 724–733). No inconsistency.

### 1.7 Rate Limiting

**Status: ✅ Implemented**

- **Lines 146–157:** `_rate_limit()` enforces 100ms between requests.
- **Lines 161–178:** `_api_call_with_backoff` retries on 429 with exponential backoff (1s, 2s, 4s).

**Minor (line 177):** After exhausting retries, `return fn()` runs a 4th attempt without `_rate_limit()`. Low risk but could be made consistent.

### 1.8 Error Handling

**Status: ✅ Adequate**

- **Lines 161–178:** Retries on 429.
- **Lines 336–345:** `get_revision_stats` catches exceptions and returns empty stats.
- **Lines 401–416, 491–508:** Cache load failures return `None` and are logged.
- **Lines 756–759:** `_get_shared_drive_ids` catches config read errors.

**Gap:** `discover_files` and `discover_shared_drive_files` do not wrap the main API call in try/except. A non-429 error will propagate. The collector uses a circuit breaker (collector.py), so repeated failures are handled at a higher level.

---

## 2. meeting_collector.py

### 2.1 Calendar Collection (`collect_calendar_meetings`)

**Status: ✅ Complete**

- **Lines 186–221:** Reads `config.json` → `google.qc_calendars`; falls back to `[{"id": "primary", "name": "Personal"}]`.
- **Lines 204–214:** Deduplicates by event ID across calendars (`seen_event_ids`).
- **Config:** `config.json` lines 760–769 define `primary` and Ansible Eng calendar.

### 2.2 Meet API / Calendar–Meet Linking

**Status: ⚠️ Issues**

- **`collect_meet_attendance` (lines 341–434):** Never called. The main flow uses `link_calendar_to_meet` instead.
- **`link_calendar_to_meet` (lines 437–416):** Correctly links Calendar events to Meet records via `space.meeting_code` filter. Uses `conferenceRecords().list(filter=...)` and `participants().list()`.
- **Meet filter (line 365):** Uses `space.meeting_code="{code}"`. Google docs show `space.meeting_code = "abc-mnop-xyz"`; both forms are typically accepted.

**Recommendation:** Remove or document `collect_meet_attendance` as unused, or integrate it if a different use case is intended.

### 2.3 Classification (`MEETING_CLASSIFICATION_RULES`)

**Status: ✅ Broad coverage**

- **Lines 29–117:** 14 rule groups: standup, sprint_planning, sprint_review, retrospective, one_on_one, architecture_review, interview, training, incident_response, all_hands, planning, customer_meeting, cross_team, presentation, code_review.

**Issues:**

1. **Line 53:** Pattern `"/ "` is very broad. Matches any title with `"/ "` (e.g. "Q1 / Q2 Planning"), which can misclassify as `one_on_one`. Consider narrowing (e.g. `"1:1 / "`, `"sync / "`) or removing.
2. **Line 90:** Pattern `"prioriti"` is a truncation for "prioritization"/"priorities". Works but is unclear; consider `"priorit"` or full words.

### 2.4 Event Generation (`generate_meeting_events`)

**Status: ✅ Complete**

| Field | Line | Notes |
|-------|------|------|
| `id` | 389 | `meeting:{event_id}:{event_type}` – stable |
| `source` | 410 | `"meeting"` |
| `type` | 411 | e.g. `meeting_organized_standup`, `meeting_attended_sprint_review` |
| `item_id` | 413 | Calendar event ID |
| `title` | 415 | `[Meeting] {title}` |
| `timestamp` | 416 | `start_time` |
| `meeting_role` | 418 | `assignee` (organizer) or `contributor` |
| `extra_classification_text` | 420 | From `_build_meeting_classification_text` |

Event types align with `scorer.py` (e.g. `meeting_organized_standup`, `meeting_attended_sprint_review`).

### 2.5 Peer Data (`collect_meeting_peer_contributions`)

**Status: ✅ Correct**

- **Lines 451–477:** `build_peer_meeting_index` indexes by `accepted_emails`.
- **Lines 480–522:** `generate_peer_meeting_events` produces events with `meeting_peer_source: True`.
- **Lines 602–662:** `ensure_meeting_peer_index` builds/loads index with 24h TTL.
- **Lines 665–681:** `collect_meeting_peer_contributions` filters by peer email.

**Note:** Peer index uses `user_email` from git config (lines 619–625). For personal calendar, events where the user declined are skipped (line 295). Peers who accepted those meetings are not in the index for those events. This is a design choice: only meetings the user did not decline are considered.

### 2.6 Caching

**Status: ✅ Implemented**

- **Lines 428–446:** `load_cache` / `save_cache` with 24-hour TTL.
- **Lines 448–469:** Saves `meetings`, `events`, `meet_link_data`.
- **Lines 606–622:** Peer index cache with same TTL.

### 2.7 Rate Limiting

**Status: ⚠️ Partial**

- **Lines 155–166:** `_rate_limit()` enforces 100ms between requests.
- **No retry/backoff:** Calendar and Meet API calls are not wrapped in retry logic. A 429 will fail immediately, unlike gdrive_collector.

**Recommendation:** Add `_api_call_with_backoff`-style retries for Calendar and Meet API calls.

### 2.8 Multi-Calendar Deduplication

**Status: ✅ Correct**

- **Lines 204–214:** `seen_event_ids` ensures each event ID appears only once across calendars.
- Recurring instances have distinct IDs, so no incorrect deduplication.

---

## 3. Cross-Cutting Concerns

### 3.1 `_enrich_event` Compatibility

**Status: ✅ Compatible**

`_enrich_event` (collector.py 321–425) expects:

- `item_id`, `title`, `source`, `type` – all present.
- `extra_classification_text` – merged into `classification_text` (lines 361–363).
- `gdrive_role` / `meeting_role` – used to override role (lines 352–356).

Both collectors provide these fields.

### 3.2 Event ID Stability

**Status: ✅ Stable**

- GDrive: `gdrive:{file_id}:{event_type}` (line 354); shared: `gdrive_shared:{file_id}:{email}:{event_type}` (line 668).
- Meeting: `meeting:{event_id}:{event_type}` (line 389); peer: `meeting_peer:{event_id}:{email}:{event_type}` (line 461).

IDs are deterministic for the same inputs.

### 3.3 `classification_text` for Scorer

**Status: ✅ Sufficient**

- **GDrive (lines 424–437):** Combines filename, MIME label, classification, description, and `_CLASSIFICATION_BOOST_TEXT`.
- **Meeting (lines 531–543):** Combines title, classification, boost text, organizer flag, and large-meeting hint.

Scorer uses `classification_text` for phrase/keyword matching and `min_signals` (default 2). The boost text helps reach the threshold.

### 3.4 Timestamp Format

**Status: ✅ Consistent**

- GDrive: ISO 8601 from Drive API (`modifiedTime`, `modifiedByMeTime`, `createdTime`).
- Meeting: ISO 8601 from Calendar API (`start.dateTime` or `start.date`).

Both match what the collector and scorer expect.

### 3.5 `issue_keys` Extraction

**Status: ✅ Handled by collector**

- Collectors do not set `issue_keys`.
- `_enrich_event` derives Jira key via `_extract_jira_key(title)` (collector.py 334–336).
- Titles like `[Meeting] AAP-12345 Sprint Planning` or `[Google Doc] AAP-12345 Design Doc` are correctly parsed.

---

## 4. Summary of Issues

| Severity | Location | Issue |
|----------|----------|-------|
| Medium | meeting_collector.py:341 | `collect_meet_attendance` is dead code; never called |
| Medium | meeting_collector.py | No retry/backoff for Calendar/Meet API 429 errors |
| Low | meeting_collector.py:53 | Pattern `"/ "` too broad; can misclassify as one_on_one |
| Low | meeting_collector.py:90 | Pattern `"prioriti"` unclear; consider `"priorit"` or full words |
| Low | gdrive_collector.py:177 | Final retry in `_api_call_with_backoff` skips rate limit |
| Low | gdrive_collector.py | No try/except around main `discover_files` API call |

---

## 5. Recommendations

1. **Remove or integrate `collect_meet_attendance`** – Either delete it or wire it into the pipeline if needed.
2. **Add API retry logic to meeting_collector** – Mirror gdrive_collector’s `_api_call_with_backoff` for Calendar and Meet calls.
3. **Tighten one_on_one pattern** – Replace `"/ "` with something like `"1:1 / "` or `"sync / "` to reduce false positives.
4. **Optional:** Add try/except around gdrive `discover_files` and `discover_shared_drive_files` for clearer error handling and logging.
