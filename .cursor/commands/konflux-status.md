# Konflux Status

Get overall Konflux platform health.

## Instructions

```
skill_run("konflux_status", '{}')
```

## What It Does

1. Shows running and failed pipelines
2. Lists recent builds and their status
3. Checks application health
4. Summarizes namespace activity

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `namespace` | Specific namespace | `aap-aa-tenant` |
| `application` | Filter by application | All |

## Examples

```bash
# Overall Konflux status
skill_run("konflux_status", '{}')

# Specific namespace
skill_run("konflux_status", '{"namespace": "aap-aa-tenant"}')
```
