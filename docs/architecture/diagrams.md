# Architecture Diagrams

> Detailed visual diagrams of system components, data flows, and interactions

Comprehensive technical architecture of the AI Workflow system.

## High-Level Architecture

```mermaid
graph TB
    subgraph UserLayer["User Interface Layer"]
        USER[👤 Developer]
        CURSOR[Cursor IDE]
        CLAUDE[Claude Code CLI]
        VSCODE[VSCode Extension]
    end

    subgraph CoreLayer["MCP Server Core"]
        MCP[FastMCP Server]
        PERSONA[Persona Loader]
        SKILL[Skill Engine]
        REGISTRY[Tool Registry]
        STATE[State Manager]
        CONFIG[Config Manager]
    end

    subgraph ToolLayer["Tool Modules Layer"]
        subgraph DevTools["Development"]
            GIT[aa_git]
            GITLAB[aa_gitlab]
            JIRA[aa_jira]
        end
        subgraph InfraTools["Infrastructure"]
            K8S[aa_k8s]
            BONFIRE[aa_bonfire]
            KONFLUX[aa_konflux]
        end
        subgraph CommTools["Communication"]
            SLACK[aa_slack]
            MEET[aa_meet_bot]
            GCAL[aa_google_calendar]
        end
    end

    subgraph DaemonLayer["Background Services"]
        DBUS[D-Bus IPC]
        SLACK_D[Slack Daemon]
        SPRINT_D[Sprint Daemon]
        MEET_D[Meet Daemon]
        VIDEO_D[Video Daemon]
        SESSION_D[Session Daemon]
        CRON_D[Cron Daemon]
    end

    subgraph PersistLayer["Persistence Layer"]
        YAML[(YAML Memory)]
        JSON[(JSON Config/State)]
        SQLITE[(SQLite DBs)]
        VECTOR[(Vector Index)]
    end

    subgraph ExternalLayer["External Services"]
        JIRA_API[Jira API]
        GITLAB_API[GitLab API]
        K8S_API[Kubernetes API]
        SLACK_API[Slack API]
        GOOGLE_API[Google APIs]
    end

    USER --> CURSOR
    USER --> CLAUDE
    CURSOR --> MCP
    CLAUDE --> MCP
    CURSOR --> VSCODE

    MCP --> PERSONA
    MCP --> SKILL
    MCP --> REGISTRY
    MCP --> STATE
    MCP --> CONFIG

    REGISTRY --> DevTools
    REGISTRY --> InfraTools
    REGISTRY --> CommTools

    DevTools --> JIRA_API
    DevTools --> GITLAB_API
    InfraTools --> K8S_API
    CommTools --> SLACK_API
    CommTools --> GOOGLE_API

    DBUS --> SLACK_D
    DBUS --> SPRINT_D
    DBUS --> MEET_D
    DBUS --> VIDEO_D
    DBUS --> SESSION_D
    DBUS --> CRON_D

    STATE --> JSON
    SKILL --> YAML
    MEET_D --> SQLITE
    REGISTRY --> VECTOR

    VSCODE --> DBUS
    VSCODE --> MCP
```

## Component Interactions

### Request Flow

```mermaid
sequenceDiagram
    participant User
    participant Cursor as Cursor IDE
    participant MCP as MCP Server
    participant Persona as Persona Loader
    participant Skill as Skill Engine
    participant Tool as Tool Module
    participant External as External API
    participant Memory as Memory System

    User->>Cursor: /start-work AAP-12345
    Cursor->>MCP: Call skill_run("start_work", ...)
    MCP->>Skill: Execute skill
    Skill->>Persona: Ensure developer persona
    Persona-->>Skill: Tools loaded

    loop For each step
        Skill->>Tool: Execute tool
        Tool->>External: API call
        External-->>Tool: Response
        Tool-->>Skill: Result
    end

    Skill->>Memory: Update current_work.yaml
    Memory-->>Skill: Saved
    Skill-->>MCP: Skill result
    MCP-->>Cursor: Formatted output
    Cursor-->>User: Display result
```

### Auto-Heal Flow

```mermaid
stateDiagram-v2
    [*] --> Execute: Tool called
    Execute --> Success: No error
    Execute --> DetectFailure: Error in output

    DetectFailure --> AuthFailure: Token expired, 401, 403
    DetectFailure --> NetworkFailure: No route, timeout
    DetectFailure --> OtherFailure: Unknown error

    AuthFailure --> KubeLogin: Run oc login
    NetworkFailure --> VPNConnect: Connect VPN
    OtherFailure --> CheckPatterns: Check memory patterns

    KubeLogin --> Retry: Auth refreshed
    VPNConnect --> Retry: VPN connected
    CheckPatterns --> ApplyFix: Pattern matched
    CheckPatterns --> ReportError: No pattern

    ApplyFix --> Retry
    Retry --> Execute: Retry tool
    Retry --> ReportError: Max retries

    Success --> LogSuccess: Log to memory
    ReportError --> LogFailure: Log to memory
    LogSuccess --> [*]
    LogFailure --> [*]
```

## Server Components

