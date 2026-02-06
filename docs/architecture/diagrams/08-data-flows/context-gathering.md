# Context Gathering

> How context is assembled for LLM interactions

## Diagram

```mermaid
graph TB
    subgraph Sources[Context Sources]
        PERSONA[Persona Context]
        SESSION[Session State]
        MEMORY[Memory Data]
        SKILLS[Available Skills]
        TOOLS[Loaded Tools]
    end

    subgraph Builder[Session Builder]
        GATHER[Gather context]
        MERGE[Merge sources]
        FORMAT[Format prompt]
    end

    subgraph Output[Super Prompt]
        SYSTEM[System context]
        USER[User context]
        HISTORY[Conversation history]
    end

    Sources --> Builder
    Builder --> Output
```

## Context Assembly Flow

```mermaid
sequenceDiagram
    participant Session as Session Start
    participant Builder as SessionBuilder
    participant Persona as PersonaLoader
    participant Memory as Memory
    participant Skills as SkillEngine

    Session->>Builder: Build context

    par Gather sources (parallel)
        Builder->>Persona: Get persona context
        Persona-->>Builder: Persona config

        Builder->>Memory: Get current work
        Memory-->>Builder: Active issues

        Builder->>Skills: Get available skills
        Skills-->>Builder: Skill list
    end

    Builder->>Builder: Merge contexts
    Builder->>Builder: Format super prompt
    Builder-->>Session: Complete context
```

## Context Layers

```mermaid
flowchart TB
    subgraph Layer1[Layer 1: System]
        IDENTITY[AI identity]
        RULES[Behavior rules]
        CAPABILITIES[Tool capabilities]
    end

    subgraph Layer2[Layer 2: Persona]
        FOCUS[Work focus]
        DEFAULTS[Default values]
        PROMPTS[Custom prompts]
    end

    subgraph Layer3[Layer 3: Session]
        PROJECT[Current project]
        ISSUES[Active issues]
        BRANCHES[Active branches]
    end

    subgraph Layer4[Layer 4: Conversation]
        HISTORY[Message history]
        TOOL_RESULTS[Recent tool results]
    end

    Layer1 --> Layer2
    Layer2 --> Layer3
    Layer3 --> Layer4
```

## Super Prompt Structure

```markdown
## System Context
You are an AI assistant for software development workflows.

### Available Tools
- jira_view_issue: View Jira issue details
- git_status: Check git status
- ...

### Behavior Rules
- Use skills for common workflows
- Never discard uncommitted work
- ...

## Persona Context
**Current Persona:** developer
**Focus:** Code development and review

### Defaults
- Default branch: main
- Commit format: {issue_key} - {type}({scope}): {description}

## Session Context
**Project:** automation-analytics-backend
**Active Issue:** AAP-12345 (In Progress)
**Branch:** aap-12345-fix-auth

## Conversation History
[Previous messages and tool results]
```

## Context Injection Points

```mermaid
flowchart TB
    subgraph Injection[Injection Points]
        BOOTSTRAP[Session bootstrap]
        TOOL_CALL[Before tool call]
        SKILL_RUN[Before skill run]
        QUERY[Memory query]
    end

    subgraph Context[Injected Context]
        PROJECT_CTX[Project context]
        ISSUE_CTX[Issue context]
        ENV_CTX[Environment context]
    end

    Injection --> Context
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| SessionBuilder | `server/session_builder.py` | Context assembly |
| UsageContextInjector | `server/usage_context_injector.py` | Context injection |
| PersonaLoader | `server/persona_loader.py` | Persona context |

## Related Diagrams

- [Session Bootstrap](./session-bootstrap.md)
- [Persona Context](../05-personas/persona-context.md)
- [Session Builder](../01-server/session-builder.md)
