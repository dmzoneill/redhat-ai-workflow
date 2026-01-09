# Memory & Auto-Remediation: Improvement Roadmap

> Identified gaps, potential enhancements, and recommended improvements

## 🔴 Critical Issues (Fix Now)

### 1. Race Conditions in Memory Writes

**Problem:**
```python
# scripts/common/memory.py:88-119
def append_to_list(key, list_path, item, match_key=None):
    data = read_memory(key)  # ← Read
    # ... modify data ...
    data[list_path].append(item)
    return write_memory(key, data)  # ← Write
```

**Issue:** Two concurrent skill executions could lose updates.

**Example Scenario:**
```
Time  Skill A                    Skill B                    File State
0     read current_work          -                          {issues: [AAP-1]}
1     -                          read current_work          {issues: [AAP-1]}
2     add AAP-2                  -                          {issues: [AAP-1]}
3     write {issues: [AAP-1, AAP-2]}  -                    {issues: [AAP-1, AAP-2]}
4     -                          add AAP-3                  {issues: [AAP-1, AAP-2]}
5     -                          write {issues: [AAP-1, AAP-3]}  {issues: [AAP-1, AAP-3]}
                                                            ^^^ AAP-2 LOST!
```

**Solution:**
```python
import fcntl
from pathlib import Path

def atomic_append_to_list(key, list_path, item, match_key=None):
    """Thread-safe append with file locking."""
    path = get_memory_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Acquire exclusive lock
    with open(path, 'r+' if path.exists() else 'w+') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)

        try:
            data = yaml.safe_load(f) or {}

            if list_path not in data:
                data[list_path] = []

            # Check for duplicate
            if match_key and item.get(match_key):
                for i, existing in enumerate(data[list_path]):
                    if existing.get(match_key) == item.get(match_key):
                        data[list_path][i] = item
                        f.seek(0)
                        f.truncate()
                        yaml.dump(data, f, default_flow_style=False)
                        return True

            data[list_path].append(item)
            data["last_updated"] = datetime.now().isoformat()

            f.seek(0)
            f.truncate()
            yaml.dump(data, f, default_flow_style=False)
            return True

        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
```

**Impact:** Prevents data loss in concurrent skill executions.

---

### ✅ 2. Missing Memory Backup Strategy - IMPLEMENTED

**Status:** ✅ Completed (2026-01-09)

**Implementation:** Added `backup_before_init` step to `skills/memory_init.yaml`.

**What was added:**
- Timestamped backup creation (YYYYMMDD_HHMMSS format)
- Backs up 8 critical memory files:
  - state/current_work.yaml
  - state/environments.yaml
  - learned/patterns.yaml
  - learned/tool_fixes.yaml
  - learned/tool_failures.yaml
  - learned/runbooks.yaml
  - learned/service_quirks.yaml
  - learned/teammate_preferences.yaml
- Keeps last 10 backups automatically (deletes older ones)
- Shows backup location and file count in output
- Backup happens BEFORE any files are wiped (critical!)

**Location:** `memory/backups/YYYYMMDD_HHMMSS/`

**Impact:** Prevents data loss from accidental memory_init. User can restore from `memory/backups/` if needed.

**Note:** Pre-commit hook for automatic backups not implemented yet (P2 priority).

---

### 3. tool_failures.yaml Growing Unbounded

**Problem:** Rolling window keeps "last 100", but stats grow forever.

**Current State:**
```yaml
failures: [...]  # ← Capped at 100
stats:
  total_failures: 127    # ← Grows forever
  auto_fixed: 98         # ← Grows forever
  manual_required: 29    # ← Grows forever
```

**After 1 year:**
```yaml
stats:
  total_failures: 36,500  # ~100/day
  auto_fixed: 28,105
  manual_required: 8,395
```

**Solution:**

