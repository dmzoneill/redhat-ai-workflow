# Audit: Event Collection and Enrichment Pipeline (GDrive + Meeting)

**File:** `services/stats/collector.py`
**Date:** 2026-02-22
**Scope:** Verify Google Drive and Calendar/Meeting events are properly collected, enriched, and integrated.

---

## Executive Summary

| Area | Status | Notes |
|------|--------|-------|
| Imports | ✅ OK | Both collectors properly imported |
| Collection (self) | ✅ OK | GDrive and Meeting collected for self |
| Collection (peer) | ✅ OK | GDrive and Meeting collected for peer via user_override |
| Circuit breakers | ✅ OK | Separate breakers for gdrive, gdrive_shared, meeting, meeting_peer |
| Deduplication | ✅ OK | seen_ids used for all sources |
| Source filter | ✅ OK | `_src` correctly gates collection; sources=["jira"] skips GDrive/Meeting |
| Scope detection | ⚠️ Partial | GDrive/Meeting get "story" when no Jira key; no doc/meeting-specific scope |
| Role detection | ✅ OK | _detect_role + gdrive_role/meeting_role override |
| classification_text | ✅ OK | Built from title + Jira context; extra_classification_text appended |
| Issue key extraction | ✅ OK | _extract_jira_key runs on title for all sources |
| Event type mapping | ✅ OK | scorer.py has gdrive_* and meeting_* in competencies |
| Docstring | ❌ Outdated | Valid sources list omits gdrive, meeting |
| Error handling | ✅ OK | try/except with circuit breaker; non-blocking |

---

## 1. Imports

**Lines 17–25**

```python
from services.stats.gdrive_collector import (
    collect_gdrive_contributions,
    collect_shared_drive_peer_contributions,
    ensure_shared_drive_index,
)
from services.stats.meeting_collector import (
    collect_meeting_contributions,
    collect_meeting_peer_contributions,
)
```

**Finding:** ✅ Both collectors are imported correctly. All required entry points are present.

---

## 2. `_collect_for_date_impl` Method

### 2.1 GDrive Collection – Self (Lines 2800–2850)

```python
if (not _src or "gdrive" in _src) and not user_override:
    try:
        if _circuit.is_open("gdrive"):
            raise RuntimeError("circuit breaker open")
        ...
        gdrive_events = collect_gdrive_contributions(...)
        for ev in gdrive_events:
            if ev["id"] not in seen_ids:
                seen_ids.add(ev["id"])
                events.append(self._enrich_event(ev))
        ...
        _circuit.record_success("gdrive")
    except Exception as e:
        _circuit.record_failure("gdrive")
        logger.debug(f"GDrive collect failed (non-blocking): {e}")
```

**Findings:**
- ✅ Source filter: `(not _src or "gdrive" in _src)` – skipped when `sources=["jira"]`
- ✅ Circuit breaker: `gdrive` used
- ✅ Deduplication: `ev["id"] not in seen_ids` before adding
- ✅ Error handling: try/except, non-blocking, circuit breaker updated

### 2.2 GDrive Collection – Peer (Lines 2851–2879)

```python
if (not _src or "gdrive" in _src) and user_override:
    try:
        if _circuit.is_open("gdrive_shared"):
            raise RuntimeError("circuit breaker open for gdrive_shared")
        ...
        shared_events = collect_shared_drive_peer_contributions(...)
        for ev in shared_events:
            if ev["id"] not in seen_ids:
                seen_ids.add(ev["id"])
                events.append(self._enrich_event(ev))
        _circuit.record_success("gdrive_shared")
    except Exception as e:
        _circuit.record_failure("gdrive_shared")
        ...
```

**Findings:**
- ✅ Peer collection via `user_override`
- ✅ Source filter applied
- ✅ Separate circuit breaker `gdrive_shared`
- ✅ Deduplication via `seen_ids`

### 2.3 Meeting Collection – Self (Lines 2881–2901)

```python
if (not _src or "meeting" in _src) and not user_override:
    try:
        if _circuit.is_open("meeting"):
            raise RuntimeError("circuit breaker open")
        ...
        meeting_events = collect_meeting_contributions(...)
        for ev in meeting_events:
            if ev["id"] not in seen_ids:
                seen_ids.add(ev["id"])
                events.append(self._enrich_event(ev))
        _circuit.record_success("meeting")
    except Exception as e:
        _circuit.record_failure("meeting")
        ...
```

