# ⚡ Skills Reference

Skills are **reusable multi-step workflows** that chain MCP tools together with logic, conditions, and templating.

## Quick Reference

| Skill | Description | Agent |
|-------|-------------|-------|
| ☕ [coffee](./coffee.md) | Morning briefing - email, PRs, Jira, calendar | developer |
| 🍺 [beer](./beer.md) | End-of-day wrap-up and standup prep | developer |
| ⚡ [start_work](./start_work.md) | Begin working on a Jira issue | developer |
| 🚀 [create_mr](./create_mr.md) | Create MR with validation and linting | developer |
| ✅ [mark_mr_ready](./mark_mr_ready.md) | Mark draft MR as ready for review | developer |
| ✅ [close_issue](./close_issue.md) | Close issue with commit summary | developer |
| 👀 [review_pr](./review_pr.md) | Review MR with auto-approve/feedback | developer |
| 📋 [review_all_prs](./review_all_prs.md) | Batch review open PRs | developer |
| 📝 [check_my_prs](./check_my_prs.md) | Check your PRs for feedback | developer |
| 💬 [check_mr_feedback](./check_mr_feedback.md) | Find comments needing response | developer |
| 🔄 [rebase_pr](./rebase_pr.md) | Rebase with auto-conflict resolution | developer |
| 🔁 [sync_branch](./sync_branch.md) | Quick sync with main | developer |
| 📊 [standup_summary](./standup_summary.md) | Generate standup from activity | developer |
| 📋 [jira_hygiene](./jira_hygiene.md) | Validate issue quality | developer |
| 📋 [create_jira_issue](./create_jira_issue.md) | Create issue with Markdown support | developer |
| 🧪 [test_mr_ephemeral](./test_mr_ephemeral.md) | Deploy MR to ephemeral environment | devops |
| 🚨 [investigate_alert](./investigate_alert.md) | Quick alert triage | devops, incident |
| 🐛 [debug_prod](./debug_prod.md) | Deep production debugging | devops, incident |
| 🚨 [investigate_slack_alert](./investigate_slack_alert.md) | Handle alerts from Slack | slack |
| 🤖 [slack_daemon_control](./slack_daemon_control.md) | Control Slack daemon | slack |
| 📦 [release_aa_backend_prod](./release_aa_backend_prod.md) | Release to production | release |

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

### 💻 Development Flow

| Skill | When to Use |
|-------|-------------|
| [start_work](./start_work.md) | Pick up a Jira issue |
| [sync_branch](./sync_branch.md) | Stay up to date with main |
| [create_mr](./create_mr.md) | Ready to submit code |
| [mark_mr_ready](./mark_mr_ready.md) | Mark draft as ready |
| [close_issue](./close_issue.md) | Work is merged |

### 👀 Code Review

| Skill | When to Use |
|-------|-------------|
| [review_pr](./review_pr.md) | Review a specific MR |
| [review_all_prs](./review_all_prs.md) | Batch review session |
| [check_my_prs](./check_my_prs.md) | Check your PR status |
| [check_mr_feedback](./check_mr_feedback.md) | Find feedback to address |
| [rebase_pr](./rebase_pr.md) | Fix merge conflicts |

### 🧪 Testing & Deployment

| Skill | When to Use |
|-------|-------------|
| [test_mr_ephemeral](./test_mr_ephemeral.md) | Test in ephemeral namespace |
| [release_aa_backend_prod](./release_aa_backend_prod.md) | Release to production |

### 🚨 Incident Response

| Skill | When to Use |
|-------|-------------|
| [investigate_alert](./investigate_alert.md) | Quick alert triage |
| [debug_prod](./debug_prod.md) | Deep debugging |
| [investigate_slack_alert](./investigate_slack_alert.md) | Slack alert handling |

### 📋 Jira Management

| Skill | When to Use |
|-------|-------------|
| [create_jira_issue](./create_jira_issue.md) | Create new issue |
| [jira_hygiene](./jira_hygiene.md) | Validate issue quality |

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

  - name: step_two
    condition: "{{ step1_result.success }}"
    compute: |
      # Python code here
      result = {"processed": step1_result.data}
    output: step2_result

outputs:
  - name: summary
    value: "{{ step2_result | json }}"
```
