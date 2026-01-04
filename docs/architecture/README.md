# 🏗️ Architecture Overview

This document describes the architecture of the AI Workflow MCP server.

## Terminology

| Term | Meaning in This Project |
|------|------------------------|
| **Agent / Persona** | A tool configuration profile that determines which MCP tools are loaded (e.g., developer, devops, incident). NOT a separate AI instance. |
| **Tool Module** | A plugin directory containing MCP tool implementations (e.g., `aa-git/`, `aa-jira/`). |
| **Skill** | A YAML-defined multi-step workflow that chains tools together. |
| **Memory** | Persistent YAML files that maintain context across Claude sessions. |
| **Auto-Heal** | Automatic detection and remediation of VPN/auth failures in skills. |

> **Important:** This is a **single-agent system** with dynamic tool loading. When you "load an agent," you're changing which tools Claude has access to, not spawning a separate AI. The term "agent" refers to adopting a persona/role.

## Core Concepts

```mermaid
graph TB
    subgraph IDE["🖥️ Your IDE (Cursor)"]
        YOU[👤 You] --> |natural language| CLAUDE[🤖 Claude AI]
    end

    subgraph CORE["🧠 AI Workflow Core"]
        CLAUDE --> |MCP Protocol| MCP[📡 MCP Server]
        MCP --> AGENTS[🎭 Agents]
        MCP --> SKILLS[⚡ Skills]
        MCP --> MEMORY[💾 Memory]
        MCP --> TOOLS[🔧 Tools]
    end

    subgraph EXTERNAL["🌐 External Services"]
        TOOLS --> JIRA[📋 Jira]
        TOOLS --> GITLAB[🦊 GitLab]
        TOOLS --> K8S[☸️ Kubernetes]
        TOOLS --> GIT[📂 Git]
        TOOLS --> MORE[...]
    end

    style CLAUDE fill:#6366f1,stroke:#4f46e5,color:#fff
    style MCP fill:#10b981,stroke:#059669,color:#fff
```

## The Five Pillars

### 🔧 Tools

Individual MCP tool functions that perform specific actions:

- **260+ tools** across 16 modules
- Each tool is a simple, focused function
- Wrapped with `@debuggable` for self-healing
- Shared utilities in `server/src/utils.py`

### 🎭 Agents

Specialized personas with curated tool sets:

| Agent | Focus | Tools |
|-------|-------|-------|
| developer | Coding, PRs | ~86 tools |
| devops | Deployments, K8s | ~90 tools |
| incident | Production debugging | ~78 tools |
| release | Shipping | ~69 tools |
| slack | Slack bot daemon | ~52 tools |

### ⚡ Skills

Multi-step workflows that chain tools:

- YAML-defined workflows (50 skills)
- Conditional logic and branching
- Template substitution (Jinja2)
- Error handling
- **Auto-heal patterns** for VPN/auth issues
- **44 shared parsers** in `scripts/common/parsers.py`

### 💾 Memory

Persistent context across sessions:

- Current work state
- Learned patterns
- Session logs
- Tool failure tracking

### 🔄 Auto-Heal

Two levels of automatic remediation:

| Level | Mechanism | Scope |
|-------|-----------|-------|
| **Tool-Level** | `@debuggable` + `debug_tool()` | Fix tool source code |
| **Skill-Level** | Auto-heal YAML patterns | Fix VPN/auth at runtime |

## Dynamic Agent Loading

```mermaid
sequenceDiagram
    participant User
    participant Claude
    participant MCP as MCP Server
    participant Loader as AgentLoader
    participant Cursor

    User->>Claude: "Load devops agent"
    Claude->>MCP: persona_load("devops")
    MCP->>Loader: switch_agent("devops")
    Loader->>Loader: Unload current tools
    Loader->>Loader: Load k8s, bonfire, quay, gitlab
    Loader->>MCP: Register new tools
    MCP->>Cursor: tools/list_changed notification
    Cursor->>Cursor: Refresh tool list
    Loader-->>MCP: Agent persona
    MCP-->>Claude: "Loaded 90 tools"
```

## Tool Modules

```
tool_modules/
├── server/             # Core server, agent loading
├── aa-workflow/        # Workflow tools (30 tools)
├── aa-git/             # Git operations (19 tools)
├── aa-gitlab/          # GitLab MRs, pipelines (35 tools)
├── aa-jira/            # Jira issues (28 tools)
├── aa-k8s/             # Kubernetes ops (26 tools)
├── aa-bonfire/         # Ephemeral environments (21 tools)
├── aa-quay/            # Container registry (8 tools)
├── aa-prometheus/      # Metrics queries (13 tools)
├── aa-alertmanager/    # Alert management (7 tools)
├── aa-kibana/          # Log search (9 tools)
├── aa-google-calendar/ # Calendar & meetings (6 tools)
├── aa-gmail/           # Email processing (6 tools)
├── aa-slack/           # Slack integration (16 tools)
├── aa-konflux/         # Build pipelines (40 tools)
└── aa-appinterface/    # App-interface config (8 tools)
```