**Findings:**
- ✅ Source filter, circuit breaker, deduplication, error handling all correct

### 2.4 Meeting Collection – Peer (Lines 2903–2931)

```python
if (not _src or "meeting" in _src) and user_override:
    try:
        if _circuit.is_open("meeting_peer"):
            raise RuntimeError("circuit breaker open for meeting_peer")
        ...
        peer_mtg_events = collect_meeting_peer_contributions(...)
        ...
```

**Findings:**
- ✅ Peer meeting collection with `meeting_peer` circuit breaker
- ✅ Source filter and deduplication applied

### 2.5 Source Filter Logic (Line 2584)

```python
_src = set(sources) if sources else None
```

- `sources=None` → collect all
- `sources=["jira"]` → only jira; GDrive and Meeting skipped
- `sources=["gdrive","meeting"]` → only gdrive and meeting; git/jira/gitlab/github skipped

---

## 3. `_enrich_event` Method (Lines 321–426)

### 3.1 Scope Detection (Lines 329–341)

```python
jira_key = (
    item_id if re.match(r"[A-Z]+-\d+$", item_id) else _extract_jira_key(title)
)
scope = (
    _detect_scope(jira_key, self.hierarchy_cache)
    if jira_key
    else ("commit" if source == "git" else "story")
)
```

**GDrive:** `item_id` is a Drive file ID (e.g. `1abc123xyz`), not a Jira key. `jira_key` comes from `_extract_jira_key(title)` when the filename contains `PROJECT-123`.

**Meeting:** Same pattern; `item_id` is a calendar event ID; `jira_key` from meeting title.

**When no Jira key:**
- GDrive: `scope = "story"` (fallback)
- Meeting: `scope = "story"` (fallback)

**Finding:** ⚠️ No scope like `"doc"` or `"meeting"`. All non-Jira GDrive/Meeting events use `"story"`. This is a design choice; `scope_multipliers` only define `commit`, `story`, `epic`, `anstrat`.

### 3.2 Role Detection (Lines 344–357)

```python
role = _detect_role(...)
if source == "gdrive" and event.get("gdrive_role"):
    gdrive_role = event["gdrive_role"]
    role = "assignee" if gdrive_role == "owner" else "contributor"
if source == "meeting" and event.get("meeting_role"):
    role = event["meeting_role"]
```

**Finding:** ✅ GDrive and Meeting roles are overridden by collector-provided `gdrive_role` / `meeting_role`. `_detect_role` is used as a fallback when those are missing.

### 3.3 classification_text (Lines 358–364)

```python
classification_text = _build_classification_text(
    title, jira_key, self.hierarchy_cache
)
extra = event.get("extra_classification_text", "")
if extra:
    classification_text += " " + extra
```

**Finding:** ✅ `_build_classification_text` uses title and Jira context. GDrive and Meeting collectors set `extra_classification_text` (filename classification, meeting details), which is appended.

### 3.4 Issue Key Extraction (Lines 334–336)

```python
jira_key = (
    item_id if re.match(r"[A-Z]+-\d+$", item_id) else _extract_jira_key(title)
)
```

`_extract_jira_key` (lines 203–213) matches `PROJECT-123` in the title.

**GDrive:** Title format `[Google Doc] filename` – Jira keys in filenames are extracted.
**Meeting:** Title format `[Meeting] meeting title` – Jira keys in titles are extracted.

**Finding:** ✅ Issue keys are extracted from GDrive filenames and meeting titles when present.

---

## 4. `_detect_role` Method (Lines 90–146)

```python
if source == "gdrive":
    if "created" in event_type:
        return "assignee"
    return "contributor"
if source == "meeting":
    if "organized" in event_type:
        return "assignee"
    return "contributor"
```

**Finding:** ✅ Both `gdrive` and `meeting` are handled. These values are overridden in `_enrich_event` when `gdrive_role` or `meeting_role` are present.

---

## 5. Event Type Mapping (scorer.py)

**GDrive event types** (from `gdrive_collector._event_type_for_file`):
- `gdrive_doc_created`, `gdrive_doc_contributed`
- `gdrive_sheet_created`, `gdrive_sheet_contributed`
- `gdrive_slides_created`, `gdrive_slides_contributed`

