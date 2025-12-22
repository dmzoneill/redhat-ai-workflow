# Memory System

Persistent storage for context that survives across Claude sessions.

## Structure

```
memory/
├── state/              # Current work state (changes frequently)
│   ├── current_work.yaml   # Active issues, branches, MRs
│   └── environments.yaml   # Stage/prod health status
├── learned/            # Accumulated knowledge (grows over time)
│   ├── patterns.yaml       # Error patterns and fixes
│   └── runbooks.yaml       # Procedures that worked
└── sessions/           # Daily session logs (auto-created)
    └── 2024-12-21.yaml     # Today's actions
```

## Usage

### Reading Memory

```
memory_read()                     # List all memory files
memory_read("state/current_work") # Read specific file
```

### Writing Memory

```
# Overwrite entire file
memory_write("learned/patterns", "content...")

# Update a specific field
memory_update("state/current_work", "notes", "New notes here")

# Append to a list
memory_append("state/current_work", "active_issues", '{"key": "AAP-123", "summary": "..."}')
```

### Session Logging

```
# Log an action (creates/updates sessions/YYYY-MM-DD.yaml)
memory_session_log("action", "details")

# Examples:
memory_session_log("started_work", "AAP-12345 - Implement API")
memory_session_log("created_mr", "MR !456 for AAP-12345")
memory_session_log("deployed", "v2.3.1 to stage")
memory_session_log("fixed", "OOMKilled issue by increasing limits")
```

## Best Practices

1. **Log important actions** - Future you will thank you
2. **Update current_work** when starting/finishing tasks
3. **Record patterns** when you solve a tricky problem
4. **Add runbooks** for procedures you might repeat

## Auto-Loading

When you call `session_start()`, it automatically:
1. Reads `state/current_work.yaml` to show your context
2. Reads today's session log if it exists
3. Shows what you were working on

This gives you continuity across sessions.
