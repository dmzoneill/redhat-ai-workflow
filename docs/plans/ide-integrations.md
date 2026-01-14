# IDE Integrations Plan

## Overview

Enhance the AI Workflow experience by integrating directly into Cursor/VSCode UI, providing real-time status, quick actions, and visibility without context switching.

---

## Core Requirements

### ⚠️ CRITICAL: IDE Integration is Optional

**All skills, tools, and code MUST work without any IDE integration.**

The IDE integration is a **convenience layer**, not a dependency. Users should be able to:

1. **Run skills from CLI** - `python -m mcp_server skill_run start_work ...`
2. **Use MCP tools via chat** - No extension required
3. **Run daemons standalone** - `python scripts/slack_daemon.py`
4. **Execute in headless environments** - CI/CD, servers, containers

### Design Principles

| Principle | Description |
|-----------|-------------|
| **Optional Enhancement** | IDE features add value but aren't required |
| **Graceful Degradation** | If extension unavailable, everything still works |
| **No Coupling** | Core code must not import IDE-specific modules |
| **Event-Driven** | IDE listens to events; core code doesn't wait for IDE |
| **CLI First** | Every feature must work from command line |

### Architecture Pattern

```text
┌─────────────────────────────────────────────────────────────┐
│                    IDE EXTENSION (Optional)                  │
│         Status Bar │ Webview │ Notifications                │
└──────────────────────────┬──────────────────────────────────┘
                           │ D-Bus / Events (subscribe)
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    CORE WORKFLOW (Required)                  │
│         MCP Tools │ Skills │ Daemons │ CLI                  │
│                                                              │
│  ✅ Works standalone    ✅ Works in containers               │
│  ✅ Works headless      ✅ Works without Cursor              │
└─────────────────────────────────────────────────────────────┘
```

### Implementation Rules

1. **Core code emits events** - It doesn't know or care if anyone is listening
2. **IDE subscribes to events** - It's just another consumer
3. **No blocking on IDE** - Core never waits for IDE acknowledgment
4. **Feature flags** - IDE-specific logging/events can be disabled

```python
# ✅ CORRECT: Core emits events, doesn't care about listeners
class SkillExecutor:
    def run_step(self, step):
        result = step.execute()
        self.emit_event("step_complete", result)  # Fire and forget
        return result

# ❌ WRONG: Core depends on IDE
class SkillExecutor:
    def run_step(self, step):
        result = step.execute()
        await self.ide_extension.update_ui(result)  # Blocks on IDE!
        return result
```text

---

## Current State

### What We Have
| Integration | Status | Location |
|-------------|--------|----------|
| MCP Tools | ✅ 100+ tools | `tool_modules/` |
| Slash Commands | ✅ 35 commands | `.cursor/commands/` |
| Rules Files | ✅ Project context | `.cursor/rules/` |
| Browser Tools | ✅ Testing | Built-in MCP |
| **Status Bar Extension** | ✅ **Phase 1 Complete** | `extensions/aa_workflow-vscode/` |

### What We've Built (Phases 1-4)

**Phase 1 - Status Bar:**
- ✅ Status bar items: Slack, Issue, Environment, MR
- ✅ Click actions to open Jira, GitLab, investigate alerts
- ✅ Configurable visibility per item

**Phase 2 - Tree View Sidebar:**
- ✅ Workflow Explorer in activity bar
- ✅ Active Work section with issues and MRs
- ✅ Namespaces section for ephemeral environments
- ✅ Alerts section with environment health
- ✅ Follow-ups section with priority indicators
- ✅ Context menus for actions

**Phase 3 - Command Palette:**
- ✅ 11 commands registered
- ✅ Skill picker with common workflows
- ✅ Refresh commands for status and tree

**Phase 4 - Notifications:**
- ✅ Alert notifications (production critical, stage warning)
- ✅ Pipeline status notifications (failed/passed)
- ✅ MR ready for review notifications
- ✅ D-Bus watcher for Slack events
- ✅ Configurable via settings

**Infrastructure:**
- ✅ Data provider reading from memory files + D-Bus
- ✅ Makefile targets: `ext-build`, `ext-install`, `ext-watch`, `ext-package`

**Phase 5 - Dashboard Webview:**
- ✅ Rich visual dashboard in editor tab
- ✅ Current work overview (issue + MR cards)
- ✅ Environment health indicators
- ✅ Namespaces and follow-ups lists
- ✅ Quick action buttons
- ✅ Auto-refresh with timestamp

**Phase 6 - Skill Visualizer:**
- ✅ GitHub Actions-style flowchart
- ✅ Step-by-step progress visualization
- ✅ Status icons (pending/running/success/failed)
- ✅ Duration tracking per step
- ✅ Error highlighting with details
- ✅ Summary statistics on completion
- ✅ Skill picker integration

