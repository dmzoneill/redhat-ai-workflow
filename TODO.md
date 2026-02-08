# Technical Debt & Code Quality TODO

Generated: 2026-02-08
Source: Automated code smell audit across 250+ Python files

---

## Priority 1: Bugs (fix immediately)

### BUG-001: SessionDaemon._sync_recent_sessions undefined
- **File:** `services/session/daemon.py:1045`
- **Impact:** Runtime `AttributeError` crash after every system wake event
- **Details:** `on_system_wake()` calls `self._sync_recent_sessions()` which is never defined on `SessionDaemon`
- **Fix:** Implement the method or remove the call

### BUG-002: SQL injection in slop/database.py
- **File:** `services/slop/database.py:258`
- **Impact:** `order_by` parameter interpolated directly into SQL: `query += f" ORDER BY {order_by}"`
- **Details:** While it defaults to `"detected_at DESC"`, callers could pass arbitrary SQL
- **Fix:** Whitelist allowed column names, reject anything else

### BUG-003: Shallow copy of DEFAULT_KNOWLEDGE_SCHEMA
- **File:** `tool_modules/aa_workflow/src/knowledge_tools.py:865`
- **Impact:** `dict(DEFAULT_KNOWLEDGE_SCHEMA)` is a shallow copy - nested dicts/lists are shared references between all knowledge instances created this way
- **Fix:** Use `copy.deepcopy()` instead

---

## Priority 2: Security

### SEC-001: exec()/eval() with open/__import__ in compute engine
- **File:** `tool_modules/aa_workflow/src/skill_engine.py:1508-1536`
- **Impact:** `safe_globals` exposes `open` and `__import__` as builtins, enabling arbitrary file I/O and module loading from YAML skill definitions
- **Details:** Line 1168 also uses `eval()` with `safe_context` including `type`, `dir`, `vars`, `hasattr`, `getattr` which could be chained for introspection
- **Fix:** Assess risk and restrict. Remove `open` and `__import__` from safe_globals, use a whitelist of allowed modules

---

## Priority 3: Memory Leaks (HIGH severity)

### MEM-001: MeetingState.caption_buffer unbounded
- **File:** `tool_modules/aa_meet_bot/src/browser_controller.py:75`
- **Impact:** `caption_buffer: list[CaptionEntry]` grows unboundedly during meetings. 2-hour meeting at 1 caption/second = ~7200 entries
- **Fix:** Add max cap (e.g., 10000) and rotate old entries, or write to DB after threshold

### MEM-002: GoogleMeetController._instances crash leak
- **File:** `tool_modules/aa_meet_bot/src/browser_controller.py:125,152`
- **Impact:** Class-level `_instances: dict` holds all controller instances. If `close()` is never called (crash), references are retained permanently, preventing GC of controller + browser + page objects
- **Fix:** Use `weakref.WeakValueDictionary` for `_instances`, or add `__del__` / `atexit` handler

### MEM-003: SSO browser atexit async cleanup fragile
- **File:** `tool_modules/aa_sso/src/tools_basic.py:1067-1073`
- **Impact:** `_cleanup_browser_sync()` atexit handler attempts async cleanup in a possibly-closed event loop. If loop is closed, `loop.run_until_complete()` raises RuntimeError and browser process leaks
- **Fix:** Use synchronous approach (kill browser process by PID) instead of async cleanup in atexit

---

## Priority 4: God Classes & Functions (decompose)

### GOD-001: SkillExecutor class (~2500 lines, 40+ methods)
- **File:** `tool_modules/aa_workflow/src/skill_engine.py:475-2968`
- **Impact:** Single class handles templating, condition evaluation, compute execution, tool execution, auto-healing, error recovery, event emission, and output formatting
- **Fix:** Extract into sub-components:
  - `SkillTemplateEngine` (templating, Jinja2, regex fallback)
  - `SkillAutoHealer` (auto-fix, VPN connect, kube login, pattern matching)
  - `SkillEventBus` (unified file-based + WebSocket + toast notification emission)
  - `SkillComputeEngine` (exec/eval sandbox)
  - `SkillErrorRecovery` (interactive recovery, issue creation)

