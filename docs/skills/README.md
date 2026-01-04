# ⚡ Skills Reference

Skills are **reusable multi-step workflows** that chain MCP tools together with logic, conditions, and templating. All 42 production skills include **auto-healing** for VPN and authentication issues.

## Quick Reference

| Skill | Description | Agent | Auto-Heal |
|-------|-------------|-------|-----------|
| ☕ [coffee](./coffee.md) | Morning briefing - email, PRs, Jira, calendar | developer | ✅ |
| 🍺 [beer](./beer.md) | End-of-day wrap-up and standup prep | developer | ✅ |
| ⚡ [start_work](./start_work.md) | Begin working on a Jira issue | developer | ✅ VPN+Auth |
| 🚀 [create_mr](./create_mr.md) | Create MR with validation and linting | developer | ✅ VPN |
| ✅ [mark_mr_ready](./mark_mr_ready.md) | Mark draft MR as ready for review | developer | ✅ |
| ✅ [close_issue](./close_issue.md) | Close issue with commit summary | developer | ✅ VPN |
| 👀 [review_pr](./review_pr.md) | Review MR with auto-approve/feedback | developer | ✅ VPN+Auth |
| 📋 [review_all_prs](./review_all_prs.md) | Batch review open PRs | developer | ✅ VPN |
| 📝 [check_my_prs](./check_my_prs.md) | Check your PRs for feedback | developer | ✅ VPN |
| 💬 [check_mr_feedback](./check_mr_feedback.md) | Find comments needing response | developer | ✅ VPN |
| 🔄 [rebase_pr](./rebase_pr.md) | Rebase with auto-conflict resolution | developer | ✅ VPN |
| 🔁 [sync_branch](./sync_branch.md) | Quick sync with main | developer | ✅ VPN |
| 📊 [standup_summary](./standup_summary.md) | Generate standup from activity | developer | ✅ |
| 📋 [jira_hygiene](./jira_hygiene.md) | Validate and fix issue quality | developer | ✅ VPN |
| 📋 [create_jira_issue](./create_jira_issue.md) | Create issue with Markdown support | developer | ✅ |
| 📋 [clone_jira_issue](./clone_jira_issue.md) | Clone existing Jira issue | developer | ✅ |
| 📋 [sprint_planning](./sprint_planning.md) | Sprint planning assistance | developer | ✅ |
| 🧪 [test_mr_ephemeral](./test_mr_ephemeral.md) | Deploy MR to ephemeral environment | devops | ✅ VPN+Auth |
| 🚀 [deploy_to_ephemeral](./deploy_to_ephemeral.md) | Full ephemeral deployment | devops | ✅ VPN+Auth |
| ⏰ [extend_ephemeral](./extend_ephemeral.md) | Extend ephemeral namespace TTL | devops | ✅ VPN+Auth |
| 🔄 [rollout_restart](./rollout_restart.md) | Restart deployment with rollout | devops | ✅ VPN+Auth |
| 📈 [scale_deployment](./scale_deployment.md) | Scale deployment replicas | devops | ✅ VPN+Auth |
| 🔐 [check_secrets](./check_secrets.md) | Check Kubernetes secrets | devops | ✅ VPN+Auth |
| 🚨 [investigate_alert](./investigate_alert.md) | Quick alert triage | devops, incident | ✅ VPN+Auth |
| 🐛 [debug_prod](./debug_prod.md) | Deep production debugging | devops, incident | ✅ VPN+Auth |
| 🔇 [silence_alert](./silence_alert.md) | Silence Prometheus alert | devops, incident | ✅ VPN+Auth |
| 🌍 [environment_overview](./environment_overview.md) | Environment health overview | devops | ✅ VPN+Auth |
| 📊 [check_ci_health](./check_ci_health.md) | CI pipeline health check | developer | ✅ VPN |
| 🔄 [ci_retry](./ci_retry.md) | Retry failed CI pipeline | developer | ✅ VPN |
| ❌ [cancel_pipeline](./cancel_pipeline.md) | Cancel running pipeline | developer | ✅ VPN+Auth |
| 🧪 [check_integration_tests](./check_integration_tests.md) | Check Konflux integration tests | devops | ✅ VPN+Auth |
| 🔍 [scan_vulnerabilities](./scan_vulnerabilities.md) | Scan container for CVEs | devops | ✅ VPN |
| 🚨 [investigate_slack_alert](./investigate_slack_alert.md) | Handle alerts from Slack | slack | ✅ |
| 🤖 [slack_daemon_control](./slack_daemon_control.md) | Control Slack daemon | slack | - |
| 💬 [notify_team](./notify_team.md) | Post to team Slack channel | developer | ✅ |
| 💬 [notify_mr](./notify_mr.md) | Notify team about MR | developer | ✅ |
| 📆 [schedule_meeting](./schedule_meeting.md) | Create calendar meeting | developer | ✅ |
| 📦 [release_aa_backend_prod](./release_aa_backend_prod.md) | Release to production | release | ✅ VPN+Auth |
| 📦 [release_to_prod](./release_to_prod.md) | Generic production release | release | ✅ VPN+Auth |
| 🔍 [appinterface_check](./appinterface_check.md) | Check app-interface state | release | ✅ VPN+Auth |
| ⚙️ [konflux_status](./konflux_status.md) | Konflux platform status | release | ✅ VPN+Auth |
| 📊 [weekly_summary](./weekly_summary.md) | Weekly activity summary | developer | ✅ |
| 🧹 [cleanup_branches](./cleanup_branches.md) | Clean up stale branches | developer | ✅ |
| 🔥 [hotfix](./hotfix.md) | Create emergency hotfix | developer | ✅ |
| ❌ [close_mr](./close_mr.md) | Close merge request | developer | ✅ VPN |