## Auto-Heal Architecture

### Tool-Level Auto-Debug

All tools support self-healing via the `@debuggable` decorator:

```mermaid
flowchart LR
    A[Tool Fails] --> B[Returns ❌ with hint]
    B --> C[Claude calls debug_tool]
    C --> D[Analyze source code]
    D --> E[Propose fix]
    E --> F{User confirms?}
    F -->|Yes| G[Apply fix & commit]
    G --> H[Retry operation]
```

### Skill-Level Auto-Heal

All 42 production skills include auto-healing for VPN/auth:

```mermaid
flowchart LR
    A[Tool Call] --> B{Success?}
    B -->|Yes| C[Continue]
    B -->|No| D[Detect Failure]
    D --> E{VPN Issue?}
    E -->|Yes| F[vpn_connect]
    E -->|No| G{Auth Issue?}
    G -->|Yes| H[kube_login]
    G -->|No| I[Log & Report]
    F --> J[Retry]
    H --> J
    J --> C
```

### Auto-Heal Pattern in Skills

```yaml
# Original tool call
- name: get_pods
  tool: kubectl_get_pods
  args: { namespace: "{{ namespace }}" }
  output: pods_result
  on_error: continue

# Detect failure
- name: detect_failure_pods
  condition: "pods_result and 'error' in str(pods_result).lower()"
  compute: |
    error_text = str(pods_result)[:300].lower()
    result = {
      "needs_vpn": 'no route' in error_text,
      "needs_auth": 'unauthorized' in error_text,
    }
  output: failure_pods

# Quick fix VPN
- name: quick_fix_vpn_pods
  condition: "failure_pods and failure_pods.get('needs_vpn')"
  tool: vpn_connect
  on_error: continue

# Quick fix auth
- name: quick_fix_auth_pods
  condition: "failure_pods and failure_pods.get('needs_auth')"
  tool: kube_login
  args: { cluster: "{{ env }}" }
  on_error: continue

# Retry after fix
- name: retry_get_pods
  condition: "failure_pods"
  tool: kubectl_get_pods
  args: { namespace: "{{ namespace }}" }
  output: pods_retry_result
```

## Shared Utilities

### MCP Tool Utilities (`server/src/utils.py`)

Common utilities shared across all MCP servers:

- `load_config()` - Load config.json with caching
- `get_kubeconfig(env)` - Get kubeconfig for environment (ephemeral/stage/prod)
- `run_cmd()` - Execute shell commands with proper output handling
- `get_token_from_kubeconfig()` - Extract bearer tokens for API calls
- `resolve_repo_path()` - Resolve repository paths from config

### Shared Parsers (`scripts/common/parsers.py`)

**44 reusable parser functions** to avoid regex duplication in skills:

| Category | Examples |
|----------|----------|
| MR Parsing | `parse_mr_list`, `extract_mr_id_from_url`, `analyze_mr_status` |
| Jira | `extract_jira_key`, `parse_jira_issues`, `validate_jira_key` |
| Git | `parse_git_log`, `parse_git_branches`, `extract_conflict_files` |
| Kubernetes | `parse_kubectl_pods`, `parse_namespaces` |
| Alerts | `parse_prometheus_alert`, `parse_alertmanager_output` |

### Auto-Heal Utilities (`scripts/common/auto_heal.py`)

Shared auto-heal functions for skills:

- `detect_vpn_error(text)` - Check for VPN-related errors
- `detect_auth_error(text)` - Check for auth-related errors
- `log_failure(tool, error, skill)` - Log failure to memory

## Configuration

Central configuration via `config.json`:

- Repository paths and GitLab projects
- Kubernetes namespaces
- Jira settings
- Slack channels (team, standup, alerts)
- Google API settings
- User preferences (including email aliases)

## See Also

- [MCP Implementation Details](./mcp-implementation.md) - Server code & patterns
- [Workflow Module Architecture](./workflow-modules.md) - aa-workflow internal structure
- [Skills Reference](../skills/README.md) - All 50 available skills
- [Learning Loop](../learning-loop.md) - Auto-remediation and memory integration
- [Skill Auto-Heal Plan](../plans/skill-auto-heal.md) - Auto-heal implementation details
- [README](../../README.md) - Getting started
