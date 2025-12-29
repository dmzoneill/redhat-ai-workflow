# IDE Integrations Plan

## Overview

Enhance the AI Workflow experience by integrating directly into Cursor/VSCode UI, providing real-time status, quick actions, and visibility without context switching.

---

## Current State

### What We Have
| Integration | Status | Location |
|-------------|--------|----------|
| MCP Tools | ✅ 100+ tools | `mcp-servers/` |
| Slash Commands | ✅ 35 commands | `.cursor/commands/` |
| Rules Files | ✅ Project context | `.cursor/rules/` |
| Browser Tools | ✅ Testing | Built-in MCP |

### What's Missing
- No visual status indicators in the IDE
- No quick access to common actions
- No real-time notifications
- Must use chat for everything

---

## Proposed Integrations

### Phase 1: Status Bar Extension (Quick Win)

**Goal:** Show real-time status without opening chat

```
┌─────────────────────────────────────────────────────────────┐
│ [file tabs]                                    │ 🟢 Slack │ AAP-61214 │ ⚡ Stage OK │
└─────────────────────────────────────────────────────────────┘
```

**Components:**
| Item | Shows | Click Action |
|------|-------|--------------|
| Slack Status | 🟢 Online / 🔴 Errors: 3 | Open Slack daemon logs |
| Active Issue | AAP-61214 | Open Jira in browser |
| Environment | ⚡ Stage OK / ⚠️ 2 alerts | Run investigate-alert |
| Active MR | MR !1459 | Open GitLab MR |

**Effort:** 1-2 days

---

### Phase 2: Activity Panel (Sidebar)

**Goal:** Tree view showing current work context

```
WORKFLOW EXPLORER
├── 📋 Active Work
│   ├── AAP-61214 - Fix billing calculation
│   │   ├── Branch: aap-61214-fix-billing
│   │   ├── MR: !1459 (Draft)
│   │   └── Pipeline: ✅ Passed
│   └── AAP-61200 - Add retry logic
├── 🚀 Namespaces
│   ├── ephemeral-abc123 (mine, 2h left)
│   └── ephemeral-xyz789 (team)
├── 🔔 Alerts
│   ├── ⚠️ HighMemoryUsage (stage)
│   └── 🔴 PodCrashLooping (prod)
└── 📬 Recent Messages
    ├── @alice: Can you review MR !1459?
    └── @bob: Deploy looks good
```

**Features:**
- Refresh on demand or auto-refresh
- Right-click context menus (Open, Investigate, Deploy)
- Icons and colors for status
- Collapsible sections

**Effort:** 3-5 days

---

### Phase 3: Command Palette Integration

**Goal:** Quick actions via `Ctrl+Shift+P`

```
> AI Workflow: Start Work on Issue
> AI Workflow: Create MR
> AI Workflow: Deploy to Ephemeral
> AI Workflow: Check Pipeline Status
> AI Workflow: Investigate Alert
> AI Workflow: Load DevOps Agent
```

**Benefits:**
- Discoverable (searchable)
- Keyboard-friendly
- Consistent with VSCode patterns

**Effort:** 1 day (if extension exists)

---

### Phase 4: Notifications

**Goal:** Toast notifications for important events

| Event | Notification |
|-------|--------------|
| MR approved | "✅ MR !1459 approved by @alice" |
| Pipeline failed | "❌ Pipeline failed for aap-61214" |
| Alert firing | "🔴 PodCrashLooping in prod" |
| Namespace expiring | "⏰ ephemeral-abc123 expires in 30m" |

**Implementation Options:**
1. VSCode native notifications
2. System notifications (libnotify on Linux)
3. Both

**Effort:** 1-2 days

---

### Phase 5: Webview Dashboard

**Goal:** Rich visual dashboard

