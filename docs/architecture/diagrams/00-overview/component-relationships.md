# Component Relationships

> How major system components connect and interact with each other

## Diagram

```mermaid
graph LR
    subgraph Interfaces[User Interfaces]
        CURSOR[Cursor IDE]
        CLAUDE[Claude CLI]
        VSCODE[VSCode Ext]
        SLACK[Slack]
    end

    subgraph Core[MCP Core]
        MCP[FastMCP]
        PERSONA[PersonaLoader]
        SKILL[SkillEngine]
        TOOLS[ToolRegistry]
    end

    subgraph Managers[State Managers]
        STATE[StateManager]
        CONFIG[ConfigManager]
        SESSION[SessionBuilder]
    end

    subgraph Patterns[Usage Patterns]
        CHECKER[PatternChecker]
        CLASSIFIER[PatternClassifier]
        LEARNER[PatternLearner]
        STORAGE[PatternStorage]
    end

    subgraph Healing[Auto-Heal]
        DECORATOR[AutoHealDecorator]
        PREVENTION[PreventionTracker]
    end

    subgraph Daemons[Background Services]
        SLACK_D[SlackDaemon]
        SPRINT_D[SprintDaemon]
        CRON_D[CronDaemon]
        SESSION_D[SessionDaemon]
        MEET_D[MeetDaemon]
    end

    subgraph Memory[Memory System]
        YAML_MEM[YAML Files]
        VECTOR[VectorDB]
        ABSTRACTION[MemoryAbstraction]
    end

    CURSOR -->|stdio| MCP
    CLAUDE -->|stdio| MCP
    VSCODE -->|WebSocket| MCP
    SLACK -->|D-Bus| SLACK_D

    MCP --> PERSONA
    MCP --> SKILL
    MCP --> TOOLS
    MCP --> STATE
    MCP --> CONFIG

    PERSONA -->|loads| TOOLS
    SKILL -->|calls| TOOLS
    SKILL -->|reads| YAML_MEM

    TOOLS --> DECORATOR
    DECORATOR --> PREVENTION
    DECORATOR --> LEARNER

    CHECKER --> CLASSIFIER
    CLASSIFIER --> STORAGE
    LEARNER --> STORAGE

    SESSION --> STATE
    SESSION --> CONFIG
    SESSION --> CHECKER

    SLACK_D -->|D-Bus| VSCODE
    SPRINT_D -->|D-Bus| VSCODE
    CRON_D --> SKILL
    SESSION_D --> SESSION
    MEET_D --> YAML_MEM

    ABSTRACTION --> YAML_MEM
    ABSTRACTION --> VECTOR
```

## Component Interactions

| Source | Target | Protocol | Purpose |
|--------|--------|----------|---------|
| Cursor/Claude | FastMCP | stdio/JSON-RPC | Tool invocation |
| VSCode Extension | FastMCP | WebSocket | Real-time updates |
| VSCode Extension | Daemons | D-Bus | Service control |
| FastMCP | PersonaLoader | Python | Tool loading |
| FastMCP | SkillEngine | Python | Workflow execution |
| SkillEngine | ToolRegistry | Python | Tool calls |
| ToolRegistry | AutoHealDecorator | Python | Error recovery |
| Daemons | Memory | File I/O | State persistence |
| MemoryAbstraction | Multiple Sources | Adapters | Unified queries |

## Key Relationships

### MCP Server Core
- **FastMCP** is the central hub receiving all requests
- **PersonaLoader** dynamically loads/unloads tool modules
- **SkillEngine** orchestrates multi-step workflows
- **ToolRegistry** manages tool registration and discovery

### State Management
- **StateManager** handles runtime state (JSON)
- **ConfigManager** manages configuration
- **SessionBuilder** bootstraps new sessions with context

### Usage Pattern System
- **PatternChecker** validates tool usage
- **PatternClassifier** categorizes patterns
- **PatternLearner** learns from successes/failures
- **PatternStorage** persists patterns to YAML

### Background Services
- All daemons communicate via **D-Bus**
- **CronDaemon** triggers scheduled skills
- **SessionDaemon** syncs IDE state
- **SlackDaemon** handles real-time messages

## Related Diagrams

- [System Architecture](./system-architecture.md)
- [Technology Stack](./technology-stack.md)
- [Data Flows](../08-data-flows/request-lifecycle.md)
