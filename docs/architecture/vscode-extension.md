# 🖥️ VSCode Extension Architecture

This document describes the AI Workflow VSCode extension that provides real-time status indicators, workflow automation, and integration with the MCP server and background daemons.

## Overview

The AA Workflow VSCode extension (`aa_workflow_vscode`) provides:

- **Status bar indicators** - Real-time status for VPN, agent, Slack, issue, environment, MR, and namespace
- **Workflow Explorer** - Sidebar tree view for active work and quick actions
- **Memory Viewer** - Comprehensive view of the memory system
- **Skill Execution Visualization** - Real-time flowchart of skill execution
- **Command Center** - Unified interface for all workflow operations
- **Real-time Updates** - WebSocket and D-Bus integration for live data

## Architecture Diagram

```mermaid
graph TB
    subgraph Extension["VSCode Extension"]
        ACTIVATE[extension.ts<br/>Entry Point]

        subgraph UI["UI Components"]
            STATUSBAR[statusBar.ts<br/>7 Status Items]
            TREE[treeView.ts<br/>Workflow Explorer]
            MEMORY[memoryTab.ts<br/>Memory Viewer]
            CMD[commandCenter.ts<br/>Command Center]
            FLOW[skillFlowchartPanel.ts<br/>Skill Flowchart]
        end

        subgraph Data["Data Layer"]
            PROVIDER[dataProvider.ts<br/>Central Data Source]
            WORKSPACE[workspaceStateProvider.ts<br/>Workspace State]
            WATCHER[skillExecutionWatcher.ts<br/>File Watcher]
        end

        subgraph Comms["Communication"]
            WEBSOCKET[skillWebSocket.ts<br/>WebSocket Client]
            NOTIFY[notifications.ts<br/>D-Bus Monitor]
            DBUS[chatDbusService.ts<br/>D-Bus Service]
        end

        subgraph Utils["Utilities"]
            COMMANDS[commands.ts<br/>Command Registration]
            LOGGER[logger.ts<br/>Centralized Logging]
            PATHS[paths.ts<br/>Path Utilities]
            REFRESH[refreshCoordinator.ts<br/>Refresh Sync]
        end
    end

    subgraph External["External Sources"]
        YAML[(YAML Files)]
        JSON[(JSON State Files)]
        DBUS_BUS[D-Bus Session Bus]
        WS_SERVER[WebSocket Server<br/>Port 9876]
    end

    ACTIVATE --> STATUSBAR
    ACTIVATE --> TREE
    ACTIVATE --> MEMORY
    ACTIVATE --> CMD
    ACTIVATE --> NOTIFY
    ACTIVATE --> WATCHER
    ACTIVATE --> WEBSOCKET

    PROVIDER --> YAML
    PROVIDER --> JSON
    PROVIDER --> DBUS_BUS
    WORKSPACE --> JSON
    WEBSOCKET --> WS_SERVER
    NOTIFY --> DBUS_BUS

    STATUSBAR --> PROVIDER
    TREE --> PROVIDER
    MEMORY --> PROVIDER
    CMD --> WEBSOCKET
    FLOW --> WATCHER

    style ACTIVATE fill:#10b981,stroke:#059669,color:#fff
    style WS_SERVER fill:#6366f1,stroke:#4f46e5,color:#fff
    style DBUS_BUS fill:#f59e0b,stroke:#d97706,color:#fff
```

## Component Details

### Entry Point (`extension.ts`)

**Location**: `src/extension.ts`

**Responsibilities**:
- Extension activation and deactivation lifecycle
- Initialize all UI components (status bar, tree views, memory tab)
- Set up periodic refresh intervals (30 seconds default)
- Register webview serializers for persistent panels
- Listen for workspace state changes
- Coordinate component updates

**Key Exports**:
```typescript
export function activate(context: vscode.ExtensionContext): void
export function deactivate(): void
export function getWorkspaceState(): WorkspaceState | undefined
```

### Status Bar (`statusBar.ts`)

**Location**: `src/statusBar.ts`

**Responsibilities**:
- Create and manage 7 status bar items
- Color-coded status displays with rich tooltips
- Click actions to open external tools