```python
# server/auto_heal_decorator.py:260-270
# Add daily/weekly stats breakdown

data["stats"] = {
    "total_failures": data["stats"].get("total_failures", 0) + 1,
    "auto_fixed": data["stats"].get("auto_fixed", 0) + 1,

    # Add time-based stats
    "today": {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "total": data["stats"].get("today", {}).get("total", 0) + 1,
        "auto_fixed": data["stats"].get("today", {}).get("auto_fixed", 0) + 1,
    },
    "this_week": {
        "week": datetime.now().strftime("%Y-W%U"),
        "total": ...,
        "auto_fixed": ...,
    },
    # Archive old daily/weekly stats
}
```

---

## 🟡 High Priority (Plan for Next Sprint)

### 4. Memory Query Interface

**Problem:** No easy way to query memory without reading entire files.

**Current:**
```python
# Must read entire file
data = memory_read("state/current_work")
active = data.get("active_issues", [])
my_issue = next((i for i in active if i["key"] == "AAP-123"), None)
```

**Proposed:**
```python
# New query interface
memory_query("state/current_work", "active_issues[key=AAP-123]")

# Or SQL-like
memory_query("state/current_work",
    "SELECT * FROM active_issues WHERE key = 'AAP-123'")

# Or JSONPath
memory_query("state/current_work",
    "$.active_issues[?(@.key=='AAP-123')]")
```

**Implementation:**

```python
# tool_modules/aa_workflow/src/memory_tools.py

@registry.tool()
async def memory_query(key: str, query: str) -> list[TextContent]:
    """
    Query memory using JSONPath expressions.

    Args:
        key: Memory file (e.g., "state/current_work")
        query: JSONPath query (e.g., "$.active_issues[?(@.status=='In Progress')]")

    Returns:
        Matching data
    """
    from jsonpath_ng import parse

    memory_file = MEMORY_DIR / f"{key}.yaml"
    if not memory_file.exists():
        return [TextContent(type="text", text="Memory file not found")]

    with open(memory_file) as f:
        data = yaml.safe_load(f) or {}

    expr = parse(query)
    matches = [match.value for match in expr.find(data)]

    return [TextContent(type="text", text=yaml.dump(matches))]
```

---

### 5. Memory Analytics Dashboard

**Problem:** No visibility into memory health/usage.

**Proposed Tool:**

```python
@registry.tool()
async def memory_stats() -> list[TextContent]:
    """
    Get memory system statistics.

    Returns:
        - File sizes and growth trends
        - Most-read/written files
        - Auto-heal success rates
        - Pattern match frequency
        - Memory fragmentation analysis
    """
    stats = {
        "files": {},
        "auto_heal": {},
        "patterns": {},
        "sessions": {},
    }

    # File sizes
    for file in MEMORY_DIR.rglob("*.yaml"):
        relative = file.relative_to(MEMORY_DIR)
        stats["files"][str(relative)] = {
            "size_kb": file.stat().st_size / 1024,
            "modified": datetime.fromtimestamp(file.stat().st_mtime).isoformat(),
        }

    # Auto-heal stats
    failures = read_memory("learned/tool_failures")
    stats["auto_heal"] = {
        "total": failures.get("stats", {}).get("total_failures", 0),
        "auto_fixed": failures.get("stats", {}).get("auto_fixed", 0),
        "success_rate": ...,
        "recent_failures": failures.get("failures", [])[-10:],
    }

    # Pattern usage
    patterns = read_memory("learned/patterns")
    stats["patterns"] = {
        "total": sum(len(patterns.get(cat, [])) for cat in [
            "auth_patterns", "error_patterns", "bonfire_patterns",
            "pipeline_patterns", "jira_cli_patterns"
        ]),
        "by_category": {...},
    }

    # Session activity
    today = datetime.now().strftime("%Y-%m-%d")
    session = read_memory(f"sessions/{today}")
    stats["sessions"] = {
        "today_actions": len(session.get("actions", [])),
        "total_session_files": len(list((MEMORY_DIR / "sessions").glob("*.yaml"))),
    }

    return [TextContent(type="text", text=yaml.dump(stats))]
```

