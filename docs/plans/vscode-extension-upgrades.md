# VS Code Extension: Contextual Upgrades

> **Goal:** Enhance the VS Code extension with contextual awareness features that leverage per-workspace state from the MCP server. This document covers upgrades beyond the Chats Tab (see `vscode-extension-chats-tab.md`).

## Current Architecture Analysis

### Existing Components

| Component | File | Purpose |
|-----------|------|---------|
| `extension.ts` | Entry point | Initializes all components, sets up refresh interval |
| `dataProvider.ts` | Data source | Reads memory files, queries D-Bus for Slack status |
| `statusBar.ts` | Status bar | 7 status bar items (VPN, Agent, Slack, Issue, Env, MR, Namespace) |
| `treeView.ts` | Sidebar tree | Hierarchical view of Quick Actions, Active Work, Namespaces, Alerts, Follow-ups, Skills |
| `commandCenter.ts` | Webview panel | Tabbed interface with Overview, Skills, Services, Memory, Cron |
| `commands.ts` | Commands | Registers all command palette commands |
| `notifications.ts` | Notifications | Toast notifications for alerts, pipeline failures, MR approvals |
| `skillExecutionWatcher.ts` | File watcher | Watches skill_execution.json for real-time flowchart updates |
| `paths.ts` | Path utilities | Workspace-relative path resolution |

### Current Data Flow

```
Memory Files (~/.config/aa-workflow/memory/)
    ↓
WorkflowDataProvider (reads YAML files)
    ↓
┌─────────────────────────────────────────┐
│ StatusBarManager  │ TreeProvider        │
│ NotificationMgr   │ CommandCenter       │
└─────────────────────────────────────────┘
```

### Identified Gaps

1. **No per-workspace awareness** - All components read global memory files
2. **No MCP server communication** - Extension doesn't know about MCP state
3. **No tool visibility** - Can't see which tools are loaded
4. **No persona sync** - Status bar agent doesn't reflect MCP persona
5. **No inference visibility** - NPU filtering is opaque
6. **Limited context** - Tree view doesn't show workspace-specific info

---

## Proposed Upgrades

### 1. Workspace-Aware Data Provider

**Problem:** `WorkflowDataProvider` reads from global memory files, not workspace-specific state.

**Solution:** Add `WorkspaceStateProvider` that reads from MCP server's exported state.

```typescript
// src/workspaceStateProvider.ts
export interface WorkspaceState {
  workspace_uri: string;
  project: string | null;
  persona: string | null;
  issue_key: string | null;
  branch: string | null;
  active_tools: string[];
  tool_count: number;
  started_at: string;
  last_activity: string;
  is_active: boolean;
}

export class WorkspaceStateProvider {
  private _states: Map<string, WorkspaceState> = new Map();
  private _watcher: fs.FSWatcher | undefined;
  private _onDidChange = new vscode.EventEmitter<void>();

  readonly onDidChange = this._onDidChange.event;

  constructor() {
    this.startWatching();
  }

  getCurrentWorkspaceState(): WorkspaceState | undefined {
    const workspaceUri = vscode.workspace.workspaceFolders?.[0]?.uri.toString();
    return workspaceUri ? this._states.get(workspaceUri) : undefined;
  }

  getAllWorkspaceStates(): WorkspaceState[] {
    return Array.from(this._states.values());
  }
}
```

**Effort:** 3 hours

---

### 2. Real-Time Persona Sync

**Problem:** Status bar shows `currentAgent` from local state, not MCP server's actual persona.

**Solution:** Sync persona from `WorkspaceStateProvider` and update on changes.

```typescript
// In statusBar.ts - updateAgentItem()
private updateAgentItem() {
  // Get persona from workspace state instead of local variable
  const workspaceState = this.workspaceStateProvider.getCurrentWorkspaceState();
  const agent = workspaceState?.persona || this.currentAgent || "";

  // ... rest of update logic
}
```

**Additional Changes:**
- Add `WorkspaceStateProvider` dependency to `StatusBarManager`
- Subscribe to `onDidChange` event
- Update status bar when workspace state changes

**Effort:** 2 hours

---

### 3. Tool Count Badge in Status Bar

**Problem:** No visibility into how many tools are loaded.

**Solution:** Add tool count indicator to agent status bar item.

