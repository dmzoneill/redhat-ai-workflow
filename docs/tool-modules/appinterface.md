# 🔗 appinterface

> GitOps configuration management

## Overview

The `aa-appinterface` module provides tools for managing app-interface (GitOps) configuration.

## Tool Count

**6 tools**

## Tools

| Tool | Description |
|------|-------------|
| `appinterface_get_config` | Get current config |
| `appinterface_get_ref` | Get deployed ref |
| `appinterface_update_ref` | Update image ref |
| `appinterface_get_namespace` | Get namespace config |
| `appinterface_get_alerts` | Get alert definitions |
| `appinterface_validate` | Validate changes |

## Key Paths

```
app-interface/
├── data/services/insights/tower-analytics/
│   ├── cicd/
│   │   └── deploy-clowder.yml      # Deployment config
│   └── namespaces/
│       ├── tower-analytics-prod.yml
│       ├── tower-analytics-stage.yml
│       └── tower-analytics-prod-billing.yml
└── resources/
    ├── insights-prod/              # Production alerts
    └── insights-stage/             # Stage alerts
```

## Usage Examples

### Get Current Deployed SHA

```python
appinterface_get_ref(
    namespace="tower-analytics-prod",
    component="tower-analytics-clowdapp"
)
```

### Get Alert Definitions

```python
appinterface_get_alerts(namespace="tower-analytics-prod")
```

## Loaded By

- [📦 Release Persona](../personas/release.md)

## Related Skills

- [release_aa_backend_prod](../skills/release_aa_backend_prod.md) - Updates refs
- [debug_prod](../skills/debug_prod.md) - Checks deployed version
