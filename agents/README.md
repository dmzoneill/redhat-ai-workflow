# Agents

Agents are specialized AI personas with specific goals, expertise, and tool access.
They are defined as markdown files that Claude loads as context.

## How Agents Work

1. **Agent Definition** - A markdown file describing the agent's role, goals, and capabilities
2. **Tool Access** - Which MCP tools the agent can use
3. **Memory Access** - What context the agent remembers
4. **Skills** - Pre-defined workflows the agent can execute

## Available Agents

| Agent | Purpose | Tools |
|-------|---------|-------|
| `devops.md` | Infrastructure, deployments, monitoring | k8s, prometheus, alertmanager, bonfire |
| `developer.md` | Coding, PRs, code review | git, gitlab, jira |
| `incident.md` | Alert response, debugging, recovery | k8s, prometheus, kibana, alertmanager |
| `release.md` | Release management, deployments | konflux, quay, bonfire, appinterface |

## Usage in Cursor

Add to your `.cursor/rules` or mention in chat:
```
@agent:devops Please check the health of production
```

Or load the full agent context:
```
Load the devops agent and help me investigate the current alerts
```

