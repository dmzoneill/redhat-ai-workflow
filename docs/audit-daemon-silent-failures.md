# Audit: Silent Failure Patterns in services/stats/daemon.py

**Audit date:** 2026-02-22
**File:** `services/stats/daemon.py`
**Purpose:** Comprehensive list of every place where errors are swallowed, ignored, or result in empty returns without user notification.

---

## Executive Summary

### _handle_collect_daily and _handle_backfill

| Aspect | Finding |
|--------|---------|
| **Failure reporting** | Both return `{"success": False, "error": str(e)}` to the D-Bus caller on exception. Backfill also includes per-day `results[]` with `success`/`error` per date. |
| **D-Bus signals** | **No D-Bus signals are emitted** when collection fails. The daemon does not call `emit_status_changed()` or `emit_event()` on collection failure. Callers must poll or explicitly invoke the method to discover failures. |
| **Health tracking** | **Neither handler calls `record_failed_operation()`** or `record_successful_operation()`. The base class provides these for health tracking, but the stats daemon never uses them. |

### Health Status

| Aspect | Finding |
|--------|---------|
| **health_check()** | Only checks `running` and `config_dir_exists`. **Does NOT verify** that collection is working, that daily files exist, or that the last collection succeeded. Users have no programmatic way to know if collection is broken. |

---

## Structured Findings

### CRITICAL Severity

#### 1. Health check does not verify collection health
- **Lines:** 4897–4915
- **Code:**
```python
async def health_check(self) -> dict:
    """Perform a health check on the stats daemon."""
    self._last_health_check = time.time()

    checks = {
        "running": self.is_running,
        "config_dir_exists": AA_CONFIG_DIR.exists(),
    }

    healthy = all(checks.values())
```
- **What is swallowed:** Any notion that collection has failed recently or that daily data is stale/missing.
- **Severity:** **CRITICAL**
- **Fix:** Add checks for: last successful collection timestamp, presence of recent daily files, or `record_failed_operation` / `record_successful_operation` integration.

---

#### 2. No D-Bus signals on collection failure
- **Lines:** 846–891 (`_handle_collect_daily`), 893–952 (`_handle_backfill`)
- **Code:** Neither handler calls `emit_status_changed()` or `emit_event()` when collection fails.
- **What is swallowed:** Real-time notification to UI/clients that collection failed. Clients must poll or re-invoke methods.
- **Severity:** **CRITICAL**
- **Fix:** Emit `emit_event("collect_daily_failed", json.dumps({"error": str(e)}))` on exception in `_handle_collect_daily`. For backfill, emit on first failure or include failure summary in a signal.

---

### HIGH Severity

#### 3. _load_file returns stale cache on exception
- **Lines:** 4786–4806
- **Code:**
```python
def _load_file(self, filepath: Path) -> dict | None:
    ...
    except Exception as e:
        logger.error(f"Failed to load {filepath}: {e}")
        return self._stats_cache.get(key)
```
- **What is swallowed:** Returns stale cached data (or None) without indicating an error. Callers receive data as if load succeeded.
- **Severity:** **HIGH**
- **Fix:** Return `None` and/or add a separate `_load_file_with_status()` that returns `(data, error)`. Or raise and let callers handle.

---

#### 4. _get_questions_summary returns None on exception
- **Lines:** 360–371
- **Code:**
```python
def _get_questions_summary(...) -> list[dict] | None:
    try:
        ...
        return summary if summary else None
    except Exception as e:
        logger.debug(f"Failed to load questions summary: {e}")
        return None
```
- **What is swallowed:** QuestionManager load/parse errors. Caller gets `None` with no indication of failure (only debug log).
- **Severity:** **HIGH**
- **Fix:** Log at `warning` level; consider returning `{"error": str(e)}` or propagating to caller so UI can show a message.

---

