---
description: Investigate production issues
agent: devops
---

Debug issues in the $1 environment. This will:
- Check pod health and status
- Review recent logs
- Check for errors and warnings
- Analyze resource usage

Execute: skill_run("debug_prod", '{"namespace": "$1"}')

**Usage:** 
- `/debug-prod stage`
- `/debug-prod tower-analytics-prod`
