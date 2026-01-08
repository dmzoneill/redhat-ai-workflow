<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://capsule-render.vercel.app/api?type=waving&color=0:667eea,100:764ba2&height=200&section=header&text=AI%20Workflow&fontSize=80&fontColor=fff&animation=twinkling&fontAlignY=35&desc=Your%20AI-Powered%20Development%20Command%20Center&descSize=20&descAlignY=55">
  <img src="https://capsule-render.vercel.app/api?type=waving&color=0:667eea,100:764ba2&height=200&section=header&text=AI%20Workflow&fontSize=80&fontColor=fff&animation=twinkling&fontAlignY=35&desc=Your%20AI-Powered%20Development%20Command%20Center&descSize=20&descAlignY=55" alt="AI Workflow Header"/>
</picture>

<div align="center">

[![MCP](https://img.shields.io/badge/MCP-Protocol-6366f1?style=for-the-badge&logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZmlsbD0iI2ZmZiIgZD0iTTEyIDJDNi40OCAyIDIgNi40OCAyIDEyczQuNDggMTAgMTAgMTAgMTAtNC40OCAxMC0xMFMxNy41MiAyIDEyIDJ6bTAgMThjLTQuNDEgMC04LTMuNTktOC04czMuNTktOCA4LTggOCAzLjU5IDggOC0zLjU5IDgtOCA4eiIvPjxjaXJjbGUgZmlsbD0iI2ZmZiIgY3g9IjEyIiBjeT0iMTIiIHI9IjQiLz48L3N2Zz4=)](https://modelcontextprotocol.io/)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Claude](https://img.shields.io/badge/Claude-Anthropic-FF6B6B?style=for-the-badge&logo=anthropic&logoColor=white)](https://anthropic.com/)
[![Cursor](https://img.shields.io/badge/Cursor-IDE-000000?style=for-the-badge&logo=cursor&logoColor=white)](https://cursor.sh/)
[![Tools](https://img.shields.io/badge/Tools-270-10b981?style=for-the-badge&logo=toolbox&logoColor=white)](#-tool-modules)
[![Skills](https://img.shields.io/badge/Skills-53-f59e0b?style=for-the-badge&logo=lightning&logoColor=white)](#-skills)
[![License](https://img.shields.io/badge/License-MIT-f59e0b?style=for-the-badge)](LICENSE)

**Transform Claude into your personal DevOps engineer, developer assistant, and incident responder.**

*Works with both **Claude Code** and **Cursor IDE***

[Getting Started](#-quick-start) •
[Commands](docs/commands/README.md) •
[Skills](docs/skills/README.md) •
[Personas](docs/personas/README.md) •
[Tool Modules](docs/tool-modules/README.md) •
[Architecture](docs/architecture/README.md)

</div>

---

## ✨ What is This?

AI Workflow is a **comprehensive MCP (Model Context Protocol) server** that gives Claude AI superpowers for software development:

| Capability | Description |
|------------|-------------|
| 🔧 **Execute Actions** | Create branches, update Jira, deploy code |
| 🧠 **Remember Context** | Track your work across sessions |
| 🎭 **Adopt Personas** | DevOps, Developer, Incident modes |
| ⚡ **Run Workflows** | Multi-step skills that chain tools |
| 🔄 **Auto-Heal** | Detect failures, fix auth/VPN, retry automatically |
| 🔍 **Self-Debug** | Analyze and fix its own tools |

---

## 🚀 Quick Start

### 1️⃣ Clone & Install

```bash
git clone https://github.com/yourusername/ai-workflow.git ~/src/ai-workflow
cd ~/src/ai-workflow

# Option 1: Using UV (recommended - fast!)
uv venv
uv pip install -e .

# Option 2: Traditional pip
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

> **Don't have UV?** Install it: `curl -LsSf https://astral.sh/uv/install.sh | sh`

### 2️⃣ Configure Your IDE

<details>
<summary><strong>🔷 Claude Code (claude.ai/code)</strong></summary>

Create `.mcp.json` in your **project root**:

```json
{
  "mcpServers": {
    "aa_workflow": {
      "command": "bash",
      "args": [
        "-c",
        "cd ~/src/ai-workflow && source .venv/bin/activate && python3 -m server"
      ]
    }
  }
}
```

Then restart Claude Code or run `/mcp` to reload.

</details>

<details>
<summary><strong>⬛ Cursor IDE</strong></summary>

Create `.cursor/mcp.json` in your **project directory**:

```json
{
  "mcpServers": {
    "aa_workflow": {
      "command": "bash",
      "args": [
        "-c",
        "cd ~/src/ai-workflow && source .venv/bin/activate && python3 -m server"
      ]
    }
  }
}
```

Then restart Cursor (Cmd/Ctrl+Shift+P → "Reload Window").

</details>

> **Default Persona:** The server starts with the `developer` persona loaded by default (~78 tools). Use `persona_load("devops")` to switch.

### 3️⃣ Restart & Go!

```
You: Load the developer persona

Claude: 👨‍💻 Developer Persona Loaded
        Tools: workflow, git_basic, gitlab_basic, jira_basic (~78 tools)

You: Start working on AAP-12345

Claude: [Runs start_work skill]
        ✅ Created branch: aap-12345-implement-api
        ✅ Updated Jira: In Progress
        Ready to code!
```

---

## 💬 Slack Bot Setup

The Slack bot is an autonomous agent that monitors channels, responds to queries, and investigates alerts.

### 1. Get Slack Credentials

The bot uses Slack's web API. Extract credentials from Chrome:

```bash
pip install pycookiecheat
python scripts/get_slack_creds.py
```

### 2. Configure

Add to `config.json`:

```json
{
  "slack": {
    "auth": {
      "xoxc_token": "xoxc-...",
      "d_cookie": "xoxd-...",
      "workspace_id": "E...",
      "host": "your-company.enterprise.slack.com"
    },
    "channels": {
      "team": { "id": "C01234567", "name": "my-team" }
    },
    "alert_channels": {
      "C089XXXXXX": { "name": "alerts", "environment": "stage" }
    }
  }
}
```

### 3. Configure Claude AI (Optional)

For autonomous responses:

```bash
# Vertex AI (recommended)
export CLAUDE_CODE_USE_VERTEX=1
export ANTHROPIC_VERTEX_PROJECT_ID="your-gcp-project"

# Or Anthropic API
export ANTHROPIC_API_KEY="your-key"
```

### 4. Run

```bash
# Test credentials
make slack-test

# Foreground (Ctrl+C to stop)
make slack-daemon

# Background with D-Bus control
make slack-daemon-bg
make slack-status
make slack-daemon-logs
make slack-daemon-stop
```

See [Slack Persona docs](docs/personas/slack.md) for full setup guide.

---

## 🎭 Personas (Tool Profiles)

> **Note:** "Agents" in this project are **tool configuration profiles** (personas), not separate AI instances. When you "load an agent," you're configuring which tools Claude has access to.

Switch personas to get different tool sets. See [full persona reference](docs/personas/README.md).

| Persona | Command | Tools | Focus |
|---------|---------|-------|-------|
| [👨‍💻 developer](docs/personas/developer.md) | `Load developer persona` | ~78 | Daily coding, PRs |
| [🔧 devops](docs/personas/devops.md) | `Load devops persona` | ~83 | Deployments, K8s |
| [🚨 incident](docs/personas/incident.md) | `Load incident persona` | ~89 | Production debugging |
| [📦 release](docs/personas/release.md) | `Load release persona` | ~91 | Shipping releases |
| [💬 slack](docs/personas/slack.md) | `Load slack persona` | ~85 | Slack bot daemon |

```mermaid
graph LR
    DEV[👨‍💻 Developer] --> |"persona_load"| DEVOPS[🔧 DevOps]
    DEVOPS --> |"persona_load"| INCIDENT[🚨 Incident]
    INCIDENT --> |"persona_load"| DEV

    style DEV fill:#3b82f6,stroke:#2563eb,color:#fff
    style DEVOPS fill:#10b981,stroke:#059669,color:#fff
    style INCIDENT fill:#ef4444,stroke:#dc2626,color:#fff
```

---

## ⚡ Skills

Skills are reusable multi-step workflows with **built-in auto-healing**. See [full skills reference](docs/skills/README.md).

### Daily Workflow

| Time | Command | What It Does |
|------|---------|--------------|
| ☕ Morning | `/coffee` | Email, PRs, calendar, Jira summary |
| 💻 Work | `/start-work AAP-12345` | Create branch, update Jira |
| 🚀 Submit | `/create-mr` | Validate, lint, create MR |
| 🍺 Evening | `/beer` | Wrap-up, standup prep |

### Popular Skills

| Skill | Description | Auto-Heal |
|-------|-------------|-----------|
| [☕ coffee](docs/skills/coffee.md) | Morning briefing | ✅ |
| [🍺 beer](docs/skills/beer.md) | End-of-day wrap-up | ✅ |
| [⚡ start_work](docs/skills/start_work.md) | Begin Jira issue | ✅ VPN + Auth |
| [🚀 create_mr](docs/skills/create_mr.md) | Create MR + Slack notify | ✅ VPN + Auth |
| [✅ mark_mr_ready](docs/skills/mark_mr_ready.md) | Mark draft as ready | ✅ |
| [👀 review_pr](docs/skills/review_pr.md) | Review MR | ✅ VPN + Auth |
| [🔄 sync_branch](docs/skills/sync_branch.md) | Rebase onto main | ✅ VPN |
| [📋 standup_summary](docs/skills/standup_summary.md) | Generate standup | ✅ |
| [🧪 test_mr_ephemeral](docs/skills/test_mr_ephemeral.md) | Deploy to ephemeral | ✅ VPN + Auth |
| [🚨 investigate_alert](docs/skills/investigate_alert.md) | Triage alerts | ✅ VPN + Auth |
| [🎫 create_jira_issue](docs/skills/create_jira_issue.md) | Create Jira issue | ✅ |
| [✅ close_issue](docs/skills/close_issue.md) | Close issue with summary | ✅ VPN |

### 🔄 Auto-Heal via Python Decorators

MCP tools include **auto-healing** via Python decorators (`server/auto_heal_decorator.py`). When a tool fails due to VPN or auth issues:

1. **Checks memory** for known fixes via `check_known_issues()`
2. **Detects** the failure pattern (network timeout, unauthorized, forbidden)
3. **Fixes** by calling `vpn_connect()` or `kube_login()`
4. **Retries** the operation automatically
5. **Logs** the fix to `memory/learned/tool_failures.yaml` for future reference

```python
from server.auto_heal_decorator import auto_heal_k8s

@registry.tool()
@auto_heal_k8s()
async def kubectl_get_pods(namespace: str, environment: str = "stage") -> str:
    """Get pods - auto-heals VPN/auth failures."""
    ...
```

| Decorator | Use Case |
|-----------|----------|
| `@auto_heal_ephemeral()` | Bonfire namespace tools |
| `@auto_heal_konflux()` | Tekton pipeline tools |
| `@auto_heal_k8s()` | Kubectl tools |
| `@auto_heal_jira()` | Jira tools |
| `@auto_heal_git()` | Git/GitLab tools |

---

## 🎯 Slash Commands

64 slash commands for quick access. See [full commands reference](docs/commands/README.md).

| Category | Commands |
|----------|----------|
| ☀️ **Daily** | `/coffee` `/beer` `/standup` `/weekly-summary` |
| 🔧 **Development** | `/start-work` `/create-mr` `/mark-ready` `/close-issue` `/sync-branch` `/rebase-pr` `/hotfix` |
| 👀 **Review** | `/review-mr` `/review-all-open` `/check-feedback` `/check-prs` `/close-mr` |
| 🧪 **Testing** | `/deploy-ephemeral` `/test-ephemeral` `/check-namespaces` `/extend-ephemeral` `/run-local-tests` |
| 🚨 **Operations** | `/investigate-alert` `/debug-prod` `/release-prod` `/env-overview` `/rollout-restart` `/scale-deployment` `/silence-alert` |
| 📋 **Jira** | `/jira-hygiene` `/create-issue` `/clone-issue` `/sprint-planning` |
| 🔍 **Discovery** | `/tools` `/personas` `/list-skills` `/smoke-tools` `/smoke-skills` `/memory` |
| 📅 **Calendar** | `/my-calendar` `/schedule-meeting` `/setup-gmail` `/google-reauth` |
| 🔐 **Infrastructure** | `/vpn` `/konflux-status` `/appinterface-check` `/ci-health` `/cancel-pipeline` `/check-secrets` `/scan-vulns` |

### Example Workflow

```bash
/coffee                    # Morning briefing
/start-work AAP-12345      # Begin work on issue
# ... code ...
/create-mr                 # Create merge request
/deploy-ephemeral          # Test in ephemeral
/mark-ready                # Remove draft, notify team
# ... review cycle ...
/close-issue AAP-12345     # Wrap up
/beer                      # End of day summary
```

---

## 🔧 Tool Modules

~270 tools across 17 modules. See [full MCP server reference](docs/tool-modules/README.md).

| Module | Tools | Description |
|--------|-------|-------------|
| [workflow](docs/tool-modules/workflow.md) | 16 | Core workflow, agents, skills, memory |
| [git](docs/tool-modules/git.md) | 30 | Git operations |
| [gitlab](docs/tool-modules/gitlab.md) | 30 | MRs, pipelines, code review |
| [jira](docs/tool-modules/jira.md) | 28 | Issue tracking |
| [k8s](docs/tool-modules/k8s.md) | 28 | Kubernetes operations |
| [bonfire](docs/tool-modules/bonfire.md) | 20 | Ephemeral environments |
| [quay](docs/tool-modules/quay.md) | 8 | Container registry |
| [prometheus](docs/tool-modules/prometheus.md) | 13 | Metrics queries |
| [alertmanager](docs/tool-modules/alertmanager.md) | 7 | Alert management |
| [kibana](docs/tool-modules/kibana.md) | 9 | Log search |
| [google_calendar](docs/tool-modules/google_calendar.md) | 6 | Calendar & meetings |
| [gmail](docs/tool-modules/gmail.md) | 6 | Email processing |
| [slack](docs/tool-modules/slack.md) | 10 | Slack integration |
| [konflux](docs/tool-modules/konflux.md) | 35 | Build pipelines |
| [appinterface](docs/tool-modules/appinterface.md) | 7 | GitOps config |
| lint | 7 | Python/YAML linting |
| dev_workflow | 9 | Development helpers |

> Plus **45+ shared parsers** in `scripts/common/parsers.py` and **config helpers** in `scripts/common/config_loader.py`

See [MCP Server Architecture](docs/architecture/README.md) for implementation details.

---

## 🛠️ Auto-Debug & Learning Loop

When tools fail, Claude can fix them **and remember the fix forever**:

```
Tool: ❌ Failed to release namespace
      💡 Known Issues Found!
         Previous fix for `bonfire_release`: Add --force flag

      💡 Auto-fix: debug_tool('bonfire_namespace_release')
```

### The Learning Loop

```
┌────────────────────────────────────────────────────────────────┐
│  Tool fails → Check memory → Apply known fix → ✓              │
│       ↓                                                        │
│  Unknown? → debug_tool() → Fix code → learn_tool_fix() → ✓    │
│                                              ↓                 │
│                                    Saved to memory forever     │
└────────────────────────────────────────────────────────────────┘
```

### Key Tools

| Tool | Purpose |
|------|---------|
| `check_known_issues(tool, error)` | Check if we've seen this before |
| `debug_tool(tool, error)` | Analyze source and propose fix |
| `learn_tool_fix(tool, pattern, cause, fix)` | Save fix to memory |

### Session Start with Memory

When you start a session with `session_start()`, the system automatically:

1. **Loads current work state** - Active issues, branches, MRs
2. **Loads learned patterns** - Shows count of patterns by category
3. **Shows loaded tools** - Which tool modules are active
4. **Provides guidance** - Prefer MCP tools over raw CLI commands

```
You: session_start(agent="developer")

Claude: 📋 Session Started
        🧠 Learned Patterns: 12 patterns loaded
           - Jira CLI: 3 patterns
           - Error handling: 5 patterns
           - Authentication: 4 patterns
        🛠️ Currently Loaded Tools: git, gitlab, jira (~95 tools)
```

### Memory Files

| File | Purpose |
|------|---------|
| `memory/learned/tool_fixes.yaml` | Tool-specific fixes from auto-remediation |
| `memory/learned/patterns.yaml` | General error patterns and solutions |
| `memory/learned/runbooks.yaml` | Operational procedures that worked |
| `memory/learned/tool_failures.yaml` | Auto-heal history with success/failure tracking |
| `memory/state/current_work.yaml` | Active issues, branches, MRs |
| `memory/sessions/*.yaml` | Session logs for continuity |

---

## 📁 Project Structure

```
ai-workflow/
├── server/              # MCP server infrastructure
│   ├── main.py          # Server entry point
│   ├── persona_loader.py # Dynamic persona loading
│   ├── auto_heal_decorator.py  # Auto-heal decorators
│   └── utils.py         # Shared utilities
├── tool_modules/        # Tool plugins (aa_git/, aa_jira/, etc.)
├── personas/            # Persona configs (developer.yaml, devops.yaml)
├── skills/              # 53 workflow definitions (start_work.yaml, etc.)
├── memory/              # Persistent context
│   ├── state/           # Active issues, MRs, environments
│   └── learned/         # Patterns, tool fixes, runbooks
├── extensions/          # IDE integrations
│   └── aa_workflow-vscode/  # VSCode/Cursor extension
├── docs/                # Documentation
├── scripts/             # Python utilities
│   └── common/
│       ├── auto_heal.py   # Skill auto-healing utilities
│       ├── config_loader.py # Config helpers (commit format, repos)
│       └── parsers.py     # 44 shared parser functions
├── config.json          # Configuration (commit format, repos, Slack, etc.)
├── .cursor/commands/    # 64 slash commands (Cursor)
└── .claude/commands/    # 64 slash commands (Claude Code)
```

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [Commands Reference](docs/commands/README.md) | 64 slash commands (Claude/Cursor) |
| [Skills Reference](docs/skills/README.md) | All 53 available skills |
| [Personas Reference](docs/personas/README.md) | 5 tool configuration profiles |
| [Tool Modules Reference](docs/tool-modules/README.md) | 17 tool plugins with ~270 tools |
| [Learning Loop](docs/learning-loop.md) | Auto-remediation + memory |
| [Skill Auto-Heal](docs/plans/skill-auto-heal.md) | Auto-healing implementation |
| [IDE Extension](docs/ide-extension.md) | VSCode/Cursor extension |
| [Architecture Overview](docs/architecture/README.md) | High-level design |
| [MCP Server Implementation](docs/architecture/mcp-implementation.md) | Server code details |
| [Development Guide](docs/DEVELOPMENT.md) | Contributing and development setup |

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Submit a merge request

---

## 📄 License

MIT License - See [LICENSE](LICENSE) for details.

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://capsule-render.vercel.app/api?type=waving&color=0:667eea,100:764ba2&height=100&section=footer">
  <img src="https://capsule-render.vercel.app/api?type=waving&color=0:667eea,100:764ba2&height=100&section=footer" alt="Footer"/>
</picture>

<div align="center">
  <sub>Built with ❤️ for developers who want AI that actually does things</sub>
</div>
