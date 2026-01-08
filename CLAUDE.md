# AI Workflow Assistant

This is a complete AI-powered development workflow system with **MCP Tools**, **Personas**, **Skills**, and **Memory**.

## ⚠️ CRITICAL: Tool Usage Rules

**ALWAYS prefer MCP tools over CLI commands!** You have ~270 specialized tools - use them.

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

```
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
│  ~270 tools across 17 modules                           │
│  aa_git, aa_jira, aa_gitlab, aa_k8s, aa_prometheus...  │
└─────────────────────────────────────────────────────────┘
```

---

## Quick Start

### Load an Agent (Dynamic!)
```
Load the devops agent
```
Tools switch dynamically! You go from ~16 workflow tools to ~106 devops tools.

```
Load the developer agent
```
Now you have git, gitlab, jira tools (~106 tools).

### Run a Skill
```
Run the start_work skill for issue PROJ-12345 in my-backend
```
Claude follows the workflow in `skills/start_work.yaml`.

### Use Memory
```
What am I currently working on?
```
Claude reads `memory/state/current_work.yaml`.

### Deploy to Ephemeral
```
Deploy MR 1459 to ephemeral
Test AAP-61214 in ephemeral
```
Claude runs the `test_mr_ephemeral` skill automatically.

---

## MCP Tools (~270 total)

### Tool Categories

| Module | Tools | Purpose |
|--------|-------|---------|
| `aa_workflow` | 16 | Core: agents, skills, memory, vpn, kube_login |
| `aa_git` | 19 | Git operations (status, branch, commit, push) |
| `aa_gitlab` | 35 | GitLab MRs, CI/CD pipelines |
| `aa_jira` | 28 | Jira issues (view, create, update, transition) |
| `aa_k8s` | 26 | Kubernetes (pods, deployments, logs) |
| `aa_bonfire` | 21 | Ephemeral namespace management |
| `aa_quay` | 8 | Container registry, vulnerabilities |
| `aa_prometheus` | 13 | Prometheus queries, alerts, metrics |
| `aa_alertmanager` | 7 | Silences, alert management |
| `aa_kibana` | 9 | Log search and analysis |
| `aa_konflux` | 40 | Konflux builds, Tekton, snapshots |
| `aa_appinterface` | 8 | App-Interface validation |
| `aa_google_calendar` | 6 | Calendar & meetings |
| `aa-gmail` | 6 | Email processing |
| `aa_slack` | 16 | Slack integration |
| `aa_lint` | 7 | Code linting and testing |
| `aa_dev_workflow` | 9 | Development workflow helpers |

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
```

---

## Personas (Dynamic Tool Loading!)

Personas are tool configuration profiles. **Load one and tools switch dynamically!**

### How It Works
```
You: Load the devops agent

[Server unloads current tools, loads k8s/bonfire/quay/gitlab]
[Server sends tools/list_changed to Cursor]
[Cursor refreshes available tools]

Claude: DevOps persona loaded with ~106 tools!
```

### Available Personas

| Persona | Modules | ~Tools | Best For |
|---------|---------|--------|----------|
| **devops** | k8s, bonfire, quay, gitlab | ~106 | Ephemeral deployments, K8s ops |
| **developer** | git, gitlab, jira, lint, dev-workflow | ~106 | Coding, PRs, code review |
| **incident** | k8s, prometheus, alertmanager, kibana, jira | ~100 | Production debugging |
| **release** | konflux, quay, appinterface, git, gitlab | ~100 | Shipping releases |

### DevOps Persona (`personas/devops.md`)
- Focus: Infrastructure, ephemeral environments, deployments
- Tools: aa_k8s, aa_bonfire, aa_quay, aa_gitlab
- Use when: Deploying to ephemeral, checking namespaces

### Developer Persona (`personas/developer.md`)
- Focus: Coding, PRs, code review
- Tools: aa_git, aa_gitlab, aa_jira
- Use when: Writing code, creating MRs

### Incident Persona (`personas/incident.md`)
- Focus: Rapid triage, mitigation, recovery
- Tools: aa_k8s, aa_kibana, aa_jira
- Use when: Production incidents

### Release Persona (`personas/release.md`)
- Focus: Release coordination, deployment
- Tools: aa_konflux, aa_quay, aa_appinterface, aa_git
- Use when: Managing releases

---

## Skills

Skills are multi-step workflows. They combine tools with decision logic.

### start_work
Begin work on a Jira issue:
1. Get issue details
2. Create feature branch
3. Update Jira status

### create_mr
Create a properly formatted MR:
1. Push current branch
2. Create MR with Jira link
3. Update Jira with MR URL

### investigate_alert
Systematic alert investigation:
1. Get current alerts
2. Check namespace health
3. Get recent events and errors
4. Produce investigation report

---

## Memory

Memory persists across sessions.

### State (`memory/state/`)
- `current_work.yaml` - Active issues, branches, MRs
- `environments.yaml` - Stage/prod health, known issues

### Learned (`memory/learned/`)
- `patterns.yaml` - Error patterns and solutions
- `runbooks.yaml` - Procedures that worked

### Session Instructions
- Read `memory/state/current_work.yaml` at session start
- Update memory when learning something reusable
- Save important patterns to `memory/learned/`

---

## Environment Configuration

All configuration is in `config.json`:

### Clusters
| Cluster | Purpose | Kubeconfig |
|---------|---------|------------|
| Konflux | CI/CD builds | `~/.kube/config.k` |
| Stage | QA/Testing | `~/.kube/config.s` |
| Production | Live | `~/.kube/config.p` |
| Ephemeral | PR testing | `~/.kube/config.e` |

### ⚠️ CRITICAL: Kubeconfig Rules

**NEVER copy kubeconfig files!** Use the correct config for each environment:

```bash
# WRONG - NEVER DO THIS:
cp ~/.kube/config.e ~/.kube/config

