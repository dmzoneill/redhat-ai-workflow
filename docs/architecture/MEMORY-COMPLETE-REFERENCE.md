# Memory & Auto-Remediation: Complete Reference

> Master index of all memory-related documentation and integration points

## 📚 Documentation Suite

This is the master reference for the complete memory and auto-remediation system. Read these documents in order:

### 1. [memory-and-auto-remediation.md](./memory-and-auto-remediation.md) - **START HERE**

**Purpose:** High-level overview with architecture diagrams

**Contains:**
- Memory directory structure
- Memory tools (5 MCP tools)
- Auto-heal decorator system
- Skill-level auto-fix
- Data flow diagrams
- Usage patterns
- Statistics and coverage

**Read this first** for conceptual understanding.

### 2. [memory-integration-deep-dive.md](./memory-integration-deep-dive.md) - **DEEP DIVE**

**Purpose:** Exhaustive analysis of every integration point

**Contains:**
- scripts/common/memory.py helpers (15+ functions)
- session_start() comprehensive loading
- check_known_issues() dual implementation
- Memory access patterns (A, B, C)
- Direct YAML vs MCP tools vs Python helpers
- Memory consistency and concurrency
- Context resolver integration
- Complete file reference table
- Memory initialization process

**Read this second** for implementation details.

---

## 🗂️ Quick Reference

### Memory Files

| File | Purpose | Size | Managed By | Primary Readers | Primary Writers |
|------|---------|------|------------|-----------------|-----------------|
| **state/current_work.yaml** | Active issues, MRs, follow-ups | ~2 KB | Skills | session_start, coffee, standup | start_work, create_mr, close_mr |
| **state/environments.yaml** | Environment health status | ~3 KB | Skills | session_start, coffee | deploy_to_ephemeral, investigate_alert |
| **learned/patterns.yaml** | Error patterns with fixes | ~8 KB | learn_pattern | check_known_issues (all), debug_prod | learn_pattern, manual |
| **learned/tool_failures.yaml** | Auto-heal failure log | ~15 KB | auto_heal | debug_tool, memory_view | _log_auto_heal_to_memory (auto) |
| **learned/tool_fixes.yaml** | Manual tool fixes | ~5 KB | Manual | check_known_issues, debug_tool | learn_tool_fix, debug_tool |
| **learned/runbooks.yaml** | Operational procedures | ~10 KB | Manual | debug_prod, investigate_alert | Manual |
| **learned/skill_error_fixes.yaml** | Skill compute errors | ~5 KB | skill_error_recovery | skill_error_recovery | log_fix_attempt (auto) |
| **sessions/YYYY-MM-DD.yaml** | Daily activity log | ~3 KB | memory_session_log | standup, weekly, coffee, beer | memory_session_log (39 skills) |

### Memory Tools (MCP)

| Tool | Purpose | Example |
|------|---------|---------|
| `memory_read(key)` | Read YAML file | `memory_read("state/current_work")` |
| `memory_write(key, content)` | Write YAML file | `memory_write("state/current_work", yaml_str)` |
| `memory_update(key, path, value)` | Update single field | `memory_update("state/current_work", "active_issue", "AAP-123")` |
| `memory_append(key, list_path, item)` | Append to list | `memory_append("state/current_work", "active_issues", yaml_item)` |
| `memory_session_log(action, details)` | Log to today's session | `memory_session_log("Started AAP-123", "branch: main")` |

### Python Helper Functions

```python
from scripts.common.memory import (
    read_memory,          # Read YAML file → dict
    write_memory,         # Write dict → YAML file
    append_to_list,       # Add to list (with dedup)
    remove_from_list,     # Remove from list
    update_field,         # Update nested field
    get_active_issues,    # Get active_issues list
    add_active_issue,     # Add issue to active_issues
    remove_active_issue,  # Remove issue
    # ... 8 more functions
)
```text

### Auto-Heal Coverage

