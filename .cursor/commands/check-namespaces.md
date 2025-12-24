# Check My Namespaces

List and manage your ephemeral namespaces.

```bash
KUBECONFIG=~/.kube/config.e bonfire namespace list --mine
```

To release a namespace:
```bash
KUBECONFIG=~/.kube/config.e bonfire namespace release <namespace-name> --force
```

**Note**: Only releases namespaces you own (safety check built-in).

