# Skill Dependencies

> Inter-skill relationships and tool dependencies

## Diagram

```mermaid
graph LR
    subgraph CoreSkills[Core Skills]
        START[start_work]
        CREATE_MR[create_mr]
        CLOSE[close_issue]
    end

    subgraph DeploySkills[Deployment Skills]
        TEST_MR[test_mr_ephemeral]
        RELEASE[release_to_prod]
    end

    subgraph AutoSkills[Automation Skills]
        COFFEE[coffee]
        BEER[beer]
    end

    START --> CREATE_MR
    CREATE_MR --> TEST_MR
    TEST_MR --> CLOSE
    CREATE_MR --> RELEASE
    RELEASE --> CLOSE

    COFFEE --> START
    BEER --> CLOSE
```

## Tool Dependencies

```mermaid
graph TB
    subgraph Skills[Skills]
        START_WORK[start_work]
        CREATE_MR[create_mr]
        TEST_MR[test_mr_ephemeral]
    end

    subgraph Tools[Required Tools]
        JIRA[jira_*]
        GIT[git_*]
        GITLAB[gitlab_*]
        BONFIRE[bonfire_*]
        K8S[k8s_*]
        QUAY[quay_*]
    end

    START_WORK --> JIRA
    START_WORK --> GIT

    CREATE_MR --> GIT
    CREATE_MR --> GITLAB
    CREATE_MR --> JIRA

    TEST_MR --> GITLAB
    TEST_MR --> BONFIRE
    TEST_MR --> K8S
    TEST_MR --> QUAY
```

## Dependency Matrix

| Skill | jira | git | gitlab | bonfire | k8s | quay | slack |
|-------|------|-----|--------|---------|-----|------|-------|
| start_work | X | X | | | | | |
| create_mr | X | X | X | | | | |
| test_mr_ephemeral | | | X | X | X | X | |
| release_to_prod | | | | | | X | |
| coffee | X | | | | | | X |
| beer | X | X | | | | | X |
| investigate_alert | | | | | X | | X |

## Persona Requirements

```mermaid
flowchart TB
    subgraph Skill[Skill Execution]
        SKILL_RUN[skill_run]
        CHECK[Check required tools]
    end

    subgraph Persona[Persona Check]
        LOADED[Currently loaded tools]
        REQUIRED[Required tools]
        MISSING{Missing tools?}
    end

    subgraph Action[Action]
        PROCEED[Execute skill]
        SUGGEST[Suggest persona]
        LOAD[Load persona]
    end

    SKILL_RUN --> CHECK
    CHECK --> LOADED
    CHECK --> REQUIRED
    LOADED --> MISSING
    REQUIRED --> MISSING

    MISSING -->|No| PROCEED
    MISSING -->|Yes| SUGGEST
    SUGGEST --> LOAD
    LOAD --> PROCEED
```

## Skill Chains

| Chain | Skills | Use Case |
|-------|--------|----------|
| Development | start_work → create_mr → close_issue | Full issue lifecycle |
| Deploy | create_mr → test_mr_ephemeral → release_to_prod | MR to production |
| Daily | coffee → (work) → beer | Daily workflow |

## Components

| Component | File | Description |
|-----------|------|-------------|
| skill_info | `tools_basic.py` | Get skill dependencies |
| SkillEngine | `skill_engine.py` | Dependency checking |

## Related Diagrams

- [Skill Categories](./skill-categories.md)
- [Persona Tool Mapping](../05-personas/persona-tool-mapping.md)
- [Common Skills](./common-skills.md)
