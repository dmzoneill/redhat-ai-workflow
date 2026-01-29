# Per-Workspace Context Implementation Plan

> **Goal:** Enable each Cursor chat/workspace to have independent state (project, persona, tools, issue) while sharing a single MCP server process.

## Problem Statement

Currently, all Cursor chats share global state in the MCP server:
- `_chat_state` in `chat_context.py` is a global dict
- `PersonaLoader.current_persona` is global
- Tool filtering/loading affects all chats

When you switch persona in one chat, it affects all other chats. When you set a project context, it's overwritten by the next chat that calls `session_start()`.

## Solution: Workspace-Keyed State

The MCP protocol provides `ctx.session.list_roots()` which returns the workspace path(s) open in Cursor. We can use this as a "workspace identifier" to key all state.

```
Workspace Path (from list_roots) → WorkspaceState
"/home/user/src/backend"        → {project: "backend", persona: "developer", ...}
"/home/user/src/workflow"       → {project: "workflow", persona: "devops", ...}
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  MCP Server                                                          │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  WorkspaceRegistry                                           │    │
│  │                                                              │    │
│  │  _workspaces: dict[str, WorkspaceState] = {                 │    │
│  │      "file:///home/user/src/backend": WorkspaceState(       │    │
│  │          workspace_uri="file:///home/user/src/backend",     │    │
│  │          project="automation-analytics-backend",             │    │
│  │          persona="developer",                                │    │
│  │          issue_key="AAP-12345",                              │    │
│  │          branch="AAP-12345-feature",                         │    │
│  │          active_tools={"git", "gitlab", "jira"},            │    │
│  │      ),                                                      │    │
│  │      "file:///home/user/src/workflow": WorkspaceState(      │    │
│  │          workspace_uri="file:///home/user/src/workflow",    │    │
│  │          project="redhat-ai-workflow",                       │    │
│  │          persona="devops",                                   │    │
│  │          issue_key=None,                                     │    │
│  │          branch="main",                                      │    │
│  │          active_tools={"k8s", "bonfire", "quay"},           │    │
│  │      ),                                                      │    │
│  │  }                                                           │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  Tool Call Flow:                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ 1. Tool receives Context (ctx)                                │   │
│  │ 2. workspace = await get_workspace_from_ctx(ctx)             │   │
│  │ 3. state = WorkspaceRegistry.get(workspace)                  │   │
│  │ 4. Check tool access: if tool not in state.active_tools      │   │
│  │    → Return "Tool not loaded for this workspace"             │   │
│  │ 5. Execute tool with workspace-specific context              │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  NPU Tool Filtering (per-workspace):                                 │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ 1. Get workspace state                                        │   │
│  │ 2. Get persona baseline tools for state.persona              │   │
│  │ 3. Run NPU classifier with workspace context                 │   │
│  │ 4. Cache result keyed by (workspace, message_hash)           │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

## Implementation Phases

### Phase 1: WorkspaceState Infrastructure

**Files to create/modify:**
- `server/workspace_state.py` (NEW) - WorkspaceState dataclass and registry
- `server/workspace_utils.py` (NEW) - Helper to get workspace from ctx

**WorkspaceState dataclass:**
```python
@dataclass
class WorkspaceState:
    workspace_uri: str
    project: str | None = None
    persona: str = "developer"
    issue_key: str | None = None
    branch: str | None = None
    active_tools: set[str] = field(default_factory=set)
    started_at: datetime | None = None

    # NPU filtering cache (per-workspace)
    tool_filter_cache: dict[str, list[str]] = field(default_factory=dict)
```

**WorkspaceRegistry:**
```python
class WorkspaceRegistry:
    _workspaces: dict[str, WorkspaceState] = {}

    @classmethod
    async def get_for_ctx(cls, ctx: Context) -> WorkspaceState:
        """Get or create workspace state from MCP context."""
        workspace_uri = await cls._get_workspace_uri(ctx)
        if workspace_uri not in cls._workspaces:
            cls._workspaces[workspace_uri] = WorkspaceState(workspace_uri)
            # Auto-detect project
            cls._workspaces[workspace_uri].project = _detect_project(workspace_uri)
        return cls._workspaces[workspace_uri]

    @classmethod
    async def _get_workspace_uri(cls, ctx: Context) -> str:
        """Extract workspace URI from MCP context."""
        try:
            roots = await ctx.session.list_roots()
            if roots and roots.roots:
                return str(roots.roots[0].uri)
        except Exception:
            pass
        return "default"