#### 5. _update_summary skips corrupt daily files silently
- **Lines:** 580–614
- **Code:**
```python
for daily_file in sorted(daily_dir.glob("*.json")):
    try:
        with open(daily_file, encoding="utf-8") as f:
            data = json.load(f)
        # ... process ...
    except Exception:
        continue
```
- **What is swallowed:** JSON parse errors, file read errors. Entire day's data is dropped with no user notification.
- **Severity:** **HIGH**
- **Fix:** Log the error with file path; accumulate failed files and include in summary or return value (e.g. `summary["failed_days"] = [...]`).

---

#### 6. _compute_peer_comparable_from_daily skips corrupt files
- **Lines:** 711–732
- **Code:**
```python
for daily_file in sorted(daily_dir.glob("*.json")):
    try:
        ...
    except Exception:
        continue
```
- **What is swallowed:** Same as #5. Peer-comparable aggregation silently drops bad files.
- **Severity:** **HIGH**
- **Fix:** Log with file path; optionally return `(data, failed_files)` so caller can surface.

---

#### 7. _update_summary_from_data loads prev summary with bare pass
- **Lines:** 785–796
- **Code:**
```python
if summary_file.exists():
    try:
        with open(summary_file, encoding="utf-8") as f:
            prev = json.load(f)
        strategy_alignment = prev.get("strategy_alignment", {})
        questions_summary = prev.get("questions_summary", {})
    except Exception:
        pass
```
- **What is swallowed:** Corrupt `summary.json` or I/O errors. Strategy/questions data is lost with no logging.
- **Severity:** **HIGH**
- **Fix:** Log the exception; optionally use empty dicts but record that fallback occurred.

---

#### 8. Hierarchy cache load failures (multiple locations)
- **Lines:** 865–868, 1894–1899, 2784–2790, 3783–3790, 4179–4184
- **Code (representative):**
```python
if cache_file.exists():
    try:
        with open(cache_file, encoding="utf-8") as f:
            hierarchy_cache = json.load(f)
    except Exception:
        pass  # or self._collector.hierarchy_cache = {}
```
- **What is swallowed:** Corrupt `jira_hierarchy_cache.json` or I/O errors. Enrichment uses empty hierarchy.
- **Severity:** **HIGH**
- **Fix:** Log at `warning`; optionally set `hierarchy_cache = {}` explicitly and record `hierarchy_load_failed: True` for diagnostics.

---

#### 9. _load_peers_config returns {} on all failures
- **Lines:** 956–987
- **Code:**
```python
try:
    if org_roster.exists():
        ...
        return peers
except Exception as e:
    logger.warning("Failed to load org_roster.json: %s", e)

for cfg_path in config_paths:
    try:
        ...
    except Exception:
        continue
return {}
```
- **What is swallowed:** First failure is logged; config.json failures are silent. Empty `{}` is indistinguishable from "no peers configured."
- **Severity:** **HIGH**
- **Fix:** Log each config failure; consider returning `{"error": "..."}` or `{"peers": {}, "load_error": "..."}` when all sources fail.

---

#### 10. _update_peer_summary skips corrupt peer daily files
- **Lines:** 1034–1048
- **Code:**
```python
for daily_file in sorted(peer_daily_dir.glob("*.json")):
    try:
        ...
    except Exception:
        continue
```
- **What is swallowed:** Corrupt peer daily files. Peer summary is incomplete.
- **Severity:** **HIGH**
- **Fix:** Log with file path; optionally track and return failed files.

---

#### 11. _handle_get_captured_days returns placeholder on exception
- **Lines:** 3041–3051
- **Code:**
```python
except Exception:
    days.append({
        "date": f.stem,
        "event_count": 0,
        "total_points": 0,
        "sources": [],
        "category_points": {},
    })
```
- **What is swallowed:** File read/parse errors. Day appears as empty instead of "failed to load."
- **Severity:** **HIGH**
- **Fix:** Add `"error": str(e)` or `"load_failed": True` to the day entry; log the error.

---

#### 12. _load_benchmarks_levels returns {} on exception
- **Lines:** 2047–2059
- **Code:**
```python
if bf.exists():
    try:
        with open(bf, encoding="utf-8") as f:
            return json.load(f).get("levels", {})
    except Exception:
        pass
return {}
```
- **What is swallowed:** Corrupt benchmarks.json. Callers get empty levels with no indication of failure.
- **Severity:** **HIGH**
- **Fix:** Log the exception; consider returning `{"error": str(e)}` or a sentinel so callers can distinguish failure from "no benchmarks."

