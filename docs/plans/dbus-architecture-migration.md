# D-Bus Architecture Migration Plan

## Overview

This document outlines the migration to a clean D-Bus-based architecture where:
- **All daemon state** is accessed exclusively via D-Bus (read AND write)
- **State files are internal** to daemons - UI never reads/writes them directly
- **No race conditions** - daemons own their state completely

```
┌─────────────────────────────────────────────────────────────┐
│                         VS Code UI                          │
│         (D-Bus only for daemon state, no file I/O)          │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ D-Bus (read & write)
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                        D-Bus Bus                            │
└─────────────────────────────────────────────────────────────┘
         │              │              │              │
         ▼              ▼              ▼              ▼
    ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐
    │ Sprint  │   │  Meet   │   │  Cron   │   │ Session │
    │ Daemon  │   │ Daemon  │   │ Daemon  │   │ Daemon  │
    └────┬────┘   └────┬────┘   └────┬────┘   └────┬────┘
         │              │              │              │
         ▼              ▼              ▼              ▼
    ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐
    │ .json   │   │ .json   │   │ .json   │   │ .json   │
    │(internal)│  │(internal)│  │(internal)│  │(internal)│
    └─────────┘   └─────────┘   └─────────┘   └─────────┘
```

---

## Step 1: Daemon State via D-Bus

Migrate all daemon-owned state to D-Bus access. The UI will use D-Bus for both reading and writing daemon state.

### 1.1 Current State (Before Migration)

| Daemon | Service Name | State File | UI Reads File | UI Uses D-Bus |
|--------|--------------|------------|---------------|---------------|
| Sprint | `com.aiworkflow.BotSprint` | `sprint_state_v2.json` | ✅ Yes | ✅ Write only |
| Meet | `com.aiworkflow.BotMeet` | `meet_state.json` | ✅ Yes | ✅ Write only |
| Cron | `com.aiworkflow.BotCron` | `cron_state.json` | ✅ Yes | ✅ Write only |
| Session | `com.aiworkflow.BotSession` | `session_state.json` | ✅ Yes | ⚠️ Partial |
| Slack | None | `slack_state.db` | ⚠️ Legacy JSON | ❌ No D-Bus |

### 1.2 Target State (After Step 1)

| Daemon | UI Reads File | UI Uses D-Bus Read | UI Uses D-Bus Write |
|--------|---------------|--------------------|--------------------|
| Sprint | ❌ No | ✅ `get_state` | ✅ All actions |
| Meet | ❌ No | ✅ `get_state` | ✅ All actions |
| Cron | ❌ No | ✅ `get_state` | ✅ All actions |
| Session | ❌ No | ✅ `get_state` | ✅ All actions |
| Slack | ❌ No | ✅ `get_state` | ✅ All actions |

### 1.3 Tasks

#### 1.3.1 Add `get_state` D-Bus Methods

Each daemon needs a `get_state` method that returns its full state:

**Sprint Daemon** (`scripts/sprint_daemon.py`):
```python
async def _handle_get_state(self, params: dict) -> dict:
    """Get full sprint state for UI."""
    state = self._load_state()
    return {"success": True, "state": state}
```
- Register: `self.register_handler("get_state", self._handle_get_state)`

**Meet Daemon** (`scripts/meet_daemon.py`):
```python
async def _handle_get_state(self, params: dict) -> dict:
    """Get full meet state for UI."""
    # Build state from scheduler
    state = await self._build_state()
    return {"success": True, "state": state}
```
- Register: `self.register_handler("get_state", self._handle_get_state)`

**Cron Daemon** (`scripts/cron_daemon.py`):
```python
async def _handle_get_state(self, params: dict) -> dict:
    """Get full cron state for UI."""
    state = await self._build_state()
    return {"success": True, "state": state}
```
- Register: `self.register_handler("get_state", self._handle_get_state)`

**Session Daemon** (`scripts/session_daemon.py`):
- Already has `get_state` handler ✅

**Slack Daemon** (`scripts/slack_daemon.py`):
- Needs full D-Bus interface added (see 1.3.4)

#### 1.3.2 Update UI to Use D-Bus for Reads

Replace file reads in `commandCenter.ts`:

**Current (file read):**
```typescript
if (fs.existsSync(SESSION_STATE_FILE)) {
  const content = fs.readFileSync(SESSION_STATE_FILE, "utf8");
  const sessionState = JSON.parse(content);
  // ...
}
```

