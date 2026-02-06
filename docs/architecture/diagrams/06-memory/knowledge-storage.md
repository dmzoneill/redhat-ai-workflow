# Knowledge Storage

> Domain knowledge and documentation storage

## Diagram

```mermaid
graph TB
    subgraph KnowledgeRoot[knowledge/]
        PERSONAS[personas/<br/>Per-persona knowledge]
        PROJECTS[projects/<br/>Project documentation]
    end

    subgraph PersonaKnowledge[personas/]
        DEV_K[developer/<br/>Dev tips, patterns]
        DEVOPS_K[devops/<br/>Deployment guides]
        INCIDENT_K[incident/<br/>Runbooks]
    end

    subgraph ProjectKnowledge[projects/]
        AAB[automation-analytics-backend/]
        PDF[pdf-generator/]
        WORKFLOW[redhat-ai-workflow/]
    end

    KnowledgeRoot --> PersonaKnowledge
    KnowledgeRoot --> ProjectKnowledge
```

## Knowledge Structure

```yaml
# knowledge/personas/developer/tips.yaml
tips:
  - context: git_commit
    tip: "Use conventional commit format: {issue_key} - {type}({scope}): {description}"
    priority: high

  - context: mr_create
    tip: "Always link Jira issue in MR description"
    priority: high

  - context: code_review
    tip: "Check for test coverage before approving"
    priority: medium

# knowledge/personas/devops/runbooks.yaml
runbooks:
  - name: ephemeral_deploy
    steps:
      - "Reserve namespace with bonfire"
      - "Build image from MR"
      - "Deploy with IMAGE_TAG"
    common_issues:
      - error: "manifest unknown"
        fix: "Use full 40-char SHA"

# knowledge/projects/automation-analytics-backend/architecture.yaml
architecture:
  components:
    - name: API
      path: src/api/
      description: REST API endpoints
    - name: Workers
      path: src/workers/
      description: Background job processors
  databases:
    - name: PostgreSQL
      purpose: Primary data store
    - name: Redis
      purpose: Caching and queues
```

## Knowledge Access

```mermaid
sequenceDiagram
    participant User as User/Claude
    participant Tool as memory_ask
    participant Router as Source Router
    participant YAML as YAML Adapter
    participant Knowledge as knowledge/

    User->>Tool: "How do I deploy to ephemeral?"
    Tool->>Router: Route query
    Router->>YAML: Query knowledge

    YAML->>Knowledge: Search personas/devops/
    Knowledge-->>YAML: runbooks.yaml

    YAML-->>Router: Deployment runbook
    Router-->>Tool: Formatted response
    Tool-->>User: "## Ephemeral Deployment\n1. Reserve namespace..."
```

## Knowledge Categories

| Category | Path | Content |
|----------|------|---------|
| Persona tips | `personas/{name}/tips.yaml` | Context-specific guidance |
| Runbooks | `personas/{name}/runbooks.yaml` | Step-by-step procedures |
| Project docs | `projects/{name}/architecture.yaml` | Architecture details |
| API docs | `projects/{name}/api.yaml` | API documentation |
| Troubleshooting | `personas/{name}/troubleshooting.yaml` | Common issues & fixes |

## Knowledge Flow

```mermaid
flowchart TB
    subgraph Sources[Knowledge Sources]
        MANUAL[Manual documentation]
        LEARNED[Learned from usage]
        EXTERNAL[External docs]
    end

    subgraph Storage[Knowledge Storage]
        YAML_FILES[YAML files]
    end

    subgraph Usage[Knowledge Usage]
        SESSION[Session context]
        SKILLS[Skill execution]
        QUERIES[User queries]
    end

    MANUAL --> YAML_FILES
    LEARNED --> YAML_FILES
    EXTERNAL --> YAML_FILES

    YAML_FILES --> SESSION
    YAML_FILES --> SKILLS
    YAML_FILES --> QUERIES
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| Knowledge files | `memory/knowledge/` | YAML storage |
| memory_ask | `memory_unified.py` | Query interface |
| SessionBuilder | `session_builder.py` | Context injection |

## Related Diagrams

- [Memory Architecture](./memory-architecture.md)
- [Memory Paths](./memory-paths.md)
- [Session Builder](../01-server/session-builder.md)
