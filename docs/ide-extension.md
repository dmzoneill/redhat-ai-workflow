# IDE Extension

The AI Workflow VSCode/Cursor extension provides real-time status and quick actions directly in your IDE.

## Installation

```bash
# Build and install
make ext-install

# Or manually:
cd extensions/aa_workflow-vscode
npm install
npm run compile
ln -sf "$(pwd)" ~/.cursor/extensions/aa_workflow
```

**Restart Cursor** after installation.

## Features

### 🚀 Activity Bar (Workflow Explorer)

Click the rocket icon in the Activity Bar (left sidebar) to open the Workflow Explorer:

- **Active Issues** - Your current Jira issues from memory
- **Open MRs** - Merge requests you're working on with pipeline status
- **Environments** - Stage/Prod health indicators
- **Follow-ups** - Tasks marked for follow-up with priority

### 📊 Status Bar

Real-time indicators in the bottom status bar:

| Indicator | What It Shows |
|-----------|---------------|
| 💬 Slack | Slack daemon status (running/stopped) |
| 🎫 Issue | Current active Jira issue |
| 🌍 Env | Environment health (stage/prod) |
| 🔀 MR | Active merge request with pipeline status |

Click any indicator for quick actions.

### ⚡ Command Palette

Access all commands via `Ctrl+Shift+P`:

| Command | Description |
|---------|-------------|
| AI Workflow: Open Dashboard | Rich visual overview panel |
| AI Workflow: Visualize Skill | Watch skill execution as flowchart |
| AI Workflow: Run Skill | Execute any skill |
| AI Workflow: Start Work on Issue | Begin work on a Jira issue |
| AI Workflow: Morning Briefing | Run `/coffee` skill |
| AI Workflow: End of Day Summary | Run `/beer` skill |
| AI Workflow: Open Current Jira Issue | Open issue in browser |
| AI Workflow: Open Current MR | Open MR in browser |
| AI Workflow: Investigate Alert | Triage current alerts |
| AI Workflow: Refresh Status | Update all status indicators |

### 🔔 Notifications

Toast notifications for important events:

- MR pipeline failures
- Review requests
- Environment health changes
- Slack messages requiring attention

### 📈 Dashboard

The Dashboard webview (`AI Workflow: Open Dashboard`) shows:

- Active work summary
- Environment health cards
- Recent activity log
- Quick action buttons

### 🎬 Skill Visualizer

Watch skills execute in real-time (`AI Workflow: Visualize Skill`):

- Flowchart of skill steps
- Step-by-step progress
- Tool call details
- Success/failure highlighting

## Configuration

Settings in VSCode/Cursor preferences:

```json
{
  "aa_workflow.refreshInterval": 30,
  "aa_workflow.showSlackStatus": true,
  "aa_workflow.showActiveIssue": true,
  "aa_workflow.showEnvironment": true,
  "aa_workflow.showActiveMR": true
}
```

## Data Sources

The extension reads from:

- `memory/state/current_work.yaml` - Active issues, MRs, follow-ups
- `memory/state/environments.yaml` - Environment health
- D-Bus signals from Slack daemon (if running)

## Development

```bash
# Watch mode for development
make ext-watch

# Build only
make ext-build

# Clean build artifacts
make ext-clean
```

## Troubleshooting

### Extension not showing

1. Check the extension is linked: `ls -la ~/.cursor/extensions/aa_workflow`
2. Reload Cursor: `Ctrl+Shift+P` → "Developer: Reload Window"
3. Check Output panel: `View` → `Output` → Select "AI Workflow"

### No data in tree view

1. Ensure memory files exist: `ls ~/src/redhat-ai-workflow/memory/state/`
2. Run `/coffee` or `/start-work` to populate memory
3. Click refresh in the tree view header

### Status bar items missing

Check settings: `Ctrl+,` → Search "aa_workflow" → Enable desired indicators
