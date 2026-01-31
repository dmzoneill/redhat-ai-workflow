# OpenCode Setup for AI Workflow

This directory contains OpenCode-specific configuration for the AI Workflow MCP server.

## What's Included

### Commands (`.opencode/commands/`)

Custom slash commands for common workflows:

| Command | Description | Example |
|---------|-------------|---------|
| `/coffee` | Morning briefing | `/coffee` |
| `/start-work` | Begin Jira issue | `/start-work AAP-12345` |
| `/create-mr` | Create merge request | `/create-mr AAP-12345` |
| `/deploy` | Deploy to ephemeral | `/deploy 1483` |
| `/review` | Single-agent code review | `/review 1483` |
| `/review-mr-multiagent` | Multi-agent review | `/review-mr-multiagent 1483 true` |
| `/check-my-prs` | Check your MRs | `/check-my-prs` |
| `/debug-prod` | Debug production | `/debug-prod stage` |
| `/investigate-alert` | Alert investigation | `/investigate-alert stage` |
| `/memory` | View work state | `/memory` |
| `/beer` | End of day wrap-up | `/beer` |

### Agents (`.opencode/agents/`)

Specialized AI assistants:

**Primary Agents (Tab to switch):**
- `developer` - Default coding agent with full tools
- `devops` - Infrastructure and deployment management

**Subagents (@ mention):**
- `@incident` - Production incident response
- `@release` - Release management
- `@researcher` - Information gathering and planning
- `@code` - Pure coding without issue tracking
- `@observability` - Monitoring and logs

## Quick Start

1. **Install OpenCode** if you haven't already:
   ```bash
   npm install -g @opencode/cli
   ```

2. **The MCP server is already configured** in `opencode.json`:
   ```json
   {
     "mcp": {
       "aa_workflow": {
         "type": "local",
         "command": ["bash", "-c", "cd ~/redhat-ai-workflow && source .venv/bin/activate && python3 -m server"]
       }
     }
   }
   ```

3. **Start using commands** in the OpenCode TUI:
   ```bash
   opencode
   /coffee
   ```

4. **Switch agents** with Tab or @ mention:
   ```bash
   Tab                # Cycle primary agents
   @researcher        # Invoke subagent
   ```

## Differences from Cursor

### Commands
- **Cursor**: Single `.cursorcommands` file
- **OpenCode**: Individual `.md` files in `.opencode/commands/`
- **OpenCode** supports: `$1`, `$2`, `$ARGUMENTS`, `!`command``, `@file`

### Agents
- **Cursor**: No built-in agent system
- **OpenCode**: Primary agents + subagents with permissions
- **OpenCode** supports: Mode (primary/subagent), tools control, permissions

### MCP Integration
- Both use the same `aa_workflow` MCP server
- OpenCode has tighter integration with agent permissions
- OpenCode can restrict tools per agent

## File Structure

```
.opencode/
├── commands/           # Slash commands
│   ├── README.md
│   ├── coffee.md
│   ├── start-work.md
│   ├── create-mr.md
│   ├── deploy.md
│   ├── review.md
│   ├── review-mr-multiagent.md
│   ├── check-my-prs.md
│   ├── debug-prod.md
│   ├── investigate-alert.md
│   ├── memory.md
│   └── beer.md
│
└── agents/            # AI personas
    ├── README.md
    ├── developer.md   (primary)
    ├── devops.md      (primary)
    ├── incident.md    (subagent)
    ├── release.md     (subagent)
    ├── researcher.md  (subagent)
    ├── code.md        (subagent)
    └── observability.md (subagent)
```

## Next Steps

1. **Try the commands**: `/coffee` to start your day
2. **Switch agents**: Tab through Developer and DevOps
3. **Invoke subagents**: `@researcher how does billing work?`
4. **Customize**: Edit `.md` files to adjust behavior

## Documentation

- Commands: See `.opencode/commands/README.md`
- Agents: See `.opencode/agents/README.md`
- OpenCode docs: https://opencode.ai/docs/

## Support

- OpenCode Discord: https://opencode.ai/discord
- GitHub: https://github.com/anomalyco/opencode
