# Skill Engine Architecture

> Core skill execution engine internals

## Diagram

```mermaid
classDiagram
    class SkillEngine {
        +server: FastMCP
        +skills_dir: Path
        +execute(skill_name, inputs): dict
        +validate(skill_name): list
        +list_skills(): list
        +get_skill_info(name): dict
        -_load_skill(name): Skill
        -_execute_step(step, context): dict
        -_handle_error(step, error): dict
    }

    class Skill {
        +name: str
        +description: str
        +inputs: list~Input~
        +steps: list~Step~
        +on_error: str
        +notify: list~str~
    }

    class Input {
        +name: str
        +type: str
        +required: bool
        +default: any
        +description: str
    }

    class Step {
        +name: str
        +tool: str
        +args: dict
        +output: str
        +on_error: str
        +condition: str
        +confirm: ConfirmConfig
    }

    class ExecutionContext {
        +skill_id: str
        +inputs: dict
        +outputs: dict
        +step_results: dict
        +current_step: int
        +status: str
    }

    class ConfirmConfig {
        +prompt: str
        +options: list~str~
        +default: str
        +timeout: int
    }

    SkillEngine --> Skill : loads
    Skill --> Input : has
    Skill --> Step : has
    Step --> ConfirmConfig : optional
    SkillEngine --> ExecutionContext : creates
```

## Execution Flow

```mermaid
sequenceDiagram
    participant User as User/Claude
    participant Engine as SkillEngine
    participant Loader as Skill Loader
    participant Executor as Step Executor
    participant Tools as Tool Registry
    participant WS as WebSocket

    User->>Engine: execute("start_work", inputs)
    Engine->>Loader: Load skill YAML
    Loader-->>Engine: Skill definition

    Engine->>Engine: Validate inputs
    Engine->>WS: skill_started event

    loop For each step
        Engine->>WS: step_started event
        Engine->>Executor: Execute step
        
        alt Has condition
            Executor->>Executor: Evaluate condition
        end
        
        alt Has confirm
            Executor->>WS: confirmation_required
            WS-->>Executor: User response
        end

        Executor->>Tools: Call tool
        Tools-->>Executor: Tool result
        
        alt Step succeeded
            Engine->>WS: step_completed event
        else Step failed
            Engine->>Engine: Handle error
            Engine->>WS: step_failed event
        end
    end

    Engine->>WS: skill_completed event
    Engine-->>User: Skill result
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| SkillEngine | `tool_modules/aa_workflow/src/skill_engine.py` | Main engine class |
| skill_run | `tool_modules/aa_workflow/src/tools_core.py` | MCP tool wrapper |
| skill_list | `tool_modules/aa_workflow/src/tools_basic.py` | List skills |
| skill_info | `tool_modules/aa_workflow/src/tools_basic.py` | Get skill info |

## Related Diagrams

- [Skill YAML Schema](./skill-yaml-schema.md)
- [Skill Execution Flow](./skill-execution-flow.md)
- [Skill State Machine](./skill-state-machine.md)
