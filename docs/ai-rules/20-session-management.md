# Session Management

## On Session Start - TRACK YOUR SESSION ID!

**IMPORTANT:** Multiple Cursor chats share the same MCP server. You MUST track your session_id to maintain separate context per chat.

```python
# Start a NEW session - SAVE the returned session_id!
session_start()  # Returns something like "Session ID: abc123" - REMEMBER THIS!

# To check YOUR session (not another chat's), pass your session_id:
session_info(session_id="abc123")  # Gets YOUR session info

# To resume a previous session:
session_start(session_id="abc123")  # Resumes existing session

# Start with specific options:
session_start(agent="devops")       # DevOps/monitoring
session_start(agent="developer")    # Coding/PRs
session_start(agent="incident")     # Incidents
session_start(agent="release")      # Releases
session_start(name="Fixing AAP-12345")  # Named session
```

## Session Management Commands

```python
session_list()                    # List all sessions
session_switch(session_id="...")  # Switch to different session
session_rename(name="...")        # Rename session
```

**Why track session_id?** Without it, `session_info()` returns whichever session was most recently active - which might be from a DIFFERENT chat window!

## Dynamic Agent Loading

**Tools switch automatically when you load a new agent!**

This is a single MCP server that dynamically loads/unloads tools based on the active agent.

```
You: Load the devops agent
Claude: [calls persona_load("devops")]
        Server unloads current tools, loads k8s_basic/bonfire_basic/jira_basic/quay (~74 tools)
        Cursor receives tools/list_changed notification and refreshes
```

## Available Personas

Load a persona when the task matches their expertise:

| Persona | Tools | Best For |
|---------|-------|----------|
| **developer** | git, gitlab, jira, lint, docker, make, code_search | Coding, PRs, code review |
| **devops** | k8s, bonfire, jira, quay, docker | Ephemeral deployments, K8s ops |
| **incident** | k8s, prometheus, kibana, jira, alertmanager | Production debugging |
| **release** | konflux, quay, jira, git, appinterface | Shipping releases |

> **Note:** All personas include `jira_basic`. Use `tool_exec()` for `_extra` module tools when needed.

## Memory Usage

- **Log important actions**: `memory_session_log("action", "details")`
- **Track active work**: `memory_append("state/current_work", "active_issues", '{...}')`
- **Save learned patterns**: `memory_write("learned/patterns", content)` for reusable knowledge
