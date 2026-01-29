# Workspace Persona

Multi-project workspace state and session management.

## Overview

The workspace persona is focused on session and workspace state management across multiple Cursor chats and projects.

## Tool Modules

| Module | Tools | Purpose |
|--------|-------|---------|
| workflow | 51 | Core system tools |
| project | 5 | Project configuration |
| scheduler | 7 | Background scheduling |

**Total:** ~63 tools

## Key Skills

| Skill | Description |
|-------|-------------|
| memory_view | View workspace state |
| memory_edit | Edit state entries |

## Key Tools

| Tool | Purpose |
|------|---------|
| session_start | Initialize session |
| session_info | Get session details |
| session_list | List all sessions |
| workspace_state_list | List workspaces |
| workspace_state_export | Export state |

## Use Cases

- Multi-chat management
- Session tracking
- Workspace state export
- Cross-session context

## Loading

```
persona_load("workspace")
```

## See Also

- [Personas Overview](./README.md)
- [Session Management](../architecture/session-management.md)
- [State Management](../architecture/state-management.md)
