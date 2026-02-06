# Auto-Heal Decorator

> Automatic error detection and recovery for MCP tools

## Diagram

```mermaid
stateDiagram-v2
    [*] --> Execute: Tool called

    Execute --> CheckResult: Function returns
    Execute --> HandleException: Exception raised

    CheckResult --> Success: No error patterns
    CheckResult --> DetectFailure: Error in output

    DetectFailure --> AuthFailure: 401/403/token expired
    DetectFailure --> NetworkFailure: timeout/no route
    DetectFailure --> UnknownFailure: Other error

    AuthFailure --> GuessCluster: cluster="auto"
    AuthFailure --> KubeLogin: cluster specified
    GuessCluster --> KubeLogin: Determine cluster

    NetworkFailure --> VPNConnect: Run vpn_connect

    KubeLogin --> FixSuccess: Login successful
    KubeLogin --> FixFailed: Login failed
    VPNConnect --> FixSuccess: VPN connected
    VPNConnect --> FixFailed: VPN failed

    FixSuccess --> LogToMemory: Log auto-heal
    LogToMemory --> Retry: Retry tool

    Retry --> Execute: attempt < max_retries
    Retry --> ReturnResult: max retries reached

    FixFailed --> ReturnResult: Return original error
    UnknownFailure --> ReturnResult: Return original error
    Success --> ReturnResult: Return success

    HandleException --> DetectFailure: Check exception message

    ReturnResult --> [*]
```

## Class Structure

```mermaid
classDiagram
    class auto_heal {
        <<decorator>>
        +cluster: ClusterType
        +max_retries: int
        +retry_on: list~str~
    }

    class ClusterType {
        <<enumeration>>
        stage
        prod
        ephemeral
        konflux
        auto
    }

    class ErrorPatterns {
        <<constant>>
        +AUTH_PATTERNS: list
        +NETWORK_PATTERNS: list
    }

    class FixFunctions {
        +_run_kube_login(cluster): bool
        +_run_vpn_connect(): bool
    }

    class DetectionFunctions {
        +_detect_failure_type(output): tuple
        +_guess_cluster(tool, output): str
    }

    class MemoryLogging {
        +_log_auto_heal_to_memory(tool, type, error, fix)
        +_update_rolling_stats(data, today, week)
        +_cleanup_old_stats(data)
    }

    auto_heal --> ClusterType : uses
    auto_heal --> ErrorPatterns : matches
    auto_heal --> FixFunctions : calls
    auto_heal --> DetectionFunctions : uses
    auto_heal --> MemoryLogging : logs to
```

## Error Detection Patterns

```mermaid
flowchart TB
    subgraph Input[Tool Output]
        OUTPUT[Result string]
    end

    subgraph Detection[Pattern Detection]
        CHECK_ERROR{Has error indicator?}
        CHECK_AUTH{Auth pattern?}
        CHECK_NET{Network pattern?}
    end

    subgraph AuthPatterns[AUTH_PATTERNS]
        A1[unauthorized]
        A2[401/403]
        A3[token expired]
        A4[permission denied]
    end

    subgraph NetPatterns[NETWORK_PATTERNS]
        N1[no route to host]
        N2[connection refused]
        N3[timeout]
        N4[dial tcp]
    end

    subgraph Result[Failure Type]
        AUTH[auth]
        NETWORK[network]
        UNKNOWN[unknown]
        NONE[none]
    end

    OUTPUT --> CHECK_ERROR
    CHECK_ERROR -->|No| NONE
    CHECK_ERROR -->|Yes| CHECK_AUTH
    CHECK_AUTH -->|Yes| AUTH
    CHECK_AUTH -->|No| CHECK_NET
    CHECK_NET -->|Yes| NETWORK
    CHECK_NET -->|No| UNKNOWN

    AuthPatterns -.-> CHECK_AUTH
    NetPatterns -.-> CHECK_NET
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| auto_heal | `server/auto_heal_decorator.py` | Main decorator |
| auto_heal_ephemeral | `server/auto_heal_decorator.py` | Ephemeral preset |
| auto_heal_stage | `server/auto_heal_decorator.py` | Stage preset |
| auto_heal_konflux | `server/auto_heal_decorator.py` | Konflux preset |
| AUTH_PATTERNS | `server/auto_heal_decorator.py` | Auth error patterns |
| NETWORK_PATTERNS | `server/auto_heal_decorator.py` | Network error patterns |

## Fix Actions

| Failure Type | Fix Action | Description |
|--------------|------------|-------------|
| auth | kube_login | Run kube-clean + kube for SSO refresh |
| network | vpn_connect | Connect to Red Hat VPN |

## Memory Logging

Auto-heal events are logged to `memory/learned/tool_failures.yaml`:

```yaml
failures:
  - tool: bonfire_namespace_reserve
    error_type: auth
    error_snippet: "unauthorized..."
    fix_applied: kube_login
    success: true
    timestamp: "2024-01-15T10:30:00"

stats:
  total_failures: 42
  auto_fixed: 38
  daily:
    "2024-01-15": {total: 5, auto_fixed: 4}
  weekly:
    "2024-W03": {total: 12, auto_fixed: 10}
```

## Related Diagrams

- [Tool Registry](./tool-registry.md)
- [Memory Architecture](../06-memory/memory-architecture.md)
- [Auto-Heal Flow](../08-data-flows/incident-response.md)