### Utility/Internal Skills (no auto-heal needed)

| Skill | Description |
|-------|-------------|
| 📖 [learn_pattern](./learn_pattern.md) | Save learned pattern to memory |
| 🧹 [memory_cleanup](./memory_cleanup.md) | Clean up old memory entries |
| ✏️ [memory_edit](./memory_edit.md) | Edit memory entries |
| 🗄️ [memory_init](./memory_init.md) | Initialize memory structure |
| 👁️ [memory_view](./memory_view.md) | View memory contents |

## 🔄 Auto-Heal Feature

All production skills include automatic remediation for common failures:

### How It Works

```mermaid
graph LR
    A[Tool Call] --> B{Success?}
    B -->|Yes| C[Continue]
    B -->|No| D[Detect Failure]
    D --> E{VPN Issue?}
    E -->|Yes| F[vpn_connect]
    E -->|No| G{Auth Issue?}
    G -->|Yes| H[kube_login]
    G -->|No| I[Log & Report]
    F --> J[Retry Tool]
    H --> J
    J --> C
```

### Auto-Heal Patterns

| Error Pattern | Detection | Auto-Fix |
|---------------|-----------|----------|
| "No route to host" | Network timeout | `vpn_connect()` |
| "Connection refused" | Network issue | `vpn_connect()` |
| "Unauthorized" / "401" | Auth expired | `kube_login(cluster)` |
| "Forbidden" / "403" | Auth issue | `kube_login(cluster)` |
| "Token expired" | Auth expired | `kube_login(cluster)` |

### Example in Skill YAML

```yaml
# Original tool call
- name: get_pods
  tool: kubectl_get_pods
  args:
    namespace: "{{ namespace }}"
    environment: "{{ env }}"
  output: pods_result
  on_error: continue

# Detect failure
- name: detect_failure_pods
  condition: "pods_result and ('❌' in str(pods_result) or 'error' in str(pods_result).lower())"
  compute: |
    error_text = str(pods_result)[:300].lower()
    result = {
      "failed": True,
      "needs_vpn": any(x in error_text for x in ['no route', 'timeout', 'connection refused']),
      "needs_auth": any(x in error_text for x in ['unauthorized', '401', 'forbidden', '403']),
    }
  output: failure_pods

# Auto-fix VPN
- name: quick_fix_vpn_pods
  condition: "failure_pods and failure_pods.get('needs_vpn')"
  tool: vpn_connect
  on_error: continue

# Auto-fix Auth
- name: quick_fix_auth_pods
  condition: "failure_pods and failure_pods.get('needs_auth')"
  tool: kube_login
  args:
    cluster: "{{ env }}"
  on_error: continue

# Retry after fix
- name: retry_get_pods
  condition: "failure_pods"
  tool: kubectl_get_pods
  args:
    namespace: "{{ namespace }}"
    environment: "{{ env }}"
  output: pods_retry_result
```

## Daily Workflow

```mermaid
graph LR
    MORNING["☕ Morning"] --> COFFEE["coffee"]
    COFFEE --> WORK["💻 Work"]
    WORK --> START["start_work"]
    START --> CODE["Write Code"]
    CODE --> MR["create_mr"]
    MR --> REVIEW["review_pr"]
    REVIEW --> EVENING["🌙 Evening"]
    EVENING --> BEER["beer"]

    style COFFEE fill:#6366f1,stroke:#4f46e5,color:#fff
    style BEER fill:#f59e0b,stroke:#d97706,color:#fff
```

## Skill Categories

### 📅 Daily Rituals

| Skill | When to Use |
|-------|-------------|
| [coffee](./coffee.md) | Start of day - get briefed |
| [beer](./beer.md) | End of day - wrap up |
| [standup_summary](./standup_summary.md) | Generate standup notes |
| [weekly_summary](./weekly_summary.md) | Weekly activity report |

### 💻 Development Flow

