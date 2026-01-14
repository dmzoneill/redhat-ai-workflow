# Extend Ephemeral

Extend the lifetime of an ephemeral namespace.

## Instructions

```text
skill_run("extend_ephemeral", '{"namespace": "$NAMESPACE"}')
```

## What It Does

1. Lists your ephemeral namespaces
2. Shows current expiration time
3. Extends the namespace lifetime

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `namespace` | Namespace to extend | Auto-detect (if only one) |
| `hours` | Hours to extend | `4` |

## Examples

```bash
# Extend your namespace
skill_run("extend_ephemeral", '{}')

# Extend specific namespace
skill_run("extend_ephemeral", '{"namespace": "ephemeral-abc123"}')

# Extend by 8 hours
skill_run("extend_ephemeral", '{"namespace": "ephemeral-abc123", "hours": 8}')
```

## Finding Your Namespace

Use `/check-namespaces` to see your ephemeral namespaces.
