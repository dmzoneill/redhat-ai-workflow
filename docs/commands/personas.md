# /personas

> Switch to a specialized persona with relevant tools.

## Overview

Switch to a specialized persona with relevant tools.

## Arguments

No arguments required.

## Usage

### Examples

```bash
persona_load("developer")
```

```bash
# Starting development work
persona_load("developer")

# Deploying to ephemeral
persona_load("devops")

# Investigating an alert
persona_load("incident")

# Releasing to production
persona_load("release")
```

```bash
session_start(agent="devops")
```

## Process Flow

```mermaid
flowchart TD
    START([Start]) --> PROCESS[Process Command]
    PROCESS --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
```text

## Details

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

## Additional Examples

```bash
# Starting development work
persona_load("developer")

# Deploying to ephemeral
persona_load("devops")

# Investigating an alert
persona_load("incident")

# Releasing to production
persona_load("release")
```bash

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

```text
session_start(agent="devops")
```

## Tools Not in Personas (use skills instead)

Some capabilities are available **only via skills**, not by loading a persona:

- **Google Drive:** No persona includes `aa_gdrive`. Use the **`gdrive_fetch_doc`** skill to fetch a Google Doc by `file_id`. The skill engine runs GDrive tools inside skill steps.

## See Also

- `/tools` - See what tools are available
- `/list-skills` - See available skills


## Related Commands

*(To be determined based on command relationships)*
