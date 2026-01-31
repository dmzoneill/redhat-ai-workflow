---
name: investigate-slack-alert
description: Investigate Prometheus alerts from Slack and create/link Jira issues
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: investigate_slack_alert.yaml
  executable: "true"
---

# investigate_slack_alert

Investigate Prometheus alerts from Slack and create/link Jira issues.

## Trigger
Called when a message from app-sre-alerts is detected in alert channels:
- C01CPSKFG0P (stage alerts)
- C01L1K82AP5 (prod alerts)

## Behavior
1. Immediately reply to acknowledge ("Looking into this...")
2. Parse alert name, namespace, severity from Slack message
3. Check pod status and logs for errors
4. Search for existing Jira issues matching the alert
5. If no match, create a new Jira issue
6. For billing alerts: use special "BillingEvent XXXXX" format
7. Reply with Jira link and investigation summary

## Billing Alert Special Handling
Billing alerts (containing "billing", "subscription", "vcpu", etc.) get:
- Higher priority
- Special Jira format: "BillingEvent XXXXX - [Processor] Error: ..."
- Numbered sequentially from existing billing events

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("investigate_slack_alert", '{
  "channel_id": "example-channel_id",
  "message_ts": "example-message_ts",
  "message_text": "example-message_text",
  "alert_url": "example-alert_url"
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load incident persona for Kubernetes investigation tools**
2. **Initialize failure tracking**
3. **Get alert investigation patterns from knowledge base**
4. **Parse alert knowledge for investigation context**
5. **Check for known alert patterns**
6. **Load alert channel configuration**
7. **Extract alert details from Slack message using shared parser**
8. **Load slack persona for Slack reply tools**
9. **Reply to Slack thread to acknowledge we're looking into it**
10. **Load incident persona for Kubernetes investigation tools**
11. **Determine correct kubeconfig for environment**
12. **Get pod status in the affected namespace**
13. **Identify unhealthy pods using shared parser**
14. **Get recent error logs from processor pods**
15. **Extract error patterns from logs using shared parser**
16. **Find code related to the alert**
17. **Parse code search results for alert**
18. **Search for existing Jira issues matching this alert**
19. **Search for billing event issues if this is a billing alert**
20. **Determine if we have a matching issue or need to create one using shared parsers**
21. **Build the Jira issue summary**
22. **Build the Jira issue description**
23. **Create a new Jira issue for this alert (uses create_jira_issue skill)**
24. **Extract the Jira issue key using shared parser**
25. **Build the Slack response with findings**
26. **Load slack persona for Slack reply**
27. **Reply to Slack with investigation findings**
28. **Update environment status after investigation**
29. **Log Slack alert investigation to session**
30. **Detect failure patterns from Slack alert investigation**
31. **Learn from Kubernetes auth failures**
32. **Learn from VPN failures**
33. **Learn from Kibana auth failures**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `channel_id` | string | Yes | `-` | Slack channel ID where alert was posted |
| `message_ts` | string | Yes | `-` | Slack message timestamp (for threading replies) |
| `message_text` | string | Yes | `-` | The alert message content (HTML or text) |
| `alert_url` | string | No | `-` | URL to AlertManager (extracted from message) |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the investigate_slack_alert skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("investigate_slack_alert", '{
  "channel_id": "example-channel_id",
  "message_ts": "example-message_ts",
  "message_text": "example-message_text",
  "alert_url": "example-alert_url"
}')
```

### Via Command (if configured)

```
/investigate-slack-alert
```

## MCP Tools Used

- `code_search`
- `jira_search`
- `knowledge_query`
- `kubectl_get_pods`
- `kubectl_logs`
- `learn_tool_fix`
- `memory_session_log`
- `persona_load`
- `skill_run`
- `slack_send_message`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/investigate_slack_alert.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/investigate_slack_alert.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
