# VS Code Extension: Chats Tab Requirements

> **Goal:** Add a "Chats" tab to the Command Center that displays all known chat sessions, their personas, tools, and contextual information. This provides visibility into per-workspace state managed by the MCP server.

## Background

The VS Code extension currently has these tabs in the Command Center:
- **Overview** - Agent stats, current work, environments
- **Skills** - Skill browser + real-time execution flowchart
- **Services** - Slack bot, MCP server, D-Bus explorer
- **Memory** - Memory browser, session logs, patterns
- **Cron** - Scheduled job management

With the per-workspace context feature (see `per-workspace-context.md`), the MCP server will track independent state per workspace. The extension needs a way to visualize this.

## Requirements

### 1. Chats Tab in Command Center

Add a new "Chats" tab that shows:

```
┌─────────────────────────────────────────────────────────────────────┐
│  CHATS                                                    [Refresh] │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ 🟢 /home/user/src/automation-analytics-backend              │   │
│  │    Project: automation-analytics-backend                     │   │
│  │    Persona: developer                                        │   │
│  │    Issue: AAP-61661 (In Progress)                           │   │
│  │    Branch: AAP-61661-pytest-xdist                           │   │
│  │    Tools: 78 loaded (git, gitlab, jira, workflow)           │   │
│  │    Started: 2 hours ago                                      │   │
│  │    [Switch Persona ▼] [View Tools] [Clear Context]          │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ 🟡 /home/user/src/redhat-ai-workflow                        │   │
│  │    Project: redhat-ai-workflow                               │   │
│  │    Persona: devops                                           │   │
│  │    Issue: None                                               │   │
│  │    Branch: main                                              │   │
│  │    Tools: 74 loaded (k8s, bonfire, quay, workflow)          │   │
│  │    Started: 30 minutes ago                                   │   │
│  │    [Switch Persona ▼] [View Tools] [Clear Context]          │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ ⚪ /home/user/src/app-interface                              │   │
│  │    Project: app-interface                                    │   │
│  │    Persona: (default)                                        │   │
│  │    Issue: None                                               │   │
│  │    Tools: Not loaded (inactive)                              │   │
│  │    Last active: 3 days ago                                   │   │
│  │    [Activate] [Remove]                                       │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 2. Chat State Indicators

| Indicator | Meaning |
|-----------|---------|
| 🟢 Green | Active workspace (current window) |
| 🟡 Yellow | Active in another window |
| ⚪ Gray | Inactive (no recent activity) |
| 🔴 Red | Error state (tools failed to load) |

### 3. Per-Chat Information Display

For each chat/workspace, show:

| Field | Source | Description |
|-------|--------|-------------|
| Workspace Path | `WorkspaceState.workspace_uri` | Full path to workspace |
| Project | `WorkspaceState.project` | Detected project from config.json |
| Persona | `WorkspaceState.persona` | Active persona (developer, devops, etc.) |
| Issue | `WorkspaceState.issue_key` | Active Jira issue |
| Branch | `WorkspaceState.branch` | Current git branch |
| Tools | `WorkspaceState.active_tools` | Count and list of loaded tool modules |
| Started | `WorkspaceState.started_at` | When session started |
| Last Activity | Computed | Time since last tool call |

### 4. Actions Per Chat

| Action | Description |
|--------|-------------|
| **Switch Persona** | Dropdown to change persona for that workspace |
| **View Tools** | Expand to show all loaded tools |
| **Clear Context** | Reset workspace state (project, issue, branch) |
| **Activate** | For inactive workspaces, load tools |
| **Remove** | Remove workspace from tracking |

### 5. Tool Details Panel

When "View Tools" is clicked, show expandable panel:

```
┌─────────────────────────────────────────────────────────────────┐
│ Tools for automation-analytics-backend (78 total)               │
├─────────────────────────────────────────────────────────────────┤
│ ▼ git (12 tools)                                                │
│   • git_status       • git_commit      • git_push              │
│   • git_branch_create • git_checkout   • git_log               │
│   ...                                                           │
│ ▼ gitlab (15 tools)                                             │
│   • gitlab_mr_create  • gitlab_mr_view  • gitlab_ci_status     │
│   ...                                                           │
│ ▼ jira (10 tools)                                               │
│   • jira_view_issue   • jira_set_status • jira_add_comment     │
│   ...                                                           │
│ ▼ workflow (41 tools)                                           │
│   • session_start     • skill_run       • memory_read          │
│   ...                                                           │
└─────────────────────────────────────────────────────────────────┘
```

### 6. NPU Tool Filtering Status

Show NPU filtering status per workspace:

```
┌─────────────────────────────────────────────────────────────────┐
│ NPU Tool Filtering                                              │
├─────────────────────────────────────────────────────────────────┤
│ Status: ✅ Active (qwen2.5:0.5b on NPU)                         │
│ Cache: 12 entries (TTL: 5 min)                                  │
│ Last filter: "deploy MR to ephemeral" → k8s, bonfire, quay     │
│                                                                 │
│ Baseline tools (always loaded):                                 │
│   developer: jira_read, gitlab_mr_read, gitlab_ci              │
│                                                                 │
│ [Clear Cache] [Disable Filtering]                               │
└─────────────────────────────────────────────────────────────────┘
```

### 7. Data Source: MCP Server API

The extension needs to communicate with the MCP server to get workspace state. Options:

#### Option A: File-Based (Recommended for MVP)
Write workspace state to a JSON file that the extension watches:

```json
// ~/.config/aa-workflow/workspace_states.json
{
  "workspaces": {
    "file:///home/user/src/backend": {
      "workspace_uri": "file:///home/user/src/backend",
      "project": "automation-analytics-backend",
      "persona": "developer",
      "issue_key": "AAP-61661",
      "branch": "AAP-61661-pytest-xdist",
      "active_tools": ["git", "gitlab", "jira", "workflow"],
      "started_at": "2025-01-18T10:30:00Z",
      "last_activity": "2025-01-18T12:45:00Z",
      "tool_count": 78
    }
  },
  "npu_status": {
    "enabled": true,
    "model": "qwen2.5:0.5b",
    "instance": "npu",
    "cache_size": 12,
    "cache_ttl": 300
  },
  "last_updated": "2025-01-18T12:45:30Z"
}
```

#### Option B: HTTP API
Add HTTP endpoint to MCP server (already has web mode):

```
GET /api/workspaces
GET /api/workspaces/{workspace_uri}
POST /api/workspaces/{workspace_uri}/persona
DELETE /api/workspaces/{workspace_uri}
```

#### Option C: D-Bus Interface
Add D-Bus methods (similar to Slack daemon):

```
com.aiworkflow.MCPServer.GetWorkspaces() -> JSON
com.aiworkflow.MCPServer.SetPersona(workspace_uri, persona) -> bool
com.aiworkflow.MCPServer.ClearContext(workspace_uri) -> bool
```

### 8. Tree View Integration

Also add workspace info to the existing Tree View sidebar:

```
WORKFLOW EXPLORER
├── 📁 Current Workspace
│   ├── Project: automation-analytics-backend
│   ├── Persona: developer
│   ├── Issue: AAP-61661
│   └── Tools: 78 loaded
├── ⚡ Quick Actions
│   └── ...
├── 📋 Active Work
│   └── ...
└── ...
```

### 9. Status Bar Enhancement

Update status bar to show workspace-specific info:

```
[$(robot) Developer] [$(issues) AAP-61661] [$(git-branch) AAP-61661-pytest-xdist] ...
```

When switching Cursor windows, the status bar should update to reflect that workspace's state.

## Implementation Plan

### Phase 1: MCP Server State Export (Backend)
1. Add `WorkspaceStateExporter` class to MCP server
2. Write state to `~/.config/aa-workflow/workspace_states.json`
3. Update on every state change (debounced)
4. Include NPU filtering status

### Phase 2: Extension Data Provider
1. Add `WorkspaceStateProvider` class to extension
2. Watch `workspace_states.json` for changes
3. Parse and expose workspace data

### Phase 3: Chats Tab UI
1. Add "Chats" tab to Command Center
2. Implement workspace card component
3. Add persona switcher dropdown
4. Add tool details expandable panel

### Phase 4: Actions Integration
1. Implement "Switch Persona" action (calls MCP tool)
2. Implement "Clear Context" action
3. Implement "View Tools" expansion
4. Add NPU status panel

### Phase 5: Tree View & Status Bar
1. Add "Current Workspace" section to tree view
2. Update status bar to be workspace-aware
3. Handle window focus changes

## UI/UX Considerations

### Color Scheme
- Use existing VS Code theme colors
- Match Command Center styling
- Use codicons for icons

### Responsiveness
- File watcher for real-time updates
- Debounce rapid state changes
- Show loading states

### Accessibility
- Keyboard navigation for all actions
- Screen reader friendly labels
- High contrast support

## Dependencies

- Per-workspace context implementation (see `per-workspace-context.md`)
- MCP server state export mechanism
- File watcher in extension

## Success Criteria

1. ✅ Chats tab shows all known workspaces
2. ✅ Each workspace shows correct project, persona, tools
3. ✅ Persona can be switched from the UI
4. ✅ Tool list is accurate and expandable
5. ✅ NPU filtering status is visible
6. ✅ State updates in real-time when MCP server changes
7. ✅ Tree view shows current workspace info
8. ✅ Status bar reflects active workspace

## Timeline Estimate

| Phase | Effort | Dependencies |
|-------|--------|--------------|
| Phase 1: Backend State Export | 3 hours | per-workspace-context |
| Phase 2: Extension Data Provider | 2 hours | Phase 1 |
| Phase 3: Chats Tab UI | 4 hours | Phase 2 |
| Phase 4: Actions Integration | 3 hours | Phase 3 |
| Phase 5: Tree View & Status Bar | 2 hours | Phase 2 |

**Total: ~14 hours**

## Mockups

### Chats Tab - Expanded View

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Overview │ Skills │ Services │ Memory │ Cron │ [Chats] │               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Active Workspaces (2)                                    [↻ Refresh]  │
│  ─────────────────────────────────────────────────────────────────────  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐ │
│  │ 🟢 automation-analytics-backend                          [Active] │ │
│  │ ───────────────────────────────────────────────────────────────── │ │
│  │                                                                   │ │
│  │ 📁 /home/daoneill/src/automation-analytics-backend               │ │
│  │                                                                   │ │
│  │ ┌─────────────┬────────────────────────────────────────────────┐ │ │
│  │ │ Persona     │ $(code) Developer                        [▼]  │ │ │
│  │ │ Issue       │ $(issues) AAP-61661 - pytest-xdist parallel   │ │ │
│  │ │ Branch      │ $(git-branch) AAP-61661-pytest-xdist          │ │ │
│  │ │ Tools       │ 78 loaded                          [Expand ▼] │ │ │
│  │ │ Session     │ Started 2h ago • Last active 5m ago           │ │ │
│  │ └─────────────┴────────────────────────────────────────────────┘ │ │
│  │                                                                   │ │
│  │ ▼ Loaded Tools (78)                                              │ │
│  │   ├── git (12): status, commit, push, branch_create, ...        │ │
│  │   ├── gitlab (15): mr_create, mr_view, ci_status, ...           │ │
│  │   ├── jira (10): view_issue, set_status, add_comment, ...       │ │
│  │   └── workflow (41): session_start, skill_run, memory_read, ... │ │
│  │                                                                   │ │
│  │ [Clear Context] [Open in Terminal]                               │ │
│  └───────────────────────────────────────────────────────────────────┘ │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐ │
│  │ 🟡 redhat-ai-workflow                                   [Other]  │ │
│  │ ───────────────────────────────────────────────────────────────── │ │
│  │ 📁 /home/daoneill/src/redhat-ai-workflow                         │ │
│  │ Persona: $(server-process) DevOps • Tools: 74 • Active 30m ago   │ │
│  │ [Expand ▼]                                                        │ │
│  └───────────────────────────────────────────────────────────────────┘ │
│                                                                         │
│  ─────────────────────────────────────────────────────────────────────  │
│  NPU Tool Filtering                                                     │
│  ─────────────────────────────────────────────────────────────────────  │
│  Status: ✅ Active • Model: qwen2.5:0.5b • Instance: NPU               │
│  Cache: 12 entries • TTL: 5 min • Hit rate: 78%                        │
│  [Clear Cache] [Configure]                                              │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Persona Switcher Dropdown

```
┌──────────────────────────────┐
│ Switch Persona               │
├──────────────────────────────┤
│ ● $(code) Developer          │  ← Current
│ ○ $(server-process) DevOps   │
│ ○ $(flame) Incident          │
│ ○ $(package) Release         │
├──────────────────────────────┤
│ $(gear) Custom...            │
└──────────────────────────────┘
```