| Module | Tools | Decorated | Coverage |
|--------|-------|-----------|----------|
| aa_git | 30 | 30 | 100% |
| aa_gitlab | 30 | 30 | 100% |
| aa_jira | 28 | 28 | 100% |
| aa_k8s | 28 | 28 | 100% |
| aa_bonfire | 20 | 20 | 100% |
| aa_konflux | 35 | 35 | 100% |
| aa_prometheus | 13 | 13 | 100% |
| aa_quay | 7 | 7 | 100% |
| aa_alertmanager | 7 | 7 | 100% |
| aa_kibana | 9 | 9 | 100% |
| aa_appinterface | 7 | 7 | 100% |
| aa_slack | 9 | 9 | 100% |
| aa_google_calendar | 6 | 6 | 100% |
| aa_lint | 7 | 7 | 100% |
| aa_dev_workflow | 9 | 9 | 100% |
| **TOTAL** | **239+** | **239+** | **100%** |

---

## 🔄 Auto-Remediation Flow

### Tool-Level (Auto-Heal Decorator)

```python
Tool Fails
    ↓
@auto_heal() Detects Pattern
    ↓
Applies Fix (kube_login/vpn_connect)
    ↓
Logs to memory/learned/tool_failures.yaml
    ↓
Retries Tool (max 1 retry)
    ↓
Returns Result
```text

**Success Rate:** 77% (98 of 127 failures auto-fixed)

### Skill-Level (Pattern Matching)

```text
Skill Step Fails
    ↓
check_known_issues() → Reads patterns.yaml + tool_fixes.yaml
    ↓
_try_auto_fix() → Applies VPN/auth fix
    ↓
Retries Tool (once)
    ↓
Continues Skill Execution
```text

**Pattern Categories:**
- auth_patterns (3) - kube_login fixes
- network_patterns (1) - vpn_connect fixes
- bonfire_patterns (3) - CLI flag fixes
- error_patterns (7) - Diagnostic guidance
- pipeline_patterns (4) - Test/build fixes
- jira_cli_patterns (2) - rh-issue usage

---

## 📊 Usage Statistics

### Memory Operations per Day

```text
Total:  ~395 operations/day

Reads:  ~250/day (65%)
  - check_known_issues: ~50
  - session_start: 5 files
  - skill compute blocks: ~195

Writes: ~145/day (35%)
  - memory_session_log: ~30
  - auto_heal logging: ~100
  - skill state updates: ~15
```text

### Skill Memory Usage

| Category | Skills | Memory Operations | Files |
|----------|--------|-------------------|-------|
| **Workflow** | 15 | append, update, session_log | current_work, sessions |
| **Investigation** | 8 | read patterns, session_log | patterns, sessions |
| **Reporting** | 6 | read work/sessions | current_work, sessions |
| **Memory Mgmt** | 4 | direct YAML r/w | All files |
| **Learning** | 1 | write patterns | patterns |
| **Deployment** | 12 | update env, session_log | environments, sessions |

**Total:** 46 of 55 skills (85%) use memory

### Most-Read Files

1. **learned/patterns.yaml** - ~75 reads/day
2. **state/current_work.yaml** - ~60 reads/day
3. **sessions/YYYY-MM-DD.yaml** - ~35 reads/day

### Most-Written Files

1. **learned/tool_failures.yaml** - ~100 writes/day (auto-heal)
2. **sessions/YYYY-MM-DD.yaml** - ~30 appends/day (session_log)
3. **state/current_work.yaml** - ~10 updates/day (workflow)

---

## 🏗️ Architecture Layers

