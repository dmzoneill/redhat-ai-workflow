# ⚡ workflow

> Core workflow and agent management tools

## Overview

The `aa-workflow` module provides core tools for session management, skill execution, and agent loading. These tools are always available regardless of which agent is loaded.

## Tool Count

**28 tools**

## Core Tools (Always Available)

| Tool | Description |
|------|-------------|
| `session_start` | Initialize session with context |
| `agent_list` | List available agents |
| `agent_load` | Switch to a different agent |
| `skill_list` | List available skills |
| `skill_run` | Execute a skill |
| `tool_list` | List all available tools |
| `tool_exec` | Execute any tool dynamically |
| `debug_tool` | Self-healing tool debugger |

## Memory Tools

| Tool | Description |
|------|-------------|
| `memory_read` | Read from persistent memory |
| `memory_write` | Write to persistent memory |
| `memory_update` | Update specific field |
| `memory_append` | Append to list |
| `memory_session_log` | Log action to session |

## Workflow Tools

| Tool | Description |
|------|-------------|
| `workflow_start_work` | Quick start work |
| `workflow_prepare_mr` | Prepare MR |
| `workflow_run_local_checks` | Run linting |
| `workflow_monitor_pipelines` | Check pipelines |
| `workflow_check_deploy_readiness` | Deployment checklist |
| `workflow_daily_standup` | Generate standup |

## Usage Examples

### Initialize Session

```python
session_start(agent="developer")
```

### Switch Agent

```python
agent_load("devops")
```

### Run Skill

```python
skill_run("start_work", '{"issue_key": "AAP-12345"}')
```

### List Tools

```python
tool_list(module="git")
```

### Debug Failed Tool

```python
debug_tool("bonfire_namespace_release", "Output is not a TTY")
```

## Memory Structure

```
memory/
├── state/
│   └── current_work.yaml      # Active issues, branches
├── learned/
│   └── patterns.yaml          # Error patterns and fixes
└── sessions/
    └── 2025-01-15.yaml        # Today's action log
```

## Loaded By

Always loaded - these are core tools.

## Related

- [Architecture](../architecture/README.md)
- [Agents](../agents/README.md)
- [Skills](../skills/README.md)