```mermaid
graph LR
    subgraph StatusBar["Status Bar Items"]
        VPN[🔒 VPN<br/>Connected/Disconnected]
        AGENT[🎭 Agent<br/>Current Persona]
        SLACK[💬 Slack<br/>Pending Count]
        ISSUE[📋 Issue<br/>Active Jira]
        ENV[🌍 Environment<br/>Stage/Prod Health]
        MR[🔀 MR<br/>Pipeline Status]
        NS[📦 Namespace<br/>Ephemeral Status]
    end

    VPN --> |click| VPNCMD[Connect VPN]
    ISSUE --> |click| JIRA[Open in Jira]
    MR --> |click| GITLAB[Open in GitLab]
    NS --> |click| BONFIRE[Manage Namespace]
```

**Status Bar Items**:

| Item | Colors | Click Action |
|------|--------|--------------|
| VPN | Green (connected), Red (disconnected) | Connect VPN |
| Agent | Blue (loaded), Gray (none) | Switch persona |
| Slack | Orange (pending), Green (clear) | Open Command Center |
| Issue | Blue (active), Gray (none) | Open in Jira |
| Environment | Green/Yellow/Red (health) | Show env details |
| MR | Green/Red (pipeline) | Open in GitLab |
| Namespace | Blue (active), Gray (none) | Manage namespace |

### Data Provider (`dataProvider.ts`)

**Location**: `src/dataProvider.ts`

**Responsibilities**:
- Central data source for all status information
- Read from YAML memory files
- Query D-Bus for daemon statistics
- Monitor VPN connectivity
- Load workspace state from JSON

**Key Interfaces**:

```typescript
interface WorkflowStatus {
  vpn: VpnStatus;
  agent: string;
  slack: SlackStatus;
  activeIssue: ActiveIssue | null;
  activeMR: ActiveMR | null;
  environment: EnvironmentStatus;
  namespace: EphemeralNamespace | null;
}

interface ActiveIssue {
  key: string;
  summary: string;
  status: string;
  branch?: string;
}

interface ActiveMR {
  id: number;
  title: string;
  status: string;
  pipelineStatus: string;
  url: string;
}

interface EnvironmentStatus {
  stage: 'healthy' | 'degraded' | 'unhealthy';
  prod: 'healthy' | 'degraded' | 'unhealthy';
  lastCheck: Date;
}
```

**Data Sources**:
- `memory/state/current_work.yaml` - Active issues, MRs, branches
- `memory/state/environments.yaml` - Environment health
- `~/.config/aa-workflow/workspace_states.json` - Session state
- D-Bus: `com.aiworkflow.BotSlack` - Slack statistics

### Workflow Explorer (`treeView.ts`)

**Location**: `src/treeView.ts`

**Responsibilities**:
- Hierarchical tree view in sidebar
- Organized sections for different workflow areas
- Clickable shortcuts for common workflows

```mermaid
graph TD
    subgraph TreeView["Workflow Explorer"]
        ROOT[AI Workflow]

        WORK[Active Work]
        WORK --> ISSUE[Current Issue]
        WORK --> BRANCH[Current Branch]
        WORK --> MR[Open MRs]

        ACTIONS[Quick Actions]
        ACTIONS --> START[Start Work]
        ACTIONS --> CREATE[Create MR]
        ACTIONS --> REVIEW[Review PRs]

        NAMESPACES[Namespaces]
        NAMESPACES --> NS1[my-namespace-1]
        NAMESPACES --> NS2[my-namespace-2]

        SKILLS[Skills]
        SKILLS --> DAILY[Daily]
        SKILLS --> DEV[Development]
        SKILLS --> OPS[DevOps]

        ROOT --> WORK
        ROOT --> ACTIONS
        ROOT --> NAMESPACES
        ROOT --> SKILLS
    end
```

**Skill Categories**:
| Category | Skills |
|----------|--------|
| Daily | coffee, beer, standup |
| Development | start_work, create_mr, sync_branch |
| DevOps | deploy_ephemeral, test_ephemeral |
| Jira | create_issue, close_issue, jira_hygiene |
| Memory | memory_view, memory_cleanup |
| Knowledge | knowledge_load, knowledge_scan |

