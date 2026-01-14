# Claude Code Integration for Skill Error Recovery

## Overview

The skill error recovery system automatically detects if running in Claude Code and adapts its behavior accordingly.

## Detection Strategies

The system uses multiple strategies to detect Claude Code:

### 1. Environment Variables
```python
- CLAUDE_CODE=1
- MCP_SERVER_NAME=claude-code
- CLAUDE_CLI_VERSION=X.Y.Z
```text

### 2. Server Context
- Checks if FastMCP server has tool calling capabilities
- Queries server tool registry for AskUserQuestion

### 3. MCP Socket
- Looks for `MCP_SOCKET` environment variable
- Can create MCP client to call tools

### 4. Parent Process Detection
- Checks if parent process is Claude Code CLI
- Works on Linux via `/proc/{pid}/cmdline`

## How It Works

### In Claude Code Context

When running in Claude Code, the error recovery system:

1. **Detects the environment** on server startup
2. **Attempts to wire up AskUserQuestion** tool
3. **Falls back gracefully** if native UI unavailable

**Current Behavior**:
```
✅ Detection works - knows we're in Claude Code
⚠️  AskUserQuestion wiring - falls back to CLI
   (This is because AskUserQuestion is called BY Claude, not by the server)
```

### Outside Claude Code

When running standalone (CLI, scripts, etc.):

1. **Detection returns False**
2. **Uses CLI fallback** immediately
3. **No attempt to find AskUserQuestion**

## Future Enhancement: True Native UI Integration

For full native UI integration, we need:

### Option A: Cooperative Protocol
```python
# Skill error occurs
skill_engine.pause_and_signal_error({
    "step": "resolve_repo",
    "error": "'dict' object has no attribute 'repo'",
    "options": ["auto_fix", "edit", "skip", "abort", "continue"],
    "suggestion": "Change inputs.repo to inputs.get('repo')"
})

# Claude sees this structured error
# Claude calls: AskUserQuestion(...)
# Claude passes answer back to: skill_engine.resume(answer)
```

### Option B: Bidirectional Tool Calls
```python
# Server can request Claude to call a tool
server.request_tool_call(
    tool="AskUserQuestion",
    args={...},
    callback=handle_user_response
)
```text

### Option C: MCP Extensions
```
# MCP protocol extension for server->client tool calls
{
  "type": "tool_request",
  "from": "server",
  "tool": "AskUserQuestion",
  "args": {...}
}
```text

## Current Recommendation

For now, the **CLI fallback provides excellent UX**:

```
======================================================================
🔴 SKILL ERROR IN STEP: resolve_repo
======================================================================

**Error:** 'dict' object has no attribute 'repo'
**Suggestion:** Change inputs.repo to inputs.get('repo')

**Previous fixes:**
  ✅ auto_fix - Auto-fixed dict_attribute_access (2026-01-08)

======================================================================

What would you like to do?

  1. Auto-fix (Recommended)
     Apply automatic fix and retry

  2. Edit skill file
     Open YAML in editor

  3. Skip skill
     Stop and show manual commands

  4. Create GitHub issue
     Report bug automatically

  5. Continue anyway
     Debug mode

Enter choice (1-5): _
```

## Enabling/Disabling

### Disable Interactive Recovery

```python
executor = SkillExecutor(
    skill,
    inputs,
    enable_interactive_recovery=False  # Disable prompts
)
```

### Force CLI Fallback

```python
# Pass None to force CLI even in Claude Code
register_skill_tools(server, create_issue_fn, ask_question_fn=None)
```text

## Logging

Check logs to see detection results:

```
INFO: Claude Code detection: {'is_claude_code': True, 'has_ask_question': False, ...}
INFO: ℹ️  AskUserQuestion not available - using CLI fallback for skill errors
```

## Testing

Test the detection:

```python
from tool_modules.aa_workflow.src.claude_code_integration import (
    get_claude_code_capabilities
)

caps = get_claude_code_capabilities()
print(caps)
# {'is_claude_code': True/False, 'detection_method': '...', ...}
```

## Architecture Notes

**Why AskUserQuestion isn't directly callable:**

1. AskUserQuestion is a Claude Code tool FOR Claude (the LLM)
2. The MCP server PROVIDES tools TO Claude
3. There's no built-in mechanism for server to call client tools

**Possible solutions:**

- MCP protocol extension for bidirectional calls
- Pause/resume mechanism for skills
- Event-driven architecture with Claude as orchestrator

For now, the CLI provides a great user experience and works everywhere!
