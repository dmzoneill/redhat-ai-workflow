# Skill Execution History Plan

## Overview

Consolidate skill execution tracking into a single SQLite database that serves as the source of truth for both real-time execution state and historical records. This replaces the current JSON file-based approach with a more robust, queryable solution.

## Current State

### Existing Implementation

The current system uses `~/.config/aa-workflow/skill_execution.json` for tracking skill executions:

| Component | File | Role |
|-----------|------|------|
| **SkillExecutionEmitter** | `skill_execution_events.py` | Writes execution events during skill runs |
| **SkillExecutionWatcher** | `skillExecutionWatcher.ts` | Watches JSON file for real-time UI updates |
| **CommandCenter** | `commandCenter.ts` | Displays running skills panel |
| **CronScheduler** | `scheduler.py` | Cleans up stale executions on timeout |
| **cleanup_stale_executions** | `cleanup_stale_executions.yaml` | Periodic cleanup skill |

### Problems with Current Approach

1. **No persistent history** - Completed executions are deleted after 5 minutes
2. **File-based concurrency** - Lockfile mechanism is fragile across processes
3. **Limited queryability** - Cannot filter/search historical executions
4. **Scattered cleanup logic** - Multiple places handle stale execution cleanup
5. **No aggregated statistics** - Cannot easily compute success rates, durations

## Target State

### Single Source of Truth: SQLite Database

```
~/.config/aa-workflow/skill_history.db
```

All skill execution tracking consolidated into one SQLite database that provides:

- Real-time execution state (replaces JSON file)
- Persistent history (last 200 executions)
- Step-level results with full output capture
- Queryable via MCP tool
- Proper concurrency with WAL mode

### Architecture

```mermaid
flowchart TB
    subgraph MCP[MCP Server]
        SE[SkillExecutor]
        SHD[SkillHistoryDB]
    end

    subgraph DB[(skill_history.db)]
        EX[skill_executions]
        ST[skill_step_results]
    end

    subgraph VSCode[VSCode Extension]
        CC[CommandCenter]
        SEW[SkillExecutionWatcher]
    end

    SE -->|"record_*"| SHD
    SHD -->|WAL mode| DB
    SEW -->|"poll/MCP call"| SHD
    CC -->|Running/History tabs| SEW
```

### VSCode Extension UI

New tabbed interface in the Skills tab:

```
+------------------------------------------+
| [Running] [History] [Browse]              |  <-- Sub-tabs
+------------------------------------------+
| (Content based on selected sub-tab)       |
+------------------------------------------+
```

- **Running**: Currently executing skills with live progress
- **History**: Last 200 executions with filtering
- **Browse**: Existing skill browser (categories, detail view)

## Implementation Phases

### Phase 1: SQLite Database Module

Create `tool_modules/aa_workflow/src/skill_history_db.py`:

**Schema:**

```sql
-- Main executions table
CREATE TABLE skill_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT UNIQUE NOT NULL,
    skill_name TEXT NOT NULL,
    workspace_uri TEXT,
    session_id TEXT,
    session_name TEXT,
    source TEXT DEFAULT 'chat',        -- chat, cron, slack, api
    source_details TEXT,
    status TEXT NOT NULL,              -- running, success, failed
    inputs_json TEXT,                  -- JSON string of inputs
    outputs_json TEXT,                 -- JSON string of outputs
    start_time TEXT NOT NULL,          -- ISO8601
    end_time TEXT,                     -- ISO8601
    duration_ms INTEGER,
    success_count INTEGER DEFAULT 0,
    fail_count INTEGER DEFAULT 0,
    created_at REAL NOT NULL
);

-- Step results table (one-to-many)
CREATE TABLE skill_step_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT NOT NULL,
    step_index INTEGER NOT NULL,
    step_name TEXT NOT NULL,
    tool_name TEXT,
    success INTEGER NOT NULL,
    duration_ms INTEGER,
    result_preview TEXT,               -- First 2000 chars of output
    error TEXT,
    auto_healed INTEGER DEFAULT 0,
    heal_type TEXT,
    skipped INTEGER DEFAULT 0,
    FOREIGN KEY (execution_id) REFERENCES skill_executions(execution_id) ON DELETE CASCADE
);

-- Indexes for common queries
CREATE INDEX idx_executions_skill ON skill_executions(skill_name);
CREATE INDEX idx_executions_status ON skill_executions(status);
CREATE INDEX idx_executions_time ON skill_executions(start_time DESC);
CREATE INDEX idx_executions_source ON skill_executions(source);
CREATE INDEX idx_steps_execution ON skill_step_results(execution_id);
```

