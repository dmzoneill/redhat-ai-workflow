# 🔧 Tool Modules Reference

Tool modules are MCP plugins that provide specific capabilities. Each module contains related tools that are loaded based on which persona is active.

> **Terminology:** "Personas" (sometimes called "agents") are tool configuration profiles that determine which modules are loaded. This is NOT a multi-agent AI system.

## Quick Reference

**263 tools** across **16 modules**, split into **188 basic** (used in skills, 71%) and **75 extra** (rarely used, 29%).

> **Performance:** Loading basic tools only reduces context window usage by **30%**. See [Tool Organization](../tool-organization.md) for details.

| Module | Variant | Tools | Usage % | Description |
|--------|---------|-------|---------|-------------|
| [workflow](./workflow.md) | basic | 18 | 100% | Core: agents, skills, memory, vpn_connect, kube_login |
| [git](./git.md) | basic | 27 | 90% | Essential git (status, log, diff, add, commit, push, rebase, merge) |
| [git](./git.md) | extra | 3 | - | Rarely used (clean, remote_info, docker_compose_down) |
| [gitlab](./gitlab.md) | basic | 16 | 53% | MRs, CI basics (list, view, create, comment, lint) |
| [gitlab](./gitlab.md) | extra | 14 | - | Advanced (approve, merge, rebase, issues, releases) |
| [jira](./jira.md) | basic | 17 | 61% | Essential (view, search, status, comments, create, clone) |
| [jira](./jira.md) | extra | 11 | - | Advanced (sprint, links, flags, lint, ai_helper) |
| [k8s](./k8s.md) | basic | 22 | 79% | Essential k8s (pods, logs, deployments, exec, cp, scale) |
| [k8s](./k8s.md) | extra | 6 | - | Advanced k8s (list helpers, delete, saas logs) |
| [bonfire](./bonfire.md) | basic | 10 | 50% | Used in deploy workflows (reserve, list, release, deploy) |
| [bonfire](./bonfire.md) | extra | 10 | - | Specialized deploys (process, local, snapshot, test workflow) |
| [konflux](./konflux.md) | basic | 22 | 63% | Pipelines, components, snapshots, builds, releases |
| [konflux](./konflux.md) | extra | 13 | - | Releases plans, environments, low-level tkn tools |
| [prometheus](./prometheus.md) | basic | 5 | 38% | Queries, alerts, rules, pod health |
| [prometheus](./prometheus.md) | extra | 8 | - | Range queries, namespace metrics, targets, labels |
| [kibana](./kibana.md) | basic | 1 | 11% | Log search (kibana_search_logs) |
| [kibana](./kibana.md) | extra | 8 | - | URL gen, index patterns, dashboards, trace (interactive) |
| [quay](./quay.md) | basic | 5 | 71% | Image ops (check exists, get tag, manifest, vulnerabilities) |
| [quay](./quay.md) | extra | 2 | - | Repository management (get_repository, list_tags) |
| [alertmanager](./alertmanager.md) | basic | 4 | 57% | Alerts, silences, create/delete |
| [alertmanager](./alertmanager.md) | extra | 3 | - | Receivers, status |
| [google_calendar](./google_calendar.md) | basic | 6 | 100% | Calendar & meetings (all used in skills) |
| [slack](./slack.md) | basic | 6 | 67% | Messaging, channels, user lookup |
| [slack](./slack.md) | extra | 3 | - | Reactions, get_channels, list_messages |
| [appinterface](./appinterface.md) | basic | 4 | 57% | Core validation (diff, get_saas, resources, validate) |
| [appinterface](./appinterface.md) | extra | 3 | - | Clusters, user, search |
| [lint](./lint.md) | basic | 1 | 14% | lint_python (used in pre-MR checks) |
| [lint](./lint.md) | extra | 6 | - | dockerfile, yaml, precommit, security, test coverage |
| [dev_workflow](./dev_workflow.md) | basic | 9 | 100% | Workflow helpers (start_work, prepare_mr, etc.) |

**Total:** 263 tools (**188 basic**, **75 extra**) across 16 modules

> **Data-Driven Split:** Based on analysis of 55 skills. See `.claude/skill-tool-usage-report.md` for full details.

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
```text

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

        🔧 DevOps agent ready with ~74 tools
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
