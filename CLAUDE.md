# AI Workflow Assistant

This is a complete AI-powered development workflow system with **MCP Tools**, **Personas**, **Skills**, and **Memory**.

## ⚠️ CRITICAL: Tool Usage Rules

**ALWAYS prefer MCP tools over CLI commands!** You have ~261 specialized tools - use them.

| ❌ DON'T DO THIS | ✅ DO THIS INSTEAD |
|------------------|-------------------|
| `rh-issue set-status AAP-123 "In Progress"` | `jira_set_status(issue_key="AAP-123", status="In Progress")` |
| `git checkout -b feature-branch` | `git_branch_create(repo="backend", branch_name="feature-branch")` |
| `glab mr create ...` | `gitlab_mr_create(project="backend", title="...")` |
| `kubectl get pods -n stage` | `kubectl_get_pods(namespace="stage", environment="stage")` |
| `bonfire namespace list --mine` | `bonfire_namespace_list(mine_only=True)` |
| `curl https://issues.redhat.com/...` | `jira_view_issue(issue_key="AAP-123")` |

### Why Use MCP Tools?

1. **Auto-healing**: MCP tools automatically fix VPN/auth issues and retry
2. **Memory integration**: Failures are logged, patterns are learned
3. **Consistent output**: Formatted for AI parsing
4. **Error handling**: Proper error messages with fix suggestions
5. **Debug support**: `debug_tool()` can fix broken tools

### When CLI Is Acceptable

- Running actual application code (e.g., `python app.py`, `pytest`)
- No MCP tool exists for the operation
- User explicitly requests CLI

### Use Skills for Common Workflows

Instead of chaining tools manually, use pre-built skills:

| Task | Skill to Use |
|------|-------------|
| Start work on Jira issue | `skill_run("start_work", '{"issue_key": "AAP-123"}')` |
| Create an MR | `skill_run("create_mr", '{"issue_key": "AAP-123"}')` |
| Deploy to ephemeral | `skill_run("test_mr_ephemeral", '{"mr_id": 1459}')` |
| Investigate an alert | `skill_run("investigate_alert", '{"environment": "stage"}')` |
| Morning briefing | `skill_run("coffee")` |

---

## Terminology

| Term | Meaning |
|------|---------|
| **Agent / Persona** | A tool configuration profile (developer, devops, incident, release). NOT a separate AI instance - just a different set of tools. |
| **Tool Module** | A plugin directory (e.g., `aa_git/`, `aa_jira/`) containing MCP tool implementations. |
| **Skill** | A YAML-defined multi-step workflow that chains tools. |
| **Memory** | Persistent YAML files for context across sessions. |

> **This is a single-agent system.** When you "load an agent," you're configuring which tools are available, not spawning a separate AI.

---

## Architecture Overview

```text
┌─────────────────────────────────────────────────────────┐
│                    Claude Session                        │
├─────────────────────────────────────────────────────────┤
│  AGENTS (personas/)           SKILLS (skills/)            │
│  Specialized personas       Reusable workflows          │
│  - devops.md                - start_work.yaml           │
│  - developer.md             - create_mr.yaml            │
│  - incident.md              - investigate_alert.yaml    │
│  - release.md                                           │
├─────────────────────────────────────────────────────────┤
│  MEMORY (memory/)                                        │
│  Persistent context across sessions                      │
│  - state/current_work.yaml  - learned/patterns.yaml    │
│  - state/environments.yaml  - learned/runbooks.yaml    │
├─────────────────────────────────────────────────────────┤
│  MCP TOOLS (tool_modules/)                               │
│  263 tools: 188 basic (used) + 75 extra (unused)       │
│  aa_git, aa_jira, aa_gitlab, aa_k8s, aa_prometheus...  │
│  30% context reduction with basic-only loading         │
└─────────────────────────────────────────────────────────┘
```

---

## Quick Start

### Load an Agent (Dynamic!)
```text
Load the devops agent
```
Tools switch dynamically! You get k8s_basic, bonfire_basic, jira_basic, quay (~74 tools).

```text
Load the developer agent
```
Now you have git_basic, gitlab_basic, jira_basic (~78 tools).

### Run a Skill
```text
Run the start_work skill for issue PROJ-12345 in my-backend
```
Claude follows the workflow in `skills/start_work.yaml`.

### Use Memory
```text
What am I currently working on?
```
Claude reads `memory/state/current_work.yaml`.

### Deploy to Ephemeral
```text
Deploy MR 1459 to ephemeral
Test AAP-61214 in ephemeral
```
Claude runs the `test_mr_ephemeral` skill automatically.

---

## MCP Tools (263 total: 188 basic + 75 extra)

### Tool Organization