# RIGHT - use --kubeconfig flag for kubectl/oc:
kubectl --kubeconfig=~/.kube/config.e get pods -n ephemeral-xxx
oc --kubeconfig=~/.kube/config.e get pods -n ephemeral-xxx

# RIGHT - use KUBECONFIG env for bonfire:
KUBECONFIG=~/.kube/config.e bonfire namespace list --mine
```

### Namespaces
| Environment | Namespace |
|-------------|-----------|
| Stage | Configured in `config.json` |
| Production | Configured in `config.json` |
| Konflux | Configured in `config.json` |

### URLs
All URLs are configured in `config.json`. Key sections:
- **Jira**: `jira.url`
- **GitLab**: `gitlab.host`
- **Prometheus**: `prometheus.environments.{stage|production}.url`
- **Alertmanager**: `alertmanager.environments.{stage|production}.url`
- **Kibana**: `kibana.environments.{stage|production}.url`
- **Clusters**: `clusters.{stage|production}.console_url`

### Authentication
All authentication uses system credentials:
- **Jira**: `JIRA_JPAT` environment variable
- **GitLab**: `glab auth login` or `GITLAB_TOKEN`
- **Kubernetes**: kubeconfig files
- **Quay**: Docker/Podman credentials

---

## Workflow Patterns

### Feature Development
```
1. jira_view_issue → understand requirements
2. git_branch_create → create feature branch
3. jira_set_status "In Progress"
4. [make changes]
5. lint_python → check code quality
6. git_add, git_commit
7. git_push --set-upstream
8. gitlab_mr_create --draft
9. gitlab_ci_status → monitor pipeline
10. gitlab_mr_update draft=false → ready for review
11. jira_set_status "In Review"
```

### Incident Response
```
1. prometheus_alerts → see what's firing
2. k8s_namespace_health → check pod/deployment status
3. kubectl_get_events → recent events
4. kibana_get_errors → error logs
5. [identify issue]
6. kubectl_rollout_restart → if restart needed
7. prometheus_alerts → verify resolved
8. jira_create_issue → track incident
```

### Release
```
1. konflux_list_builds → verify build complete
2. quay_get_vulnerabilities → security check
3. konflux_list_snapshots → get snapshot
4. bonfire_namespace_reserve → ephemeral env
5. bonfire_deploy → deploy for testing
6. [run tests]
7. bonfire_namespace_release → cleanup
8. appinterface_get_saas → check deployment config
9. [merge to deploy]
10. prometheus_alerts → monitor post-deploy
```

---

## Project Structure

```
ai-workflow/
├── CLAUDE.md              # This file (AI context)
├── README.md              # Human documentation
├── config.json             # Configuration
├── personas/                # Agent personas
│   ├── devops.md
│   ├── developer.md
│   ├── incident.md
│   └── release.md
├── skills/                # Reusable workflows
│   ├── start_work.yaml
│   ├── create_mr.yaml
│   └── investigate_alert.yaml
├── memory/                # Persistent context
│   ├── state/
│   └── learned/
├── tool_modules/           # MCP tool modules
│   ├── server/         # Shared infrastructure
│   ├── aa_git/
│   ├── aa_jira/
│   ├── aa_gitlab/
│   ├── aa_k8s/
│   ├── aa_prometheus/
│   ├── aa_alertmanager/
│   ├── aa_kibana/
│   ├── aa_konflux/
│   ├── aa_bonfire/
│   ├── aa_quay/
│   ├── aa_appinterface/
│   └── aa_workflow/
└── examples/              # MCP config examples
    ├── mcp-full.json
    ├── mcp-minimal.json
    ├── mcp-cicd.json
    └── mcp-debugging.json
