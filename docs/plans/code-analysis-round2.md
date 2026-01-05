# Code Analysis Round 2: Deeper Patterns

**Date:** 2026-01-05
**Focus:** Magic numbers, code smells, consolidation opportunities

---

## Summary of Findings

| Category | Issues Found | Impact | Effort to Fix |
|----------|-------------|--------|---------------|
| Magic Numbers | 50+ hardcoded values | Medium | Low |
| CLI Runners | 6 duplicated patterns | High | Medium |
| HTTP Clients | 5 duplicated patterns | Medium | Medium |
| Exception Handling | 31 bare `except Exception` | Low | Low |
| Output Truncation | Still 11 inline patterns | Medium | Low |
| Auto-Heal Blocks | 172 duplicated steps | High | High |
| Response Building | 98 `"\n".join(lines)` patterns | Low | Medium |

---

## 1. Magic Numbers & Hardcoded Values

### 1.1 Timeout Values (33 occurrences)

**Problem:** Inconsistent timeout values scattered across modules with no central configuration.

| Module | Function | Timeout | Purpose |
|--------|----------|---------|---------|
| aa-jira | `run_rh_issue()` | 30s | Default |
| aa-git | `run_git()` | 60s | Default |
| aa-gitlab | `run_glab()` | 60s | Default |
| aa-konflux | `run_konflux_cmd()` | 60s | Default |
| aa-bonfire | `run_bonfire()` | 300s | Default |
| aa-bonfire | `bonfire_deploy()` | 600s | Deploy |
| aa-bonfire | `bonfire_reserve_deploy()` | 960s | Combined |
| aa-lint | `run_pytest()` | 600s | Tests |
| aa-lint | `run_pylint()` | 300s | Linting |

**Solution:** Create `server/timeouts.py`:

```python
# server/timeouts.py
"""Centralized timeout configuration."""

class Timeouts:
    """Standard timeout values in seconds."""

    # Quick operations
    FAST = 30
    DEFAULT = 60

    # Medium operations
    LINT = 300
    BUILD = 600

    # Long operations
    DEPLOY = 900
    TEST_SUITE = 1200

    # Network-dependent
    HTTP_REQUEST = 30
    CLUSTER_LOGIN = 120
```

**Estimated Impact:** Easier to tune all timeouts from one place.

---

### 1.2 Truncation Lengths (27 occurrences)

**Problem:** Inconsistent max lengths for output truncation.

| Length | Occurrences | Used For |
|--------|-------------|----------|
| 1000 | 1 | Short outputs |
| 1500 | 5 | Medium outputs |
| 2000 | 8 | Common default |
| 3000 | 1 | Longer outputs |
| 5000 | 3 | Log outputs |
| 8000 | 1 | Build logs |
| 10000 | 6 | Pipeline logs |
| 15000 | 3 | Full logs |
| 20000 | 2 | Complete logs |

**Solution:** Add constants to `server/utils.py`:

```python
class OutputLimits:
    """Standard output truncation limits."""

    SHORT = 1000      # Error messages
    MEDIUM = 2000     # Command output
    STANDARD = 5000   # Default for most tools
    LONG = 10000      # Pipeline logs
    FULL = 20000      # Complete output when needed
```

---

### 1.3 Duration Maps (2 duplicates)

**Problem:** Same duration map in `aa-alertmanager` and `aa-prometheus`:

```python
duration_map = {"m": 1, "h": 60, "d": 1440}
```

**Solution:** Add to `server/utils.py`:

```python
def parse_duration(duration_str: str) -> int:
    """Parse duration string like '30m', '2h', '1d' to minutes."""
    MINUTES_MAP = {"m": 1, "h": 60, "d": 1440, "w": 10080}
    # ... implementation
```

---

## 2. CLI Runner Consolidation

### 2.1 Current State

Six modules have their own async CLI runner with similar patterns:

| Module | Function | Lines | Special Features |
|--------|----------|-------|------------------|
| aa-git | `run_git()` | 8 | Uses `run_cmd` |
| aa-gitlab | `run_glab()` | 52 | Custom env, cwd resolution |
| aa-jira | `run_rh_issue()` | 35 | Shell mode, auth error handling |
| aa-bonfire | `run_bonfire()` | 70 | Kubeconfig, timeout, shell |
| aa-quay | `run_skopeo()` | 25 | Standard subprocess |
| aa-konflux | `run_konflux_cmd()` | 30 | Kubeconfig handling |

**Common patterns:**
- Subprocess execution with timeout
- Environment variable injection
- Working directory handling
- Error message parsing
- Auth failure detection

**Solution:** Enhance `server/utils.py` with a configurable runner:

```python
@dataclass
class CLIRunner:
    """Configurable CLI command runner."""

    base_command: str
    timeout: int = 60
    env_vars: dict[str, str] = field(default_factory=dict)
    kubeconfig: str | None = None
    shell_mode: bool = False
    auth_error_patterns: list[str] = field(default_factory=list)

    async def run(self, args: list[str], cwd: str | None = None) -> tuple[bool, str]:
        """Execute command with configured settings."""
        ...
```

Then each module:

```python
# aa-git
git_runner = CLIRunner("git", timeout=60)

# aa-bonfire
bonfire_runner = CLIRunner(
    "bonfire",
    timeout=300,
    kubeconfig=get_kubeconfig("ephemeral"),
    shell_mode=True,
    auth_error_patterns=["Unauthorized", "token expired"]
)
```

**Estimated savings:** ~120 lines

---

## 3. HTTP Client Patterns

### 3.1 Current State

Five modules create their own `httpx.AsyncClient`:

```python
# aa-prometheus
async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
    ...

# aa-alertmanager
async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
    ...

# aa-kibana
async with httpx.AsyncClient(timeout=30.0, verify=True) as client:
    ...

# aa-quay
async with httpx.AsyncClient(timeout=30.0) as client:
    ...

# aa-workflow
async with httpx.AsyncClient() as client:
    ...
```

**Common needs:**
- Bearer token auth
- JSON response handling
- Timeout configuration
- Error code handling (401, 403, 404)

**Solution:** Create `server/http_client.py`:

```python
class APIClient:
    """Reusable async HTTP client with common patterns."""

    def __init__(
        self,
        base_url: str = "",
        timeout: float = 30.0,
        bearer_token: str | None = None,
        verify_ssl: bool = True,
    ):
        self.base_url = base_url
        self.timeout = timeout
        self.bearer_token = bearer_token
        self.verify_ssl = verify_ssl

    async def get(self, path: str, **kwargs) -> tuple[bool, dict | str]:
        """GET request with standard error handling."""
        ...

    async def post(self, path: str, data: dict, **kwargs) -> tuple[bool, dict | str]:
        """POST request with standard error handling."""
        ...
```

---

## 4. Exception Handling Code Smells

### 4.1 Bare Exception Catches (31 occurrences)

**Problem:** Many `except Exception as e:` blocks that swallow errors too broadly.

**Examples:**
```python
# aa-workflow/src/skill_engine.py - 10 occurrences
except Exception as e:
    return f"Error: {e}"

# aa-workflow/src/memory_tools.py - 5 occurrences
except Exception as e:
    return [TextContent(type="text", text=f"Error: {e}")]
```

**Issues:**
1. Catches `KeyboardInterrupt`, `SystemExit`
2. Hides specific error types
3. Logs generic messages
4. Hard to debug

**Solution:** Replace with specific exceptions:

```python
# Before
except Exception as e:
    return f"Error: {e}"

# After
except (OSError, subprocess.SubprocessError) as e:
    return f"Command failed: {e}"
except yaml.YAMLError as e:
    return f"Invalid YAML: {e}"
except Exception as e:
    logger.exception("Unexpected error")  # Log with traceback
    return f"Unexpected error: {e}"
```

---

## 5. Still-Inline Output Truncation

### 5.1 Missed Patterns (11 occurrences)

Despite adding `truncate_output()`, some modules still have inline truncation:

```python
# aa-lint/src/tools.py
lines.append(f"```\n{output[:1500]}\n```")
lines.append(f"```\n{output[:2000]}\n```")
lines.append(f"```\n{stdout[:2000]}\n```")

# aa-infra_tools.py
lines.append(output[-2000:] if len(output) > 2000 else output)
lines.append(output[-1500:] if len(output) > 1500 else output)

# aa-appinterface/src/tools.py
lines.append(output[-3000:] if len(output) > 3000 else output)
lines.append(stdout[:2000])
lines.append(yaml.dump(data)[:1500])
```

**Solution:** Replace with `truncate_output()`:

```python
# Before
lines.append(f"```\n{output[:1500]}\n```")

# After
lines.append(f"```\n{truncate_output(output, max_length=1500)}\n```")

# Before (tail mode)
lines.append(output[-2000:] if len(output) > 2000 else output)

# After
lines.append(truncate_output(output, max_length=2000, mode="tail"))
```

**Estimated savings:** More consistency, easier to change limits

---

## 6. Auto-Heal Block Duplication

### 6.1 Current State (172 occurrences across 37 skills)

Every skill that calls a fallible tool has this pattern repeated:

