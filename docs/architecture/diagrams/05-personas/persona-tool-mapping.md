# Persona Tool Mapping

> Which tools are loaded by each persona

## Diagram

```mermaid
graph TB
    subgraph Personas[Personas]
        DEV[developer]
        DEVOPS[devops]
        INCIDENT[incident]
        RELEASE[release]
    end

    subgraph ToolModules[Tool Modules]
        GIT[aa_git]
        GITLAB[aa_gitlab]
        JIRA[aa_jira]
        K8S[aa_k8s]
        BONFIRE[aa_bonfire]
        PROMETHEUS[aa_prometheus]
        KIBANA[aa_kibana]
        KONFLUX[aa_konflux]
        QUAY[aa_quay]
        SLACK[aa_slack]
        CODE_SEARCH[aa_code_search]
    end

    DEV --> GIT
    DEV --> GITLAB
    DEV --> JIRA
    DEV --> CODE_SEARCH

    DEVOPS --> K8S
    DEVOPS --> BONFIRE
    DEVOPS --> JIRA
    DEVOPS --> QUAY

    INCIDENT --> K8S
    INCIDENT --> PROMETHEUS
    INCIDENT --> KIBANA
    INCIDENT --> SLACK
    INCIDENT --> JIRA

    RELEASE --> KONFLUX
    RELEASE --> QUAY
    RELEASE --> JIRA
    RELEASE --> GIT
```

## Tool Matrix

| Module | developer | devops | incident | release |
|--------|-----------|--------|----------|---------|
| aa_workflow | ✓ | ✓ | ✓ | ✓ |
| aa_memory | ✓ | ✓ | ✓ | ✓ |
| aa_ollama | ✓ | ✓ | ✓ | ✓ |
| aa_jira_basic | ✓ | ✓ | ✓ | ✓ |
| aa_jira_core | ✓ | | | |
| aa_git_basic | ✓ | | | ✓ |
| aa_git_core | ✓ | | | |
| aa_gitlab_basic | ✓ | | | |
| aa_gitlab_core | ✓ | | | |
| aa_k8s_basic | | ✓ | ✓ | |
| aa_k8s_core | | ✓ | ✓ | |
| aa_bonfire_basic | | ✓ | | |
| aa_bonfire_core | | ✓ | | |
| aa_prometheus_basic | | | ✓ | |
| aa_kibana_basic | | | ✓ | |
| aa_alertmanager_basic | | | ✓ | |
| aa_konflux_basic | | | | ✓ |
| aa_konflux_core | | | | ✓ |
| aa_quay_basic | | ✓ | | ✓ |
| aa_slack_basic | | | ✓ | |
| aa_code_search_basic | ✓ | | | |

## Tool Tiers per Persona

```mermaid
flowchart TB
    subgraph Developer[developer Persona]
        D_BASIC[Basic Tools<br/>Read-only operations]
        D_CORE[Core Tools<br/>Write operations]
        D_EXTRA[Extra Tools<br/>Advanced features]
    end

    subgraph DevOps[devops Persona]
        DO_BASIC[Basic Tools<br/>Read-only operations]
        DO_CORE[Core Tools<br/>Write operations]
    end

    subgraph Incident[incident Persona]
        I_BASIC[Basic Tools<br/>Read-only operations]
    end

    D_BASIC --> D_CORE
    D_CORE --> D_EXTRA
    DO_BASIC --> DO_CORE
```

## Module Loading

```mermaid
sequenceDiagram
    participant Loader as PersonaLoader
    participant Config as Persona Config
    participant Module as Tool Module
    participant MCP as FastMCP

    Loader->>Config: Get tools list
    Config-->>Loader: [aa_git_basic, aa_gitlab_core, ...]

    loop For each module
        Loader->>Module: Import module
        Module->>Module: Get tool functions
        Module->>MCP: Register tools
    end

    Loader->>MCP: Notify tools changed
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| PersonaLoader | `server/persona_loader.py` | Tool loading |
| Persona configs | `personas/*.yaml` | Tool lists |

## Related Diagrams

- [Persona Architecture](./persona-architecture.md)
- [Tool Tiers](../03-tools/tool-tiers.md)
- [Persona Use Cases](./persona-use-cases.md)