```

---

## Tips for AI Assistants

1. **Load memory first** - Check `memory/state/current_work.yaml` for context
2. **Use the right persona** - Match persona to the task (persona_load)
3. **Follow skills** - Use predefined workflows for common tasks
4. **Update memory** - Save learned patterns for future sessions
5. **Be specific with tools** - Always include required parameters
6. **Handle errors gracefully** - Check tool output before proceeding
7. **Link Jira + GitLab** - Always reference issues in commits/MRs
8. **Auto-debug on failures** - When a tool fails, call `debug_tool()` to fix it

## 🔧 Auto-Heal: Self-Fixing Skills

Skills now include **auto-heal** capabilities. When a tool fails, the skill:

1. **Detects** the failure pattern (auth, network, registry, etc.)
2. **Applies** automatic fixes for known issues
3. **Retries** the operation after fixing
4. **Logs** the failure to memory for future learning

### Auto-Fixed Error Types

| Error Type | Pattern | Auto-Fix |
|------------|---------|----------|
| **auth** | "unauthorized", "401", "forbidden" | `kube_login(cluster)` |
| **network** | "no route", "timeout", "connection refused" | `vpn_connect()` |
| **registry** | "manifest unknown", "podman login" | Manual: `podman login quay.io` |
| **tty** | "output is not a tty" | Use `debug_tool()` to add --force |

### Skills with Auto-Heal (15 total)

- ✅ `test_mr_ephemeral` - bonfire namespace reserve
- ✅ `deploy_to_ephemeral` - bonfire namespace reserve
- ✅ `debug_prod` - kubectl get pods
- ✅ `investigate_alert` - kubectl get pods
- ✅ `rollout_restart` - kubectl rollout restart
- ✅ `release_to_prod` - konflux get component
- ✅ `start_work` - jira view issue
- ✅ `create_mr` - git push
- ✅ `konflux_status` - konflux status
- ✅ `appinterface_check` - appinterface validate
- ✅ `review_pr` - gitlab mr view
- ✅ `check_ci_health` - gitlab ci list
- ✅ `silence_alert` - alertmanager alerts
- ✅ `extend_ephemeral` - bonfire namespace list
- ✅ `cancel_pipeline` - tkn pipelinerun list

### Failure Memory

Failures are logged to `memory/learned/tool_failures.yaml` for learning.

### Manual Fixes with debug_tool

For errors that can't be auto-fixed:

1. **Tool fails** → Look for hint: `💡 To auto-fix: debug_tool('tool_name')`
2. **Call debug_tool** → `debug_tool('bonfire_namespace_release', 'error message')`
3. **Analyze source** → Compare error to code, identify bug
4. **Propose fix** → Show exact `search_replace` edit
5. **Apply & commit** → `git_commit(repo=".", message="description", issue_key="AAP-XXXXX", commit_type="fix", scope="tool_name")`


## ⚠️ Critical Don'ts

1. **NEVER copy kubeconfig files** - Use `--kubeconfig=` flag or `KUBECONFIG=` env
2. **NEVER use short SHAs for image tags** - Konflux uses full 40-char git SHA
3. **NEVER release namespaces you don't own** - Check `bonfire namespace list --mine` first
4. **NEVER run raw bonfire deploy without `--set-image-tag`** - Will use wrong image
5. **NEVER guess tool parameters** - Call `debug_tool()` to inspect the source

## Ephemeral Environment Checklist

Before deploying to ephemeral:
1. ✅ **Ask which ClowdApp** - main (default) or billing?
2. ✅ Get full 40-char commit SHA: `git rev-parse <short_sha>`
3. ✅ Check image exists: `quay_get_tag(repository="...", tag="<full_sha>")`
4. ✅ Get sha256 digest from Quay response
5. ✅ Use skill: `skill_run("test_mr_ephemeral", '{"mr_id": 1459, "billing": false}')`

### ClowdApp Options (automation-analytics-backend)

| Option | Component | Use When |
|--------|-----------|----------|
| `billing: false` (default) | `tower-analytics-clowdapp` | Testing main app |
| `billing: true` | `tower-analytics-billing-clowdapp` | Testing billing features |

If user doesn't specify, **default to main** (`billing: false`).

Or if manual:
```bash
KUBECONFIG=~/.kube/config.e bonfire deploy \
  --set-template-ref component=<40-char-git-sha> \
  --set-parameter component/IMAGE=quay.io/.../image@sha256 \
  --set-parameter component/IMAGE_TAG=<64-char-sha256-digest> \
  app-name
```
