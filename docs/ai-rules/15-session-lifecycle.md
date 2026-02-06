# Session Lifecycle

## Opening Actions (Start of Every Session)

When starting ANY session, execute these in order:

1. **Start session**: `session_start()` - Returns session ID, loads context
2. **Discover tools**: `tool_list()` - See available tools for current persona
3. **List skills**: `skill_list()` - See available workflows

```json
// Example opening sequence
session_start()           // Get session ID, load context
tool_list()               // Discover available tools
skill_list()              // See available workflows
```

## Closing Actions (End of Session)

Before ending a session or when work is complete:

1. **Log session**: `memory_session_log("Session ended", "summary of work done")`
2. **Save learnings**: If you discovered a fix, call `learn_tool_fix()`
3. **Update work state**: If work is in progress, call `memory_update("state/current_work", ...)`
4. **Update Jira**: If working on an issue, update its status (see 55-work-completion.md)

```json
// Example closing sequence
memory_session_log("Completed AAP-12345", "Fixed auth bug, created MR !1234")
learn_tool_fix("bonfire_deploy", "manifest unknown", "Short SHA", "Use full 40-char SHA")
```

## Mid-Session Actions

During a session, keep context updated:

| Action | Tool |
|--------|------|
| Log important action | `memory_session_log(action, details)` |
| Save a pattern/fix | `learn_tool_fix(tool, pattern, cause, fix)` |
| Check for known fixes | `check_known_issues(tool, error)` |
| Update work state | `memory_update("state/current_work", path, value)` |

## Session Recovery

If a session is interrupted or you need to resume:

```json
// Resume with session ID
session_start(session_id="abc123")

// Or start fresh and load context
session_start()
memory_read("state/current_work")
```