---

### MEDIUM Severity

#### 13. _tag_events_to_questions suppresses tagging errors
- **Lines:** 522–531
- **Code:**
```python
except Exception as exc:
    logger.debug("Suppressed error tagging events: %s", exc)
```
- **What is swallowed:** Tagging errors per daily file. Only debug log.
- **Severity:** **MEDIUM**
- **Fix:** Log at `warning`; optionally accumulate and return failed files.

---

#### 14. Date parsing in backfill (date_start/date_end)
- **Lines:** 1506–1517
- **Code:**
```python
if date_start:
    try:
        ds = date.fromisoformat(date_start)
        all_weekdays = [d for d in all_weekdays if d >= ds]
    except ValueError:
        pass
if date_end:
    try:
        de = date.fromisoformat(date_end)
        ...
    except ValueError:
        pass
```
- **What is swallowed:** Invalid `date_start`/`date_end` strings. Filter is silently not applied.
- **Severity:** **MEDIUM**
- **Fix:** Log and/or add to `_peer_backfill_progress["errors"]`; consider returning validation error to caller.

---

#### 15. Pre-fetch failures in peer backfill
- **Lines:** 1599–1600
- **Code:**
```python
except Exception as e:
    logger.warning("Pre-fetch failed for %s: %s", pf_user, e)
```
- **What is swallowed:** Pre-fetch continues for other peers; failed peer is not recorded in `_peer_backfill_progress["errors"]`.
- **Severity:** **MEDIUM**
- **Fix:** Append to `errors` list so progress API reports it.

---

#### 16. Shared drive index failure
- **Lines:** 1633–1634
- **Code:**
```python
except Exception as e:
    logger.warning("Shared drive index failed (non-blocking): %s", e)
```
- **What is swallowed:** GDrive indexing failure. Backfill continues; no entry in progress errors.
- **Severity:** **MEDIUM**
- **Fix:** Append to `_peer_backfill_progress["errors"]` for visibility.

---

#### 17. Meeting peer index failure
- **Lines:** 1658–1659
- **Code:**
```python
except Exception as e:
    logger.warning("Meeting peer index failed (non-blocking): %s", e)
```
- **What is swallowed:** Meeting index failure. Same as #16.
- **Severity:** **MEDIUM**
- **Fix:** Append to `_peer_backfill_progress["errors"]`.

---

#### 18. _handle_scrub_data / rescore_peers skips corrupt files
- **Lines:** 1919–1924
- **Code:**
```python
for daily_file in sorted(daily_dir.glob("*.json")):
    try:
        with open(daily_file, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        continue
```
- **What is swallowed:** Corrupt peer daily files during rescore. File is skipped silently.
- **Severity:** **MEDIUM**
- **Fix:** Log with path; optionally track failed files in return value.

---

#### 19. _get_user_event_counts skips corrupt files
- **Lines:** 2035–2045
- **Code:**
```python
for f in daily_dir.glob("*.json"):
    try:
        ...
    except Exception:
        continue
```
- **What is swallowed:** Corrupt daily files. Event counts are undercounted.
- **Severity:** **MEDIUM**
- **Fix:** Log; optionally return `(counts, failed_files)`.

---

#### 20. _handle_get_overview_digest skips corrupt daily files
- **Lines:** 2108–2121
- **Code:**
```python
for f in sorted(daily_dir.glob("*.json")):
    try:
        ...
    except Exception:
        continue
```
- **What is swallowed:** Same pattern. Daily trend is incomplete.
- **Severity:** **MEDIUM**
- **Fix:** Log; optionally include failed days in response.

---

#### 21. get_merged_config failure in _handle_ask_ai
- **Lines:** 2362–2367
- **Code:**
```python
scoring_config = None
try:
    scoring_config = get_merged_config()
except Exception:
    pass
```
- **What is swallowed:** Scoring config load failure. AI tutor runs with `None` config.
- **Severity:** **MEDIUM**
- **Fix:** Log; consider returning `{"success": False, "error": "..."}` if config is required.

