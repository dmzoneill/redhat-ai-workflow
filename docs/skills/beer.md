# 🍺 beer

> End of day wrap-up - wind down and prepare for tomorrow

## Overview

The `beer` skill is your end-of-day assistant. It summarizes what you accomplished, highlights unfinished work, and prepares you for tomorrow—perfect for generating standup notes.

## Quick Start

```
skill_run("beer", '{}')
```

Or use the Cursor command:

```
/beer
```

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `generate_standup` | boolean | No | `true` | Generate standup notes |
| `cleanup_prompts` | boolean | No | `true` | Show cleanup reminders |

## Flow

```mermaid
flowchart TD
    START([🍺 Start]) --> CONFIG[Load Configuration]
    CONFIG --> TIME{What Time?}

    TIME -->|Before 5pm| EARLY[☀️ Wrapping up early]
    TIME -->|5-8pm| NORMAL[🍺 Cheers!]
    TIME -->|After 8pm| LATE[🌙 Burning midnight oil]

    EARLY --> GATHER
    NORMAL --> GATHER
    LATE --> GATHER

    GATHER[Gather Today's Activity] --> COMMITS[📝 Today's Commits]
    GATHER --> MERGED[✅ Merged PRs]
    GATHER --> CLOSED[📋 Closed Issues]

    COMMITS --> STATS[Calculate Stats]
    MERGED --> STATS
    CLOSED --> STATS

    STATS --> WIP[Check Work in Progress]
    WIP --> UNCOMMITTED[Uncommitted Changes?]
    WIP --> DRAFTS[Draft PRs?]
    WIP --> EXPIRING[Expiring Ephemeral?]

    UNCOMMITTED --> TOMORROW[Tomorrow's Schedule]
    DRAFTS --> TOMORROW
    EXPIRING --> TOMORROW

    TOMORROW --> STANDUP{Generate Standup?}
    STANDUP -->|Yes| NOTES[📝 Create Notes]
    STANDUP -->|No| DONE
    NOTES --> DONE([🌙 Done for the day!])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style DONE fill:#10b981,stroke:#059669,color:#fff
    style NORMAL fill:#f59e0b,stroke:#d97706,color:#fff
```

## Sections

| Section | Description |
|---------|-------------|
| ✅ **Today's Wins** | Commits pushed, PRs merged, issues closed |
| 📊 **Weekly Stats** | Lines added/removed, files touched |
| 🔄 **Still In Progress** | Uncommitted changes, draft PRs |
| 🔀 **Open PRs** | Your active and draft PRs |
| ⏰ **Tomorrow's Schedule** | Early meetings, deadlines |
| 🧹 **Cleanup Reminders** | Stale branches, expiring ephemeral envs |
| 📝 **Standup Prep** | Ready-to-paste standup notes |
| 🎯 **Follow-ups** | PRs needing attention tomorrow |

## MCP Tools Used

- `git_log` - Today's commits and stats
- `gitlab_mr_list` - Merged PRs, open PRs
- `jira_search` - Closed issues
- `git_status` - Uncommitted changes
- `bonfire_namespace_list` - Ephemeral environments
- `google_calendar_list_events` - Tomorrow's meetings

## Example Output

```
## 🍺 Cheers, Dave!

📊 **Today's Summary**
├── Commits: 5 pushed
├── PRs merged: 1 (!456)
├── Issues closed: 1 (AAP-12345)
└── Lines: +245 / -89

✅ **Wins**
└── Shipped new API endpoint (AAP-12345)

🔄 **Work in Progress**
├── !458: AAP-12348 - Draft (pipeline passed)
└── 3 uncommitted files in automation-analytics-backend

⏰ **Tomorrow**
├── 09:00 - Early standup call ⚠️
└── No deadlines this week

🧹 **Cleanup Reminders**
├── Branch `aap-12340-old-feature` (2 weeks stale)
└── ephemeral-nx6n2s expires in 45m

📝 **Standup Notes (copy-paste ready)**
─────────────────────────────────
**Yesterday:**
• Completed AAP-12345 - New API endpoint
• Code reviewed !455 (approved)

**Today:**
• Continue AAP-12348 - Fix database issue
• Address feedback on !458

**Blockers:**
• None
─────────────────────────────────

🌙 Have a great evening!
```

## Daily Workflow

| Time | Command | Purpose |
|------|---------|---------|
| ☕ Morning | `/coffee` | What needs attention today |
| 🍺 Evening | `/beer` | What you accomplished, prep for tomorrow |

## Related Skills

- [coffee](./coffee.md) - Morning briefing
- [standup_summary](./standup_summary.md) - Detailed standup generation
- [sync_branch](./sync_branch.md) - Quick sync before going home
