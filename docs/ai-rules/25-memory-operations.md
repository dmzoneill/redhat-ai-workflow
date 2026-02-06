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
| `memory_session_log(action, details)` | Log to today's session |

### Examples

```python
# Update a field
memory_update("state/current_work", "active_issues[0].status", '"In Progress"')

# Append to a list
memory_append("state/current_work", "follow_ups", '{"task": "Review MR", "priority": "high"}')

# Log an action
memory_session_log("Created MR !1234", "For AAP-12345, fixes auth bug")
```

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
    └── YYYY-MM-DD.yaml        # Daily session logs
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

### End of Day Summary

```python
memory_session_log("End of day", '''
  Completed:
  - Fixed AAP-12345 (MR !1234)
  - Reviewed AAP-12346
  Tomorrow:
  - Deploy to stage
  - Address review comments
''')
```
