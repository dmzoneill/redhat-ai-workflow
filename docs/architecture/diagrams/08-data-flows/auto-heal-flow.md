# Auto-Heal Flow

> Automatic error detection and recovery

## Diagram

```mermaid
sequenceDiagram
    participant Tool as MCP Tool
    participant Decorator as @auto_heal
    participant Detector as Error Detector
    participant Fixer as Fix Executor
    participant Memory as Memory
    participant External as External API

    Tool->>External: API call
    External-->>Tool: Error response

    Tool->>Decorator: Return error
    Decorator->>Detector: Analyze error

    Detector->>Detector: Match patterns
    Detector-->>Decorator: Fix action

    alt Fix available
        Decorator->>Fixer: Execute fix
        Fixer-->>Decorator: Fix result

        Decorator->>Tool: Retry original call
        Tool->>External: API call (retry)
        External-->>Tool: Success

        Decorator->>Memory: Log healing event
    else No fix
        Decorator-->>Tool: Return original error
    end

    Tool-->>Tool: Return result
```

## Error Detection

```mermaid
flowchart TB
    subgraph Patterns[Error Patterns]
        AUTH["401 Unauthorized<br/>Token expired<br/>Authentication failed"]
        NETWORK["Connection refused<br/>Timeout<br/>DNS resolution failed"]
        RESOURCE["404 Not found<br/>Resource deleted"]
        RATE["429 Too many requests<br/>Rate limited"]
    end

    subgraph Detection[Pattern Matching]
        MATCH[Match error text]
        CLASSIFY[Classify error type]
        SELECT[Select fix action]
    end

    Patterns --> Detection
```

## Fix Actions

```mermaid
flowchart TB
    subgraph AuthFixes[Auth Fixes]
        KUBE_LOGIN[kube_login<br/>Refresh K8s token]
        TOKEN_REFRESH[token_refresh<br/>Refresh OAuth token]
    end

    subgraph NetworkFixes[Network Fixes]
        VPN_CONNECT[vpn_connect<br/>Reconnect VPN]
        RETRY_BACKOFF[retry_backoff<br/>Exponential backoff]
    end

    subgraph ResourceFixes[Resource Fixes]
        CACHE_CLEAR[cache_clear<br/>Clear stale cache]
    end

    subgraph RateFixes[Rate Limit Fixes]
        WAIT_RETRY[wait_retry<br/>Wait and retry]
    end
```

## State Machine

```mermaid
stateDiagram-v2
    [*] --> Executing: Tool called

    Executing --> Success: No error
    Executing --> ErrorDetected: Error returned

    ErrorDetected --> Analyzing: Check patterns
    Analyzing --> FixAvailable: Pattern matched
    Analyzing --> NoFix: No match

    FixAvailable --> ApplyingFix: Execute fix
    ApplyingFix --> Retrying: Fix succeeded
    ApplyingFix --> NoFix: Fix failed

    Retrying --> Success: Retry succeeded
    Retrying --> NoFix: Retry failed

    Success --> Logging: Log success
    NoFix --> Logging: Log failure

    Logging --> [*]
```

## Healing Log

```yaml
# memory/learned/tool_fixes.yaml
healing_events:
  - timestamp: 2026-02-04T10:30:00
    tool: k8s_get_pods
    error: "Unauthorized"
    fix_applied: kube_login
    result: success
    retry_count: 1

  - timestamp: 2026-02-04T11:00:00
    tool: gitlab_view_mr
    error: "Connection refused"
    fix_applied: vpn_connect
    result: success
    retry_count: 1
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| auto_heal | `server/auto_heal_decorator.py` | Decorator |
| Error patterns | `auto_heal_decorator.py` | Pattern definitions |
| Fix actions | `auto_heal_decorator.py` | Fix implementations |

## Related Diagrams

- [Auto-Heal Decorator](../01-server/auto-heal-decorator.md)
- [Learned Patterns](../06-memory/learned-patterns.md)
- [Skill Error Handling](../04-skills/skill-error-handling.md)