```yaml
- name: detect_failure_{step}
  compute: |
    from scripts.common.auto_heal import detect_failure
    result = detect_failure(
        output=str({output}),
        success={output}.get('success', True) if isinstance({output}, dict) else True
    )
  output: failure_{step}

- name: quick_fix_auth_{step}
  condition: "{failure_step}.get('detected') and 'auth' in {failure_step}.get('category', '')"
  tool: kube_login
  args:
    cluster: "{cluster}"
  output: auth_fix_{step}

- name: quick_fix_vpn_{step}
  condition: "{failure_step}.get('detected') and 'network' in {failure_step}.get('category', '')"
  tool: vpn_connect
  args: {}
  output: vpn_fix_{step}

- name: retry_{step}
  condition: "{auth_fix_step} or {vpn_fix_step}"
  tool: {original_tool}
  args: {original_args}
  output: retry_{step}_result

- name: merge_{step}_result
  compute: |
    result = {retry_step_result} if {retry_step_result} else {original_output}
  output: {step}_final

- name: log_failure_{step}
  condition: "{failure_step}.get('detected') and not ({auth_fix_step} or {vpn_fix_step})"
  compute: |
    from scripts.common.auto_heal import log_failure
    ...
```

**That's ~30 lines repeated per fallible tool call!**

**Solution:** Implement skill step templating (as outlined in previous plan):

```yaml
steps:
  - name: reserve_namespace
    tool: bonfire_namespace_reserve
    args: {duration: 4h}
    output: reserve_result
    auto_heal: true  # NEW: enables auto-heal block expansion
    auto_heal_cluster: ephemeral
```

The skill engine would expand `auto_heal: true` into the full block.

---

## 7. Response Building Pattern

### 7.1 Current State (98 `"\n".join(lines)` patterns)

Almost every tool function uses:

```python
lines = []
lines.append("## Title")
lines.append("")
lines.append("content...")
return "\n".join(lines)
```

**Alternative approach:** Use a response builder:

```python
from server.response import ResponseBuilder

def my_tool(...) -> str:
    rb = ResponseBuilder()
    rb.header("Title")
    rb.text("content...")
    rb.code_block(output, lang="yaml")
    rb.success("Operation complete")
    return rb.build()
```

**Trade-off:** This is a stylistic choice. The current pattern is simple and explicit. A builder adds abstraction but could make code more consistent.

**Recommendation:** Keep current pattern, it's readable and explicit.

---

## 8. Environment Configuration

### 8.1 Hardcoded Environment Names

**Problem:** "stage" and "prod" are hardcoded in many places:

```python
environment: str = "stage"  # 23 occurrences
```

**Valid environments:** `stage`, `prod`, `ephemeral`, `konflux`

**Solution:** Add to `server/constants.py`:

```python
from typing import Literal

Environment = Literal["stage", "prod", "ephemeral", "konflux"]

DEFAULT_ENVIRONMENT: Environment = "stage"
VALID_ENVIRONMENTS = {"stage", "prod", "ephemeral", "konflux"}
```

---

## 9. Unused Imports & Dead Code

Quick grep for potential issues:

```bash
# Check for unused imports with pylint
pylint --disable=all --enable=unused-import tool_modules/
```

**Recommendation:** Run `ruff` or `pylint` for systematic cleanup.

---

## Priority Recommendations

### High Priority (Low Effort, High Impact)

1. **Fix remaining inline truncation** - 11 places, replace with `truncate_output()`
2. **Add timeout constants** - Create `server/timeouts.py`
3. **Add output limit constants** - Add to `server/utils.py`
4. **Extract duration parser** - DRY the duration_map pattern

### Medium Priority (Medium Effort, Medium Impact)

5. **CLI Runner abstraction** - Could save ~120 lines
6. **HTTP Client abstraction** - Could save ~80 lines
7. **Improve exception handling** - Replace bare `except Exception`

### Low Priority (High Effort)

8. **Auto-heal templating** - Would save 500+ lines but complex to implement
9. **Response builder** - Stylistic, current approach is fine

---

## Quick Wins Implementation Checklist

- [x] Replace 11 remaining inline truncations with `truncate_output()` ✅
- [x] Create `server/timeouts.py` with standard values ✅
- [x] Add `OutputLimits` class to `server/timeouts.py` ✅
- [x] Add `parse_duration_to_minutes()` utility ✅
- [x] Add `Environment` type alias ✅
- [x] Update `aa-alertmanager` and `aa-prometheus` to use shared duration parser ✅

**Completed:** 2026-01-05
**Estimated savings:** ~40 lines + much better consistency

### New Files Created

- `server/timeouts.py` - Contains:
  - `Timeouts` class with standard timeout values
  - `OutputLimits` class with truncation limits
  - `parse_duration_to_minutes()` function
  - `Environment` type alias
  - `DEFAULT_ENVIRONMENT` constant
