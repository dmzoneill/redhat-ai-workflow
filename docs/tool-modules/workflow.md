# ⚡ workflow

> Core workflow and persona management tools

## Overview

The `aa_workflow` module provides core tools for session management, skill execution, and persona loading. These tools are always available regardless of which persona is loaded.

> **Terminology:** "Agents" here means tool configuration profiles (personas), not separate AI instances.

## Tool Count

**18 tools**

## Core Tools (Always Available)

| Tool | Description |
|------|-------------|
| `session_start` | Initialize session with context |
| `persona_list` | List available personas |
| `persona_load` | Switch to a different persona |
| `skill_list` | List available skills |
| `skill_run` | Execute a skill |
| `tool_list` | List all available tools |
| `tool_exec` | Execute any tool dynamically |
| `debug_tool` | Self-healing tool debugger |

## Memory Tools (9 tools)

| Tool | Description |
|------|-------------|
| `memory_read` | Read from persistent memory |
| `memory_write` | Write to persistent memory |
| `memory_update` | Update specific field |
| `memory_append` | Append to list |
| `memory_query` | Query memory using JSONPath |
| `memory_session_log` | Log action to session |
| `check_known_issues` | Check memory for known fixes |
| `learn_tool_fix` | Save a fix to memory |
| `memory_stats` | Get memory system statistics |

## Infrastructure Tools (2 tools)

| Tool | Description |
|------|-------------|
| `vpn_connect` | Connect to Red Hat VPN |
| `kube_login` | Refresh Kubernetes credentials |

## Usage Examples

### Initialize Session

```python
session_start(agent="developer")
```

### Switch Agent

```python
persona_load("devops")
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
```text

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
- [Agents](../personas/README.md)
- [Skills](../skills/README.md)
