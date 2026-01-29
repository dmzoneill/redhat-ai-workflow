# Code Cleanup Plan

> Auto-generated technical debt and code smell analysis.
> Organized by smell category for searchability and deduplication.

---

## Table of Contents

### Code Smell Categories
- [LARGE_CLASS](#large_class) (17 entries) *(+3 in iteration 12)*
- [LONG_METHOD](#long_method) (23 entries) *(+5 in iteration 12)*
- [MAGIC_LITERALS](#magic_literals) (46 entries) *(+9 in iteration 12)*
- [PRIMITIVE_OBSESSION](#primitive_obsession) (26 entries)
- [DUPLICATE_CODE](#duplicate_code) (57 entries) *(+4 in iteration 12)*
- [CONFIGURATION_SCATTERING](#configuration_scattering) (11 entries)
- [HARD_CODED_DEFAULTS](#hard_coded_defaults) (31 entries)
- [DEAD_CODE](#dead_code) (13 entries)
- [LONG_PARAMETER_LIST](#long_parameter_list) (8 entries)
- [FEATURE_ENVY](#feature_envy) (12 entries)
- [DATA_CLUMPS](#data_clumps) (53 entries)
- [INAPPROPRIATE_INTIMACY](#inappropriate_intimacy) (6 entries)
- [SPECULATIVE_GENERALITY](#speculative_generality) (13 entries)
- [SHOTGUN_SURGERY](#shotgun_surgery) (6 entries)
- [LACK_OF_CENTRALIZATION](#lack_of_centralization) (8 entries)
- [RACE_CONDITIONS](#race_conditions) (13 entries)
- [FILE_LOCKING_ISSUES](#file_locking_issues) (6 entries)
- [MEMORY_LEAKS](#memory_leaks) (10 entries) *(+3 in iteration 12)*
- [CIRCULAR_DEPENDENCIES](#circular_dependencies) (3 entries)
- [DIVERGENT_CHANGE](#divergent_change) (3 entries)
- [COMBINATORIAL_EXPLOSION](#combinatorial_explosion) (7 entries)

### Special Sections
- [WELL_DESIGNED CODE](#well-designed-code-positive-examples) (12 examples) *(+2 in iteration 12)*
- [GLOBAL SINGLETON ANALYSIS](#global-singleton-analysis)
- [server/ DIRECTORY ANALYSIS](#server-directory-analysis)
- [Priority Matrix](#updated-priority-matrix-iteration-10---final)
- [Final Summary](#comprehensive-final-summary)

### Quick Reference
| Severity | Count | Top Items |
|----------|-------|-----------|
| Critical | 6 | LC-002, LC-005, LC-006, LC-007, LC-013, DC-041 |
| High | 30+ | Singleton pattern, kubectl duplication, inline CSS/HTML |
| Medium | 85+ | Most categories, TypeScript webviews |
| Low | 40+ | Dead code, speculative generality |

---

## LARGE_CLASS

### LC-001: ClaudeAgent (scripts/claude_agent.py)
**Lines:** 1630-2002 (~370 lines)
**Severity:** High
**Description:** `ClaudeAgent` class handles too many responsibilities:
- Message processing
- Tool execution routing
- Conversation history management
- Context building
- Vertex AI / Anthropic client selection
**Refactor:** Extract `ConversationHistoryManager`, `ContextBuilder`, and `ClientFactory` classes.

### LC-002: ToolExecutor (scripts/claude_agent.py)
**Lines:** 724-1628 (~900 lines)
**Severity:** Critical
**Description:** Massive class with execute methods for every tool type (jira, gitlab, git, k8s, bonfire, quay, memory, slack, skill). Each _execute_* method is 50-200 lines.
**Refactor:** Split into separate executor classes per domain (JiraExecutor, GitLabExecutor, K8sExecutor, etc.) using Strategy pattern.

### LC-003: ToolRegistry (scripts/claude_agent.py)
**Lines:** 142-722 (~580 lines)
**Severity:** High
**Description:** `ToolRegistry._register_builtin_tools()` is a single massive method with 60+ tool definitions hardcoded inline.
**Refactor:** Move tool definitions to YAML/JSON config or use decorator-based registration like MCP tools.

### LC-004: SkillExecutor (tool_modules/aa_workflow/src/skill_engine.py)
**Lines:** 431-1000+ (~600+ lines)
**Severity:** High
**Description:** Handles skill execution, step processing, error recovery, event emission, context management, and safety guards all in one class.
**Refactor:** Extract `StepProcessor`, `ErrorRecoveryHandler`, `SkillEventEmitter` as separate classes.

### LC-005: WorkspaceState (server/workspace_state.py)
**Lines:** 1-2400+ (~2400 lines)
**Severity:** Critical
**Description:** File contains multiple large classes (WorkspaceState, ChatSession, WorkspaceRegistry) with persistence, caching, and session management all intertwined.
**Refactor:** Split into separate modules: `session.py`, `registry.py`, `persistence.py`.

---

## LONG_METHOD

### LM-001: _default_system_prompt (scripts/claude_agent.py)
**Lines:** 1733-1784 (~50 lines)
**Severity:** Medium
**Description:** System prompt is a massive multiline string literal inside a method.
**Refactor:** Move to external file `prompts/slack_agent.md` and load at init.

### LM-002: _build_context_message (scripts/claude_agent.py)
**Lines:** 1785-1877 (~90 lines)
**Severity:** Medium
**Description:** Complex context building with many nested conditionals.
**Refactor:** Break into smaller methods: `_build_tone_context`, `_build_resolver_context`, `_build_enrichment_context`.

### LM-003: init_scheduler (server/main.py)
**Lines:** 316-440 (~125 lines)
**Severity:** Medium
**Description:** Does too much: config loading, notification engine init, scheduler init, poll engine init, callback creation.
**Refactor:** Create `SchedulerFactory` that composes these components.

### LM-004: create_mcp_server (server/main.py)
**Lines:** 218-310 (~90 lines)
**Severity:** Medium
**Description:** Module loading, persona initialization, workspace restoration all in one function.
**Refactor:** Extract `load_tool_modules()`, `init_persona_loader()`, `restore_sessions()`.

### LM-005: switch_persona (server/persona_loader.py)
**Lines:** 242-353 (~110 lines)
**Severity:** Medium
**Description:** Clears tools, loads new tools, updates workspace, sends notifications - too many concerns.
**Refactor:** Apply Command pattern with distinct phases.

---

## MAGIC_LITERALS

### ML-001: Timeout values scattered
**Files:** Multiple
**Examples:**
- `timeout=30` (jira tools)
- `timeout=60` (kubectl)
- `timeout=300` (bonfire)
- `timeout=900` (deploy_aa)
- `timeout=600` (namespace reserve)
**Refactor:** Create `constants.py` with `TIMEOUT_SHORT`, `TIMEOUT_MEDIUM`, `TIMEOUT_LONG`, `TIMEOUT_DEPLOY`.

### ML-002: SHA length validation
**Files:** `claude_agent.py:1199-1201`, `tools_basic.py:236-244`
**Examples:**
- `if len(template_ref) != 40:`
- `if len(digest) != 64:`
**Refactor:** Define `GIT_SHA_LENGTH = 40`, `SHA256_DIGEST_LENGTH = 64` in constants.

### ML-003: Tool limits
**File:** `server/main.py:244`
**Example:** `if len(tools) > 128:`
**Refactor:** Define `MAX_CURSOR_TOOLS = 128` in config.

### ML-004: Message truncation lengths
**File:** `server/utils.py:22-47`
**Examples:** `max_length: int = 5000`
**Refactor:** Add to config: `OUTPUT_TRUNCATE_LENGTH`.

### ML-005: Conversation history limits
**File:** `scripts/claude_agent.py:1701-1702`
**Examples:** `self._max_history: int = 10`, `self._history_ttl: int = 3600`
**Refactor:** Move to config or class constants.

### ML-006: Memory limits
**File:** `scripts/common/memory.py:1280`
**Example:** `data["tool_fixes"] = data["tool_fixes"][-100:]`
**Refactor:** Define `MAX_TOOL_FIXES = 100` constant.

---

## PRIMITIVE_OBSESSION

### PO-001: Environment strings
**Files:** Multiple (`utils.py`, `tools_basic.py`, `claude_agent.py`)
**Description:** Environment passed as raw strings ("stage", "prod", "ephemeral") with ad-hoc normalization.
**Example:** `if env_key == "prod": env_key = "production"`
**Refactor:** Create `Environment` enum: `class Environment(Enum): STAGE = "stage"; PROD = "production"; ...`

### PO-002: Issue keys as strings
**Files:** Jira tools, skills, memory
**Description:** Issue keys like "AAP-12345" passed as raw strings without validation.
**Refactor:** Create `IssueKey` value object with validation: `IssueKey.parse("AAP-12345")`.

### PO-003: MR identifiers
**Files:** `claude_agent.py`, gitlab tools
**Description:** MR IDs passed as strings, ints, or embedded in URLs inconsistently.
**Refactor:** Create `MergeRequestRef` class that normalizes from URL, ID, or iid.

### PO-004: Duration strings
**Files:** Bonfire tools
**Examples:** `duration: str = "1h"`, `duration: str = "2h"`
**Refactor:** Create `Duration` value object or use `timedelta` with parser.

### PO-005: Priority as string
**File:** `scripts/common/memory.py:519`
**Example:** `priority: str = "medium"`
**Refactor:** Create `Priority` enum: `class Priority(Enum): LOW = "low"; MEDIUM = "medium"; HIGH = "high"; CRITICAL = "critical"`

---

## DUPLICATE_CODE

### DC-001: run_cmd implementations
**Files:** `server/utils.py`, `scripts/claude_agent.py:797-830`
**Description:** Both implement command execution with shell sourcing, env setup, timeout handling.
**Refactor:** Use `server/utils.run_cmd` everywhere; remove duplicate in claude_agent.py.

### DC-002: Known issues checking
**Files:** `skill_engine.py:87-151`, `scripts/common/memory.py:1119-1207`
**Description:** Two implementations of `_check_known_issues_sync` with same logic.
**Refactor:** Single implementation in `memory.py`, import in skill_engine.

### DC-003: KUBECONFIG_MAP
**Files:** `server/utils.py:202-221`, `scripts/claude_agent.py:1086-1100`
**Description:** Duplicated environment to kubeconfig suffix mapping.
**Refactor:** Single source in `server/utils.py`.

### DC-004: Tool registration patterns
**Files:** All `tools_basic.py` files
**Description:** Every tool file has nearly identical `register_tools(server)` boilerplate.
**Refactor:** Base class or decorator that handles registration.

### DC-005: YAML file operations
**Files:** `scripts/common/memory.py`, skill engine, persona loader
**Description:** Repeated patterns: read YAML, modify, write with locking.
**Refactor:** Create `YAMLDocument` class with atomic read/modify/write.

### DC-006: Markdown to Jira conversion
**File:** `tools_basic.py:72-91`
**Description:** Converter function loaded inline with fallback.
**Refactor:** Move to `scripts/common/jira_utils.py` with proper import handling.

---

## CONFIGURATION_SCATTERING

### CS-001: Path configuration
**Files:** `server/config.py`, `server/utils.py`, `memory.py`
**Description:** Paths defined in multiple places:
- `MEMORY_DIR = Path.home() / "src/redhat-ai-workflow/memory"` (hardcoded!)
- `_get_kube_base()` reads from config.json
- Various `PROJECT_ROOT` definitions
**Refactor:** Single `paths.py` module with all path resolution.

### CS-002: Timeouts
**Files:** All tool modules
**Description:** Timeout values scattered across tool implementations.
**Refactor:** Centralize in `config.json` under `timeouts` section.

### CS-003: Tool module discovery
**Files:** `server/main.py`, `server/persona_loader.py`
**Description:** Duplicated `TOOL_MODULES_DIR`, `TOOLS_FILE`, constants.
**Refactor:** Single `tool_discovery.py` module.

### CS-004: Jira URL
**Files:** `tools_basic.py:25-28`, various
**Description:** `_get_jira_url()` called multiple times, reads config each time.
**Refactor:** Cache at module level or use ConfigManager.

---

## HARD_CODED_DEFAULTS

### HD-001: MEMORY_DIR path
**File:** `scripts/common/memory.py:38`
**Code:** `MEMORY_DIR = Path.home() / "src/redhat-ai-workflow/memory"`
**Problem:** Hardcoded path assumes specific directory structure.
**Refactor:** Load from config.json or env var `AA_MEMORY_DIR`.

### HD-002: Default project
**File:** `server/workspace_state.py:50`
**Code:** `DEFAULT_PROJECT = "redhat-ai-workflow"`
**Problem:** Hardcoded project name.
**Refactor:** Load from config.json.

### HD-003: Image base URLs
**File:** `tools_basic.py:81-84`
**Code:** `"quay.io/redhat-user-workloads/aap-aa-tenant/..."`
**Problem:** Hardcoded Quay repository path.
**Refactor:** Fully configurable in config.json.

### HD-004: Protected branches
**File:** `skill_engine.py:192`
**Code:** `PROTECTED_BRANCHES = {"main", "master", "develop", "production", "staging"}`
**Problem:** Hardcoded protected branch names.
**Refactor:** Move to config.json per-project settings.

### HD-005: Default pool
**File:** `tools_basic.py:491`
**Code:** `pool: str = "default"`
**Problem:** Hardcoded namespace pool.
**Refactor:** Load from config.json.

---

## DEAD_CODE

### DD-001: Unused imports
**Files:** Multiple
**Examples:**
- `from typing import cast` imported but not always used
- `TYPE_CHECKING` imports with unused type hints
**Action:** Run `ruff check --select F401` and remove.

### DD-002: Deprecated functions
**File:** `server/utils.py:797-806`
**Code:** `async def run_cmd_shell(...)` marked as DEPRECATED
**Action:** Migrate callers to `run_cmd_full()`, then remove.

### DD-003: Commented code blocks
**Files:** Various
**Action:** Search for `# TODO`, `# REMOVED`, `# OLD` and clean up.

### DD-004: Unused tool implementations
**File:** `claude_agent.py`
**Description:** Some `_impl` functions may not be called if tool registry changed.
**Action:** Audit tool coverage.

---

## LONG_PARAMETER_LIST

### LP-001: jira_create_issue
**File:** `tools_basic.py:279-331`
**Parameters:** 12 parameters
**Refactor:** Create `CreateIssueRequest` dataclass.

### LP-002: SkillExecutor.__init__
**File:** `skill_engine.py:438-470`
**Parameters:** 16 parameters
**Refactor:** Create `SkillConfig` and `SessionContext` dataclasses.

### LP-003: bonfire_deploy
**File:** `tools_basic.py:580-627`
**Parameters:** 12 parameters
**Refactor:** Create `DeployConfig` dataclass.

### LP-004: add_discovered_work
**File:** `scripts/common/memory.py:509-581`
**Parameters:** 10 parameters
**Refactor:** Create `DiscoveredWork` dataclass.

---

## FEATURE_ENVY

### FE-001: ToolExecutor accessing resolver internals
**File:** `scripts/claude_agent.py:847-895`
**Description:** `_resolve_gitlab_context` deeply accesses `self.resolver` internals.
**Refactor:** Let `ContextResolver` return a complete context object.

### FE-002: PersonaLoader manipulating server internals
**File:** `server/persona_loader.py:185`
**Code:** `self.server._tool_manager._tools.values()`
**Description:** Accessing private `_tool_manager` attribute.
**Refactor:** FastMCP should expose public API for tool enumeration.

---

## DATA_CLUMPS

### DC-001: GitLab context tuple
**File:** `scripts/claude_agent.py:847-895`
**Description:** `project`, `mr_id`, `run_cwd`, `use_repo_flag` always passed together.
**Refactor:** Create `GitLabContext` dataclass.

### DC-002: Issue fields
**File:** `scripts/common/memory.py:402-437`
**Description:** `issue_key`, `summary`, `status`, `branch`, `repo`, `notes` always grouped.
**Refactor:** Already somewhat addressed, but formalize `ActiveIssue` dataclass.

### DC-003: Deploy parameters
**Files:** Bonfire tools
**Description:** `namespace`, `template_ref`, `image_tag`, `billing` always passed together.
**Refactor:** Create `DeploymentSpec` dataclass.

---

## INAPPROPRIATE_INTIMACY

### II-001: skill_engine accessing server._tool_manager
**File:** Skill engine, persona loader
**Description:** Multiple files access FastMCP internals.
**Refactor:** Add proper public API methods to FastMCP wrapper.

### II-002: Memory accessing config internals
**File:** `scripts/common/memory.py:61-78`
**Description:** Direct JSON parsing of config.json instead of using ConfigManager.
**Refactor:** Import and use `server.utils.load_config`.

---

## SPECULATIVE_GENERALITY

### SG-001: Unused create_issue_fn parameter
**File:** `skill_engine.py:443`
**Description:** `create_issue_fn` parameter in SkillExecutor but rarely used.
**Action:** Remove if not used, or document use case.

### SG-002: Excessive environment aliases
**File:** `server/utils.py:202-221`
**Description:** Many aliases for same environment (e.g., "s", "stage", "stg").
**Action:** Reduce to canonical names only.

---

## SHOTGUN_SURGERY

### SS-001: Adding a new environment
**Files affected:** `utils.py`, `claude_agent.py`, `config.json`, potentially tool files
**Description:** Adding new environment requires changes in multiple places.
**Refactor:** Single environment registry in config.json.

### SS-002: Adding a new tool
**Files affected:** Tool module, persona YAML, potentially claude_agent.py ToolRegistry
**Description:** New tools require changes in multiple locations.
**Refactor:** Single registration point with auto-discovery.

---

## LACK_OF_CENTRALIZATION

### LC-001: Error formatting
**Files:** Every tool file has its own error formatting
**Examples:** `f"❌ Failed: {output}"`, `f"❌ {message}"`
**Refactor:** Use `server/utils.format_error` consistently everywhere.

### LC-002: Success formatting
**Files:** Every tool file
**Examples:** `f"✅ Done"`, `f"✅ {message}"`
**Refactor:** Use `server/utils.format_success` consistently.

---

## RACE_CONDITIONS

### RC-001: Session ID generation
**File:** `server/workspace_state.py`
**Description:** UUID generation for session IDs is safe, but session lookup and creation may race.
**Mitigation:** Add locking around session creation.

### RC-002: Config file writes
**File:** `server/config_manager.py`
**Description:** Multiple processes could write config.json simultaneously.
**Mitigation:** Use file locking for config writes.

---

## FILE_LOCKING_ISSUES

### FL-001: Memory file operations
**File:** `scripts/common/memory.py`
**Status:** Good - uses `fcntl.flock()` for atomic operations.
**Note:** Linux-only; Windows compatibility would need `msvcrt`.

### FL-002: Config file not locked
**File:** `server/config_manager.py`
**Issue:** No locking on config.json read/write.
**Refactor:** Add file locking for write operations.

---

## MEMORY_LEAKS

### ML-001: Conversation history growth
**File:** `scripts/claude_agent.py:1699-1731`
**Description:** `_conversations` dict grows unbounded except for TTL cleanup.
**Current mitigation:** TTL cleanup exists but only runs on access.
**Refactor:** Add periodic cleanup task or use LRU cache.

### ML-002: Session accumulation
**File:** `server/workspace_state.py`
**Description:** Sessions persist indefinitely in memory.
**Refactor:** Add session expiry and cleanup.

---

## CIRCULAR_DEPENDENCIES

### CD-001: server ↔ tool_modules
**Description:** Tool modules import from `server/` while `server/main.py` imports from `tool_modules/`.
**Current mitigation:** Deferred imports, but fragile.
**Refactor:** Cleaner dependency injection or event-based communication.

### CD-002: skill_engine imports
**File:** `skill_engine.py:31-35`
**Code:** Fallback imports with try/except for circular dependency handling.
**Refactor:** Restructure module hierarchy.

---

## Priority Matrix

| Severity | Count | Categories |
|----------|-------|------------|
| Critical | 2 | LARGE_CLASS (LC-002, LC-005) |
| High | 5 | LARGE_CLASS, LONG_METHOD, DUPLICATE_CODE |
| Medium | 15+ | Most other categories |
| Low | 10+ | DEAD_CODE, SPECULATIVE_GENERALITY |

## Recommended Order of Attack

1. **Quick Wins (1-2 hours each)**
   - ML-001 through ML-006: Extract magic literals to constants
   - DD-001: Remove unused imports
   - LC-001: Centralize error/success formatting

2. **Medium Effort (1-2 days each)**
   - DC-001: Consolidate run_cmd implementations
   - CS-001: Create central paths.py
   - HD-001: Make MEMORY_DIR configurable

3. **Large Refactors (1 week each)**
   - LC-002: Split ToolExecutor into domain-specific executors
   - LC-003: Move tool definitions to config
   - LC-005: Split workspace_state.py into modules

---

## DIVERGENT_CHANGE

### DV-001: tools_basic.py files have different patterns
**Files:** All `tool_modules/*/src/tools_basic.py`
**Description:** Each tool file follows slightly different patterns:
- Some use `_impl` suffix for implementations, others don't
- Some group tools into `_register_*_tools()` functions, others don't
- Some have inline docstrings, others reference impl docstrings
**Refactor:** Create template/code generator for consistent tool module structure.

### DV-002: Config loading patterns vary
**Files:** All tool modules
**Description:** Different approaches to loading config:
- `_get_slack_config()` reads config each call
- `get_app_config()` has complex fallback logic
- Some cache results, some don't
**Refactor:** Use `ConfigManager` consistently everywhere with proper caching.

---

## COMBINATORIAL_EXPLOSION

### CE-001: Environment handling
**Files:** `utils.py`, `tools_basic.py` (k8s, bonfire)
**Description:** Every environment (stage, prod, ephemeral, konflux, appsre) handled with separate if/else branches.
**Refactor:** Create `Environment` class with polymorphic behavior.

### CE-002: Message target resolution
**File:** `tool_modules/aa_slack/src/tools_basic.py:350-450`
**Description:** Complex if/elif tree handling `@username`, `#channel`, `U...`, `D...`, `C...` targets.
**Refactor:** Create `SlackTarget` class with factory method `SlackTarget.parse(target)`.

### CE-003: Output format handling
**File:** `tool_modules/aa_gitlab/src/tools_basic.py:177-186`
**Description:** State to CLI flag mapping: `if state == "closed": args.append("--closed")` repeated.
**Refactor:** Create lookup dict or enum with flag mapping.

---

## Additional LARGE_CLASS entries

### LC-006: tools_basic.py (aa_meet_bot)
**Lines:** 1-2134 (2134 lines!)
**Severity:** Critical
**Description:** Single file with 50+ tool implementations covering:
- Meeting bot core
- Device management
- Notes bot
- Scheduler
- Voice pipeline
- Cleanup utilities
**Refactor:** Split into separate files: `meet_core.py`, `notes_bot.py`, `scheduler.py`, `voice_pipeline.py`.

### LC-007: commandCenter.ts
**Lines:** 1-2000+ lines
**Severity:** Critical
**Description:** Single TypeScript file handling:
- Panel rendering
- File watchers
- D-Bus communication
- State management
- All 5+ tabs content generation
**Refactor:** Extract per-tab renderers, create `StateManager`, `DBusClient`, `PanelRenderer` classes.

---

## Additional LONG_METHOD entries

### LM-006: _meet_notes_export_state_impl
**File:** `tool_modules/aa_meet_bot/src/tools_basic.py:1369-1538`
**Lines:** ~170 lines
**Severity:** High
**Description:** Single method doing:
- Database queries
- Google Calendar API calls
- State aggregation
- JSON file writing
**Refactor:** Break into `_get_calendar_events()`, `_aggregate_meeting_state()`, `_write_state_file()`.

### LM-007: _meet_notes_join_now_impl
**File:** `tool_modules/aa_meet_bot/src/tools_basic.py:880-924`
**Lines:** ~45 lines
**Severity:** Medium
**Description:** Mixes validation, duration calculation, and join logic.
**Refactor:** Extract `_validate_join_params()`, `_calculate_end_time()`.

### LM-008: run_cmd (utils.py)
**File:** `server/utils.py:477-570`
**Lines:** ~95 lines
**Severity:** Medium
**Description:** Complex command execution with shell sourcing, env setup, timeout handling, cwd handling.
**Refactor:** Split into `_build_shell_command()`, `_execute_with_timeout()`.

---

## Additional MAGIC_LITERALS entries

### ML-007: Buffer/limit sizes
**Files:** Multiple
**Examples:**
- `last_n: int = 20` (captions)
- `[-30:]` (captions buffer slice)
- `[:50]` (captions limit)
- `limit: int = 20` (commits)
- `max_results: int = 20` (jira search)
**Refactor:** Create `BUFFER_LIMITS` config section.

### ML-008: Image dimension thresholds
**File:** `tool_modules/aa_meet_bot/src/tools_basic.py:407-417`
**Examples:**
- `if width >= 256 and height >= 256:`
- `if 0.8 <= aspect <= 1.2:`
**Refactor:** Define `MIN_AVATAR_SIZE = 256`, `ASPECT_RATIO_TOLERANCE = 0.2`.

### ML-009: Hung instance thresholds
**File:** `tool_modules/aa_meet_bot/src/tools_basic.py:1063-1066`
**Examples:**
- `if inactive_minutes > 30:` (possibly hung)
- `if inactive_minutes > 60:` (likely hung)
**Refactor:** Define `HUNG_INSTANCE_THRESHOLD_MINUTES = 30`, `LIKELY_HUNG_THRESHOLD = 60`.

---

## Additional DUPLICATE_CODE entries

### DC-007: Global state singletons pattern
**Files:** Multiple tool modules
**Examples:**
```python
_controller: Optional[GoogleMeetController] = None
async def _get_controller():
    global _controller
    if _controller is None:
        _controller = GoogleMeetController()
    return _controller
```
**Description:** This singleton pattern is duplicated for 6+ global objects in meet_bot alone.
**Refactor:** Create `SingletonProvider` generic class or use proper dependency injection.

### DC-008: JSON response formatting
**Files:** `aa_slack/src/tools_basic.py`
**Description:** Repeated `json.dumps({ ... }, indent=2)` pattern with similar structure.
**Refactor:** Create `SlackResponse.success()`, `SlackResponse.error()` helper classes.

### DC-009: State export to JSON pattern
**Files:** `meet_bot/tools_basic.py:1530-1537`, memory tools, workspace state
**Description:** Repeated pattern: create dir if not exists, open file, json.dump.
**Refactor:** Create `StateExporter.export_to_file(path, state)` utility.

### DC-010: D-Bus/HTTP fallback pattern
**File:** `aa_slack/src/tools_basic.py:534-558`
**Description:** `_query_knowledge_cache` tries D-Bus, then HTTP, then config fallback.
**Refactor:** Create `CacheQueryStrategy` with pluggable backends.

---

## Additional HARD_CODED_DEFAULTS entries

### HD-006: Meet bot paths
**File:** `extensions/aa_workflow_vscode/src/commandCenter.ts:47-79`
**Examples:**
- `STATS_FILE = path.join(os.homedir(), ".config", "aa-workflow", "agent_stats.json")`
- `CONFIG_FILE = path.join(os.homedir(), "src", "redhat-ai-workflow", "config.json")`
**Problem:** Assumes specific paths on user's system.
**Refactor:** Read from config or environment.

### HD-007: D-Bus service definitions
**File:** `extensions/aa_workflow_vscode/src/commandCenter.ts:82-138`
**Description:** Service names, paths, interfaces all hardcoded inline.
**Refactor:** Move to extension configuration.

### HD-008: State file locations
**File:** `tool_modules/aa_meet_bot/src/tools_basic.py:1531`
**Code:** `state_dir = Path.home() / ".local" / "share" / "meet_bot"`
**Problem:** Hardcoded XDG path.
**Refactor:** Use `XDG_DATA_HOME` env var with fallback.

---

## Additional PRIMITIVE_OBSESSION entries

### PO-006: Skill execution status
**Files:** `commandCenter.ts:235`, skill engine
**Description:** Status as strings: "idle", "running", "success", "failed", "pending", "skipped".
**Refactor:** Create `ExecutionStatus` enum.

### PO-007: Bot mode
**Files:** meet_bot tools
**Examples:** `bot_mode="notes"`, `mode="notes"`
**Refactor:** Create `BotMode` enum: `NOTES`, `INTERACTIVE`, `PASSIVE`.

### PO-008: Notification types
**File:** `aa_slack/src/tools_basic.py:160-167`
**Examples:** `notification_type == "feedback"`, `"approval"`, `"info"`
**Refactor:** Create `NotificationType` enum.

---

## Additional FEATURE_ENVY entries

### FE-003: Slack tools accessing manager session internals
**File:** `aa_slack/src/tools_basic.py:173, 199, 229`
**Description:** Tools directly call `manager.session.send_dm()`, `manager.session.get_user_info()`.
**Refactor:** Let manager expose higher-level methods.

### FE-004: Meet bot accessing controller state
**File:** `tool_modules/aa_meet_bot/src/tools_basic.py:115-122`
**Code:** `if _controller and _controller.state and _controller.state.joined:`
**Description:** Deep access into controller internals.
**Refactor:** Add `controller.is_in_meeting()` method.

---

## Additional RACE_CONDITIONS entries

### RC-003: Global state in meet_bot
**File:** `tool_modules/aa_meet_bot/src/tools_basic.py:47-57`
**Description:** Multiple global variables (`_controller`, `_device_manager`, `_approved_meetings`, etc.) modified without locking.
**Mitigation:** Add `asyncio.Lock()` for each global.

### RC-004: Slack manager singleton
**File:** `aa_slack/src/tools_basic.py:87-120`
**Description:** `get_manager()` uses `_manager_lock` but dynamic module loading in critical section could still race.
**Mitigation:** Move module loading outside lock or use more granular locking.

### RC-005: Approved meetings dict
**File:** `tool_modules/aa_meet_bot/src/tools_basic.py:51, 212-218`
**Description:** `_approved_meetings` dict modified without locking in async context.
**Mitigation:** Use `asyncio.Lock()` or thread-safe dict.

---

## Additional MEMORY_LEAKS entries

### ML-003: Caption buffers
**File:** `tool_modules/aa_meet_bot/src/tools_basic.py:371, 1479`
**Description:** `caption_buffer` and `transcript_buffer` grow unbounded during long meetings.
**Mitigation:** Add max buffer size with circular buffer behavior.

### ML-004: Approved meetings never cleaned
**File:** `tool_modules/aa_meet_bot/src/tools_basic.py:51`
**Description:** `_approved_meetings` dict only grows, never pruned.
**Mitigation:** Add TTL or max size with LRU eviction.

### ML-005: Browser instance tracking
**File:** `tool_modules/aa_meet_bot/src/tools_basic.py:1043`
**Description:** `GoogleMeetController.get_all_instances()` could accumulate if cleanup fails.
**Current mitigation:** `cleanup_hung_instances()` exists.
**Enhancement:** Add periodic automatic cleanup.

---

## Additional DEAD_CODE entries

### DD-005: Legacy single-bot mode
**File:** `tool_modules/aa_meet_bot/src/tools_basic.py:54, 678-689`
**Code:** `_notes_bot` variable and `_get_notes_bot()` function
**Description:** Marked as "Legacy single-bot mode" but still present.
**Action:** Remove if fully migrated to multi-meeting mode.

### DD-006: TODO comments
**File:** `tool_modules/aa_meet_bot/src/tools_basic.py:521`
**Code:** `# TODO: Play audio only`
**Action:** Either implement or remove.

---

## Priority Matrix (Updated)

| Severity | Count | Key Items |
|----------|-------|-----------|
| Critical | 4 | LC-002, LC-005, LC-006, LC-007 |
| High | 10 | LONG_METHOD, DUPLICATE_CODE, RACE_CONDITIONS |
| Medium | 25+ | Most other categories |
| Low | 10+ | DEAD_CODE, SPECULATIVE_GENERALITY |

## Recommended Order of Attack (Updated)

1. **Quick Wins (1-2 hours each)**
   - ML-001 through ML-009: Extract magic literals to constants
   - DD-001, DD-005, DD-006: Remove unused/dead code
   - LC-001/002 (centralization): Use format_error/format_success everywhere

2. **Medium Effort (1-2 days each)**
   - DC-001: Consolidate run_cmd implementations
   - DC-007: Create SingletonProvider for global state
   - CS-001: Create central paths.py
   - HD-001, HD-006, HD-008: Make paths configurable
   - PO-001, PO-006, PO-007, PO-008: Create enums for string constants

3. **Large Refactors (1 week each)**
   - LC-002: Split ToolExecutor into domain-specific executors
   - LC-006: Split aa_meet_bot/tools_basic.py into modules
   - LC-007: Split commandCenter.ts into components
   - RC-003, RC-004, RC-005: Add proper locking to globals

4. **Architectural Changes (2+ weeks)**
   - CD-001: Restructure server/tool_modules dependency
   - SS-001: Single environment registry
   - DV-001: Template/generator for tool modules

---

## Additional LARGE_CLASS entries (Iteration 3)

### LC-008: CronScheduler (scheduler.py)
**Lines:** 277-1255 (~980 lines)
**Severity:** High
**Description:** Single class handling:
- Job configuration and parsing
- Cron trigger creation
- Job execution with retry logic
- Remediation (kube_login, vpn_connect)
- Claude CLI integration
- Skill execution
- Notification dispatch
- Config hot-reloading
**Refactor:** Extract `JobExecutor`, `RemediationHandler`, `ClaudeCliRunner`, `ConfigWatcher` classes.

### LC-009: ContextResolver (context_resolver.py)
**Lines:** 73-337 (~264 lines)
**Severity:** Medium
**Description:** Reasonably sized but mixes concerns:
- Config loading
- Index building
- URL parsing
- Message parsing
- Repo resolution
**Refactor:** Could extract `GitLabUrlParser`, `JiraKeyParser` as separate utilities.

---

## Additional LONG_METHOD entries (Iteration 3)

### LM-009: _execute_job (scheduler.py)
**File:** `tool_modules/aa_workflow/src/scheduler.py:507-643`
**Lines:** ~136 lines
**Severity:** High
**Description:** Massive method doing:
- Session name generation
- Retry loop with backoff
- Claude CLI or direct execution branching
- Failure type detection
- Remediation application
- Logging
**Refactor:** Break into `_execute_with_retry()`, `_apply_remediation_and_retry()`, `_log_execution()`.

### LM-010: _run_with_claude_cli (scheduler.py)
**File:** `tool_modules/aa_workflow/src/scheduler.py:832-947`
**Lines:** ~115 lines
**Severity:** Medium
**Description:** Prompt building, process execution, timeout handling, file logging all in one method.
**Refactor:** Extract `_build_cron_prompt()`, `_run_claude_process()`.

### LM-011: from_message (context_resolver.py)
**File:** `scripts/common/context_resolver.py:134-259`
**Lines:** ~125 lines
**Severity:** Medium
**Description:** Long method with 5 sequential pattern matching blocks.
**Refactor:** Extract `_try_gitlab_url()`, `_try_jira_key()`, `_try_repo_name()`, `_try_branch_pattern()`.

### LM-012: _poll_loop (poll_engine.py)
**File:** `tool_modules/aa_workflow/src/poll_engine.py:373-422`
**Lines:** ~50 lines
**Severity:** Low
**Description:** Acceptable length but mixes scheduling logic with source polling.
**Refactor:** Minor - could extract `_check_and_poll_job()`.

---

## Additional MAGIC_LITERALS entries (Iteration 3)

### ML-010: Scheduler timeouts
**File:** `tool_modules/aa_workflow/src/scheduler.py`
**Examples:**
- `timeout=300` (Claude CLI timeout - line 908)
- `timeout=120` (kube_login timeout - line 763)
- `seconds=30` (config watcher interval - line 407)
- `misfire_grace_time=300` (APScheduler - line 309)
**Refactor:** Define `SCHEDULER_TIMEOUTS` config section.

### ML-011: Dedup TTL in poll engine
**File:** `tool_modules/aa_workflow/src/poll_engine.py:331`
**Code:** `self._dedup_ttl = timedelta(hours=24)`
**Refactor:** Make configurable: `POLL_DEDUP_TTL_HOURS`.

### ML-012: Notification truncation limits
**File:** `tool_modules/aa_workflow/src/notification_engine.py`
**Examples:**
- `message[:2000]` (Slack limit - line 85)
- `message[:200]` (desktop notification - line 118)
- `message[:500]` (memory storage - line 200)
- `notifications[-100:]` (max stored - line 208)
**Refactor:** Define `NOTIFICATION_LIMITS` constants.

### ML-013: Pattern matching thresholds
**File:** `tool_modules/aa_workflow/src/scheduler.py:659-695`
**Description:** Auth, network, timeout patterns all have inline string lists.
**Refactor:** Move to config or constants file for easier maintenance.

---

## Additional DUPLICATE_CODE entries (Iteration 3)

### DC-011: Singleton pattern for global engines
**Files:** `scheduler.py:1212-1243`, `notification_engine.py:376-392`, `poll_engine.py:507-523`
**Description:** All three files use identical pattern:
```python
_engine: Engine | None = None

def get_engine() -> Engine | None:
    return _engine

def init_engine(...) -> Engine:
    global _engine
    _engine = Engine(...)
    return _engine
```
**Refactor:** Create `SingletonFactory` generic or use dependency injection container.

### DC-012: Duration parsing
**File:** `tool_modules/aa_workflow/src/poll_engine.py:26-57`
**Description:** `parse_duration()` duplicates logic that could use `dateutil.parser` or standard library.
**Note:** Check if similar parsing exists in bonfire tools.

### DC-013: Condition comparison operators
**File:** `tool_modules/aa_workflow/src/poll_engine.py:147-173`
**Description:** `_compare()` and `_compare_duration()` have identical operator handling.
**Refactor:** Create generic `_compare_with_operator(left, right, operator)`.

### DC-014: glab command pattern
**File:** `tool_modules/aa_gitlab/src/tools_basic.py:169-298`
**Description:** Multiple `_gitlab_mr_*_impl` functions have similar structure:
```python
args = ["mr", "command", str(mr_id)]
success, output = await run_glab(args, repo=project)
return f"✅ ..." if success else f"❌ Failed: {output}"
```
**Refactor:** Create `_run_mr_command(project, mr_id, command, args, success_msg)` helper.

---

## Additional HARD_CODED_DEFAULTS entries (Iteration 3)

### HD-009: VPN script path
**File:** `tool_modules/aa_workflow/src/scheduler.py:796`
**Code:** `vpn_script = os.path.expanduser("~/src/redhatter/src/redhatter_vpn/vpn-connect")`
**Problem:** Hardcoded path to VPN script.
**Refactor:** Load from config.json under `auth.vpn_script`.

### HD-010: Log file locations
**File:** `tool_modules/aa_workflow/src/scheduler.py:316, 884`
**Code:**
- `log_file = Path.home() / ".config" / "aa-workflow" / "scheduler.log"`
- `log_dir = Path.home() / ".config" / "aa-workflow" / "cron_logs"`
**Problem:** Hardcoded XDG-like paths.
**Refactor:** Use `XDG_CONFIG_HOME` env var or centralize in paths.py.

### HD-011: History file path
**File:** `tool_modules/aa_workflow/src/scheduler.py:181`
**Code:** `HISTORY_FILE = Path.home() / ".config" / "aa-workflow" / "cron_history.json"`
**Problem:** Same as HD-010.

### HD-012: Config paths in context_resolver
**File:** `scripts/common/context_resolver.py:83-87`
**Code:**
```python
CONFIG_PATHS = [
    Path.cwd() / "config.json",
    Path(__file__).parent.parent.parent / "config.json",
    Path.home() / "src/redhat-ai-workflow/config.json",
]
```
**Problem:** Multiple hardcoded fallback paths.
**Refactor:** Use single source from environment or central config module.

---

## Additional PRIMITIVE_OBSESSION entries (Iteration 3)

### PO-009: Failure types
**File:** `tool_modules/aa_workflow/src/scheduler.py:644-697`
**Examples:** `failure_type = "auth"`, `"network"`, `"timeout"`, `"unknown"`
**Refactor:** Create `FailureType` enum.

### PO-010: Backoff strategies
**File:** `tool_modules/aa_workflow/src/scheduler.py:52`
**Code:** `backoff: Literal["exponential", "linear"] = "exponential"`
**Refactor:** Create `BackoffStrategy` enum.

### PO-011: Condition types
**File:** `tool_modules/aa_workflow/src/poll_engine.py:75`
**Examples:** `self.condition_type = "any"`, `"age"`, `"count"`
**Refactor:** Create `ConditionType` enum.

### PO-012: Source types
**File:** `tool_modules/aa_workflow/src/poll_engine.py:213-218`
**Examples:** `self.source_type == "gitlab_mr_list"`, `"jira_search"`
**Refactor:** Create `PollSourceType` enum.

---

## Additional DATA_CLUMPS entries (Iteration 3)

### DC-015: Job execution context
**File:** `tool_modules/aa_workflow/src/scheduler.py:507-525`
**Description:** `job_name`, `skill`, `inputs`, `notify`, `persona`, `retry_config` always passed together.
**Refactor:** Create `JobContext` dataclass.

### DC-016: Notification parameters
**File:** `tool_modules/aa_workflow/src/notification_engine.py:254-262`
**Description:** `job_name`, `skill`, `success`, `output`, `error`, `channels` always grouped.
**Refactor:** Create `NotificationPayload` dataclass.

### DC-017: Poll source configuration
**File:** `tool_modules/aa_workflow/src/poll_engine.py:179-191`
**Description:** `name`, `source_type`, `args`, `condition`, `server` always passed together.
**Refactor:** Create `PollSourceConfig` dataclass.

---

## Additional FEATURE_ENVY entries (Iteration 3)

### FE-005: Scheduler accessing config internals
**File:** `tool_modules/aa_workflow/src/scheduler.py:1028-1029`
**Code:** `self.scheduler.remove_job(job_id)` directly accessing APScheduler internals.
**Refactor:** Encapsulate job management in wrapper methods.

### FE-006: PollSource parsing tool responses
**File:** `tool_modules/aa_workflow/src/poll_engine.py:231-234, 278-280`
**Description:** `_parse_mr_list` and `_parse_jira_list` parse tool output, which is fragile.
**Refactor:** Tools should return structured data, not formatted text.

---

## Additional RACE_CONDITIONS entries (Iteration 3)

### RC-006: Scheduler singleton
**File:** `tool_modules/aa_workflow/src/scheduler.py:1221-1239`
**Description:** `init_scheduler` checks and sets global `_scheduler` without locking.
**Mitigation:** Unlikely to race in practice, but add lock for safety.

### RC-007: Triggered hashes dict
**File:** `tool_modules/aa_workflow/src/poll_engine.py:330-438`
**Description:** `_triggered_hashes` dict modified in async loop without locking.
**Mitigation:** Use `asyncio.Lock()` for thread safety.

### RC-008: Config hot-reload
**File:** `tool_modules/aa_workflow/src/scheduler.py:1045-1079`
**Description:** `_check_config_and_reload` modifies scheduler jobs while other async operations may be running.
**Mitigation:** Add job modification lock.

---

## Additional CONFIGURATION_SCATTERING entries (Iteration 3)

### CS-005: PROJECT_DIR definitions
**Files:** `scheduler.py:127-129`, `notification_engine.py:26-27`, `poll_engine.py:23`
**Description:** Each file defines its own `PROJECT_DIR = Path(__file__).parent.parent.parent.parent`
**Refactor:** Single `project_paths.py` module with all path constants.

### CS-006: Retry configuration
**File:** `tool_modules/aa_workflow/src/scheduler.py:28-35`
**Description:** `DEFAULT_RETRY_CONFIG` hardcoded in scheduler, not in config.json.
**Refactor:** Move to config.json under `schedules.default_retry`.

---

## Additional SPECULATIVE_GENERALITY entries (Iteration 3)

### SG-003: Unused poll source types
**File:** `tool_modules/aa_workflow/src/poll_engine.py:212-219`
**Description:** Only `gitlab_mr_list` and `jira_search` are implemented, but infrastructure suggests more types planned.
**Action:** Document planned types or remove overly generic structure.

### SG-004: Unused notification backends
**File:** `tool_modules/aa_workflow/src/notification_engine.py:103-169`
**Description:** `DesktopNotificationBackend` implemented but may not be used in production.
**Action:** Verify usage or mark as experimental.

---

## Additional LACK_OF_CENTRALIZATION entries (Iteration 3)

### LC-003: Emoji formatting
**Files:** Multiple notification/tool files
**Examples:**
- `"✅"` / `"❌"` for success/failure
- `"🔴"` / `"🟡"` / `"ℹ️"` for severity
**Refactor:** Create `format_utils.py` with `SUCCESS_EMOJI`, `FAILURE_EMOJI`, `severity_emoji()`.

### LC-004: Date/time parsing
**Files:** `poll_engine.py:124-134`, `memory.py`, `scheduler.py`
**Description:** ISO date parsing done differently in each file.
**Refactor:** Create `datetime_utils.parse_iso()` with consistent timezone handling.

---

## Updated Priority Matrix (Iteration 3)

| Severity | Count | Key Items |
|----------|-------|-----------|
| Critical | 4 | LC-002, LC-005, LC-006, LC-007 |
| High | 14 | LC-008, LM-009, LM-010, RACE_CONDITIONS |
| Medium | 35+ | Most other categories |
| Low | 15+ | DEAD_CODE, SPECULATIVE_GENERALITY |

## Updated Recommended Order of Attack

1. **Quick Wins (1-2 hours each)**
   - ML-010 through ML-013: Extract magic literals
   - LC-003/004: Centralize emoji and date formatting
   - DC-011: Create SingletonFactory for global instances

2. **Medium Effort (1-2 days each)**
   - DC-014: Create glab command helper
   - HD-009 through HD-012: Make paths configurable
   - PO-009 through PO-012: Create enums for type strings
   - CS-005: Centralize PROJECT_DIR

3. **Large Refactors (1 week each)**
   - LC-008: Split CronScheduler into focused classes
   - LM-009/010: Refactor _execute_job into smaller methods
   - RC-006/007/008: Add proper locking to scheduler/poll engine

4. **Architectural Changes (2+ weeks)**
   - DC-011: Implement dependency injection container
   - FE-006: Return structured data from tools instead of formatted text
   - CS-006: Consolidate all config in config.json

---

## Additional Entries (Iteration 4)

### LONG_PARAMETER_LIST

#### LP-005: jira_create_issue
**File:** `tool_modules/aa_jira/src/tools_basic.py:279-329`
**Parameters:** 12 parameters
**Same as LP-001 but now confirmed in impl function.**
**Refactor:** Create `CreateIssueRequest` dataclass with builder pattern.

#### LP-006: bonfire_deploy
**File:** `tool_modules/aa_bonfire/src/tools_basic.py:580-593`
**Parameters:** 12 parameters
**Description:** `app`, `namespace`, `source`, `target_env`, `ref_env`, `set_image_tag`, `set_template_ref`, `component`, `timeout`, `no_get_dependencies`, `single_replicas`, `reserve`
**Refactor:** Create `DeployConfig` dataclass.

#### LP-007: kubectl_logs
**File:** `tool_modules/aa_k8s/src/tools_basic.py:390-412`
**Parameters:** 8 parameters
**Description:** `pod_name`, `namespace`, `environment`, `container`, `tail`, `previous`, `since`, `selector`
**Refactor:** Create `LogRequest` dataclass.

#### LP-008: kubectl_cp
**File:** `tool_modules/aa_k8s/src/tools_basic.py:142-168`
**Parameters:** 6 parameters
**Description:** `source`, `destination`, `namespace`, `environment`, `container`, `to_pod`
**Refactor:** Create `CopySpec` dataclass.

---

### DUPLICATE_CODE (Iteration 4)

#### DC-015: Tool registration pattern
**Files:** All `tools_basic.py` files
**Description:** Every file has:
```python
def _register_*_tools(registry: ToolRegistry) -> None:
    @auto_heal()
    @registry.tool()
    async def tool_name(...) -> str:
        return await _tool_name_impl(...)
```
This boilerplate is repeated dozens of times.
**Refactor:** Use metaclass or decorator factory that auto-wraps `_impl` functions.

#### DC-016: Success/failure return pattern
**Files:** All tool modules
**Description:** Repeated pattern across 100+ functions:
```python
if success:
    return f"✅ {message}"
return f"❌ Failed: {output}"
```
**Refactor:** Create `ToolResult.success(msg)` / `ToolResult.error(msg)` helpers.

#### DC-017: run_cmd with kubeconfig pattern
**File:** `tool_modules/aa_k8s/src/tools_basic.py`
**Description:** Pattern repeated 20+ times:
```python
kubeconfig = get_kubeconfig(environment, namespace)
success, output = await run_kubectl(args, kubeconfig=kubeconfig, namespace=namespace)
```
**Refactor:** Create `K8sContext` class that encapsulates environment + namespace.

#### DC-018: run_rh_issue / run_bonfire / run_glab pattern
**Files:** Jira, Bonfire, GitLab tools
**Description:** Nearly identical command execution patterns across all CLI tools.
**Refactor:** Create `CLITool` base class with `run()` method.

---

### MAGIC_LITERALS (Iteration 4)

#### ML-014: Command timeouts
**File:** `tool_modules/aa_jira/src/tools_basic.py`
**Examples:**
- `timeout=30` (default for rh-issue)
- `timeout=60` (for create/clone/search)
**Refactor:** Define `JIRA_TIMEOUT_DEFAULT = 30`, `JIRA_TIMEOUT_LONG = 60`.

#### ML-015: Bonfire timeouts
**File:** `tool_modules/aa_bonfire/src/tools_basic.py`
**Examples:**
- `timeout=300` (default bonfire)
- `timeout=600` (deploy)
- `timeout=900` (deploy_aa)
- `timeout + 120` (buffer)
**Refactor:** Define `BONFIRE_TIMEOUTS` constant dict.

#### ML-016: K8s truncation limits
**File:** `tool_modules/aa_k8s/src/tools_basic.py`
**Examples:**
- `max_length=10000` (describe)
- `max_length=15000` (get)
- `lines[:50]` (events)
- `lines[:5]` (namespaces preview)
**Refactor:** Define `K8S_OUTPUT_LIMITS` constants.

#### ML-017: SHA length validations
**File:** `tool_modules/aa_bonfire/src/tools_basic.py:236, 252`
**Examples:**
- `len(template_ref) != 40` (git SHA)
- `len(digest) != 64` (sha256)
**Refactor:** Define `GIT_SHA_LENGTH = 40`, `SHA256_DIGEST_LENGTH = 64`.

---

### HARD_CODED_DEFAULTS (Iteration 4)

#### HD-013: Jira URL fallback
**File:** `tool_modules/aa_jira/src/tools_basic.py:28`
**Code:** `.get("url", "https://issues.redhat.com")`
**Refactor:** Require config instead of fallback.

#### HD-014: Bonfire image base
**File:** `tool_modules/aa_bonfire/src/tools_basic.py:81-84`
**Code:** `"quay.io/redhat-user-workloads/aap-aa-tenant/aap-aa-main/automation-analytics-backend-main"`
**Refactor:** Require in config, no fallback.

#### HD-015: Bonfire component names
**File:** `tool_modules/aa_bonfire/src/tools_basic.py:74-76`
**Code:** `"tower-analytics-billing-clowdapp"`, `"tower-analytics-clowdapp"`
**Refactor:** Require in config.

#### HD-016: Bonfire ref_env
**File:** `tool_modules/aa_bonfire/src/tools_basic.py:85`
**Code:** `.get("ref_env", "insights-production")`
**Refactor:** Require in config.

#### HD-017: K8s namespace prefixes
**File:** `tool_modules/aa_k8s/src/tools_basic.py:61`
**Code:** `if "your-app" in ln`
**Problem:** Hardcoded namespace filter - should be configurable.
**Refactor:** Load from config.

---

### PRIMITIVE_OBSESSION (Iteration 4)

#### PO-013: Jira issue type
**File:** `tool_modules/aa_jira/src/tools_basic.py:336-337`
**Examples:** `valid_types = {"bug", "story", "task", "epic", "spike", "subtask"}`
**Refactor:** Create `IssueType` enum.

#### PO-014: Jira priority
**File:** `tool_modules/aa_jira/src/tools_basic.py:535`
**Examples:** `"Blocker", "Critical", "Major", "Normal", "Minor"`
**Refactor:** Create `Priority` enum.

#### PO-015: Bonfire source
**File:** `tool_modules/aa_bonfire/src/tools_basic.py:156`
**Examples:** `source: str = "appsre"` (also `"file"`)
**Refactor:** Create `BonfireSource` enum.

#### PO-016: Pool names
**File:** `tool_modules/aa_bonfire/src/tools_basic.py:487`
**Examples:** `pool: str = "default"`
**Refactor:** Create `NamespacePool` enum or load from config.

---

### FEATURE_ENVY (Iteration 4)

#### FE-007: Jira output parsing
**File:** `tool_modules/aa_jira/src/tools_basic.py:643-662`
**Description:** `_jira_view_issue_json_impl` parses CLI output with regex - fragile.
**Refactor:** CLI should output JSON, or create dedicated parser class.

#### FE-008: K8s output parsing
**File:** `tool_modules/aa_k8s/src/tools_basic.py:94-128`
**Description:** `_k8s_namespace_health_impl` manually parses kubectl output lines.
**Refactor:** Use `-o json` and parse structured data.

---

### DATA_CLUMPS (Iteration 4)

#### DC-019: K8s context
**File:** `tool_modules/aa_k8s/src/tools_basic.py`
**Description:** `namespace`, `environment`, `kubeconfig` always passed together.
**Refactor:** Create `K8sContext` dataclass.

#### DC-020: Bonfire deploy params
**File:** `tool_modules/aa_bonfire/src/tools_basic.py:151-164`
**Description:** `app`, `namespace`, `source`, `target_env`, `ref_env`, etc. always grouped.
**Refactor:** Create `DeployConfig` dataclass.

#### DC-021: AA deploy params
**File:** `tool_modules/aa_bonfire/src/tools_basic.py:212-218`
**Description:** `namespace`, `template_ref`, `image_tag`, `billing`, `timeout` always grouped.
**Refactor:** Create `AADeployConfig` dataclass.

---

### DEAD_CODE (Iteration 4)

#### DD-007: Unused import cast
**File:** `tool_modules/aa_jira/src/tools_basic.py:8`
**Code:** `from typing import cast` - used only once for config casting.
**Refactor:** Remove cast, use proper typing.

#### DD-008: PROJECT_ROOT assignments
**Files:** All tool modules
**Code:** `__project_root__ = PROJECT_ROOT  # Module initialization`
**Description:** Assigned but never used - only needed for side effect of import.
**Refactor:** Remove assignment, keep import for side effect with comment.

---

### CONFIGURATION_SCATTERING (Iteration 4)

#### CS-007: App configuration fallbacks
**File:** `tool_modules/aa_bonfire/src/tools_basic.py:37-87`
**Description:** `get_app_config()` has complex fallback chain with hardcoded values.
**Refactor:** Require complete config, fail fast on missing values.

#### CS-008: Quay repository path
**File:** `tool_modules/aa_bonfire/src/tools_basic.py:284`
**Code:** `repository = "aap-aa-tenant/aap-aa-main/automation-analytics-backend-main"`
**Problem:** Hardcoded repository path should come from config.
**Refactor:** Load from `bonfire.apps.*.image_repository`.

---

### COMBINATORIAL_EXPLOSION (Iteration 4)

#### CE-004: Kubectl resource getters
**File:** `tool_modules/aa_k8s/src/tools_basic.py:270-387`
**Description:** Separate functions for:
- `_kubectl_get_configmaps_impl`
- `_kubectl_get_deployments_impl`
- `_kubectl_get_events_impl`
- `_kubectl_get_ingress_impl`
- `_kubectl_get_pods_impl`
- `_kubectl_get_secrets_impl`
- `_kubectl_get_services_impl`
All essentially call `run_kubectl(["get", resource_type])`.
**Refactor:** Use single generic `_kubectl_get_resource_impl(resource_type, ...)`.

#### CE-005: Jira status/priority setters
**File:** `tool_modules/aa_jira/src/tools_basic.py:548-586`
**Description:** Separate functions for set_status, set_priority, set_story_points.
**Refactor:** Single `_jira_set_field_impl(issue, field, value)`.

---

### SHOTGUN_SURGERY (Iteration 4)

#### SS-003: Adding a new kubectl resource type
**Files affected:** `tools_basic.py` (k8s), potentially consumers
**Description:** Adding support for a new K8s resource type requires:
1. New `_kubectl_get_*_impl` function
2. New `_register_*_tools` entry
3. New decorated tool function
**Refactor:** Generic resource getter with resource type parameter.

#### SS-004: Adding a new Jira field setter
**Files affected:** `tools_basic.py` (jira)
**Description:** Adding new field setters follows same pattern.
**Refactor:** Generic field setter.

---

### INAPPROPRIATE_INTIMACY (Iteration 4)

#### II-003: Tool modules importing from server
**Files:** All `tools_basic.py`
**Description:** `from server.utils import ...`, `from server.tool_registry import ...`
**Problem:** Tool modules deeply depend on server internals.
**Refactor:** Create clean interface layer between tool_modules and server.

#### II-004: Tool registry accessing FastMCP internals
**File:** `server/tool_registry.py` (if it exists)
**Description:** Registry wraps FastMCP server.
**Refactor:** Abstract the registration interface.

---

## Updated Priority Matrix (Iteration 4)

| Severity | Count | Key Items |
|----------|-------|-----------|
| Critical | 4 | LC-002, LC-005, LC-006, LC-007 |
| High | 18 | LC-008, LM-009, DC-015-018, LP-005-008 |
| Medium | 50+ | Most other categories |
| Low | 20+ | DEAD_CODE, SPECULATIVE_GENERALITY, some PRIMITIVE_OBSESSION |

## Updated Totals by Category

| Category | Count |
|----------|-------|
| LARGE_CLASS | 9 |
| LONG_METHOD | 12 |
| MAGIC_LITERALS | 17 |
| PRIMITIVE_OBSESSION | 16 |
| DUPLICATE_CODE | 21 |
| CONFIGURATION_SCATTERING | 8 |
| HARD_CODED_DEFAULTS | 17 |
| DEAD_CODE | 8 |
| LONG_PARAMETER_LIST | 8 |
| FEATURE_ENVY | 8 |
| DATA_CLUMPS | 21 |
| INAPPROPRIATE_INTIMACY | 4 |
| SPECULATIVE_GENERALITY | 4 |
| SHOTGUN_SURGERY | 4 |
| LACK_OF_CENTRALIZATION | 4 |
| RACE_CONDITIONS | 8 |
| FILE_LOCKING_ISSUES | 2 |
| MEMORY_LEAKS | 5 |
| CIRCULAR_DEPENDENCIES | 2 |
| DIVERGENT_CHANGE | 2 |
| COMBINATORIAL_EXPLOSION | 5 |

**TOTAL: 175+ code smell entries**

## Updated Recommended Order of Attack

### Phase 1: Quick Wins (1-2 hours each)
- ML-014 through ML-017: Extract all magic literals to constants
- DC-016: Create `ToolResult` helper class
- DD-007, DD-008: Remove unused code
- PO-013 through PO-016: Create enums for type strings

### Phase 2: Medium Effort (1-2 days each)
- DC-015: Create decorator factory for tool registration
- DC-017, DC-018: Create base classes for CLI tools
- CE-004: Generic kubectl resource getter
- CE-005: Generic Jira field setter
- LP-005 through LP-008: Create dataclasses for complex params

### Phase 3: Large Refactors (1 week each)
- DC-019, DC-020, DC-021: Create context/config dataclasses
- CS-007, CS-008: Strict config loading with validation
- II-003, II-004: Create clean interface between tool_modules and server
- HD-013 through HD-017: Remove all hardcoded fallbacks

### Phase 4: Architectural Changes (2+ weeks)
- SS-003, SS-004: Generic handlers to reduce shotgun surgery
- All LARGE_CLASS items: Split into focused modules
- FE-007, FE-008: Use JSON output and proper parsers

---

## Additional Entries (Iteration 5)

### LARGE_CLASS (Iteration 5)

#### LC-010: server/utils.py
**File:** `server/utils.py`
**Lines:** ~1093 lines
**Severity:** High
**Description:** Single file handling:
- Output formatting (truncate, format_error, format_success, format_warning, format_list)
- Config loading (load_config, get_section_config)
- Kubeconfig handling (get_kubeconfig, check_cluster_auth, refresh_cluster_auth)
- Repository handling (resolve_repo_path, get_repo_config)
- Command execution (run_cmd, run_cmd_full, run_cmd_sync, run_cmd_shell, run_kubectl, run_oc)
- User config (get_user_config, get_username)
- Service URLs (get_gitlab_host, get_service_url, get_bearer_token)
**Refactor:** Split into:
- `server/formatting.py` - Output formatting utilities
- `server/kube.py` - Kubernetes/kubeconfig utilities
- `server/command.py` - Command execution utilities
- `server/repo.py` - Repository utilities

#### LC-011: DaemonDBusBase + DynamicDaemonInterface
**File:** `scripts/common/dbus_base.py:94-369`
**Lines:** ~275 lines
**Severity:** Medium
**Description:** Base class plus dynamically-generated interface class.
**Note:** Acceptable complexity for D-Bus abstraction, but could extract interface factory.

#### LC-012: SprintSafetyGuard
**File:** `tool_modules/aa_workflow/src/skill_engine.py:174-430+`
**Lines:** ~250+ lines (within 26K token file)
**Severity:** Medium
**Description:** Git safety checking before sprint work.
**Refactor:** Could be in separate `sprint_safety.py` module.

---

### LONG_METHOD (Iteration 5)

#### LM-013: run_cmd
**File:** `server/utils.py:477-570`
**Lines:** ~93 lines
**Severity:** Medium
**Description:** Command execution with shell setup, environment prep, error handling.
**Refactor:** Already uses helpers `_build_shell_sources()` and `_prepare_shell_environment()` which is good.

#### LM-014: _prepare_shell_environment
**File:** `server/utils.py:740-793`
**Lines:** ~53 lines
**Severity:** Low
**Description:** Environment preparation with GUI/Wayland handling.
**Note:** Acceptable length, well-organized by concern.

---

### DUPLICATE_CODE (Iteration 5)

#### DC-022: run_cmd variants
**File:** `server/utils.py:477-706`
**Description:** Three very similar functions:
- `run_cmd()` - async, returns (success, output)
- `run_cmd_full()` - async, returns (success, stdout, stderr)
- `run_cmd_sync()` - sync version
All share nearly identical logic.
**Refactor:** Create `_run_cmd_core()` helper that all three call.

#### DC-023: KUBECONFIG_MAP duplication
**Files:** `server/utils.py:202-221`, `scripts/common/context_resolver.py`
**Description:** Environment to kubeconfig suffix mapping defined in multiple places.
**Refactor:** Single `KUBECONFIG_MAP` in server/constants.py.

#### DC-024: get_auth_hint cluster_map
**File:** `server/utils.py:843-855`
**Description:** Nearly identical to `KUBECONFIG_MAP` defined earlier in same file.
**Refactor:** Reuse `KUBECONFIG_MAP`.

#### DC-025: D-Bus service config repetition
**File:** `scripts/common/dbus_base.py:487-503`
**Description:** `services` dict hardcodes service configs that could come from config.json.
**Refactor:** Load from config.json under `dbus.services` section.

---

### MAGIC_LITERALS (Iteration 5)

#### ML-018: run_cmd timeouts
**File:** `server/utils.py`
**Examples:**
- `timeout: int = 60` (default run_cmd)
- `timeout: int = 300` (run_cmd_full, run_cmd_shell)
- `timeout=10` (auth check)
- `timeout=120` (auth refresh)
**Refactor:** Define `CMD_TIMEOUTS` constant dict.

#### ML-019: Truncation limits in utils
**File:** `server/utils.py:21-47`
**Code:** `max_length: int = 5000`
**Refactor:** Define `DEFAULT_TRUNCATE_LENGTH` constant.

#### ML-020: Health check interval
**File:** `scripts/common/dbus_base.py:125`
**Code:** `self._health_check_interval: float = 30.0`
**Refactor:** Load from config or define constant.

#### ML-021: Uptime threshold
**File:** `scripts/common/dbus_base.py:161`
**Code:** `(time.time() - self.start_time) > 10`
**Description:** Magic number 10 seconds for "uptime_ok" check.
**Refactor:** Define `MIN_UPTIME_SECONDS` constant.

---

### CONFIGURATION_SCATTERING (Iteration 5)

#### CS-009: D-Bus service definitions
**File:** `scripts/common/dbus_base.py:487-503`
**Description:** Service names, object paths, interface names hardcoded.
**Refactor:** Load from config.json under `dbus.services`.

#### CS-010: Workspace roots
**File:** `server/utils.py:433-440`
**Description:** Default workspace roots hardcoded.
**Refactor:** Already supports config override, but defaults should be in constants file.

---

### HARD_CODED_DEFAULTS (Iteration 5)

#### HD-018: Default truncation suffix
**File:** `server/utils.py:24`
**Code:** `suffix: str = "\n\n... (truncated)"`
**Refactor:** Define `TRUNCATE_SUFFIX` constant.

#### HD-019: GitLab default host
**File:** `server/utils.py:991`
**Code:** `"gitlab.cee.redhat.com"`
**Refactor:** Require in config, no fallback.

#### HD-020: Protected branches
**File:** `tool_modules/aa_workflow/src/skill_engine.py:192`
**Code:** `PROTECTED_BRANCHES = {"main", "master", "develop", "production", "staging"}`
**Refactor:** Load from config.json under `git.protected_branches`.

---

### PRIMITIVE_OBSESSION (Iteration 5)

#### PO-017: Environment names
**File:** `server/utils.py:202-221`
**Description:** `"stage"`, `"production"`, `"ephemeral"`, etc. as strings.
**Refactor:** Create `Environment` enum.

#### PO-018: Truncation mode
**File:** `server/utils.py:25`
**Code:** `mode: str = "head"` (also "tail")
**Refactor:** Create `TruncateMode` enum.

---

### DEAD_CODE (Iteration 5)

#### DD-009: run_cmd_shell deprecated wrapper
**File:** `server/utils.py:797-806`
**Description:** `run_cmd_shell()` marked as DEPRECATED, just calls `run_cmd_full()`.
**Refactor:** Remove after updating callers.

---

### FEATURE_ENVY (Iteration 5)

#### FE-009: git_status parsing in SprintSafetyGuard
**File:** `tool_modules/aa_workflow/src/skill_engine.py:246-280`
**Description:** `check_git_status()` manually parses git status output text.
**Refactor:** git_status tool should return structured data, not text.

---

### INAPPROPRIATE_INTIMACY (Iteration 5)

#### II-005: skill_engine importing from server
**File:** `tool_modules/aa_workflow/src/skill_engine.py:23-24`
**Code:** `from server.tool_registry import ToolRegistry`, `from server.utils import load_config`
**Problem:** Tool module depends on server internals.
**Refactor:** Use clean interface layer.

---

### RACE_CONDITIONS (Iteration 5)

#### RC-009: DaemonDBusBase state
**File:** `scripts/common/dbus_base.py:114-131`
**Description:** Instance variables like `is_running`, `_consecutive_failures` modified without locking.
**Mitigation:** Add lock for health tracking state.

---

### DATA_CLUMPS (Iteration 5)

#### DC-027: Shell execution context
**File:** `server/utils.py:477-570`
**Description:** `cmd`, `cwd`, `env`, `timeout`, `use_shell` always passed together.
**Refactor:** Create `CommandContext` dataclass.

#### DC-028: Git status result
**File:** `tool_modules/aa_workflow/src/skill_engine.py:225-232`
**Description:** `clean`, `modified`, `staged`, `untracked`, `branch`, `in_progress` always grouped.
**Refactor:** Create `GitStatus` dataclass.

---

## Updated Priority Matrix (Iteration 5)

| Severity | Count | Key Items |
|----------|-------|-----------|
| Critical | 4 | LC-002, LC-005, LC-006, LC-007 |
| High | 20 | LC-008, LC-010, DC-015-018, DC-022 |
| Medium | 60+ | Most other categories |
| Low | 25+ | DEAD_CODE, SPECULATIVE_GENERALITY |

## Updated Totals by Category (Iteration 5)

| Category | Count |
|----------|-------|
| LARGE_CLASS | 12 |
| LONG_METHOD | 14 |
| MAGIC_LITERALS | 21 |
| PRIMITIVE_OBSESSION | 18 |
| DUPLICATE_CODE | 28 |
| CONFIGURATION_SCATTERING | 10 |
| HARD_CODED_DEFAULTS | 20 |
| DEAD_CODE | 9 |
| LONG_PARAMETER_LIST | 8 |
| FEATURE_ENVY | 9 |
| DATA_CLUMPS | 28 |
| INAPPROPRIATE_INTIMACY | 5 |
| SPECULATIVE_GENERALITY | 4 |
| SHOTGUN_SURGERY | 4 |
| LACK_OF_CENTRALIZATION | 4 |
| RACE_CONDITIONS | 9 |
| FILE_LOCKING_ISSUES | 2 |
| MEMORY_LEAKS | 5 |
| CIRCULAR_DEPENDENCIES | 2 |
| DIVERGENT_CHANGE | 2 |
| COMBINATORIAL_EXPLOSION | 5 |

**TOTAL: 195+ code smell entries**

---

## Additional Entries (Iteration 6)

### LARGE_CLASS (Iteration 6)

#### LC-013: slack_daemon.py
**File:** `scripts/slack_daemon.py`
**Lines:** ~2500+ lines (102KB)
**Severity:** Critical
**Description:** Massive daemon file handling:
- Slack client initialization
- Message monitoring and polling
- Claude agent integration
- Command parsing and routing
- User classification system
- Rate limiting
- D-Bus interface
- Message queuing
- Error handling and recovery
**Refactor:** Split into:
- `slack/client.py` - Slack API client
- `slack/monitor.py` - Message monitoring
- `slack/agent.py` - Claude integration
- `slack/commands.py` - Command handling
- `slack/user_classifier.py` - User classification

#### LC-014: CronDaemon
**File:** `scripts/cron_daemon.py:114-423`
**Lines:** ~310 lines
**Severity:** Medium
**Description:** Daemon class with D-Bus, scheduling, sleep/wake handling.
**Note:** Acceptable complexity for daemon, but could extract D-Bus handlers.

#### LC-015: sprintTab.ts (Iteration 12)
**File:** `extensions/aa_workflow_vscode/src/sprintTab.ts:1-1257`
**Lines:** ~1257 lines
**Severity:** High
**Description:** Single file containing interfaces, state loading, HTML/CSS generation, and rendering. Combines data layer (loadSprintState), styling (getSprintTabStyles), and view rendering (getSprintTabContent) in one file.
**Keywords:** typescript, vscode-extension, large-file, sprint, html-generation
**Refactor:** Split into `sprintTypes.ts`, `sprintStateLoader.ts`, `sprintStyles.ts`, `sprintRenderer.ts`.

#### LC-016: performanceTab.ts (Iteration 12)
**File:** `extensions/aa_workflow_vscode/src/performanceTab.ts:1-904`
**Lines:** ~904 lines
**Severity:** Medium
**Description:** Similar to sprintTab.ts - mixes interfaces, state loading, SVG chart generation, HTML rendering, and CSS in one file.
**Keywords:** typescript, vscode-extension, performance, sunburst-chart, html-generation
**Refactor:** Extract `performanceSunburstChart.ts` for SVG generation, `performanceStyles.ts` for CSS.

#### LC-017: SkillToastWebview (Iteration 12)
**File:** `extensions/aa_workflow_vscode/src/skillToast.ts:339-772`
**Lines:** ~433 lines
**Severity:** Medium
**Description:** Webview class with massive inline HTML/CSS/JS template in `getWebviewContent()` method (~320 lines of string template).
**Keywords:** typescript, vscode-extension, webview, inline-html, skill-toast
**Refactor:** Move HTML template to separate file, use Handlebars or EJS templating.

---

### DUPLICATE_CODE (Iteration 6)

#### DC-029: SingleInstance pattern
**Files:** `scripts/cron_daemon.py:67-111`, `scripts/slack_daemon.py`
**Description:** Lock file-based single instance pattern duplicated in both daemons.
**Refactor:** Already have `DaemonDBusBase` - add `SingleInstanceMixin` or base class.

#### DC-030: Daemon argument parsing
**Files:** `scripts/cron_daemon.py:455-505`, `scripts/slack_daemon.py`
**Description:** Nearly identical argparse setup:
- `--verbose`, `--dbus`, `--status`, `--stop` flags
- Similar help text and examples
**Refactor:** Create `create_daemon_argparser()` helper.

#### DC-031: D-Bus status/stop handling
**Files:** `scripts/cron_daemon.py:516-570`, `scripts/slack_daemon.py`
**Description:** Identical pattern for --status and --stop:
```python
try:
    client = get_client("service")
    if await client.connect():
        status = await client.get_status()
        ...
except Exception:
    # Fall back to PID check
```
**Refactor:** Create `daemon_status()` and `daemon_stop()` helpers in dbus_base.py.

#### DC-032: VSCode extension global variables
**File:** `extensions/aa_workflow_vscode/src/extension.ts:27-34`
**Description:** Multiple `| undefined` typed globals:
```typescript
let statusBarManager: StatusBarManager | undefined;
let dataProvider: WorkflowDataProvider | undefined;
...
```
**Refactor:** Create `ExtensionContext` class that holds all managers.

#### DC-033: Legacy command aliases
**File:** `extensions/aa_workflow_vscode/src/extension.ts:99-115`
**Description:** Multiple commands that just redirect to openCommandCenter.
**Refactor:** Use command aliasing mechanism or single handler with args.

---

### MAGIC_LITERALS (Iteration 6)

#### ML-022: Daemon lock/PID paths
**File:** `scripts/cron_daemon.py:50-51`
**Code:**
```python
LOCK_FILE = Path("/tmp/cron-daemon.lock")
PID_FILE = Path("/tmp/cron-daemon.pid")
```
**Refactor:** Use XDG_RUNTIME_DIR or ~/.cache/aa-workflow/.

#### ML-023: Job filtering magic string
**File:** `scripts/cron_daemon.py:151, 201, 265`
**Code:** `if job.id != "_config_watcher":`
**Description:** Magic string for internal job ID repeated 3 times.
**Refactor:** Define `CONFIG_WATCHER_JOB_ID = "_config_watcher"`.

#### ML-024: VSCode refresh interval
**File:** `extensions/aa_workflow_vscode/src/extension.ts:122`
**Code:** `const intervalSeconds = config.get<number>("refreshInterval", 30);`
**Note:** Good - already configurable with default.

#### ML-025: Failure rate threshold
**File:** `scripts/cron_daemon.py:208`
**Code:** `failure_rate < 0.5  # Less than 50% failures`
**Refactor:** Define `ACCEPTABLE_FAILURE_RATE = 0.5`.

#### ML-026: Uptime check threshold
**File:** `scripts/cron_daemon.py:218`
**Code:** `(now - self.start_time) > 10`
**Refactor:** Define `MIN_UPTIME_SECONDS = 10` (also in dbus_base.py).

---

### HARD_CODED_DEFAULTS (Iteration 6)

#### HD-021: D-Bus service names
**File:** `scripts/cron_daemon.py:117-120`
**Code:**
```python
service_name = "com.aiworkflow.BotCron"
object_path = "/com/aiworkflow/BotCron"
interface_name = "com.aiworkflow.BotCron"
```
**Refactor:** Define constants or load from config.

#### HD-022: Temp file locations
**File:** `scripts/cron_daemon.py:50-51`
**Code:** `/tmp/cron-daemon.lock`, `/tmp/cron-daemon.pid`
**Refactor:** Use proper XDG paths.

---

### PRIMITIVE_OBSESSION (Iteration 6)

#### PO-019: Daemon verbose flag
**File:** `scripts/cron_daemon.py:124`
**Code:** `self.verbose = verbose` (bool)
**Note:** Acceptable for simple flag.

#### PO-020: Execution mode
**File:** `scripts/cron_daemon.py:144`
**Code:** `"execution_mode": self._scheduler.config.execution_mode`
**Description:** String type for mode.
**Refactor:** Create `ExecutionMode` enum.

---

### FILE_LOCKING_ISSUES (Iteration 6)

#### FL-003: Lock file cleanup on crash
**File:** `scripts/cron_daemon.py:74-98`
**Description:** `SingleInstance` uses fcntl lock but may leave stale PID file on crash.
**Mitigation:** Check if PID in file is actually running before failing.
**Note:** Code at line 106-110 does check this - good!

#### FL-004: Lock file permissions
**File:** `scripts/cron_daemon.py:77`
**Code:** `self._lock_file = open(LOCK_FILE, "w")`
**Problem:** Creates world-writable file in /tmp.
**Mitigation:** Use `os.open()` with mode 0o600.

---

### RACE_CONDITIONS (Iteration 6)

#### RC-010: Daemon job counters
**File:** `scripts/cron_daemon.py:128-129`
**Code:**
```python
self._jobs_executed = 0
self._jobs_failed = 0
```
**Description:** Counters incremented without locking during async job execution.
**Mitigation:** Use `asyncio.Lock()` or atomic counters.

#### RC-011: shutdown_event check
**File:** `scripts/cron_daemon.py:385`
**Description:** `await self._shutdown_event.wait()` is thread-safe but signal handler sets event from different context.
**Note:** Generally OK with asyncio, but verify signal handler behavior.

---

### DEAD_CODE (Iteration 6)

#### DD-010: Verbose flag unused
**File:** `scripts/cron_daemon.py:124`
**Code:** `self.verbose = verbose`
**Description:** Set but never used - no extra logging based on verbose flag.
**Refactor:** Either use it or remove.

---

### DATA_CLUMPS (Iteration 6)

#### DC-034: D-Bus service triple
**Files:** Multiple daemon files
**Description:** `service_name`, `object_path`, `interface_name` always defined together.
**Note:** Already have `ServiceConfig` dataclass - but not used in class definitions.
**Refactor:** Use `ServiceConfig` as class attribute.

#### DC-035: Job execution context
**File:** `scripts/cron_daemon.py:249-252`
**Description:** `job_name`, `skill`, `inputs` passed together.
**Refactor:** Create `JobRequest` dataclass.

---

### DIVERGENT_CHANGE (Iteration 6)

#### DV-003: Adding a new daemon
**Files affected:** Need to create new file copying pattern from cron_daemon.py
**Description:** Adding a new daemon requires:
1. Copy cron_daemon.py structure
2. Define D-Bus service names
3. Copy SingleInstance pattern
4. Copy argparse setup
5. Copy status/stop handlers
**Refactor:** Create `DaemonBase` class or generator script.

---

### SHOTGUN_SURGERY (Iteration 6)

#### SS-005: Changing D-Bus service discovery
**Files affected:** `dbus_base.py`, all daemon files, consumers
**Description:** Adding a new D-Bus service requires changes to:
1. `get_client()` services dict in dbus_base.py
2. Daemon class definition
3. Any consumers that discover services
**Refactor:** Service registry pattern or config-driven discovery.

---

### SPECULATIVE_GENERALITY (Iteration 6)

#### SG-007: register_handler mechanism
**File:** `scripts/cron_daemon.py:132-134`
**Code:** Custom D-Bus method handlers registered but mechanism is complex.
**Action:** Verify all handlers are actually called via D-Bus or simplify.

---

### INAPPROPRIATE_INTIMACY (Iteration 6)

#### II-006: Daemon importing from tool_modules
**File:** `scripts/cron_daemon.py:317, 403, 427`
**Code:**
```python
from tool_modules.aa_workflow.src.scheduler import get_scheduler, init_scheduler, start_scheduler
```
**Problem:** Daemon script deeply depends on tool_modules internals.
**Refactor:** Create clean scheduler API facade.

---

## Updated Priority Matrix (Iteration 6)

| Severity | Count | Key Items |
|----------|-------|-----------|
| Critical | 5 | LC-002, LC-005, LC-006, LC-007, LC-013 |
| High | 22 | LC-008, LC-010, DC-015-018, DC-022, DC-029-031 |
| Medium | 65+ | Most other categories |
| Low | 28+ | DEAD_CODE, SPECULATIVE_GENERALITY |

## Updated Totals by Category (Iteration 6)

| Category | Count |
|----------|-------|
| LARGE_CLASS | 14 |
| LONG_METHOD | 14 |
| MAGIC_LITERALS | 26 |
| PRIMITIVE_OBSESSION | 20 |
| DUPLICATE_CODE | 35 |
| CONFIGURATION_SCATTERING | 10 |
| HARD_CODED_DEFAULTS | 22 |
| DEAD_CODE | 10 |
| LONG_PARAMETER_LIST | 8 |
| FEATURE_ENVY | 9 |
| DATA_CLUMPS | 35 |
| INAPPROPRIATE_INTIMACY | 6 |
| SPECULATIVE_GENERALITY | 5 |
| SHOTGUN_SURGERY | 5 |
| LACK_OF_CENTRALIZATION | 4 |
| RACE_CONDITIONS | 11 |
| FILE_LOCKING_ISSUES | 4 |
| MEMORY_LEAKS | 5 |
| CIRCULAR_DEPENDENCIES | 2 |
| DIVERGENT_CHANGE | 3 |
| COMBINATORIAL_EXPLOSION | 5 |

**TOTAL: 215+ code smell entries**

---

## Additional Entries (Iteration 7)

### WELL-DESIGNED CODE (Positive Examples)

#### GOOD-001: ConfigManager singleton
**File:** `server/config_manager.py`
**Lines:** ~387 lines
**Description:** Well-designed thread-safe singleton with:
- Proper RLock for thread safety
- File locking for cross-process safety
- Debounced writes to reduce disk I/O
- Automatic cache invalidation via mtime
- Clean public API
**Note:** This is a good reference for how to structure similar components.

#### GOOD-002: ParsedCommand dataclass
**File:** `scripts/common/command_parser.py:35-97`
**Description:** Clean dataclass with:
- Good field defaults
- Type hints
- Helper methods (`to_skill_inputs()`, `to_dict()`)
**Note:** Good pattern for similar result types.

#### GOOD-003: auto_heal decorator
**File:** `server/auto_heal_decorator.py`
**Description:** Well-structured decorator with:
- Pattern detection extracted to helpers
- Async/sync handling
- Configurable retry behavior
- Memory logging for learning
**Note:** Good example of a complex decorator done right.

---

### DUPLICATE_CODE (Iteration 7)

#### DC-036: cluster_map definitions
**Files:** `server/auto_heal_decorator.py:115-121`, `server/utils.py`
**Description:** Cluster short code mapping duplicated:
```python
cluster_map = {
    "stage": "s",
    "production": "p",
    "ephemeral": "e",
    "konflux": "k",
}
```
**Refactor:** Single `CLUSTER_SHORT_CODES` in constants.py.

#### DC-037: kubeconfig suffix mapping
**Files:** `server/auto_heal_decorator.py:126-127`, `server/utils.py`
**Description:** Kubeconfig path suffix logic duplicated.
**Refactor:** Create `get_kubeconfig_path(cluster)` helper.

#### DC-038: Trigger patterns
**File:** `scripts/common/command_parser.py:107-117`
**Description:** Trigger patterns hardcoded - if adding new triggers, must update this dict.
**Note:** Current design is acceptable, but could be config-driven.

---

### MAGIC_LITERALS (Iteration 7)

#### ML-027: ConfigManager debounce delay
**File:** `server/config_manager.py:45`
**Code:** `DEBOUNCE_DELAY = 2.0`
**Note:** Good - already a constant!

#### ML-028: Auto-heal timeouts
**File:** `server/auto_heal_decorator.py`
**Examples:**
- `timeout=10` (whoami check - line 133)
- `timeout=30` (kube-clean - line 138)
- `timeout=120` (kube login - line 144, 156, 198)
**Refactor:** Define `AUTO_HEAL_TIMEOUTS` dict.

#### ML-029: Stats retention limits
**File:** `server/auto_heal_decorator.py:246-258`
**Code:**
- `len(data["stats"]["daily"]) > 30` (30 days)
- `len(data["stats"]["weekly"]) > 12` (12 weeks)
- `len(data.get("failures", [])) > 100` (100 entries)
**Refactor:** Define `STATS_RETENTION` constants.

#### ML-030: Error snippet length
**File:** `server/auto_heal_decorator.py:75, 301`
**Code:** `error_snippet = output[:300]`, `error_snippet[:100]`
**Refactor:** Define `ERROR_SNIPPET_LENGTH` constant.

---

### PRIMITIVE_OBSESSION (Iteration 7)

#### PO-021: ClusterType as Literal
**File:** `server/auto_heal_decorator.py:50`
**Code:** `ClusterType = Literal["stage", "prod", "ephemeral", "konflux", "auto"]`
**Note:** Good - using Literal! Could be enum but Literal is fine.

#### PO-022: TriggerType enum
**File:** `scripts/common/command_parser.py:25-32`
**Note:** Good - already an enum!

---

### HARD_CODED_DEFAULTS (Iteration 7)

#### HD-023: VPN script path
**File:** `server/auto_heal_decorator.py:188`
**Code:** `vpn_script = os.path.expanduser("~/src/redhatter/src/redhatter_vpn/vpn-connect")`
**Note:** Same as HD-009 - duplicated hardcoded path.
**Refactor:** Single config source.

#### HD-024: Auth patterns
**File:** `server/auto_heal_decorator.py:27-37`
**Description:** `AUTH_PATTERNS` list is hardcoded.
**Note:** Acceptable for error detection, but could be config-driven for extensibility.

#### HD-025: Network patterns
**File:** `server/auto_heal_decorator.py:39-48`
**Description:** `NETWORK_PATTERNS` list is hardcoded.
**Note:** Same as HD-024.

---

### DATA_CLUMPS (Iteration 7)

#### DC-039: auto_heal retry context
**File:** `server/auto_heal_decorator.py:350-356`
**Description:** `tool_name`, `failure_type`, `error_snippet`, `cluster`, `result_str` always passed together.
**Refactor:** Create `HealContext` dataclass.

#### DC-040: ParsedCommand routing flags
**File:** `scripts/common/command_parser.py:64-65`
**Description:** `reply_dm` and `reply_thread` always set together.
**Refactor:** Create `ReplyRouting` enum or dataclass.

---

### LONG_METHOD (Iteration 7)

#### LM-015: async_wrapper in auto_heal
**File:** `server/auto_heal_decorator.py:428-480`
**Lines:** ~52 lines
**Severity:** Low
**Description:** Complex retry logic but well-structured with helper calls.
**Note:** Acceptable length given the complexity.

#### LM-016: _log_auto_heal_to_memory
**File:** `server/auto_heal_decorator.py:262-324`
**Lines:** ~62 lines
**Severity:** Low
**Description:** Memory logging with stats updates.
**Note:** Good use of helper functions `_update_rolling_stats()` and `_cleanup_old_stats()`.

---

### FEATURE_ENVY (Iteration 7)

#### FE-010: _detect_failure_type string matching
**File:** `server/auto_heal_decorator.py:53-85`
**Description:** Failure detection uses simple string matching on output.
**Note:** This is a reasonable approach, but could be more sophisticated with pattern registry.

---

### CONFIGURATION_SCATTERING (Iteration 7)

#### CS-011: Error patterns
**Files:** `server/auto_heal_decorator.py:27-48`, `tool_modules/aa_workflow/src/scheduler.py`
**Description:** Auth and network patterns defined in multiple places.
**Refactor:** Central `error_patterns.py` or config section.

---

### SPECULATIVE_GENERALITY (Iteration 7)

#### SG-008: retry_on parameter
**File:** `server/auto_heal_decorator.py:379`
**Code:** `retry_on: list[str] | None = None`
**Description:** Allows custom retry conditions but always uses default `["auth", "network"]`.
**Action:** Verify this flexibility is actually used or simplify.

#### SG-009: Convenience decorators
**File:** `server/auto_heal_decorator.py:493-506`
**Description:** `auto_heal_ephemeral()`, `auto_heal_stage()`, `auto_heal_konflux()` defined but may not be used.
**Action:** Verify usage or remove.

---

### DEAD_CODE (Iteration 7)

#### DD-011: sync_wrapper never healing
**File:** `server/auto_heal_decorator.py:414-424`
**Description:** Sync functions get wrapped but auto-healing is disabled for them.
**Note:** This is intentional per comments, but wrapper adds no value.
**Refactor:** Consider just returning `func` for sync functions.

---

### LACK_OF_CENTRALIZATION (Iteration 7)

#### LC-005: Kubeconfig path logic
**Files:** `server/utils.py`, `server/auto_heal_decorator.py`, `tool_modules/aa_k8s/src/tools_basic.py`
**Description:** Kubeconfig path construction scattered across files.
**Refactor:** Single `get_kubeconfig_path(cluster, namespace=None)` utility.

#### LC-006: VPN script path
**Files:** `server/auto_heal_decorator.py`, `tool_modules/aa_workflow/src/scheduler.py`
**Description:** VPN script path hardcoded in multiple places.
**Refactor:** Load from config.json once.

---

### FILE_LOCKING_ISSUES (Iteration 7)

#### FL-005: ConfigManager write lock
**File:** `server/config_manager.py:147-154`
**Description:** Uses `fcntl.LOCK_EX` for exclusive lock during write.
**Note:** Good implementation!

#### FL-006: No read lock
**File:** `server/config_manager.py:94`
**Description:** `_load()` reads file without acquiring read lock.
**Note:** Acceptable since writes use exclusive lock and we only read mtime to detect changes.

---

## Updated Priority Matrix (Iteration 7)

| Severity | Count | Key Items |
|----------|-------|-----------|
| Critical | 5 | LC-002, LC-005, LC-006, LC-007, LC-013 |
| High | 23 | LC-008, LC-010, DC-015-018, DC-022, DC-029-031, DC-036-037 |
| Medium | 68+ | Most other categories |
| Low | 30+ | DEAD_CODE, SPECULATIVE_GENERALITY, some PRIMITIVE_OBSESSION |

## Updated Totals by Category (Iteration 7)

| Category | Count |
|----------|-------|
| LARGE_CLASS | 14 |
| LONG_METHOD | 16 |
| MAGIC_LITERALS | 30 |
| PRIMITIVE_OBSESSION | 22 |
| DUPLICATE_CODE | 40 |
| CONFIGURATION_SCATTERING | 11 |
| HARD_CODED_DEFAULTS | 25 |
| DEAD_CODE | 11 |
| LONG_PARAMETER_LIST | 8 |
| FEATURE_ENVY | 10 |
| DATA_CLUMPS | 40 |
| INAPPROPRIATE_INTIMACY | 6 |
| SPECULATIVE_GENERALITY | 7 |
| SHOTGUN_SURGERY | 5 |
| LACK_OF_CENTRALIZATION | 6 |
| RACE_CONDITIONS | 11 |
| FILE_LOCKING_ISSUES | 6 |
| MEMORY_LEAKS | 5 |
| CIRCULAR_DEPENDENCIES | 2 |
| DIVERGENT_CHANGE | 3 |
| COMBINATORIAL_EXPLOSION | 5 |
| **WELL_DESIGNED** | 3 |

**TOTAL: 230+ code smell entries** (plus 3 positive examples)

## Key Takeaways from Iteration 7

1. **ConfigManager** is a good reference implementation for singleton patterns
2. **auto_heal decorator** is well-structured but has some duplication with utils.py
3. **Cluster/kubeconfig mapping** is scattered across 3+ files - high priority dedup
4. **Error patterns** could be centralized for easier maintenance
5. **VPN script path** hardcoded in 2+ places

---

## Additional Entries (Iteration 8)

### WELL-DESIGNED CODE (Positive Examples)

#### GOOD-004: ToolRegistry
**File:** `server/tool_registry.py`
**Lines:** ~99 lines
**Description:** Clean, focused registry with:
- Simple decorator pattern
- Tracks registered tools
- Supports `len()` and `in` operators
- No global state, uses instance
**Note:** Good example of single-responsibility class.

#### GOOD-005: CommandInfo/CommandHelp dataclasses
**File:** `scripts/common/command_registry.py:38-74, 76-130`
**Description:** Well-structured dataclasses with:
- Format methods for different outputs (Slack, text)
- Proper type hints
- to_dict() serialization
**Note:** Good pattern for structured command metadata.

---

### DUPLICATE_CODE (Iteration 8)

#### DC-041: Global singleton pattern (MAJOR)
**Files:** 35+ files using `global _variable` pattern
**Examples:**
- `server/persona_loader.py`: `global _loader`
- `scripts/common/command_registry.py`: `global _registry`
- `tool_modules/aa_workflow/src/scheduler.py`: `global _scheduler`
- `tool_modules/aa_workflow/src/notification_engine.py`: `global _notification_engine`
- `tool_modules/aa_workflow/src/poll_engine.py`: `global _poll_engine`
- `tool_modules/aa_slack/src/tools_basic.py`: `global _manager`
- `tool_modules/aa_meet_bot/src/notes_bot.py`: `global _notes_bot`
- And 25+ more...
**Problem:** Identical pattern repeated everywhere:
```python
_instance: Type | None = None

def get_instance() -> Type:
    global _instance
    if _instance is None:
        _instance = Type()
    return _instance
```
**Refactor:** Create `SingletonFactory` or use dependency injection container.

#### DC-042: Registry pattern
**Files:** `server/tool_registry.py`, `scripts/common/command_registry.py`
**Description:** Similar registry patterns for different purposes.
**Note:** Acceptable - they serve different needs, but could share base class.

#### DC-043: Cache invalidation pattern
**File:** `scripts/common/command_registry.py:207-209, 538-541`
**Description:** `_skills_cache` and `_tools_cache` with `clear_cache()` method.
**Note:** Good pattern, could be extracted to `CacheMixin`.

---

### MAGIC_LITERALS (Iteration 8)

#### ML-031: Display limits
**File:** `scripts/common/command_registry.py`
**Examples:**
- `[:20]` - Limit display in Slack (line 518)
- `[:60]` - Description truncation (line 520)
- `[:3]` - Examples limit (line 124, 148)
- `>= 3` - Related commands limit (line 481)
**Refactor:** Define `DISPLAY_LIMITS` dict.

#### ML-032: CONTEXTUAL_SKILLS set
**File:** `scripts/common/command_registry.py:162-168`
**Description:** Hardcoded set of skills that support contextual execution.
**Note:** Could be a skill property instead of hardcoded list.

---

### HARD_CODED_DEFAULTS (Iteration 8)

#### HD-026: BUILTIN_COMMANDS dict
**File:** `scripts/common/command_registry.py:171-190`
**Description:** Built-in commands hardcoded.
**Note:** Acceptable for truly built-in commands.

#### HD-027: Category name mappings
**File:** `scripts/common/command_registry.py:438-455`
**Description:** `_categorize_skill()` uses hardcoded string matching.
**Refactor:** Could use skill metadata or config.

---

### PRIMITIVE_OBSESSION (Iteration 8)

#### PO-023: format_type parameter
**File:** `scripts/common/command_registry.py:491`
**Code:** `format_type: str = "slack"` (also "text")
**Refactor:** Create `FormatType` enum.

---

### LONG_METHOD (Iteration 8)

#### LM-017: _get_skills
**File:** `scripts/common/command_registry.py:319-373`
**Lines:** ~54 lines
**Severity:** Low
**Description:** YAML parsing with error handling.
**Note:** Could extract `_parse_skill_file()` helper.

#### LM-018: format_slack (CommandHelp)
**File:** `scripts/common/command_registry.py:98-130`
**Lines:** ~32 lines
**Severity:** Low
**Description:** Complex formatting logic.
**Note:** Acceptable for formatting method.

#### LM-019: getSprintTabStyles (Iteration 12)
**File:** `extensions/aa_workflow_vscode/src/sprintTab.ts:298-816`
**Lines:** ~518 lines
**Severity:** High
**Description:** Massive template literal containing CSS. Returns a single string with all styles for the sprint tab.
**Keywords:** typescript, css-in-js, template-literal, styles
**Refactor:** Move to external `.css` file or use CSS modules.

#### LM-020: getSprintTabContent (Iteration 12)
**File:** `extensions/aa_workflow_vscode/src/sprintTab.ts:983-1243`
**Lines:** ~260 lines
**Severity:** Medium
**Description:** Single method generating entire HTML document with embedded JavaScript. Contains inline event handlers and script block.
**Keywords:** typescript, html-generation, inline-script
**Refactor:** Split rendering into smaller components: `renderHeader`, `renderSubtabs`, `renderIssueList`, etc.

#### LM-021: getWebviewContent (SkillToastWebview) (Iteration 12)
**File:** `extensions/aa_workflow_vscode/src/skillToast.ts:440-766`
**Lines:** ~326 lines
**Severity:** High
**Description:** Massive inline HTML template with embedded CSS (~150 lines) and JavaScript (~100 lines). Classic "mega template string" anti-pattern.
**Keywords:** typescript, inline-html, inline-css, inline-js, webview
**Refactor:** Use Vite/Webpack to bundle webview assets, or at minimum extract to separate template file.

#### LM-022: generateSunburstSVG (Iteration 12)
**File:** `extensions/aa_workflow_vscode/src/performanceTab.ts:549-641`
**Lines:** ~92 lines
**Severity:** Medium
**Description:** Complex SVG generation with hardcoded meta-categories, arc calculations, and path rendering all in one method.
**Keywords:** typescript, svg-generation, chart
**Refactor:** Extract `renderCenterCircle`, `renderCategoryArc`, `renderCompetencyArc` helper methods.

#### LM-023: loadToolGapRequests (Iteration 12)
**File:** `extensions/aa_workflow_vscode/src/sprintTab.ts:173-211`
**Lines:** ~38 lines
**Severity:** Medium
**Description:** Hand-rolled YAML parser with complex line-by-line parsing logic. Brittle and error-prone.
**Keywords:** typescript, yaml-parsing, manual-parser
**Refactor:** Use proper YAML parser library (js-yaml) instead of manual line parsing.

---

### FEATURE_ENVY (Iteration 8)

#### FE-011: _parse_tools_file regex parsing
**File:** `scripts/common/command_registry.py:403-436`
**Description:** Uses regex to parse Python files for tool definitions.
**Problem:** Fragile approach - should use AST or introspection.
**Refactor:** Use `inspect` module on loaded modules instead.

---

### RACE_CONDITIONS (Iteration 8)

#### RC-012: Global singleton creation (MAJOR)
**Files:** All 35+ files with global singleton pattern
**Description:** Non-thread-safe singleton initialization:
```python
def get_instance() -> Type:
    global _instance
    if _instance is None:  # Race condition here!
        _instance = Type()
    return _instance
```
**Mitigation:** Use `threading.Lock()` or atomic check-and-set.
**Note:** ConfigManager does this correctly with `_instance_lock`.

#### RC-013: Cache invalidation race
**File:** `scripts/common/command_registry.py:538-541`
**Description:** `clear_cache()` sets caches to None without locking.
**Mitigation:** Add lock or use atomic swap.

---

### DATA_CLUMPS (Iteration 8)

#### DC-044: CommandInfo fields
**File:** `scripts/common/command_registry.py:38-61`
**Description:** Many optional fields that could be grouped:
- `inputs` + `parameters` -> `ArgumentSpec`
- `examples` + `usage` -> `DocumentationSpec`
**Note:** Current design is acceptable, but could be more structured.

---

### SPECULATIVE_GENERALITY (Iteration 8)

#### SG-010: tool_modules_dir parameter
**File:** `scripts/common/command_registry.py:195-196`
**Description:** Constructor allows custom directories but likely always uses defaults.
**Action:** Verify if customization is used or simplify.

#### SG-011: category filter
**File:** `scripts/common/command_registry.py:215`
**Description:** `category` parameter but may not be used.
**Action:** Verify usage or remove.

---

### LACK_OF_CENTRALIZATION (Iteration 8)

#### LC-007: Singleton patterns
**Files:** 35+ files
**Description:** Each file implements its own singleton.
**Refactor:** Create `singleton` decorator or use DI container.

#### LC-008: PROJECT_ROOT definitions
**Files:** Many files define `PROJECT_ROOT = Path(__file__).parent...`
**Refactor:** Single `project_paths.py` module.

---

### CIRCULAR_DEPENDENCIES (Iteration 8)

#### CD-003: command_registry imports patterns
**File:** `scripts/common/command_registry.py`
**Note:** No circular imports detected in this file.
**Observation:** Good use of lazy loading for skills/tools.

---

## GLOBAL SINGLETON ANALYSIS

**35+ files use `global _variable` singleton pattern:**

| Module | Global Variable | Thread-Safe? |
|--------|-----------------|--------------|
| `server/config_manager.py` | `_instance` | ✅ Yes (Lock) |
| `server/persona_loader.py` | `_loader` | ❌ No |
| `server/websocket_server.py` | `_ws_server` | ❌ No |
| `scripts/common/command_registry.py` | `_registry` | ❌ No |
| `tool_modules/aa_workflow/src/scheduler.py` | `_scheduler` | ❌ No |
| `tool_modules/aa_workflow/src/notification_engine.py` | `_notification_engine` | ❌ No |
| `tool_modules/aa_workflow/src/poll_engine.py` | `_poll_engine` | ❌ No |
| `tool_modules/aa_workflow/src/chat_context.py` | `_chat_state` | ❌ No |
| `tool_modules/aa_slack/src/tools_basic.py` | `_manager` | ❌ No |
| `tool_modules/aa_meet_bot/src/notes_bot.py` | `_notes_bot` | ❌ No |
| `tool_modules/aa_meet_bot/src/tts_engine.py` | `_tts_engine` | ❌ No |
| ... | ... | ... |

**Recommendation:** Create `server/singletons.py` with thread-safe factory:
```python
from threading import Lock

_lock = Lock()
_instances: dict[str, Any] = {}

def get_singleton(cls: Type[T], *args, **kwargs) -> T:
    with _lock:
        key = cls.__name__
        if key not in _instances:
            _instances[key] = cls(*args, **kwargs)
        return _instances[key]
```

---

## Updated Priority Matrix (Iteration 8)

| Severity | Count | Key Items |
|----------|-------|-----------|
| Critical | 6 | LC-002, LC-005, LC-006, LC-007, LC-013, DC-041 |
| High | 25 | LC-007, RC-012, DC-041, plus previous high items |
| Medium | 70+ | Most other categories |
| Low | 32+ | DEAD_CODE, SPECULATIVE_GENERALITY |

## Updated Totals by Category (Iteration 8)

| Category | Count |
|----------|-------|
| LARGE_CLASS | 14 |
| LONG_METHOD | 18 |
| MAGIC_LITERALS | 32 |
| PRIMITIVE_OBSESSION | 23 |
| DUPLICATE_CODE | 44 |
| CONFIGURATION_SCATTERING | 11 |
| HARD_CODED_DEFAULTS | 27 |
| DEAD_CODE | 11 |
| LONG_PARAMETER_LIST | 8 |
| FEATURE_ENVY | 11 |
| DATA_CLUMPS | 44 |
| INAPPROPRIATE_INTIMACY | 6 |
| SPECULATIVE_GENERALITY | 9 |
| SHOTGUN_SURGERY | 5 |
| LACK_OF_CENTRALIZATION | 8 |
| RACE_CONDITIONS | 13 |
| FILE_LOCKING_ISSUES | 6 |
| MEMORY_LEAKS | 5 |
| CIRCULAR_DEPENDENCIES | 3 |
| DIVERGENT_CHANGE | 3 |
| COMBINATORIAL_EXPLOSION | 5 |
| **WELL_DESIGNED** | 5 |

**TOTAL: 245+ code smell entries** (plus 5 positive examples)

## Key Takeaways from Iteration 8

1. **MAJOR FINDING: 35+ files use non-thread-safe global singleton pattern**
   - Only `ConfigManager` does it correctly with Lock
   - This is a systemic issue across the codebase
   - High risk of race conditions in concurrent usage

2. **ToolRegistry and CommandRegistry are well-designed**
   - Good separation of concerns
   - Clean public APIs
   - Could share base class

3. **Regex-based tool parsing is fragile**
   - `_parse_tools_file()` uses regex to extract tool definitions
   - Should use Python AST or introspection instead

4. **Singleton factory would deduplicate ~35 files**
   - Single biggest deduplication opportunity
   - Also fixes thread-safety issues

---

## Additional Entries (Iteration 9)

### WELL-DESIGNED CODE (Positive Examples)

#### GOOD-006: OllamaClient
**File:** `tool_modules/aa_ollama/src/client.py`
**Lines:** ~400 lines
**Description:** Well-designed HTTP client with:
- Proper caching with TTL (`_check_interval`)
- Latency tracking with bounded buffer (`_max_samples`)
- Fallback chain pattern (`get_available_client`)
- Factory pattern with dict cache (not global singleton!)
- Clean status/metrics API
**Note:** Good example of caching done right.

#### GOOD-007: Konflux tools organization
**File:** `tool_modules/aa_konflux/src/tools_basic.py`
**Description:** Well-organized tool module with:
- Clear separation: `_register_status_tools`, `_register_list_tools`, etc.
- Consistent `_*_impl` pattern for testable implementations
- Uses `@auto_heal_konflux()` decorator consistently
**Note:** Good pattern for organizing many similar tools.

---

### DUPLICATE_CODE (Iteration 9)

#### DC-045: Konflux kubectl get pattern
**File:** `tool_modules/aa_konflux/src/tools_basic.py`
**Description:** 15+ functions follow identical pattern:
```python
success, output = await run_cmd(["kubectl", "get", RESOURCE, "-n", namespace, "-o", "wide"])
if not success:
    return f"❌ Failed: {output}"
return f"## {Title}: {namespace}\n\n```\n{output}\n```"
```
**Refactor:** Create `_get_resource(resource_type, namespace, title)` helper.

#### DC-046: Line limiting pattern
**File:** `tool_modules/aa_konflux/src/tools_basic.py:169-172, 216-218, 261-263, 284-286, 308-310`
**Description:** Same pattern repeated 5+ times:
```python
lines = output.strip().split("\n")
if len(lines) > limit + 1:
    lines = lines[:1] + lines[-(limit):]
```
**Refactor:** Create `limit_output_lines(output, limit)` helper.

#### DC-047: Double @auto_heal_konflux decorator
**File:** `tool_modules/aa_konflux/src/tools_basic.py`
**Description:** Every tool has `@auto_heal_konflux()` twice - once on `_impl` and once on registered tool.
**Refactor:** Only apply once on `_impl`, or only on registered tool.

#### DC-048: Client factory pattern
**File:** `tool_modules/aa_ollama/src/client.py:295-309`
**Description:** Dict-based client caching pattern:
```python
_clients: dict[str, Client] = {}

def get_client(name: str) -> Client:
    if name not in _clients:
        _clients[name] = Client(name)
    return _clients[name]
```
**Note:** This is BETTER than global singleton - allows multiple instances.
**Recommendation:** Use this pattern instead of global singletons elsewhere.

---

### MAGIC_LITERALS (Iteration 9)

#### ML-033: OllamaClient defaults
**File:** `tool_modules/aa_ollama/src/client.py`
**Examples:**
- `timeout: float = 30.0`
- `connect_timeout: float = 5.0`
- `_check_interval: float = 30.0`
- `_max_samples: int = 100`
- `"keep_alive": "30m"`
**Refactor:** Define `OLLAMA_TIMEOUTS` and `OLLAMA_DEFAULTS` constants.

#### ML-034: Konflux truncation limits
**File:** `tool_modules/aa_konflux/src/tools_basic.py`
**Examples:**
- `max_length=20000` (build logs - lines 101, 445)
- `max_length=10000` (component, release, describe - lines 116, 125, 414)
**Refactor:** Define `KONFLUX_OUTPUT_LIMITS` constants.

#### ML-035: Default limit parameter
**File:** `tool_modules/aa_konflux/src/tools_basic.py`
**Description:** `limit: int = 10` appears 8+ times.
**Note:** Acceptable as parameter default.

---

### COMBINATORIAL_EXPLOSION (Iteration 9)

#### CE-006: Konflux resource getters
**File:** `tool_modules/aa_konflux/src/tools_basic.py`
**Description:** Separate functions for:
- `_konflux_list_applications_impl`
- `_konflux_list_builds_impl`
- `_konflux_list_components_impl`
- `_konflux_list_integration_tests_impl`
- `_konflux_list_pipelines_impl`
- `_konflux_list_releases_impl`
- `_konflux_list_snapshots_impl`
And matching `_konflux_get_*_impl` functions.
All essentially call kubectl with different resource types.
**Refactor:** Generic `_konflux_list_resource_impl(resource_type, ...)`.

#### CE-007: Tekton management tools
**File:** `tool_modules/aa_konflux/src/tools_basic.py:391-454`
**Description:** Separate functions for cancel, delete, describe, logs.
**Refactor:** Could use command pattern.

---

### HARD_CODED_DEFAULTS (Iteration 9)

#### HD-028: DEFAULT_NAMESPACE from env
**File:** `tool_modules/aa_konflux/src/tools_basic.py:44`
**Code:** `DEFAULT_NAMESPACE = os.getenv("KONFLUX_NAMESPACE", "default")`
**Note:** Good - uses env var with fallback.

#### HD-029: Fallback chain
**File:** `tool_modules/aa_ollama/src/client.py:331`
**Code:** `fallback_chain = ["igpu", "nvidia", "cpu"]`
**Refactor:** Could be config-driven.

---

### PRIMITIVE_OBSESSION (Iteration 9)

#### PO-024: Instance name strings
**File:** `tool_modules/aa_ollama/src/client.py`
**Examples:** `"npu"`, `"igpu"`, `"nvidia"`, `"cpu"`
**Refactor:** Create `OllamaInstanceType` enum.

---

### DATA_CLUMPS (Iteration 9)

#### DC-049: kubectl command args
**File:** `tool_modules/aa_konflux/src/tools_basic.py`
**Description:** `["kubectl", "get", resource, "-n", namespace, "-o", "wide", "--sort-by=.metadata.creationTimestamp"]` repeated many times.
**Refactor:** Create `KubectlGetArgs` builder.

#### DC-050: OllamaClient config
**File:** `tool_modules/aa_ollama/src/client.py:21-26`
**Description:** `instance`, `timeout`, `connect_timeout` always grouped.
**Note:** Already passed to constructor - acceptable.

---

### MEMORY_LEAKS (Iteration 9)

#### MEM-006: _clients dict unbounded
**File:** `tool_modules/aa_ollama/src/client.py:295`
**Description:** `_clients` dict grows without bound.
**Note:** In practice limited by number of instances, but no explicit cleanup.
**Mitigation:** Add `clear_clients()` function (already exists - line 364).

#### MEM-007: _latency_samples bounded
**File:** `tool_modules/aa_ollama/src/client.py:44-45, 259-263`
**Description:** `_latency_samples` capped at `_max_samples = 100`.
**Note:** Good - properly bounded!

### MEMORY_LEAKS (Iteration 12)

#### MEM-008: SkillToastManager event subscriptions
**File:** `extensions/aa_workflow_vscode/src/skillToast.ts:59-137`
**Description:** Event handlers subscribed in `setupEventHandlers()` but only statusBarItem and outputChannel disposed:
```typescript
// In setupEventHandlers():
this.wsClient.onSkillStarted((skill) => { ... });  // No unsubscribe
this.wsClient.onSkillUpdate((skill) => { ... });   // No unsubscribe
// ...
// In dispose():
dispose(): void {
  this.statusBarItem.dispose();
  this.outputChannel.dispose();
  // Missing: event subscription cleanup!
}
```
**Keywords:** typescript, vscode, memory-leak, event-subscription
**Refactor:** Store subscriptions in `context.subscriptions` or use `Disposable` pattern.

#### MEM-009: SkillToastWebview event subscriptions
**File:** `extensions/aa_workflow_vscode/src/skillToast.ts:408-410`
**Description:** Event subscriptions created but never disposed:
```typescript
this.wsClient.onSkillUpdate(() => this.updateWebview());
this.wsClient.onConfirmationRequired(() => this.updateWebview());
this.wsClient.onConfirmationResolved(() => this.updateWebview());
```
**Keywords:** typescript, webview, memory-leak, event-subscription
**Refactor:** Store returned Disposable and clean up in `dispose()`.

#### MEM-010: skills Map retained after completion
**File:** `extensions/aa_workflow_vscode/src/skillWebSocket.ts:338-340`
**Description:** Skills are kept for 10 seconds after completion via setTimeout. If many skills complete rapidly, memory accumulates.
**Note:** Low severity - 10 second delay is reasonable, and skills are deleted.
**Keywords:** typescript, timeout, map, bounded

---

### SHOTGUN_SURGERY (Iteration 9)

#### SS-006: Adding new Konflux resource type
**Files affected:** `tools_basic.py`
**Description:** Adding support for a new Konflux resource requires:
1. New `_konflux_list_*_impl` function
2. New `_konflux_get_*_impl` function
3. Two new registered tools
4. Possibly update `_konflux_namespace_summary_impl`
**Refactor:** Generic resource handler.

---

### FEATURE_ENVY (Iteration 9)

#### FE-012: classify parsing result
**File:** `tool_modules/aa_ollama/src/client.py:188-203`
**Description:** `classify()` parses LLM output to extract category.
**Note:** Acceptable - this is the client's job.

---

### SPECULATIVE_GENERALITY (Iteration 9)

#### SG-012: stream parameter unused
**File:** `tool_modules/aa_ollama/src/client.py:106`
**Code:** `stream: bool = False,` but always set to False (line 134).
**Action:** Remove parameter if not implementing streaming.

#### SG-013: system parameter
**File:** `tool_modules/aa_ollama/src/client.py:109`
**Description:** `system` parameter passed but may rarely be used.
**Note:** Keep - useful for flexibility.

---

### DEAD_CODE (Iteration 9)

#### DD-012: __project_root__ assignment
**File:** `tool_modules/aa_konflux/src/tools_basic.py:15`
**Code:** `__project_root__ = PROJECT_ROOT  # Module initialization`
**Description:** Assigned but never used.
**Refactor:** Remove or add explanatory comment.

---

## Updated Priority Matrix (Iteration 9)

| Severity | Count | Key Items |
|----------|-------|-----------|
| Critical | 6 | LC-002, LC-005, LC-006, LC-007, LC-013, DC-041 |
| High | 27 | Previous + DC-045, DC-046, CE-006 |
| Medium | 75+ | Most other categories |
| Low | 35+ | DEAD_CODE, SPECULATIVE_GENERALITY |

## Updated Totals by Category (Iteration 9)

| Category | Count |
|----------|-------|
| LARGE_CLASS | 14 |
| LONG_METHOD | 18 |
| MAGIC_LITERALS | 35 |
| PRIMITIVE_OBSESSION | 24 |
| DUPLICATE_CODE | 50 |
| CONFIGURATION_SCATTERING | 11 |
| HARD_CODED_DEFAULTS | 29 |
| DEAD_CODE | 12 |
| LONG_PARAMETER_LIST | 8 |
| FEATURE_ENVY | 12 |
| DATA_CLUMPS | 50 |
| INAPPROPRIATE_INTIMACY | 6 |
| SPECULATIVE_GENERALITY | 11 |
| SHOTGUN_SURGERY | 6 |
| LACK_OF_CENTRALIZATION | 8 |
| RACE_CONDITIONS | 13 |
| FILE_LOCKING_ISSUES | 6 |
| MEMORY_LEAKS | 7 |
| CIRCULAR_DEPENDENCIES | 3 |
| DIVERGENT_CHANGE | 3 |
| COMBINATORIAL_EXPLOSION | 7 |
| **WELL_DESIGNED** | 7 |

**TOTAL: 260+ code smell entries** (plus 7 positive examples)

## Key Takeaways from Iteration 9

1. **OllamaClient uses dict-based client factory** - better pattern than global singletons
   - Recommend using this pattern across the codebase

2. **Konflux tools have massive duplication** - 15+ nearly identical kubectl get functions
   - Single generic handler could eliminate 50%+ of code

3. **Double decorator anti-pattern** - `@auto_heal_konflux()` applied twice per tool
   - Should only apply once

4. **Latency samples properly bounded** - good example of preventing memory leaks

5. **Line limiting pattern repeated 5+ times** - easy refactor to helper function

---

## FINAL SUMMARY

After 9 iterations, the exhaustive code smell analysis has identified:

### Critical Issues (6)
1. **LC-002**: ToolExecutor ~900 lines
2. **LC-005**: workspace_state.py ~2400 lines
3. **LC-006**: aa_meet_bot/tools_basic.py 2134 lines
4. **LC-007**: commandCenter.ts 2000+ lines
5. **LC-013**: slack_daemon.py 2500+ lines (102KB)
6. **DC-041**: 35+ files with non-thread-safe global singleton

### High-Impact Refactoring Opportunities
1. **Singleton Factory**: Deduplicate 35+ files and fix race conditions
2. **Generic Resource Handlers**: Eliminate 50%+ of kubectl/Konflux code
3. **Constants Extraction**: 35+ magic literal categories
4. **Dataclass Creation**: 50+ data clump patterns

### Well-Designed Patterns to Replicate
1. ConfigManager (thread-safe singleton)
2. OllamaClient (dict-based factory)
3. auto_heal decorator (helper extraction)
4. ToolRegistry (clean decorator pattern)
5. ParsedCommand (structured dataclass)

---

## Additional Entries (Iteration 10)

### WELL-DESIGNED CODE (Positive Examples)

#### GOOD-008: UsagePatternStorage
**File:** `server/usage_pattern_storage.py`
**Lines:** ~341 lines
**Description:** Well-designed YAML persistence with:
- Automatic initialization on first use
- Pruning of old patterns (`prune_old_patterns`)
- Statistics auto-update on save (`_update_stats`)
- Proper error handling with specific exceptions
- File creation safety (`mkdir(parents=True, exist_ok=True)`)
**Note:** Good pattern for file-based persistence.

#### GOOD-009: ToolManifest dataclass
**File:** `server/tool_discovery.py:48-108`
**Description:** Clean dataclass-based registry with:
- Freeze capability to prevent late registration
- Module-to-tool mapping
- Clear method for testing
- Proper encapsulation
**Note:** Good pattern for decorator-based auto-registration.

#### GOOD-010: ToolTier enum
**File:** `server/tool_discovery.py:41-45`
**Description:** Simple enum for tool classification.
**Note:** Good - avoids string primitive obsession!

#### GOOD-011: SkillWebSocketClient event emitters (Iteration 12)
**File:** `extensions/aa_workflow_vscode/src/skillWebSocket.ts:67-83`
**Description:** Clean event emitter pattern using VS Code's EventEmitter:
```typescript
private _onSkillStarted = new vscode.EventEmitter<SkillState>();
private _onSkillUpdate = new vscode.EventEmitter<SkillState>();
// ...
public readonly onSkillStarted = this._onSkillStarted.event;
```
**Why it's good:**
- Private emitters with public read-only event accessors
- Type-safe generic event types
- Follows VS Code extension patterns
- Clean separation of producer/consumer
**Keywords:** typescript, event-emitter, vscode, design-pattern

#### GOOD-012: SkillWebSocketClient dispose method (Iteration 12)
**File:** `extensions/aa_workflow_vscode/src/skillWebSocket.ts:493-521`
**Description:** Comprehensive cleanup that disposes all resources:
```typescript
dispose(): void {
  this.ws?.close();
  if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
  if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
  this.confirmationTimers.forEach((timer) => clearInterval(timer));
  // ... dispose all event emitters
}
```
**Why it's good:**
- Clears all timers and intervals
- Disposes all event emitters
- Clears all Maps
- Null-safe with optional chaining
**Keywords:** typescript, dispose, cleanup, resource-management

---

### MAGIC_LITERALS (Iteration 10)

#### ML-036: Confidence thresholds
**File:** `server/usage_pattern_storage.py`
**Examples:**
- `min_confidence: float = 0.85` (high confidence threshold - lines 206, 260)
- `0.70 <= p.get("confidence", 0.0) < 0.85` (medium - line 261)
- `p.get("confidence", 0.0) < 0.70` (low - line 262)
- `min_confidence: float = 0.70` (prune threshold - line 295)
**Refactor:** Define `CONFIDENCE_THRESHOLDS` dict with `HIGH`, `MEDIUM`, `LOW` keys.

#### ML-037: Prune age
**File:** `server/usage_pattern_storage.py:295`
**Code:** `max_age_days: int = 90`
**Refactor:** Define `DEFAULT_PATTERN_MAX_AGE_DAYS` constant.

### MAGIC_LITERALS (Iteration 12)

#### ML-038: WebSocket port
**File:** `extensions/aa_workflow_vscode/src/skillWebSocket.ts:87`
**Code:** `constructor(private readonly port: number = 9876)`
**Keywords:** typescript, websocket, port, magic-number
**Refactor:** Use environment variable or configuration setting.

#### ML-039: Reconnect/heartbeat intervals
**File:** `extensions/aa_workflow_vscode/src/skillWebSocket.ts:143-151`
**Code:**
```typescript
setTimeout(() => { ... }, 5000);  // Reconnect delay
setInterval(() => { ... }, 30000);  // Heartbeat interval
```
**Keywords:** typescript, websocket, timeout, magic-number
**Refactor:** Define as named constants: `RECONNECT_DELAY_MS`, `HEARTBEAT_INTERVAL_MS`.

#### ML-040: Skill cleanup delay
**File:** `extensions/aa_workflow_vscode/src/skillWebSocket.ts:338`
**Code:** `setTimeout(() => { this.skills.delete(skillId); }, 10000);`
**Keywords:** typescript, timeout, magic-number
**Refactor:** Define `SKILL_CLEANUP_DELAY_MS` constant.

#### ML-041: Confirmation timeout default
**File:** `extensions/aa_workflow_vscode/src/skillWebSocket.ts:376`
**Code:** `const timeoutSeconds = (data.timeout_seconds as number) || 30;`
**Keywords:** typescript, timeout, default-value
**Refactor:** Define `DEFAULT_CONFIRMATION_TIMEOUT_SECONDS` constant.

#### ML-042: SVG chart dimensions
**File:** `extensions/aa_workflow_vscode/src/performanceTab.ts:550-556`
**Code:**
```typescript
const width = 350;
const height = 350;
const cx = width / 2;
const cy = height / 2;
const innerRadius = 55;
const middleRadius = 100;
const outerRadius = 145;
```
**Keywords:** typescript, svg, chart, dimensions, magic-number
**Note:** Reasonable to define as local constants, but could be configurable.

#### ML-043: Meta-categories hardcoded
**File:** `extensions/aa_workflow_vscode/src/performanceTab.ts:562-579`
**Description:** Competency categories hardcoded in array literal:
```typescript
const metaCategories = [
  { id: "technical_excellence", competencies: ["technical_contribution", ...] },
  { id: "leadership_influence", competencies: ["leadership", ...] },
  { id: "delivery_impact", competencies: ["portfolio_impact", ...] },
];
```
**Keywords:** typescript, hardcoded-data, competencies, configuration
**Refactor:** Load from configuration file or API to allow customization.

#### ML-044: Quarter days calculation
**File:** `extensions/aa_workflow_vscode/src/performanceTab.ts:765`
**Code:** `const quarterProgress = Math.round((state.day_of_quarter / 90) * 100);`
**Keywords:** typescript, magic-number, quarter
**Refactor:** Define `DAYS_PER_QUARTER = 90` constant (or calculate dynamically for accuracy).

#### ML-045: Color percentage thresholds
**File:** `extensions/aa_workflow_vscode/src/performanceTab.ts:133-138`
**Code:**
```typescript
if (pct >= 80) return "#10b981"; // Green
if (pct >= 50) return "#f59e0b"; // Yellow
if (pct >= 25) return "#f97316"; // Orange
return "#ef4444"; // Red
```
**Keywords:** typescript, magic-number, threshold, color
**Refactor:** Define `THRESHOLDS = { excellent: 80, good: 50, fair: 25 }` object.

#### ML-046: Status bar priority
**File:** `extensions/aa_workflow_vscode/src/skillToast.ts:35-38`
**Code:** `vscode.StatusBarAlignment.Right, 100`
**Keywords:** typescript, vscode, magic-number
**Note:** Low priority - common pattern in VS Code extensions.

---

### HARD_CODED_DEFAULTS (Iteration 10)

#### HD-030: Pattern categories
**File:** `server/usage_pattern_storage.py:51-56, 272-278`
**Description:** Error categories hardcoded in two places:
```python
"by_category": {
    "INCORRECT_PARAMETER": 0,
    "PARAMETER_FORMAT": 0,
    "MISSING_PREREQUISITE": 0,
    "WORKFLOW_SEQUENCE": 0,
    "WRONG_TOOL_SELECTION": 0,
}
```
**Refactor:** Create `ErrorCategory` enum and reference it.

#### HD-031: Default patterns file path
**File:** `server/usage_pattern_storage.py:31-32`
**Code:** `patterns_file = project_root / "memory" / "learned" / "usage_patterns.yaml"`
**Note:** Good - uses project-relative path.

---

### DUPLICATE_CODE (Iteration 10)

#### DC-051: Broad exception handling
**Files:** `server/usage_pattern_storage.py:77, 101, 132, 169, 245, 338`
**Description:** Same exception tuple repeated 6 times:
```python
except (OSError, yaml.YAMLError, ValueError, KeyError, TypeError) as e:
```
**Refactor:** Define `YAML_EXCEPTIONS = (OSError, yaml.YAMLError, ...)` constant.

#### DC-052: Stats category iteration
**File:** `server/usage_pattern_storage.py:272-282`
**Description:** Iterates over hardcoded category list.
**Refactor:** Use `ErrorCategory` enum to iterate.

---

### PRIMITIVE_OBSESSION (Iteration 10)

#### PO-025: Error categories as strings
**File:** `server/usage_pattern_storage.py:51-56`
**Description:** Categories like `"INCORRECT_PARAMETER"` are raw strings.
**Refactor:** Create `ErrorCategory` enum.

#### PO-026: tier as string
**File:** `server/tool_discovery.py:117`
**Code:** `tier: str | ToolTier = ToolTier.BASIC`
**Note:** Accepts both string and enum - converts internally.
**Observation:** Good design - flexible input, strong internal typing.

---

### DATA_CLUMPS (Iteration 10)

#### DC-053: Pattern CRUD operations
**File:** `server/usage_pattern_storage.py`
**Description:** `load()`, `save()`, `add_pattern()`, `update_pattern()`, `delete_pattern()` all work with same data structure.
**Note:** Already well-organized in class - acceptable.

#### DC-054: Non-thread-safe TypeScript singleton (Iteration 12)
**File:** `extensions/aa_workflow_vscode/src/skillWebSocket.ts:526-540`
**Description:** Global `_instance` singleton pattern identical to Python version:
```typescript
let _instance: SkillWebSocketClient | null = null;

export function getSkillWebSocketClient(): SkillWebSocketClient {
  if (!_instance) {
    _instance = new SkillWebSocketClient();
  }
  return _instance;
}
```
**Keywords:** typescript, singleton, global-state, skillwebsocket
**Note:** Acceptable in single-threaded JS/TS, but creates hidden global state.

#### DC-055: Duplicate loadUnifiedState helper (Iteration 12)
**Files:**
- `extensions/aa_workflow_vscode/src/sprintTab.ts:118-128`
- `extensions/aa_workflow_vscode/src/performanceTab.ts:74-84`
**Description:** Identical file loading function duplicated in both tab files:
```typescript
function loadUnifiedState(): Record<string, unknown> {
  try {
    if (fs.existsSync(WORKSPACE_STATE_FILE)) {
      const content = fs.readFileSync(WORKSPACE_STATE_FILE, "utf-8");
      return JSON.parse(content);
    }
  } catch (e) { ... }
  return {};
}
```
**Keywords:** typescript, file-loading, duplicate, unified-state
**Refactor:** Extract to shared `stateLoader.ts` module.

#### DC-056: Duplicate escapeHtml helper (Iteration 12)
**Files:**
- `extensions/aa_workflow_vscode/src/sprintTab.ts:215-222`
- `extensions/aa_workflow_vscode/src/performanceTab.ts:124-131`
**Description:** Identical HTML escaping function in both files.
**Keywords:** typescript, html-escape, utility, duplicate
**Refactor:** Move to shared `utils.ts` or use DOMPurify library.

#### DC-057: CSS variable definitions (Iteration 12)
**Files:**
- `extensions/aa_workflow_vscode/src/sprintTab.ts:298-816` (styles)
- `extensions/aa_workflow_vscode/src/performanceTab.ts:155-544` (styles)
- `extensions/aa_workflow_vscode/src/skillToast.ts:443-607` (styles)
**Description:** All three webview components define similar CSS variables and base styles (`--card-bg`, `--border-color`, `--text-primary`, etc.). Each file has 150-500 lines of inline CSS.
**Keywords:** typescript, css, duplicate-styles, webview
**Refactor:** Create shared `webviewStyles.ts` with base theme variables.

---

### SPECULATIVE_GENERALITY (Iteration 10)

#### SG-014: freeze() method
**File:** `server/tool_discovery.py:100-102`
**Description:** `freeze()` prevents registration but may not be called in practice.
**Action:** Verify usage or remove.

#### SG-015: clear() method
**File:** `server/tool_discovery.py:104-108`
**Description:** `clear()` for testing - appropriate.
**Note:** Keep - useful for test isolation.

---

### DEAD_CODE (Iteration 10)

#### DD-013: _frozen check without freeze call
**File:** `server/tool_discovery.py:70-72`
**Description:** Checks `_frozen` but `freeze()` may never be called.
**Action:** Verify if freeze is used or remove check.

---

## server/ DIRECTORY ANALYSIS

The `server/` directory contains many specialized modules:

| File | Purpose | Analyzed? |
|------|---------|-----------|
| `utils.py` | Command execution, formatting | ✅ LC-010 |
| `config_manager.py` | Thread-safe config singleton | ✅ GOOD-001 |
| `auto_heal_decorator.py` | Self-healing tool wrapper | ✅ GOOD-003 |
| `tool_registry.py` | FastMCP tool registration | ✅ GOOD-004 |
| `tool_discovery.py` | Decorator-based tool manifest | ✅ GOOD-009, GOOD-010 |
| `usage_pattern_storage.py` | YAML pattern persistence | ✅ GOOD-008 |
| `workspace_state.py` | Session/workspace management | ✅ LC-005 (Critical) |
| `persona_loader.py` | Dynamic persona loading | ⚠️ Has global singleton |
| `websocket_server.py` | Real-time updates | ⚠️ Has global singleton |
| `usage_pattern_*.py` (7 files) | Layer 5 usage learning | ❓ Not fully analyzed |

### Key Finding: Multiple Well-Designed Modules
The `server/` directory contains several well-designed modules (ConfigManager, UsagePatternStorage, ToolManifest) that should serve as patterns for the rest of the codebase.

---

## Updated Totals by Category (Iteration 12)

| Category | Count | Iteration 12 Additions |
|----------|-------|------------------------|
| LARGE_CLASS | 17 | +3 (sprintTab.ts, performanceTab.ts, SkillToastWebview) |
| LONG_METHOD | 23 | +5 (getSprintTabStyles, getWebviewContent, etc.) |
| MAGIC_LITERALS | 46 | +9 (WebSocket port, timeouts, SVG dimensions, etc.) |
| PRIMITIVE_OBSESSION | 26 | - |
| DUPLICATE_CODE | 57 | +4 (loadUnifiedState, escapeHtml, CSS variables) |
| CONFIGURATION_SCATTERING | 11 | - |
| HARD_CODED_DEFAULTS | 31 | - |
| DEAD_CODE | 13 | - |
| LONG_PARAMETER_LIST | 8 | - |
| FEATURE_ENVY | 12 | - |
| DATA_CLUMPS | 53 | - |
| INAPPROPRIATE_INTIMACY | 6 | - |
| SPECULATIVE_GENERALITY | 13 | - |
| SHOTGUN_SURGERY | 6 | - |
| LACK_OF_CENTRALIZATION | 8 | - |
| RACE_CONDITIONS | 13 | - |
| FILE_LOCKING_ISSUES | 6 | - |
| MEMORY_LEAKS | 10 | +3 (event subscription leaks in skillToast.ts) |
| CIRCULAR_DEPENDENCIES | 3 | - |
| DIVERGENT_CHANGE | 3 | - |
| COMBINATORIAL_EXPLOSION | 7 | - |
| **WELL_DESIGNED** | 12 | +2 (event emitters, dispose pattern) |

**TOTAL: 295+ code smell entries** (plus 12 positive examples)

---

## COMPREHENSIVE FINAL SUMMARY

After 12 iterations of exhaustive code smell analysis:

### Critical Issues (6)
1. **LC-002**: ToolExecutor ~900 lines
2. **LC-005**: workspace_state.py ~2400 lines
3. **LC-006**: aa_meet_bot/tools_basic.py 2134 lines
4. **LC-007**: commandCenter.ts 2000+ lines
5. **LC-013**: slack_daemon.py 2500+ lines (102KB)
6. **DC-041**: 35+ files with non-thread-safe global singleton

### Top 6 Refactoring Opportunities
1. **Singleton Factory**: Deduplicate 35+ files and fix race conditions
2. **Generic Resource Handlers**: Eliminate 50%+ of kubectl/Konflux/K8s code
3. **Constants Module**: Extract 46+ magic literal categories
4. **Dataclass Creation**: Group 53+ data clump patterns
5. **Enum Creation**: Replace 26+ primitive type strings
6. **Shared Webview Styles**: Extract 1500+ lines of duplicate CSS from TS files

### Well-Designed Patterns (12 Examples)
1. ConfigManager - thread-safe singleton
2. OllamaClient - dict-based factory with caching
3. auto_heal decorator - helper extraction pattern
4. ToolRegistry - clean decorator pattern
5. ParsedCommand - structured dataclass
6. Konflux tool organization - _register_*_tools pattern
7. UsagePatternStorage - YAML persistence with pruning
8. ToolManifest - decorator-based auto-registration
9. CommandInfo/CommandHelp - format methods
10. ToolTier enum - avoiding primitive obsession
11. SkillWebSocketClient event emitters - private/public pattern
12. SkillWebSocketClient dispose - comprehensive cleanup

### Analysis Coverage
- **Files analyzed**: 50+ across server/, scripts/, tool_modules/, extensions/
- **Iterations**: 12
- **Total entries**: 295+ code smells + 12 positive examples
- **Categories covered**: All 22 requested categories

### Iteration 12 Focus: TypeScript/VSCode Extension
New files analyzed in iteration 12:
- `extensions/aa_workflow_vscode/src/sprintTab.ts` (1257 lines)
- `extensions/aa_workflow_vscode/src/performanceTab.ts` (904 lines)
- `extensions/aa_workflow_vscode/src/skillWebSocket.ts` (541 lines)
- `extensions/aa_workflow_vscode/src/skillToast.ts` (772 lines)

Key findings:
- Large inline CSS/HTML templates (500+ lines each)
- Duplicate helper functions across webview files
- Event subscription memory leaks
- Good event emitter and dispose patterns to replicate

---

## KEYWORD INDEX

For easy searching and deduplication, use these keywords:

### By Entry ID
```
LC-001 to LC-017: Large Class entries (+3 in iteration 12)
LM-001 to LM-023: Long Method entries (+5 in iteration 12)
ML-001 to ML-046: Magic Literals entries (+9 in iteration 12)
PO-001 to PO-026: Primitive Obsession entries
DC-001 to DC-057: Duplicate Code entries (+4 in iteration 12)
CS-001 to CS-011: Configuration Scattering entries
HD-001 to HD-031: Hard-Coded Defaults entries
DD-001 to DD-013: Dead Code entries
LP-001 to LP-008: Long Parameter List entries
FE-001 to FE-012: Feature Envy entries
RC-001 to RC-013: Race Conditions entries
FL-001 to FL-006: File Locking Issues entries
MEM-006 to MEM-010: Memory Leaks entries (+3 in iteration 12)
CD-001 to CD-003: Circular Dependencies entries
SS-001 to SS-006: Shotgun Surgery entries
SG-001 to SG-015: Speculative Generality entries
DV-001 to DV-003: Divergent Change entries
CE-001 to CE-007: Combinatorial Explosion entries
II-001 to II-006: Inappropriate Intimacy entries
GOOD-001 to GOOD-012: Well-Designed examples (+2 in iteration 12)
```

### By File (Most Referenced)
```
server/utils.py: LC-010, DC-022-024, ML-018-019, HD-018-019
server/workspace_state.py: LC-005 (CRITICAL)
server/config_manager.py: GOOD-001
server/auto_heal_decorator.py: GOOD-003, DC-036-037, ML-028-030
scripts/claude_agent.py: LC-001, LC-002, LC-003
scripts/slack_daemon.py: LC-013 (CRITICAL)
scripts/cron_daemon.py: LC-014, DC-029-031
scripts/common/dbus_base.py: DC-025, ML-020-021, RC-009-010
tool_modules/aa_meet_bot/src/tools_basic.py: LC-006 (CRITICAL)
tool_modules/aa_slack/src/tools_basic.py: CE-002, DC-008-010
tool_modules/aa_konflux/src/tools_basic.py: DC-045-047, CE-006-007
tool_modules/aa_ollama/src/client.py: GOOD-006, DC-048
extensions/aa_workflow_vscode/src/sprintTab.ts: LC-015, LM-019-020, LM-023, DC-055-056
extensions/aa_workflow_vscode/src/performanceTab.ts: LC-016, LM-022, DC-055-056, ML-042-045
extensions/aa_workflow_vscode/src/skillWebSocket.ts: DC-054, ML-038-041, GOOD-011, GOOD-012
extensions/aa_workflow_vscode/src/skillToast.ts: LC-017, LM-021, MEM-008-009, DC-057
extensions/aa_workflow_vscode/src/commandCenter.ts: LC-007 (CRITICAL)
```

### By Pattern Type
```
Singleton Pattern: DC-011, DC-041, RC-012, LC-007
Kubeconfig/Cluster: DC-023, DC-036-037, LC-005
Tool Registration: DC-015, DC-047
Success/Failure Returns: DC-016
Command Execution: DC-022, DC-017-018
YAML Persistence: GOOD-008, DC-051
Dataclass Usage: GOOD-002, GOOD-005, GOOD-009
Enum Usage: GOOD-010, PO-*
```

---

*Last updated: Auto-generated during code smell analysis (Iteration 12)*
*Document size: ~3500 lines, 295+ entries, 12 positive examples*
*Analysis iterations: 12*
*Files analyzed: 50+ (server/, scripts/, tool_modules/, extensions/)*
