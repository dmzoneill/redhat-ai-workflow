# Admin Persona

Administrative tasks - expenses, calendar, team communication.

## Overview

The admin persona is designed for non-coding administrative tasks like expense submission, calendar management, and team coordination.

## Tool Modules

| Module | Tools | Purpose |
|--------|-------|---------|
| workflow | 51 | Core system tools |
| knowledge | 6 | Project knowledge |
| project | 5 | Project configuration |
| scheduler | 7 | Cron job management |
| concur | 9 | Expense automation |
| slack | 15 | Team notifications |
| jira_basic | 17 | Issue viewing |

**Total:** ~71 tools

## Key Skills

| Skill | Description |
|-------|-------------|
| submit_expense | Submit monthly expenses |
| coffee | Morning briefing |
| beer | End of day summary |
| notify_team | Slack notifications |
| schedule_meeting | Calendar management |

## Use Cases

- Submit expense reports via SAP Concur
- Schedule and manage meetings
- Send team notifications
- Track work for standups

## Loading

```
persona_load("admin")
/load-admin
```

## See Also

- [Personas Overview](./README.md)
- [Concur Tools](../tool-modules/concur.md)
