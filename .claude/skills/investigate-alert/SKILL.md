---
name: investigate-alert
description: Quick investigation of a firing Prometheus alert
license: MIT
compatibility: opencode
metadata:
  version: "3.0"
  source: investigate_alert.yaml
  executable: "true"
---

# investigate_alert

Quick investigation of a firing Prometheus alert.

Steps:
1. Get current firing alerts
2. Quick health check (pods, deployments)
3. Check recent events
4. Look for known patterns
5. **NEW:** Search codebase for error source code
6. **NEW:** Load deployment gotchas from knowledge
7. Escalate to debug_prod if serious

Use this for quick triage. For deep investigation, use debug_prod directly.

Resolves namespaces and paths from config.json.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("investigate_alert", '{
  "environment": "example-environment",
  "namespace": "example-namespace",
  "alert_name": "example-alert_name",
  "auto_escalate": true
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load incident persona for Prometheus, Alertmanager, Kibana, and K8s tools**
2. **Check for known Prometheus issues before starting**
3. **Check for known Kubernetes issues before starting**
4. **Load namespace configuration**
5. **Determine the target namespace**
6. **Get currently firing alerts**
7. **Parse alert data using shared parser**
8. **Get overall namespace health**
9. **Parse namespace health**
10. **Get pod status**
11. **Get CPU/memory usage for pods**
12. **Parse resource usage for high consumption**
13. **Query error rate trend over last hour**
14. **Analyze error rate trend**
15. **Parse pod health**
16. **Get recent warning events**
17. **Parse events**
18. **Search Kibana for recent errors in namespace**
19. **Parse Kibana error results**
20. **Match against known error patterns**
21. **Search codebase for code related to this alert**
22. **Parse error source search results**
23. **Load deployment-related gotchas**
24. **Parse deployment gotchas**
25. **Search for code changes related to the alert**
26. **Parse recent changes search**
27. **Determine overall severity**
28. **Check if alerts are already silenced**
29. **Parse existing silences**
30. **Build silence recommendation for critical/high alerts**
31. **Run full debug_prod for serious issues**
32. **Notify team channel about critical alerts**
33. **Notify team channel about critical alerts via Slack**
34. **Notify team channel about escalated alerts**
35. **Build context for memory updates**
36. **Log alert investigation to session**
37. **Update environment status in memory**
38. **Detect failure patterns from alert investigation**
39. **Learn from Prometheus connection failures**
40. **Learn from Kubernetes auth failures**
41. **Learn from Kibana auth failures**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `environment` | string | Yes | `-` | Environment to investigate |
| `namespace` | string | No | `-` | Namespace: 'main' or 'billing' (defaults to main) |
| `alert_name` | string | No | `-` | Specific alert to investigate |
| `auto_escalate` | boolean | No | `true` | Auto-run debug_prod if critical issues found |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the investigate_alert skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("investigate_alert", '{
  "environment": "example-environment",
  "namespace": "example-namespace",
  "alert_name": "example-alert_name",
  "auto_escalate": true
}')
```

### Via Command (if configured)

```
/investigate-alert
```

## MCP Tools Used

- `alertmanager_list_silences`
- `check_known_issues`
- `code_search`
- `k8s_namespace_health`
- `kibana_search_logs`
- `knowledge_query`
- `kubectl_get_events`
- `kubectl_get_pods`
- `kubectl_top_pods`
- `learn_tool_fix`
- `memory_session_log`
- `persona_load`
- `prometheus_alerts`
- `prometheus_query_range`
- `skill_run`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/investigate_alert.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/investigate_alert.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