**Skill:**
```yaml
# skills/memory_health.yaml
name: memory_health
description: Check memory system health

steps:
  - name: get_stats
    tool: memory_stats
    output: stats

  - name: check_large_files
    compute: |
      large = [f for f, info in stats["files"].items()
               if info["size_kb"] > 50]
      if large:
        result = f"⚠️ Large files: {large}"
      else:
        result = "✅ All files normal size"
    output: size_check

  - name: check_success_rate
    compute: |
      rate = stats["auto_heal"]["success_rate"]
      if rate < 0.7:
        result = f"⚠️ Success rate low: {rate:.0%}"
      else:
        result = f"✅ Success rate: {rate:.0%}"
    output: rate_check
```

---

### 6. Pattern Effectiveness Tracking

**Problem:** No way to know which patterns are useful.

**Current State:**
```yaml
# learned/patterns.yaml
auth_patterns:
  - pattern: "token expired"
    fix: "Refresh credentials"
    commands: ["kube_login(cluster='e')"]
    # ← No usage tracking!
```

**Proposed:**
```yaml
auth_patterns:
  - pattern: "token expired"
    fix: "Refresh credentials"
    commands: ["kube_login(cluster='e')"]
    # NEW:
    usage_stats:
      times_matched: 47
      times_fixed: 45
      success_rate: 0.96
      last_matched: "2026-01-09T14:23:15"
      avg_fix_time_ms: 1250
```

**Implementation:**

```python
# tool_modules/aa_workflow/src/skill_engine.py

def _check_error_patterns(self, error: str) -> str | None:
    patterns_file = SKILLS_DIR.parent / "memory" / "learned" / "patterns.yaml"

    # ... existing matching logic ...

    for pattern in error_patterns:
        if pattern["pattern"].lower() in error_lower:
            # NEW: Track usage
            if "usage_stats" not in pattern:
                pattern["usage_stats"] = {
                    "times_matched": 0,
                    "times_fixed": 0,
                    "success_rate": 0.0,
                }

            pattern["usage_stats"]["times_matched"] += 1
            pattern["usage_stats"]["last_matched"] = datetime.now().isoformat()

            # Write back (async to not block)
            asyncio.create_task(self._update_pattern_stats(patterns_file, pattern))

            return pattern.get("fix", "")
```

---

## 🟢 Medium Priority (Nice to Have)

### 7. Memory Compression/Archival

**Problem:** Session logs accumulate forever.

**Current:**
```
memory/sessions/
  2026-01-09.yaml  (3 KB)
  2026-01-08.yaml  (3 KB)
  2026-01-07.yaml  (3 KB)
  ...
  2025-06-15.yaml  (3 KB)  ← 200 days old, rarely accessed
```

**Proposed:**

```python
# skills/memory_cleanup.yaml - Add archival step

- name: archive_old_sessions
  compute: |
    from datetime import datetime, timedelta
    import gzip

    sessions_dir = Path.home() / "src/.../memory/sessions"
    archive_dir = sessions_dir / "archive"
    archive_dir.mkdir(exist_ok=True)

    cutoff = datetime.now() - timedelta(days=90)

    archived = 0
    for session_file in sessions_dir.glob("*.yaml"):
        date_str = session_file.stem  # YYYY-MM-DD
        try:
            file_date = datetime.strptime(date_str, "%Y-%m-%d")
            if file_date < cutoff:
                # Compress and move
                with open(session_file, 'rb') as f_in:
                    with gzip.open(archive_dir / f"{session_file.name}.gz", 'wb') as f_out:
                        f_out.writelines(f_in)
                session_file.unlink()
                archived += 1
        except ValueError:
            pass

    result = f"Archived {archived} old session logs"
  output: archive_result
```

---

### 8. Pattern Auto-Discovery

**Problem:** Patterns must be manually added via `learn_pattern` skill.

**Proposed:** Auto-detect common error patterns.

