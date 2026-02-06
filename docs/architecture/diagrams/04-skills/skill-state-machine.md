# Skill State Machine

> Execution states and transitions

## Diagram

```mermaid
stateDiagram-v2
    [*] --> Pending: skill_run() called

    Pending --> Validating: Load skill
    Validating --> Ready: Inputs valid
    Validating --> Failed: Validation error

    Ready --> Running: Start execution

    state Running {
        [*] --> StepPending

        StepPending --> CheckingCondition: Has condition
        StepPending --> Confirming: Has confirm
        StepPending --> Executing: No condition/confirm

        CheckingCondition --> Skipped: Condition false
        CheckingCondition --> Confirming: Condition true + has confirm
        CheckingCondition --> Executing: Condition true

        Confirming --> Executing: User confirmed
        Confirming --> Skipped: User skipped
        Confirming --> Aborted: User aborted
        Confirming --> Executing: Timeout (use default)

        Executing --> StepCompleted: Tool succeeded
        Executing --> StepFailed: Tool failed

        StepCompleted --> StepPending: More steps
        StepCompleted --> [*]: All steps done

        StepFailed --> Retrying: on_error = retry
        StepFailed --> StepPending: on_error = continue
        StepFailed --> Aborted: on_error = abort

        Retrying --> Executing: Retry attempt
        Retrying --> Aborted: Max retries

        Skipped --> StepPending: More steps
        Skipped --> [*]: All steps done
    }

    Running --> Completed: All steps done
    Running --> Failed: Aborted

    Completed --> [*]
    Failed --> [*]
```

## State Descriptions

| State | Description |
|-------|-------------|
| Pending | Skill execution requested |
| Validating | Validating inputs and loading skill |
| Ready | Ready to execute steps |
| Running | Executing steps |
| StepPending | Waiting to execute next step |
| CheckingCondition | Evaluating step condition |
| Confirming | Waiting for user confirmation |
| Executing | Calling MCP tool |
| StepCompleted | Step finished successfully |
| StepFailed | Step failed |
| Retrying | Retrying failed step |
| Skipped | Step skipped (condition false or user skip) |
| Aborted | Execution aborted |
| Completed | All steps completed successfully |
| Failed | Execution failed |

## Confirmation States

```mermaid
stateDiagram-v2
    [*] --> WaitingForResponse: Show confirmation

    WaitingForResponse --> Confirmed: User selects "yes"
    WaitingForResponse --> Skipped: User selects "skip"
    WaitingForResponse --> Aborted: User selects "abort"
    WaitingForResponse --> TimedOut: Timeout reached

    TimedOut --> Confirmed: default = yes
    TimedOut --> Skipped: default = skip
    TimedOut --> LetClaude: default = let_claude

    LetClaude --> Confirmed: Claude decides yes
    LetClaude --> Skipped: Claude decides skip

    Confirmed --> [*]
    Skipped --> [*]
    Aborted --> [*]
```

## Error Handling States

```mermaid
stateDiagram-v2
    [*] --> StepFailed: Tool error

    StepFailed --> CheckOnError: Evaluate on_error

    CheckOnError --> Abort: on_error = "abort"
    CheckOnError --> Continue: on_error = "continue"
    CheckOnError --> Retry: on_error = "retry"

    Retry --> CheckRetries: Check retry count
    CheckRetries --> RetryStep: retries < max
    CheckRetries --> Abort: retries >= max

    RetryStep --> [*]: Retry execution

    Continue --> [*]: Continue to next step
    Abort --> [*]: Abort skill
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| SkillState | `skill_engine.py` | State tracking |
| ExecutionContext | `skill_engine.py` | Context with state |

## Related Diagrams

- [Skill Engine Architecture](./skill-engine-architecture.md)
- [Skill Execution Flow](./skill-execution-flow.md)
- [Skill Error Handling](./skill-error-handling.md)
