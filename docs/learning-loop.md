# Learning Loop: Auto-Remediation + Memory

The Learning Loop ensures that when Claude fixes a tool error, the fix is remembered forever - preventing the same mistake from happening again.

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│                       Tool Execution                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Tool executes...                                               │
│      ↓                                                          │
│  ❌ FAILS                                                        │
│      ↓                                                          │
│  check_known_issues(tool_name, error_text)                      │
│      ↓                                                          │
│  ┌──────────────────────────────────────────┐                   │
│  │ Checks:                                  │                   │
│  │  - memory/learned/tool_fixes.yaml        │                   │
│  │  - memory/learned/patterns.yaml          │                   │
│  └──────────────────────────────────────────┘                   │
│      ↓                                                          │
│  ┌─────────────────────────────────────┐                        │
│  │ If matches found:                   │                        │
│  │   Show: "💡 Known Issues Found!"    │                        │
│  │   - Previous fix for tool_name      │                        │
│  │   - Root cause                      │                        │
│  │   - How to fix                      │                        │
│  └─────────────────────────────────────┘                        │
│      ↓                                                          │
│  Apply fix immediately OR debug_tool() for new issues           │
│      ↓                                                          │
│  After fix works: learn_tool_fix() → Saved to memory            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Tools

### check_known_issues

Check memory for known fixes before or after an error:

```python
# Check by tool name
check_known_issues(tool_name="bonfire_deploy")

# Check by error text
check_known_issues(error_text="manifest unknown")

# Check both
check_known_issues(tool_name="bonfire_deploy", error_text="manifest unknown")
```

**Output:**
```
## 💡 Known Issues Found!

**Previous fix for `bonfire_deploy`:**
- Pattern: `manifest unknown`
- Root cause: Short SHA doesn't exist in Quay
- **Fix:** Use full 40-char SHA instead of 8-char
```

### debug_tool

Analyze a failing tool's source code:

```python
debug_tool("bonfire_deploy", "manifest unknown: image not found")
```

**Output:**
- Source file location
- Function code
- Step-by-step fix instructions
- Reminder to save the learning

### learn_tool_fix

Save a fix to memory after it works:

```python
learn_tool_fix(
    tool_name="bonfire_deploy",
    error_pattern="manifest unknown",
    root_cause="Short SHA doesn't exist in Quay",
    fix_description="Use full 40-char SHA instead of 8-char"
)
```

**Output:**
```
✅ Saved tool fix to memory!

Tool: `bonfire_deploy`
Pattern: `manifest unknown`
Root cause: Short SHA doesn't exist in Quay
Fix: Use full 40-char SHA instead of 8-char

Next time this pattern appears, you'll be reminded of the fix.
```

## Memory Files

### memory/learned/tool_fixes.yaml

Stores tool-specific fixes from auto-remediation:

```yaml
tool_fixes:
  - tool_name: bonfire_deploy
    error_pattern: "manifest unknown"
    root_cause: "Short SHA doesn't exist in Quay"
    fix_applied: "Use full 40-char SHA instead of 8-char"
    date_learned: "2026-01-03"
    times_prevented: 3  # Incremented each time we skip this mistake

common_mistakes:
  missing_flags:
    description: "CLI tools often need --yes/--force for automation"
    examples:
      - bonfire: "--force"
      - glab: "--yes"
      - rh-issue: "--no-ai"

  wrong_formats:
    description: "Image tags, SHAs, and IDs have specific format requirements"
    examples:
      - "Git SHA must be full 40-char, not short 8-char"
      - "IMAGE_TAG for ITS deploy needs sha256 digest"
```

### memory/learned/patterns.yaml

General error patterns and solutions:

```yaml
error_patterns:
  - pattern: "ImagePullBackOff"
    meaning: "Cannot pull container image"
    fix: "Check image name, tag exists in Quay"
    commands:
      - quay_check_image_exists(...)

auth_patterns:
  - pattern: "No route to host"
    meaning: "VPN not connected"
    fix: "Connect to Red Hat VPN"
    commands:
      - vpn_connect()
```

## Integration Points

The learning loop is integrated into all tool execution paths:

| Path | Auto-Check | Auto-Suggest Learn |
|------|------------|-------------------|
| `@debuggable` decorator | ✅ On failure | ✅ In error output |
| `SkillExecutor._exec_tool` | ✅ On failure | ✅ In error message |
| `tool_exec` meta tool | ✅ On failure | ✅ In error output |
| Claude Agent (Slack bot) | ✅ On failure | ✅ In error output |

## Example Workflow

1. **Tool fails:**
   ```
   ❌ bonfire_deploy failed: manifest unknown

   💡 Known Issues Found!
   Previous fix for `bonfire_deploy`: Use full 40-char SHA
   ```

2. **Apply the known fix immediately**

3. **If it's a new error:**
   ```python
   debug_tool("bonfire_deploy", "new error message")
   # Follow instructions to fix
   ```

4. **After fix works:**
   ```python
   learn_tool_fix(
       "bonfire_deploy",
       "new error pattern",
       "why it failed",
       "what fixed it"
   )
   ```

5. **Next time:** The fix appears automatically!

## Commands

- `/debug-tool` - Debug and fix a failing tool
- `/learn-fix` - Save a tool fix to memory
- `/memory` - View all memory including learned fixes

## Agent Personas

All agents include the Learning Loop in their documentation:

- [Developer Persona](personas/developer.md#-learning-loop-auto-remediation--memory)
- [DevOps Persona](personas/devops.md#-learning-loop-auto-remediation--memory)
- [Incident Persona](personas/incident.md#-learning-loop-auto-remediation--memory)
- [Release Persona](personas/release.md#-learning-loop-auto-remediation--memory)
