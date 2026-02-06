# Session Management

## On Session Start - TRACK YOUR SESSION ID!

**IMPORTANT:** Multiple Cursor chats share the same MCP server. You MUST track your session_id to maintain separate context per chat.

## Bootstrap Context - AUTO-LOADED

When you call `session_start()`, the system automatically:

1. **Classifies intent** from the session name/project context
2. **Suggests a persona** based on the detected intent
3. **Auto-loads the persona** if confidence > 80%
4. **Shows current work** (active issues, branches)
5. **Recommends next actions** based on intent

### What Bootstrap Returns

```
## 🎯 Bootstrap Context

**Detected Intent:** code_lookup (85% confidence)
**Auto-loading Persona:** developer (confidence: 85%)
  ✅ Switched from researcher to developer
**Active Issues:** AAP-12345, AAP-12346
**Recommended Actions:**
  - Use code_search to find relevant code
  - Check memory for similar patterns
```

### Acting on Bootstrap Context

After `session_start()` returns, **follow the recommended actions**:

| Intent | Recommended Follow-up |
|--------|----------------------|
| `code_lookup` | Call `memory_query("...")` with code-related question |
| `troubleshooting` | Call `check_known_issues()` for known fixes |
| `issue_context` | Call `jira_view_issue()` for issue details |
| `status_check` | Review the current work shown in bootstrap |
| `documentation` | Call `inscope_ask()` for documentation |

### If Persona Wasn't Auto-Loaded

If the suggested persona confidence is below 80%, the bootstrap shows:

```
**Suggested Persona:** incident (confidence: 70% - below auto-load threshold)
```

In this case, **decide based on the user's request** whether to load it:

```json
// If the task matches the suggestion, load it manually
CallMcpTool(toolName: "persona_load", arguments: {"persona": "incident"})
```

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

## Unified Memory Query

**NEW:** Use `memory_ask` for intelligent context gathering across all sources:

### Memory Source Latency Classes

Sources are categorized by latency to keep bootstrap fast:

| Class | Sources | Latency | Used In |
|-------|---------|---------|---------|
| **Fast** | yaml, code, slack | <2s | Bootstrap, default queries |
| **Slow** | inscope, jira, gitlab, github, calendar, gmail, gdrive | >2s | On-demand only |

**Bootstrap only queries fast sources** to keep session startup under 2 seconds.

### Querying Memory

```json
// Auto-selects FAST sources only (default)
CallMcpTool(
  server: "project-0-redhat-ai-workflow-aa_workflow",
  toolName: "memory_ask",
  arguments: {"question": "What am I working on?"}
)

// Include slow sources for comprehensive results
CallMcpTool(
  toolName: "memory_ask",
  arguments: {
    "question": "How do I configure RDS?",
    "include_slow": true  // Includes inscope, jira, etc.
  }
)

// Query specific slow sources explicitly
CallMcpTool(
  toolName: "memory_ask",
  arguments: {
    "question": "What's the status of AAP-12345?",
    "sources": "jira"  // Explicit source bypasses latency filter
  }
)

// Query InScope for documentation
CallMcpTool(
  toolName: "memory_ask",
  arguments: {
    "question": "Konflux release process",
    "sources": "inscope"
  }
)
```

### When to Use Each Approach

| Situation | Approach |
|-----------|----------|
| Quick context check | Default (fast sources only) |
| Need documentation | `sources="inscope"` |
| Need issue details | `sources="jira"` |
| Need MR/pipeline info | `sources="gitlab"` |
| Comprehensive search | `include_slow=true` |
| Simple YAML read | Use `memory_read` directly |

### memory_ask Output

Returns LLM-friendly markdown with:
- **Intent classification** at the top
- **Results grouped by source**
- **Relevance scores** for weighting
- **Code blocks** preserved
- **Tip** about slow sources if not included
