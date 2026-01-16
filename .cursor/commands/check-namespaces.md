# Check My Namespaces

List and manage your ephemeral namespaces.

## Prerequisites

Load the devops persona first:
```text
persona_load("devops")
```

## Instructions

List your namespaces:
```text
bonfire_namespace_list(mine_only=true)
```

## Actions

### Release a namespace

```text
bonfire_namespace_release(namespace="ephemeral-xxxxx")
```

### Extend a namespace

```text
bonfire_namespace_extend(namespace="ephemeral-xxxxx", duration="2h")
```

## Manual Commands

If you prefer raw shell commands:

```bash
# List your namespaces
KUBECONFIG=~/.kube/config.e bonfire namespace list --mine

# Release a namespace
KUBECONFIG=~/.kube/config.e bonfire namespace release <namespace-name> --force
```

**Note**: Only releases namespaces you own (safety check built-in).

## See Also

- `/extend-ephemeral` - Extend namespace lifetime
- `/test-ephemeral` - Deploy MR to ephemeral
- `/deploy` - Quick deploy command
