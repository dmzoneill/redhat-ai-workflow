---
name: appinterface-check
description: "Validate app-interface GitOps configuration."
arguments:
  - name: saas_file
    required: true
---
# App-Interface Check

Validate app-interface GitOps configuration.

## Instructions

```text
skill_run("appinterface_check", '{"saas_file": "$SAAS_FILE"}')
```

## What It Does

1. Validates app-interface configuration
2. Shows SaaS file contents and refs
3. Compares against live state
4. Lists resource quotas and limits

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `saas_file` | SaaS file to check | Auto-detect |
| `environment` | Environment to validate | All |

## Examples

```bash
# Check tower-analytics SaaS
skill_run("appinterface_check", '{"saas_file": "tower-analytics"}')

# Check specific environment
skill_run("appinterface_check", '{"saas_file": "tower-analytics", "environment": "stage"}')
```
