# Sprint Workflow

> Jira workflow automation rules and transitions

## Diagram

```mermaid
flowchart TB
    subgraph Triggers[Trigger Conditions]
        TIME[Time-based<br/>Stale issues]
        EVENT[Event-based<br/>MR merged]
        STATUS[Status-based<br/>Blocked too long]
        MANUAL[Manual<br/>D-Bus call]
    end

    subgraph Rules[Rule Engine]
        EVAL[Evaluate Conditions]
        MATCH[Match Rules]
        PRIORITY[Sort by Priority]
        SELECT[Select Actions]
    end

    subgraph Actions[Available Actions]
        TRANS[Transition Issue]
        COMMENT[Add Comment]
        ASSIGN[Change Assignee]
        LABEL[Add/Remove Labels]
        LINK[Link Issues]
        NOTIFY[Send Notification]
    end

    subgraph Targets[Notification Targets]
        SLACK_CH[Slack Channel]
        SLACK_DM[Slack DM]
        EMAIL[Email]
        MEMORY[Memory Log]
    end

    TIME --> EVAL
    EVENT --> EVAL
    STATUS --> EVAL
    MANUAL --> EVAL

    EVAL --> MATCH
    MATCH --> PRIORITY
    PRIORITY --> SELECT

    SELECT --> TRANS
    SELECT --> COMMENT
    SELECT --> ASSIGN
    SELECT --> LABEL
    SELECT --> LINK
    SELECT --> NOTIFY

    NOTIFY --> SLACK_CH
    NOTIFY --> SLACK_DM
    NOTIFY --> EMAIL
    NOTIFY --> MEMORY
```

## Rule Evaluation

```mermaid
sequenceDiagram
    participant Daemon as SprintDaemon
    participant Config as WorkflowConfig
    participant Jira as Jira API
    participant Notifier as Notification Engine

    Daemon->>Config: get_rules_for_status(status)
    Config-->>Daemon: Matching rules

    loop For each rule
        Daemon->>Daemon: Evaluate condition

        alt Condition matches
            Daemon->>Jira: Apply action
            Jira-->>Daemon: Result

            alt Has notification
                Daemon->>Notifier: Send notification
            end
        end
    end
```

## Workflow States

```mermaid
stateDiagram-v2
    [*] --> Open: Issue created

    Open --> InProgress: Start work
    Open --> Blocked: Blocked by dependency

    InProgress --> InReview: MR created
    InProgress --> Blocked: Hit blocker
    InProgress --> Open: Unassign

    InReview --> Done: MR merged
    InReview --> InProgress: Changes requested

    Blocked --> InProgress: Blocker resolved
    Blocked --> Open: Reassign

    Done --> [*]

    note right of InProgress
        Auto-alert if stale > 3 days
    end note

    note right of InReview
        Auto-close when MR merged
    end note

    note right of Blocked
        Daily reminder to assignee
    end note
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| WorkflowConfig | `services/sprint/bot/workflow_config.py` | Rule definitions |
| ExecutionTracer | `services/sprint/bot/execution_tracer.py` | Action logging |
| SprintDaemon | `services/sprint/daemon.py` | Rule executor |

## Rule Schema

```yaml
rule:
  name: string           # Unique rule name
  description: string    # Human-readable description
  enabled: boolean       # Enable/disable rule
  priority: integer      # Execution order (lower = first)

  condition:
    status: string       # Issue status
    days_unchanged: int  # Days since last update
    days_in_status: int  # Days in current status
    assignee: string     # Assignee filter
    labels: list         # Required labels
    mr_merged: boolean   # MR merge status
    custom_field: any    # Custom field check

  action:
    transition: string   # Target status
    comment: string      # Comment to add
    assignee: string     # New assignee
    labels_add: list     # Labels to add
    labels_remove: list  # Labels to remove
    notify: list         # Notification targets
```

## Built-in Rules

| Rule | Trigger | Action |
|------|---------|--------|
| stale_in_progress | In Progress > 3 days | Comment + notify |
| auto_close_merged | In Review + MR merged | Transition to Done |
| blocked_reminder | Blocked > 1 day | Daily DM to assignee |
| unassigned_alert | Open + no assignee | Notify channel |
| sprint_end_warning | 2 days before end | Notify incomplete |

## Related Diagrams

- [Sprint Daemon](./sprint-daemon.md)
- [Jira Integration](../07-integrations/jira-integration.md)
- [Sprint Automation Flow](../08-data-flows/sprint-automation.md)
