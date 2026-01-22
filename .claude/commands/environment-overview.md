---
name: environment-overview
description: "Get an overview of all environments (stage, prod, ephemeral)."
arguments:
  - name: environment
---
# Environment Overview

Get an overview of all environments (stage, prod, ephemeral).

## Instructions

```text
skill_run("environment_overview", '{}')
```

## What It Does

1. Checks stage cluster health
2. Checks production cluster health
3. Lists active ephemeral namespaces
4. Shows recent deployments
5. Highlights any issues

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `environment` | Specific env to check | No (all) |

## Examples

```bash
# Overview of all environments
skill_run("environment_overview", '{}')

# Check specific environment
skill_run("environment_overview", '{"environment": "stage"}')
```

## Output

- Pod status for each environment
- Recent deployment info
- Active alerts
- Resource usage
