# AI Workflow VSCode Extension

Real-time status indicators and quick actions for the AI Workflow system.

## Features

### Status Bar Items

The extension adds four status bar items (right side):

| Item | Shows | Click Action |
|------|-------|--------------|
| **Slack** | 🟢 Online / 🔴 Errors | Show full status |
| **Issue** | Active Jira issue key | Open in Jira |
| **Env** | Environment health | Investigate alerts |
| **MR** | Active merge request | Open in GitLab |

### Commands

Available via `Ctrl+Shift+P`:

- `AI Workflow: Show Status` - Full status in output panel
- `AI Workflow: Open Current Jira Issue` - Open in browser
- `AI Workflow: Open Current MR` - Open in browser
- `AI Workflow: Investigate Alert` - Launch investigation
- `AI Workflow: Refresh Status` - Force refresh
- `AI Workflow: Run Skill...` - Pick a skill to run
- `AI Workflow: Start Work on Issue` - Start work flow
- `AI Workflow: Morning Briefing (/coffee)` - Run coffee skill
- `AI Workflow: End of Day Summary (/beer)` - Run beer skill

## Installation

### Development Installation

1. Build the extension:
   ```bash
   cd extensions/aa-workflow-vscode
   npm install
   npm run compile
   ```

2. Install in Cursor/VSCode:
   - Open Extensions view
   - Click "..." → "Install from VSIX..."
   - Or press F5 in the extension folder to debug

### From Makefile

```bash
# Build the extension
make ext-build

# Install in Cursor (creates symlink)
make ext-install

# Watch for changes during development
make ext-watch
```

## Configuration

Settings in `settings.json`:

```json
{
  "aa-workflow.refreshInterval": 30,
  "aa-workflow.showSlackStatus": true,
  "aa-workflow.showActiveIssue": true,
  "aa-workflow.showEnvironment": true,
  "aa-workflow.showActiveMR": true
}
```

## Data Sources

The extension reads from:

1. **Memory files** (`~/.config/aa-workflow/memory/`)
   - `state/current_work.yaml` - Active issues, MRs
   - `state/environments.yaml` - Environment health

2. **D-Bus** (when Slack daemon running)
   - `com.aiworkflow.SlackAgent.GetStats` - Daemon statistics

## Development

```bash
# Watch and rebuild on changes
npm run watch

# Lint TypeScript
npm run lint

# Package for distribution
npx vsce package
```

## Architecture

```
┌────────────────────────────────────────────┐
│           VSCode Extension                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐ │
│  │ StatusBar│  │ Commands │  │ DataProv │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘ │
└───────┼─────────────┼─────────────┼────────┘
        │             │             │
        └─────────────┴──────┬──────┘
                             │
        ┌────────────────────┴───────────────┐
        │                                     │
        ▼                                     ▼
┌───────────────┐                    ┌───────────────┐
│ Memory Files  │                    │    D-Bus      │
│ (YAML state)  │                    │ (Slack stats) │
└───────────────┘                    └───────────────┘
```

## Future Phases

- **Phase 2**: Tree view sidebar with full work context
- **Phase 3**: Enhanced command palette
- **Phase 4**: Toast notifications
- **Phase 5**: Dashboard webview
- **Phase 6**: Skill execution visualizer
