# 🎭 Personas Reference

> **Terminology Note:** In this project, "agents" refers to **tool configuration profiles** (personas) that determine which MCP tools are available to Claude. This is NOT a multi-agent AI system - there is always a single Claude instance. The term "agent" is used because you "load an agent" to adopt a specialized role with focused tools.

Personas are **specialized tool configurations** with curated tool sets. Switch personas to get different capabilities.

## Quick Reference

| Persona | Command | Tools | Focus |
|---------|---------|-------|-------|
| [👨‍💻 developer](./developer.md) | `Load developer agent` | ~78 | Daily coding, PRs |
| [🔧 devops](./devops.md) | `Load devops agent` | ~83 | Deployments, K8s |
| [🚨 incident](./incident.md) | `Load incident agent` | ~89 | Production debugging |
| [📦 release](./release.md) | `Load release agent` | ~91 | Shipping releases |
| [💬 slack](./slack.md) | `Load slack agent` | ~85 | Slack automation |
| [🌐 universal](./universal.md) | `Load universal agent` | ~92 | All-in-one |
| [🔹 core](./core.md) | `Load core agent` | ~76 | Essential shared |

## How Persona Loading Works

```mermaid
sequenceDiagram
    participant User
    participant Claude
    participant MCP as MCP Server
    participant Cursor

    User->>Claude: "Load devops agent"
    Claude->>MCP: persona_load("devops")
    MCP->>MCP: Unload current tools
    MCP->>MCP: Load k8s, bonfire, quay, gitlab
    MCP->>Cursor: tools/list_changed notification
    Cursor->>Cursor: Refresh tool list
    MCP-->>Claude: Persona + tool count
    Claude-->>User: "🔧 DevOps persona loaded with ~95 tools"
```

## Switching Personas

You can switch personas at any time:

```
You: Load the developer agent
Claude: 👨‍💻 Developer persona loaded (~78 tools)

You: Actually I need to deploy, load devops
Claude: 🔧 DevOps persona loaded (~83 tools)
        [Tools automatically switch!]
```

## Tool Limit

Each persona is designed to stay under Cursor's 128 tool limit. Tool counts are based on split module composition:

| Persona | Modules | Estimated Tools |
|---------|---------|-----------------|
| developer | workflow, git_basic, gitlab_basic, jira_basic | ~78 |
| devops | workflow, k8s_basic, bonfire_basic, jira_basic, quay | ~83 |
| incident | workflow, k8s_basic, prometheus_basic, kibana, jira_basic, alertmanager | ~89 |
| release | workflow, konflux_basic, quay, jira_basic, git_basic | ~91 |
| slack | workflow, slack, jira_basic, k8s_basic, prometheus_basic | ~85 |
| universal | workflow, git_basic, gitlab_basic, jira_basic, k8s_basic | ~92 |
| core | workflow, git_basic, jira_basic, k8s_basic | ~76 |

> **Note:** `_basic` modules contain essential tools. Use `tool_exec()` for `_extra` tools when needed.

## Persona Tool Modules

All personas include `workflow` module (required for skills/memory).

```mermaid
graph TD
    subgraph Developer["👨‍💻 Developer ~78"]
        D_WF[workflow]
        D_GIT[git_basic]
        D_GITLAB[gitlab_basic]
        D_JIRA[jira_basic]
    end

    subgraph DevOps["🔧 DevOps ~83"]
        O_WF[workflow]
        O_K8S[k8s_basic]
        O_BON[bonfire_basic]
        O_JIRA[jira_basic]
        O_QUAY[quay]
    end

    subgraph Incident["🚨 Incident ~89"]
        I_WF[workflow]
        I_K8S[k8s_basic]
        I_PROM[prometheus_basic]
        I_KIB[kibana]
        I_JIRA[jira_basic]
        I_ALERT[alertmanager]
    end

    subgraph Release["📦 Release ~91"]
        R_WF[workflow]
        R_KON[konflux_basic]
        R_QUAY[quay]
        R_JIRA[jira_basic]
        R_GIT[git_basic]
    end

    style Developer fill:#3b82f6,stroke:#2563eb,color:#fff
    style DevOps fill:#10b981,stroke:#059669,color:#fff
    style Incident fill:#ef4444,stroke:#dc2626,color:#fff
    style Release fill:#8b5cf6,stroke:#7c3aed,color:#fff
```

## Core Tools (Always Available)

These tools are available regardless of which persona is loaded:

| Tool | Purpose |
|------|---------|
| `persona_load` | Switch to a different persona |
| `persona_list` | List available personas |
| `session_start` | Initialize session with context |
| `debug_tool` | Self-healing tool debugger |
| `skill_run` | Execute a skill |
| `skill_list` | List available skills |
| `vpn_connect` | Connect to VPN (fixes network errors) |
| `kube_login` | Refresh k8s credentials |

## Persona Variants

Several personas have "slim" variants with fewer tool modules for combining:

| Variant | Base Persona | Description |
|---------|--------------|-------------|
| `developer-slim` | developer | Core dev tools only (3 modules) |
| `devops-slim` | devops | Essential k8s/deploy (3 modules) |
| `incident-slim` | incident | Fast incident response (4 modules) |
| `release-slim` | release | Streamlined release (4 modules) |

**Special Personas:**

| Persona | Description |
|---------|-------------|
| `core` | Essential shared tools (most modules) |
| `universal` | Developer + DevOps combined (10 modules) |

> All personas include `workflow` module for skills, memory, and infrastructure tools

## Persona Configuration

Personas are defined in YAML files in the `personas/` directory:

```yaml
name: developer
description: Coding, PRs, and code review
persona: personas/developer.md

# Using split modules to stay under 100 tools
tools:
  - workflow        # 33 tools - Core (memory, persona, session, skill, infra, meta)
  - git_basic       # 14 tools - Essential git (status, log, diff, add, commit, push, pull)
  - gitlab_basic    # 16 tools - MRs, CI/CD basics
  - jira_basic      # 15 tools - Issue viewing, search, status updates, comments

# Total: ~78 tools ✅
# Note: git_extra, gitlab_extra, jira_extra available via tool_exec()

skills:
  - coffee
  - start_work
  - create_mr
  - mark_mr_ready
  # ...
```

## See Also

- [MCP Servers](../tool-modules/README.md) - Tool modules
- [Skills](../skills/README.md) - Available workflows