```typescript
// In statusBar.ts
private updateAgentItem() {
  const workspaceState = this.workspaceStateProvider.getCurrentWorkspaceState();
  const toolCount = workspaceState?.tool_count || 0;

  // Show: "$(code) Developer (78)"
  this.agentItem.text = `${icon} ${displayName} (${toolCount})`;

  // Enhanced tooltip with tool breakdown
  this.agentItem.tooltip = new vscode.MarkdownString(
    `### $(robot) AI Workflow Agent\n\n` +
    `**Active:** ${displayName}\n` +
    `**Tools:** ${toolCount} loaded\n\n` +
    `| Module | Count |\n` +
    `|--------|-------|\n` +
    `| git | 12 |\n` +
    `| gitlab | 15 |\n` +
    `| jira | 10 |\n` +
    `| workflow | 41 |\n\n` +
    `Click to switch agents`,
    true
  );
}
```

**Effort:** 1 hour

---

### 4. Context-Aware Quick Actions

**Problem:** Quick Actions in tree view are static, not context-aware.

**Solution:** Show different quick actions based on current workspace state.

```typescript
// In treeView.ts - getQuickActionItems()
private getQuickActionItems(): WorkflowTreeItem[] {
  const workspaceState = this.workspaceStateProvider.getCurrentWorkspaceState();
  const actions: QuickAction[] = [];

  // Always show morning/evening
  actions.push({ label: "Morning Briefing", icon: "coffee", command: "aa-workflow.coffee" });

  // Show "Start Work" only if no active issue
  if (!workspaceState?.issue_key) {
    actions.push({ label: "Start Work on Issue", icon: "rocket", command: "aa-workflow.startWork" });
  }

  // Show "Create MR" only if we have an issue and branch
  if (workspaceState?.issue_key && workspaceState?.branch) {
    actions.push({ label: "Create MR", icon: "git-pull-request-create", command: "aa-workflow.createMR" });
  }

  // Show persona-specific actions
  if (workspaceState?.persona === "devops") {
    actions.push({ label: "Deploy to Ephemeral", icon: "cloud-upload", command: "aa-workflow.deployEphemeral" });
    actions.push({ label: "Check Alerts", icon: "bell", command: "aa-workflow.investigateAlert" });
  }

  if (workspaceState?.persona === "incident") {
    actions.push({ label: "Investigate Alert", icon: "search", command: "aa-workflow.investigateAlert" });
    actions.push({ label: "Check Logs", icon: "output", command: "aa-workflow.checkLogs" });
  }

  // ... etc
}
```

**Effort:** 3 hours

---

### 5. Workspace Section in Tree View

**Problem:** Tree view doesn't show current workspace context.

**Solution:** Add "Current Workspace" section at the top.

```typescript
// In treeView.ts - getRootItems()
private getRootItems(): WorkflowTreeItem[] {
  const items: WorkflowTreeItem[] = [];
  const workspaceState = this.workspaceStateProvider.getCurrentWorkspaceState();

  // NEW: Current Workspace section
  if (workspaceState) {
    const wsItem = new WorkflowTreeItem(
      "Current Workspace",
      vscode.TreeItemCollapsibleState.Expanded,
      "root"
    );
    wsItem.iconPath = new vscode.ThemeIcon("folder-opened", new vscode.ThemeColor("charts.blue"));
    wsItem.description = workspaceState.project || "Unknown";
    items.push(wsItem);
  }

  // ... existing items (Quick Actions, Active Work, etc.)
}

// Add children for workspace section
private getWorkspaceChildren(): WorkflowTreeItem[] {
  const ws = this.workspaceStateProvider.getCurrentWorkspaceState();
  if (!ws) return [];

  return [
    this.createDetailItem("Project", ws.project || "Not detected", "folder"),
    this.createDetailItem("Persona", ws.persona || "Default", this.getPersonaIcon(ws.persona)),
    this.createDetailItem("Issue", ws.issue_key || "None", "issues"),
    this.createDetailItem("Branch", ws.branch || "None", "git-branch"),
    this.createDetailItem("Tools", `${ws.tool_count} loaded`, "extensions"),
  ];
}
```

**Effort:** 2 hours

---

### 6. NPU Filtering Status Panel

**Problem:** No visibility into NPU tool filtering.

**Solution:** Add NPU status to Command Center Overview tab.

```html
<!-- In commandCenter.ts - getOverviewHtml() -->
<div class="card">
  <h3>$(chip) NPU Tool Filtering</h3>
  <div class="npu-status">
    <div class="status-row">
      <span class="label">Status:</span>
      <span class="value ${npuEnabled ? 'success' : 'disabled'}">
        ${npuEnabled ? '✅ Active' : '⚪ Disabled'}
      </span>
    </div>
    <div class="status-row">
      <span class="label">Model:</span>
      <span class="value">${npuModel || 'N/A'}</span>
    </div>
    <div class="status-row">
      <span class="label">Instance:</span>
      <span class="value">${npuInstance || 'N/A'}</span>
    </div>
    <div class="status-row">
      <span class="label">Cache:</span>
      <span class="value">${cacheSize} entries (TTL: ${cacheTtl}s)</span>
    </div>
    <div class="status-row">
      <span class="label">Hit Rate:</span>
      <span class="value">${hitRate}%</span>
    </div>
  </div>
  <div class="actions">
    <button onclick="clearNpuCache()">Clear Cache</button>
    <button onclick="toggleNpuFiltering()">
      ${npuEnabled ? 'Disable' : 'Enable'}
    </button>
  </div>
