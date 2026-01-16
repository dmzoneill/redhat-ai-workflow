# Load Incident Persona

Switch to Incident persona for alert investigation and production issues.

Call `persona_load("incident")` to load:
- Kubernetes tools (pods, logs, events)
- Prometheus/Alertmanager tools
- Kibana log search
- Jira tools

**~78 tools** for incident response and troubleshooting.

Use for:
- Investigate firing alerts
- Debug production issues
- Silence noisy alerts
- Check environment health

## Related Commands

After loading incident persona:
- `/investigate-alert` - Quick alert triage
- `/debug-prod` - Deep production investigation
- `/silence-alert` - Create alert silences
- `/rollout-restart` - Restart deployments
- `/env-overview` - Full environment health check