### What's Complete
🎉 **All 6 phases implemented!** The extension is feature-complete.

---

## Proposed Integrations

### Phase 1: Status Bar Extension (Quick Win)

**Goal:** Show real-time status without opening chat

```
┌─────────────────────────────────────────────────────────────┐
│ [file tabs]                                    │ 🟢 Slack │ AAP-61214 │ ⚡ Stage OK │
└─────────────────────────────────────────────────────────────┘
```text

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
```text

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
> AI Workflow: Load DevOps Persona
```text

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
```text

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
└── aa_workflow-vscode/
    ├── package.json
    ├── src/
    │   ├── extension.ts      # Entry point
    │   ├── statusBar.ts      # Status bar items
    │   ├── treeView.ts       # Sidebar tree
    │   ├── commands.ts       # Command palette
    │   └── webview.ts        # Dashboard
    └── media/
        └── dashboard.html
```text

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
│  Extension  │◀────│  (bridge)   │◀────│  (aa_workflow)│
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
```text

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
```text

---

## Decisions Made

1. **Priority:** TBD - will decide later
2. **Data source:** MCP + D-Bus (hybrid)
3. **Distribution:** This project only (local extension)

---

## Phase 6: Skill Execution Visualizer (GitHub Actions Style)

**Goal:** Show real-time visual flowchart of skill execution

### Mockup

```
┌─────────────────────────────────────────────────────────────────────┐
│ SKILL: start_work                                    [Running... 5s] │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   ┌─────────────────┐                                               │
│   │ 1. Fetch Issue  │ ✅ 0.8s                                       │
│   │   AAP-61214     │                                               │
│   └────────┬────────┘                                               │
│            │                                                         │
│            ▼                                                         │
│   ┌─────────────────┐                                               │
│   │ 2. Check Branch │ ✅ 0.3s                                       │
│   │   exists: false │                                               │
│   └────────┬────────┘                                               │
│            │                                                         │
│            ▼                                                         │
│   ┌─────────────────┐                                               │
│   │ 3. Create Branch│ ⏳ Running...                                 │
│   │   aap-61214-... │                                               │
│   └────────┬────────┘                                               │
│            │                                                         │
│            ▼                                                         │
│   ┌─────────────────┐                                               │
│   │ 4. Switch Branch│ ⏸️ Pending                                    │
│   └────────┬────────┘                                               │
│            │                                                         │
│            ▼                                                         │
│   ┌─────────────────┐                                               │
│   │ 5. Show Context │ ⏸️ Pending                                    │
│   └─────────────────┘                                               │
│                                                                      │
├─────────────────────────────────────────────────────────────────────┤
│ STEP 3 OUTPUT:                                                       │
│ > git checkout -b aap-61214-fix-billing-calculation                 │
│ > Switched to new branch 'aap-61214-fix-billing-calculation'        │
└─────────────────────────────────────────────────────────────────────┘
```text

### With Conditional Branches (Decision Tree)

```
┌─────────────────────────────────────────────────────────────────────┐
│ SKILL: deploy_ephemeral                              [Running... 12s]│
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   ┌─────────────────┐                                               │
│   │ 1. Check Image  │ ✅                                            │
│   └────────┬────────┘                                               │
│            │                                                         │
│            ▼                                                         │
│   ┌─────────────────┐                                               │
│   │ 2. Image Ready? │                                               │
│   └───┬─────────┬───┘                                               │
│       │         │                                                    │
│    Yes│         │No                                                  │
│       ▼         ▼                                                    │
│   ┌───────┐ ┌───────────┐                                           │
│   │ Skip  │ │ 3. Build  │ ⏳ Running...                             │
│   │       │ │    Image  │                                           │
│   └───┬───┘ └─────┬─────┘                                           │
│       │           │                                                  │
│       └─────┬─────┘                                                  │
│             ▼                                                        │
│   ┌─────────────────┐                                               │
│   │ 4. Reserve NS   │ ⏸️ Pending                                    │
│   └────────┬────────┘                                               │
│            ▼                                                         │
│   ┌─────────────────┐                                               │
│   │ 5. Deploy App   │ ⏸️ Pending                                    │
│   └─────────────────┘                                               │
└─────────────────────────────────────────────────────────────────────┘
```text

### Display Location Options

Where should the visualizer appear? Here are the options:

#### Option A: Webview Panel (Recommended)

Opens as a tab in the editor area, like a file.

