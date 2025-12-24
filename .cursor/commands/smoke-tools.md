# Smoke Test Tools

Run quick smoke tests on MCP tools to verify they're working.

## Quick tool tests:

```bash
# Git tools
cd /home/daoneill/src/redhat-ai-workflow && git status

# Jira tools  
rh-issue search "project=AAP" -m 3

# GitLab tools
cd /home/daoneill/src/automation-analytics-backend && glab mr list --per-page 3

# Bonfire tools
KUBECONFIG=~/.kube/config.e bonfire namespace list --mine

# Quay tools
skopeo list-tags docker://quay.io/redhat-user-workloads/aap-aa-tenant/aap-aa-main/automation-analytics-backend-main | head -20

# K8s tools (ephemeral)
kubectl --kubeconfig=~/.kube/config.e get namespaces | grep ephemeral | head -5
```

Run each command to verify the tool stack is working.