</div>
```

**Effort:** 3 hours

---

### 7. Contextual Notifications

**Problem:** Notifications are generic, not workspace-aware.

**Solution:** Enhance notifications with workspace context.

```typescript
// In notifications.ts
private async checkPipeline(status: WorkflowStatus): Promise<void> {
  const workspaceState = this.workspaceStateProvider.getCurrentWorkspaceState();
  const mr = status.activeMR;
  if (!mr) return;

  // Include workspace context in notification
  if (mr.pipelineStatus === "failed") {
    const projectName = workspaceState?.project || "Unknown";
    const action = await vscode.window.showErrorMessage(
      `❌ Pipeline failed for MR !${mr.id} in ${projectName}`,
      "View MR",
      "View Logs",
      "Retry Pipeline"
    );

    switch (action) {
      case "View MR":
        vscode.commands.executeCommand("aa-workflow.openMR");
        break;
      case "View Logs":
        // NEW: Open CI logs directly
        vscode.commands.executeCommand("aa-workflow.viewCILogs", mr.id);
        break;
      case "Retry Pipeline":
        // NEW: Retry pipeline
        vscode.commands.executeCommand("aa-workflow.retryPipeline", mr.id);
        break;
    }
  }
}
```

**Effort:** 2 hours

---

### 8. Smart Skill Suggestions

**Problem:** Skill picker shows all skills, not contextually relevant ones.

**Solution:** Sort/filter skills based on current workspace state.

```typescript
// In commands.ts - runSkill command
context.subscriptions.push(
  vscode.commands.registerCommand("aa-workflow.runSkill", async () => {
    const workspaceState = this.workspaceStateProvider.getCurrentWorkspaceState();
    const allSkills = loadSkillsFromDisk();

    // Score skills by relevance to current context
    const scoredSkills = allSkills.map(skill => ({
      ...skill,
      score: calculateSkillRelevance(skill, workspaceState)
    }));

    // Sort by score (highest first)
    scoredSkills.sort((a, b) => b.score - a.score);

    // Add "Suggested" section for high-scoring skills
    const suggested = scoredSkills.filter(s => s.score > 0.7);
    const other = scoredSkills.filter(s => s.score <= 0.7);

    const quickPickItems = [
      { label: "Suggested", kind: vscode.QuickPickItemKind.Separator },
      ...suggested.map(s => createSkillQuickPickItem(s)),
      { label: "All Skills", kind: vscode.QuickPickItemKind.Separator },
      ...other.map(s => createSkillQuickPickItem(s)),
    ];

    // ... show quick pick
  })
);

