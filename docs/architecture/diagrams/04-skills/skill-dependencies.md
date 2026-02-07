# Skill Dependencies

> Inter-skill relationships, validation links, and tool dependencies

## Link Types

Every skill has an optional `links:` metadata block with five relationship types:

| Link Type | Meaning | Example |
|-----------|---------|---------|
| `depends_on` | Must run before this skill | `create_mr` depends on `start_work` |
| `validates` | Running this skill validates the linked skill worked | `review_pr` validates `create_mr` |
| `validated_by` | These skills validate this one | `create_mr` is validated by `review_pr` |
| `chains_to` | Natural next steps after this skill | `start_work` chains to `create_mr` |
| `provides_context_for` | Output feeds into these skills | `start_work` provides context for `create_mr` |

## Development Lifecycle

```mermaid
graph LR
    subgraph CoreSkills[Core Lifecycle]
        START[start_work]
        CREATE_MR[create_mr]
        CLOSE[close_issue]
    end

    subgraph QualityGates[Quality Gates]
        HYGIENE[jira_hygiene]
        REVIEW[review_pr]
        LOCAL_REVIEW[review_local_changes]
        CI[check_ci_health]
    end

    subgraph DeploySkills[Deployment]
        TEST_MR[test_mr_ephemeral]
        RELEASE[release_to_prod]
    end

    START -->|chains_to| CREATE_MR
    CREATE_MR -->|chains_to| TEST_MR
    TEST_MR -->|chains_to| CLOSE
    CREATE_MR -->|chains_to| RELEASE
    RELEASE -->|chains_to| CLOSE

    HYGIENE -.->|validates| START
    REVIEW -.->|validates| CREATE_MR
    LOCAL_REVIEW -.->|validates| START
    CI -.->|validates| CREATE_MR
    TEST_MR -.->|validates| CREATE_MR

    START -->|depends_on| HYGIENE
    CREATE_MR -->|depends_on| START
    CLOSE -->|depends_on| CREATE_MR
```

## Validation Web

Skills validate each other in a web of trust. If a downstream skill succeeds, it
validates that upstream skills produced correct output:

```mermaid
graph TB
    subgraph Validators[Validation Sources]
        REVIEW[review_pr]
        REVIEW_MULTI[review_pr_multiagent]
        CI[check_ci_health]
        TEST_MR[test_mr_ephemeral]
        ENV[environment_overview]
    end

    subgraph Validated[Validated Skills]
        CREATE_MR[create_mr]
        START_WORK[start_work]
        REBASE[rebase_pr]
        CVE[cve_fix]
        HOTFIX[hotfix]
        DEPLOY[deploy_to_ephemeral]
        RELEASE[release_to_prod]
    end

    REVIEW -->|validates| CREATE_MR
    REVIEW -->|validates| START_WORK
    REVIEW_MULTI -->|validates| CREATE_MR
    CI -->|validates| CREATE_MR
    CI -->|validates| REBASE
    CI -->|validates| CVE
    CI -->|validates| HOTFIX
    TEST_MR -->|validates| CREATE_MR
    TEST_MR -->|validates| START_WORK
    ENV -->|validates| DEPLOY
    ENV -->|validates| RELEASE
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
| Quality | review_local_changes → create_mr → review_pr | Pre-commit to review |
| Incident | investigate_alert → debug_prod → hotfix → release_to_prod | Alert to fix |
| Research | gather_context → research_topic → plan_implementation → start_work | Research to code |
| Daily | coffee → (work) → beer | Daily workflow |
| Knowledge | bootstrap_knowledge → knowledge_refresh → gather_context | Knowledge lifecycle |
| CVE | cve_fix → review_pr → test_mr_ephemeral → release_to_prod | Security fix pipeline |

## Cross-Validation Rules

The `validate_skills.py` script enforces these consistency rules:

1. **Bidirectional validates/validated_by**: If A validates B, B should list A in validated_by
2. **Bidirectional depends_on/chains_to**: If A depends_on B, B should list A in chains_to
3. **No self-references**: Skills cannot link to themselves
4. **Reference validity**: All linked skill names must exist as real skills

Run validation:
```bash
python scripts/validate_skills.py --verbose
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| skill_info | `tools_basic.py` | Get skill dependencies |
| SkillEngine | `skill_engine.py` | Dependency checking |
| validate_skills | `scripts/validate_skills.py` | Link validation |
| generate_skill_graph | `scripts/generate_skill_graph.py` | Graph with link types |

## Related Diagrams

- [Skill Categories](./skill-categories.md)
- [Persona Tool Mapping](../05-personas/persona-tool-mapping.md)
- [Common Skills](./common-skills.md)