```
┌─────────────────────────────────────────────────────────────┐
│ Explorer │ main.py │ 🔄 skill-execution │                   │
├──────────┼─────────┴────────────────────────────────────────┤
│ Files    │  ┌──────────────────────────────────────────┐   │
│          │  │   🔄 test_mr_ephemeral                   │   │
│          │  │   [✅ validate] → [✅ reserve] → [🔄 deploy]  │
│          │  └──────────────────────────────────────────┘   │
│          │                                                  │
└──────────┴──────────────────────────────────────────────────┘
```text

| Pros | Cons |
|------|------|
| Rich visuals, full HTML/CSS/JS | Requires extension |
| Interactive (click, hover) | Takes editor space |
| Can dock, split, or float | |
| Native VSCode feel | |

**Best for:** Full flowchart visualization with interaction

---

#### Option B: Bottom Panel

Like the Terminal, Problems, Output panels.

```
┌─────────────────────────────────────────────────────────────┐
│ main.py                                                     │
├─────────────────────────────────────────────────────────────┤
│ Terminal │ Output │ Problems │ 🔄 Skill Execution │         │
├─────────────────────────────────────────────────────────────┤
│ start_work: [✅ fetch] → [✅ branch] → [🔄 checkout] → [⏸ context] │
└─────────────────────────────────────────────────────────────┘
```text

| Pros | Cons |
|------|------|
| Always visible | Limited vertical space |
| Doesn't interrupt coding | Less room for complex flows |
| Familiar location | Compact view only |

**Best for:** Compact progress indicator while coding

---

#### Option C: External Browser Window

Opens `http://localhost:PORT/skill-viewer` in a browser.

```
┌───────────────────────────────────────────────────┐
│ 🌐 Skill Execution Viewer - localhost:3456        │
├───────────────────────────────────────────────────┤
│   Full flowchart with animations...              │
│   Can be larger than any IDE panel               │
│   Shareable URL for team members                 │
└───────────────────────────────────────────────────┘
```text

| Pros | Cons |
|------|------|
| No extension needed | Context switching |
| Unlimited size | Separate window |
| Can be accessed remotely | Runs on port |
| Independent of IDE | |

**Best for:** Dashboard-style persistent monitoring

---

#### Option D: Sidebar Tree View

Hierarchical view in the Explorer sidebar.

```
SKILL EXECUTION
├── 🔄 start_work
│   ├── ✅ 1. Fetch Issue (0.8s)
│   │   └── AAP-61214: Fix billing
│   ├── ✅ 2. Check Branch (0.3s)
│   │   └── exists: false
│   ├── 🔄 3. Create Branch...
│   └── ⏸ 4. Switch Branch
└── 📜 Previous Runs
    └── test_ephemeral (2m ago) ✅
```

| Pros | Cons |
|------|------|
| Compact | Not visual flowchart |
| Always visible | Limited to tree structure |
| Native VSCode widget | No decision branches |
| Expandable details | |

**Best for:** Quick status checks, history browsing

---

#### Option E: Chat Response Inline (Cursor-specific)

Mermaid diagrams rendered in chat using markdown.

```markdown
```mermaid
flowchart TD
    A[✅ Fetch Issue] --> B[✅ Check Branch]
    B --> C{Exists?}
    C -->|No| D[🔄 Create Branch]
    D --> E[⏸ Switch]
```​
```text

| Pros | Cons |
|------|------|
| Already works today | Not real-time |
| No additional UI | Static after render |
| Good for post-mortem | Can't update in place |

**Best for:** Post-execution review in conversation

---

### Recommended: Hybrid Approach

Use different displays for different scenarios:

| Scenario | Display | Why |
|----------|---------|-----|
| Quick status glance | **Status bar** | `🔄 deploy [3/5]` - minimal |
| Active execution | **Bottom panel** | Compact progress, visible while coding |
| Full visualization | **Webview panel** | On-demand, click from status bar |
| Post-execution | **Chat inline** | Mermaid diagram in response |
| History/browsing | **Sidebar tree** | Navigate past runs |
| Team/demo | **External browser** | Shareable, persistent |

```
User clicks status bar "🔄 deploy [3/5]"
    ↓
Opens webview panel with full flowchart
    ↓
When skill completes, Mermaid diagram appears in chat
```

---

### Technical Implementation

#### 1. Skill Engine Events

Add event emission to `skill_engine.py`:

