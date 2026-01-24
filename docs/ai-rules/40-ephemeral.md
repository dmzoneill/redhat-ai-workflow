# Ephemeral Deployment Rules

## ⚠️ CRITICAL: Kubeconfig Rules

**NEVER copy kubeconfig files!** Each environment has its own config:

| File | Environment |
|------|-------------|
| `~/.kube/config.s` | Stage |
| `~/.kube/config.p` | Production |
| `~/.kube/config.e` | Ephemeral |

```bash
# WRONG - NEVER DO THIS:
cp ~/.kube/config.e ~/.kube/config

# RIGHT - use --kubeconfig flag:
kubectl --kubeconfig=~/.kube/config.e get pods -n ephemeral-xxx
oc --kubeconfig=~/.kube/config.e get pods -n ephemeral-xxx

# RIGHT - use KUBECONFIG env for bonfire:
KUBECONFIG=~/.kube/config.e bonfire namespace list --mine
```

## Deployment Rules

1. **Use the skill**: `skill_run("test_mr_ephemeral", '{"mr_id": 1459}')`
2. **Image tags must be FULL 40-char git SHA** - short SHAs (8 chars) don't exist in Quay
3. **Only release YOUR namespaces**: `bonfire namespace list --mine`
4. **ITS deploy pattern requires sha256 digest**, not git SHA for IMAGE_TAG

## ClowdApp Deployment

When deploying from **automation-analytics-backend** repo:
- **Ask which ClowdApp** to deploy: main or billing
- **Default to main** if user doesn't specify

| ClowdApp | Name |
|----------|------|
| Main (default) | `tower-analytics-clowdapp` |
| Billing | `tower-analytics-billing-clowdapp` |

```python
# Main (default):
skill_run("test_mr_ephemeral", '{"mr_id": 1459, "billing": false}')

# Billing:
skill_run("test_mr_ephemeral", '{"mr_id": 1459, "billing": true}')
```

## Namespace Safety

```bash
# Check YOUR namespaces only:
KUBECONFIG=~/.kube/config.e bonfire namespace list --mine

# NEVER release namespaces you don't own
```

## Project Context

Key namespaces for Automation Analytics:
- **Konflux**: `aap-aa-tenant`
- **Stage**: `tower-analytics-stage`
- **Production**: `tower-analytics-prod`