**All tools are split into `_basic` (used in skills) and `_extra` (rarely used) to reduce context window by 30%.**

> **Data-Driven:** Analyzed 55 skills to identify which 188 tools are actually used. See `.claude/skill-tool-usage-report.md` for details.

### Tool Categories

| Module | Total | Basic (Used) | Extra (Unused) | Purpose |
|--------|-------|--------------|----------------|---------|
| `aa_workflow` | 18 | 18 | 0 | Core: agents, skills, memory, vpn, kube_login |
| `aa_git` | 30 | 27 | 3 | Git operations (90% usage) |
| `aa_gitlab` | 30 | 16 | 14 | GitLab MRs, CI/CD pipelines (53% usage) |
| `aa_jira` | 28 | 17 | 11 | Jira issues (61% usage) |
| `aa_k8s` | 28 | 22 | 6 | Kubernetes (79% usage) |
| `aa_bonfire` | 20 | 10 | 10 | Ephemeral namespace management (50% usage) |
| `aa_quay` | 7 | 5 | 2 | Container registry, vulnerabilities (71% usage) |
| `aa_prometheus` | 13 | 5 | 8 | Prometheus queries, alerts (38% usage) |
| `aa_alertmanager` | 7 | 4 | 3 | Silences, alert management (57% usage) |
| `aa_kibana` | 9 | 1 | 8 | Log search and analysis (11% usage) |
| `aa_konflux` | 35 | 22 | 13 | Konflux builds, Tekton (63% usage) |
| `aa_appinterface` | 7 | 4 | 3 | App-Interface validation (57% usage) |
| `aa_google_calendar` | 6 | 6 | 0 | Calendar & meetings (100% usage) |
| `aa_slack` | 9 | 6 | 3 | Slack integration (67% usage) |
| `aa_lint` | 7 | 1 | 6 | Code linting and testing (14% usage) |
| `aa_dev_workflow` | 9 | 9 | 0 | Development workflow helpers (100% usage) |

**Total:** 263 tools (188 basic used in skills, 75 extra rarely used)

### Most-Used Tools

**Starting Work:**
```python
jira_view_issue(issue_key="AAP-12345")
git_branch_create(repo="backend", branch_name="aap-12345-feature")
jira_set_status(issue_key="AAP-12345", status="In Progress")
```

**Creating MR:**
```python
git_push(repo="backend", set_upstream=True)
gitlab_mr_create(project="backend", title="AAP-12345 - feat: description")
gitlab_ci_status(project="backend")
```

**Investigating Issues:**
```python
prometheus_alerts(environment="stage")
kubectl_get_pods(namespace="your-app-stage", environment="stage")
kibana_get_errors(environment="stage", time_range="30m")
```

**Deploying:**
```python
konflux_list_snapshots(namespace="your-tenant")
bonfire_namespace_reserve(duration="2h")
bonfire_deploy(app="your-app", namespace="ephemeral-xxx")
```text

---

## Personas (Dynamic Tool Loading!)

Personas are tool configuration profiles. **Load one and tools switch dynamically!**

### How Persona Loading Works

```text
You: Load the devops agent

[Server unloads current tools, loads k8s_basic/bonfire_basic/jira_basic/quay/docker]
[Server sends tools/list_changed to Cursor]
[Cursor refreshes available tools]

Claude: DevOps persona loaded with ~79 tools!
```

### Available Personas

| Persona | Modules | ~Tools | Best For |
|---------|---------|--------|----------|
| **developer** | workflow, git_basic, gitlab_basic, jira_basic, lint, docker, make, code_search | ~86 | Coding, PRs, code review |
| **devops** | workflow, k8s_basic, bonfire_basic, jira_basic, quay, docker | ~79 | Ephemeral deployments, K8s ops |
| **incident** | workflow, k8s_basic, prometheus_basic, kibana, jira_basic, alertmanager | ~78 | Production debugging |
| **release** | workflow, konflux_basic, quay, jira_basic, git_basic, appinterface | ~94 | Shipping releases |
| **admin** | workflow, knowledge, project, scheduler, concur, slack, jira_basic | ~71 | Expenses, calendar, team comms |
| **slack** | workflow, slack, jira, gitlab | ~85 | Autonomous Slack responder |
| **universal** | workflow, git_basic, gitlab_basic, jira_basic, k8s_basic, code_search | ~104 | All-in-one |
| **core** | workflow, git_basic, jira_basic, k8s_basic | ~84 | Essential shared |

> **Note:** All personas include `jira_basic` for issue tracking. Use `tool_exec()` for `_extra` tools.