```mermaid
classDiagram
    class FastMCP {
        +tools: Dict
        +register_tool()
        +call_tool()
        +list_tools()
    }

    class PersonaLoader {
        +current_persona: str
        +loaded_modules: List
        +load_persona(name)
        +unload_current()
        +get_tools()
    }

    class SkillEngine {
        +skills: Dict
        +execute(skill_name, inputs)
        +validate_skill()
        +handle_error()
    }

    class ToolRegistry {
        +server: FastMCP
        +registered: List
        +tool() decorator
        +count()
    }

    class StateManager {
        +state_file: Path
        +get(key)
        +set(key, value)
        +flush()
    }

    class ConfigManager {
        +config_file: Path
        +get(section)
        +update_section()
        +flush()
    }

    class AutoHealDecorator {
        +cluster: str
        +max_retries: int
        +detect_failure()
        +apply_fix()
        +log_to_memory()
    }

    FastMCP --> PersonaLoader
    FastMCP --> SkillEngine
    FastMCP --> ToolRegistry
    FastMCP --> StateManager
    FastMCP --> ConfigManager
    ToolRegistry --> AutoHealDecorator
```

## Data Flow Architecture

```mermaid
flowchart LR
    subgraph Input["Input Sources"]
        CMD[Slash Commands]
        CHAT[Chat Messages]
        HOOK[Webhooks]
        SCHEDULE[Scheduled Jobs]
    end

    subgraph Processing["Processing"]
        PARSE[Parse Intent]
        ROUTE[Route to Skill/Tool]
        EXECUTE[Execute]
        HEAL[Auto-Heal if needed]
    end

    subgraph Output["Output Targets"]
        RESPONSE[Chat Response]
        MEMORY[Memory Update]
        STATE[State Update]
        NOTIFY[Notifications]
    end

    CMD --> PARSE
    CHAT --> PARSE
    HOOK --> PARSE
    SCHEDULE --> PARSE

    PARSE --> ROUTE
    ROUTE --> EXECUTE
    EXECUTE --> HEAL
    HEAL --> EXECUTE

    EXECUTE --> RESPONSE
    EXECUTE --> MEMORY
    EXECUTE --> STATE
    EXECUTE --> NOTIFY
```

## Daemon Architecture

```mermaid
graph TB
    subgraph Control["Control Layer"]
        SYSTEMD[systemd]
        HEALTH[health_check.py]
        CONTROL[service_control.py]
    end

    subgraph DBus["D-Bus Layer"]
        BUS[System Bus]
        INTERFACE[com.redhat.ai.workflow]
    end

    subgraph Daemons["Daemon Processes"]
        SLACK[Slack Daemon<br/>Real-time messages]
        SPRINT[Sprint Daemon<br/>Jira automation]
        MEET[Meet Daemon<br/>Meeting bot]
        VIDEO[Video Daemon<br/>Virtual camera]
        SESSION[Session Daemon<br/>IDE sync]
        CRON[Cron Daemon<br/>Scheduled jobs]
    end

    subgraph External["External Connections"]
        SLACK_WS[Slack WebSocket]
        JIRA_API[Jira API]
        MEET_WS[Meet WebRTC]
        V4L2[V4L2 Loopback]
        CURSOR_DB[Cursor SQLite]
        SKILLS[Skill Engine]
    end

    SYSTEMD --> SLACK
    SYSTEMD --> SPRINT
    SYSTEMD --> MEET
    SYSTEMD --> VIDEO
    SYSTEMD --> SESSION
    SYSTEMD --> CRON

    HEALTH --> SLACK
    HEALTH --> SPRINT
    HEALTH --> MEET
    HEALTH --> VIDEO
    HEALTH --> SESSION
    HEALTH --> CRON

    CONTROL --> SYSTEMD
    CONTROL --> BUS

    SLACK --> BUS
    SPRINT --> BUS
    MEET --> BUS
    VIDEO --> BUS
    SESSION --> BUS
    CRON --> BUS

    SLACK --> SLACK_WS
    SPRINT --> JIRA_API
    MEET --> MEET_WS
    VIDEO --> V4L2
    SESSION --> CURSOR_DB
    CRON --> SKILLS
```

## Memory Architecture

```mermaid
graph TB
    subgraph MemorySystem["Memory System"]
        subgraph State["State Layer"]
            CURRENT[current_work.yaml<br/>Active issues, MRs]
            ENV[environments.yaml<br/>Stage/prod status]
            SHARED[shared_context.yaml<br/>Cross-session data]
        end

        subgraph Learned["Learning Layer"]
            PATTERNS[patterns.yaml<br/>Error patterns]
            FIXES[tool_fixes.yaml<br/>Known solutions]
            FAILURES[tool_failures.yaml<br/>Failure history]
        end

        subgraph Knowledge["Knowledge Layer"]
            PERSONAS[personas/developer/...]
            PROJECTS[project.yaml files]
        end

        subgraph Sessions["Session Layer"]
            DAILY[sessions/YYYY-MM-DD.yaml]
            PROJECTS_STATE[projects/*/current_work.yaml]
        end
    end

    subgraph Access["Access Methods"]
        MCP_TOOLS[MCP Memory Tools]
        PYTHON[Python Helpers]
        DIRECT[Direct YAML]
        AUTO_HEAL[Auto-Heal Logger]
    end

    MCP_TOOLS --> State
    MCP_TOOLS --> Sessions
    PYTHON --> State
    PYTHON --> Learned
    DIRECT --> Knowledge
    AUTO_HEAL --> Failures

    AUTO_HEAL --> PATTERNS
```

