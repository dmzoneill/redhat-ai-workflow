---
name: beer
description: "Wind down your work day with a summary of what you accomplished and prep for tomorrow."
arguments:
  - name: cleanup_prompts
---
# 🍺 End of Day Wrap-Up

Wind down your work day with a summary of what you accomplished and prep for tomorrow.

## Instructions

Get your end of day wrap-up:

```text
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