```

### Phase 2: Migrate chat_context.py

**Changes to `tool_modules/aa_workflow/src/chat_context.py`:**

1. Remove global `_chat_state` dict
2. Add `WorkspaceRegistry` integration
3. Update all functions to be workspace-aware:

```python
# Before (global state)
def get_chat_project() -> str:
    if _chat_state["project"]:
        return _chat_state["project"]
    return DEFAULT_PROJECT

# After (workspace state)
async def get_chat_project(ctx: Context) -> str:
    state = await WorkspaceRegistry.get_for_ctx(ctx)
    if state.project:
        return state.project
    return DEFAULT_PROJECT
```

**Note:** Functions become async because `list_roots()` is async.

### Phase 3: Migrate session_tools.py

**Changes to `tool_modules/aa_workflow/src/session_tools.py`:**

1. Update `session_start()` to use workspace state
2. Update `_load_chat_context()` to use workspace state
3. Store persona choice per-workspace

```python
async def _session_start_impl(ctx, agent: str = "", project: str = "") -> list[TextContent]:
    # Get workspace-specific state
    state = await WorkspaceRegistry.get_for_ctx(ctx)

    # Set project if provided
    if project:
        state.project = project

    # Load persona if provided (per-workspace!)
    if agent:
        state.persona = agent
        state.active_tools = _get_persona_tools(agent)

    # ... rest of implementation
```

### Phase 4: Migrate PersonaLoader

**Changes to `server/persona_loader.py`:**

1. Remove `self.current_persona` (global)
2. Store persona per-workspace in `WorkspaceState`
3. Update `switch_persona()` to be workspace-aware

```python
async def switch_persona(self, persona_name: str, ctx: Context) -> dict:
    # Get workspace state
    state = await WorkspaceRegistry.get_for_ctx(ctx)

    # Update workspace-specific persona
    state.persona = persona_name
    state.active_tools = set(config.get("tools", []))

    # Note: We still load all tools globally, but track which are "active"
    # per workspace for access control
```

### Phase 5: Tool Access Control

**Create decorator for workspace-aware tools:**

```python
# server/workspace_tools.py

def workspace_tool(required_modules: list[str] | None = None):
    """Decorator to enforce workspace-specific tool access."""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(ctx: Context, *args, **kwargs):
            state = await WorkspaceRegistry.get_for_ctx(ctx)

            # Check if tool's module is active for this workspace
            if required_modules:
                for module in required_modules:
                    if module not in state.active_tools:
                        return f"❌ {module} tools not loaded for this workspace.\n\nRun `persona_load('{_suggest_persona(module)}')` to enable."

            return await func(ctx, *args, **kwargs)
        return wrapper
    return decorator
```

**Usage:**
```python
@registry.tool()
@workspace_tool(required_modules=["k8s"])
async def kubectl_get_pods(ctx: Context, namespace: str) -> str:
    # Only runs if k8s is in workspace's active_tools
    ...
```

### Phase 6: NPU Tool Filtering Integration

**Changes to `server/usage_context_injector.py` and tool filtering:**

1. Make tool filtering workspace-aware
2. Cache NPU results per-workspace
3. Use workspace's persona as baseline

```python
class UsageContextInjector:
    async def get_filtered_tools(self, ctx: Context, message: str) -> list[str]:
        state = await WorkspaceRegistry.get_for_ctx(ctx)

        # Check cache (keyed by workspace + message hash)
        cache_key = f"{state.workspace_uri}:{hash(message)}"
        if cache_key in state.tool_filter_cache:
            return state.tool_filter_cache[cache_key]

        # Get persona baseline
        baseline_tools = _get_persona_baseline(state.persona)

        # Run NPU classification
        npu_tools = await self._npu_classify(message, state.persona)

        # Combine and cache
        result = baseline_tools | npu_tools
        state.tool_filter_cache[cache_key] = list(result)

        return result