```python
# scripts/pattern_miner.py

def mine_patterns_from_failures():
    """Analyze tool_failures.yaml to discover new patterns."""
    failures = read_memory("learned/tool_failures")
    patterns = read_memory("learned/patterns")

    # Group failures by error text similarity
    from difflib import SequenceMatcher

    error_groups = []
    for failure in failures.get("failures", []):
        error = failure["error_snippet"]

        # Find similar errors
        matched = False
        for group in error_groups:
            similarity = SequenceMatcher(None, error, group["representative"]).ratio()
            if similarity > 0.8:
                group["count"] += 1
                group["errors"].append(error)
                matched = True
                break

        if not matched:
            error_groups.append({
                "representative": error,
                "count": 1,
                "errors": [error],
            })

    # Suggest patterns for frequent errors
    suggestions = []
    for group in error_groups:
        if group["count"] >= 5:  # Seen 5+ times
            # Check if already in patterns
            already_learned = any(
                group["representative"].lower() in str(patterns).lower()
            )

            if not already_learned:
                suggestions.append({
                    "pattern": group["representative"][:50],
                    "frequency": group["count"],
                    "examples": group["errors"][:3],
                })

    return suggestions
```

**Skill:**
```yaml
# skills/suggest_patterns.yaml
- name: mine_patterns
  compute: |
    from scripts.pattern_miner import mine_patterns_from_failures
    suggestions = mine_patterns_from_failures()
    result = suggestions
  output: pattern_suggestions

outputs:
  - name: summary
    value: |
      ## 🔍 Suggested Patterns

      {% for suggestion in pattern_suggestions %}
      ### Pattern: {{ suggestion.pattern }}
      **Frequency:** {{ suggestion.frequency }} occurrences

      **Examples:**
      {% for example in suggestion.examples %}
      - {{ example }}
      {% endfor %}

      **Action:** Run `learn_pattern` to add this
      {% endfor %}
```

---

### 9. Memory Schema Validation

**Problem:** No validation of memory file structure.

**Risk:**
```yaml
# current_work.yaml - Typo!
active_issuse:  # ← Should be "active_issues"
  - key: AAP-123
```

Skills silently fail to find data.

**Solution:**

```python
# scripts/common/memory_schemas.py

from pydantic import BaseModel, Field
from typing import List, Optional

class ActiveIssue(BaseModel):
    key: str
    summary: str
    status: str
    branch: str
    repo: str
    started: str

class CurrentWork(BaseModel):
    active_issue: Optional[str] = ""
    active_issues: List[ActiveIssue] = []
    open_mrs: List[dict] = []
    follow_ups: List[dict] = []
    last_updated: str

class ErrorPattern(BaseModel):
    pattern: str
    meaning: str
    fix: str
    commands: List[str] = []
    usage_stats: Optional[dict] = None

class Patterns(BaseModel):
    auth_patterns: List[ErrorPattern] = []
    error_patterns: List[ErrorPattern] = []
    bonfire_patterns: List[ErrorPattern] = []
    # ...

# In memory.py
def validate_memory(key: str, data: dict) -> bool:
    """Validate memory data against schema."""
    schemas = {
        "state/current_work": CurrentWork,
        "learned/patterns": Patterns,
    }

    schema = schemas.get(key)
    if schema:
        try:
            schema(**data)
            return True
        except Exception as e:
            logger.warning(f"Memory validation failed for {key}: {e}")
            return False
    return True

def write_memory(key: str, data: dict) -> bool:
    if not validate_memory(key, data):
        return False
    # ... existing write logic ...
```

---

### 10. Cross-Skill Memory Sharing

**Problem:** Skills can't easily share context.

**Example:**
```python
# Skill A discovers important info
skill_run("investigate_alert", '{"environment": "stage"}')
# → Finds: "High CPU on pod tower-analytics-api-123"

# Skill B needs this context
skill_run("debug_prod", '{"namespace": "stage"}')
# → Has to re-discover the same info
```

**Proposed:**

```yaml
# New memory file: state/shared_context.yaml
current_investigation:
  started_by: "investigate_alert"
  started_at: "2026-01-09T14:30:00"
  context:
    environment: "stage"
    namespace: "tower-analytics-prod"
    issue: "High CPU on pod tower-analytics-api-123"
    pod_name: "tower-analytics-api-123"
    related_alerts: ["HighCPU", "SlowRequests"]

expires_at: "2026-01-09T15:30:00"  # 1 hour TTL
```