| Skill | When to Use |
|-------|-------------|
| [start_work](./start_work.md) | Pick up a Jira issue |
| [sync_branch](./sync_branch.md) | Stay up to date with main |
| [create_mr](./create_mr.md) | Ready to submit code |
| [mark_mr_ready](./mark_mr_ready.md) | Mark draft as ready |
| [close_issue](./close_issue.md) | Work is merged |
| [hotfix](./hotfix.md) | Emergency fix needed |

### 👀 Code Review

| Skill | When to Use |
|-------|-------------|
| [review_pr](./review_pr.md) | Review a specific MR |
| [review_all_prs](./review_all_prs.md) | Batch review session |
| [check_my_prs](./check_my_prs.md) | Check your PR status |
| [check_mr_feedback](./check_mr_feedback.md) | Find feedback to address |
| [rebase_pr](./rebase_pr.md) | Fix merge conflicts |
| [close_mr](./close_mr.md) | Close abandoned MR |

### 🧪 Testing & Deployment

| Skill | When to Use |
|-------|-------------|
| [test_mr_ephemeral](./test_mr_ephemeral.md) | Test in ephemeral namespace |
| [deploy_to_ephemeral](./deploy_to_ephemeral.md) | Full ephemeral deploy |
| [extend_ephemeral](./extend_ephemeral.md) | Need more time testing |
| [release_aa_backend_prod](./release_aa_backend_prod.md) | Release to production |
| [release_to_prod](./release_to_prod.md) | Generic prod release |
| [check_ci_health](./check_ci_health.md) | CI pipeline issues |
| [check_integration_tests](./check_integration_tests.md) | Integration test status |
| [scan_vulnerabilities](./scan_vulnerabilities.md) | Security scanning |

### 🚨 Incident Response

| Skill | When to Use |
|-------|-------------|
| [investigate_alert](./investigate_alert.md) | Quick alert triage |
| [debug_prod](./debug_prod.md) | Deep debugging |
| [investigate_slack_alert](./investigate_slack_alert.md) | Slack alert handling |
| [silence_alert](./silence_alert.md) | Silence noisy alert |
| [environment_overview](./environment_overview.md) | Environment health check |
| [rollout_restart](./rollout_restart.md) | Restart stuck pods |
| [scale_deployment](./scale_deployment.md) | Scale for load |

### 📋 Jira Management

| Skill | When to Use |
|-------|-------------|
| [create_jira_issue](./create_jira_issue.md) | Create new issue |
| [clone_jira_issue](./clone_jira_issue.md) | Clone existing issue |
| [jira_hygiene](./jira_hygiene.md) | Validate issue quality |
| [sprint_planning](./sprint_planning.md) | Sprint planning |

### 📦 Release & Infrastructure

| Skill | When to Use |
|-------|-------------|
| [appinterface_check](./appinterface_check.md) | Check GitOps config |
| [konflux_status](./konflux_status.md) | Konflux platform status |
| [check_secrets](./check_secrets.md) | Verify secrets |
| [cancel_pipeline](./cancel_pipeline.md) | Cancel stuck pipeline |

## Running Skills

**Via Chat:**
```
Run the start_work skill for AAP-12345
```

**Via Tool:**
```
skill_run("start_work", '{"issue_key": "AAP-12345"}')
```

**Via Cursor Command:**
```
/deploy
/coffee
/standup
```

## Skill YAML Format

```yaml
name: skill_name
description: What this skill does
version: "1.0"

inputs:
  - name: input_name
    type: string
    required: true
    description: "What this input is for"

steps:
  - name: step_one
    tool: tool_name
    args:
      param: "{{ inputs.input_name }}"
    output: step1_result
    on_error: continue

  # Auto-heal pattern
  - name: detect_failure_step_one
    condition: "step1_result and 'error' in str(step1_result).lower()"
    compute: |
      result = {"needs_vpn": 'no route' in str(step1_result).lower()}
    output: failure_step_one

  - name: quick_fix_vpn
    condition: "failure_step_one and failure_step_one.get('needs_vpn')"
    tool: vpn_connect
    on_error: continue

  - name: retry_step_one
    condition: "failure_step_one"
    tool: tool_name
    args:
      param: "{{ inputs.input_name }}"
    output: step1_retry_result

  - name: step_two
    condition: "{{ step1_result.success or step1_retry_result.success }}"
    compute: |
      # Python code here
      result = {"processed": step1_result.data}
    output: step2_result

outputs:
  - name: summary
    value: "{{ step2_result | json }}"
```

## See Also

- [Architecture Overview](../architecture/README.md)
- [Learning Loop](../learning-loop.md) - Tool-level auto-remediation
- [Auto-Heal Implementation](../plans/skill-auto-heal.md) - Skill auto-heal details
- [Commands Reference](../commands/README.md) - Cursor slash commands
