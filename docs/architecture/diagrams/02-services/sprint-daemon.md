# Sprint Daemon

> Jira sprint automation and workflow management

## Diagram

```mermaid
stateDiagram-v2
    [*] --> Idle: Daemon started

    Idle --> Monitoring: Start monitoring
    
    state Monitoring {
        [*] --> CheckSprint
        CheckSprint --> ProcessIssues: Active sprint found
        CheckSprint --> Wait: No active sprint
        
        ProcessIssues --> CheckTransitions: For each issue
        CheckTransitions --> ApplyRules: Transitions needed
        ApplyRules --> ProcessIssues: Next issue
        CheckTransitions --> ProcessIssues: No transitions
        
        ProcessIssues --> UpdateMetrics: All issues processed
        UpdateMetrics --> Wait: Cycle complete
        Wait --> CheckSprint: Interval elapsed
    }

    Monitoring --> Paused: Pause requested
    Paused --> Monitoring: Resume requested
    Monitoring --> Shutdown: Stop requested
    Shutdown --> [*]
```

## Class Structure

```mermaid
classDiagram
    class SprintDaemon {
        +name: str = "sprint"
        +service_name: str
        -_scheduler: APScheduler
        -_current_sprint: Sprint
        -_rules: list~Rule~
        +startup() async
        +run_daemon() async
        +shutdown() async
        +process_sprint() async
        +apply_rules(issue) async
        +get_service_stats() async
    }

    class WorkflowConfig {
        +rules: list~Rule~
        +transitions: dict
        +notifications: dict
        +load_config()
        +get_rules_for_status(status)
    }

    class ExecutionTracer {
        +trace_id: str
        +start_trace()
        +log_step(step, result)
        +end_trace()
        +get_trace()
    }

    class SprintBot {
        +process_issue(issue)
        +check_stale_issues()
        +send_reminders()
        +update_sprint_board()
    }

    SprintDaemon --> WorkflowConfig : uses
    SprintDaemon --> ExecutionTracer : uses
    SprintDaemon --> SprintBot : uses
```

## Workflow Processing

```mermaid
flowchart TB
    subgraph Input[Sprint Data]
        SPRINT[Active Sprint]
        ISSUES[Sprint Issues]
        RULES[Workflow Rules]
    end

    subgraph Processing[Issue Processing]
        FETCH[Fetch Issues]
        FILTER[Filter by Status]
        CHECK[Check Rules]
        APPLY[Apply Transitions]
    end

    subgraph Actions[Automated Actions]
        TRANSITION[Transition Issue]
        COMMENT[Add Comment]
        ASSIGN[Update Assignee]
        NOTIFY[Send Notification]
    end

    subgraph Output[Results]
        LOG[Execution Log]
        METRICS[Sprint Metrics]
        ALERTS[Slack Alerts]
    end

    SPRINT --> FETCH
    ISSUES --> FETCH
    FETCH --> FILTER
    FILTER --> CHECK
    RULES --> CHECK
    CHECK --> APPLY

    APPLY --> TRANSITION
    APPLY --> COMMENT
    APPLY --> ASSIGN
    APPLY --> NOTIFY

    TRANSITION --> LOG
    COMMENT --> LOG
    ASSIGN --> LOG
    NOTIFY --> ALERTS
    LOG --> METRICS
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| SprintDaemon | `services/sprint/daemon.py` | Main daemon class |
| WorkflowConfig | `services/sprint/bot/workflow_config.py` | Rule configuration |
| ExecutionTracer | `services/sprint/bot/execution_tracer.py` | Execution tracing |

## Workflow Rules Example

```yaml
rules:
  - name: stale_in_progress
    condition:
      status: "In Progress"
      days_unchanged: 3
    action:
      comment: "Issue has been in progress for 3 days"
      notify: ["assignee", "#sprint-alerts"]

  - name: auto_close_merged
    condition:
      status: "In Review"
      mr_merged: true
    action:
      transition: "Done"
      comment: "Auto-closed: MR merged"
```

## D-Bus Methods

| Method | Description |
|--------|-------------|
| `process_now()` | Trigger immediate processing |
| `get_sprint_status()` | Get current sprint info |
| `toggle_rule(name, enabled)` | Enable/disable rule |
| `get_execution_history()` | Get recent executions |

## Related Diagrams

- [Daemon Overview](./daemon-overview.md)
- [Jira Integration](../07-integrations/jira-integration.md)
- [Sprint Automation Flow](../08-data-flows/sprint-automation.md)
