# Skill Execution Flow

> Step-by-step skill execution process

## Diagram

```mermaid
sequenceDiagram
    participant User as User/Claude
    participant Tool as skill_run tool
    participant Engine as SkillEngine
    participant YAML as Skill YAML
    participant Context as ExecutionContext
    participant Step as Step Executor
    participant MCP as MCP Tools
    participant WS as WebSocket
    participant Memory as Memory

    User->>Tool: skill_run("start_work", inputs)
    Tool->>Engine: execute(skill_name, inputs)

    Engine->>YAML: Load skill definition
    YAML-->>Engine: Skill object

    Engine->>Engine: Validate inputs
    Engine->>Context: Create context
    Engine->>WS: skill_started(id, name, steps)
    Engine->>Memory: Log skill start

    loop For each step
        Engine->>Context: Set current_step
        Engine->>WS: step_started(skill_id, index, name)

        alt Has condition
            Engine->>Engine: Evaluate condition
            alt Condition false
                Engine->>WS: step_skipped
                Engine->>Engine: Continue to next step
            end
        end

        alt Has confirm
            Engine->>WS: confirmation_required
            WS-->>Engine: User response
            alt Response = abort
                Engine->>Engine: Abort skill
            end
        end

        Engine->>Step: Execute step
        Step->>Step: Resolve templates
        Step->>MCP: Call tool(args)
        MCP-->>Step: Tool result

        alt Step succeeded
            Step->>Context: Store output
            Engine->>WS: step_completed(duration)
        else Step failed
            Engine->>Engine: Handle error
            alt on_error = abort
                Engine->>WS: skill_failed(error)
                Engine-->>User: Error result
            else on_error = continue
                Engine->>WS: step_failed
                Engine->>Engine: Continue to next step
            else on_error = retry
                Engine->>Step: Retry step
            end
        end
    end

    Engine->>WS: skill_completed(duration)
    Engine->>Memory: Log skill completion
    Engine-->>Tool: Skill result
    Tool-->>User: Formatted output
```

## Template Resolution

```mermaid
flowchart TB
    subgraph Input[Step Arguments]
        TEMPLATE["{{ inputs.issue_key }}"]
        STATIC["static_value"]
        NESTED["{{ outputs.step1.field }}"]
    end

    subgraph Context[Execution Context]
        INPUTS[inputs dict]
        OUTPUTS[outputs dict]
        STEPS[step_results dict]
        ENV[environment]
    end

    subgraph Resolution[Template Resolution]
        JINJA[Jinja2 Engine]
        RESOLVE[Resolve references]
        VALIDATE[Validate types]
    end

    subgraph Output[Resolved Arguments]
        FINAL[Final args dict]
    end

    TEMPLATE --> JINJA
    STATIC --> FINAL
    NESTED --> JINJA

    INPUTS --> RESOLVE
    OUTPUTS --> RESOLVE
    STEPS --> RESOLVE
    ENV --> RESOLVE

    JINJA --> RESOLVE
    RESOLVE --> VALIDATE
    VALIDATE --> FINAL
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| SkillEngine.execute | `skill_engine.py` | Main execution method |
| _execute_step | `skill_engine.py` | Step execution |
| _resolve_templates | `skill_engine.py` | Template resolution |
| _handle_error | `skill_engine.py` | Error handling |

## Step Execution Details

| Phase | Description |
|-------|-------------|
| 1. Load | Load step definition |
| 2. Condition | Evaluate condition (if present) |
| 3. Confirm | Request confirmation (if present) |
| 4. Resolve | Resolve template variables |
| 5. Execute | Call MCP tool |
| 6. Store | Store result in context |
| 7. Notify | Send WebSocket event |

## Related Diagrams

- [Skill Engine Architecture](./skill-engine-architecture.md)
- [Skill State Machine](./skill-state-machine.md)
- [Skill Error Handling](./skill-error-handling.md)
