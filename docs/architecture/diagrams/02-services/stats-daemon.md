# Stats Daemon

> Statistics collection and aggregation service

## Diagram

```mermaid
graph TB
    subgraph Sources[Data Sources]
        MCP[MCP Server]
        DAEMONS[Other Daemons]
        TOOLS[Tool Modules]
        MEMORY[Memory System]
    end

    subgraph Daemon[Stats Daemon]
        COLLECTOR[Stats Collector]
        AGGREGATOR[Aggregator]
        STORAGE[Stats Storage]
        API[D-Bus API]
    end

    subgraph Metrics[Metric Types]
        COUNTERS[Counters]
        GAUGES[Gauges]
        HISTOGRAMS[Histograms]
        TIMERS[Timers]
    end

    subgraph Output[Output]
        JSON_FILE[stats.json]
        DBUS_QUERY[D-Bus Queries]
        PROMETHEUS[Prometheus Export]
    end

    MCP --> COLLECTOR
    DAEMONS --> COLLECTOR
    TOOLS --> COLLECTOR
    MEMORY --> COLLECTOR

    COLLECTOR --> COUNTERS
    COLLECTOR --> GAUGES
    COLLECTOR --> HISTOGRAMS
    COLLECTOR --> TIMERS

    COUNTERS --> AGGREGATOR
    GAUGES --> AGGREGATOR
    HISTOGRAMS --> AGGREGATOR
    TIMERS --> AGGREGATOR

    AGGREGATOR --> STORAGE
    STORAGE --> JSON_FILE
    STORAGE --> API
    API --> DBUS_QUERY
    API --> PROMETHEUS
```

## Class Structure

```mermaid
classDiagram
    class StatsDaemon {
        +name: str = "stats"
        +service_name: str
        -_collector: StatsCollector
        -_aggregator: Aggregator
        -_storage: StatsStorage
        +startup() async
        +run_daemon() async
        +shutdown() async
        +record(metric, value)
        +get_stats(metric): dict
        +get_all_stats(): dict
        +get_service_stats() async
    }

    class StatsCollector {
        +counters: dict
        +gauges: dict
        +histograms: dict
        +timers: dict
        +increment(name, value)
        +set_gauge(name, value)
        +observe(name, value)
        +start_timer(name)
        +stop_timer(name)
    }

    class Aggregator {
        +aggregate_counters(): dict
        +aggregate_gauges(): dict
        +compute_percentiles(histogram): dict
        +compute_rates(counter, window): float
    }

    class StatsStorage {
        +current: dict
        +history: list
        +save()
        +load()
        +get_history(metric, range): list
    }

    StatsDaemon --> StatsCollector
    StatsDaemon --> Aggregator
    StatsDaemon --> StatsStorage
```

## Metric Collection Flow

```mermaid
sequenceDiagram
    participant Source as Data Source
    participant Daemon as StatsDaemon
    participant Collector as StatsCollector
    participant Aggregator as Aggregator
    participant Storage as StatsStorage

    Source->>Daemon: record("tool_calls", 1)
    Daemon->>Collector: increment("tool_calls", 1)
    Collector->>Collector: Update counter

    loop Every minute
        Daemon->>Aggregator: aggregate()
        Aggregator->>Collector: Get all metrics
        Collector-->>Aggregator: Raw metrics
        Aggregator->>Aggregator: Compute aggregates
        Aggregator-->>Daemon: Aggregated stats
        Daemon->>Storage: save(stats)
    end
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| StatsDaemon | `services/stats/daemon.py` | Main daemon class |
| StatsCollector | Internal | Metric collection |
| Aggregator | Internal | Metric aggregation |
| StatsStorage | Internal | Persistence |

## Metric Types

| Type | Description | Example |
|------|-------------|---------|
| Counter | Monotonic count | `tool_calls_total` |
| Gauge | Current value | `active_sessions` |
| Histogram | Distribution | `response_time_ms` |
| Timer | Duration tracking | `skill_execution_time` |

## D-Bus Methods

| Method | Description |
|--------|-------------|
| `record(metric, value)` | Record metric value |
| `get_stats(metric)` | Get specific metric |
| `get_all_stats()` | Get all metrics |
| `get_history(metric, range)` | Get historical data |
| `reset_stats()` | Reset all counters |

## Collected Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `tool_calls_total` | Counter | Total tool invocations |
| `skill_executions_total` | Counter | Total skill runs |
| `skill_failures_total` | Counter | Failed skill runs |
| `active_sessions` | Gauge | Current sessions |
| `memory_usage_bytes` | Gauge | Memory consumption |
| `response_time_ms` | Histogram | Tool response times |
| `skill_duration_ms` | Histogram | Skill execution times |

## Output Format

```json
{
  "timestamp": "2024-01-15T12:00:00",
  "counters": {
    "tool_calls_total": 1234,
    "skill_executions_total": 56
  },
  "gauges": {
    "active_sessions": 3,
    "memory_usage_bytes": 104857600
  },
  "histograms": {
    "response_time_ms": {
      "p50": 45,
      "p90": 120,
      "p99": 350
    }
  }
}
```

## Related Diagrams

- [Daemon Overview](./daemon-overview.md)
- [Memory Architecture](../06-memory/memory-architecture.md)
