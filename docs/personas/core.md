# Core Persona

Essential shared tools that support all agent personas.

## Overview

| Metric | Value |
|--------|-------|
| **Approximate Tools** | ~76 |
| **Purpose** | Minimal shared toolset |
| **Use Case** | Basic operations across all workflows |

## Tool Modules

| Module | Tools | Description |
|--------|-------|-------------|
| workflow | 18 | Core: memory, persona, session, skill, infra, meta |
| git_basic | 27 | Essential git operations |
| jira_basic | 17 | Issue viewing, search, status updates |
| k8s_basic | 22 | Essential k8s (pods, logs, deployments) |

## Capabilities

### Included

- Git operations (status, branch, commit, push)
- Jira operations (view, create, update issues)
- Kubernetes operations (pods, deployments, logs)
- Skills execution
- Persona switching
- Memory persistence
- Infrastructure (vpn_connect, kube_login)

### Not Included

Load a specialized persona for these:

| Need | Persona |
|------|---------|
| GitLab (MRs, pipelines) | developer |
| Konflux (builds, snapshots) | release |
| Kibana (logs) | incident |
| Bonfire (ephemeral) | devops |
| Alertmanager (silences) | incident |
| Quay (images) | release |

## Available Skills

- `start_work` - Start working on a Jira issue
- `investigate_alert` - Investigate Prometheus alerts
- `debug_prod` - Debug production issues
- `standup_summary` - Generate standup summary
- `create_jira_issue` - Create Jira issue
- `close_issue` - Close Jira issue
- `memory_view` - View memory contents
- `memory_edit` - Edit memory
- `learn_pattern` - Save learned pattern

## Usage

```python
persona_load("core")
```

## When to Use

- You need minimal tool loading for faster startup
- You're doing basic cross-functional work
- You want to switch personas dynamically later
