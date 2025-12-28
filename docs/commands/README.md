# 🎯 Cursor Commands Reference

Cursor commands are slash commands you can invoke directly in the Cursor IDE chat. Type `/` to see available commands.

## Quick Reference

| Category | Commands |
|----------|----------|
| [☀️ Daily Workflow](#️-daily-workflow) | `/coffee`, `/beer`, `/standup` |
| [🔧 Development](#-development) | `/start-work`, `/create-mr`, `/mark-ready`, `/close-issue`, `/sync-branch`, `/jira-hygiene` |
| [👀 Code Review](#-code-review) | `/review-mr`, `/review-all-open`, `/check-feedback`, `/review`, `/review-mr-with-tests` |
| [🧪 Testing](#-testing) | `/deploy-ephemeral`, `/check-namespaces`, `/run-local-tests` |
| [🚨 Operations](#-operations) | `/investigate-alert`, `/debug-prod`, `/release-prod`, `/vpn` |
| [🔍 Discovery](#-discovery) | `/tools`, `/agents`, `/list-skills`, `/smoke-tools`, `/smoke-skills` |
| [📅 Calendar & Email](#-calendar--email) | `/my-calendar`, `/schedule-meeting`, `/setup-gmail`, `/google-reauth` |
| [🛠️ Utilities](#️-utilities) | `/debug-tool`, `/deploy`, `/create-issue`, `/load-developer`, `/load-devops` |

---

## ☀️ Daily Workflow

### `/coffee` ☕
**Morning briefing** - Everything you need at the start of your work day.

```
skill_run("coffee")
skill_run("coffee", '{"days_back": 7}')
```

| Section | Description |
|---------|-------------|
| 📅 Calendar | Today's meetings with Meet links |
| 📧 Email | Unread count, categorized (people vs newsletters) |
| 🔀 PRs | Your open PRs, feedback waiting, failed pipelines |
| 👀 Reviews | PRs assigned to you for review |
| 🧪 Ephemeral | Your active test environments with expiry times |
| 📝 Yesterday | Your commits from yesterday (for standup) |
| 📋 Jira | Sprint activity for the day/week |
| 🚀 Merges | Recently merged code in aa-backend |
| 🚨 Alerts | Any firing Prometheus alerts |
| 🎯 Actions | Smart suggestions based on all the above |

---

### `/beer` 🍺
**End of day wrap-up** - Review what you accomplished and prep for tomorrow.

```
skill_run("beer")
skill_run("beer", '{"generate_standup": true}')
```

| Section | Description |
|---------|-------------|
| ✅ Wins | Commits pushed, PRs merged, issues closed |
| 📊 Stats | Lines changed, files touched |
| 🔄 WIP | Uncommitted changes, draft PRs |
| ⏰ Tomorrow | Early meetings, deadlines |
| 🧹 Cleanup | Stale branches, expiring ephemeral envs |
| 📝 Standup | Auto-generated standup notes |
| 🎯 Follow-ups | PRs needing attention tomorrow |

---

### `/standup` 📝
**Generate standup summary** from recent activity.

```
skill_run("standup_summary")
skill_run("standup_summary", '{"days": 2}')
```

Includes: Git commits, Jira issues worked on, MRs created/reviewed, issues closed.

---

## 🔧 Development

### `/start-work` 🚀
**Begin or resume working on a Jira issue.**

```
skill_run("start_work", '{"issue_key": "AAP-12345"}')
```

What it does:
- Gets issue context from Jira
- Creates or checks out feature branch
- Shows MR feedback if exists
- Updates Jira status to "In Progress"

---

### `/create-mr` 📤
**Create a merge request** with full validation.

```
skill_run("create_mr", '{"issue_key": "AAP-12345"}')
skill_run("create_mr", '{"issue_key": "AAP-12345", "draft": false}')
```

What it does:
- Checks for uncommitted changes
- Validates commit message format
- Runs black/flake8 linting
- Creates MR with proper description
- Links to Jira and updates status

---

### `/mark-ready` 📢
**Remove draft status** from an MR and notify the team.

```
skill_run("mark_mr_ready", '{"mr_id": 1234}')
skill_run("mark_mr_ready", '{"mr_id": 1234, "issue_key": "AAP-12345"}')
```

What it does:
- Removes "Draft:" prefix from MR title
- Posts to team Slack channel
- Updates Jira status to "In Review"

---

### `/close-issue` ✅
**Close a Jira issue** and add a summary comment from commits.

```
skill_run("close_issue", '{"issue_key": "AAP-12345"}')
```

What it does:
- Finds commits referencing the issue
- Generates summary comment
- Transitions issue to Done

---

### `/sync-branch` 🔄
**Quickly rebase current branch onto main.**

```
skill_run("sync_branch")
skill_run("sync_branch", '{"force_push": true}')
```

What it does:
- Fetches latest from remote
- Stashes uncommitted changes
- Rebases onto main
- Restores stashed changes

---

### `/jira-hygiene` 🧹
**Check and fix Jira issue quality** before you start coding.

```
skill_run("jira_hygiene", '{"issue_key": "AAP-12345"}')
skill_run("jira_hygiene", '{"issue_key": "AAP-12345", "auto_fix": true}')
```

Checks: Description, Acceptance Criteria, Labels, Priority, Epic Link, Story Points, Formatting.

---

## 👀 Code Review

### `/review-mr` 👁️
**Review a single merge request.**

```
skill_run("review_pr", '{"mr_id": 1234}')
skill_run("review_pr", '{"issue_key": "AAP-12345"}')
```

---

### `/review-all-open` 👀
**Review all open MRs** in a project.

```
skill_run("review_all_prs")
skill_run("review_all_prs", '{"limit": 5}')
```

Automatically excludes your own MRs and handles previous feedback.

---

### `/check-feedback` 💬
**Check your open MRs for feedback** that needs your attention.

```
skill_run("check_mr_feedback")
```

Scans for: Human reviewer comments, meeting requests, code change requests, questions.

---

### `/review` 🔍
General review command - alias for `/review-mr`.

---

### `/review-mr-with-tests` 🧪
Review an MR and run local tests as part of the review.

```
skill_run("review_pr", '{"mr_id": 1234, "run_tests": true}')
```

---

## 🧪 Testing

### `/deploy-ephemeral` 🚀
**Deploy an MR's image to an ephemeral namespace** for testing.

```
skill_run("test_mr_ephemeral", '{"mr_id": 1459}')
skill_run("test_mr_ephemeral", '{"mr_id": 1459, "billing": true}')
```

What it does:
1. Gets commit SHA from MR
2. Checks Konflux has built the image
3. Reserves ephemeral namespace
4. Deploys using full SHA image tag
5. Optionally runs tests

---

### `/check-namespaces` 📦
**List your active ephemeral environments.**

```
bonfire_namespace_list(mine_only=True)
```

Shows namespace, expiry time, and deployed components.

---

### `/run-local-tests` 🧪
**Run tests locally** before pushing.

```
test_run(repo='backend')
test_run(repo='backend', coverage=True)
```

---

## 🚨 Operations

### `/investigate-alert` 🚨
**Quick triage of a firing Prometheus alert.**

```
skill_run("investigate_alert", '{"environment": "stage"}')
skill_run("investigate_alert", '{"environment": "prod"}')
```

What it does:
1. Gets current firing alerts
2. Quick health check (pods, deployments)
3. Checks recent events
4. Looks for known patterns
5. Escalates if serious

---

### `/debug-prod` 🔍
**Deep investigation of production issues.**

```
skill_run("debug_prod")
skill_run("debug_prod", '{"pod_filter": "processor", "time_range": "6h"}')
```

Gathers: Pod status, recent logs, metrics, alerts, recent deployments, Kubernetes events.

---

### `/release-prod` 🚀
**Release to production** - guide through stage → prod promotion.

```
skill_run("release_aa_backend_prod", '{"commit_sha": "abc123..."}')
skill_run("release_aa_backend_prod", '{"commit_sha": "abc123...", "include_billing": true}')
```

What it does:
1. Validates commit exists in stage
2. Checks Quay for built image
3. Updates app-interface
4. Creates MR for approval

---

### `/vpn` 🔐
**Connect to Red Hat VPN** for internal resources.

```
vpn_connect()
```

Required for: GitLab, ephemeral clusters, stage cluster, Konflux, internal APIs.

---

## 🔍 Discovery

### `/tools` 🔧
**Discover all available MCP tools.**

```
tool_list()
tool_list(module='git')
tool_list(module='gitlab')
```

Shows 150+ tools across 15 modules.

---

### `/agents` 🤖
**Switch between specialized agent personas.**

```
agent_load("developer")   # coding, PRs
agent_load("devops")      # k8s, ephemeral, deployments
agent_load("incident")    # logs, alerts, investigation
agent_load("release")     # konflux, quay, app-interface
```

---

### `/list-skills` 📋
**List all available skills.**

```
skill_list()
```

---

### `/smoke-tools` 🧪
**Test all MCP tools** - verify connectivity and authentication.

Automatically authenticates to Kubernetes clusters and tests all tool modules.

---

### `/smoke-skills` 🧪
**Test all skills** - verify skill definitions load correctly.

---

## 📅 Calendar & Email

### `/my-calendar` 📅
**Show today's calendar events.**

```
# Uses Google Calendar API
```

---

### `/schedule-meeting` 📆
**Create a Google Calendar event** with Meet link.

```
# Creates calendar event with video conferencing
```

---

### `/setup-gmail` 📧
**Enable Gmail API access** for email features.

Run this first time to add Gmail scopes to your Google OAuth.

---

### `/google-reauth` 🔑
**Re-authenticate Google APIs** when tokens expire.

---

## 🛠️ Utilities

### `/debug-tool` 🔧
**Debug a failed MCP tool** - analyze source and propose fixes.

```
debug_tool('bonfire_namespace_release', 'error message here')
```

---

### `/deploy` 🚀
General deployment command.

---

### `/create-issue` 🎫
**Create a Jira issue** with proper formatting.

```
skill_run("create_jira_issue", '{
  "summary": "Add feature X",
  "issue_type": "story",
  "description": "## Overview\n\nDescription here..."
}')
```

---

### `/load-developer` 👨‍💻
Quick command to load the developer agent.

```
agent_load("developer")
```

---

### `/load-devops` 🔧
Quick command to load the devops agent.

```
agent_load("devops")
```

---

## Command Locations

All commands are defined in `.cursor/commands/`:

```
.cursor/commands/
├── agents.md
├── beer.md
├── check-feedback.md
├── check-namespaces.md
├── close-issue.md
├── coffee.md
├── create-issue.md
├── create-mr.md
├── debug-prod.md
├── debug-tool.md
├── deploy-ephemeral.md
├── deploy.md
├── google-reauth.md
├── investigate-alert.md
├── jira-hygiene.md
├── list-skills.md
├── load-developer.md
├── load-devops.md
├── mark-ready.md
├── my-calendar.md
├── release-prod.md
├── review-all-open.md
├── review-mr-with-tests.md
├── review-mr.md
├── review.md
├── run-local-tests.md
├── schedule-meeting.md
├── setup-gmail.md
├── smoke-skills.md
├── smoke-tools.md
├── standup.md
├── start-work.md
├── sync-branch.md
├── tools.md
└── vpn.md
```

## Creating Custom Commands

To create a new command, add a `.md` file to `.cursor/commands/`:

```markdown
# 🎯 My Custom Command

Description of what it does.

## Instructions

```
skill_run("my_skill", '{"param": "value"}')
```
```

The command name comes from the filename (e.g., `my-command.md` → `/my-command`).