### GOD-002: SkillExecutor.execute() (~280 lines)
- **File:** `tool_modules/aa_workflow/src/skill_engine.py:2532-2811`
- **Impact:** Main execution loop with deeply nested tool/compute/description branching, dual event emission, and auto-heal logic
- **Fix:** Extract step processors: `_execute_tool_step()`, `_execute_compute_step()`, `_execute_description_step()`

### GOD-003: _session_start_impl() (~340 lines)
- **File:** `tool_modules/aa_workflow/src/session_tools.py:796-1138`
- **Impact:** Single function handles resume/create paths, workspace detection, persona loading, bootstrap context, export
- **Fix:** Split into `_resume_session()`, `_create_session()`, `_load_bootstrap_context()`, `_build_session_output()`

### GOD-004: SlackDaemon (3252 lines)
- **File:** `services/slack/daemon.py`
- **Impact:** Largest file in codebase. Combines Slack API, message processing, response generation, D-Bus interface, and lifecycle management
- **Fix:** Extract message processor, response builder, and approval workflow into separate classes

### GOD-005: SlackAgentDBusInterface (2758 lines)
- **File:** `services/slack/dbus.py`
- **Impact:** Combines D-Bus protocol, message history, formatting, and client into one file
- **Fix:** Split D-Bus interface from message formatting and history management

### GOD-006: SprintDaemon (2584 lines)
- **File:** `services/sprint/daemon.py`
- **Impact:** Single class handling sprint planning, execution, history, D-Bus, and workflow orchestration
- **Fix:** Extract sprint planner, issue executor, and history tracker

### GOD-007: _handle_tool_error() (~260 lines)
- **File:** `tool_modules/aa_workflow/src/skill_engine.py:2019-2277`
- **Impact:** Deeply nested (6+ levels) auto-heal logic
- **Fix:** Split by error handling strategy: `_handle_auto_heal()`, `_handle_continue()`, `_handle_fail()`

### GOD-008: init_scheduler() (128 lines)
- **File:** `server/main.py:305-432`
- **Impact:** Nested async callbacks, file-based logging, multiple error paths
- **Fix:** Extract `_create_notification_callback()`, `_create_poll_callback()`

---

## Priority 5: Code Duplication

### DUP-001: _check_known_issues_sync() + _format_known_issues() duplicated
- **Files:** `skill_engine.py:114-200` and `meta_tools.py:43-133`
- **Impact:** Identical functions in two files, will diverge over time
- **Fix:** Extract to shared module (e.g., `tool_modules/common/patterns.py`)

### DUP-002: AUTH_PATTERNS / NETWORK_PATTERNS duplicated in 5 files
- **Files:** `auto_heal_decorator.py:27-48`, `usage_pattern_classifier.py:67-87`, `debuggable.py:441-505`, `utils.py:826-838`, `skill_engine.py:700-704`
- **Impact:** Pattern lists diverge across files, bugs fixed in one place but not others
- **Fix:** Extract to `server/constants.py` and import everywhere

### DUP-003: Project detection duplicated
- **Files:** `session_tools.py:514-534` and `knowledge_tools.py:193-221`
- **Impact:** `_detect_project_from_cwd()` and `_detect_project_from_path()` implement nearly identical logic
- **Fix:** Extract to shared detection module

### DUP-004: Persona detection duplicated
- **Files:** `session_tools.py:537-547` and `knowledge_tools.py:247-260`
- **Impact:** `_get_current_persona()` identically implemented in both files
- **Fix:** Extract to shared module

### DUP-005: ConfigManager / StateManager structural duplication (~300 lines)
- **Files:** `server/state_manager.py` (471 lines) and `server/config_manager.py` (566 lines)
- **Impact:** Same debounced-file-write, mtime-check, file-locking, singleton pattern
- **Fix:** Extract generic `JsonFileManager` base class

### DUP-006: State-building code in daemon _handle_get_state() vs _write_state()
- **Files:** `services/meet/daemon.py:530-595 vs 749-821`, `services/cron/daemon.py:333-390 vs 503-570`
- **Impact:** ~70 lines of identical dict-building and countdown logic copy-pasted
- **Fix:** Extract shared `_build_state_dict()` method