### Developer Persona (`personas/developer.yaml`) ~86 tools
- Focus: Coding, PRs, code review
- Tools: workflow (18), git_basic (22), gitlab_basic (18), jira_basic (17), lint (2), docker (4), make (1), code_search (4)
- Use when: Writing code, creating MRs
- Skills: coffee, beer, start_work, create_mr, review_pr, check_my_prs, sync_branch, cleanup_branches

### DevOps Persona (`personas/devops.yaml`) ~79 tools
- Focus: Infrastructure, ephemeral environments, deployments
- Tools: workflow (18), k8s_basic (22), bonfire_basic (10), jira_basic (17), quay (8), docker (4)
- Use when: Deploying to ephemeral, checking namespaces
- Skills: test_mr_ephemeral, deploy_to_ephemeral, investigate_alert, rollout_restart, scale_deployment

### Incident Persona (`personas/incident.yaml`) ~78 tools
- Focus: Rapid triage, mitigation, recovery
- Tools: workflow (18), k8s_basic (22), prometheus_basic (5), kibana (9), jira_basic (17), alertmanager (7)
- Use when: Production incidents
- Skills: investigate_alert, debug_prod, silence_alert, rollout_restart, scale_deployment

### Release Persona (`personas/release.yaml`) ~94 tools
- Focus: Release coordination, deployment
- Tools: workflow (18), konflux_basic (22), quay (8), jira_basic (17), git_basic (22), appinterface (7)
- Use when: Managing releases
- Skills: release_aa_backend_prod, release_to_prod, scan_vulnerabilities, konflux_status, appinterface_check

### Admin Persona (`personas/admin.yaml`) ~71 tools
- Focus: Administrative tasks - expenses, scheduling, team communication
- Tools: workflow (18), knowledge (6), project (5), scheduler (7), concur (9), slack (9), jira_basic (17)
- Use when: Submitting expenses, scheduling meetings, team notifications
- Skills: submit_expenses, coffee, beer, notify_team, schedule_meeting

### Slack Persona (`personas/slack.yaml`) ~85 tools
- Focus: Autonomous Slack responder that monitors channels
- Tools: workflow (18), slack (9), jira (28), gitlab (30)
- Use when: Running as Slack bot daemon
- Skills: start_work, create_jira_issue, create_mr, review_pr, investigate_alert, slack_daemon_control

---

## Skills

Skills are multi-step workflows. **Always prefer skills over manual tool chaining.**

### When User Says → Run This Skill

| User Request | Skill | Example |
|--------------|-------|---------|
| "Start work on AAP-12345" | `start_work` | `skill_run("start_work", '{"issue_key": "AAP-12345"}')` |
| "Create an MR" / "Open a PR" | `create_mr` | `skill_run("create_mr", '{"issue_key": "AAP-12345"}')` |
| "Deploy to ephemeral" / "Test MR 1459" | `test_mr_ephemeral` | `skill_run("test_mr_ephemeral", '{"mr_id": 1459}')` |
| "What's firing?" / "Check alerts" | `investigate_alert` | `skill_run("investigate_alert", '{"environment": "stage"}')` |
| "Morning briefing" / "What's up?" | `coffee` | `skill_run("coffee")` |
| "End of day" / "Wrap up" | `beer` | `skill_run("beer")` |
| "Review this PR" / "Check MR 1234" | `review_pr` | `skill_run("review_pr", '{"mr_id": 1234}')` |
| "Create a Jira issue" | `create_jira_issue` | `skill_run("create_jira_issue", '{"summary": "...", "issue_type": "story"}')` |
| "Close this issue" | `close_issue` | `skill_run("close_issue", '{"issue_key": "AAP-12345"}')` |
| "Sync my branch" / "Rebase" | `sync_branch` | `skill_run("sync_branch", '{"repo": "backend"}')` |
| "Check my PRs" | `check_my_prs` | `skill_run("check_my_prs")` |
| "Silence this alert" | `silence_alert` | `skill_run("silence_alert", '{"alert_name": "...", "duration": "2h"}')` |
| "Restart the deployment" | `rollout_restart` | `skill_run("rollout_restart", '{"deployment": "...", "namespace": "..."}')` |
| "Scale up/down" | `scale_deployment` | `skill_run("scale_deployment", '{"deployment": "...", "replicas": 3}')` |
| "Extend my namespace" | `extend_ephemeral` | `skill_run("extend_ephemeral", '{"namespace": "ephemeral-xxx", "duration": "2h"}')` |
| "Release to prod" | `release_to_prod` | `skill_run("release_to_prod", '{"version": "..."}')` |
| "Check vulnerabilities" | `scan_vulnerabilities` | `skill_run("scan_vulnerabilities", '{"image": "..."}')` |
| "Retry the pipeline" | `ci_retry` | `skill_run("ci_retry", '{"mr_id": 1234}')` |
| "Mark MR ready" | `mark_mr_ready` | `skill_run("mark_mr_ready", '{"mr_id": 1234}')` |
| "Clean up branches" | `cleanup_branches` | `skill_run("cleanup_branches", '{"repo": "backend"}')` |
| "Schedule a meeting" | `schedule_meeting` | `skill_run("schedule_meeting", '{"title": "...", "attendees": "..."}')` |
| "Submit expenses" | `submit_expense` | `skill_run("submit_expense")` |

