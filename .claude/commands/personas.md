---
name: personas
description: "Switch to a specialized persona with relevant tools."
---
# 🎭 Load Persona

Switch to a specialized persona with relevant tools.

## Instructions

```text
persona_load("developer")
```

## Available Personas

| Persona | Focus | Tools Loaded |
|---------|-------|--------------|
| `developer` | Coding, PRs, reviews | workflow, git_basic, gitlab_basic, jira_basic (~78 tools) |
| `devops` | Deployments, k8s, ephemeral | workflow, k8s_basic, bonfire_basic, jira_basic, quay (~74 tools) |
| `incident` | Production issues, logs | workflow, k8s_basic, prometheus_basic, kibana, jira_basic, alertmanager (~78 tools) |
| `release` | Shipping to production | workflow, konflux_basic, quay, jira_basic, git_basic (~91 tools) |

## Examples

```bash
# Starting development work
persona_load("developer")

# Deploying to ephemeral
persona_load("devops")

# Investigating an alert
persona_load("incident")

# Releasing to production
persona_load("release")
```text

## What Happens

When you load a persona:

1. Current tools are unloaded (except core)
2. Persona's tool modules are loaded
3. Cursor receives notification of tool change
4. Persona's expertise context is activated

## Personas

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

You can also load a persona when starting a session:

```
session_start(agent="devops")
```

## See Also

- `/tools` - See what tools are available
- `/list-skills` - See available skills
