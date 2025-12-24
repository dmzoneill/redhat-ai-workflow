# AI Workflow Assistant

This is a complete AI-powered development workflow system with **MCP Tools**, **Agents**, **Skills**, and **Memory**.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Claude Session                        │
├─────────────────────────────────────────────────────────┤
│  AGENTS (agents/)           SKILLS (skills/)            │
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
│  MCP TOOLS (mcp-servers/)                               │
│  219 tools across 12 modules                            │
│  aa-git, aa-jira, aa-gitlab, aa-k8s, aa-prometheus...  │
└─────────────────────────────────────────────────────────┘
```

---

## Quick Start

### Load an Agent
```
I need help as a DevOps engineer. Load the devops agent.
```
Then Claude reads `agents/devops.md` and adopts that persona.

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

---

## MCP Tools (219 total)

### Tool Categories

| Module | Tools | Purpose |
|--------|-------|---------|
| `aa-git` | 15 | Git operations (status, branch, commit, push) |
| `aa-jira` | 24 | Jira issues (view, create, update, transition) |
| `aa-gitlab` | 35 | GitLab MRs, CI/CD pipelines |
| `aa-k8s` | 26 | Kubernetes (pods, deployments, logs) |
| `aa-prometheus` | 13 | Prometheus queries, alerts, metrics |
| `aa-alertmanager` | 6 | Silences, alert management |
| `aa-kibana` | 9 | Log search and analysis |
| `aa-konflux` | 40 | Konflux builds, Tekton, snapshots |
| `aa-bonfire` | 21 | Ephemeral namespace management |
| `aa-quay` | 8 | Container registry, vulnerabilities |
| `aa-appinterface` | 6 | App-Interface validation |
| `aa-workflow` | 16 | Orchestrated workflows |

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

## Agents

Agents are specialized personas. Load one to get focused expertise.

### DevOps Agent (`agents/devops.md`)
- Focus: Infrastructure, monitoring, incident response
- Tools: aa-k8s, aa-prometheus, aa-alertmanager, aa-kibana
- Use when: Investigating alerts, managing deployments

### Developer Agent (`agents/developer.md`)
- Focus: Coding, PRs, code review
- Tools: aa-git, aa-gitlab, aa-jira
- Use when: Writing code, creating MRs

### Incident Agent (`agents/incident.md`)
- Focus: Rapid triage, mitigation, recovery
- Tools: All observability tools
- Use when: Production incidents

### Release Agent (`agents/release.md`)
- Focus: Release coordination, deployment
- Tools: aa-konflux, aa-quay, aa-bonfire, aa-appinterface
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
├── agents/                # Agent personas
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
├── mcp-servers/           # MCP tool modules
│   ├── aa-common/         # Shared infrastructure
│   ├── aa-git/
│   ├── aa-jira/
│   ├── aa-gitlab/
│   ├── aa-k8s/
│   ├── aa-prometheus/
│   ├── aa-alertmanager/
│   ├── aa-kibana/
│   ├── aa-konflux/
│   ├── aa-bonfire/
│   ├── aa-quay/
│   ├── aa-appinterface/
│   └── aa-workflow/
└── examples/              # MCP config examples
    ├── mcp-full.json
    ├── mcp-minimal.json
    ├── mcp-cicd.json
    └── mcp-debugging.json
```

---

## Tips for AI Assistants

1. **Load memory first** - Check `memory/state/current_work.yaml` for context
2. **Use the right agent** - Match persona to the task
3. **Follow skills** - Use predefined workflows for common tasks
4. **Update memory** - Save learned patterns for future sessions
5. **Be specific with tools** - Always include required parameters
6. **Handle errors gracefully** - Check tool output before proceeding
7. **Link Jira + GitLab** - Always reference issues in commits/MRs

## ⚠️ Critical Don'ts

1. **NEVER copy kubeconfig files** - Use `--kubeconfig=` flag or `KUBECONFIG=` env
2. **NEVER use short SHAs for image tags** - Konflux uses full 40-char git SHA
3. **NEVER release namespaces you don't own** - Check `bonfire namespace list --mine` first
4. **NEVER run raw bonfire deploy without `--set-image-tag`** - Will use wrong image

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
