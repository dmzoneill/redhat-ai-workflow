# Memory Operations

## Overview

Memory persists context across sessions. Use it to:
- Track active work (issues, branches, MRs)
- Store learned patterns and fixes
- Log session activity
- Query across multiple data sources

## Reading Memory

| Tool | Use Case |
|------|----------|
| `memory_read(key)` | Read a specific YAML file |
| `memory_read()` | List all available memory files |
| `memory_ask(question)` | Query across all sources (auto-routes) |
| `memory_search(query)` | Semantic search across sources |

### Examples

```python
# Read specific memory
memory_read("state/current_work")
memory_read("learned/patterns")

# Query with auto-routing
memory_ask("What am I working on?")
memory_ask("Where is the billing calculation?")
```

## Writing Memory

| Tool | Use Case |
|------|----------|
| `memory_write(key, content)` | Replace entire file |
| `memory_update(key, path, value)` | Update specific field |
| `memory_append(key, list_path, item)` | Add to a list |
| `memory_session_log(action, details)` | Log context/decisions to today's session |
| `session_close(issues, accomplished, ...)` | **MANDATORY** structured session summary at end |

### Examples

```python
# Update a field
memory_update("state/current_work", "active_issues[0].status", '"In Progress"')

# Append to a list
memory_append("state/current_work", "follow_ups", '{"task": "Review MR", "priority": "high"}')

# Log context/narrative (things only the LLM knows)
memory_session_log("Investigated auth failure", "Root cause: JWT key rotation expired")

# Close session with structured summary (MANDATORY before ending)
session_close(
    issues="AAP-12345, AAP-12346",
    accomplished="Fixed auth bug\nAdded tests",
    decisions="Chose JWT refresh approach",
    next_steps="Address MR review comments"
)
```

## Session Log Format

Daily session logs (`memory/sessions/YYYY-MM-DD.yaml`) use an enriched entry format.
Each entry has a `type` field indicating its source:

| Type | Source | Description |
|------|--------|-------------|
| `session` | Auto (session_tools.py) | Session start/end events |
| `skill` | Auto (skill_engine.py) | Skill execution completions |
| `tool` | Auto (debuggable.py) | Significant tool calls (commits, MR creation, Jira transitions) |
| `manual` | LLM (memory_session_log) | Context, decisions, findings logged by the LLM |
| `summary` | LLM (session_close) | Structured session summary with issues, accomplished, next_steps |
| `cron` | Auto (cron jobs) | Scheduled task results |

### Entry Fields

All entries have: `time`, `action`, `type`. Additional fields by type:

| Field | Types | Description |
|-------|-------|-------------|
| `session_id` | all | Which chat session produced this entry |
| `details` | all | Human-readable description |
| `issues` | all | Jira issue keys (auto-extracted from text) |
| `skill_name` | skill | Name of the skill that ran |
| `tool_name` | tool | Name of the tool that was called |
| `result` | skill, tool | `success` or `failure` |
| `duration_ms` | skill, tool | Execution time in milliseconds |
| `accomplished` | summary | List of what was done |
| `decisions` | summary | List of key decisions |
| `next_steps` | summary | List of unfinished work |
| `files_changed` | summary | List of key files modified |

### Concurrency

Multiple sessions can write to the same daily file safely -- all writes use `fcntl.flock` file locking.

## Learning from Errors

| Tool | Use Case |
|------|----------|
| `check_known_issues(tool, error)` | Check if we've seen this error before |
| `learn_tool_fix(tool, pattern, cause, fix)` | Save a fix for future reference |

### Examples

```python
# Check for known fixes
check_known_issues("bonfire_deploy", "manifest unknown")

# Save a fix
learn_tool_fix(
    tool_name="bonfire_deploy",
    error_pattern="manifest unknown",
    root_cause="Short SHA doesn't exist in Quay",
    fix_description="Use full 40-char SHA from git rev-parse"
)
```

## Querying External Sources

Use `memory_ask` with explicit sources for external data:

| Source | Query Example |
|--------|---------------|
| `jira` | `memory_ask("AAP-12345 status", sources="jira")` |
| `gitlab` | `memory_ask("MR pipeline status", sources="gitlab")` |
| `inscope` | `memory_ask("ClowdApp configuration", sources="inscope")` |
| `code` | `memory_ask("billing calculation", sources="code")` |
| `slack` | `memory_ask("RDS discussion", sources="slack")` |

### Latency Classes

Sources are categorized by response time:

| Class | Sources | Latency |
|-------|---------|---------|
| **Fast** | yaml, code, slack | <2s |
| **Slow** | inscope, jira, gitlab, github, calendar, gmail, gdrive | >2s |

**Default queries use fast sources only.** Add `include_slow=True` for comprehensive results:

```python
# Fast sources only (default)
memory_ask("What am I working on?")

# Include slow sources
memory_ask("How do I configure RDS?", include_slow=True)

# Query specific slow source
memory_ask("AAP-12345 details", sources="jira")
```

## Memory File Structure

```
memory/
├── state/
│   ├── current_work.yaml      # Active issues, branches, MRs
│   ├── environments.yaml      # Stage/prod health status
│   └── projects/
│       └── <project>/
│           └── current_work.yaml  # Per-project work state
├── learned/
│   ├── patterns.yaml          # Error patterns and solutions
│   ├── tool_fixes.yaml        # Tool-specific fixes
│   └── runbooks.yaml          # Procedures that worked
└── sessions/
    └── YYYY-MM-DD.yaml        # Daily session logs (enriched format)
```

## Common Patterns

### Starting Work on an Issue

```python
memory_append("state/current_work", "active_issues", '''
  key: AAP-12345
  summary: Fix authentication bug
  status: In Progress
  branch: aap-12345-fix-auth
''')
```

### Recording a Learning

```python
learn_tool_fix(
    "kubectl_logs",
    "container not found",
    "Pod has multiple containers",
    "Specify container with -c flag"
)
```

### End of Session (MANDATORY)

```python
session_close(
    issues="AAP-12345",
    accomplished="Fixed auth bug in middleware\nAdded 3 unit tests",
    decisions="Used JWT refresh instead of session extension",
    next_steps="Deploy to stage\nAddress review comments on MR !1234",
    files_changed="src/auth/middleware.py, tests/test_auth.py"
)
```