### DUP-007: cluster_map / KUBECONFIG_MAP internal duplication
- **File:** `server/utils.py:850-864 vs 201-220`
- **Impact:** Same cluster mapping in two places within the same file
- **Fix:** Reuse `KUBECONFIG_MAP` or `get_cluster_short_name()`

### DUP-008: Event emission copy-paste pattern (~12 times)
- **File:** `tool_modules/aa_workflow/src/skill_engine.py` throughout
- **Impact:** Every lifecycle event emitted twice (file + WebSocket) with identical try/import/call/except pattern
- **Fix:** Create `SkillEventBus` abstraction that handles both channels

### DUP-009: Duplicate AdapterInfo class
- **Files:** `services/memory_abstraction/models.py:235` and `registry.py:46`
- **Impact:** Slightly different fields (registry version has `latency_class` and `is_fast`), creates confusion
- **Fix:** Consolidate to single definition

---

## Priority 6: Hardcoded Values

### HARD-001: User-specific absolute paths in source
- `tool_modules/aa_meet_bot/src/config.py:104` - `/home/daoneill/Documents/Identification/IMG_3249_.jpg`
- `tool_modules/aa_meet_bot/src/tts_engine.py:32,329` - `/home/daoneill/src/GPT-SoVITS`
- `scripts/get_slides_info.py:5` - `/home/daoneill/src/redhat-ai-workflow`
- `server/session_builder.py:27` - `Path.home() / "src" / "redhat-ai-workflow"`
- **Fix:** Use environment variables, config.json, or relative paths

### HARD-002: VPN script path hardcoded in 3 files
- `skill_engine.py:733`, `infra_tools.py:114`, `scheduler.py:845`
- Path: `~/src/redhatter/src/redhatter_vpn/vpn-connect`
- **Fix:** Single constant in config.json `paths.vpn_connect_script`

### HARD-003: Cluster URLs hardcoded
- `skill_engine.py:798-803` - OpenShift cluster URLs as inline dict
- **Fix:** Move to config.json `kubernetes.clusters`

### HARD-004: Namespace names hardcoded
- `session_tools.py:1826-1844` - `"tower-analytics-prod"`, `"tower-analytics-prod-billing"`
- **Fix:** Move to config.json

### HARD-005: GitLab project hardcoded
- `skill_engine.py:968` - `"automation-analytics/automation-analytics-backend"`
- **Fix:** Resolve from config or context

### HARD-006: Magic numbers throughout
- `skill_engine.py:2007` - `if len(data["failures"]) > 100` (log truncation)
- `skill_engine.py:2949` - `knowledge["learned_from_tasks"][-50:]` (learnings limit)
- `knowledge_tools.py:367` - `readme_content[:2000]` (README truncation)
- `session_tools.py:591` - `overview[:200]` (overview truncation)
- `server/main.py:233` - `if len(tools) > 128` (Cursor tool limit)
- `server/session_builder.py:39` - `len(text) // 4` (token estimation)
- **Fix:** Extract as named constants

### HARD-007: Sound file paths and display defaults
- `server/websocket_server.py:552-568` - `/usr/share/sounds/freedesktop/...`
- `server/utils.py:778` - `env["DISPLAY"] = ":0"`
- `server/config.py:165` - fallback UID `1000`
- **Fix:** Make configurable or use OS detection

---

## Priority 7: Error Handling

### ERR-001: 130+ silent except Exception: pass blocks
- **Worst offenders:**
  - `browser_controller.py` - 12 instances
  - `skill_engine.py` - 12 instances
  - `session_tools.py` - 11 instances
  - `chat_context.py` - 8 instances
  - `meet/daemon.py` - 5 instances
  - `session/daemon.py` - 3 instances
- **Fix:** At minimum add `logger.debug()` calls. For critical paths, catch specific exceptions

### ERR-002: Race condition in singleton creation
- **Files:** `services/base/ai_router.py:416-432`, `interface.py:462`, `discovery.py:52`
- **Impact:** Global `_router` created without locks; concurrent async tasks could create duplicates
- **Fix:** Add `threading.Lock()` around singleton creation

