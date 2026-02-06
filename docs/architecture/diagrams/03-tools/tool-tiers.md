# Tool Tiers

> Basic, core, and extra tier system for tool organization

## Diagram

```mermaid
graph LR
    subgraph Tiers[Tool Tiers]
        BASIC[basic<br/>Essential tools]
        CORE[core<br/>Core functionality]
        EXTRA[extra<br/>Extended features]
        STYLE[style<br/>Style tools]
    end

    subgraph Loading[Loading Strategy]
        ALL_PERSONAS[All Personas]
        MOST_PERSONAS[Most Personas]
        SPECIFIC[Specific Personas]
        STYLE_ONLY[Style Personas]
    end

    subgraph Examples[Example Tools]
        BASIC_EX[jira_view_issue<br/>git_status<br/>k8s_get_pods]
        CORE_EX[jira_create_issue<br/>git_commit<br/>k8s_apply]
        EXTRA_EX[jira_bulk_update<br/>git_rebase<br/>k8s_port_forward]
        STYLE_EX[style_analyze<br/>style_suggest]
    end

    BASIC --> ALL_PERSONAS
    CORE --> MOST_PERSONAS
    EXTRA --> SPECIFIC
    STYLE --> STYLE_ONLY

    BASIC --> BASIC_EX
    CORE --> CORE_EX
    EXTRA --> EXTRA_EX
    STYLE --> STYLE_EX
```

## Tier Definitions

```mermaid
flowchart TB
    subgraph Basic[Basic Tier]
        B_DESC[Read-only operations<br/>Safe to call anytime<br/>No side effects]
        B_TOOLS[view, list, get, search, status]
    end

    subgraph Core[Core Tier]
        C_DESC[Write operations<br/>Common workflows<br/>Standard use cases]
        C_TOOLS[create, update, commit, apply]
    end

    subgraph Extra[Extra Tier]
        E_DESC[Advanced operations<br/>Specialized workflows<br/>Power user features]
        E_TOOLS[bulk, migrate, rebase, port-forward]
    end

    subgraph Style[Style Tier]
        S_DESC[Style analysis<br/>Writing assistance<br/>Tone matching]
        S_TOOLS[analyze, suggest, match, generate]
    end
```

## Tier by Module

| Module | Basic | Core | Extra | Style |
|--------|-------|------|-------|-------|
| jira | view, search, list | create, update, transition | bulk_update, clone | - |
| gitlab | view, list, search | create_mr, approve | merge, rebase | - |
| git | status, log, diff | commit, push, pull | rebase, cherry-pick | - |
| k8s | get, describe, logs | apply, delete | port-forward, exec | - |
| slack | search, history | send, react | bulk_send | - |
| style | - | - | - | analyze, suggest |

## Loading Rules

```mermaid
sequenceDiagram
    participant Persona as Persona Config
    participant Loader as PersonaLoader
    participant Module as Tool Module

    Persona->>Loader: tools: [jira_basic, jira_core]

    loop For each tool spec
        Loader->>Loader: Parse module_tier

        alt tier = basic
            Loader->>Module: Load tools_basic.py
        else tier = core
            Loader->>Module: Load tools_core.py
        else tier = extra
            Loader->>Module: Load tools_extra.py
        else tier = style
            Loader->>Module: Load tools_style.py
        else no tier (base module)
            Loader->>Module: Load tools_basic.py
        end
    end
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| tools_basic.py | `tool_modules/aa_*/src/` | Essential tools |
| tools_core.py | `tool_modules/aa_*/src/` | Core tools |
| tools_extra.py | `tool_modules/aa_*/src/` | Extended tools |
| tools_style.py | `tool_modules/aa_*/src/` | Style tools |

## Persona Examples

```yaml
# Developer persona - needs core tools
developer:
  tools:
    - jira_basic
    - jira_core
    - gitlab_basic
    - gitlab_core
    - git_basic
    - git_core

# DevOps persona - needs extra k8s tools
devops:
  tools:
    - k8s_basic
    - k8s_core
    - k8s_extra
    - bonfire_basic
    - bonfire_extra

# Researcher persona - basic only
researcher:
  tools:
    - jira_basic
    - gitlab_basic
    - code_search_basic
```

## Tool Count Guidelines

| Tier | Typical Count | Purpose |
|------|---------------|---------|
| basic | 5-10 | Essential read operations |
| core | 5-15 | Common write operations |
| extra | 5-20 | Advanced features |
| style | 2-5 | Style assistance |

## Related Diagrams

- [Tool Module Structure](./tool-module-structure.md)
- [Persona Tool Mapping](../05-personas/persona-tool-mapping.md)
- [Tool Registry](../01-server/tool-registry.md)
