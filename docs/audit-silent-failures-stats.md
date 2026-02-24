# Silent Failure Audit: services/stats/

**Scope:** scorer.py, strategy.py, email_parser.py
**Date:** 2026-02-22

---

## Summary

| Severity | Count |
|----------|-------|
| Critical | 1 |
| High | 6 |
| Medium | 9 |
| Low | 2 |

---

## Findings

### scorer.py

#### 1. NPU classifier bonus signals – silent pass (map_competencies)
- **Lines:** 896–899
- **Code:**
```python
try:
    npu_bonus = npu_classifier.get_bonus_signals(classification_text)
except Exception:
    pass
```
- **Error swallowed:** Any exception from `npu_classifier.get_bonus_signals()` (e.g. model load failure, inference error, timeout).
- **Severity:** **Critical** – scoring can silently drop NPU-derived signals with no visibility.
- **Fix:** Log at `logger.debug` or `logger.warning` with exception details.

---

#### 2. NPU classifier bonus signals – silent pass (map_competencies_with_signals)
- **Lines:** 1012–1015
- **Code:**
```python
try:
    npu_bonus = npu_classifier.get_bonus_signals(classification_text)
except Exception:
    pass
```
- **Error swallowed:** Same as above.
- **Severity:** **Critical** – same behavior in the signals variant.
- **Fix:** Same as #1; consider shared helper with logging.

---

### strategy.py

#### 3. Executive email JSON load – silent continue (build_strategy_context_index)
- **Lines:** 137–142
- **Code:**
```python
try:
    with open(f, encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    continue
```
- **Error swallowed:** File I/O errors, JSON parse errors, encoding issues.
- **Severity:** **Medium** – one bad file is skipped; no indication which file failed.
- **Fix:** Log at `logger.debug` or `logger.warning` with filename and exception.

---

#### 4. config.json load – silent return []
- **Lines:** 293–298
- **Code:**
```python
try:
    with open(config_file, encoding="utf-8") as fh:
        cfg = json.load(fh)
except Exception:
    return []
```
- **Error swallowed:** File not found, permission denied, invalid JSON.
- **Severity:** **High** – GitLab MR enrichment fails with no MRs and no explanation.
- **Fix:** Log at `logger.warning` with exception; optionally re-raise for caller to handle.

---

#### 5. glab config YAML load – silent pass
- **Lines:** 307–316
- **Code:**
```python
try:
    ...
    with open(glab_config, encoding="utf-8") as fh:
        gc = yaml.safe_load(fh)
    ...
except Exception:
    pass
```
- **Error swallowed:** File I/O, YAML parse errors; token extraction fails silently.
- **Severity:** **Medium** – token may be missing with no indication why.
- **Fix:** Log at `logger.debug` with exception.

---

#### 6. GitLab user API – silent pass
- **Lines:** 323–328
- **Code:**
```python
try:
    ...
    with urllib.request.urlopen(user_req, timeout=10) as resp:
        user_data = json.loads(resp.read())
        username = user_data.get("username", "")
except Exception:
    pass
```
- **Error swallowed:** Network errors, 401/403, timeout, JSON parse errors.
- **Severity:** **High** – username resolution fails; later warning is generic.
- **Fix:** Log at `logger.debug` or `logger.warning` with exception before the `if not username` check.

---

#### 7. Executive email JSON load – silent continue (build_sender_relationships)
- **Lines:** 430–434
- **Code:**
```python
try:
    with open(f, encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    continue
```
- **Error swallowed:** Same as #3.
- **Severity:** **Medium**
- **Fix:** Same as #3.

---

#### 8. Inferred relationships cache load – silent pass
- **Lines:** 513–527
- **Code:**
```python
try:
    with open(cache_file, encoding="utf-8") as fh:
        cached = json.load(fh)
    ...
    except Exception:
        age_hours = 999   # inner: datetime parse
    ...
except Exception:
    pass                 # outer: file/JSON load
```
- **Error swallowed:** Cache file I/O, JSON parse errors; datetime parse (inner) sets `age_hours = 999` without logging.
- **Severity:** **Low** – cache miss leads to recompute; acceptable but opaque.
- **Fix:** Log at `logger.debug` for cache load/parse failures.