function calculateSkillRelevance(skill: Skill, ws: WorkspaceState | undefined): number {
  let score = 0;

  // Persona match
  if (ws?.persona && skill.personas?.includes(ws.persona)) {
    score += 0.5;
  }

  // Has active issue - suggest issue-related skills
  if (ws?.issue_key) {
    if (skill.name.includes("mr") || skill.name.includes("review")) {
      score += 0.3;
    }
  }

  // Has active MR - suggest MR-related skills
  if (ws?.branch && ws.branch !== "main") {
    if (skill.name.includes("create_mr") || skill.name.includes("push")) {
      score += 0.3;
    }
  }

  // DevOps persona - suggest deployment skills
  if (ws?.persona === "devops") {
    if (skill.name.includes("deploy") || skill.name.includes("ephemeral")) {
      score += 0.4;
    }
  }

  return Math.min(score, 1.0);
}
```

**Effort:** 4 hours

---

### 9. Workspace Switcher Command

**Problem:** No way to quickly switch between workspace contexts.

**Solution:** Add command to switch focus to another workspace.

```typescript
// In commands.ts
context.subscriptions.push(
  vscode.commands.registerCommand("aa-workflow.switchWorkspace", async () => {
    const allWorkspaces = this.workspaceStateProvider.getAllWorkspaceStates();

    const items = allWorkspaces.map(ws => ({
      label: `$(folder) ${ws.project || path.basename(ws.workspace_uri)}`,
      description: ws.persona ? `$(${getPersonaIcon(ws.persona)}) ${ws.persona}` : "",
      detail: ws.issue_key ? `$(issues) ${ws.issue_key}` : "No active issue",
      workspace: ws,
    }));

    const selected = await vscode.window.showQuickPick(items, {
      placeHolder: "Select workspace to focus",
      matchOnDescription: true,
    });

    if (selected) {
      // Open the workspace folder
      const uri = vscode.Uri.parse(selected.workspace.workspace_uri);
      await vscode.commands.executeCommand("vscode.openFolder", uri, { forceNewWindow: false });
    }
  })
);
```

**Effort:** 2 hours

---

### 10. Activity Timeline

**Problem:** No visibility into recent activity across workspaces.

**Solution:** Add activity timeline to Command Center.

```html
<!-- In commandCenter.ts - new tab or section -->
<div class="card">
  <h3>$(history) Recent Activity</h3>
  <div class="timeline">
    <div class="timeline-item">
      <span class="time">2 min ago</span>
      <span class="icon">$(git-commit)</span>
      <span class="action">Committed to AAP-61661-pytest-xdist</span>
      <span class="workspace">backend</span>
    </div>
    <div class="timeline-item">
      <span class="time">15 min ago</span>
      <span class="icon">$(play)</span>
      <span class="action">Ran skill: create_mr</span>
      <span class="workspace">backend</span>
    </div>
    <div class="timeline-item">
      <span class="time">30 min ago</span>
      <span class="icon">$(cloud-upload)</span>
      <span class="action">Deployed to ephemeral-abc123</span>
      <span class="workspace">workflow</span>
    </div>
    <div class="timeline-item">
      <span class="time">1 hour ago</span>
      <span class="icon">$(robot)</span>
      <span class="action">Switched to devops persona</span>
      <span class="workspace">workflow</span>
    </div>
  </div>
</div>
```

**Data Source:** Session logs from `~/.config/aa-workflow/memory/sessions/`

**Effort:** 4 hours

---

### 11. Inline Tool Documentation

**Problem:** Users don't know what tools do without checking docs.

**Solution:** Add hover documentation for tools in Command Center.

```typescript
// In commandCenter.ts - tool list rendering
private getToolHtml(tool: ToolDefinition): string {
  return `
    <div class="tool-item" data-tool="${tool.name}">
      <span class="tool-name">${tool.name}</span>
      <span class="tool-module">${tool.module}</span>
      <div class="tool-tooltip">
        <strong>${tool.name}</strong>
        <p>${tool.description}</p>
        <code>Parameters: ${tool.parameters?.join(", ") || "none"}</code>
      </div>
    </div>
  `;
}
```

**CSS:**
```css
.tool-item {
  position: relative;
}

.tool-tooltip {
  display: none;
  position: absolute;
  background: var(--vscode-editorHoverWidget-background);
  border: 1px solid var(--vscode-editorHoverWidget-border);
  padding: 8px;
  border-radius: 4px;
  z-index: 100;
  max-width: 300px;
}

.tool-item:hover .tool-tooltip {
  display: block;
}
```

**Effort:** 2 hours

---

### 12. Keyboard Shortcuts Panel

**Problem:** Users don't know available keyboard shortcuts.

**Solution:** Add shortcuts reference to Command Center.

```html
<!-- In commandCenter.ts - Overview tab -->
<div class="card shortcuts-card">
  <h3>$(keyboard) Keyboard Shortcuts</h3>
  <table class="shortcuts-table">
    <tr>
      <td><kbd>Ctrl+Alt+O</kbd></td>
      <td>Open Command Center</td>
    </tr>
    <tr>
      <td><kbd>Ctrl+Alt+R</kbd></td>
      <td>Run Skill</td>
    </tr>
    <tr>
      <td><kbd>Ctrl+Alt+A</kbd></td>
      <td>Switch Agent</td>
    </tr>
    <tr>
      <td><kbd>Ctrl+Alt+S</kbd></td>
      <td>Skill Flowchart</td>
    </tr>
    <tr>
      <td><kbd>Ctrl+Alt+D</kbd></td>
      <td>Dashboard</td>
    </tr>
    <tr>
      <td><kbd>Ctrl+Alt+C</kbd></td>
      <td>Cron Tab</td>
    </tr>
  </table>