**Usage:**

```yaml
# investigate_alert.yaml - Save context
- name: save_investigation_context
  tool: memory_write
  args:
    key: "state/shared_context"
    content: |
      current_investigation:
        started_by: "investigate_alert"
        context:
          environment: "{{ inputs.environment }}"
          pod_name: "{{ problematic_pod }}"
          issue: "{{ issue_summary }}"
        expires_at: "{{ expiry_time }}"

# debug_prod.yaml - Load context
- name: load_shared_context
  tool: memory_read
  args:
    key: "state/shared_context"
  output: shared_ctx
  on_error: continue

- name: use_context
  condition: "{{ shared_ctx and shared_ctx.current_investigation }}"
  compute: |
    # Auto-populate from previous investigation
    pod = shared_ctx["current_investigation"]["context"]["pod_name"]
    result = f"Continuing investigation of {pod}"
```

---

## 🔵 Low Priority (Future Enhancements)

### 11. Memory Metrics Export

Export memory stats to Prometheus for monitoring.

```python
# server/memory_metrics.py
from prometheus_client import Counter, Gauge, Histogram

memory_reads = Counter('memory_reads_total', 'Total memory reads', ['file'])
memory_writes = Counter('memory_writes_total', 'Total memory writes', ['file'])
auto_heal_attempts = Counter('auto_heal_attempts_total', 'Auto-heal attempts', ['tool', 'type'])
auto_heal_success = Counter('auto_heal_success_total', 'Successful auto-heals', ['tool'])
pattern_matches = Counter('pattern_matches_total', 'Pattern matches', ['pattern'])
memory_file_size = Gauge('memory_file_size_bytes', 'Memory file size', ['file'])
```

---

### 12. Memory Replication

Replicate memory across multiple machines for teams.

```python
# Sync learned patterns across team
git add memory/learned/*.yaml
git commit -m "sync: Update learned patterns"
git push
```

---

### 13. Memory A/B Testing

Test different auto-heal strategies.

```yaml
# learned/patterns_experimental.yaml
auth_patterns:
  - pattern: "token expired"
    fix: "Try refresh token before full reauth"  # New strategy
    commands: ["refresh_token()", "kube_login()"]  # Fallback
```

---

## 📋 Implementation Priority

| Priority | Item | Effort | Impact | Risk |
|----------|------|--------|--------|------|
| 🔴 **P0** | Race condition fix | Medium | High | High |
| 🔴 **P0** | Backup strategy | Low | High | High |
| 🔴 **P0** | Stats growth limit | Low | Medium | Medium |
| 🟡 **P1** | Memory query interface | Medium | High | Low |
| 🟡 **P1** | Analytics dashboard | Medium | Medium | Low |
| 🟡 **P1** | Pattern effectiveness | Medium | High | Low |
| 🟢 **P2** | Session archival | Low | Low | Low |
| 🟢 **P2** | Pattern auto-discovery | High | Medium | Low |
| 🟢 **P2** | Schema validation | Medium | Medium | Low |
| 🟢 **P2** | Cross-skill context | Medium | Medium | Low |
| 🔵 **P3** | Metrics export | Medium | Low | Low |
| 🔵 **P3** | Memory replication | High | Low | Medium |
| 🔵 **P3** | A/B testing | High | Low | Low |

---

## 🎯 Quick Wins (Do This Week)

1. **Add backup before memory_init** (30 min)
2. **Implement file locking** (2 hours)
3. **Add stats rotation** (1 hour)
4. **Create memory_stats tool** (2 hours)

**Total:** ~5.5 hours for major improvements.

---

## 📖 Related Documentation

- [Memory Complete Reference](./MEMORY-COMPLETE-REFERENCE.md)
- [Memory & Auto-Remediation](./memory-and-auto-remediation.md)
- [Memory Integration Deep Dive](./memory-integration-deep-dive.md)
