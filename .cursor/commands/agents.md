# 🤖 Load Agent

Switch to a specialized agent with relevant tools.

## Instructions

```
agent_load("developer")
```

## Available Agents

| Agent | Focus | Tools Loaded |
|-------|-------|--------------|
| `developer` | Coding, PRs, reviews | git, gitlab, jira (~74 tools) |
| `devops` | Deployments, k8s, ephemeral | k8s, bonfire, quay, gitlab (~90 tools) |
| `incident` | Production issues, logs | k8s, kibana, prometheus, jira (~78 tools) |
| `release` | Shipping to production | konflux, quay, appinterface, git (~69 tools) |

## Examples

```bash
# Starting development work
agent_load("developer")

# Deploying to ephemeral
agent_load("devops")

# Investigating an alert
agent_load("incident")

# Releasing to production
agent_load("release")
```

## What Happens

When you load an agent:

1. Current tools are unloaded (except core)
2. Agent's tool modules are loaded
3. Cursor receives notification of tool change
4. Agent's persona/expertise is activated

## Agent Personas

### 👨‍💻 Developer
Expert in code review, git workflows, Jira management.
Focuses on code quality and PR best practices.

### 🔧 DevOps
Expert in Kubernetes, ephemeral environments, deployments.
Knows bonfire, cluster management, image tags.

### 🚨 Incident
Expert in production investigation, log analysis, metrics.
Focuses on quick triage and root cause analysis.

### 📦 Release
Expert in Konflux builds, Quay images, app-interface.
Guides stage → prod promotions.

## Session Start

You can also load an agent when starting a session:

```
session_start(agent="devops")
```

## See Also

- `/tools` - See what tools are available
- `/list-skills` - See available skills
