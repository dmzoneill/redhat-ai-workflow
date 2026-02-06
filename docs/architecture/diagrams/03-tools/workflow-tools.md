# Workflow Tools

> aa_workflow module for core workflow operations

## Diagram

```mermaid
classDiagram
    class WorkflowBasic {
        +skill_list(): list
        +skill_info(name): dict
        +persona_list(): list
        +persona_load(name): dict
        +session_start(name): dict
        +session_info(): dict
    }

    class WorkflowCore {
        +skill_run(name, inputs): dict
        +tool_exec(tool, args): dict
        +debug_tool(tool, error): dict
        +check_known_issues(tool, error): dict
        +learn_tool_fix(tool, pattern, fix): dict
    }

    class MemoryTools {
        +memory_read(path): dict
        +memory_write(path, data): dict
        +memory_append(path, key, value): dict
        +memory_query(question): dict
        +memory_ask(question, sources): dict
    }

    class SessionTools {
        +session_start(name, agent): dict
        +session_info(id): dict
        +session_list(): list
        +session_switch(id): dict
        +session_set_project(project): dict
    }

    class SkillEngine {
        +execute(skill, inputs): dict
        +validate(skill): list
        +get_steps(skill): list
    }

    WorkflowBasic --> SkillEngine
    WorkflowCore --> SkillEngine
    WorkflowCore --> MemoryTools
    WorkflowBasic --> SessionTools
```

## Tool Categories

```mermaid
flowchart TB
    subgraph Skills[Skill Tools]
        SKILL_LIST[skill_list]
        SKILL_INFO[skill_info]
        SKILL_RUN[skill_run]
    end

    subgraph Personas[Persona Tools]
        PERSONA_LIST[persona_list]
        PERSONA_LOAD[persona_load]
    end

    subgraph Sessions[Session Tools]
        SESSION_START[session_start]
        SESSION_INFO[session_info]
        SESSION_LIST[session_list]
    end

    subgraph Memory[Memory Tools]
        MEMORY_READ[memory_read]
        MEMORY_WRITE[memory_write]
        MEMORY_ASK[memory_ask]
    end

    subgraph Debug[Debug Tools]
        DEBUG_TOOL[debug_tool]
        CHECK_ISSUES[check_known_issues]
        LEARN_FIX[learn_tool_fix]
    end
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| tools_basic.py | `tool_modules/aa_workflow/src/` | Basic operations |
| tools_core.py | `tool_modules/aa_workflow/src/` | Core operations |
| memory_tools.py | `tool_modules/aa_workflow/src/` | Memory operations |
| session_tools.py | `tool_modules/aa_workflow/src/` | Session management |
| skill_engine.py | `tool_modules/aa_workflow/src/` | Skill execution |
| scheduler.py | `tool_modules/aa_workflow/src/` | Job scheduling |
| tool_gap_detector.py | `tool_modules/aa_workflow/src/` | Gap detection |

## Tool Summary

| Tool | Category | Description |
|------|----------|-------------|
| `skill_list` | Skills | List available skills |
| `skill_run` | Skills | Execute a skill |
| `persona_load` | Personas | Load persona tools |
| `session_start` | Sessions | Start new session |
| `memory_ask` | Memory | Query memory |
| `debug_tool` | Debug | Debug failed tool |

## Skill Execution Flow

```mermaid
sequenceDiagram
    participant User as User
    participant Tool as skill_run
    participant Engine as SkillEngine
    participant Steps as Step Executor
    participant Memory as Memory

    User->>Tool: skill_run("start_work", inputs)
    Tool->>Engine: execute(skill, inputs)
    Engine->>Engine: Load skill YAML
    Engine->>Engine: Validate inputs

    loop For each step
        Engine->>Steps: Execute step
        Steps->>Steps: Call tool
        Steps-->>Engine: Step result
        Engine->>Memory: Log progress
    end

    Engine-->>Tool: Skill result
    Tool-->>User: Formatted output
```

## Session Bootstrap

```mermaid
flowchart TB
    subgraph Start[session_start]
        CREATE[Create session]
        CLASSIFY[Classify intent]
        SUGGEST[Suggest persona]
    end

    subgraph AutoLoad[Auto-load]
        CHECK{Confidence > 80%?}
        LOAD[Load persona]
        SKIP[Skip auto-load]
    end

    subgraph Context[Context]
        WORK[Current work]
        PATTERNS[Patterns]
        ACTIONS[Recommended actions]
    end

    CREATE --> CLASSIFY
    CLASSIFY --> SUGGEST
    SUGGEST --> CHECK
    CHECK -->|Yes| LOAD
    CHECK -->|No| SKIP
    LOAD --> WORK
    SKIP --> WORK
    WORK --> PATTERNS
    PATTERNS --> ACTIONS
```

## Related Diagrams

- [Tool Module Structure](./tool-module-structure.md)
- [Skill Engine Architecture](../04-skills/skill-engine-architecture.md)
- [Session Builder](../01-server/session-builder.md)