### Memory Viewer (`memoryTab.ts`)

**Location**: `src/memoryTab.ts`

**Responsibilities**:
- Comprehensive view of memory system
- Hierarchical breakdown of memory categories
- Quick actions for memory operations

```mermaid
graph TD
    subgraph MemoryView["Memory Viewer"]
        ROOT[Memory System]

        STATE[State]
        STATE --> ISSUES[Active Issues]
        STATE --> BRANCHES[Branches]
        STATE --> MRS[Merge Requests]

        ENVS[Environments]
        ENVS --> STAGE[Stage Health]
        ENVS --> PROD[Prod Health]

        SESSIONS[Sessions]
        SESSIONS --> S1[Session 1]
        SESSIONS --> S2[Session 2]

        LEARNED[Learned Patterns]
        LEARNED --> PATTERNS[Error Patterns]
        LEARNED --> FAILURES[Tool Failures]
        LEARNED --> FIXES[Tool Fixes]

        KNOWLEDGE[Knowledge Base]
        KNOWLEDGE --> DEV[Developer]
        KNOWLEDGE --> DEVOPS[DevOps]

        STATS[Statistics]

        ROOT --> STATE
        ROOT --> ENVS
        ROOT --> SESSIONS
        ROOT --> LEARNED
        ROOT --> KNOWLEDGE
        ROOT --> STATS
    end
```

### Command Center (`commandCenter.ts`)

**Location**: `src/commandCenter.ts`

**Responsibilities**:
- Unified webview panel for all operations
- Tab-based interface
- Real-time updates via WebSocket
- Slack message approval workflow

**Tabs**:

| Tab | Purpose |
|-----|---------|
| Slack Messages | Pending approvals, message history |
| Running Skills | Active skill executions |
| MR Status | Open MRs with pipeline status |
| Namespaces | Ephemeral namespace management |

```mermaid
sequenceDiagram
    participant User
    participant CommandCenter
    participant WebSocket
    participant Daemon as Slack Daemon

    User->>CommandCenter: Open panel
    CommandCenter->>WebSocket: Connect
    CommandCenter->>Daemon: Get pending messages
    Daemon-->>CommandCenter: Message list

    loop Real-time updates
        WebSocket-->>CommandCenter: Skill progress
        Daemon-->>CommandCenter: New message signal
        CommandCenter->>CommandCenter: Update UI
    end

    User->>CommandCenter: Approve message
    CommandCenter->>Daemon: approve_message()
    Daemon-->>CommandCenter: Success
    CommandCenter->>CommandCenter: Update UI
```

### Skill Execution Watcher (`skillExecutionWatcher.ts`)

**Location**: `src/skillExecutionWatcher.ts`

**Responsibilities**:
- Watch `skill_execution.json` for execution events
- Track multiple concurrent executions
- Dispatch events to flowchart and command center

**Event Types**:

```typescript
interface SkillExecutionEvent {
  execution_id: string;
  skill_name: string;
  status: 'running' | 'success' | 'failed';
  current_step?: string;
  steps: StepProgress[];
  started_at: string;
  completed_at?: string;
  error?: string;
}

interface StepProgress {
  id: string;
  name: string;
  status: 'pending' | 'running' | 'success' | 'failed' | 'skipped';
  duration_ms?: number;
  output?: string;
}
```

### WebSocket Client (`skillWebSocket.ts`)

**Location**: `src/skillWebSocket.ts`

**Responsibilities**:
- Connect to MCP server WebSocket (port 9876)
- Real-time skill execution updates
- Handle confirmations and auto-heal events
- Automatic reconnection with exponential backoff

```mermaid
stateDiagram-v2
    [*] --> Disconnected

    Disconnected --> Connecting: connect()
    Connecting --> Connected: WebSocket open
    Connecting --> Disconnected: Connection failed

    Connected --> Disconnected: WebSocket close
    Connected --> Connected: Receive message

    state Connected {
        [*] --> Idle
        Idle --> Processing: skill_started
        Processing --> Processing: step_completed
        Processing --> Idle: skill_completed
        Processing --> AwaitingConfirmation: confirmation_required
        AwaitingConfirmation --> Processing: confirmation_answered
    }

    Disconnected --> Connecting: Reconnect (backoff)
```

