# Examples

Practical examples and tutorials for the AI Workflow system.

## Quick Start Examples

### 1. Morning Workflow

```bash
# Start your day with a comprehensive briefing
/coffee

# This shows:
# - Today's meetings
# - Unread emails
# - Open PRs needing attention
# - Sprint issues
# - Active ephemeral environments
# - Firing alerts
```

### 2. Working on a Jira Issue

```bash
# Start work on an issue - creates branch, loads context
/start-work AAP-12345

# Make your changes...
# Then create the MR
/create-mr

# Mark ready and notify team
/mark-ready

# Close the issue when merged
/close-issue AAP-12345
```

### 3. Deploying to Ephemeral

```bash
# Deploy an MR to ephemeral for testing
/deploy MR-1459

# Check your namespaces
/check-namespaces

# Extend if needed
/extend-ephemeral ephemeral-abc123
```

## Custom Skill Examples

### Example 1: Simple Tool Chain

Create `skills/my_skill.yaml`:

```yaml
name: my_skill
description: Example skill that chains two tools

inputs:
  - name: issue_key
    type: string
    required: true

steps:
  - name: get_issue
    tool: jira_get_issue
    args:
      issue_key: "{{ inputs.issue_key }}"
    output: issue

  - name: log_result
    tool: memory_session_log
    args:
      action: "Fetched issue {{ inputs.issue_key }}"
      details: "Summary: {{ issue.summary }}"
```

Run it:
```bash
skill_run("my_skill", '{"issue_key": "AAP-12345"}')
```

### Example 2: Conditional Logic

```yaml
name: conditional_skill
description: Skill with conditional steps

inputs:
  - name: deploy
    type: boolean
    default: false

steps:
  - name: run_tests
    tool: make_target
    args:
      repo: "backend"
      target: "test"
    output: test_result

  - name: deploy_if_pass
    condition: "{{ deploy and 'passed' in test_result }}"
    tool: bonfire_deploy
    args:
      namespace: "ephemeral-test"
```

### Example 3: Compute Block

```yaml
name: compute_skill
description: Skill with Python compute block

steps:
  - name: calculate
    compute: |
      from datetime import date

      today = date.today()
      quarter = (today.month - 1) // 3 + 1

      result = {
          "date": today.isoformat(),
          "quarter": f"Q{quarter}",
          "is_end_of_quarter": today.month in [3, 6, 9, 12]
      }
    output: date_info

  - name: use_result
    tool: memory_session_log
    args:
      action: "Computed date info"
      details: "Quarter: {{ date_info.quarter }}"
```

### Example 4: Error Handling

```yaml
name: error_handling_skill
description: Skill with error recovery

steps:
  - name: risky_operation
    tool: kubectl_apply
    args:
      manifest: "deployment.yaml"
    on_error: retry
    max_retries: 3

  - name: fallback_operation
    condition: "{{ not risky_operation_success }}"
    tool: notify_team
    args:
      message: "Deployment failed after retries"
```

## Tool Module Examples

### Git Operations

```python
# List branches
git_branch_list(repo="backend")

# Create branch from issue
git_branch_create(
    repo="backend",
    branch="AAP-12345-fix-bug",
    from_branch="main"
)

# Check out branch
git_checkout(repo="backend", branch="AAP-12345-fix-bug")

# Commit changes
git_commit(
    repo="backend",
    message="AAP-12345 - fix: Correct billing calculation"
)

# Push to remote
git_push(repo="backend")
```

### Jira Operations

```python
# Get issue details
jira_get_issue(issue_key="AAP-12345")

# Create issue
jira_create_issue(
    project="AAP",
    issue_type="Story",
    summary="Add new feature",
    description="## Overview\n\nDescription here..."
)

# Transition issue
jira_transition(issue_key="AAP-12345", status="In Progress")

# Add comment
jira_add_comment(
    issue_key="AAP-12345",
    body="Started work on this issue."
)
```

### Kubernetes Operations

```python
# Get pods
kubectl_get_pods(
    namespace="tower-analytics-stage",
    selector="app=api"
)

# View logs
kubectl_logs(
    namespace="tower-analytics-stage",
    pod="api-12345-abc",
    tail=100
)

# Execute command
kubectl_exec(
    namespace="tower-analytics-stage",
    pod="api-12345-abc",
    command="python manage.py shell"
)
```

### Memory Operations

```python
# Read memory
memory_read("state/current_work")

# Update field
memory_update(
    key="state/current_work",
    path="active_issue",
    value="AAP-12345"
)

# Append to list
memory_append(
    key="state/current_work",
    list_path="active_issues",
    item={
        "key": "AAP-12345",
        "summary": "Fix bug",
        "status": "In Progress"
    }
)

# Log to session
memory_session_log(
    action="Started work on AAP-12345",
    details="Branch: aap-12345-fix-bug"
)
```

## Integration Examples

### Slack Bot Integration

```python
# Send message
slack_send_message(
    channel="#dev-team",
    text="MR ready for review: !1459"
)

# React to message
slack_add_reaction(
    channel="C12345",
    timestamp="1234567890.123456",
    emoji="white_check_mark"
)
```

### Google Calendar Integration

```python
# List events
google_calendar_list_events(days=7)

# Create event
google_calendar_create_event(
    title="Team Sync",
    start="2026-01-27T10:00:00",
    end="2026-01-27T11:00:00",
    attendees=["user@example.com"],
    create_meet=True
)
```

## Configuration Examples

### config.json Structure

```json
{
  "repositories": {
    "automation-analytics-backend": {
      "path": "/home/user/src/backend",
      "gitlab": "org/backend",
      "jira_project": "AAP",
      "default_branch": "main",
      "lint_command": "make lint",
      "test_command": "make test"
    }
  },
  "schedules": {
    "timezone": "America/New_York",
    "jobs": [
      {
        "name": "morning_coffee",
        "skill": "coffee",
        "cron": "0 9 * * 1-5"
      }
    ]
  }
}
```

### Persona YAML

```yaml
# personas/my_persona.yaml
name: my_persona
description: Custom persona for my workflow

modules:
  - name: workflow
    source: basic
  - name: git
    source: basic
  - name: jira
    source: basic
  - name: custom_module
    source: extra

behavior:
  auto_load_knowledge: true
  default_project: backend
```

## See Also

- [Skills Reference](../skills/README.md)
- [Tool Modules Reference](../tool-modules/README.md)
- [Development Guide](../DEVELOPMENT.md)
- [Architecture Overview](../architecture/README.md)