---

#### 22. get_merged_config failure in _handle_explain_competency_score
- **Lines:** 2402–2407
- **Code:**
```python
scoring_config = None
try:
    scoring_config = get_merged_config()
except Exception:
    pass
```
- **What is swallowed:** Same as #21.
- **Severity:** **MEDIUM**
- **Fix:** Same as #21.

---

#### 23. _handle_explain_competency_score skips corrupt daily files
- **Lines:** 2391–2401
- **Code:**
```python
for f in sorted(daily_dir.glob("*.json")):
    try:
        ...
    except Exception:
        continue
```
- **What is swallowed:** Corrupt daily files. Evidence list is incomplete.
- **Severity:** **MEDIUM**
- **Fix:** Log; optionally track failed files.

---

#### 24. _handle_get_mindmap_clusters skips corrupt files
- **Lines:** 2475–2491
- **Code:**
```python
for f in sorted(daily_dir.glob("*.json")):
    try:
        ...
    except Exception:
        continue
```
- **What is swallowed:** Same pattern.
- **Severity:** **MEDIUM**
- **Fix:** Log; optionally track failed files.

---

#### 25. Fast rethreshold skips corrupt daily files
- **Lines:** 2660–2666
- **Code:**
```python
for daily_file in sorted(daily_dir.glob("*.json")):
    try:
        with open(daily_file, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        continue
```
- **What is swallowed:** Corrupt files during rethreshold. Some days are not re-scored.
- **Severity:** **MEDIUM**
- **Fix:** Log; optionally return failed file list.

---

#### 26. _handle_evaluate_all skips corrupt daily files
- **Lines:** 2805–2812
- **Code:**
```python
for daily_file in sorted(daily_dir.glob("*.json")):
    try:
        ...
    except Exception:
        continue
```
- **What is swallowed:** Same pattern in full evaluate.
- **Severity:** **MEDIUM**
- **Fix:** Log; optionally return failed file list.

---

#### 27. _refresh_issue_hierarchy_from_jira swallows per-issue fetch errors
- **Lines:** 3145–3146
- **Code:**
```python
except Exception as e:
    logger.debug(f"Failed to fetch {key}: {e}")
```
- **What is swallowed:** rh-issue failures per Jira key. Issue metadata is missing; only debug log.
- **Severity:** **MEDIUM**
- **Fix:** Log at `warning`; optionally add to a `failed_keys` list in return.

---

#### 28. Issue hierarchy cache load
- **Lines:** 3429–3436
- **Code:**
```python
if cache_file.exists() and not refresh:
    try:
        with open(cache_file, encoding="utf-8") as fh:
            cached = json.load(fh)
    except Exception:
        pass
```
- **What is swallowed:** Corrupt hierarchy cache. Falls through to empty cached data.
- **Severity:** **MEDIUM**
- **Fix:** Log; proceed with empty cache but record failure.

---

#### 29. _handle_export_report skips corrupt daily files
- **Lines:** 3626–3633
- **Code:**
```python
for f in sorted(daily_dir.glob("*.json")):
    try:
        ...
    except Exception:
        continue
```
- **What is swallowed:** Corrupt files excluded from report. Report is incomplete.
- **Severity:** **MEDIUM**
- **Fix:** Log; optionally add `failed_files` to report metadata.

---

#### 30. _handle_get_issue_hierarchy skips corrupt event processing
- **Lines:** 3382–3388
- **Code:**
```python
except Exception:
    continue
```
- **What is swallowed:** Errors while processing events for issue keys. Some issues may be missing from hierarchy.
- **Severity:** **MEDIUM**
- **Fix:** Log with event/issue context; optionally track failed events.

---

