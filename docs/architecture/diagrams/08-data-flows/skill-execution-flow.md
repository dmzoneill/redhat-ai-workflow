# Skill Execution Flow

> Complete flow of skill execution

## Diagram

```mermaid
sequenceDiagram
    participant User as User/Claude
    participant Tool as skill_run
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
    YAML-->>Engine: Skill config

    Engine->>Engine: Validate inputs
    Engine->>Context: Create context

    Engine->>WS: Notify: skill_started

    loop For each step
        Engine->>Step: Execute step

        alt Has condition
            Step->>Step: Evaluate condition
            opt Condition false
                Step-->>Engine: Skip step
            end
        end

        opt Requires confirmation
            Step->>WS: Request confirmation
            WS-->>Step: User response
        end

        Step->>MCP: Call tool
        MCP-->>Step: Result

        Step->>Context: Store output
        Step->>WS: Notify: step_completed
    end

    Engine->>Memory: Log execution
    Engine->>WS: Notify: skill_completed
    Engine-->>Tool: Final result
    Tool-->>User: Formatted output
```

## Step Execution Detail

```mermaid
flowchart TB
    subgraph StepStart[Step Start]
        LOAD[Load step config]
        RESOLVE[Resolve templates]
    end

    subgraph Condition[Condition Check]
        HAS_COND{Has condition?}
        EVAL[Evaluate condition]
        SKIP[Skip step]
    end

    subgraph Confirm[Confirmation]
        HAS_CONFIRM{Requires confirm?}
        REQUEST[Request via WebSocket]
        WAIT[Wait for response]
        DENIED[Abort or skip]
    end

    subgraph Execute[Execution]
        CALL_TOOL[Call MCP tool]
        PROCESS[Process result]
        STORE[Store in context]
    end

    StepStart --> Condition
    HAS_COND -->|Yes| EVAL
    HAS_COND -->|No| Confirm
    EVAL -->|True| Confirm
    EVAL -->|False| SKIP

    HAS_CONFIRM -->|Yes| REQUEST
    HAS_CONFIRM -->|No| Execute
    REQUEST --> WAIT
    WAIT -->|Approved| Execute
    WAIT -->|Denied| DENIED

    CALL_TOOL --> PROCESS
    PROCESS --> STORE
```

## Template Resolution

```mermaid
flowchart TB
    subgraph Templates[Template Types]
        INPUT["{{ inputs.issue_key }}"]
        OUTPUT["{{ steps.fetch_issue.output.key }}"]
        CONFIG["{{ config.gitlab_url }}"]
        CONTEXT["{{ context.project }}"]
    end

    subgraph Resolution[Resolution Process]
        PARSE[Parse template]
        LOOKUP[Lookup value]
        REPLACE[Replace in string]
    end

    Templates --> PARSE
    PARSE --> LOOKUP
    LOOKUP --> REPLACE
```

## Error Handling

```mermaid
flowchart TB
    ERROR[Step Error]

    CHECK{on_error strategy}

    ABORT[Abort skill]
    CONTINUE[Continue to next]
    RETRY[Retry step]
    AUTO_HEAL[Auto-heal & retry]

    CHECK -->|abort| ABORT
    CHECK -->|continue| CONTINUE
    CHECK -->|retry| RETRY
    CHECK -->|auto_heal| AUTO_HEAL

    AUTO_HEAL --> DETECT[Detect error type]
    DETECT --> FIX[Apply fix]
    FIX --> RETRY_STEP[Retry step]
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| SkillEngine | `tool_modules/aa_workflow/src/skill_engine.py` | Main engine |
| skill_run | `tool_modules/aa_workflow/src/tools_core.py` | MCP tool |
| WebSocket | `server/websocket_server.py` | Notifications |

## Related Diagrams

- [Skill Engine Architecture](../04-skills/skill-engine-architecture.md)
- [Skill State Machine](../04-skills/skill-state-machine.md)
- [Skill Error Handling](../04-skills/skill-error-handling.md)