</div>
```

**Effort:** 1 hour

---

## Implementation Priority

### High Priority (Core Contextual Features)

| # | Upgrade | Effort | Impact |
|---|---------|--------|--------|
| 1 | Workspace-Aware Data Provider | 3h | Foundation for all other upgrades |
| 2 | Real-Time Persona Sync | 2h | Accurate status bar |
| 5 | Workspace Section in Tree View | 2h | Visibility into current context |
| 3 | Tool Count Badge | 1h | Quick tool visibility |

**Subtotal: 8 hours**

### Medium Priority (Enhanced UX)

| # | Upgrade | Effort | Impact |
|---|---------|--------|--------|
| 4 | Context-Aware Quick Actions | 3h | Smarter suggestions |
| 6 | NPU Filtering Status Panel | 3h | Inference visibility |
| 8 | Smart Skill Suggestions | 4h | Better skill discovery |
| 7 | Contextual Notifications | 2h | Actionable alerts |

**Subtotal: 12 hours**

### Lower Priority (Nice to Have)

| # | Upgrade | Effort | Impact |
|---|---------|--------|--------|
| 9 | Workspace Switcher Command | 2h | Multi-workspace workflow |
| 10 | Activity Timeline | 4h | Historical visibility |
| 11 | Inline Tool Documentation | 2h | Discoverability |
| 12 | Keyboard Shortcuts Panel | 1h | Onboarding |

**Subtotal: 9 hours**

---

## Total Effort Estimate

| Priority | Effort |
|----------|--------|
| High | 8 hours |
| Medium | 12 hours |
| Low | 9 hours |
| **Total** | **29 hours** |

Combined with Chats Tab (~14 hours) and Per-Workspace Context backend (~17 hours):

**Grand Total: ~60 hours**

---

## Dependencies

```
per-workspace-context.md (backend)
    ↓
WorkspaceStateExporter (writes JSON)
    ↓
workspace_states.json
    ↓
WorkspaceStateProvider (extension)
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ All Upgrades (status bar, tree view, command center, etc.)      │
└─────────────────────────────────────────────────────────────────┘
```

---

## Success Metrics

1. **Persona Accuracy:** Status bar always shows correct MCP persona
2. **Tool Visibility:** Users can see loaded tools at a glance
3. **Context Awareness:** Quick actions adapt to current state
4. **Reduced Friction:** Fewer clicks to find relevant skills
5. **Better Debugging:** NPU filtering status visible
6. **Multi-Workspace:** Smooth switching between projects

---

## Mockups

### Enhanced Status Bar

```
[$(shield) VPN] [$(code) Developer (78)] [$(check) Slack] [$(issues) AAP-61661] [$(pass) Env] [$(pass) !1459] [$(cloud-upload) eph-abc]
                      ↑
                Tool count badge
```

### Enhanced Tree View

```
WORKFLOW EXPLORER
├── 📁 Current Workspace
│   ├── Project: automation-analytics-backend
│   ├── Persona: $(code) Developer
│   ├── Issue: $(issues) AAP-61661
│   ├── Branch: $(git-branch) AAP-61661-pytest-xdist
│   └── Tools: $(extensions) 78 loaded
├── ⚡ Quick Actions
│   ├── $(git-pull-request-create) Create MR  ← Context-aware
│   ├── $(eye) Check MR Feedback              ← Context-aware
│   ├── $(play) Run Skill...
│   └── $(debug-stop) End of Day
├── 📋 Active Work
│   └── ...
└── ...
```

### NPU Status in Command Center

```
┌─────────────────────────────────────────────────────────────────┐
│ $(chip) NPU Tool Filtering                                      │
├─────────────────────────────────────────────────────────────────┤
│ Status:    ✅ Active                                            │
│ Model:     qwen2.5:0.5b                                         │
│ Instance:  NPU (port 11434)                                     │
│ Cache:     12 entries • TTL: 5 min • Hit rate: 78%              │
│                                                                 │
│ Last Filter:                                                    │
│   Message: "deploy MR 1459 to ephemeral"                        │
│   Result:  k8s, bonfire, quay (24 tools)                        │
│   Latency: 45ms                                                 │
│                                                                 │
│ [Clear Cache] [View History] [Configure]                        │
└─────────────────────────────────────────────────────────────────┘
```
