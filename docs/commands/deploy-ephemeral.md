# /deploy-ephemeral

> Deploy an MR or branch to an ephemeral environment.

## Overview

Deploy an MR or branch to an ephemeral environment.

## Arguments

No arguments required.

## Usage

## Process Flow

```mermaid
flowchart TD
    START([Start]) --> PROCESS[Process Command]
    PROCESS --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
```

## Details

## Prerequisites
1. Load DevOps persona: `persona_load("devops")`
2. Be logged into ephemeral cluster
3. Have the MR ID or branch name

## How to Use

Tell me:
- "Deploy MR 1459 to ephemeral"
- "Test AAP-61214 in ephemeral"
- "Deploy my branch to ephemeral"

I will:
1. Get the full commit SHA from GitLab
2. Verify image exists in Quay (Konflux build)
3. Reserve an ephemeral namespace
4. Deploy using bonfire with correct ClowdApp (main or billing)
5. Wait for pods to be ready
6. Report deployment status

## Important
- Uses `KUBECONFIG=~/.kube/config.e` (never copies kubeconfig!)
- Image tag must be 64-char SHA256 digest
- Template ref must be 40-char git SHA


## Related Commands

*(To be determined based on command relationships)*