```

### Phase 7: Update All Tool Callers

**Files that need ctx passed through:**

- `tool_modules/aa_workflow/src/chat_context.py` - All functions
- `tool_modules/aa_workflow/src/session_tools.py` - All functions
- `tool_modules/aa_workflow/src/knowledge_tools.py` - `_detect_project_from_path()`
- `tool_modules/aa_workflow/src/skill_engine.py` - Skill execution
- `server/persona_loader.py` - `switch_persona()`

## Migration Strategy

1. **Backward Compatibility:** Keep global fallback for tools that don't have ctx
2. **Gradual Migration:** Update tools one module at a time
3. **Testing:** Add tests for multi-workspace scenarios

## Testing Plan

1. **Unit Tests:**
   - `test_workspace_state.py` - WorkspaceState and Registry
   - `test_workspace_isolation.py` - State isolation between workspaces

2. **Integration Tests:**
   - Open two Cursor windows with different workspaces
   - Set different personas in each
   - Verify state isolation

3. **NPU Tests:**
   - Verify tool filtering respects workspace persona
   - Verify cache is workspace-scoped

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| `list_roots()` not available | Fallback to "default" workspace |
| Async function changes break callers | Gradual migration with compat shims |
| Memory growth with many workspaces | Add LRU eviction for inactive workspaces |
| NPU cache bloat | TTL-based cache expiration per workspace |

## Success Criteria

1. ✅ Each Cursor workspace maintains independent project context
2. ✅ Persona changes in one workspace don't affect others
3. ✅ Tool access respects workspace's active persona
4. ✅ NPU filtering uses workspace-specific persona baseline
5. ✅ `session_start()` shows correct project for each workspace
6. ✅ No regression in single-workspace usage

## Timeline Estimate

| Phase | Effort | Dependencies |
|-------|--------|--------------|
| Phase 1: Infrastructure | 2 hours | None |
| Phase 2: chat_context.py | 1 hour | Phase 1 |
| Phase 3: session_tools.py | 2 hours | Phase 2 |
| Phase 4: PersonaLoader | 2 hours | Phase 1 |
| Phase 5: Tool Access Control | 3 hours | Phase 4 |
| Phase 6: NPU Integration | 2 hours | Phase 5 |
| Phase 7: Update Callers | 3 hours | Phase 2-4 |
| Testing | 2 hours | All |

**Total: ~17 hours**

## Additional Backend Components to Update

Based on comprehensive code review, these additional components need workspace-awareness:

### 1. Memory Tools (`memory_tools.py`)

The memory system already has project-specific paths via `_resolve_memory_path()`:
- `state/current_work` → `memory/state/projects/<project>/current_work.yaml`

**Changes needed:**
- Pass `ctx` to memory tools to get workspace-specific project
- Update `PROJECT_SPECIFIC_KEYS` to use workspace state

### 2. Skill Engine (`skill_engine.py`)

The skill executor uses global config and context:
- `SkillExecutor.context` stores inputs and config
- Event emitter writes to global file

**Changes needed:**
- Add workspace URI to skill execution context
- Scope event emitter output per-workspace
- Pass workspace state to skill steps

### 3. NPU Tool Filter (`aa_ollama/src/tool_filter.py`)

The `HybridToolFilter` has:
- Global `_filter_instance` singleton
- Cache keyed by `(message, persona)` only

**Changes needed:**
- Add workspace_uri to cache key: `(workspace_uri, message, persona)`
- Pass workspace context to `enrich_context()`
- Update `context_enrichment.py` to use workspace state

### 4. Usage Pattern Learner (`usage_pattern_learner.py`)

The Layer 5 auto-heal system learns from tool failures:
- Patterns stored globally in `memory/learned/usage_patterns.yaml`
- No workspace context in pattern storage

**Changes needed:**
- Add workspace context to pattern extraction
- Consider per-project pattern storage for project-specific errors

### 5. Agent Stats (`agent_stats.py`)

Tracks session statistics:
- `start_session()`, `record_memory_read()`, etc.
- Stats stored globally

**Changes needed:**
- Track stats per-workspace for accurate reporting
- Update VS Code extension to show per-workspace stats

### 6. Scheduler (`scheduler.py`, `poll_engine.py`)

The cron scheduler runs skills on schedule:
- No workspace context for scheduled jobs
- Skills execute without workspace state

**Changes needed:**
- Add default workspace for scheduled jobs
- Or: Make scheduled jobs workspace-agnostic (global)

### 7. Knowledge Tools (`knowledge_tools.py`)

Project knowledge is stored per-project per-persona:
- `memory/knowledge/personas/<persona>/<project>.yaml`

**Changes needed:**
- Pass `ctx` to `_detect_project_from_path()`
- Use workspace state for project detection

## Component Dependency Graph

```
WorkspaceRegistry (NEW)
    ↓
