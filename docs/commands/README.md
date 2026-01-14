# 🎯 Cursor Commands Reference

Cursor commands are slash commands you can invoke directly in the Cursor IDE chat. Type `/` to see available commands.

**Total: 64 commands** across 10 categories.

## Quick Reference

| Category | Commands |
|----------|----------|
| [☀️ Daily Workflow](#️-daily-workflow) | `/coffee`, `/beer`, `/standup`, `/weekly-summary` |
| [🔧 Development](#-development) | `/start-work`, `/create-mr`, `/mark-ready`, `/close-issue`, `/sync-branch`, `/rebase-pr`, `/jira-hygiene`, `/hotfix` |
| [👀 Code Review](#-code-review) | `/review-mr`, `/review-all-open`, `/check-feedback`, `/check-prs`, `/close-mr`, `/review`, `/review-mr-with-tests` |
| [🧪 Testing](#-testing) | `/deploy-ephemeral`, `/test-ephemeral`, `/check-namespaces`, `/extend-ephemeral`, `/run-local-tests`, `/integration-tests` |
| [🚨 Operations](#-operations) | `/investigate-alert`, `/debug-prod`, `/release-prod`, `/env-overview`, `/rollout-restart`, `/scale-deployment`, `/silence-alert`, `/vpn` |
| [📋 Jira](#-jira-management) | `/create-issue`, `/clone-issue`, `/sprint-planning` |
| [📅 Calendar & Email](#-calendar--email) | `/my-calendar`, `/schedule-meeting`, `/setup-gmail`, `/google-reauth` |
| [🔐 Infrastructure](#-infrastructure) | `/konflux-status`, `/appinterface-check`, `/ci-health`, `/cancel-pipeline`, `/check-secrets`, `/scan-vulns` |
| [🔍 Discovery](#-discovery) | `/tools`, `/personas`, `/list-skills`, `/smoke-tools`, `/smoke-skills`, `/memory` |
| [🛠️ Utilities](#️-utilities) | `/debug-tool`, `/learn-fix`, `/learn-pattern`, `/deploy`, `/load-developer`, `/load-devops`, `/notify-mr`, `/notify-team`, `/memory-edit`, `/memory-cleanup`, `/memory-init` |

---

## ☀️ Daily Workflow

### `/coffee` ☕
**Morning briefing** - Everything you need at the start of your work day.

```text
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

```text
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

```text
skill_run("standup_summary")
skill_run("standup_summary", '{"days": 2}')
```

Includes: Git commits, Jira issues worked on, MRs created/reviewed, issues closed.

---

### `/weekly-summary` 📊
**Generate weekly activity report** for status updates.

```text
skill_run("weekly_summary")
```

---

## 🔧 Development

### `/start-work` 🚀
**Begin or resume working on a Jira issue.**

```text
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

```text
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

```text
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

```text
skill_run("close_issue", '{"issue_key": "AAP-12345"}')
```

What it does:
- Finds commits referencing the issue
- Generates summary comment
- Transitions issue to Done

---

### `/sync-branch` 🔄
**Quickly rebase current branch onto main.**

```text
skill_run("sync_branch")
skill_run("sync_branch", '{"force_push": true}')
```

What it does:
- Fetches latest from remote
- Stashes uncommitted changes
- Rebases onto main
- Restores stashed changes

---

### `/rebase-pr` 🔄
**Rebase a PR** with auto-conflict resolution hints.

```text
skill_run("rebase_pr", '{"mr_id": 1234}')
```

---

### `/jira-hygiene` 🧹
**Check and fix Jira issue quality** before you start coding.

```text
skill_run("jira_hygiene", '{"issue_key": "AAP-12345"}')
skill_run("jira_hygiene", '{"issue_key": "AAP-12345", "auto_fix": true}')
```

Checks: Description, Acceptance Criteria, Labels, Priority, Epic Link, Story Points, Formatting.

---

### `/hotfix` 🔥
**Create an emergency hotfix** branch.

```text
skill_run("hotfix", '{"issue_key": "AAP-12345"}')
```

---

## 👀 Code Review

### `/review-mr` 👁️
**Review a single merge request.**

```text
skill_run("review_pr", '{"mr_id": 1234}')
skill_run("review_pr", '{"issue_key": "AAP-12345"}')
```

---

### `/review-all-open` 👀
**Review all open MRs** in a project.

```text
skill_run("review_all_prs")
skill_run("review_all_prs", '{"limit": 5}')
```

Automatically excludes your own MRs and handles previous feedback.

---

### `/check-feedback` 💬
**Check your open MRs for feedback** that needs your attention.

```text
skill_run("check_mr_feedback")
```

Scans for: Human reviewer comments, meeting requests, code change requests, questions.

---

### `/check-prs` 📋
**Check status of your open PRs.**

```text
skill_run("check_my_prs")
```

---

### `/close-mr` ❌
**Close an abandoned merge request.**

```text
skill_run("close_mr", '{"mr_id": 1234}')
```

---

### `/review` 🔍
General review command - alias for `/review-mr`.

---

### `/review-mr-with-tests` 🧪
Review an MR and run local tests as part of the review.

```text
skill_run("review_pr", '{"mr_id": 1234, "run_tests": true}')
```

---

### `/review-mr-multiagent` 🤖
**Multi-agent code review** using specialized reviewer personas.

```text
skill_run("review_pr_multiagent", '{"mr_id": 1234}')
```

Uses Security, Performance, and Architecture reviewers in parallel.

---

## 🧪 Testing

### `/deploy-ephemeral` 🚀
**Deploy an MR's image to an ephemeral namespace** for testing.

```text
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

### `/test-ephemeral` 🧪
Alias for `/deploy-ephemeral`.

---

### `/check-namespaces` 📦
**List your active ephemeral environments.**

```text
bonfire_namespace_list(mine_only=True)
```

Shows namespace, expiry time, and deployed components.

---

### `/extend-ephemeral` ⏰
**Extend the TTL of an ephemeral namespace.**

```text
skill_run("extend_ephemeral", '{"namespace": "ephemeral-abc123"}')
```

---

### `/run-local-tests` 🧪
**Run tests locally** before pushing.

```text
test_run(repo='backend')
test_run(repo='backend', coverage=True)
```

---

### `/integration-tests` 🧪
**Check Konflux integration test status.**

```text
skill_run("check_integration_tests")
```

---

## 🚨 Operations

### `/investigate-alert` 🚨
**Quick triage of a firing Prometheus alert.**

```text
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

```text
skill_run("debug_prod")
skill_run("debug_prod", '{"pod_filter": "processor", "time_range": "6h"}')
```

Gathers: Pod status, recent logs, metrics, alerts, recent deployments, Kubernetes events.

---

### `/release-prod` 🚀
**Release to production** - guide through stage → prod promotion.

```text
skill_run("release_aa_backend_prod", '{"commit_sha": "abc123..."}')
skill_run("release_aa_backend_prod", '{"commit_sha": "abc123...", "include_billing": true}')
```

What it does:
1. Validates commit exists in stage
2. Checks Quay for built image
3. Updates app-interface
4. Creates MR for approval

---

### `/env-overview` 🌍
**Environment health overview** - check stage and prod status.

```text
skill_run("environment_overview")
```

---

### `/rollout-restart` 🔄
**Restart a deployment** via rollout restart.

```text
skill_run("rollout_restart", '{"deployment": "api", "environment": "stage"}')
```

---

### `/scale-deployment` 📈
**Scale a deployment** to specified replicas.

```text
skill_run("scale_deployment", '{"deployment": "api", "replicas": 3}')
```

---

### `/silence-alert` 🔇
**Silence a noisy alert** temporarily.

```text
skill_run("silence_alert", '{"alertname": "HighCPU", "duration": "2h"}')
```

---

### `/vpn` 🔐
**Connect to Red Hat VPN** for internal resources.

```text
vpn_connect()
```

Required for: GitLab, ephemeral clusters, stage cluster, Konflux, internal APIs.

---

## 📋 Jira Management

### `/create-issue` 🎫
**Create a Jira issue** with proper formatting.

```text
skill_run("create_jira_issue", '{
  "summary": "Add feature X",
  "issue_type": "story",
  "description": "## Overview\n\nDescription here..."
}')
```

---

### `/clone-issue` 📋
**Clone an existing Jira issue.**

```text
skill_run("clone_jira_issue", '{"issue_key": "AAP-12345"}')
```

---

### `/sprint-planning` 📊
**Assist with sprint planning.**

```text
skill_run("sprint_planning")
```

---

## 📅 Calendar & Email

### `/my-calendar` 📅
**Show today's calendar events.**

```text
google_calendar_list_events()
```

---

### `/schedule-meeting` 📆
**Create a Google Calendar event** with Meet link.

```text
skill_run("schedule_meeting", '{"title": "Sync", "attendees": ["user@example.com"]}')
```

---

### `/setup-gmail` 📧
**Enable Gmail API access** for email features.

Run this first time to add Gmail scopes to your Google OAuth.

---

### `/google-reauth` 🔑
**Re-authenticate Google APIs** when tokens expire.

---

## 🔐 Infrastructure

### `/konflux-status` ⚙️
**Check Konflux platform status** - builds, pipelines, components.

```text
skill_run("konflux_status")
```

---

### `/appinterface-check` 🔍
**Check app-interface configuration** with validation and live state comparison.

```text
skill_run("appinterface_check", '{"saas_file": "tower-analytics-backend"}')
```

Features:
- SHA format validation
- Live state comparison (stage vs prod)
- Resource quota information
- Pending MR detection
- Release readiness assessment

---

### `/ci-health` 📊
**Check CI pipeline health** - recent failures, stuck pipelines.

```text
skill_run("check_ci_health")
```

---

### `/cancel-pipeline` ❌
**Cancel a running pipeline.**

```text
skill_run("cancel_pipeline", '{"pipeline_id": 12345}')
```

---

### `/check-secrets` 🔐
**Check Kubernetes secrets** in a namespace.

```text
skill_run("check_secrets", '{"namespace": "tower-analytics-stage"}')
```

---

### `/scan-vulns` 🔍
**Scan a container image for vulnerabilities.**

```text
skill_run("scan_vulnerabilities", '{"image": "quay.io/..."}')
```

---

## 🔍 Discovery

### `/tools` 🔧
**Discover all available MCP tools.**

```text
tool_list()
tool_list(module='git')
tool_list(module='gitlab')
```

Shows ~263 tools across 16 modules.

---

### `/personas` 🎭
**List and switch between personas.**

```text
persona_list()
persona_load("developer")
persona_load("devops")
```

---

### `/list-skills` 📋
**List all available skills.**

```text
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

### `/memory` 💾
**View persistent memory** - current work, learned patterns, session logs.

```text
memory_read()
memory_read("state/current_work")
memory_read("learned/patterns")
```

---

## 🛠️ Utilities

### `/debug-tool` 🔧
**Debug a failed MCP tool** - analyze source and propose fixes.

```text
debug_tool('bonfire_namespace_release', 'error message here')
```

---

### `/learn-fix` 📚
**Save a tool fix to memory** for future reference.

```text
learn_tool_fix(
    tool_name="bonfire_deploy",
    error_pattern="manifest unknown",
    root_cause="Short SHA",
    fix_description="Use full 40-char SHA"
)
```

---

### `/learn-pattern` 📖
**Save a general error pattern** to memory.

```text
skill_run("learn_pattern", '{"pattern": "...", "solution": "..."}')
```

---

### `/deploy` 🚀
General deployment command.

---

### `/load-developer` 👨‍💻
Quick command to load the developer agent.

```text
persona_load("developer")
```

---

### `/load-devops` 🔧
Quick command to load the devops agent.

```text
persona_load("devops")
```

---

### `/notify-mr` 💬
**Notify team about an MR** in Slack.

```text
skill_run("notify_mr", '{"mr_id": 1234}')
```

---

### `/notify-team` 💬
**Post a message to team Slack channel.**

```text
skill_run("notify_team", '{"message": "Heads up: deploying to prod"}')
```

---

### `/memory-edit` ✏️
**Edit a memory entry.**

```text
skill_run("memory_edit", '{"key": "state/current_work", "path": "notes"}')
```

---

### `/memory-cleanup` 🧹
**Clean up old memory entries.**

```text
skill_run("memory_cleanup")
```

---

### `/memory-init` 🗄️
**Initialize memory structure** for a new project.

```text
skill_run("memory_init")
```

---

## Command Locations

All commands are defined in `.cursor/commands/`:

```text
.cursor/commands/
├── appinterface-check.md
├── beer.md
├── cancel-pipeline.md
├── check-feedback.md
├── check-namespaces.md
├── check-prs.md
├── check-secrets.md
├── ci-health.md
├── clone-issue.md
├── close-issue.md
├── close-mr.md
├── coffee.md
├── create-issue.md
├── create-mr.md
├── debug-prod.md
├── debug-tool.md
├── deploy-ephemeral.md
├── deploy.md
├── env-overview.md
├── extend-ephemeral.md
├── google-reauth.md
├── hotfix.md
├── integration-tests.md
├── investigate-alert.md
├── jira-hygiene.md
├── konflux-status.md
├── learn-fix.md
├── learn-pattern.md
├── list-skills.md
├── load-developer.md
├── load-devops.md
├── mark-ready.md
├── memory-cleanup.md
├── memory-edit.md
├── memory-init.md
├── memory.md
├── my-calendar.md
├── notify-mr.md
├── notify-team.md
├── personas.md
├── rebase-pr.md
├── release-prod.md
├── review-all-open.md
├── review-mr-multiagent.md
├── review-mr-with-tests.md
├── review-mr.md
├── review.md
├── rollout-restart.md
├── run-local-tests.md
├── scale-deployment.md
├── scan-vulns.md
├── schedule-meeting.md
├── setup-gmail.md
├── silence-alert.md
├── smoke-skills.md
├── smoke-tools.md
├── sprint-planning.md
├── standup.md
├── start-work.md
├── sync-branch.md
├── test-ephemeral.md
├── tools.md
├── vpn.md
└── weekly-summary.md
```

## Creating Custom Commands

To create a new command, add a `.md` file to `.cursor/commands/`:

```markdown
# 🎯 My Custom Command

Description of what it does.

## Instructions

```text
skill_run("my_skill", '{"param": "value"}')
```
```

The command name comes from the filename (e.g., `my-command.md` → `/my-command`).
