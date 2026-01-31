---
description: Systematic alert investigation
agent: devops
---

Investigate alerts in the $1 environment. This will:
- Fetch active alerts from Prometheus
- Check related pod status
- Review logs for errors
- Provide diagnosis and remediation steps

Execute: skill_run("investigate_alert", '{"environment": "$1"}')

**Usage:** `/investigate-alert stage`
