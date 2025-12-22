# AA Kubernetes MCP Server

MCP server for Kubernetes operations via kubectl.

## Tools (22)

### Pods
- `kubectl_get_pods` - List pods
- `kubectl_describe_pod` - Describe pod
- `kubectl_logs` - Get pod logs
- `kubectl_delete_pod` - Delete pod

### Deployments
- `kubectl_get_deployments` - List deployments
- `kubectl_describe_deployment` - Describe deployment
- `kubectl_rollout_status` - Check rollout status
- `kubectl_rollout_restart` - Rolling restart
- `kubectl_scale` - Scale replicas

### Networking
- `kubectl_get_services` - List services
- `kubectl_get_ingress` - List ingress

### Config
- `kubectl_get_configmaps` - List configmaps
- `kubectl_get_secrets` - List secrets

### Debugging
- `kubectl_get_events` - Get events
- `kubectl_top_pods` - Resource usage
- `kubectl_get` - Get any resource
- `kubectl_exec` - Exec command

### SaaS/App-SRE
- `kubectl_saas_pipelines` - SaaS pipelines
- `kubectl_saas_deployments` - SaaS deployments
- `kubectl_saas_pods` - SaaS pods
- `kubectl_saas_logs` - SaaS logs

## Authentication

Uses kubeconfig files in `~/.kube/`:
- `config.s` - Stage
- `config.p` - Production
- `config.e` - Ephemeral
- `config.ap` - App-SRE SaaS Pipelines

## Usage

```json
{
  "mcpServers": {
    "k8s": {
      "command": "aa-k8s"
    }
  }
}
```