**Message Types**:

| Type | Direction | Purpose |
|------|-----------|---------|
| `skill_started` | Server → Client | Skill execution began |
| `skill_updated` | Server → Client | Step progress update |
| `skill_completed` | Server → Client | Skill finished |
| `confirmation_required` | Server → Client | User confirmation needed |
| `confirmation_answer` | Client → Server | User's response |
| `auto_heal_triggered` | Server → Client | Auto-heal in progress |

### Notifications (`notifications.ts`)

**Location**: `src/notifications.ts`

**Responsibilities**:
- Monitor workflow status changes
- Show toast notifications
- D-Bus signal monitoring for Slack events
- Deduplication of similar notifications

```mermaid
flowchart TD
    A[Status Change] --> B{Change Type}

    B -->|Alert| C[Show Warning]
    B -->|Pipeline Fail| D[Show Error]
    B -->|Pipeline Success| E[Show Info]
    B -->|Slack Message| F[Show Info with Actions]

    C --> G{Already Shown?}
    D --> G
    E --> G
    F --> G

    G -->|Yes| H[Skip]
    G -->|No| I[Display Toast]
    I --> J[Record in State]
```

**D-Bus Signal Monitoring**:

```bash
# Signals monitored from com.aiworkflow.BotSlack
MessageReceived(channel_id, user, text)
MessageProcessed(message_id, result)
PendingApproval(message_id, channel, text)
```

### Command Registration (`commands.ts`)

**Location**: `src/commands.ts`

**Responsibilities**:
- Register all command palette commands
- Dynamic skill loading from disk
- Agent/persona switching
- Clipboard-based message sending

**Registered Commands**:

| Command | Description |
|---------|-------------|
| `aaWorkflow.runSkill` | Open skill picker |
| `aaWorkflow.loadAgent` | Switch persona |
| `aaWorkflow.openJira` | Open current issue |
| `aaWorkflow.openGitLab` | Open current MR |
| `aaWorkflow.connectVpn` | Connect to VPN |
| `aaWorkflow.refreshStatus` | Refresh all status |
| `aaWorkflow.showMemory` | Open memory viewer |
| `aaWorkflow.showCommandCenter` | Open command center |

### Skill Flowchart (`skillFlowchartPanel.ts`)

**Location**: `src/skillFlowchartPanel.ts`

**Responsibilities**:
- Webview panel for skill visualization
- Step-by-step progress display
- Branching logic visualization
- Timing and error details

```mermaid
graph TD
    subgraph FlowchartPanel["Skill Flowchart View"]
        HEADER[Skill: deploy_ephemeral]

        STEP1[Step 1: Check VPN<br/>✅ 0.5s]
        STEP2[Step 2: Reserve Namespace<br/>⏳ Running...]
        STEP3[Step 3: Deploy App<br/>⏸️ Pending]
        STEP4[Step 4: Run Tests<br/>⏸️ Pending]

        STEP1 --> STEP2
        STEP2 --> STEP3
        STEP3 --> STEP4

        HEADER --> STEP1
    end
```

### Workspace State Provider (`workspaceStateProvider.ts`)

**Location**: `src/workspaceStateProvider.ts`

**Responsibilities**:
- Monitor workspace state file changes
- Provide current workspace context
- Handle per-session tracking
- Emit change events

**State File**: `~/.config/aa-workflow/workspace_states.json`

```typescript
interface WorkspaceState {
  workspace_uri: string;
  persona: string;
  project: string;
  active_issue?: string;
  active_branch?: string;
  sessions: ChatSession[];
}

interface ChatSession {
  session_id: string;
  name: string;
  created_at: string;
  updated_at: string;
  persona: string;
}
```

## Data Flow

### Status Bar Update Flow