### Skill Categories

**Daily Workflow:**
- `coffee` - Morning briefing (PRs, Jira, calendar, alerts)
- `beer` - End of day wrap-up
- `standup_summary` - Generate standup notes
- `weekly_summary` - Weekly work summary

**Development:**
- `start_work` - Begin work on Jira issue (creates branch, updates status)
- `create_mr` - Create MR with proper formatting and Jira links
- `review_pr` - Review a PR (auto-approves or posts feedback)
- `check_my_prs` - Check your PRs for feedback
- `check_mr_feedback` - See comments needing response
- `sync_branch` - Rebase onto main
- `rebase_pr` - Rebase PR with conflict handling
- `cleanup_branches` - Delete merged/stale branches
- `hotfix` - Cherry-pick to release branch

**Ephemeral Testing:**
- `test_mr_ephemeral` - Deploy MR to ephemeral (auto-detects billing vs main)
- `deploy_to_ephemeral` - Deploy apps to ephemeral
- `extend_ephemeral` - Extend namespace reservation

**Incident Response:**
- `investigate_alert` - Systematic alert investigation
- `investigate_slack_alert` - Investigate from Slack context
- `debug_prod` - Debug production issues
- `silence_alert` - Create alert silences
- `rollout_restart` - Restart deployments
- `scale_deployment` - Scale pods

**Release:**
- `release_to_prod` - Production release workflow
- `release_aa_backend_prod` - AA-specific prod release
- `scan_vulnerabilities` - CVE scanning
- `konflux_status` - Check Konflux builds
- `appinterface_check` - Validate app-interface config

**CI/CD:**
- `ci_retry` - Retry failed pipelines
- `cancel_pipeline` - Cancel stuck pipelines
- `check_ci_health` - Diagnose CI issues

**Jira:**
- `create_jira_issue` - Create issue (supports Markdown)
- `clone_jira_issue` - Clone existing issue
- `close_issue` - Close with commit summary
- `jira_hygiene` - Issue quality checks
- `sprint_planning` - Prepare sprint backlog

**Communication:**
- `notify_mr` - Notify team about MR
- `notify_team` - Send Slack notifications
- `schedule_meeting` - Schedule Google Calendar meetings

---

## Search & Context Tools

Use these tools to find information and understand context.

### Code Search (Semantic Vector Search)

Find code by meaning, not just text matching:

| User Request | Tool | Example |
|--------------|------|---------|
| "Find where we handle auth" | `code_search` | `code_search(query="authentication handling", project="backend")` |
| "Show billing-related code" | `code_search` | `code_search(query="billing subscription processing", project="backend")` |
| "Where do we validate input?" | `code_search` | `code_search(query="input validation sanitization", project="backend")` |

### Memory Tools

Query what you're working on or what you've learned:

| User Request | Tool | Example |
|--------------|------|---------|
| "What am I working on?" | `memory_read` | `memory_read(key="state/current_work")` |
| "Any known issues with bonfire?" | `check_known_issues` | `check_known_issues(tool_name="bonfire")` |
| "Show my session history" | `memory_read` | `memory_read(key="")` to list files |

### Knowledge Tools

Project-specific gotchas, patterns, and architecture:

| User Request | Tool | Example |
|--------------|------|---------|
| "What gotchas should I know?" | `knowledge_query` | `knowledge_query(project="backend", section="gotchas")` |
| "Show architecture overview" | `knowledge_query` | `knowledge_query(project="backend", section="architecture")` |
| "Bootstrap knowledge for project" | skill | `skill_run("bootstrap_knowledge", '{"project": "backend"}')` |

> **Note:** Knowledge auto-loads during `session_start()`. Skills automatically search code and check known issues.

---

## Environment Configuration

All configuration is in `config.json`. Tools read URLs, namespaces, and credentials from there automatically.

> **Note:** Use MCP tools instead of raw CLI commands. Tools handle kubeconfig selection automatically.

---

## Key Principles

1. **Use skills over manual tool chaining** - Skills handle complexity automatically
2. **Use MCP tools over CLI commands** - Tools handle auth, config, and error recovery
3. **Link Jira + GitLab** - Always reference issues in commits/MRs
4. **Trust the config** - Repository-specific settings are in `config.json`

> **Note:** Tools and skills auto-heal auth/network errors automatically.