┌───────────────────────────────────────────────────────────────┐
│                                                               │
│  chat_context.py ←──── session_tools.py                      │
│       ↓                      ↓                                │
│  memory_tools.py        persona_tools.py                     │
│       ↓                      ↓                                │
│  skill_engine.py ←───── PersonaLoader                        │
│       ↓                      ↓                                │
│  knowledge_tools.py     tool_filter.py (NPU)                 │
│       ↓                      ↓                                │
│  agent_stats.py         usage_pattern_learner.py             │
│       ↓                      ↓                                │
│  context_enrichment.py  skill_discovery.py                   │
│                                                               │
└───────────────────────────────────────────────────────────────┘
```

## Detailed Context Analysis

### Current Global State Issues

After comprehensive code review, here are ALL components using global state that need workspace-awareness:

#### 1. `chat_context.py` - Chat State (CRITICAL)

**Current global state:**
```python
_chat_state: dict = {
    "project": None,
    "started_at": None,
    "issue_key": None,
    "branch": None,
}
```

**Functions affected:**
- `get_chat_project()` - Returns global project
- `set_chat_project()` - Sets global project
- `get_chat_state()` - Returns global state
- `get_project_work_state_path()` - Uses global project

**Fix:** All functions need `ctx` parameter to get workspace-specific state.

#### 2. `persona_loader.py` - Persona State (CRITICAL)

**Current global state:**
```python
class PersonaLoader:
    current_persona: str = ""
    loaded_modules: set[str] = set()
    _tool_to_module: dict[str, str] = {}
```

**Functions affected:**
- `switch_persona()` - Sets global persona
- `_load_tool_module()` - Tracks globally

**Fix:** Store `current_persona` per-workspace in `WorkspaceState`.

#### 3. `knowledge_tools.py` - Project Detection (HIGH)

**Current global state:**
```python
def _detect_project_from_path(path: str | Path | None = None) -> str | None:
    # Uses Path.cwd() - global process state
    check_path = Path.cwd().resolve()
```

**Functions affected:**
- `_detect_project_from_path()` - Uses cwd
- `_get_current_persona()` - Uses global PersonaLoader
- `_knowledge_load_impl()` - Auto-detects project
- `_knowledge_scan_impl()` - Auto-detects project
- `_knowledge_query_impl()` - Auto-detects project
- `_knowledge_learn_impl()` - Auto-detects project

**Fix:** Pass `ctx` to all knowledge tools, use workspace state for project/persona.

#### 4. `memory_tools.py` - Memory Path Resolution (HIGH)

**Current global state:**
```python
PROJECT_SPECIFIC_KEYS = {"state/current_work"}

def _resolve_memory_path(key: str) -> Path:
    # Calls get_project_work_state_path() which uses global chat state
```

**Functions affected:**
- `_resolve_memory_path()` - Uses global project
- All memory tools that use project-specific paths

**Fix:** Pass `ctx` to memory tools, resolve paths using workspace project.

#### 5. `skill_engine.py` - Skill Execution Context (HIGH)

**Current global state:**
```python
class SkillExecutor:
    context: dict = {}  # Stores inputs, config
    # No workspace awareness