**Class Interface:**

```python
class SkillHistoryDB:
    """SQLite-based skill execution history with concurrency controls."""

    async def connect(self) -> None:
        """Initialize DB with WAL mode and busy timeout."""

    async def record_execution_start(
        self,
        execution_id: str,
        skill_name: str,
        inputs: dict,
        source: str = "chat",
        **kwargs
    ) -> None:
        """Record a new skill execution starting."""

    async def record_step_result(
        self,
        execution_id: str,
        step_index: int,
        step_name: str,
        tool_name: str | None,
        success: bool,
        duration_ms: int,
        result_preview: str | None = None,
        error: str | None = None,
        auto_healed: bool = False,
        heal_type: str | None = None,
        skipped: bool = False,
    ) -> None:
        """Record a step result."""

    async def record_execution_complete(
        self,
        execution_id: str,
        success: bool,
        duration_ms: int,
        outputs: dict | None = None,
        success_count: int = 0,
        fail_count: int = 0,
    ) -> None:
        """Mark execution as complete and trigger cleanup."""

    async def get_running_executions(self) -> list[dict]:
        """Get all currently running executions."""

    async def get_history(
        self,
        limit: int = 50,
        skill_name: str | None = None,
        status: str | None = None,
        source: str | None = None,
    ) -> list[dict]:
        """Query execution history with optional filters."""

    async def get_execution_detail(self, execution_id: str) -> dict | None:
        """Get full execution with all step results."""

    async def cleanup_old_records(self, max_records: int = 200) -> int:
        """Delete oldest records beyond limit. Returns count deleted."""

    async def get_stats(self) -> dict:
        """Get aggregate statistics by skill."""

    async def mark_stale_as_failed(self, stale_threshold_minutes: int = 30) -> int:
        """Mark stale running executions as failed. Returns count marked."""
```

**Concurrency Pattern:**

```python
def __init__(self, db_path: Path | None = None):
    self.db_path = db_path or SKILL_HISTORY_DB_FILE
    self._db: aiosqlite.Connection | None = None
    self._lock = asyncio.Lock()

async def connect(self):
    async with self._lock:
        if self._db is None:
            self._db = await aiosqlite.connect(self.db_path, timeout=30.0)
            self._db.row_factory = aiosqlite.Row
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA busy_timeout=30000")
            await self._create_tables()
```

### Phase 2: Skill Engine Integration

Modify `tool_modules/aa_workflow/src/skill_engine.py`:

1. **Import and initialize DB:**
   ```python
   from .skill_history_db import SkillHistoryDB, get_skill_history_db
   ```

2. **In `SkillExecutor.__init__()`:**
   - Get DB instance
   - Generate execution_id (already exists)

3. **In `SkillExecutor.execute()`:**
   - At start: `await db.record_execution_start(...)`
   - After each step: `await db.record_step_result(...)`
   - At complete: `await db.record_execution_complete(...)`

4. **Data capture enhancements:**
   - Capture `result_preview` (first 2000 chars of tool output)
   - Serialize `outputs_json` from context

### Phase 3: Deprecate JSON File

1. **Remove from `skill_execution_events.py`:**
   - Delete `SkillExecutionEmitter` class
   - Delete file locking utilities
   - Delete `EXECUTION_FILE` constant

2. **Update `scheduler.py`:**
   - Remove `_cleanup_skill_execution_state()` method
   - Use `db.mark_stale_as_failed()` instead

3. **Delete `cleanup_stale_executions.yaml` skill:**
   - No longer needed; DB handles cleanup automatically

4. **Update `server/paths.py`:**
   - Remove `SKILL_EXECUTION_FILE`
   - Add `SKILL_HISTORY_DB_FILE`