**Target (D-Bus read):**
```typescript
const result = await this.queryDBus(
  "com.aiworkflow.BotSession",
  "/com/aiworkflow/BotSession",
  "com.aiworkflow.BotSession",
  "CallMethod",
  [
    { type: "string", value: "get_state" },
    { type: "string", value: "{}" },
  ]
);
if (result.success && result.data) {
  const sessionState = JSON.parse(result.data).state;
  // ...
}
```

**Files to update:**
- `commandCenter.ts`: `_loadWorkspaceState()` method
- `sprintTab.ts`: `loadSprintState()`, `loadSprintStateFromFile()`
- `meetingsTab.ts`: `loadMeetBotState()`
- `performanceTab.ts`: If reading from daemon state

#### 1.3.3 Remove File Watchers

Remove file watching from UI since state comes from D-Bus:

**Current (`commandCenter.ts`):**
```typescript
private _setupWorkspaceWatcher(): void {
  // Watches SESSION_STATE_FILE, MEET_STATE_FILE, CRON_STATE_FILE, etc.
  this._fileWatcher = fs.watch(dir, ...);
}
```

**Target:**
- Remove `_setupWorkspaceWatcher()` entirely
- Replace with periodic D-Bus polling (every 10s) or D-Bus signals

#### 1.3.4 Add D-Bus Interface to Slack Daemon

The slack daemon currently has no D-Bus interface. Add:

```python
class SlackDaemon(SleepWakeAwareDaemon, DaemonDBusBase):
    service_name = "com.aiworkflow.BotSlack"
    object_path = "/com/aiworkflow/BotSlack"
    interface_name = "com.aiworkflow.BotSlack"

    def __init__(self, ...):
        # Register handlers
        self.register_handler("get_state", self._handle_get_state)
        self.register_handler("get_channels", self._handle_get_channels)
        self.register_handler("get_pending", self._handle_get_pending)
        self.register_handler("send_message", self._handle_send_message)
        self.register_handler("approve_message", self._handle_approve_message)
        # ...
```

#### 1.3.5 Session Daemon - Add Missing Write Handlers

Session daemon needs handlers for state modifications:

```python
self.register_handler("remove_workspace", self._handle_remove_workspace)
self.register_handler("rename_session", self._handle_rename_session)
```

### 1.4 Files Changed

| File | Changes |
|------|---------|
| `scripts/sprint_daemon.py` | Add `get_state` handler |
| `scripts/meet_daemon.py` | Add `get_state` handler |
| `scripts/cron_daemon.py` | Add `get_state` handler |
| `scripts/session_daemon.py` | Add `remove_workspace`, `rename_session` handlers |
| `scripts/slack_daemon.py` | Add full D-Bus interface |
| `extensions/.../commandCenter.ts` | Replace file reads with D-Bus calls |
| `extensions/.../sprintTab.ts` | Replace file reads with D-Bus calls |
| `extensions/.../meetingsTab.ts` | Replace file reads with D-Bus calls |

### 1.5 State Files After Step 1

| File | Status | Notes |
|------|--------|-------|
| `session_state.json` | Internal to daemon | UI uses D-Bus |
| `sprint_state_v2.json` | Internal to daemon | UI uses D-Bus |
| `meet_state.json` | Internal to daemon | UI uses D-Bus |
| `cron_state.json` | Internal to daemon | UI uses D-Bus |
| `cron_history.json` | Internal to daemon | UI uses D-Bus `get_history` |
| `slack_state.db` | Internal to daemon | UI uses D-Bus |
| `workspace_states.json` | **DELETE** | Legacy, no longer needed |
| `sprint_state.json` | **DELETE** | Replaced by v2 |
| `sync_cache.json` | **DELETE** | Sync script removed |

### 1.6 Verification

After Step 1 completion:
- [ ] UI has zero reads from daemon state files
- [ ] UI has zero writes to daemon state files
- [ ] All daemon state accessed via D-Bus
- [ ] File watchers removed from UI
- [ ] Legacy files deleted

---

## Step 2: MCP-Managed State via D-Bus (Optional)

Extend the D-Bus architecture to cover MCP server managed state. This requires new daemons or extending the MCP server with D-Bus.

### 2.1 Scope

State currently managed by MCP server or read directly from files:

| State | Current Location | Current Access |
|-------|------------------|----------------|
| Skills | `skills/*.yaml` | File read |
| Personas | `personas/*.yaml` | File read |
| Memory | `memory/**/*.yaml` | File read / MCP tools |
| Agent Stats | `agent_stats.json` | File read |
| Inference Stats | `inference_stats.json` | File read |
| Skill Execution | `skill_execution.json` | File read |
| Notifications | `notifications.json` | File read |

### 2.2 Options

#### Option 2A: New Daemons

Create dedicated daemons for each domain:

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│   Skills    │  │   Memory    │  │    Stats    │
│   Daemon    │  │   Daemon    │  │   Daemon    │
└─────────────┘  └─────────────┘  └─────────────┘
```

**Pros:**
- Clean separation
- Each daemon owns its state

**Cons:**
- More processes to manage
- More systemd services
- Increased complexity

#### Option 2B: Extend MCP Server with D-Bus

Add D-Bus interface to the existing MCP server:

```python
# server/main.py
class MCPServerDBus(DaemonDBusBase):
    service_name = "com.aiworkflow.MCPServer"

    def __init__(self):
        self.register_handler("get_skills", self._handle_get_skills)
        self.register_handler("get_personas", self._handle_get_personas)
        self.register_handler("get_memory", self._handle_get_memory)
        self.register_handler("get_stats", self._handle_get_stats)
```

**Pros:**
- Single process
- MCP server already manages this state

**Cons:**
- MCP server becomes more complex
- Mixes MCP protocol with D-Bus

#### Option 2C: Hybrid - Keep File Reads for Static Config

Keep file reads for truly static configuration:

| State | Access Method | Rationale |
|-------|---------------|-----------|
| Skills | File read | Static YAML, rarely changes |
| Personas | File read | Static YAML, rarely changes |
| Memory | MCP tools | Already has MCP interface |
| Stats | D-Bus (new daemon) | Dynamic, frequently updated |

**Pros:**
- Pragmatic balance
- Less work

**Cons:**
- Inconsistent architecture

### 2.3 Recommended Approach

**Option 2C (Hybrid)** is recommended:

1. **Static config stays as files**: Skills, personas, memory YAML
2. **Dynamic stats get a daemon**: New `stats_daemon.py` for agent_stats, inference_stats, skill_execution
3. **MCP tools for memory**: Already works via MCP

### 2.4 Tasks (If Implementing Full Option 2A/2B)

#### 2.4.1 Skills Daemon

```python
# scripts/skills_daemon.py
class SkillsDaemon(DaemonDBusBase):
    service_name = "com.aiworkflow.Skills"

    def __init__(self):
        self.register_handler("list_skills", self._handle_list_skills)
        self.register_handler("get_skill", self._handle_get_skill)
        self.register_handler("run_skill", self._handle_run_skill)
```

#### 2.4.2 Memory Daemon

```python
# scripts/memory_daemon.py
class MemoryDaemon(DaemonDBusBase):
    service_name = "com.aiworkflow.Memory"

    def __init__(self):
        self.register_handler("read", self._handle_read)
        self.register_handler("write", self._handle_write)
        self.register_handler("append", self._handle_append)
        self.register_handler("list", self._handle_list)
```

#### 2.4.3 Stats Daemon

```python
# scripts/stats_daemon.py
class StatsDaemon(DaemonDBusBase):
    service_name = "com.aiworkflow.Stats"

    def __init__(self):
        self.register_handler("get_agent_stats", self._handle_get_agent_stats)
        self.register_handler("get_inference_stats", self._handle_get_inference_stats)
        self.register_handler("get_skill_execution", self._handle_get_skill_execution)
        self.register_handler("record_execution", self._handle_record_execution)
```

### 2.5 UI Changes for Step 2

Replace remaining file reads:

```typescript
// Before
const skills = fs.readdirSync(skillsDir).map(f => {
  const content = fs.readFileSync(path.join(skillsDir, f), "utf-8");
  // ...
});