---

## Priority 8: Dead Code & Cleanup

### DEAD-001: No-op decorators and always-true functions
- `server/workspace_tools.py:122-151` - `workspace_aware` decorator does nothing
- `server/workspace_utils.py:234-248` - `is_tool_active_for_workspace()` always returns True
- **Fix:** Remove or add meaningful behavior

### DEAD-002: Unused functions in server/main.py
- `main.py:64-85` - `get_tool_module()` never called anywhere
- `main.py:32-45` - `get_available_modules()` / `is_valid_module()` just re-delegate
- `config.py:188-189` - `get_docker_auth` backward-compat alias
- **Fix:** Audit callers and remove

### DEAD-003: Debug instrumentation left in production
- `skill_engine.py:554-584` - Writes to `~/.config/aa-workflow/emitter_debug.log` on every skill execution
- **Fix:** Remove or gate behind DEBUG flag/env var

### DEAD-004: Empty TYPE_CHECKING block
- `meta_tools.py:36-37` - `if TYPE_CHECKING: pass`
- **Fix:** Remove

---

## Priority 9: Test Quality

### TEST-001: Non-test files in tests/ directory
- `tests/test_slack_export.py` - 0 asserts, real Slack API calls
- `tests/slack_test.py` - Real DM sending, 0 asserts
- `tests/integration_test.py` - Real filesystem I/O, no pytest tests
- **Fix:** Move to `scripts/` or convert to proper mocked tests

### TEST-002: Test files exceeding 1000 lines
- `test_skill_engine.py` - 5533 lines
- `test_workspace_state.py` - 4259 lines
- `test_session_tools.py` - 2888 lines
- `test_meta_tools.py` - 1935 lines
- `test_parsers.py` - 1668 lines
- `test_utils.py` - 1270 lines
- `test_scheduler.py` - 1247 lines
- **Fix:** Split into focused test modules (e.g., `test_skill_engine_template.py`, `test_skill_engine_compute.py`)

### TEST-003: time.sleep() in tests (flaky patterns)
- `test_usage_phase5_optimization.py:152` - `time.sleep(1.1)`
- `test_config_manager.py:184` - `time.sleep(2.5)`
- `test_state_manager.py:398` - `time.sleep(0.001)`
- `test_workspace_state.py:93` - `time.sleep(0.01)`
- Plus 5 more files
- **Fix:** Use mock clock, event-based waits, or mock `time.time()`

---

## Priority 10: Architecture Improvements

### ARCH-001: SkillExecutor.__init__ parameter count (14 params)
- **File:** `skill_engine.py:482-498`
- **Fix:** Use `SkillExecutorConfig` dataclass or builder pattern

### ARCH-002: sys.path manipulation at import time (5+ scripts)
- `scripts/health_check.py:37`, `scripts/validate_skills.py:23`, `scripts/context_injector.py:42-46`, `scripts/service_control.py:27`, `services/cron/daemon.py:43`
- **Fix:** Guard with `if __name__ == "__main__"` or use proper package installation

### ARCH-003: Import side effects in paths.py
- `server/paths.py:16` - `AA_CONFIG_DIR.mkdir()` creates directories on import
- **Fix:** Move to lazy `ensure_dirs()` function

### ARCH-004: Repeated imports inside SkillExecutor methods
- `import asyncio` appears 13 times in skill_engine.py (once at module level + 12 inside methods)
- `from pathlib import Path` and `from datetime import datetime` imported inside `__init__` despite module-level imports
- **Fix:** Use the module-level imports

### ARCH-005: Global mutable state across server/
- `websocket_server.py:685` - `_ws_server` module-level mutable
- `persona_loader.py:112,486` - `_discovered_modules`, `_loader`
- `workspace_state.py:81` - `_persona_tool_counts`
- `debuggable.py:35` - `TOOL_REGISTRY`
- `tool_discovery.py:119,428` - `TOOL_MANIFEST`, `_MODULE_PREFIXES`
- **Fix:** Wrap in registry classes or proper singletons with thread safety