### Phase 4: MCP Tool for History Access

Add to `skill_engine.py`:

```python
@mcp.tool()
async def skill_history(
    limit: int = 50,
    skill_name: str | None = None,
    status: str | None = None,
    source: str | None = None,
    execution_id: str | None = None,
) -> str:
    """
    Query skill execution history.

    Args:
        limit: Maximum records to return (default 50, max 200)
        skill_name: Filter by skill name
        status: Filter by status (running, success, failed)
        source: Filter by source (chat, cron, slack, api)
        execution_id: Get specific execution with full details

    Returns:
        JSON string with execution history or detail
    """
    db = get_skill_history_db()

    if execution_id:
        result = await db.get_execution_detail(execution_id)
        return json.dumps(result, indent=2) if result else "Execution not found"

    results = await db.get_history(
        limit=min(limit, 200),
        skill_name=skill_name,
        status=status,
        source=source,
    )
    return json.dumps(results, indent=2)


@mcp.tool()
async def skill_running() -> str:
    """Get all currently running skill executions."""
    db = get_skill_history_db()
    results = await db.get_running_executions()
    return json.dumps(results, indent=2)
```

### Phase 5: VSCode Extension Updates

#### 5.1 Update `skillExecutionWatcher.ts`

Replace file watching with polling/MCP calls:

```typescript
export class SkillExecutionWatcher {
    private _pollInterval: NodeJS.Timeout | undefined;
    private _executions: Map<string, SkillExecutionState> = new Map();

    public start(): void {
        // Poll every 500ms for running executions
        this._pollInterval = setInterval(() => this._poll(), 500);
        this._poll(); // Initial check
    }

    private async _poll(): Promise<void> {
        try {
            // Call MCP tool to get running executions
            const result = await this._callMcpTool("skill_running", {});
            const executions = JSON.parse(result);
            this._processExecutions(executions);
        } catch (e) {
            console.error("[SkillWatcher] Poll error:", e);
        }
    }

    public async getHistory(
        limit: number = 50,
        filters?: { skill_name?: string; status?: string; source?: string }
    ): Promise<ExecutionSummary[]> {
        const result = await this._callMcpTool("skill_history", {
            limit,
            ...filters
        });
        return JSON.parse(result);
    }

    public async getExecutionDetail(executionId: string): Promise<SkillExecutionState | null> {
        const result = await this._callMcpTool("skill_history", {
            execution_id: executionId
        });
        return JSON.parse(result);
    }
}
```

#### 5.2 Update `commandCenter.ts`

Add sub-tabs to Skills tab:

```typescript
// State
private _skillsSubTab: 'running' | 'history' | 'browse' = 'browse';
private _skillHistory: ExecutionSummary[] = [];
private _historyFilters = { skill_name: '', status: '', source: '' };

// HTML for sub-tabs
private _getSkillsSubTabs(): string {
    return `
        <div class="skills-sub-tabs">
            <div class="view-toggle">
                <button class="toggle-btn ${this._skillsSubTab === 'running' ? 'active' : ''}"
                        data-action="setSkillsSubTab" data-value="running">
                    Running <span class="badge" id="runningCount">0</span>
                </button>
                <button class="toggle-btn ${this._skillsSubTab === 'history' ? 'active' : ''}"
                        data-action="setSkillsSubTab" data-value="history">
                    History
                </button>
                <button class="toggle-btn ${this._skillsSubTab === 'browse' ? 'active' : ''}"
                        data-action="setSkillsSubTab" data-value="browse">
                    Browse
                </button>
            </div>
        </div>
    `;
}

// History view
private _getHistoryView(): string {
    return `
        <div class="history-filters">
            <input type="text" placeholder="Filter by skill..." id="historySkillFilter">
            <select id="historyStatusFilter">
                <option value="">All statuses</option>
                <option value="success">Success</option>
                <option value="failed">Failed</option>
            </select>
            <select id="historySourceFilter">
                <option value="">All sources</option>
                <option value="chat">Chat</option>
                <option value="cron">Cron</option>
                <option value="slack">Slack</option>
            </select>
            <button class="btn btn-ghost btn-small" data-action="refreshHistory">🔄</button>
        </div>
        <div class="history-list" id="historyList">
            ${this._renderHistoryList()}
        </div>
    `;
}

private _renderHistoryList(): string {
    if (this._skillHistory.length === 0) {
        return '<div class="empty-state">No execution history</div>';
    }

    return this._skillHistory.map(exec => `
        <div class="history-item ${exec.status}" data-execution-id="${exec.executionId}">
            <div class="history-item-header">
                <span class="status-icon">${exec.status === 'success' ? '✅' : '❌'}</span>
                <span class="skill-name">${exec.skillName}</span>
                <span class="source-badge">${exec.source}</span>
                <span class="duration">${this._formatDuration(exec.duration_ms)}</span>
                <span class="time">${this._formatTime(exec.startTime)}</span>
            </div>
        </div>
    `).join('');
}
```

