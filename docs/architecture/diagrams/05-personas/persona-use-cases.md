# Persona Use Cases

> When and how to use each persona

## Diagram

```mermaid
flowchart TB
    subgraph UserIntent[User Intent]
        CODE[Write code, review MR]
        DEPLOY[Deploy to ephemeral]
        DEBUG[Debug production issue]
        RELEASE[Release to production]
        RESEARCH[Find documentation]
        ADMIN[System management]
    end

    subgraph Persona[Recommended Persona]
        DEV[developer]
        DEVOPS[devops]
        INCIDENT[incident]
        REL[release]
        RES[researcher]
        ADM[admin]
    end

    subgraph Tools[Key Tools Available]
        DEV_TOOLS[git, gitlab, jira, lint]
        DEVOPS_TOOLS[k8s, bonfire, quay]
        INCIDENT_TOOLS[prometheus, kibana, alertmanager]
        REL_TOOLS[konflux, quay, appinterface]
        RES_TOOLS[inscope, code_search]
        ADM_TOOLS[all tools]
    end

    CODE --> DEV
    DEPLOY --> DEVOPS
    DEBUG --> INCIDENT
    RELEASE --> REL
    RESEARCH --> RES
    ADMIN --> ADM

    DEV --> DEV_TOOLS
    DEVOPS --> DEVOPS_TOOLS
    INCIDENT --> INCIDENT_TOOLS
    REL --> REL_TOOLS
    RES --> RES_TOOLS
    ADM --> ADM_TOOLS
```

## Intent Detection

```mermaid
flowchart TB
    subgraph Keywords[Intent Keywords]
        K_DEV["code, MR, review, commit, branch"]
        K_DEVOPS["deploy, ephemeral, namespace, k8s"]
        K_INCIDENT["alert, incident, outage, logs"]
        K_RELEASE["release, prod, konflux, promote"]
    end

    subgraph Detection[Intent Classification]
        CLASSIFY[Classify intent]
        CONFIDENCE[Calculate confidence]
        THRESHOLD{Confidence > 80%?}
    end

    subgraph Action[Action]
        AUTO[Auto-load persona]
        SUGGEST[Suggest persona]
    end

    K_DEV --> CLASSIFY
    K_DEVOPS --> CLASSIFY
    K_INCIDENT --> CLASSIFY
    K_RELEASE --> CLASSIFY

    CLASSIFY --> CONFIDENCE
    CONFIDENCE --> THRESHOLD
    THRESHOLD -->|Yes| AUTO
    THRESHOLD -->|No| SUGGEST
```

## Use Case Examples

### Development Workflow

```mermaid
sequenceDiagram
    participant User as User
    participant Session as Session
    participant Loader as PersonaLoader

    User->>Session: "Start work on AAP-12345"
    Session->>Session: Detect intent: development
    Session->>Loader: Auto-load developer
    Loader-->>Session: developer loaded

    Note over User,Loader: Available: git, gitlab, jira, lint, code_search
```

### Deployment Workflow

```mermaid
sequenceDiagram
    participant User as User
    participant Session as Session
    participant Loader as PersonaLoader

    User->>Session: "Deploy MR 1234 to ephemeral"
    Session->>Session: Detect intent: deployment
    Session->>Loader: Auto-load devops
    Loader-->>Session: devops loaded

    Note over User,Loader: Available: k8s, bonfire, quay, jira
```

### Incident Response

```mermaid
sequenceDiagram
    participant User as User
    participant Session as Session
    participant Loader as PersonaLoader

    User->>Session: "What's firing in production?"
    Session->>Session: Detect intent: incident
    Session->>Loader: Auto-load incident
    Loader-->>Session: incident loaded

    Note over User,Loader: Available: prometheus, kibana, alertmanager, k8s
```

## Persona Selection Guide

| Scenario | Persona | Why |
|----------|---------|-----|
| Fix a bug | developer | Need git, gitlab, jira |
| Test MR in ephemeral | devops | Need bonfire, k8s |
| Alert investigation | incident | Need prometheus, kibana |
| Ship to production | release | Need konflux, quay |
| Find documentation | researcher | Need inscope, code_search |
| System configuration | admin | Need all tools |

## Switching Personas

```mermaid
flowchart TB
    subgraph Before[Current: developer]
        B_TOOLS[git, gitlab, jira, lint]
    end

    subgraph Switch[Switch to devops]
        UNLOAD[Unload: gitlab, lint]
        KEEP[Keep: jira]
        LOAD[Load: k8s, bonfire, quay]
    end

    subgraph After[Current: devops]
        A_TOOLS[k8s, bonfire, quay, jira]
    end

    Before --> Switch
    Switch --> After
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| Intent classifier | `session_builder.py` | Detect intent |
| PersonaLoader | `persona_loader.py` | Load persona |
| Bootstrap | `tools_core.py` | Auto-load logic |

## Related Diagrams

- [Persona Architecture](./persona-architecture.md)
- [Session Bootstrap](../08-data-flows/session-bootstrap.md)
- [Skill Dependencies](../04-skills/skill-dependencies.md)