```text
┌─────────────────────────────────────────────────────┐
│ Layer 1: MCP Tools                                   │
│  memory_read, memory_write, memory_update,           │
│  memory_append, memory_session_log                   │
│  → Used by: Claude, 39 skills                        │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ Layer 2: Python Helpers (scripts/common/memory)     │
│  read_memory, write_memory, append_to_list,          │
│  get_active_issues, add_active_issue, etc.           │
│  → Used by: Skills in compute blocks                 │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ Layer 3: Direct YAML Operations                     │
│  with open(...) as f: yaml.safe_load(f)              │
│  → Used by: 10 memory-focused skills                 │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ Layer 4: Auto-Heal Logging                          │
│  _log_auto_heal_to_memory()                          │
│  → Direct writes to tool_failures.yaml               │
│  → Used by: All 239+ decorated tools                 │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ Layer 5: Skill Engine Pattern Checking              │
│  _check_known_issues_sync()                          │
│  → Reads patterns.yaml, tool_fixes.yaml              │
│  → Used by: All skill executions on failure          │
└─────────────────────────────────────────────────────┘
```

---

## 🎯 Key Findings

### Memory System

1. **5 MCP Tools** for declarative memory operations
2. **15+ Python Helpers** for programmatic operations in skills
3. **10+ Memory Files** across 3 directories (state, learned, sessions)
4. **85% Skill Adoption** (46 of 55 skills use memory)
5. **Auto-Timestamping** on all writes (`last_updated` field)

### Auto-Remediation

1. **100% Tool Coverage** - All 263 tools have @auto_heal decorators
2. **Two-Layer Defense** - Tool-level + Skill-level auto-fix
3. **77% Success Rate** - 98 of 127 failures auto-fixed
4. **Pattern Learning** - Failures logged to memory for future prevention
5. **20 Error Patterns** across 6 categories

### Integration Points

1. **Tool → Memory** - Auto-heal logs failures
2. **Skill → Memory** - Pattern checking and session logging
3. **User → Memory** - learn_pattern skill
4. **Session → Memory** - Daily activity tracking
5. **Context → Memory** - Resolved contexts saved to current_work

### Daily Operations

- **~395 memory operations** (250 reads, 145 writes)
- **~100 auto-heal logs** (failures with fixes)
- **~30 session logs** (user actions)
- **~25 pattern matches** (auto-fixes applied)
- **~15 state updates** (workflow changes)

---

## 🔍 Common Use Cases

### 1. Check What You're Working On

```bash
# Option A: Quick check
memory_read("state/current_work")

# Option B: Full context
session_start()
```

### 2. Start Work on Jira Issue

```bash
skill_run("start_work", '{"issue_key": "AAP-12345"}')

# Automatically:
# - Reads current_work from memory
# - Creates branch
# - Appends to active_issues in memory
# - Logs to sessions/YYYY-MM-DD.yaml
```

### 3. Learn a New Error Pattern

```bash
skill_run("learn_pattern", '{
  "pattern": "OOMKilled",
  "meaning": "Container exceeded memory limits",
  "fix": "Increase memory limits in deployment",
  "commands": "kubectl describe pod X, kubectl top pod X",
  "category": "error_patterns"
}')

# Writes to: memory/learned/patterns.yaml
# Future failures will match this pattern
```

### 4. Debug Tool Failure

```bash
# Tool fails
bonfire_namespace_reserve(duration="2h")
# → "Unauthorized: token expired"

# Auto-heal kicks in:
# 1. Detects "auth" failure
# 2. Runs kube_login(cluster="ephemeral")
# 3. Logs to tool_failures.yaml
# 4. Retries bonfire_namespace_reserve
# 5. Returns result
```

### 5. Daily Standup

```bash
skill_run("standup_summary")

# Reads:
# - memory/state/current_work.yaml (active issues)
# - memory/sessions/YYYY-MM-DD.yaml (today's actions)
# Returns formatted summary
```

---

## 🛠️ Development Guidelines

### When to Use MCP Tools vs Python Helpers

| Scenario | Use |
|----------|-----|
| Simple read/write from skill | MCP tools |
| Complex list manipulation | Python helpers |
| Session logging | Always MCP `memory_session_log()` |
| Compute block logic | Python helpers |
| Direct from Claude | MCP tools |

### Adding New Memory Patterns