```

**Functions affected:**
- `SkillExecutor.__init__()` - No workspace context
- `_execute_step()` - No workspace context
- `_learn_from_error()` - Learns globally
- Event emitter writes to global file

**Fix:** Add `workspace_uri` to skill context, scope event output.

#### 6. `tool_filter.py` (NPU) - Tool Filtering (HIGH)

**Current global state:**
```python
_filter_instance: HybridToolFilter | None = None

class HybridToolFilter:
    cache: FilterCache  # Keyed by (message, persona) only
```

**Functions affected:**
- `get_filter()` - Returns global singleton
- `filter()` - Uses global cache
- `_npu_classify()` - No workspace context

**Fix:** Add workspace_uri to cache key, pass workspace to context enrichment.

#### 7. `context_enrichment.py` - Context Loading (MEDIUM)

**Current global state:**
```python
def load_memory_state() -> dict:
    # Reads from global memory/state/current_work.yaml
    current_work_path = memory_dir / "state" / "current_work.yaml"
```

**Functions affected:**
- `load_memory_state()` - Reads global state
- `run_semantic_search()` - Uses global project
- `enrich_context()` - Combines global state

**Fix:** Pass workspace context, read from workspace-specific memory paths.

#### 8. `skill_discovery.py` - Skill Detection (MEDIUM)

**Current global state:**
```python
_discovery: Optional[SkillToolDiscovery] = None

def get_skill_discovery() -> SkillToolDiscovery:
    # Global singleton
```

**Functions affected:**
- `discover_tools()` - Global cache
- `detect_skill()` - No workspace context

**Fix:** Skill discovery can remain global (skills are workspace-agnostic), but skill execution needs workspace context.

#### 9. `agent_stats.py` - Statistics Tracking (MEDIUM)

**Current global state:**
```python
class AgentStats:
    _instance: "AgentStats | None" = None  # Singleton
    _stats: dict  # Global stats
```

**Functions affected:**
- `record_tool_call()` - Records globally
- `record_skill_execution()` - Records globally
- `start_session()` - Global session

**Fix:** Add optional workspace parameter, track per-workspace stats in addition to global.

#### 10. `usage_pattern_learner.py` - Pattern Learning (LOW)

**Current global state:**
```python
# Patterns stored globally in memory/learned/usage_patterns.yaml
```

**Functions affected:**
- `learn_from_observation()` - Stores globally
- Pattern matching - No workspace context

**Fix:** Consider adding project context to patterns for project-specific errors.

### Context Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Tool Call with Context (ctx)                                            │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  1. Extract workspace from ctx.session.list_roots()              │    │
│  │     workspace_uri = "file:///home/user/src/backend"              │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                              ↓                                           │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  2. Get WorkspaceState from registry                             │    │
│  │     state = WorkspaceRegistry.get(workspace_uri)                 │    │
│  │     → project: "automation-analytics-backend"                    │    │
│  │     → persona: "developer"                                       │    │
│  │     → issue_key: "AAP-12345"                                     │    │
│  │     → branch: "AAP-12345-feature"                                │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                              ↓                                           │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  3. Use workspace state in tool execution                        │    │
│  │                                                                   │    │
│  │  Knowledge Tools:                                                 │    │
│  │    project = state.project  # Not Path.cwd()                     │    │
│  │    persona = state.persona  # Not PersonaLoader.current_persona  │    │
│  │                                                                   │    │
│  │  Memory Tools:                                                    │    │
│  │    path = memory/state/projects/{state.project}/current_work.yaml│    │
│  │                                                                   │    │
│  │  NPU Filter:                                                      │    │
│  │    cache_key = (state.workspace_uri, message, state.persona)     │    │
│  │    baseline = persona_baselines[state.persona]                   │    │
│  │                                                                   │    │
│  │  Skill Engine:                                                    │    │
│  │    context["workspace_uri"] = state.workspace_uri                │    │
│  │    context["project"] = state.project                            │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                              ↓                                           │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  4. Return result with workspace context                         │    │
│  │     - Stats recorded per-workspace                               │    │
│  │     - Patterns learned with project context                      │    │
│  │     - Events emitted with workspace tag                          │    │
│  └─────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
```

