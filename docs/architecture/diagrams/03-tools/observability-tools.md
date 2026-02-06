# Observability Tools

> Prometheus, Alertmanager, and Kibana integration modules

## Diagram

```mermaid
classDiagram
    class PrometheusBasic {
        +prometheus_query(query): dict
        +prometheus_query_range(query, start, end): dict
        +prometheus_alerts(): list
        +prometheus_targets(): list
        +prometheus_rules(): list
    }

    class PrometheusExtra {
        +prometheus_series(match): list
        +prometheus_labels(label): list
        +prometheus_metadata(metric): dict
    }

    class AlertmanagerBasic {
        +alertmanager_alerts(): list
        +alertmanager_silences(): list
        +alertmanager_status(): dict
    }

    class AlertmanagerExtra {
        +alertmanager_create_silence(matchers, duration): dict
        +alertmanager_delete_silence(id): dict
    }

    class KibanaBasic {
        +kibana_search(index, query): list
        +kibana_get_logs(app, namespace, lines): list
        +kibana_list_indices(): list
    }

    PrometheusBasic <|-- PrometheusExtra
    AlertmanagerBasic <|-- AlertmanagerExtra
```

## Query Flow

```mermaid
sequenceDiagram
    participant Tool as Observability Tool
    participant Client as HTTP Client
    participant Prom as Prometheus
    participant Alert as Alertmanager
    participant Kibana as Kibana

    alt Prometheus Query
        Tool->>Client: Build PromQL query
        Client->>Prom: GET /api/v1/query
        Prom-->>Client: Query result
        Client-->>Tool: Formatted metrics
    else Alertmanager Query
        Tool->>Client: Build request
        Client->>Alert: GET /api/v2/alerts
        Alert-->>Client: Alert list
        Client-->>Tool: Formatted alerts
    else Kibana Search
        Tool->>Client: Build Lucene query
        Client->>Kibana: POST /_search
        Kibana-->>Client: Search results
        Client-->>Tool: Formatted logs
    end
```

## Components

| Module | File | Description |
|--------|------|-------------|
| aa_prometheus | `tool_modules/aa_prometheus/` | Prometheus queries |
| aa_alertmanager | `tool_modules/aa_alertmanager/` | Alert management |
| aa_kibana | `tool_modules/aa_kibana/` | Log search |

## Tool Summary

| Tool | Module | Description |
|------|--------|-------------|
| `prometheus_query` | prometheus | Execute PromQL query |
| `prometheus_alerts` | prometheus | Get firing alerts |
| `alertmanager_alerts` | alertmanager | List alerts |
| `alertmanager_create_silence` | alertmanager | Create silence |
| `kibana_search` | kibana | Search logs |
| `kibana_get_logs` | kibana | Get app logs |

## PromQL Examples

```promql
# CPU usage by pod
sum(rate(container_cpu_usage_seconds_total{namespace="tower-analytics-stage"}[5m])) by (pod)

# Memory usage
container_memory_usage_bytes{namespace="tower-analytics-stage"}

# Request rate
sum(rate(http_requests_total{namespace="tower-analytics-stage"}[5m]))

# Error rate
sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))
```

## Configuration

```json
{
  "observability": {
    "prometheus": {
      "url": "https://prometheus.example.com",
      "token_env": "PROMETHEUS_TOKEN"
    },
    "alertmanager": {
      "url": "https://alertmanager.example.com"
    },
    "kibana": {
      "url": "https://kibana.example.com",
      "index_pattern": "app-*"
    }
  }
}
```

## Incident Response Flow

```mermaid
flowchart TB
    subgraph Detection[Alert Detection]
        PROM_ALERT[Prometheus Alert]
        AM_ALERT[Alertmanager]
    end

    subgraph Investigation[Investigation]
        QUERY[prometheus_query]
        LOGS[kibana_get_logs]
        METRICS[prometheus_query_range]
    end

    subgraph Response[Response]
        SILENCE[alertmanager_create_silence]
        FIX[Apply fix]
        VERIFY[Verify resolution]
    end

    PROM_ALERT --> AM_ALERT
    AM_ALERT --> QUERY
    QUERY --> LOGS
    LOGS --> METRICS
    METRICS --> SILENCE
    SILENCE --> FIX
    FIX --> VERIFY
```

## Related Diagrams

- [Tool Module Structure](./tool-module-structure.md)
- [Incident Response Flow](../08-data-flows/incident-response.md)
- [Auto-Heal Decorator](../01-server/auto-heal-decorator.md)
