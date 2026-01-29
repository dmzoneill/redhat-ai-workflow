# Observability Persona

Monitoring, metrics, and logs - no incident response.

## Overview

The observability persona provides monitoring and logging tools without the full incident response toolset. Use this for general observability tasks and health checks.

## Tool Modules

| Module | Tools | Purpose |
|--------|-------|---------|
| workflow | 51 | Core system tools |
| prometheus | 13 | Metrics queries |
| kibana | 9 | Log search |

**Total:** ~73 tools

## Key Skills

| Skill | Description |
|-------|-------------|
| environment_overview | Health check |
| check_ci_health | Pipeline health |

## Use Cases

- Query Prometheus metrics
- Search Kibana logs
- Health monitoring
- Dashboard queries

## Loading

```
persona_load("observability")
```

## Comparison with Incident

| Aspect | Observability | Incident |
|--------|---------------|----------|
| Focus | Read-only monitoring | Active response |
| Alertmanager | No | Yes |
| K8s tools | No | Yes |
| Use case | Health checks | Production issues |

## See Also

- [Personas Overview](./README.md)
- [Incident Persona](./incident.md) - Full incident response
- [Prometheus Tools](../tool-modules/prometheus.md)
