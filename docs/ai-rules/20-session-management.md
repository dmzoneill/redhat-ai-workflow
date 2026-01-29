# Session Management

## On Session Start - TRACK YOUR SESSION ID!

**IMPORTANT:** Multiple Cursor chats share the same MCP server. You MUST track your session_id to maintain separate context per chat.

## MCP Tool Call Syntax

All session tools are called via `CallMcpTool` with the server `project-0-redhat-ai-workflow-aa_workflow`.

```json
// Start a NEW session - SAVE the returned session_id!
CallMcpTool(
  server: "project-0-redhat-ai-workflow-aa_workflow",
  toolName: "session_start",
  arguments: {}  // Returns "Session ID: abc123" - REMEMBER THIS!
)

// Resume an existing session
CallMcpTool(
  server: "project-0-redhat-ai-workflow-aa_workflow",
  toolName: "session_start",
  arguments: {"session_id": "abc123"}
)

// Start with specific agent/persona
CallMcpTool(
  server: "project-0-redhat-ai-workflow-aa_workflow",
  toolName: "session_start",
  arguments: {"agent": "devops"}  // or "developer", "incident", "release"
)

// Start with a name
CallMcpTool(
  server: "project-0-redhat-ai-workflow-aa_workflow",
  toolName: "session_start",
  arguments: {"name": "Fixing AAP-12345"}
)

// Check YOUR session (pass your session_id!)
CallMcpTool(
  server: "project-0-redhat-ai-workflow-aa_workflow",
  toolName: "session_info",
  arguments: {"session_id": "abc123"}
)
```

## Session Management Commands

```json
// List all sessions
CallMcpTool(toolName: "session_list", arguments: {})

// Switch to different session
CallMcpTool(toolName: "session_switch", arguments: {"session_id": "..."})

// Rename current session
CallMcpTool(toolName: "session_rename", arguments: {"name": "..."})
```

**Why track session_id?** Without it, `session_info()` returns whichever session was most recently active - which might be from a DIFFERENT chat window!

## Project Detection - CRITICAL

**The workspace may be `redhat-ai-workflow`, but the user might be working on a DIFFERENT project!**

When starting a conversation, Claude MUST determine the correct project and set it:

1. **Look for issue keys** (AAP-XXXXX) - these indicate work context
2. **Look for repository mentions** in user's message (automation-analytics-backend, pdf-generator)
3. **Look for file paths** that indicate which repo (/home/.../automation-analytics-backend/...)
4. **Look for GitLab paths** (automation-analytics/automation-analytics-backend)
5. **If uncertain, ASK** the user which project they're working on

Then call `session_set_project` to set the correct project:

```json
// Set project for current session
CallMcpTool(
  server: "project-0-redhat-ai-workflow-aa_workflow",
  toolName: "session_set_project",
  arguments: {"project": "automation-analytics-backend"}
)

// Or set when starting session
CallMcpTool(
  server: "project-0-redhat-ai-workflow-aa_workflow",
  toolName: "session_start",
  arguments: {"project": "automation-analytics-backend"}
)
```

**Available Projects:**
- `automation-analytics-backend` - Main backend API (AAP issues, billing, reports)
- `pdf-generator` - PDF generation service
- `app-interface` - SaaS deployment configs (APPSRE issues)
- `konflux-release-data` - Release data (KONFLUX issues)
- `redhat-ai-workflow` - This workflow system itself

**DO NOT assume `redhat-ai-workflow` is the project just because that's the workspace.**

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
