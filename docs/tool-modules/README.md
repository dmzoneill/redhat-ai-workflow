# 🔧 Tool Modules Reference

Tool modules are MCP plugins that provide specific capabilities. Each module contains related tools that are loaded based on which persona is active.

> **Terminology:** "Personas" (sometimes called "agents") are tool configuration profiles that determine which modules are loaded. This is NOT a multi-agent AI system.

## Quick Reference

Large modules are split into `_basic` and `_extra` variants to allow personas to load only essential tools.

| Module | Variant | Tools | Description |
|--------|---------|-------|-------------|
| [workflow](./workflow.md) | - | 33 | Core: agents, skills, memory, vpn_connect, kube_login |
| [git](./git.md) | basic | 14 | Essential git (status, log, diff, add, commit, push) |
| [git](./git.md) | extra | 17 | Advanced git (rebase, merge, reset, docker) |
| [gitlab](./gitlab.md) | basic | 16 | MRs, CI basics (list, view, create, comment) |
| [gitlab](./gitlab.md) | extra | 15 | Advanced (approve, merge, rebase, diff) |
| [jira](./jira.md) | basic | 15 | Essential (view, search, status, comments) |
| [jira](./jira.md) | extra | 13 | Advanced (sprint, links, flags, priorities) |
| [k8s](./k8s.md) | basic | 14 | Essential k8s (pods, logs, deployments) |
| [k8s](./k8s.md) | extra | 14 | Advanced k8s (exec, cp, saas, events) |
| [bonfire](./bonfire.md) | basic | 10 | Namespace management (reserve, list, release) |
| [bonfire](./bonfire.md) | extra | 11 | Advanced (deploy, process, full workflow) |
| [konflux](./konflux.md) | basic | 18 | Pipelines, components, snapshots, status |
| [konflux](./konflux.md) | extra | 18 | Releases, integration tests, builds |
| [prometheus](./prometheus.md) | basic | 8 | Queries, alerts, health checks |
| [prometheus](./prometheus.md) | extra | 5 | Range queries, rules, series |
| [kibana](./kibana.md) | - | 10 | Log search (not split - already small) |
| [quay](./quay.md) | - | 11 | Container registry |
| [alertmanager](./alertmanager.md) | - | 9 | Alert/silence management |
| [google_calendar](./google_calendar.md) | - | 6 | Calendar & meetings |
| [gmail](./gmail.md) | - | 6 | Email processing |
| [slack](./slack.md) | - | 16 | Slack integration |
| [appinterface](./appinterface.md) | - | 7 | GitOps config |
| [lint](./common.md) | - | 7 | Python/YAML linting |
| [dev_workflow](./common.md) | - | 9 | Development helpers |

**Total:** ~270 tools across 17 modules (split into ~30 loadable units)

> Plus **45+ shared parsers** in `scripts/common/parsers.py` for reusable output parsing
> And **config helpers** in `scripts/common/config_loader.py` for commit format, repo resolution

## Architecture

```mermaid
graph TB
    subgraph MCP["MCP Server (server)"]
        LOADER[AgentLoader]
        CORE[Core Tools]
    end

    subgraph MODULES["Tool Modules"]
        GIT[aa_git]
        GITLAB[aa_gitlab]
        JIRA[aa_jira]
        K8S[aa_k8s]
        MORE[...]
    end

    LOADER --> |loads| GIT
    LOADER --> |loads| GITLAB
    LOADER --> |loads| JIRA
    LOADER --> |loads| K8S
    LOADER --> |loads| MORE

    style MCP fill:#6366f1,stroke:#4f46e5,color:#fff
    style MODULES fill:#10b981,stroke:#059669,color:#fff
```

## Module Categories

### 💻 Development

| Module | Purpose |
|--------|---------|
| [git](./git.md) | Git repository operations |
| [gitlab](./gitlab.md) | GitLab MRs, pipelines, comments |
| [jira](./jira.md) | Jira issue management |

### ☸️ Infrastructure

