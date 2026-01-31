---
name: debug-prod
description: Investigate production issues in Automation Analytics
license: MIT
compatibility: opencode
metadata:
  version: "2.0"
  source: debug_prod.yaml
  executable: "true"
---

# debug_prod

Investigate production issues in Automation Analytics.
Gathers pod status, logs, metrics, alerts, and recent deployments.
Suggests likely causes based on patterns and learned knowledge.

**NEW Features:**
- Semantic search for error handlers in codebase
- DevOps knowledge integration for deployment patterns
- Cross-reference with recent code changes
- Architecture-aware debugging suggestions

Resolves namespace and paths from config.json.

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("debug_prod", '{
  "namespace": "example-namespace",
  "alert_name": "example-alert_name",
  "pod_filter": "example-pod_filter",
  "time_range": "1h"
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load incident persona for Prometheus, Alertmanager, Kibana, and K8s tools**
2. **Check for known Kubernetes issues before starting**
3. **Check for known Kibana issues before starting**
4. **Load namespace and path configuration**
5. **Resolve which namespace to investigate**
6. **check_namespace**
7. **Load known error patterns from memory**
8. **Check pod status in namespace**
9. **Get CPU/memory usage for pods**
10. **Parse resource usage data**
11. **Identify unhealthy pods**
12. **Get recent Kubernetes events**
13. **filter_events**
14. **Get recent error logs from pods**
15. **Get detailed info on first problem pod**
16. **Get logs from first problem pod**
17. **Get logs from second problem pod**
18. **Get logs from third problem pod**
19. **Extract error lines from logs**
20. **Get currently firing alerts**
21. **Look up alert definition**
22. **Search Kibana for recent errors**
23. **Initial check for Kibana auth issues**
24. **Load slack persona for Slack channel reading**
25. **Find team channel ID**
26. **Check team Slack channel for recent relevant discussions**
27. **Parse Slack messages for relevant discussion**
28. **Finalize Kibana results after Slack check**
29. **Get SaaS pipeline status**
30. **Get SaaS deployment status**
31. **Parse SaaS deployment info**
32. **Query 5xx error rate from Prometheus**
33. **Query error rate trend over time**
34. **Query memory usage trend**
35. **Check pod health metrics**
36. **Get alerting rules for this namespace**
37. **List available Grafana dashboards**
38. **Get main AA dashboard from Grafana**
39. **Get Grafana dashboard link**
40. **Parse Prometheus query results**
41. **Build metric queries for reference**
42. **Get deployment info**
43. **Get replicasets for recent rollouts**
44. **Combine deployment and replicaset info**
45. **Get currently deployed SHA from app-interface config**
46. **Get namespace configuration from app-interface**
47. **Match issues against known patterns**
48. **Find error handling code for observed errors**
49. **Parse error handler search results**
50. **Load DevOps knowledge for debugging context**
51. **Parse DevOps deployment patterns**
52. **Load production-specific gotchas**
53. **Parse production gotchas**
54. **Search for code changes in deployed version**
55. **Parse deployed code search**
56. **build_report**
57. **Build context for memory updates**
58. **Log debug session**
59. **Update environment status after debugging**
60. **Detect failure patterns from debug operations**
61. **Learn from production cluster auth failures**
62. **Learn from production VPN failures**
63. **Learn from Prometheus connection failures**
64. **Learn from Kibana auth failures**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `namespace` | string | No | `-` | Namespace to investigate: 'main' or 'billing' (will ask if not provided) |
| `alert_name` | string | No | `-` | Prometheus alert name if triggered by an alert |
| `pod_filter` | string | No | `-` | Filter pods by name (e.g., 'fastapi', 'processor') |
| `time_range` | string | No | `1h` | How far back to search (15m, 1h, 6h, 24h) |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the debug_prod skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("debug_prod", '{
  "namespace": "example-namespace",
  "alert_name": "example-alert_name",
  "pod_filter": "example-pod_filter",
  "time_range": "1h"
}')
```

### Via Command (if configured)

```
/debug-prod
```

## MCP Tools Used

- `alertmanager_alerts`
- `check_known_issues`
- `code_search`
- `grafana_dashboard_get`
- `grafana_dashboard_list`
- `kibana_search_logs`
- `knowledge_query`
- `kubectl_describe_pod`
- `kubectl_get`
- `kubectl_get_deployments`
- `kubectl_get_events`
- `kubectl_get_pods`
- `kubectl_logs`
- `kubectl_saas_deployments`
- `kubectl_saas_pipelines`
- `kubectl_top_pods`
- `learn_tool_fix`
- `memory_session_log`
- `persona_load`
- `prometheus_grafana_link`
- `prometheus_pod_health`
- `prometheus_query`
- `prometheus_query_range`
- `prometheus_rules`
- `slack_find_channel`
- `slack_list_messages`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/debug_prod.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/debug_prod.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