// After
const result = await this.queryDBus(
  "com.aiworkflow.Skills",
  "/com/aiworkflow/Skills",
  "com.aiworkflow.Skills",
  "CallMethod",
  [{ type: "string", value: "list_skills" }, { type: "string", value: "{}" }]
);
const skills = JSON.parse(result.data).skills;
```

### 2.6 Verification

After Step 2 completion:
- [ ] UI has zero file reads for any state
- [ ] All state accessed via D-Bus or MCP tools
- [ ] New daemons have systemd services
- [ ] All daemons have health checks

---

## Summary

| Step | Scope | File Reads Removed | Complexity |
|------|-------|-------------------|------------|
| **Step 1** | Daemon state | ~15 | Medium |
| **Step 2** | MCP/static state | ~65 | High |

**Recommendation:** Complete Step 1 first. Evaluate if Step 2 is needed based on actual pain points.

---

## Implementation Progress (2026-01-30)

### Completed

1. **ConfigDaemon** (`scripts/config_daemon.py`)
   - Created daemon for skills, personas, tool_modules, config.json
   - File watchers for automatic cache invalidation
   - D-Bus service: `com.aiworkflow.Config`
   - Systemd service: `bot-config.service` (installed and running)

2. **MemoryDaemon** (`scripts/memory_daemon.py`)
   - Created daemon for memory/*.yaml files
   - Methods: get_health, get_files, get_current_work, get_environments, get_patterns, read, write, append
   - D-Bus service: `com.aiworkflow.Memory`
   - Systemd service: `bot-memory.service` (installed and running)

3. **StatsDaemon** (`scripts/stats_daemon.py`)
   - Already existed, verified running
   - Methods: get_agent_stats, get_inference_stats, get_skill_execution
   - D-Bus service: `com.aiworkflow.BotStats`
   - Systemd service: `bot-stats.service` (installed and running)

4. **dbusClient.ts Updates**
   - Added Config daemon methods: config_getSkillsList, config_getSkillDefinition, config_getPersonasList, config_getPersonaDefinition, config_getToolModules, config_getConfig
   - Added Memory daemon methods: memory_getHealth, memory_getFiles, memory_getCurrentWork, memory_getEnvironments, memory_getPatterns, memory_read, memory_write, memory_append

5. **commandCenter.ts Refactoring**
   - Converted synchronous methods to return cached values
   - Added async D-Bus methods with file fallbacks:
     - `loadStatsAsync()` → StatsDaemon
     - `loadSkillsListAsync()` → ConfigDaemon
     - `loadToolModulesAsync()` → ConfigDaemon
     - `loadPersonasAsync()` → ConfigDaemon
     - `loadCurrentWorkAsync()` → MemoryDaemon
     - `getMemoryHealthAsync()` → MemoryDaemon
     - `loadMemoryFilesAsync()` → MemoryDaemon
   - Main `update()` uses `Promise.all()` for parallel D-Bus calls
   - Synchronous methods now return cached values (populated by async methods)

6. **memoryTab.ts Updates**
   - Added `loadStatsAsync()` using MemoryDaemon D-Bus
   - Parallel D-Bus calls for health, current_work, environments, patterns

### Completed (continued)

7. **TypeScript Type Alignment**
   - Fixed `AgentStats` interface in dbusClient.ts to include optional `tools` and `skills` fields
   - Made several fields optional to handle both D-Bus and file-based data sources
   - TypeScript compilation passes successfully

### Remaining File Accesses

File accesses still in UI (mostly fallbacks or local data):
- Fallback paths when D-Bus unavailable (acceptable for resilience)
- Local Cursor/Claude/Gemini session data (not daemon-managed)
- Vector cache stats (local cache, not daemon-managed)
- Environment updates via `memory_write` (needs migration)

---

## Appendix: D-Bus Service Reference

| Service | Object Path | Interface |
|---------|-------------|-----------|
| `com.aiworkflow.BotSprint` | `/com/aiworkflow/BotSprint` | `com.aiworkflow.BotSprint` |
| `com.aiworkflow.BotMeet` | `/com/aiworkflow/BotMeet` | `com.aiworkflow.BotMeet` |
| `com.aiworkflow.BotCron` | `/com/aiworkflow/BotCron` | `com.aiworkflow.BotCron` |
| `com.aiworkflow.BotSession` | `/com/aiworkflow/BotSession` | `com.aiworkflow.BotSession` |
| `com.aiworkflow.BotSlack` | `/com/aiworkflow/BotSlack` | `com.aiworkflow.BotSlack` |
| `com.aiworkflow.Skills` | `/com/aiworkflow/Skills` | `com.aiworkflow.Skills` |
| `com.aiworkflow.Memory` | `/com/aiworkflow/Memory` | `com.aiworkflow.Memory` |
| `com.aiworkflow.Stats` | `/com/aiworkflow/Stats` | `com.aiworkflow.Stats` |
