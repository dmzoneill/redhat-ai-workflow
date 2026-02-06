# Konflux Tools

> aa_konflux module for Konflux release pipeline management

## Diagram

```mermaid
classDiagram
    class KonfluxBasic {
        +konflux_list_applications(): list
        +konflux_get_application(name): dict
        +konflux_list_components(app): list
        +konflux_get_component(app, name): dict
        +konflux_list_releases(app): list
        +konflux_get_release(name): dict
    }

    class KonfluxCore {
        +konflux_create_release(app, snapshot): dict
        +konflux_promote_release(release, env): dict
        +konflux_get_snapshot(name): dict
        +konflux_list_snapshots(app): list
    }

    class KonfluxExtra {
        +konflux_get_pipeline_run(name): dict
        +konflux_list_pipeline_runs(app): list
        +konflux_get_release_plan(name): dict
        +konflux_trigger_build(component): dict
    }

    KonfluxBasic <|-- KonfluxCore
    KonfluxCore <|-- KonfluxExtra
```

## Release Pipeline

```mermaid
flowchart TB
    subgraph Build[Build Phase]
        COMMIT[Git Commit]
        PIPELINE[PipelineRun]
        IMAGE[Container Image]
        SNAPSHOT[Snapshot]
    end

    subgraph Release[Release Phase]
        RELEASE[Release CR]
        PLAN[ReleasePlan]
        STRATEGY[ReleaseStrategy]
    end

    subgraph Promote[Promotion]
        STAGE[Stage Environment]
        PROD[Production Environment]
    end

    COMMIT --> PIPELINE
    PIPELINE --> IMAGE
    IMAGE --> SNAPSHOT

    SNAPSHOT --> RELEASE
    PLAN --> RELEASE
    STRATEGY --> RELEASE

    RELEASE --> STAGE
    STAGE --> PROD
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| tools_basic.py | `tool_modules/aa_konflux/src/` | Read operations |
| tools_core.py | `tool_modules/aa_konflux/src/` | Write operations |
| tools_extra.py | `tool_modules/aa_konflux/src/` | Advanced operations |
| server.py | `tool_modules/aa_konflux/src/` | Standalone server |

## Tool Summary

| Tool | Tier | Description |
|------|------|-------------|
| `konflux_list_applications` | basic | List applications |
| `konflux_get_application` | basic | Get application details |
| `konflux_list_components` | basic | List components |
| `konflux_list_releases` | basic | List releases |
| `konflux_create_release` | core | Create release |
| `konflux_promote_release` | core | Promote to environment |
| `konflux_get_pipeline_run` | extra | Get pipeline run |
| `konflux_trigger_build` | extra | Trigger component build |

## Konflux Resources

```mermaid
graph TB
    subgraph Application[Application]
        APP[Application CR]
        COMP[Components]
        SNAP[Snapshots]
    end

    subgraph Release[Release Resources]
        REL[Release CR]
        PLAN[ReleasePlan]
        STRAT[ReleaseStrategy]
        PLAN_ADM[ReleasePlanAdmission]
    end

    subgraph Pipeline[Pipeline Resources]
        PR[PipelineRun]
        TR[TaskRun]
    end

    APP --> COMP
    COMP --> SNAP
    SNAP --> REL
    PLAN --> REL
    STRAT --> REL
    PLAN_ADM --> REL
    COMP --> PR
    PR --> TR
```

## Configuration

```json
{
  "konflux": {
    "tenant": "aap-aa-tenant",
    "application": "automation-analytics-backend",
    "kubeconfig": "~/.kube/config.k"
  }
}
```

## Related Diagrams

- [Tool Module Structure](./tool-module-structure.md)
- [Konflux Integration](../07-integrations/konflux-integration.md)
- [Release Pipeline Flow](../08-data-flows/release-pipeline.md)