### Inference Engine Integration

The NPU/Ollama tool filtering system needs special attention:

**Current Flow:**
```
Message → HybridToolFilter.filter() → NPU classify → Return tools
                    ↓
            Uses global persona
            Uses global cache
```

**Required Flow:**
```
Message + ctx → HybridToolFilter.filter(ctx) → NPU classify → Return tools
                         ↓
                 Get workspace state
                 Use workspace persona
                 Use workspace-scoped cache
                 Enrich with workspace context
```

**Files to update:**
1. `tool_modules/aa_ollama/src/tool_filter.py`:
   - Add `ctx` parameter to `filter()` method
   - Update cache key to include workspace_uri
   - Pass workspace to `enrich_context()`

2. `tool_modules/aa_ollama/src/context_enrichment.py`:
   - Add `workspace_uri` parameter to `enrich_context()`
   - Load memory state from workspace-specific paths
   - Use workspace project for semantic search

3. `tool_modules/aa_workflow/src/meta_tools.py`:
   - Update `context_filter()` to pass ctx
   - Update `apply_tool_filter()` to pass ctx

## Updated Timeline

| Phase | Effort | Description | Files |
|-------|--------|-------------|-------|
| Phase 1: Infrastructure | 2h | WorkspaceState, WorkspaceRegistry | `server/workspace_state.py` (NEW), `server/workspace_utils.py` (NEW) |
| Phase 2: chat_context.py | 1h | Migrate to workspace state | `tool_modules/aa_workflow/src/chat_context.py` |
| Phase 3: session_tools.py | 2h | Workspace-aware session | `tool_modules/aa_workflow/src/session_tools.py` |
| Phase 4: PersonaLoader | 2h | Per-workspace persona | `server/persona_loader.py` |
| Phase 5: Tool Access Control | 3h | @workspace_tool decorator | `server/workspace_tools.py` (NEW) |
| Phase 6: NPU Integration | 3h | Workspace-scoped filtering | `tool_modules/aa_ollama/src/tool_filter.py`, `tool_modules/aa_ollama/src/context_enrichment.py` |
| Phase 7: Knowledge Tools | 2h | Workspace-aware knowledge | `tool_modules/aa_workflow/src/knowledge_tools.py` |
| Phase 8: Memory Tools | 2h | Workspace-aware memory | `tool_modules/aa_workflow/src/memory_tools.py` |
| Phase 9: Skill Engine | 2h | Workspace context in skills | `tool_modules/aa_workflow/src/skill_engine.py` |
| Phase 10: Agent Stats | 1h | Per-workspace stats | `tool_modules/aa_workflow/src/agent_stats.py` |
| Phase 11: Meta Tools | 1h | Update filter tools | `tool_modules/aa_workflow/src/meta_tools.py` |
| Phase 12: Persona Tools | 1h | Update persona tools | `tool_modules/aa_workflow/src/persona_tools.py` |
| Testing | 3h | Unit + integration tests | `tests/test_workspace_state.py` (NEW), `tests/test_workspace_isolation.py` (NEW) |

**Total: ~25 hours**

## Detailed File Changes

### Phase 1: Infrastructure (NEW FILES)