---

#### 9. Email file load in infer_relationships – silent continue
- **Lines:** 536–543
- **Code:**
```python
try:
    with open(f, encoding="utf-8") as fh:
        data = json.load(fh)
    ...
except Exception:
    continue
```
- **Error swallowed:** Same as #3.
- **Severity:** **Medium**
- **Fix:** Same as #3.

---

#### 10. Email file load in build_strategy_alignment – silent continue
- **Lines:** 623–627
- **Code:**
```python
try:
    with open(f, encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    continue
```
- **Error swallowed:** Same as #3.
- **Severity:** **Medium**
- **Fix:** Same as #3.

---

#### 11. Jira hierarchy cache load – silent pass
- **Lines:** 707–714
- **Code:**
```python
try:
    with open(cache_file, encoding="utf-8") as fh:
        user_issues = json.load(fh).get("issues", {})
except Exception:
    pass
```
- **Error swallowed:** File I/O, JSON parse errors; hierarchy data lost.
- **Severity:** **High** – strategy alignment loses issue hierarchy with no indication.
- **Fix:** Log at `logger.warning` with exception and filename.

---

### email_parser.py

#### 12. get_executive_senders – silent return []
- **Lines:** 205–207
- **Code:**
```python
try:
    with open(cfg_path, encoding="utf-8") as f:
        config = json.load(f)
    return config.get("performance", {}).get("executive_senders", [])
except Exception:
    return []
```
- **Error swallowed:** File not found, permission denied, invalid JSON.
- **Severity:** **High** – executive email collection is disabled with no explanation.
- **Fix:** Log at `logger.warning` with exception and config path.

---

#### 13. Existing email ID load – silent pass (collect_executive_emails_for_date)
- **Lines:** 265–269
- **Code:**
```python
try:
    with open(p, encoding="utf-8") as fh:
        existing_ids.add(json.load(fh).get("gmail_message_id", ""))
except Exception:
    pass
```
- **Error swallowed:** Corrupt cached email JSON; ID not added to `existing_ids`.
- **Severity:** **Low** – may re-fetch a single email; impact limited.
- **Fix:** Log at `logger.debug` with filename and exception.

---

## Recommended Fix Pattern

For each finding, apply one of:

1. **Log and continue/return:**
   ```python
   except Exception as e:
       logger.warning("Context: %s", e)  # or logger.debug for low-severity
       # continue or return default
   ```

2. **Log with context (file, operation):**
   ```python
   except Exception as e:
       logger.warning("Failed to load %s: %s", path, e)
   ```

3. **For critical paths (e.g. NPU classifier):**
   ```python
   except Exception as e:
       logger.warning("NPU bonus signals failed for %r: %s", classification_text[:50], e)
       npu_bonus = {}
   ```

---

## Checklist for Systematic Fixes

- [ ] scorer.py:896–899 – NPU classifier in map_competencies
- [ ] scorer.py:1012–1015 – NPU classifier in map_competencies_with_signals
- [ ] strategy.py:137–142 – build_strategy_context_index JSON load
- [ ] strategy.py:293–298 – get_quarter_gitlab_mrs config load
- [ ] strategy.py:307–316 – glab config YAML load
- [ ] strategy.py:323–328 – GitLab user API
- [ ] strategy.py:430–434 – build_sender_relationships JSON load
- [ ] strategy.py:513–527 – infer_relationships cache load
- [ ] strategy.py:536–543 – infer_relationships email file load
- [ ] strategy.py:623–627 – build_strategy_alignment email file load
- [ ] strategy.py:707–714 – Jira hierarchy cache load
- [ ] email_parser.py:205–207 – get_executive_senders
- [ ] email_parser.py:265–269 – collect_executive_emails existing ID load