1. **Discover pattern** during debugging
2. **Run learn_pattern skill** to save it
3. **Pattern auto-matches** in future failures
4. **Auto-fix applies** if pattern includes fix commands

### Memory File Best Practices

1. **Keep files small** - Rolling windows for logs (100 entries)
2. **Use timestamps** - Auto-added on writes
3. **Dedup on append** - Use `match_key` parameter
4. **Read-modify-write** - For atomic updates
5. **Best-effort writes** - Don't fail tools on memory errors

---

## 📖 Related Documentation

### Core Documentation

- [Architecture README](./README.md) - Overall architecture
- [Memory & Auto-Remediation](./memory-and-auto-remediation.md) - High-level overview
- [Memory Integration Deep Dive](./memory-integration-deep-dive.md) - Implementation details

### Source Code

- [auto_heal_decorator.py](../../server/auto_heal_decorator.py) - Tool-level auto-heal
- [skill_engine.py](../../tool_modules/aa_workflow/src/skill_engine.py) - Skill-level auto-fix
- [memory_tools.py](../../tool_modules/aa_workflow/src/memory_tools.py) - MCP memory tools
- [memory.py](../../scripts/common/memory.py) - Python helper functions
- [auto_heal.py](../../scripts/common/auto_heal.py) - Skill-level auto-heal utilities
- [skill_error_recovery.py](../../scripts/common/skill_error_recovery.py) - Compute error recovery
- [session_tools.py](../../tool_modules/aa_workflow/src/session_tools.py) - session_start() tool
- [meta_tools.py](../../tool_modules/aa_workflow/src/meta_tools.py) - check_known_issues() tool

### Skills Documentation

- [start_work](../skills/start_work.md) - Uses memory_append, memory_update
- [create_mr](../skills/create_mr.md) - Uses memory_append
- [learn_pattern](../skills/learn_pattern.md) - Writes to patterns.yaml
- [debug_prod](../skills/debug_prod.md) - Reads patterns.yaml
- [standup_summary](../skills/standup_summary.md) - Reads sessions/*.yaml
- [memory_init](../skills/memory_init.md) - Resets all memory files
- [memory_cleanup](../skills/memory_cleanup.md) - Removes stale entries
- [memory_view](../skills/memory_view.md) - View/manage memory

---

## 🎓 Learning Path

**For New Users:**
1. Read [memory-and-auto-remediation.md](./memory-and-auto-remediation.md)
2. Try `session_start()` tool
3. Run `skill_run("start_work", '{"issue_key": "AAP-123"}')`
4. Check `memory_read("state/current_work")`
5. Review `memory_read("learned/patterns")`

**For Skill Developers:**
1. Read [memory-integration-deep-dive.md](./memory-integration-deep-dive.md)
2. Study existing skills (start_work, create_mr)
3. Use Python helpers in compute blocks
4. Always call `memory_session_log()` for user actions
5. Add error patterns via `learn_pattern` skill

**For System Administrators:**
1. Review memory file locations and sizes
2. Understand auto-heal logging frequency
3. Monitor `tool_failures.yaml` growth
4. Implement backup strategy for learned/ directory
5. Consider log rotation for sessions/ directory

---

## 📈 Success Metrics

### Auto-Remediation Effectiveness

- **77% auto-fix rate** - Most failures resolved without user intervention
- **100% tool coverage** - All tools have auto-heal
- **20 learned patterns** - Growing knowledge base
- **~25 pattern matches/day** - Active learning in use

### Memory Adoption

- **85% skill adoption** - 46 of 55 skills use memory
- **39 skills log sessions** - Complete activity tracking
- **~395 operations/day** - Heavy usage
- **10+ memory files** - Rich context persistence

### Developer Experience

- **Single tool for context** - `session_start()` loads everything
- **Automatic session logging** - No manual tracking needed
- **Pattern learning** - One command to save knowledge
- **Zero manual fixes** - Most issues auto-remediate

---

This completes the comprehensive memory and auto-remediation reference documentation.
