# Memory & Auto-Remediation: Visual Summary

> Quick reference diagrams and flowcharts

## Complete System Architecture

```mermaid
flowchart TB
    subgraph User["👤 User / Claude"]
        A[User Action]
        B[Skill Execution]
        C[Direct Tool Call]
    end

    subgraph Tools["🔧 MCP Tools (435)"]
        D[@auto_heal Decorator]
        E[Tool Execution]
        F{Failure?}
    end

    subgraph AutoHeal["🔄 Auto-Heal Layer"]
        G[Detect Pattern]
        H[Auth Fix]
        I[Network Fix]
        J[Log Failure]
    end

    subgraph Skills["⚡ Skill Engine"]
        K[Execute Steps]
        L{Step Fails?}
        M[check_known_issues]
        N[_try_auto_fix]
    end

    subgraph Memory["💾 Memory Files"]
        O[(patterns.yaml)]
        P[(tool_failures.yaml)]
        Q[(current_work.yaml)]
        R[(sessions/daily)]
    end

    A --> B
    A --> C
    B --> K
    C --> D
    D --> E
    E --> F
    F -->|Yes| G
    F -->|No| Return[Return Success]
    G --> H
    G --> I
    H --> J
    I --> J
    J --> P
    J --> E

    K --> L
    L -->|Yes| M
    L -->|No| Continue[Continue]
    M --> O
    M --> N
    N --> H
    N --> I

    B --> Session[memory_session_log]
    Session --> R
    B --> State[Update State]
    State --> Q

    style Memory fill:#f59e0b,stroke:#d97706
    style AutoHeal fill:#10b981,stroke:#059669
    style Tools fill:#3b82f6,stroke:#2563eb
    style Skills fill:#8b5cf6,stroke:#7c3aed
```

## Memory File Ecosystem

```mermaid
graph TD
    subgraph State["📁 state/"]
        A[current_work.yaml<br/>~2KB<br/>Active issues, MRs]
        B[environments.yaml<br/>~3KB<br/>Stage/prod status]
    end

    subgraph Learned["🧠 learned/"]
        C[patterns.yaml<br/>~8KB<br/>20 error patterns]
        D[tool_failures.yaml<br/>~15KB<br/>Last 100 failures]
        E[tool_fixes.yaml<br/>~5KB<br/>Manual fixes]
        F[runbooks.yaml<br/>~10KB<br/>Procedures]
        G[skill_error_fixes.yaml<br/>~5KB<br/>Compute errors]
    end

    subgraph Sessions["📝 sessions/"]
        H[2026-01-09.yaml<br/>~3KB<br/>Today's actions]
        I[2026-01-08.yaml<br/>~3KB<br/>Yesterday]
        J[...<br/>Historical logs]
    end

    K[Skills] -->|read/write| A
    K -->|read/write| B
    K -->|read| C
    K -->|read| F
    K -->|append| H

    L[auto_heal] -->|append| D

    M[learn_pattern] -->|write| C

    N[session_start] -->|read all| State
    N -->|read all| Learned
    N -->|read| H

    style State fill:#3b82f6,stroke:#2563eb,color:#fff
    style Learned fill:#f59e0b,stroke:#d97706,color:#000
    style Sessions fill:#10b981,stroke:#059669,color:#fff
```

## Tool Failure → Auto-Heal → Memory Flow

```mermaid
sequenceDiagram
    participant User
    participant Tool as MCP Tool
    participant Decorator as @auto_heal
    participant Fix as VPN/Kube Login
    participant Memory as tool_failures.yaml

    User->>Tool: bonfire_namespace_reserve()
    Tool->>Decorator: Execute
    Decorator->>Decorator: Run bonfire CLI
    Decorator->>Decorator: Result: "Unauthorized"
    Decorator->>Decorator: _detect_failure_type()<br/>→ "auth"
    Decorator->>Fix: _run_kube_login("ephemeral")
    Fix-->>Decorator: Success
    Decorator->>Memory: _log_auto_heal_to_memory()
    Memory->>Memory: Append to failures[]<br/>Increment stats.auto_fixed
    Memory-->>Decorator: Logged
    Decorator->>Tool: Retry bonfire CLI
    Tool-->>Decorator: Success
    Decorator-->>User: Return namespace

    Note over Memory: failures:<br/>  - tool: bonfire_namespace_reserve<br/>    error_type: auth<br/>    fix_applied: kube_login<br/>    success: true<br/><br/>stats:<br/>  total_failures: 128<br/>  auto_fixed: 99
```

## Skill Failure → Pattern Match → Auto-Fix Flow

