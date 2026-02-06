# Observability Integration

> Prometheus, Alertmanager, and Kibana integration

## Diagram

```mermaid
graph TB
    subgraph Modules[Observability Modules]
        PROMETHEUS[aa_prometheus]
        ALERTMANAGER[aa_alertmanager]
        KIBANA[aa_kibana]
    end

    subgraph Operations[Operations]
        PROM_OPS[Query metrics<br/>Range query<br/>Instant query]
        ALERT_OPS[List alerts<br/>Silence alert<br/>Get status]
        KIBANA_OPS[Search logs<br/>Get indices<br/>Query DSL]
    end

    subgraph APIs[APIs]
        PROM_API[Prometheus API]
        ALERT_API[Alertmanager API]
        KIBANA_API[Kibana/ES API]
    end

    Modules --> Operations
    Operations --> APIs
```

## Incident Response Flow

```mermaid
sequenceDiagram
    participant User as User/Claude
    participant Alert as alertmanager_list
    participant Prom as prometheus_query
    participant Kibana as kibana_search
    participant K8s as k8s_logs

    User->>Alert: What's firing?
    Alert-->>User: P1: HighErrorRate

    User->>Prom: Query error rate
    Prom-->>User: 5xx rate: 15%

    User->>Kibana: Search error logs
    Kibana-->>User: Stack traces

    User->>K8s: Get pod logs
    K8s-->>User: Application logs
```

## Prometheus Tools

| Tool | Description | Endpoint |
|------|-------------|----------|
| prometheus_query | Instant query | /api/v1/query |
| prometheus_query_range | Range query | /api/v1/query_range |
| prometheus_alerts | Get alerts | /api/v1/alerts |
| prometheus_targets | Get targets | /api/v1/targets |

## Alertmanager Tools

| Tool | Description | Endpoint |
|------|-------------|----------|
| alertmanager_list | List alerts | /api/v2/alerts |
| alertmanager_silence | Create silence | /api/v2/silences |
| alertmanager_status | Get status | /api/v2/status |

## Kibana Tools

| Tool | Description | Endpoint |
|------|-------------|----------|
| kibana_search | Search logs | /_search |
| kibana_indices | List indices | /_cat/indices |
| kibana_query | DSL query | /_search |

## Query Examples

```mermaid
flowchart TB
    subgraph PromQL[PromQL Examples]
        RATE["rate(http_requests_total[5m])"]
        ERROR["sum(rate(http_errors[1h]))"]
        LATENCY["histogram_quantile(0.99, ...)"]
    end

    subgraph KQL[Kibana Query]
        LOG_SEARCH["level:error AND service:api"]
        TIME_RANGE["@timestamp:[now-1h TO now]"]
    end
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| aa_prometheus | `tool_modules/aa_prometheus/` | Metrics tools |
| aa_alertmanager | `tool_modules/aa_alertmanager/` | Alert tools |
| aa_kibana | `tool_modules/aa_kibana/` | Log tools |

## Related Diagrams

- [Observability Tools](../03-tools/observability-tools.md)
- [Incident Persona](../05-personas/persona-definitions.md)
- [Auto-Heal Decorator](../01-server/auto-heal-decorator.md)