### Phase 6: Cleanup and Migration

1. **Delete deprecated files:**
   - `~/.config/aa-workflow/skill_execution.json` (runtime)
   - `skills/cleanup_stale_executions.yaml`
   - `.claude/commands/cleanup-stale-executions.md`
   - `.cursor/commands/cleanup-stale-executions.md`

2. **Update documentation:**
   - `docs/architecture/vscode-extension.md`
   - `docs/plans/vscode-extension-upgrades.md`

3. **Update cron config:**
   - Remove `cleanup_stale_executions` job if scheduled

## File Changes Summary

| File | Action | Description |
|------|--------|-------------|
| `server/paths.py` | Modify | Add `SKILL_HISTORY_DB_FILE`, remove `SKILL_EXECUTION_FILE` |
| `tool_modules/aa_workflow/src/skill_history_db.py` | **Create** | New SQLite database module |
| `tool_modules/aa_workflow/src/skill_engine.py` | Modify | Integrate DB recording, add MCP tools |
| `tool_modules/aa_workflow/src/skill_execution_events.py` | **Delete** | No longer needed |
| `tool_modules/aa_workflow/src/scheduler.py` | Modify | Remove JSON cleanup, use DB |
| `extensions/aa_workflow_vscode/src/skillExecutionWatcher.ts` | Modify | Replace file watching with MCP polling |
| `extensions/aa_workflow_vscode/src/commandCenter.ts` | Modify | Add sub-tabs, history view |
| `skills/cleanup_stale_executions.yaml` | **Delete** | DB handles cleanup |
| `.claude/commands/cleanup-stale-executions.md` | **Delete** | No longer needed |
| `.cursor/commands/cleanup-stale-executions.md` | **Delete** | No longer needed |

## Configuration

| Setting | Value | Notes |
|---------|-------|-------|
| Max history records | 200 | Oldest deleted on insert |
| Result preview length | 2000 chars | Truncated for storage |
| Stale threshold | 30 minutes | Running executions marked failed |
| Inactive threshold | 10 minutes | No events = stale |
| WAL mode | Enabled | Better concurrent access |
| Busy timeout | 30 seconds | Wait for locks |
| Poll interval | 500ms | VSCode extension polling |

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| SQLite file corruption | WAL mode + atomic writes + backups |
| Polling latency vs file watch | 500ms poll is acceptable; can add WebSocket later |
| Migration breaks running skills | Deploy during low-activity period |
| Extension MCP call failures | Graceful degradation, show cached data |
| Database grows too large | Automatic cleanup on each insert |

## Testing Plan

1. **Unit tests for `SkillHistoryDB`:**
   - CRUD operations
   - Concurrent access
   - Cleanup logic
   - Edge cases (empty DB, max records)

2. **Integration tests:**
   - Skill execution records correctly
   - Step results captured
   - VSCode extension displays data

3. **Manual testing:**
   - Run skills from chat, cron, slack
   - Verify history appears in UI
   - Test filtering and detail view
   - Verify stale detection works

## See Also

- [VSCode Extension Upgrades](./vscode-extension-upgrades.md)
- [Skill Engine Architecture](../architecture/skill-engine.md)
- [State Management](../architecture/state-management.md)