## Skill Execution State Machine

```mermaid
stateDiagram-v2
    [*] --> Init: skill_run()
    Init --> LoadSkill: Parse YAML
    LoadSkill --> ValidateInputs: Check required

    ValidateInputs --> ExecuteStep: First step
    ValidateInputs --> Error: Missing input

    state ExecuteStep {
        [*] --> CheckCondition
        CheckCondition --> RunTool: condition=true
        CheckCondition --> Skip: condition=false
        RunTool --> HandleResult
        Skip --> HandleResult
        HandleResult --> [*]
    }

    ExecuteStep --> NextStep: Step complete
    NextStep --> ExecuteStep: More steps
    NextStep --> Complete: No more steps

    ExecuteStep --> RetryStep: on_error=retry
    RetryStep --> ExecuteStep: Retry limit
    RetryStep --> Error: Max retries

    ExecuteStep --> SkipStep: on_error=continue
    SkipStep --> NextStep

    Complete --> LogSession: Log to memory
    LogSession --> [*]: Return result

    Error --> LogError: Log failure
    LogError --> [*]: Return error
```

## WebSocket Protocol

```mermaid
sequenceDiagram
    participant Extension as VSCode Extension
    participant WS as WebSocket Server
    participant MCP as MCP Server
    participant Daemon as Daemons

    Extension->>WS: Connect ws://localhost:8765
    WS-->>Extension: Connected

    loop Heartbeat
        Extension->>WS: ping
        WS-->>Extension: pong
    end

    MCP->>WS: skill_started {skill, inputs}
    WS->>Extension: skill_started
    Extension->>Extension: Update UI

    MCP->>WS: step_progress {step, status}
    WS->>Extension: step_progress

    MCP->>WS: skill_completed {result}
    WS->>Extension: skill_completed

    Daemon->>WS: daemon_status {daemon, status}
    WS->>Extension: daemon_status
    Extension->>Extension: Update status bar
```

## Deployment Architecture

```mermaid
graph TB
    subgraph Development["Development Machine"]
        subgraph IDE["IDE Layer"]
            CURSOR[Cursor IDE]
            VSCODE_EXT[VSCode Extension]
        end

        subgraph Services["Background Services"]
            MCP[MCP Server<br/>stdio]
            DAEMONS[6 Daemons<br/>systemd]
        end

        subgraph Storage["Local Storage"]
            CONFIG[~/.config/aa-workflow/]
            MEMORY[memory/]
            VECTOR[.lancedb/]
        end
    end

    subgraph External["External Services"]
        GITLAB[GitLab]
        JIRA[Jira]
        K8S[Kubernetes Clusters]
        SLACK[Slack]
        GOOGLE[Google APIs]
    end

    CURSOR --> MCP
    VSCODE_EXT --> DAEMONS
    MCP --> Storage
    DAEMONS --> Storage
    MCP --> External
    DAEMONS --> External
```

## Security Model

```mermaid
graph TB
    subgraph Credentials["Credential Storage"]
        KEYRING[System Keyring]
        BITWARDEN[Bitwarden CLI]
        ENV[Environment Variables]
        TOKEN[OAuth Tokens]
    end

    subgraph Tools["Tool Access"]
        JIRA_TOOL[Jira Tools] --> JIRA_PAT[JIRA_JPAT]
        GITLAB_TOOL[GitLab Tools] --> GITLAB_TOKEN[GITLAB_TOKEN]
        K8S_TOOL[K8s Tools] --> KUBECONFIG[kubeconfig files]
        SLACK_TOOL[Slack Tools] --> SLACK_TOKEN[SLACK_TOKEN]
        GOOGLE_TOOL[Google Tools] --> OAUTH[OAuth2 Token]
    end

    subgraph Refresh["Token Refresh"]
        AUTO_HEAL[Auto-Heal] --> KUBE_LOGIN[kube_login]
        AUTO_HEAL --> VPN_CONNECT[vpn_connect]
        OAUTH_FLOW[OAuth Flow] --> TOKEN
    end

    KEYRING --> JIRA_PAT
    KEYRING --> GITLAB_TOKEN
    ENV --> KUBECONFIG
    KEYRING --> SLACK_TOKEN
    TOKEN --> OAUTH
```

## See Also

- [Server Components](./server-components.md) - Detailed server architecture
- [Skill Engine](./skill-engine.md) - Skill execution details
- [Memory System](./memory-system.md) - Memory architecture
- [Daemons](./daemons.md) - Background services
- [Auto-Heal](./auto-heal.md) - Self-healing system
- [WebSocket Protocol](./websocket-protocol.md) - Real-time communication