**`server/workspace_state.py`:**
```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context

@dataclass
class WorkspaceState:
    """State for a single workspace/chat."""
    workspace_uri: str
    project: str | None = None
    persona: str = "developer"
    issue_key: str | None = None
    branch: str | None = None
    active_tools: set[str] = field(default_factory=set)
    started_at: datetime | None = None
    tool_filter_cache: dict[str, list[str]] = field(default_factory=dict)

class WorkspaceRegistry:
    """Registry of workspace states."""
    _workspaces: dict[str, WorkspaceState] = {}

    @classmethod
    async def get_for_ctx(cls, ctx: "Context") -> WorkspaceState:
        """Get or create workspace state from MCP context."""
        workspace_uri = await cls._get_workspace_uri(ctx)
        if workspace_uri not in cls._workspaces:
            cls._workspaces[workspace_uri] = WorkspaceState(
                workspace_uri=workspace_uri,
                started_at=datetime.now(),
            )
            # Auto-detect project from workspace path
            cls._workspaces[workspace_uri].project = cls._detect_project(workspace_uri)
        return cls._workspaces[workspace_uri]

    @classmethod
    async def _get_workspace_uri(cls, ctx: "Context") -> str:
        """Extract workspace URI from MCP context."""
        try:
            roots = await ctx.session.list_roots()
            if roots and roots.roots:
                return str(roots.roots[0].uri)
        except Exception:
            pass
        return "default"

    @classmethod
    def _detect_project(cls, workspace_uri: str) -> str | None:
        """Detect project from workspace URI."""
        from server.utils import load_config
        from pathlib import Path

        config = load_config()
        if not config:
            return None

        # Convert file:// URI to path
        if workspace_uri.startswith("file://"):
            workspace_path = Path(workspace_uri[7:])
        else:
            workspace_path = Path(workspace_uri)

        repositories = config.get("repositories", {})
        for project_name, project_config in repositories.items():
            project_path = Path(project_config.get("path", "")).expanduser().resolve()
            try:
                workspace_path.resolve().relative_to(project_path)
                return project_name
            except ValueError:
                continue
        return None

    @classmethod
    def get_all(cls) -> dict[str, WorkspaceState]:
        """Get all workspace states (for VS Code extension export)."""
        return cls._workspaces.copy()

    @classmethod
    def clear(cls) -> None:
        """Clear all workspace states (for testing)."""
        cls._workspaces.clear()
```

**`server/workspace_utils.py`:**
```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context

from .workspace_state import WorkspaceRegistry, WorkspaceState

async def get_workspace_from_ctx(ctx: "Context") -> WorkspaceState:
    """Convenience function to get workspace state from context."""
    return await WorkspaceRegistry.get_for_ctx(ctx)

async def get_workspace_project(ctx: "Context") -> str:
    """Get the project for the current workspace."""
    state = await get_workspace_from_ctx(ctx)
    return state.project or "redhat-ai-workflow"

async def get_workspace_persona(ctx: "Context") -> str:
    """Get the persona for the current workspace."""
    state = await get_workspace_from_ctx(ctx)
    return state.persona
```

### Phase 6: NPU Integration Changes

**`tool_modules/aa_ollama/src/tool_filter.py` changes:**
```python
# Add ctx parameter to filter method
async def filter(
    self,
    message: str,
    persona: str = "developer",
    ctx: "Context | None" = None,  # NEW
) -> FilterResult:
    # Get workspace state if ctx provided
    workspace_uri = "default"
    if ctx:
        from server.workspace_utils import get_workspace_from_ctx
        state = await get_workspace_from_ctx(ctx)
        workspace_uri = state.workspace_uri
        persona = state.persona  # Use workspace persona

    # Update cache key to include workspace
    cache_key = f"{workspace_uri}:{persona}:{hash(message)}"

    # ... rest of implementation
```

**`tool_modules/aa_ollama/src/context_enrichment.py` changes:**
```python
def load_memory_state(workspace_uri: str | None = None, project: str | None = None) -> dict:
    """Load current work state from memory.

    Args:
        workspace_uri: Workspace URI for context
        project: Project name (uses workspace project if not provided)
    """
    # If project provided, use project-specific path
    if project:
        current_work_path = memory_dir / "state" / "projects" / project / "current_work.yaml"
    else:
        current_work_path = memory_dir / "state" / "current_work.yaml"

    # ... rest of implementation
```

## References

- [MCP Protocol - Roots](https://modelcontextprotocol.io/docs/concepts/roots)
- [FastMCP Context](https://github.com/jlowin/fastmcp)
- Current implementation: `tool_modules/aa_workflow/src/session_tools.py:_detect_project_from_mcp_roots()`
