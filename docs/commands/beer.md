# /beer

> Wind down your work day with a summary of what you accomplished and prep for tomorrow.

## Overview

Wind down your work day with a summary of what you accomplished and prep for tomorrow.

**Underlying Skill:** `beer`

This command is a wrapper that calls the `beer` skill. For detailed process information, see [skills/beer.md](../skills/beer.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `cleanup_prompts` | No | - |

## Usage

### Examples

```bash
skill_run("beer")
```

```bash
# Skip cleanup reminders
skill_run("beer", '{"cleanup_prompts": false}')

# Skip standup generation
skill_run("beer", '{"generate_standup": false}')
```

```bash
# 🍺 Cheers, Dave!

**Thursday, 2025-12-25** | 17:30 Irish time

---

## ✅ Today's Wins
**3** commits pushed:
- `abc1234` AAP-60034 - fix billing race condition
- `def5678` AAP-60034 - add tests
- `ghi9012` AAP-60034 - update docs

## 📊 This Week's Stats
- **12** commits
- **+847** / **-234** lines

## 🔄 Uncommitted Work
⚠️ Don't forget to commit or stash:
- **automation-analytics-backend**: 2 changed files

## ⏰ Tomorrow's Schedule
**⚠️ Early meetings:**
- **09:30** Team Standup 📹

## 🧹 Cleanup Reminders
- 🧪 Release `ephemeral-abc123`? (expires 2h)
- 🌿 Delete merged branch `AAP-59793-fix`?

## 📝 Tomorrow's Standup (ready to paste)
**Yesterday:** Fixed billing race conditions
**Today:** Continue Python 3.12 readiness
**Blockers:** None

---

🍺 Have a good evening!
```

## Process Flow

This command invokes the `beer` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /beer]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call beer skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [beer skill documentation](../skills/beer.md).

## Details

## Instructions

Get your end of day wrap-up:

```
skill_run("beer")
```

## What You'll Get

| Section | Description |
|---------|-------------|
| ✅ Wins | Commits pushed today |
| 📊 Stats | Lines changed this week |
| 🔄 WIP | Uncommitted changes to stash/commit |
| 🔀 PRs | Your open PRs status |
| ⏰ Tomorrow | Early meetings to prep for |
| 🧹 Cleanup | Stale branches, expiring ephemeral envs |
| 📝 Standup | Auto-generated notes ready to paste |

## Options

```bash
# Skip cleanup reminders
skill_run("beer", '{"cleanup_prompts": false}')

# Skip standup generation
skill_run("beer", '{"generate_standup": false}')
```text

## Example Output

```
# 🍺 Cheers, Dave!

**Thursday, 2025-12-25** | 17:30 Irish time

---

## ✅ Today's Wins
**3** commits pushed:
- `abc1234` AAP-60034 - fix billing race condition
- `def5678` AAP-60034 - add tests
- `ghi9012` AAP-60034 - update docs

## 📊 This Week's Stats
- **12** commits
- **+847** / **-234** lines

## 🔄 Uncommitted Work
⚠️ Don't forget to commit or stash:
- **automation-analytics-backend**: 2 changed files

## ⏰ Tomorrow's Schedule
**⚠️ Early meetings:**
- **09:30** Team Standup 📹

## 🧹 Cleanup Reminders
- 🧪 Release `ephemeral-abc123`? (expires 2h)
- 🌿 Delete merged branch `AAP-59793-fix`?

## 📝 Tomorrow's Standup (ready to paste)
**Yesterday:** Fixed billing race conditions
**Today:** Continue Python 3.12 readiness
**Blockers:** None

---

🍺 Have a good evening!
```

## Pair with /coffee

Start your day with `/coffee`, end it with `/beer`:

| Command | When | Purpose |
|---------|------|---------|
| `/coffee` | Morning | What needs attention today |
| `/beer` | Evening | What you accomplished, prep for tomorrow |


## Related Commands

_(To be determined based on command relationships)_
