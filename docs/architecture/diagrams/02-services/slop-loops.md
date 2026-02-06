# SLOP Loops

> Loop execution flow and state management

## Diagram

```mermaid
flowchart TB
    subgraph LoopDefinition[Loop Definition]
        CONFIG[Loop Config]
        STEPS[Step Definitions]
        HANDLERS[Error Handlers]
    end

    subgraph Execution[Loop Execution]
        START[Start Loop]
        CONTEXT[Load Context]
        
        subgraph StepExecution[Step Execution]
            STEP[Execute Step]
            TOOL[Call Tool]
            PROCESS[Process Result]
            STORE[Store State]
        end
        
        DECIDE[Decision Point]
        NEXT[Next Step]
        COMPLETE[Complete]
    end

    subgraph ErrorHandling[Error Handling]
        CATCH[Catch Error]
        RETRY[Retry Logic]
        FALLBACK[Fallback Action]
        ABORT[Abort Loop]
    end

    subgraph State[State Management]
        LOOP_STATE[Loop State]
        STEP_STATE[Step State]
        CONTEXT_STATE[Context State]
    end

    CONFIG --> START
    STEPS --> START
    START --> CONTEXT
    CONTEXT --> STEP

    STEP --> TOOL
    TOOL --> PROCESS
    PROCESS --> STORE
    STORE --> DECIDE

    DECIDE -->|More steps| NEXT
    NEXT --> STEP
    DECIDE -->|Done| COMPLETE

    TOOL -->|Error| CATCH
    CATCH --> RETRY
    RETRY -->|Retry| TOOL
    RETRY -->|Max retries| FALLBACK
    FALLBACK --> ABORT
    HANDLERS --> CATCH

    STORE --> LOOP_STATE
    STORE --> STEP_STATE
    CONTEXT --> CONTEXT_STATE
```

## Loop State Machine

```mermaid
stateDiagram-v2
    [*] --> Pending: Loop registered

    Pending --> Starting: start() called
    Starting --> Running: Context loaded

    state Running {
        [*] --> ExecutingStep
        ExecutingStep --> ProcessingResult: Tool returned
        ProcessingResult --> StoringState: Result processed
        StoringState --> ExecutingStep: More steps
        StoringState --> [*]: All steps done
    }

    Running --> Paused: pause() called
    Paused --> Running: resume() called

    Running --> Completed: Success
    Running --> Failed: Unrecoverable error
    Running --> Retrying: Recoverable error

    Retrying --> Running: Retry successful
    Retrying --> Failed: Max retries exceeded

    Completed --> [*]
    Failed --> [*]
```

## Step Types

```mermaid
graph TB
    subgraph StepTypes[Step Types]
        TOOL_STEP[Tool Step<br/>Call MCP tool]
        TRANSFORM[Transform Step<br/>Process data]
        CONDITION[Condition Step<br/>Branch logic]
        PARALLEL[Parallel Step<br/>Concurrent execution]
        WAIT[Wait Step<br/>Delay execution]
    end

    subgraph ToolStep[Tool Step Details]
        TOOL_NAME[Tool Name]
        TOOL_ARGS[Arguments]
        TOOL_TIMEOUT[Timeout]
        TOOL_RETRY[Retry Config]
    end

    subgraph TransformStep[Transform Step Details]
        INPUT[Input Data]
        TRANSFORM_FN[Transform Function]
        OUTPUT[Output Data]
    end

    TOOL_STEP --> ToolStep
    TRANSFORM --> TransformStep
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| loops | `services/slop/loops.py` | Loop definitions |
| Orchestrator | `services/slop/orchestrator.py` | Execution engine |
| database | `services/slop/database.py` | State storage |
| external_tools | `services/slop/external_tools.py` | Tool integration |

## Loop Configuration Schema

```yaml
loop:
  name: string
  description: string
  enabled: boolean
  
  trigger:
    type: interval | cron | event | manual
    interval: integer  # seconds
    cron: string       # cron expression
    event: string      # event name
  
  context:
    - source: memory
      path: state/current_work
    - source: jira
      query: "project = AAP"
  
  steps:
    - name: fetch_issues
      type: tool
      tool: jira_search
      args:
        jql: "{{ context.jql }}"
      on_error: retry
      
    - name: process_issues
      type: transform
      input: "{{ steps.fetch_issues.result }}"
      transform: filter_stale
      
    - name: notify
      type: tool
      tool: slack_send
      condition: "{{ steps.process_issues.count > 0 }}"
  
  on_success:
    - log_to_memory
    - emit_event: loop_completed
    
  on_failure:
    - log_error
    - notify_slack
```

## Built-in Loops

| Loop | Trigger | Purpose |
|------|---------|---------|
| jira_sync | 5 min interval | Sync Jira issues |
| slack_monitor | 1 min interval | Monitor Slack |
| health_check | 1 min interval | System health |
| cleanup | Daily cron | Clean old data |

## Related Diagrams

- [SLOP Daemon](./slop-daemon.md)
- [Ralph Loop Manager](../01-server/ralph-loop-manager.md)
- [Skill Execution Flow](../04-skills/skill-execution-flow.md)
