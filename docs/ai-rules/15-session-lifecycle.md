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

1. **MANDATORY: Close session with summary**: `session_close(issues, accomplished, decisions, next_steps, files_changed)` - This writes a structured summary to the daily session log. The beer/coffee skills depend on this data for daily reports, Jira updates, and Slack posts.
2. **Save learnings**: If you discovered a fix, call `learn_tool_fix()`
3. **Update work state**: If work is in progress, call `memory_update("state/current_work", ...)`
4. **Update Jira**: If working on an issue, update its status (see 55-work-completion.md)

```json
// Example closing sequence - session_close is MANDATORY
session_close(
  issues="AAP-12345, AAP-12346",
  accomplished="Fixed auth token expiry bug\nAdded unit tests for refresh flow",
  decisions="Chose JWT refresh over session extension",
  next_steps="Address review comments on MR !1234",
  files_changed="src/auth/middleware.py, tests/test_auth.py"
)
learn_tool_fix("bonfire_deploy", "manifest unknown", "Short SHA", "Use full 40-char SHA")
```

**NEVER skip session_close if you did real work.** Even for short sessions, call it with what was accomplished.

## What Gets Auto-Logged (No Action Needed)

The system automatically logs these to the daily session file:

| Event | Logged By | Entry Type |
|-------|-----------|------------|
| Session start | `session_tools.py` | `session` |
| Skill completions | `skill_engine.py` | `skill` |
| Significant tool calls (git_commit, jira_transition, slack_send_message, etc.) | `debuggable.py` | `tool` |

You do NOT need to manually log these. They are captured automatically.

## What YOU Must Log (Mid-Session)

Since the system only captures structured events, the LLM must log **context, narrative, and decisions** -- things only a human+LLM conversation produces:

| What to Log | Example |
|-------------|---------|
| Investigation findings | `memory_session_log("Investigated auth failure", "Root cause: expired JWT key rotation")` |
| Meeting notes | `memory_session_log("Meeting: Sprint planning", "Agreed to prioritize AAP-12345")` |
| Architecture decisions | `memory_session_log("Decision: Use Redis for caching", "Evaluated vs memcached, Redis chosen for pub/sub support")` |
| Debugging outcomes | `memory_session_log("Fixed deployment failure", "Missing env var REDIS_URL in ClowdApp")` |
| Alert investigations | `memory_session_log("Alert: ProcessorStopped", "Pods healthy, issue was upstream traffic")` |
| Code review findings | `memory_session_log("Reviewed MR !1234", "Suggested error handling improvements in 3 files")` |

**Rule of thumb:** If it would be useful in tomorrow's morning briefing or today's end-of-day report, log it.

## Mid-Session Actions

During a session, keep context updated:

| Action | Tool |
|--------|------|
| Log context/decisions/findings | `memory_session_log(action, details)` |
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