```mermaid
sequenceDiagram
    participant User
    participant Skill as Skill Engine
    participant Check as check_known_issues()
    participant Patterns as patterns.yaml
    participant ToolFixes as tool_fixes.yaml
    participant Fix as _try_auto_fix()
    participant Tool as MCP Tool

    User->>Skill: skill_run("test_mr_ephemeral")
    Skill->>Skill: Step 5: kubectl_get_pods
    Skill->>Tool: call_tool("kubectl_get_pods")
    Tool-->>Skill: Error: "No route to host"
    Skill->>Check: check_known_issues(tool, error)
    Check->>Patterns: Read all categories
    Check->>ToolFixes: Read tool_fixes[]
    Patterns-->>Check: Match: network_patterns<br/>"No route to host"
    ToolFixes-->>Check: (no match)
    Check-->>Skill: [{<br/>  source: "network_patterns",<br/>  pattern: "No route to host",<br/>  fix: "Connect to VPN",<br/>  commands: ["vpn_connect()"]<br/>}]
    Skill->>Fix: _try_auto_fix(error, matches)
    Fix->>Fix: Detect "network" type
    Fix->>Fix: Run: nmcli connection up VPN
    Fix-->>Skill: True (success)
    Skill->>Tool: Retry: kubectl_get_pods
    Tool-->>Skill: Success
    Skill->>Skill: Continue to next step
    Skill-->>User: Deployment completed
```

## Memory Access Layers

```mermaid
flowchart LR
    subgraph Claude["🤖 Claude"]
        A[User Request]
    end

    subgraph Layer1["Layer 1: MCP Tools"]
        B[memory_read]
        C[memory_write]
        D[memory_append]
        E[memory_session_log]
    end

    subgraph Layer2["Layer 2: Python Helpers"]
        F[read_memory]
        G[write_memory]
        H[append_to_list]
        I[get_active_issues]
    end

    subgraph Layer3["Layer 3: Direct YAML"]
        J[Path + yaml.safe_load]
        K[with open...]
    end

    subgraph Layer4["Layer 4: Auto-Heal"]
        L[_log_auto_heal_to_memory]
    end

    subgraph Layer5["Layer 5: Skill Engine"]
        M[_check_known_issues_sync]
    end

    subgraph Files["💾 YAML Files"]
        N[(Memory Files)]
    end

    A --> B
    A --> C
    A --> D
    A --> E
    B --> N
    C --> N
    D --> N
    E --> N

    Skills[Skills Compute] --> F
    Skills --> G
    Skills --> H
    Skills --> I
    F --> N
    G --> N
    H --> N
    I --> N

    Memory[Memory Skills] --> J
    Memory --> K
    J --> N
    K --> N

    Tools[All Tools] --> L
    L --> N

    SkillExec[Skill Execution] --> M
    M --> N

    style Layer1 fill:#3b82f6,stroke:#2563eb,color:#fff
    style Layer2 fill:#8b5cf6,stroke:#7c3aed,color:#fff
    style Layer3 fill:#ef4444,stroke:#dc2626,color:#fff
    style Layer4 fill:#10b981,stroke:#059669,color:#fff
    style Layer5 fill:#f59e0b,stroke:#d97706,color:#000
    style Files fill:#64748b,stroke:#475569,color:#fff
```

## Session Start Context Loading

```mermaid
flowchart TD
    A[session_start called] --> B[Read current_work.yaml]
    A --> C[Read environments.yaml]
    A --> D[Read sessions/today.yaml]
    A --> E[Read patterns.yaml]
    A --> F[Get persona state]

    B --> G[Parse active_issues]
    B --> H[Parse open_mrs]
    B --> I[Parse follow_ups]

    C --> J[Parse stage status]
    C --> K[Parse prod status]
    C --> L[Parse ephemeral namespaces]

    D --> M[Parse last 5 actions]

    E --> N[Count patterns by category]

    F --> O[Get loaded modules]

    G --> P{Build Report}
    H --> P
    I --> P
    J --> P
    K --> P
    L --> P
    M --> P
    N --> P
    O --> P

    P --> Q[Return Markdown Report]

    style A fill:#6366f1,stroke:#4f46e5,color:#fff
    style P fill:#f59e0b,stroke:#d97706,color:#000
    style Q fill:#10b981,stroke:#059669,color:#fff
```

## Daily Memory Operations

```mermaid
gantt
    title Daily Memory Operations (~395 total)
    dateFormat X
    axisFormat %s

    section Reads (250)
    check_known_issues (50)     :0, 50
    session_start (5 files)     :50, 55
    Skill compute blocks (195)  :55, 250

    section Writes (145)
    memory_session_log (30)     :250, 280
    auto_heal logging (100)     :280, 380
    Skill state updates (15)    :380, 395
```

## Pattern Matching Decision Tree

