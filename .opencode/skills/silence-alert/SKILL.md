---
name: silence-alert
description: Silence a Prometheus alert in Alertmanager
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: silence_alert.yaml
  executable: "true"
---

# silence_alert

Silence a Prometheus alert in Alertmanager.

Use when:
- You're working on a known issue and don't want alert noise
- Performing maintenance and expect alerts
- Need to temporarily suppress false positives

The skill will:
1. Verify the alert exists/is firing
2. Create a silence with appropriate duration
3. Optionally list existing silences
4. Provide commands to extend or remove the silence

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("silence_alert", '{
  "alert_name": "example-alert_name",
  "duration": "2h",
  "reason": "Investigating issue",
  "environment": "production",
  "namespace": "example-namespace",
  "action": "create",
  "silence_id": "example-silence_id"
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load incident persona for Alertmanager tools**
2. **Get alert patterns and silence guidance from knowledge base**
3. **Parse alert knowledge for silence context**
4. **Check for known alertmanager issues**
5. **Load previous silence history for this alert**
6. **Check if the alert is currently firing**
7. **Check if our target alert is firing**
8. **List all current silences**
9. **Parse existing silences**
10. **Create new silence for the alert**
11. **Parse silence creation result**
12. **Delete an existing silence**
13. **Log silence action to session**
14. **Learn from this silence for future reference**
15. **Track alerts that are frequently silenced**
16. **Update environment state with active silences**
17. **Search for code related to this alert**
18. **Parse alert code search results**
19. **Detect failure patterns from silence operations**
20. **Learn from Alertmanager connection failures**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `alert_name` | string | Yes | `-` | Name of the alert to silence (e.g., 'HighErrorRate', 'PodCrashLooping') |
| `duration` | string | No | `2h` | How long to silence (e.g., '1h', '2h', '4h', '24h') |
| `reason` | string | No | `Investigating issue` | Reason for silencing (for audit trail) |
| `environment` | string | No | `production` | Environment: 'production' or 'stage' |
| `namespace` | string | No | `-` | Optionally scope silence to specific namespace |
| `action` | string | No | `create` | Action: 'create', 'list', or 'delete' |
| `silence_id` | string | No | `-` | Silence ID (required for 'delete' action) |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the silence_alert skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("silence_alert", '{
  "alert_name": "example-alert_name",
  "duration": "2h",
  "reason": "Investigating issue",
  "environment": "production",
  "namespace": "example-namespace",
  "action": "create",
  "silence_id": "example-silence_id"
}')
```

### Via Command (if configured)

```
/silence-alert
```

## MCP Tools Used

- `alertmanager_alerts`
- `alertmanager_create_silence`
- `alertmanager_delete_silence`
- `alertmanager_list_silences`
- `code_search`
- `knowledge_query`
- `learn_tool_fix`
- `memory_session_log`
- `persona_load`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/silence_alert.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/silence_alert.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