```python
class SkillExecutor:
    def __init__(self, event_callback=None):
        self.on_event = event_callback  # Callback for UI updates

    async def run_skill(self, skill_name, inputs):
        skill = self.load_skill(skill_name)

        # Emit: skill started
        self.emit("skill_start", {"name": skill_name, "steps": skill.steps})

        for i, step in enumerate(skill.steps):
            # Emit: step started
            self.emit("step_start", {"index": i, "name": step.name})

            try:
                result = await self.execute_step(step)
                # Emit: step completed
                self.emit("step_complete", {"index": i, "result": result})
            except Exception as e:
                # Emit: step failed
                self.emit("step_failed", {"index": i, "error": str(e)})
                raise

        # Emit: skill completed
        self.emit("skill_complete", {"name": skill_name})
```

#### 2. D-Bus Interface

Extend existing D-Bus interface:

```python
# In slack_daemon.py or separate daemon
@dbus_interface("com.aiworkflow.Skills")
class SkillInterface:
    @signal
    def SkillStarted(self, skill_name: str, steps_json: str):
        pass

    @signal
    def StepStarted(self, step_index: int, step_name: str):
        pass

    @signal
    def StepCompleted(self, step_index: int, output: str):
        pass

    @signal
    def StepFailed(self, step_index: int, error: str):
        pass
```

#### 3. VSCode Webview

```typescript
// Listen for D-Bus signals
dbusConnection.on('StepStarted', (stepIndex, stepName) => {
    updateFlowchart(stepIndex, 'running');
});

dbusConnection.on('StepCompleted', (stepIndex, output) => {
    updateFlowchart(stepIndex, 'completed', output);
});

// Render flowchart using SVG or HTML/CSS
function renderFlowchart(skill: Skill) {
    const svg = buildFlowchartSVG(skill.steps);
    webviewPanel.webview.html = wrapInHTML(svg);
}
```

#### 4. Libraries for Flowchart Rendering

| Library | Pros | Cons |
|---------|------|------|
| **Mermaid.js** | Simple, declarative | Limited interactivity |
| **D3.js** | Full control | Complex |
| **Dagre-D3** | Good for DAGs | Steeper learning curve |
| **GoJS** | Beautiful, interactive | Commercial license |
| **Cytoscape.js** | Good for graphs | Overkill for linear flows |
| **Custom SVG** | Simple, no deps | More code |

**Recommendation:** Start with **Mermaid.js** for simplicity, upgrade later if needed.

```javascript
// Mermaid flowchart from skill steps
const mermaidCode = `
flowchart TD
    A[Fetch Issue] -->|0.8s| B[Check Branch]
    B -->|0.3s| C{Branch Exists?}
    C -->|No| D[Create Branch]
    C -->|Yes| E[Switch Branch]
    D --> E
    E --> F[Show Context]

    style A fill:#10b981
    style B fill:#10b981
    style C fill:#10b981
    style D fill:#3b82f6,stroke:#fff,stroke-width:2px
    style E fill:#6b7280
    style F fill:#6b7280
`;
```

### Effort Estimate

| Component | Effort |
|-----------|--------|
| Skill engine events | 1 day |
| D-Bus signals | 0.5 day |
| Webview panel scaffold | 1 day |
| Flowchart rendering (Mermaid) | 2 days |
| Interactive features (click to expand) | 1-2 days |
| **Total** | **5-7 days** |

### Future Enhancements

1. **Drill-down:** Click step to see full output
2. **Re-run:** Button to re-run failed step
3. **History:** View past skill executions
4. **Compare:** Side-by-side execution comparison
5. **Export:** Save flowchart as PNG/SVG

---

## Updated Phase Summary

| Phase | Feature | Effort | Status |
|-------|---------|--------|--------|
| 1 | Status Bar | 1-2 days | ✅ **Complete** |
| 2 | Tree View Sidebar | 3-5 days | ✅ **Complete** |
| 3 | Command Palette | 1 day | ✅ **Complete** (14 commands) |
| 4 | Notifications | 1-2 days | ✅ **Complete** |
| 5 | Dashboard Webview | 5-7 days | ✅ **Complete** |
| 6 | Skill Visualizer | 5-7 days | ✅ **Complete** |

🎉 **All phases complete!**

---

## Next Steps

1. [x] ~~Decide on priority phases (1-6)~~ - Started with Phase 1
2. [x] ~~Create VSCode extension scaffold~~ - Done: `extensions/aa_workflow-vscode/`
3. [ ] Add skill execution events to skill_engine.py (Phase 6 prep)
4. [ ] Implement D-Bus signals for real-time updates (Phase 6 prep)
5. [ ] Build webview with Mermaid.js flowchart (Phase 5/6)
6. [ ] Iterate based on feedback

### Immediate Next Steps for Phase 2
1. [ ] Create tree view provider (`treeView.ts`)
2. [ ] Register tree view in `package.json`
3. [ ] Add right-click context menus
4. [ ] Connect to data provider for refresh