```mermaid
flowchart TD
    A[Tool Failure] --> B{Error Type?}

    B -->|"unauthorized"<br/>"401"<br/>"token expired"| C[AUTH Pattern]
    B -->|"no route to host"<br/>"connection refused"| D[NETWORK Pattern]
    B -->|"manifest unknown"<br/>"image not found"| E[REGISTRY Pattern]
    B -->|"output is not a tty"| F[TTY Pattern]
    B -->|Other| G[UNKNOWN Pattern]

    C --> H[Auto-Fix:<br/>kube_login]
    D --> I[Auto-Fix:<br/>vpn_connect]
    E --> J[Manual:<br/>Suggest podman login]
    F --> K[Manual:<br/>Suggest debug_tool]
    G --> L[Manual:<br/>Suggest debug_tool]

    H --> M{Fix Success?}
    I --> M
    J --> N[Return Error]
    K --> N
    L --> N

    M -->|Yes| O[Log to tool_failures.yaml]
    M -->|No| N

    O --> P[Retry Tool]
    P --> Q{Retry Success?}

    Q -->|Yes| R[Return Result]
    Q -->|No| N

    style C fill:#3b82f6,stroke:#2563eb,color:#fff
    style D fill:#3b82f6,stroke:#2563eb,color:#fff
    style E fill:#ef4444,stroke:#dc2626,color:#fff
    style F fill:#ef4444,stroke:#dc2626,color:#fff
    style G fill:#64748b,stroke:#475569,color:#fff
    style H fill:#10b981,stroke:#059669,color:#fff
    style I fill:#10b981,stroke:#059669,color:#fff
    style R fill:#10b981,stroke:#059669,color:#fff
```

## Skill Memory Usage Pattern

```mermaid
flowchart LR
    subgraph Workflow["Workflow Skills (15)"]
        A[start_work]
        B[create_mr]
        C[close_mr]
    end

    subgraph Investigation["Investigation Skills (8)"]
        D[debug_prod]
        E[investigate_alert]
    end

    subgraph Reporting["Reporting Skills (6)"]
        F[standup_summary]
        G[coffee]
        H[beer]
    end

    subgraph Memory["Memory Skills (4)"]
        I[memory_view]
        J[memory_cleanup]
    end

    subgraph Files["Memory Files"]
        K[(current_work)]
        L[(patterns)]
        M[(sessions)]
    end

    A -->|append<br/>update<br/>session_log| K
    A -->|append| M
    B -->|append<br/>session_log| K
    B -->|append| M
    C -->|remove<br/>session_log| K
    C -->|append| M

    D -->|read| L
    D -->|append| M
    E -->|read| L
    E -->|append| M

    F -->|read| K
    F -->|read| M
    G -->|read| K
    G -->|read| M
    H -->|read| K
    H -->|read| M

    I -->|read/write| K
    I -->|read/write| L
    I -->|read/write| M
    J -->|read/write| K
    J -->|read/write| M

    style Workflow fill:#3b82f6,stroke:#2563eb,color:#fff
    style Investigation fill:#8b5cf6,stroke:#7c3aed,color:#fff
    style Reporting fill:#10b981,stroke:#059669,color:#fff
    style Memory fill:#f59e0b,stroke:#d97706,color:#000
```

## Auto-Fix Success Rates

```mermaid
pie title Auto-Remediation Success (127 total failures)
    "Auto-Fixed (77%)" : 98
    "Manual Required (23%)" : 29
```

```mermaid
pie title Failure Types
    "Auth Failures (40%)" : 51
    "Network Failures (30%)" : 38
    "Registry Failures (20%)" : 25
    "Other (10%)" : 13
```

## Memory File Growth Over Time

```mermaid
xychart-beta
    title "Memory File Sizes"
    x-axis [tool_failures, patterns, current_work, sessions/daily, tool_fixes, runbooks]
    y-axis "Size (KB)" 0 --> 16
    bar [15, 8, 2, 3, 5, 10]
```

## Tool Coverage by Module

```mermaid
xychart-beta
    title "Tools with @auto_heal Decorator"
    x-axis [git, gitlab, jira, k8s, bonfire, konflux, prometheus, other]
    y-axis "Tool Count" 0 --> 40
    bar [30, 30, 28, 28, 20, 35, 13, 55]
```

---

## Quick Stats Summary

| Metric | Value |
|--------|-------|
| **Total MCP Tools** | 435 |
| **Tools with @auto_heal** | 435 (100%) |
| **Skills Using Memory** | 70/82 (85%) |
| **Memory Files** | 10+ |
| **Error Pattern Categories** | 6 |
| **Total Error Patterns** | 20 |
| **Daily Memory Operations** | ~395 |
| **Daily Auto-Heal Logs** | ~100 |
| **Daily Session Logs** | ~30 |
| **Auto-Fix Success Rate** | 77% |
| **Auth Fix Success** | ~90% |
| **Network Fix Success** | ~85% |
| **Largest Memory File** | tool_failures.yaml (15KB) |
| **Most-Read File** | patterns.yaml (~75/day) |
| **Most-Written File** | tool_failures.yaml (~100/day) |

---

For complete details, see:
- [MEMORY-COMPLETE-REFERENCE.md](./MEMORY-COMPLETE-REFERENCE.md) - Master index
- [memory-and-auto-remediation.md](./memory-and-auto-remediation.md) - Overview
- [memory-integration-deep-dive.md](./memory-integration-deep-dive.md) - Implementation
