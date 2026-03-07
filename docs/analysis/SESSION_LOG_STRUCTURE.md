# Session Log Structure: Separation by Chat

**Date:** 2026-03-07  
**Goal:** Preserve chronological order while giving clear separation between chats (sessions) in the daily session log.

## Current behavior (after change)

- **One file per day:** `memory/sessions/YYYY-MM-DD.yaml`
- **Structure:** Log is stored **by session**, not as a single flat list.

### New format

```yaml
date: '2026-03-06'
session_order: ['0b367547-36be-4d95-8a58-42c978125bbe', 'a1b2c3-...']  # order of first appearance
sessions:
  _global:
    entries:
      - { time: '10:20:00', action: 'cron: daily_cve_fix', type: cron, ... }
      - ...
  '0b367547-36be-4d95-8a58-42c978125bbe':
    started_at: '18:00:47'
    persona: developer
    project: redhat-ai-workflow
    name: null
    entries:
      - { time: '18:00:47', action: Session started, type: session, session_id: ... }
      - { time: '18:00:54', action: 'skill: slop_scan', type: skill, ... }
  'a1b2c3-...':
    ...
```

- **`_global`:** All entries that have no `session_id` (cron jobs, daemons, or legacy).
- **Per session_id:** One block per chat; `entries` are that chat’s events in order; optional `started_at`, `persona`, `project`, `name` from the first “Session started” entry.
- **Chronological order:** Not stored as a second list. Use **`get_session_log_entries(data)`** to get a single list ordered by `time` (merge of all sessions + `_global`).

## Backward compatibility

- **Legacy files** (only `entries: [...]`) are **migrated on first write**: the next `append_session_entry` rewrites the file into the new `sessions` structure (entries grouped by `session_id`, rest in `_global`).
- **Readers** use **`get_session_log_entries(data)`** so they work with both:
  - Legacy: `data["entries"]`
  - New: merge of `data["sessions"][*].entries` sorted by `time`

No separate migration script is required; migration happens when the day’s file is next appended to.

## How to read

### Chronological (e.g. “last 5 events today”)

```python
from tool_modules.aa_workflow.src.memory_tools import get_session_log_entries

with open(session_file) as f:
    data = yaml.safe_load(f) or {}
entries = get_session_log_entries(data)
for e in entries[-5:]:
    print(e["time"], e["action"])
```

### By chat (e.g. “what happened in this session?”)

```python
from tool_modules.aa_workflow.src.memory_tools import get_session_log_by_chat

with open(session_file) as f:
    data = yaml.safe_load(f) or {}
out = get_session_log_by_chat(data)
# out["chronological"]  - full list by time
# out["by_session"]    - dict: session_id -> { "meta": {...}, "entries": [...] }
# out["session_order"] - list of session_id in order of first appearance
for sid in out["session_order"]:
    if sid == "_global":
        continue
    block = out["by_session"][sid]
    print("Session", sid, block["meta"])
    for e in block["entries"]:
        print(" ", e["time"], e["action"])
```

## Where it’s used

- **`append_session_entry`** (memory_tools): Writes into `sessions[_global]` or `sessions[session_id]`; migrates legacy on first write.
- **`get_session_log_entries`**: Used by session_tools (_load_session_history), stats collector, memory daemon, ollama context_enrichment, memory_stats.
- **`get_session_log_by_chat`**: Available for UIs or skills that want to show “per chat” or “today’s chats” with separation.

## Design choices

1. **Single file per day** – Avoids many small files; one lock per day; easy to open “today” in an editor.
2. **Separation by session_id** – Chats are clearly separated; `_global` keeps cron/non-chat in one place.
3. **Chronological via merge** – No duplicated entries; chronological view is computed when needed.
4. **Migrate on write** – Legacy files are converted the first time we append that day; all readers use the helper so they work with both formats.