```
┌────────────────────────────────────────────────────────────┐
│ AI WORKFLOW DASHBOARD                              [Refresh]│
├────────────────────────────────────────────────────────────┤
│                                                            │
│  CURRENT WORK                    ENVIRONMENTS              │
│  ┌──────────────────────┐       ┌──────────────────────┐  │
│  │ AAP-61214            │       │ Stage    🟢 Healthy  │  │
│  │ Fix billing calc     │       │ Prod     🟢 Healthy  │  │
│  │ MR: !1459 (Draft)    │       │ Ephemeral: 2 active  │  │
│  │ Pipeline: ✅ Passed  │       └──────────────────────┘  │
│  └──────────────────────┘                                  │
│                                                            │
│  RECENT ACTIVITY                                           │
│  • 10:30 - Deployed to ephemeral-abc123                   │
│  • 10:15 - MR !1459 created                               │
│  • 09:45 - Started work on AAP-61214                      │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

**Tech:**
- HTML/CSS/JS webview
- Communicate with extension via postMessage
- Pull data from MCP tools or direct API calls

**Effort:** 5-7 days

---

## Technical Approach

### Option A: Standalone VSCode Extension

```
extensions/
└── aa-workflow-vscode/
    ├── package.json
    ├── src/
    │   ├── extension.ts      # Entry point
    │   ├── statusBar.ts      # Status bar items
    │   ├── treeView.ts       # Sidebar tree
    │   ├── commands.ts       # Command palette
    │   └── webview.ts        # Dashboard
    └── media/
        └── dashboard.html
```

**Pros:**
- Full control
- Can package and distribute
- Works in any VSCode-based IDE

**Cons:**
- Separate repo/package to maintain
- Need to handle auth/config separately

---

### Option B: MCP-Powered Extension

Extension communicates with our existing MCP server:

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  VSCode     │────▶│  Extension  │────▶│  MCP Server │
│  Extension  │◀────│  (bridge)   │◀────│  (aa-workflow)│
└─────────────┘     └─────────────┘     └─────────────┘
```

**Pros:**
- Reuses existing tools
- Single source of truth
- Already handles auth

**Cons:**
- MCP communication overhead
- Need to run MCP server

---

### Option C: Lightweight Script Integration

Use existing D-Bus interface (already in slack_daemon):

```python
# slack_daemon.py already exposes:
# - com.aiworkflow.SlackAgent.GetStatus
# - com.aiworkflow.SlackAgent.GetStats
```

Extension can query via D-Bus for real-time status.

**Pros:**
- Already implemented
- Very fast
- No additional server

**Cons:**
- Linux only (D-Bus)
- Limited to what daemon exposes

---

## Recommendation

### Start with Phase 1 (Status Bar)

1. **Minimal effort, immediate value**
2. **Validates the approach**
3. **Can iterate based on feedback**

### Implementation Plan

```
Week 1:
├── Day 1-2: Create basic extension scaffold
├── Day 3-4: Implement status bar items
└── Day 5: Connect to MCP/D-Bus for real data

Week 2:
├── Day 1-3: Add tree view (Phase 2)
└── Day 4-5: Add command palette (Phase 3)

Week 3:
├── Day 1-2: Notifications (Phase 4)
└── Day 3-5: Dashboard webview (Phase 5)
```

---

## Questions to Discuss

1. **Which phases are most valuable to you?**
   - Status bar for quick glance?
   - Tree view for navigation?
   - Dashboard for overview?

2. **Data source preference?**
   - MCP tools (reuse existing)
   - Direct API calls (faster)
   - D-Bus (real-time, Linux only)

3. **Distribution?**
   - Local extension (this repo)
   - Published to marketplace
   - Both

4. **Platform support?**
   - Linux only (can use D-Bus)
   - Cross-platform (HTTP/MCP only)

---

## Next Steps

1. [ ] Decide on priority phases
2. [ ] Choose technical approach
3. [ ] Create extension scaffold
4. [ ] Implement Phase 1
5. [ ] Iterate based on feedback