```mermaid
sequenceDiagram
    participant Timer as Refresh Timer
    participant Provider as DataProvider
    participant YAML as YAML Files
    participant DBus as D-Bus
    participant StatusBar as StatusBar

    Timer->>Provider: refresh()

    par Read data sources
        Provider->>YAML: Read current_work.yaml
        Provider->>YAML: Read environments.yaml
        Provider->>DBus: Query BotSlack stats
    end

    YAML-->>Provider: Work state
    DBus-->>Provider: Slack stats

    Provider->>Provider: Build WorkflowStatus
    Provider-->>StatusBar: Status update event
    StatusBar->>StatusBar: Update 7 items
```

### Skill Execution Flow

```mermaid
sequenceDiagram
    participant User
    participant Extension
    participant WebSocket
    participant MCP as MCP Server
    participant Flowchart

    User->>Extension: Run skill
    Extension->>MCP: skill_run()
    MCP->>WebSocket: skill_started
    WebSocket->>Extension: Event
    Extension->>Flowchart: Show panel

    loop For each step
        MCP->>WebSocket: step_completed
        WebSocket->>Extension: Event
        Extension->>Flowchart: Update step
    end

    MCP->>WebSocket: skill_completed
    WebSocket->>Extension: Event
    Extension->>Flowchart: Show complete
```

## Configuration

### Extension Settings

Configured in `package.json`:

```json
{
  "aaWorkflow.refreshInterval": {
    "type": "number",
    "default": 30,
    "description": "Status refresh interval in seconds"
  },
  "aaWorkflow.showVpnStatus": {
    "type": "boolean",
    "default": true,
    "description": "Show VPN status in status bar"
  },
  "aaWorkflow.showAgentStatus": {
    "type": "boolean",
    "default": true,
    "description": "Show agent status in status bar"
  },
  "aaWorkflow.defaultAgent": {
    "type": "string",
    "default": "developer",
    "description": "Default agent to load"
  },
  "aaWorkflow.autoSendToChat": {
    "type": "boolean",
    "default": false,
    "description": "Auto-send commands to Cursor chat"
  }
}
```

### Keybindings

| Keybinding | Command |
|------------|---------|
| `Ctrl+Shift+1` | Open Command Center |
| `Ctrl+Shift+2` | Run Skill |
| `Ctrl+Shift+3` | Refresh Status |

## Building and Development

### Prerequisites

- Node.js 18+
- VSCode 1.85+

### Build Commands

```bash
cd extensions/aa_workflow_vscode

# Install dependencies
npm install

# Build
npm run compile

# Watch mode
npm run watch

# Package extension
npm run package
```

### Testing

```bash
# Run tests
npm test

# Debug in Extension Host
# Press F5 in VSCode
```

## File Structure

```
extensions/aa_workflow_vscode/
├── package.json              # Extension manifest
├── tsconfig.json             # TypeScript config
├── src/
│   ├── extension.ts          # Entry point
│   ├── statusBar.ts          # Status bar items
│   ├── dataProvider.ts       # Data source
│   ├── treeView.ts           # Workflow Explorer
│   ├── memoryTab.ts          # Memory viewer
│   ├── commands.ts           # Command registration
│   ├── notifications.ts      # Toast notifications
│   ├── skillExecutionWatcher.ts  # File watcher
│   ├── skillWebSocket.ts     # WebSocket client
│   ├── skillFlowchartPanel.ts    # Flowchart webview
│   ├── commandCenter.ts      # Command Center panel
│   ├── workspaceStateProvider.ts # Workspace state
│   ├── chatDbusService.ts    # D-Bus service
│   ├── refreshCoordinator.ts # Refresh sync
│   ├── logger.ts             # Logging
│   ├── paths.ts              # Path utilities
│   └── chatUtils.ts          # Chat utilities
├── media/                    # Icons and images
└── out/                      # Compiled JavaScript
```

## Dependencies

| Package | Purpose |
|---------|---------|
| `vscode` | VSCode API |
| `ws` | WebSocket client |
| `dbus-next` | D-Bus communication |
| `js-yaml` | YAML parsing |

## See Also

- [Architecture Overview](./README.md) - System overview
- [Daemon Architecture](./daemons.md) - Background services
- [State Management](./state-management.md) - Persistence patterns
- [Development Guide](../DEVELOPMENT.md) - Contributing guidelines
