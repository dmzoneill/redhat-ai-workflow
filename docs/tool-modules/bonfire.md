# 🔥 bonfire

> Ephemeral namespace management

## Overview

The `aa-bonfire` module provides tools for managing ephemeral Kubernetes namespaces using the `bonfire` CLI.

## Tool Count

**21 tools**

## Tools

### Namespace Management

| Tool | Description |
|------|-------------|
| `bonfire_namespace_list` | List namespaces |
| `bonfire_namespace_reserve` | Reserve a namespace |
| `bonfire_namespace_release` | Release a namespace |
| `bonfire_namespace_extend` | Extend reservation |

### Deployment

| Tool | Description |
|------|-------------|
| `bonfire_deploy_aa` | Deploy Automation Analytics |
| `bonfire_deploy_aa_local` | Deploy from local config |
| `bonfire_deploy_aa_from_snapshot` | Deploy from snapshot |

### Configuration

| Tool | Description |
|------|-------------|
| `bonfire_config_list` | List configurations |
| `bonfire_app_config` | Get app config |

## Critical Rules

⚠️ **NEVER do these:**

| ❌ Don't | ✅ Do Instead |
|---------|---------------|
| `cp ~/.kube/config.e ~/.kube/config` | Use MCP tools (auto handles kubeconfig) |
| Use short SHA (8 chars) | Always use full 40-char SHA |
| Run raw `bonfire` commands | Use the MCP tools |

## Usage Examples

### List Your Namespaces

```python
bonfire_namespace_list(mine_only=True)
```

### Reserve Namespace

```python
bonfire_namespace_reserve(duration="2h")
```

### Deploy Application

```python
bonfire_deploy_aa(
    namespace="ephemeral-nx6n2s",
    template_ref="abc123def456789...",  # Full 40-char SHA
    image_tag="sha256:20a4c976...",     # 64-char digest
    billing=False
)
```

### Release Namespace

```python
bonfire_namespace_release(
    namespace="ephemeral-nx6n2s",
    force=True
)
```

## Deploy Command Pattern

The tool generates bonfire commands like:

```bash
KUBECONFIG=~/.kube/config.e bonfire deploy \
  --source=appsre \
  --ref-env insights-production \
  --namespace ephemeral-nx6n2s \
  --timeout 900 \
  --component tower-analytics-clowdapp \
  --set-template-ref tower-analytics-clowdapp=<git-sha> \
  --set-parameter tower-analytics-clowdapp/IMAGE=quay.io/.../image@sha256 \
  --set-parameter tower-analytics-clowdapp/IMAGE_TAG=<sha256-digest> \
  tower-analytics
```

## Loaded By

- [🔧 DevOps Persona](../personas/devops.md)

## Related Skills

- [test_mr_ephemeral](../skills/test_mr_ephemeral.md) - Full deployment workflow
