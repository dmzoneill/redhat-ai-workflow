# Magic Variables and Config.json Access Analysis

> Auto-generated analysis of hardcoded values and config.json access patterns.
> Goal: Migrate magic values to config.json and ensure thread-safe access via ConfigManager.

---

## Table of Contents

### Issues by Category
- [Direct config.json Access (Bypassing ConfigManager)](#direct-configjson-access-bypassing-configmanager)
- [Hardcoded Timeouts](#hardcoded-timeouts)
- [Hardcoded Ports](#hardcoded-ports)
- [Hardcoded Intervals](#hardcoded-intervals)
- [Hardcoded Limits/Thresholds](#hardcoded-limitsthresholds)
- [Hardcoded Paths](#hardcoded-paths)
- [Hardcoded URLs](#hardcoded-urls)

### Summary
- [Migration Priority Matrix](#migration-priority-matrix)
- [Config.json Schema Additions](#configjson-schema-additions)
- [Implementation Tasks](#implementation-tasks)

---

## ConfigManager Usage

The thread-safe ConfigManager singleton is located at `server/config_manager.py` and provides:
- Thread-safe access via RLock
- File locking for cross-process safety (fcntl.flock)
- Automatic cache invalidation via mtime checking
- Debounced writes to reduce disk I/O

**Correct usage:**
```python
from server.config_manager import config

# Read
slack_config = config.get("slack")
enabled = config.get("schedules", "enabled", default=False)

# Write (debounced)
config.set("schedules", "enabled", True)
```

---

## Direct config.json Access (Bypassing ConfigManager)

Files that directly read config.json instead of using the ConfigManager singleton.
**Risk:** Race conditions, stale reads, duplicate code.

### HIGH PRIORITY - Must Fix

#### DAC-001: scripts/common/config_loader.py
**Lines:** 33-45
**Issue:** Has fallback code that reads config.json directly when utils import fails
```python
try:
    from server.utils import load_config as utils_load_config
    result = utils_load_config()  # Good - uses ConfigManager
except ImportError:
    # Fallback - BAD: reads directly without thread safety
    config_path = Path(__file__).parent.parent.parent / "config.json"
    with open(config_path) as f:
        loaded = json.load(f)
```
**Risk:** Fallback path bypasses ConfigManager
**Fix:** Import ConfigManager directly: `from server.config_manager import config`

#### DAC-002: scripts/common/memory.py
**Lines:** 61-63
**Issue:** Reads config.json directly for user info
```python
config_path = MEMORY_DIR.parent / "config.json"
with open(config_path) as f:
    data = json.load(f)
```
**Fix:** Use ConfigManager: `config.get("user")`

#### DAC-003: scripts/common/context_resolver.py
**Lines:** 84-95
**Issue:** Loads config.json from multiple paths, no thread safety
```python
Path.cwd() / "config.json",
Path(__file__).parent.parent.parent / "config.json",
Path.home() / "src/redhat-ai-workflow/config.json",
```
**Fix:** Use ConfigManager singleton

#### DAC-004: scripts/skill_hooks.py
**Lines:** 106-110
**Issue:** Reads config.json directly for skill_hooks configuration
```python
config_path = Path(__file__).parent.parent / "config.json"
with open(config_path) as f:
    config = json.load(f)
```
**Fix:** Use `from server.config_manager import config`

#### DAC-005: scripts/common/response_router.py
**Lines:** 143-148
**Issue:** Reads config.json directly for response configuration
```python
config_path = PROJECT_ROOT / "config.json"
with open(config_path) as f:
    cfg = json.load(f)
```
**Fix:** Use ConfigManager singleton

#### DAC-006: tool_modules/aa_ollama/src/instances.py
**Lines:** 72-76
**Issue:** Reads config.json directly for Ollama instances
```python
config_path = Path(__file__).parents[4] / "config.json"
with open(config_path) as f:
    cfg = json.load(f)
```
**Fix:** Use ConfigManager

#### DAC-007: tool_modules/aa_ollama/src/tool_registry.py
**Lines:** 145-157
**Issue:** Reads config.json directly for tool categories
```python
config_path = Path(__file__).parents[4] / "config.json"
with open(config_path) as f:
    full_config = json.load(f)
```
**Fix:** Use ConfigManager

#### DAC-008: tool_modules/aa_ollama/src/context_enrichment.py
**Lines:** 153-158
**Issue:** Reads config.json directly
```python
config_path = Path(__file__).parents[4] / "config.json"
with open(config_path) as f:
    full_config = json.load(f)
```
**Fix:** Use ConfigManager

#### DAC-009: tool_modules/aa_ollama/src/tool_filter.py
**Lines:** 139-162
**Issue:** Reads config.json directly for tool filtering
**Fix:** Use ConfigManager

#### DAC-010: tool_modules/aa_slack/src/slack_client.py
**Lines:** 107-122
**Issue:** Loads config.json from multiple paths for Slack credentials
```python
config_paths = [
    Path(__file__).parents[4] / "config.json",
    Path.cwd() / "config.json",
    Path.home() / "src" / "redhat-ai-workflow" / "config.json",
]
```
**Fix:** Use ConfigManager singleton

#### DAC-011: tool_modules/aa_code_search/src/tools_basic.py
**Lines:** 465-472
**Issue:** Reads config.json directly for vector search config
```python
config_paths = [
    Path.cwd() / "config.json",
    Path(__file__).parent.parent.parent.parent.parent / "config.json",
]
```
**Fix:** Use ConfigManager

#### DAC-012: tool_modules/aa_alertmanager/src/tools_basic.py
**Lines:** 255-259
**Issue:** Reads config.json directly for Prometheus URL
```python
config_path = Path(__file__).parent.parent.parent.parent / "config.json"
with open(config_path) as f:
    cfg = json.load(f)
```
**Fix:** Use ConfigManager: `config.get("prometheus", "environments")`

#### ~~DAC-013a: tool_modules/aa_meet_bot/src/jira_preloader.py~~ (ACCEPTABLE)
**Lines:** 211-214
**Issue:** Reads from `~/.config/jira/config.json`
**Note:** This is a DIFFERENT config file (user's Jira CLI config), NOT the project config.json
**Status:** No fix needed - separate config domain

#### DAC-013: scripts/get_slack_creds.py
**Lines:** 169-193
**Issue:** Reads and writes config.json directly
**Fix:** Use ConfigManager for read/write operations

#### DAC-014: scripts/integration_test.py
**Lines:** 314
**Issue:** Reads config.json directly for testing
**Note:** May be acceptable for test isolation

### MEDIUM PRIORITY - Uses backward-compat functions

These files use helper functions that eventually load config, but should migrate:

#### ~~DAC-015: server/utils.py~~ (VERIFIED OK)
**Status:** Already uses ConfigManager correctly
```python
from server.config_manager import config as _config_manager
# ...
return _config_manager.get_all()  # Line 167
result = _config_manager.get(section)  # Line 182
```
**Note:** No fix needed - already migrated

#### DAC-015: server/config.py
**Lines:** 19-142
**Issue:** Entire module duplicates config loading logic
**Fix:** Refactor to use ConfigManager

---

## Hardcoded Timeouts

Magic timeout values that should be centralized in config.json.

### Existing config.json timeouts section:
```json
"timeouts": {
    "ephemeral_default": "2h",
    "alert_default": "1h",
    "standup_days": 1
}
```

### TO-ADD: Missing timeout configurations

#### HT-001: subprocess timeout defaults
**Files affected:** Multiple files use `timeout=5`, `timeout=10`, `timeout=30`, `timeout=60`
```python
# server/workspace_state.py:143
result = subprocess.run(..., timeout=5)

# server/workspace_state.py:317
timeout=30  # Longer timeout for large DB

# server/config.py:88, 109, 131
timeout=5

# scripts/sync_workspace_state.py (multiple lines)
timeout=5
```
**Migration:** Add to config.json:
```json
"timeouts": {
    "subprocess_short": 5,
    "subprocess_medium": 30,
    "subprocess_long": 60,
    "database_query": 30
}
```

#### HT-002: API request timeouts
**Files:**
- `tool_modules/aa_slack/src/slack_client.py:181` - `timeout=30.0`
- `tool_modules/aa_concur/src/tools_basic.py:79` - `timeout=30`
- `tool_modules/aa_concur/src/tools_basic.py:114` - `timeout=10`
- `tool_modules/aa_concur/src/tools_basic.py:157` - `timeout=15`
- `tool_modules/aa_concur/src/tools_basic.py:561` - `timeout=300` (5 min upload)
**Migration:** Add to config.json:
```json
"timeouts": {
    "api_request_short": 10,
    "api_request_medium": 30,
    "api_upload": 300
}
```

#### HT-003: D-Bus future timeouts
**Files:** scripts/slack_dbus.py lines 214, 230, 336, 368, 396, 424, 466, 491, 546
```python
result = future.result(timeout=10)  # Most calls
result = future.result(timeout=30)  # Heavy operations
result = future.result(timeout=60)  # Very heavy operations
```
**Migration:** Add to config.json:
```json
"timeouts": {
    "dbus_light": 10,
    "dbus_medium": 30,
    "dbus_heavy": 60
}
```

#### HT-004: Notification timeouts
**File:** scripts/slack_daemon.py lines 683-763
```python
timeout=2000  # 2 seconds
timeout=3000  # 3 seconds
timeout=10000  # 10 seconds (for errors)
```
**Migration:** Add to config.json:
```json
"notifications": {
    "timeout_short_ms": 2000,
    "timeout_medium_ms": 3000,
    "timeout_error_ms": 10000
}
```

#### HT-005: Kubernetes operation timeouts
**Files:**
- `server/utils.py:321` - `timeout=30` (kube-clean)
- `server/utils.py:327` - `timeout=120` (kube auth)
- `server/auto_heal_decorator.py` - multiple 120s timeouts
**Migration:** Add to config.json:
```json
"kubernetes": {
    "timeout_clean": 30,
    "timeout_auth": 120,
    "timeout_operation": 120
}
```

---

## Hardcoded Ports

#### HP-001: WebSocket server port
**File:** server/websocket_server.py, server/main.py:585
**Value:** `9876`
**Migration:** Add to config.json at `websocket.port: 9876`
**Fix:** Load from config instead of hardcoding

---

## Hardcoded Intervals

#### HI-001: Polling intervals
**Files:**
- `tool_modules/aa_meet_bot/src/notes_bot.py:473` - `poll_interval = 15.0`
- `tool_modules/aa_meet_bot/src/meeting_scheduler.py:97` - `poll_interval = 300`
- `tool_modules/aa_meet_bot/src/video_generator.py:3121` - `reconnect_interval = 5.0`
**Migration:** Add to config.json:
```json
"meet_bot": {
    "poll_interval_notes": 15,
    "poll_interval_calendar": 300,
    "reconnect_interval": 5
}
```

#### HI-002: Timer intervals
**File:** scripts/common/sleep_wake.py
```python
RobustTimer(interval=60, callback=my_callback)  # Line 326
interval=300  # 5 minutes - Line 418
```
**Migration:** Add to config.json under relevant service section

#### HI-003: Cleanup intervals
**File:** tool_modules/aa_meet_bot/src/notes_bot.py:1193
```python
cleanup_interval = 5  # Run device cleanup every 5 monitor cycles
```
**Migration:** Add to meet_bot config section

---

## Hardcoded Limits/Thresholds

#### HL-001: Max retries
**Files:**
- `server/auto_heal_decorator.py:378` - `max_retries: int = 1`
- `scripts/common/auto_heal.py:188` - `max_retries: int = 2`
- Config.json already has: `slack.rate_limiting.max_retries: 5`
**Migration:** Centralize to config.json:
```json
"retries": {
    "auto_heal": 1,
    "auto_heal_shell": 2,
    "api_request": 5
}
```

#### HL-002: Max age for patterns
**Files:**
- `server/usage_pattern_storage.py:295` - `max_age_days: int = 90`
- `server/usage_pattern_optimizer.py:29` - `max_age_days: int = 90`
- `scripts/optimize_patterns.py:54` - `default=90`
**Migration:** Add to config.json:
```json
"usage_patterns": {
    "max_age_days": 90,
    "min_confidence": 0.70,
    "decay_rate": 0.05
}
```

#### HL-003: Session stale hours
**File:** server/workspace_state.py
```python
SESSION_STALE_HOURS = 24  # Line ~50 (needs verification)
max_age_hours: int = SESSION_STALE_HOURS  # Line 723
max_age_hours: int = 24  # Line 790
```
**Migration:** Add to config.json:
```json
"workspace": {
    "session_stale_hours": 24,
    "cleanup_stale_hours": 24
}
```

#### HL-004: Activity log size
**File:** server/web/app.py:29
```python
MAX_ACTIVITY = 100
```
**Migration:** Add to config.json:
```json
"web": {
    "max_activity_log": 100
}
```

#### HL-005: D-Bus cache size
**File:** scripts/slack_dbus.py:77
```python
max_size: int = 1000
```
**Migration:** Add to config.json:
```json
"slack": {
    "dbus_cache_max_size": 1000
}
```

#### HL-006: Code search defaults
**File:** tool_modules/aa_code_search/src/tools_basic.py:65
```python
DEFAULT_NPROBES = 20  # Partitions to search
```
**Migration:** Add to config.json:
```json
"code_search": {
    "default_nprobes": 20,
    "index_chunk_size": 512
}
```

#### HL-007: Slack history limit
**File:** scripts/slack_control.py:405
```python
history_parser.add_argument("-n", "--limit", type=int, default=50)
```
**Migration:** Add to config.json:
```json
"slack": {
    "default_history_limit": 50
}
```

---

## Hardcoded Default Constants

These are DEFAULT_* constants that should be centralized in config.json.

#### HD-001: Default workspace/project
**Files:**
- `server/workspace_state.py:47` - `DEFAULT_WORKSPACE = "default"`
- `server/workspace_state.py:50` - `DEFAULT_PROJECT = "redhat-ai-workflow"`
- `tool_modules/aa_workflow/src/chat_context.py:34` - `DEFAULT_PROJECT = "redhat-ai-workflow"`
**Migration:** Add to config.json:
```json
"workspace": {
    "default_workspace": "default",
    "default_project": "redhat-ai-workflow"
}
```

#### HD-002: Code search defaults
**Files:**
- `tool_modules/aa_code_search/src/tools_basic.py:53` - `DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"`
- `tool_modules/aa_code_search/src/tools_basic.py:65` - `DEFAULT_NPROBES = 20`
**Migration:** Add to config.json:
```json
"code_search": {
    "embedding_model": "all-MiniLM-L6-v2",
    "default_nprobes": 20
}
```

#### HD-003: Ollama defaults
**File:** `tool_modules/aa_ollama/src/instances.py:33`
```python
DEFAULT_INSTANCES = {
    "default": OllamaInstance(
        name="default",
        host="localhost",
        port=11434,
        ...
    )
}
```
**Migration:** Add to config.json:
```json
"ollama": {
    "default_host": "localhost",
    "default_port": 11434
}
```

#### HD-004: Meet bot defaults
**Files:**
- `tool_modules/aa_meet_bot/src/notes_database.py:24` - `DEFAULT_DB_PATH = Path.home() / ".local/share/meet_bot/meetings.db"`
- `tool_modules/aa_meet_bot/src/tts_engine.py:63` - `DEFAULT_VOICE = "en_US-lessac-medium"`
- `tool_modules/aa_meet_bot/src/gemini_hotload.py:30` - `DEFAULT_MODEL = "gemini-2.5-pro"`
**Migration:** Add to config.json:
```json
"meet_bot": {
    "database_path": "~/.local/share/meet_bot/meetings.db",
    "default_voice": "en_US-lessac-medium",
    "default_model": "gemini-2.5-pro"
}
```

#### HD-005: Google Calendar defaults
**File:** `tool_modules/aa_google_calendar/src/tools_basic.py:70`
```python
DEFAULT_DURATION = 30  # minutes
```
**Note:** Already partially in config.json at `google_calendar.default_duration_minutes: 30`
**Fix:** Ensure code loads from config instead of using DEFAULT_DURATION constant

#### HD-006: Konflux namespace default
**Files:**
- `tool_modules/aa_konflux/src/tools_basic.py:44` - `DEFAULT_NAMESPACE = os.getenv("KONFLUX_NAMESPACE", "default")`
- `tool_modules/aa_konflux/src/tools_extra.py:44` - Same pattern
**Note:** Falls back to "default" which is not useful
**Migration:** Already in config at `konflux.cluster` - ensure proper loading

#### HD-007: Scheduler retry defaults
**File:** `tool_modules/aa_workflow/src/scheduler.py:28`
```python
DEFAULT_RETRY_CONFIG = {
    "max_attempts": 2,
    "backoff": "exponential",
    "initial_delay_seconds": 30,
    "max_delay_seconds": 300,
    "retry_on": ["auth", "network"]
}
```
**Note:** Already in config.json at `schedules.default_retry`
**Fix:** Load from config instead of hardcoded dict

#### HD-008: Working hours defaults
**File:** `tool_modules/aa_workflow/src/working_hours.py:37`
```python
DEFAULT_CONFIG = {
    "enabled": True,
    "start_hour": 9,
    "end_hour": 17,
    "days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
    "timezone": "America/New_York",
    ...
}
```
**Note:** Already in config.json at `sprint.working_hours`
**Fix:** Load from config instead of hardcoded dict

#### HD-009: MCP proxy watch paths
**File:** `scripts/mcp_proxy.py:67`
```python
DEFAULT_WATCH_PATHS = [
    "config.json",
    "skills/",
    "personas/",
    ...
]
```
**Migration:** Add to config.json:
```json
"mcp": {
    "watch_paths": ["config.json", "skills/", "personas/"]
}
```

---

## Hardcoded Fallback URLs

URLs that have hardcoded fallbacks but should use config.json exclusively.

#### HU-001: Jira URL fallback
**File:** `scripts/common/config_loader.py:106`
```python
url = jira_config.get("url", "https://issues.redhat.com")
```
**Issue:** Fallback to Red Hat Jira not suitable for all users
**Fix:** Require explicit configuration, fail clearly if not set

#### HU-002: GitLab host fallback
**File:** `scripts/common/config_loader.py:248`
```python
config.get("gitlab", {}).get("host", "gitlab.cee.redhat.com")
```
**Issue:** Fallback to internal Red Hat GitLab
**Fix:** Require explicit configuration

#### HU-003: Quay URL hardcoded
**File:** `scripts/common/config_loader.py:262`
```python
def get_quay_url() -> str:
    return "https://quay.io"
```
**Issue:** No config option, just hardcoded
**Note:** Already in config.json at `quay.api_url`
**Fix:** Load from config

---

## Hardcoded Paths

Most paths are already in config.json under `paths` section:
```json
"paths": {
    "kube_base": "/home/YOUR_USER/.kube",
    "docker_config": "/home/YOUR_USER/.docker/config.json",
    "container_auth": "/home/YOUR_USER/.config/containers/auth.json",
    "google_calendar_config": "/home/YOUR_USER/.config/google_calendar",
    ...
}
```

#### HP-001: Slack state DB path
**Config.json already has:** `slack.state_db_path: "./slack_state.db"`
**Verify:** Ensure all code uses this config value

---

## Hardcoded URLs

Most URLs are already in config.json under respective service sections.
**Verify:** Ensure all code loads URLs from config instead of hardcoding.

---

## Migration Priority Matrix

| Priority | Category | Count | Effort | Impact |
|----------|----------|-------|--------|--------|
| CRITICAL | Direct config.json access | 13 | Medium | High - Race conditions |
| HIGH | Timeouts | 25+ | Low | Medium - Consistency |
| HIGH | Default constants (HD-*) | 10 | Low | Medium - Config-driven |
| HIGH | Max age/limits | 8 | Low | Medium - Tuning |
| MEDIUM | Ports | 2 | Low | Low - Already in config |
| MEDIUM | Intervals | 6 | Low | Medium - Tuning |
| MEDIUM | Fallback URLs | 3 | Low | Medium - User-specific |
| LOW | Paths | 2 | Low | Low - Most already done |

---

## Config.json Schema Additions

Proposed additions to config.json to centralize magic values:

```json
{
  "timeouts": {
    "subprocess_short": 5,
    "subprocess_medium": 30,
    "subprocess_long": 60,
    "database_query": 30,
    "api_request_short": 10,
    "api_request_medium": 30,
    "api_upload": 300,
    "dbus_light": 10,
    "dbus_medium": 30,
    "dbus_heavy": 60,
    "kubernetes_clean": 30,
    "kubernetes_auth": 120,
    "ephemeral_default": "2h",
    "alert_default": "1h"
  },
  "notifications": {
    "timeout_short_ms": 2000,
    "timeout_medium_ms": 3000,
    "timeout_error_ms": 10000
  },
  "retries": {
    "auto_heal": 1,
    "auto_heal_shell": 2,
    "api_request": 5
  },
  "usage_patterns": {
    "max_age_days": 90,
    "min_confidence": 0.70,
    "decay_rate": 0.05
  },
  "workspace": {
    "default_workspace": "default",
    "default_project": "redhat-ai-workflow",
    "session_stale_hours": 24,
    "cleanup_stale_hours": 24
  },
  "web": {
    "max_activity_log": 100
  },
  "code_search": {
    "embedding_model": "all-MiniLM-L6-v2",
    "default_nprobes": 20,
    "index_chunk_size": 512
  },
  "ollama": {
    "default_host": "localhost",
    "default_port": 11434
  },
  "meet_bot": {
    "database_path": "~/.local/share/meet_bot/meetings.db",
    "default_voice": "en_US-lessac-medium",
    "default_model": "gemini-2.5-pro",
    "poll_interval_notes": 15,
    "poll_interval_calendar": 300,
    "reconnect_interval": 5,
    "cleanup_interval": 5
  },
  "mcp": {
    "watch_paths": ["config.json", "skills/", "personas/", "tool_modules/"]
  }
}
```

---

## Implementation Tasks

### Phase 1: Fix Direct Config Access (CRITICAL)
- [ ] DAC-001: Refactor scripts/common/config_loader.py to use ConfigManager directly (remove fallback)
- [ ] DAC-002: Refactor scripts/common/memory.py to use ConfigManager
- [ ] DAC-003: Refactor scripts/common/context_resolver.py to use ConfigManager
- [ ] DAC-004: Refactor scripts/skill_hooks.py to use ConfigManager
- [ ] DAC-005: Refactor scripts/common/response_router.py to use ConfigManager
- [ ] DAC-006: Refactor tool_modules/aa_ollama/src/instances.py to use ConfigManager
- [ ] DAC-007: Refactor tool_modules/aa_ollama/src/tool_registry.py to use ConfigManager
- [ ] DAC-008: Refactor tool_modules/aa_ollama/src/context_enrichment.py to use ConfigManager
- [ ] DAC-009: Refactor tool_modules/aa_ollama/src/tool_filter.py to use ConfigManager
- [ ] DAC-010: Refactor tool_modules/aa_slack/src/slack_client.py to use ConfigManager
- [ ] DAC-011: Refactor tool_modules/aa_code_search/src/tools_basic.py to use ConfigManager
- [ ] DAC-012: Refactor tool_modules/aa_alertmanager/src/tools_basic.py to use ConfigManager
- [ ] DAC-013: Refactor scripts/get_slack_creds.py to use ConfigManager for read/write
- [ ] DAC-015: Refactor server/config.py to use ConfigManager

### Phase 2: Add Missing Config Sections
- [ ] Add `timeouts` section with all timeout values
- [ ] Add `retries` section (extend schedules.default_retry if exists)
- [ ] Add `usage_patterns` section
- [ ] Add `workspace` section with default_workspace and default_project
- [ ] Add `web` section
- [ ] Add `code_search` section with embedding_model and default_nprobes
- [ ] Add `ollama` section with default_host and default_port
- [ ] Extend `meet_bot` section with database_path, default_voice, default_model
- [ ] Add `mcp` section with watch_paths

### Phase 3: Migrate Default Constants (HD-*)
- [ ] HD-001: Load DEFAULT_WORKSPACE/DEFAULT_PROJECT from config
- [ ] HD-002: Load code_search defaults from config
- [ ] HD-003: Load ollama defaults from config
- [ ] HD-004: Load meet_bot defaults from config
- [ ] HD-005: Use google_calendar.default_duration_minutes instead of DEFAULT_DURATION
- [ ] HD-006: Load konflux namespace from config properly
- [ ] HD-007: Use schedules.default_retry instead of DEFAULT_RETRY_CONFIG
- [ ] HD-008: Use sprint.working_hours instead of DEFAULT_CONFIG
- [ ] HD-009: Use slack.interfaces.http instead of DEFAULT_HOST/DEFAULT_PORT
- [ ] HD-010: Add mcp.watch_paths and load from config

### Phase 4: Migrate Magic Timeouts
- [ ] HT-001: Replace subprocess timeouts with config values
- [ ] HT-002: Replace API request timeouts with config values
- [ ] HT-003: Replace D-Bus future timeouts with config values
- [ ] HT-004: Replace notification timeouts with config values
- [ ] HT-005: Replace Kubernetes operation timeouts with config values

### Phase 5: Migrate Other Magic Values
- [ ] HP-001, HP-002: Load ports from config
- [ ] HI-001 to HI-003: Load intervals from config
- [ ] HL-001 to HL-007: Load limits from config
- [ ] HU-001 to HU-003: Remove hardcoded fallback URLs, require explicit config

### Phase 6: Validation
- [ ] Add unit tests for ConfigManager usage in each refactored file
- [ ] Run full test suite to verify no regressions
- [ ] Update config.json.example with all new sections
- [ ] Update documentation to reflect config schema changes
- [ ] Add migration guide for existing users

---

## Files Currently Using ConfigManager Correctly

These files properly use the ConfigManager singleton:
1. `server/config_manager.py` - The singleton itself
2. `tool_modules/aa_workflow/src/project_tools.py` - Uses `load_config()` and `save_config()` wrappers
3. `tool_modules/aa_project/src/tools_basic.py` - Uses ConfigManager wrappers
4. `tool_modules/aa_workflow/src/scheduler.py` - Imports ConfigManager
5. `tool_modules/aa_workflow/src/scheduler_tools.py` - Imports ConfigManager
6. `tool_modules/aa_scheduler/src/tools_basic.py` - Imports ConfigManager
7. `server/utils.py` - Has backward-compat wrappers (should migrate callers)
8. `tests/test_config_manager.py` - Tests the singleton

---

## Summary Statistics

| Category | Count |
|----------|-------|
| Direct config.json access violations | 13 |
| Hardcoded timeout instances | 25+ |
| Hardcoded default constants | 10 |
| Hardcoded limits/thresholds | 7 |
| Hardcoded intervals | 6 |
| Hardcoded ports | 2 |
| Hardcoded fallback URLs | 3 |
| **Total magic values identified** | **66+** |
| Files using ConfigManager correctly | 8 |
| Implementation phases | 6 |
| Implementation tasks | 50+ |

---

*Last updated: Iteration 1*
*Analysis coverage: ~80 Python files*
*Direct access violations: 13 critical*
*Magic values identified: 66+*
*Config schema additions proposed: 10 new sections*
