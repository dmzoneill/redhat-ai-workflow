# Skill Error Handling

> Error detection, recovery, and on_error strategies

## Diagram

```mermaid
flowchart TB
    subgraph Detection[Error Detection]
        TOOL_ERROR[Tool returns error]
        EXCEPTION[Exception raised]
        TIMEOUT[Timeout exceeded]
        VALIDATION[Validation failed]
    end

    subgraph Strategy[on_error Strategy]
        ABORT[abort<br/>Stop execution]
        CONTINUE[continue<br/>Skip to next step]
        RETRY[retry<br/>Retry with backoff]
        AUTO_HEAL[auto_heal<br/>Apply fix and retry]
    end

    subgraph Recovery[Recovery Actions]
        LOG[Log error]
        NOTIFY[Send notification]
        ROLLBACK[Rollback changes]
        CLEANUP[Cleanup resources]
    end

    subgraph Result[Result]
        FAIL[Skill failed]
        PARTIAL[Partial success]
        RECOVERED[Recovered]
    end

    TOOL_ERROR --> Strategy
    EXCEPTION --> Strategy
    TIMEOUT --> Strategy
    VALIDATION --> ABORT

    ABORT --> LOG
    CONTINUE --> LOG
    RETRY --> LOG
    AUTO_HEAL --> LOG

    LOG --> NOTIFY
    ABORT --> ROLLBACK
    ABORT --> FAIL

    CONTINUE --> PARTIAL
    RETRY --> RECOVERED
    AUTO_HEAL --> RECOVERED
```

## Error Strategies

```mermaid
sequenceDiagram
    participant Engine as SkillEngine
    participant Step as Step Executor
    participant Tool as MCP Tool
    participant AutoHeal as Auto-Heal
    participant WS as WebSocket

    Step->>Tool: Call tool
    Tool-->>Step: Error response

    alt on_error = abort
        Step->>Engine: Report error
        Engine->>WS: skill_failed
        Engine-->>Engine: Return error
    else on_error = continue
        Step->>Engine: Log error
        Engine->>WS: step_failed
        Engine->>Engine: Continue to next step
    else on_error = retry
        loop Until max_retries
            Step->>Step: Wait backoff
            Step->>Tool: Retry call
            alt Success
                Step->>Engine: Report success
            end
        end
        Step->>Engine: Max retries exceeded
    else on_error = auto_heal
        Step->>AutoHeal: Detect failure type
        AutoHeal->>AutoHeal: Apply fix
        AutoHeal->>Tool: Retry call
        Tool-->>AutoHeal: Result
        AutoHeal-->>Step: Healed result
    end
```

## Strategy Details

| Strategy | Behavior | Use Case |
|----------|----------|----------|
| `abort` | Stop execution, return error | Critical failures |
| `continue` | Log error, skip to next step | Non-critical steps |
| `retry` | Retry with exponential backoff | Transient failures |
| `auto_heal` | Apply fix and retry | Auth/network errors |

## Retry Configuration

```yaml
steps:
  - name: deploy
    tool: bonfire_deploy
    args:
      namespace: "{{ inputs.namespace }}"
    on_error: retry
    retry:
      max_attempts: 3
      initial_delay: 1
      max_delay: 30
      backoff_multiplier: 2
```

## Auto-Heal Integration

```mermaid
flowchart TB
    subgraph Error[Error Detection]
        AUTH[Auth error<br/>401, 403, token expired]
        NETWORK[Network error<br/>timeout, connection refused]
        OTHER[Other errors]
    end

    subgraph Fix[Auto-Heal Fix]
        KUBE_LOGIN[kube_login<br/>Refresh credentials]
        VPN_CONNECT[vpn_connect<br/>Connect VPN]
        NO_FIX[No automatic fix]
    end

    subgraph Result[Result]
        RETRY[Retry step]
        FAIL[Report failure]
    end

    AUTH --> KUBE_LOGIN
    NETWORK --> VPN_CONNECT
    OTHER --> NO_FIX

    KUBE_LOGIN --> RETRY
    VPN_CONNECT --> RETRY
    NO_FIX --> FAIL
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| _handle_error | `skill_engine.py` | Error handling |
| auto_heal | `auto_heal_decorator.py` | Auto-heal decorator |
| retry logic | `skill_engine.py` | Retry implementation |

## Error Logging

```yaml
# memory/learned/tool_failures.yaml
failures:
  - skill: start_work
    step: create_branch
    tool: git_create_branch
    error: "branch already exists"
    on_error: continue
    timestamp: "2024-01-15T10:30:00"
    recovered: false
```

## Related Diagrams

- [Skill State Machine](./skill-state-machine.md)
- [Auto-Heal Decorator](../01-server/auto-heal-decorator.md)
- [Skill Execution Flow](./skill-execution-flow.md)