| Module | Purpose |
|--------|---------|
| [k8s](./k8s.md) | Kubernetes pods, deployments, logs |
| [bonfire](./bonfire.md) | Ephemeral namespace management |
| [quay](./quay.md) | Container image verification |

### 📊 Monitoring

| Module | Purpose |
|--------|---------|
| [prometheus](./prometheus.md) | Metrics and alert queries |
| [alertmanager](./alertmanager.md) | Alert and silence management |
| [kibana](./kibana.md) | Log search and analysis |

### 💬 Communication

| Module | Purpose |
|--------|---------|
| [slack](./slack.md) | Slack message handling |
| [google_calendar](./google_calendar.md) | Calendar and meetings |
| [gmail](./gmail.md) | Email processing and summarization |

### 📦 Release

| Module | Purpose |
|--------|---------|
| [konflux](./konflux.md) | Build pipelines |
| [appinterface](./appinterface.md) | GitOps configuration |

### 🔧 Core/Workflow

| Module | Purpose |
|--------|---------|
| [workflow](./workflow.md) | Agents, skills, memory, infrastructure tools |

## Infrastructure Tools

The workflow module includes essential infrastructure tools for auto-healing:

| Tool | Purpose |
|------|---------|
| `vpn_connect()` | Connect to Red Hat VPN for internal resources |
| `kube_login(cluster)` | Refresh Kubernetes authentication |
| `session_start(agent)` | Initialize session with context |
| `debug_tool(tool, error)` | Analyze failing tool source code |

These are used by skill auto-healing to recover from common failures.

## Module Loading

Modules are loaded dynamically when you switch agents:

```
You: Load devops agent

Claude: [AgentLoader]
        → Unloading: git_basic, gitlab_basic, jira_basic
        → Loading: k8s_basic, bonfire_basic, jira_basic, quay
        → Notifying Cursor of tool change

        🔧 DevOps agent ready with ~83 tools
```

### Accessing Extra Tools

When you need an advanced tool not in your persona's basic set:

```python
# Git rebase (in git_extra)
tool_exec("git_rebase", '{"repo": "backend", "onto": "origin/main"}')

# Jira sprint operations (in jira_extra)
tool_exec("jira_add_to_sprint", '{"issue_key": "AAP-12345"}')

# Bonfire full deploy (in bonfire_extra)
tool_exec("bonfire_deploy_aa", '{"namespace": "ephemeral-xxx"}')
```

## Environment Variables

| Variable | Module | Description |
|----------|--------|-------------|
| `JIRA_URL` | jira | Jira instance URL |
| `JIRA_JPAT` | jira | Jira Personal Access Token |
| `GITLAB_TOKEN` | gitlab | GitLab API token |
| `KUBECONFIG` | k8s | Default kubeconfig path |

> **Note:** Quay uses `skopeo` which leverages your existing `docker login` credentials - no separate token needed!

## Adding a New Module

1. Create directory: `tool_modules/aa_{name}/src/`

2. Create `tools.py`:
```python
from mcp.server.fastmcp import FastMCP

def register_tools(server: FastMCP) -> int:
    @server.tool()
    async def my_tool(arg: str) -> str:
        """Tool description."""
        return f"Result: {arg}"

    return 1  # tool count
```

3. Add to `server/persona_loader.py`:
```python
TOOL_MODULES = {
    "{name}": 5,  # estimated tool count
}
```

4. Add to persona config:
```yaml
tools:
  - {name}
```

5. Add to `tool_modules/aa_workflow/src/meta_tools.py`:
```python
TOOL_REGISTRY = {
    # ...
    "{name}": ["my_tool", ...],
}

MODULE_PREFIXES = {
    # ...
    "my_": "{name}",
}
```

## See Also

- [Architecture Overview](../architecture/README.md)
- [Personas](../personas/README.md)
- [MCP Implementation Details](../architecture/mcp-implementation.md)
- [Skills Reference](../skills/README.md) - Skills that use these tools
