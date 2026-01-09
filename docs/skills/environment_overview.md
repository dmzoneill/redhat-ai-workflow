# ⚡ environment_overview

> Get a comprehensive overview of an environment

## Overview

Get a comprehensive overview of an environment.

This skill shows:
- Namespace health
- Service status
- Ingress configuration
- Pod summary

Uses: k8s_environment_summary, k8s_namespace_health, kubectl_get_services,
      kubectl_get_ingress, kubectl_get_pods

**Version:** 1.0

## Quick Start

```bash
skill_run("environment_overview", '{"issue_key": "AAP-12345"}')
```

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `namespace` | string | ✅ Yes | `-` | Kubernetes namespace |
| `environment` | string | No | `stage` | Environment (stage, production, ephemeral) |

## Process Flow

```mermaid
flowchart TD
    START([Start])
    STEP1[Step 1: Get Environment Summary]
    START --> STEP1
    STEP2[Step 2: Get Namespace Health]
    STEP1 --> STEP2
    STEP3[Step 3: Parse Health]
    STEP2 --> STEP3
    STEP4[Step 4: Get Services]
    STEP3 --> STEP4
    STEP5[Step 5: Parse Services]
    STEP4 --> STEP5
    STEP6[Step 6: Get Ingress]
    STEP5 --> STEP6
    STEP7[Step 7: Parse Ingress]
    STEP6 --> STEP7
    STEP8[Step 8: Get Pods]
    STEP7 --> STEP8
    STEP9[Step 9: Analyze Pods]
    STEP8 --> STEP9
    STEP9 --> DONE([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style DONE fill:#10b981,stroke:#059669,color:#fff
```

## Detailed Steps

### Step 1: Get Environment Summary

**Description:** Get environment summary

**Tool:** `k8s_environment_summary`

### Step 2: Get Namespace Health

**Description:** Get namespace health

**Tool:** `k8s_namespace_health`

### Step 3: Parse Health

**Description:** Parse namespace health

**Tool:** `compute`

### Step 4: Get Services

**Description:** List services in namespace

**Tool:** `kubectl_get_services`

### Step 5: Parse Services

**Description:** Parse services

**Tool:** `compute`

### Step 6: Get Ingress

**Description:** Get ingress configuration

**Tool:** `kubectl_get_ingress`

### Step 7: Parse Ingress

**Description:** Parse ingress

**Tool:** `compute`

### Step 8: Get Pods

**Description:** Get pod summary

**Tool:** `kubectl_get_pods`

### Step 9: Analyze Pods

**Description:** Analyze pod health

**Tool:** `compute`


## MCP Tools Used (5 total)

- `k8s_environment_summary`
- `k8s_namespace_health`
- `kubectl_get_ingress`
- `kubectl_get_pods`
- `kubectl_get_services`

## Related Skills

_(To be determined based on skill relationships)_
