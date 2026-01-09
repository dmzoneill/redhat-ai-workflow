# 📊 prometheus

> Metrics and alert queries

## Overview

The `aa_prometheus` module provides tools for querying Prometheus metrics and checking alert status.

## Tool Count

**13 tools**

## Tools

| Tool | Description |
|------|-------------|
| `prometheus_query` | Execute PromQL query |
| `prometheus_query_range` | Time-range query |
| `prometheus_get_alerts` | List firing alerts |
| `prometheus_get_rules` | List alert rules |
| `prometheus_check_health` | API health check |
| `prometheus_get_targets` | List scrape targets |
| `prometheus_get_labels` | Get label values |
| `prometheus_get_metadata` | Get metric metadata |
| `prometheus_check_alert_rule` | Check specific rule |

## Usage Examples

### Execute Query

```python
prometheus_query(
    environment="production",
    query="sum(rate(http_requests_total[5m]))"
)
```

### Query Range

```python
prometheus_query_range(
    environment="stage",
    query="container_memory_usage_bytes{namespace='tower-analytics-stage'}",
    start="-1h",
    end="now",
    step="5m"
)
```

### Get Firing Alerts

```python
prometheus_get_alerts(environment="production")
```

## Authentication

Uses kubeconfig for authentication:

| Environment | Kubeconfig |
|-------------|------------|
| Stage | `~/.kube/config.s` |
| Production | `~/.kube/config.p` |

## Query Flow

```mermaid
flowchart TD
    START([PromQL Query]) --> AUTH[Get Kubeconfig Token]
    AUTH --> ENV{Environment?}
    ENV -->|Stage| STAGE_URL[Stage Prometheus URL]
    ENV -->|Production| PROD_URL[Prod Prometheus URL]

    STAGE_URL --> QUERY[Execute Query]
    PROD_URL --> QUERY

    QUERY --> PARSE[Parse JSON Response]
    PARSE --> FORMAT[Format Results]
    FORMAT --> RETURN([Return Metrics])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style RETURN fill:#10b981,stroke:#059669,color:#fff
```

## Loaded By

- [🚨 Incident Persona](../personas/incident.md)

## Related Skills

- [investigate_alert](../skills/investigate_alert.md) - Queries metrics
- [debug_prod](../skills/debug_prod.md) - Deep analysis