#### 31. PDF export fallbacks (hierarchy, evidence, captured days, strategy)
- **Lines:** 3726–3772
- **Code:**
```python
try:
    hier_result = await self._handle_get_issue_hierarchy(...)
    ...
except Exception as e:
    logger.warning(f"Failed to load hierarchy for PDF: {e}")

try:
    ev_result = await self._handle_get_competency_evidence()
    ...
except Exception as e:
    logger.warning(f"Failed to load competency evidence for PDF: {e}")
# ... similar for captured_days, strategy_data
```
- **What is swallowed:** Failures are logged but PDF is still generated with missing sections. User may not realize data is incomplete.
- **Severity:** **MEDIUM**
- **Fix:** Add a `warnings` or `missing_sections` list to the PDF report response; surface in UI.

---

### LOW Severity

#### 32. Clean migration swallows exception
- **Lines:** 4817–4822
- **Code:**
```python
try:
    with open(SCORING_CONFIG_FILE, encoding="utf-8") as f:
        old_cfg = json.load(f)
except Exception:
    return
```
- **What is swallowed:** Migration aborts silently if config is unreadable.
- **Severity:** **LOW**
- **Fix:** Log at `warning` before returning.

---

#### 33. Backfill executive emails: existing cache load
- **Lines:** 4418–4424
- **Code:**
```python
for p in emails_dir.glob("*.json"):
    try:
        with open(p, encoding="utf-8") as fh:
            existing_gmail_ids.add(json.load(fh).get("gmail_message_id", ""))
    except Exception:
        pass
```
- **What is swallowed:** Corrupt cached email files. That file's gmail id is not in the set; may cause re-fetch.
- **Severity:** **LOW**
- **Fix:** Log at `debug` or `warning` with file path.

---

#### 34. _handle_list_executive_emails skips corrupt files
- **Lines:** 4091–4111
- **Code:**
```python
for f in sorted(...):
    try:
        ...
        emails.append(...)
    except Exception:
        continue
```
- **What is swallowed:** Corrupt email cache files. Email list is incomplete.
- **Severity:** **LOW**
- **Fix:** Log with file path; optionally add `failed_count` to response.

---

#### 35. _handle_infer_strategy_relationships hierarchy cache load
- **Lines:** 4179–4185
- **Code:**
```python
if cache_file.exists():
    try:
        ...
    except Exception:
        pass
```
- **What is swallowed:** Same pattern as #8.
- **Severity:** **LOW** (duplicate of #8)
- **Fix:** Same as #8.

---

## Summary Table

| # | Lines | Pattern | Severity |
|---|-------|---------|----------|
| 1 | 4897–4915 | Health check ignores collection status | CRITICAL |
| 2 | 846–891, 893–952 | No D-Bus signals on collection failure | CRITICAL |
| 3 | 4786–4806 | _load_file returns stale cache on error | HIGH |
| 4 | 360–371 | _get_questions_summary returns None | HIGH |
| 5 | 580–614 | _update_summary skips corrupt daily files | HIGH |
| 6 | 711–732 | _compute_peer_comparable skips corrupt files | HIGH |
| 7 | 785–796 | _update_summary_from_data pass on summary load | HIGH |
| 8 | 865–868, 1894–1899, 2784–2790, 3783–3790, 4179–4184 | Hierarchy cache load pass | HIGH |
| 9 | 956–987 | _load_peers_config returns {} | HIGH |
| 10 | 1034–1048 | _update_peer_summary skips corrupt files | HIGH |
| 11 | 3041–3051 | _handle_get_captured_days placeholder on error | HIGH |
| 12 | 2047–2059 | _load_benchmarks_levels returns {} | HIGH |
| 13–31 | Various | continue/pass in loops, config load, etc. | MEDIUM |
| 32–35 | Various | Migration, cache load, email list | LOW |

---

## Recommended Fix Order

1. **CRITICAL:** Add D-Bus event emission on collect_daily/backfill failure.
2. **CRITICAL:** Extend health_check to include collection health (last success, recent daily files).
3. **HIGH:** Fix _load_file to not return stale cache without indication.
4. **HIGH:** Add logging and optional error reporting for all "except: continue" daily file loops.
5. **HIGH:** Differentiate _load_peers_config empty result from load failure.
6. **MEDIUM:** Add failed-files tracking to summary/aggregation return values.
7. **LOW:** Add logging to migration and cache load fallbacks.
