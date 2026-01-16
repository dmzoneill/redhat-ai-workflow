---
name: load-release
description: "Switch to Release persona for production deployments."
---
# Load Release Persona

Switch to Release persona for production deployments.

Call `persona_load("release")` to load:
- Konflux build tools
- Quay image tools
- Git tools
- Jira tools

**~91 tools** for stage→prod releases.

Use for:
- Release to production
- Check Konflux build status
- Scan for vulnerabilities
- App-interface updates

## Related Commands

After loading release persona:
- `/release-prod` - Production release workflow
- `/konflux-status` - Check Konflux build status
- `/scan-vulns` - Scan images for CVEs
- `/appinterface-check` - Validate app-interface config
- `/integration-tests` - Review integration test results