**Meeting event types** (from `meeting_collector`):
- `meeting_organized_{classification}`, `meeting_attended_{classification}`
- e.g. `meeting_organized_standup`, `meeting_attended_sprint_planning`, etc.

**scorer.py competencies:** GDrive and meeting event types are included in `event_types` for:
- `technical_knowledge` (gdrive_doc_*)
- `creativity_innovation` (gdrive_doc_created)
- `continuous_improvement` (meeting_organized/attended_retrospective, incident_response)
- `planning_execution` (meeting_participated, meeting_organized_*)
- `mentorship` (meeting_organized_training, one_on_one, interview)
- `speaking_publicity` (gdrive_slides_*, meeting_organized_presentation, sprint_review)
- `evidence_record` (meeting_participated, gdrive_*, meeting_*)

**Finding:** ✅ Event type mappings are complete for GDrive and Meeting.

---

## 6. Source Filtering

### 6.1 Partial Backfill Merge (Lines 2948–2957)

```python
if _src and daily_file.exists():
    try:
        with open(daily_file, encoding="utf-8") as f:
            existing = json.load(f)
        kept = [e for e in existing.get("events", []) if e.get("source") not in _src]
        new_ids = {e["id"] for e in events}
        kept = [e for e in kept if e["id"] not in new_ids]
        events = kept + events
    except Exception:
        pass
```

**Logic:** When `sources` is set, keep events whose `source` is not in `_src`, then replace with newly collected events for the requested sources.

**Example:** `sources=["gdrive","meeting"]` → keep git/jira/gitlab/github from existing, replace gdrive/meeting with new collection.

**Finding:** ✅ Partial backfill merge behaves correctly.

### 6.2 Docstring / Documentation (Lines 2552–2556)

```python
sources: optional list of data sources to collect. Valid values:
"git", "jira", "gitlab", "github". When set, only those sources are
re-collected and the results are merged with the existing daily file
(events from other sources are preserved). None means collect all.
```

**Finding:** ❌ Docstring omits `gdrive` and `meeting`. Valid sources should be: `"git", "jira", "gitlab", "github", "gdrive", "meeting"`.

### 6.3 Daemon Docstring (daemon.py Line 1304)

```python
sources   – only re-collect these data sources (git/jira/gitlab/github)
```

**Finding:** ❌ Same omission; should include `gdrive` and `meeting`.

---

## 7. Error Handling

**GDrive self (L2800–2850):**
```python
except Exception as e:
    _circuit.record_failure("gdrive")
    logger.debug(f"GDrive collect failed (non-blocking): {e}")
```

**GDrive peer (L2877–2879):**
```python
except Exception as e:
    _circuit.record_failure("gdrive_shared")
    logger.debug(f"GDrive shared collect failed (non-blocking): {e}")
```

**Meeting self (L2899–2901):**
```python
except Exception as e:
    _circuit.record_failure("meeting")
    logger.debug(f"Meeting collect failed (non-blocking): {e}")
```

**Meeting peer (L2929–2931):**
```python
except Exception as e:
    _circuit.record_failure("meeting_peer")
    logger.debug(f"Meeting peer collect failed (non-blocking): {e}")
```

**Finding:** ✅ All four collectors are wrapped in try/except, update circuit breakers, and use non-blocking logging.

---

## 8. Additional Notes

### Session and Gmail

- **Session events** (L2795–2796): `_collect_session_events` is always run when `not user_override`; no `_src` check. Session is a separate source.
- **Gmail** (L2784–2792): `collect_executive_emails_for_date` runs when `not user_override`; no `_src` check. Gmail is auxiliary (caching).

### GDrive Self Shared Drive

- Lines 2818–2845: `collect_shared_drive_peer_contributions` is called with `peer_email=my_email` for self, to enrich with shared drive events. This is inside the main GDrive block and is also filtered by `_src`.

---

## 9. Recommendations

1. **Docstring:** Update `collect_for_date` docstring (L2552–2553) and daemon `_run_peer_backfill` docstring (L1304) to include `"gdrive"` and `"meeting"` in the valid sources list.
2. **Scope:** Consider whether GDrive/Meeting events without Jira keys should use a different scope (e.g. `"doc"` or `"meeting"`) instead of `"story"` if you want different scoring behavior.
