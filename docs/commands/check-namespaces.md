# /check-namespaces

> List and manage your ephemeral namespaces.

## Overview

List and manage your ephemeral namespaces.

## Arguments

No arguments required.

## Usage

### Examples

```bash
KUBECONFIG=~/.kube/config.e bonfire namespace list --mine
```

```bash
KUBECONFIG=~/.kube/config.e bonfire namespace release <namespace-name> --force
```

## Process Flow

```mermaid
flowchart TD
    START([Start]) --> PROCESS[Process Command]
    PROCESS --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
```

## Details


## Related Commands

*(To be determined based on command relationships)*
