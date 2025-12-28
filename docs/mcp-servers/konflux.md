# 🔄 konflux

> Build pipelines and CI/CD

## Overview

The `aa-konflux` module provides tools for Konflux (Tekton-based) build pipeline management.

## Tool Count

**40 tools**

## Tools

### Pipelines

| Tool | Description |
|------|-------------|
| `konflux_pipeline_list` | List pipelines |
| `konflux_pipeline_status` | Get pipeline status |
| `konflux_pipeline_logs` | Get pipeline logs |
| `konflux_pipeline_retry` | Retry failed pipeline |
| `konflux_pipeline_cancel` | Cancel running pipeline |

### Applications

| Tool | Description |
|------|-------------|
| `konflux_app_list` | List applications |
| `konflux_app_status` | Get app status |
| `konflux_component_list` | List components |
| `konflux_component_status` | Component details |

### Builds

| Tool | Description |
|------|-------------|
| `konflux_build_list` | List builds |
| `konflux_build_status` | Build status |
| `konflux_build_logs` | Build logs |

### Integration Tests

| Tool | Description |
|------|-------------|
| `konflux_integration_test_list` | List tests |
| `konflux_integration_test_status` | Test status |
| `konflux_integration_test_logs` | Test logs |

## Usage Examples

### Check Pipeline Status

```python
konflux_pipeline_status(
    namespace="aap-aa-tenant",
    pipeline_name="aap-aa-main-on-push"
)
```

### Get Build Logs

```python
konflux_build_logs(
    namespace="aap-aa-tenant",
    build_name="automation-analytics-backend-main-abc123"
)
```

### List Recent Builds

```python
konflux_build_list(
    namespace="aap-aa-tenant",
    component="automation-analytics-backend-main",
    limit=10
)
```

## Loaded By

- [📦 Release Agent](../agents/release.md)

## Related Skills

- [release_aa_backend_prod](../skills/release_aa_backend_prod.md) - Checks builds before release
