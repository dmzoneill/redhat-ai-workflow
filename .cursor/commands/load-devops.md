# Load DevOps Persona

Switch to DevOps persona for deployment and infrastructure tasks.

Call `persona_load("devops")` to load:
- Kubernetes tools (kubectl, oc)
- Bonfire tools (namespace, deploy)
- Quay tools (image inspection)
- GitLab tools (MR management)

**~90 tools** for ephemeral deployments, monitoring, and infrastructure.

Use for:
- Deploy MR to ephemeral
- Check pod status
- Reserve/release namespaces
- Image inspection
