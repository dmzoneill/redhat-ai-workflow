# Architecture Diagrams

> Comprehensive Mermaid diagrams modeling the entire redhat-ai-workflow system

This directory contains **148 Mermaid diagrams** organized into 12 categories, providing exhaustive visual documentation of every component, flow, and integration in the system.

## Quick Navigation

| Category | Diagrams | Description |
|----------|----------|-------------|
| [00-overview](./00-overview/) | 4 | System-wide architecture views |
| [01-server](./01-server/) | 21 | MCP server core components |
| [02-services](./02-services/) | 16 | Background daemons (D-Bus IPC) |
| [03-tools](./03-tools/) | 46 | Tool module architecture |
| [04-skills](./04-skills/) | 10 | Skill engine and 93 skills |
| [05-personas](./05-personas/) | 6 | Persona system (21 personas) |
| [06-memory](./06-memory/) | 9 | Memory/persistence layer |
| [07-integrations](./07-integrations/) | 8 | External service integrations |
| [08-data-flows](./08-data-flows/) | 8 | End-to-end data flows |
| [09-deployment](./09-deployment/) | 4 | Deployment and operations |
| [10-vscode-extension](./10-vscode-extension/) | 6 | VSCode extension architecture |
| [11-scripts](./11-scripts/) | 9 | Utility scripts and automation |

## Category Details

### 00-overview/
High-level system architecture diagrams showing the complete system, component relationships, technology stack, and project structure.

### 01-server/
Core MCP server components including:
- FastMCP server core, tool registry, persona loader
- Session builder, state management, workspace state
- Auto-heal decorator, debuggable infrastructure
- WebSocket server, HTTP client
- Usage pattern system, config system
- Protocols, errors, timeouts, tool paths

### 02-services/
All 12 background daemons with D-Bus IPC:
- **Communication**: Slack daemon
- **Productivity**: Sprint, Meet, Video, Session daemons
- **Automation**: Cron, SLOP daemons
- **Data**: Memory, Config, Stats daemons
- **Integration**: Extension Watcher

### 03-tools/
Tool module architecture covering 50 tool modules organized by domain:
- **Development**: git, gitlab, github, jira, lint, code_search
- **Infrastructure**: k8s, bonfire, konflux, quay, docker, ansible, libvirt
- **Cloud**: aws, gcloud, kubernetes
- **Communication**: slack, meet, google_calendar, google_slides
- **Observability**: prometheus, alertmanager, kibana
- **Database**: postgres, mysql, sqlite
- **Security**: nmap, openssl, ssh, sso
- **Automation**: scheduler, slop_fixer, style, workflow
- **Specialized**: inscope, concur, ollama, curl, make, and more

### 04-skills/
Skill engine internals and complete skill catalog:
- Skill YAML schema and execution flow
- State machine and error handling
- All 93 skills organized by category
- Dependencies and common patterns

### 05-personas/
Persona system architecture covering all 21 personas:
- **Primary**: developer, devops, incident, release
- **Secondary**: researcher, admin, slack, meetings, slop
- **Specialized**: observability, performance, security, database, code, infra, presentations, project
- **External**: github, workspace, universal

### 06-memory/
Memory system architecture:
- Memory abstraction layer with adapters
- State persistence (YAML files)
- Session logging and knowledge storage
- Learned patterns and tool fixes
- Vector search for semantic queries

### 07-integrations/
External service integrations:
- Jira, GitLab, GitHub
- Kubernetes clusters (stage, prod, ephemeral, konflux)
- Slack, Google Workspace
- Quay, Konflux CI/CD
- Authentication flows (SSO, OAuth)

### 08-data-flows/
End-to-end workflows:
- Request lifecycle and session bootstrap
- Skill execution flow
- D-Bus communication patterns
- Memory query routing
- Auto-heal flow
- WebSocket events

### 09-deployment/
Operational aspects:
- Systemd services (12 daemons)
- CLI interface
- Configuration files
- Security model

### 10-vscode-extension/
VSCode extension architecture:
- Service architecture and tab system
- Data flow and message routing
- Real-time WebSocket updates

### 11-scripts/
Utility scripts and automation:
- **AI Agents**: claude_agent.py (Slack bot), mcp_proxy.py (hot-reload proxy)
- **Pattern Mining**: pattern_miner.py, health_check.py
- **Skill Hooks**: skill_hooks.py, ralph_wiggum_hook.py (Ralph Loop)
- **Sync Scripts**: slack_persona_sync.py, context_injector.py
- **Project Tools**: ptools/ (sync_ai_rules, sync_commands, sync_config_example)

## Coverage Summary

| Component | Source Files | Documented |
|-----------|--------------|------------|
| Server modules | 32 | 21 docs |
| Daemons | 12 | 16 docs |
| Tool modules | 50 | 46 docs |
| Scripts | 18 | 9 docs |
| Skills | 93 | Indexed |
| Personas | 21 | Indexed |
| Memory files | ~15 | 9 docs |

## Diagram Conventions

### File Format
Each diagram file is a self-contained Markdown document with:
- Title and one-line description
- Mermaid diagram code block
- Component reference table
- Links to related diagrams

### Mermaid Diagram Types

| Type | Use Case |
|------|----------|
| `graph TB/LR` | Architecture overviews, hierarchies |
| `classDiagram` | Module structure, class relationships |
| `sequenceDiagram` | Request flows, API interactions |
| `stateDiagram-v2` | State machines, lifecycle |
| `flowchart` | Data flows, decision trees |

### Naming Convention
- Kebab-case filenames: `skill-execution-flow.md`
- Descriptive names matching content

## Viewing Diagrams

These Mermaid diagrams render automatically in:
- GitHub/GitLab markdown preview
- VSCode with Mermaid extension
- Any Mermaid-compatible viewer

## Related Documentation

- [Architecture Overview](../README.md)
- [Memory System](../memory-system.md)

## Last Updated

2026-02-05 - Added 11-scripts category with 9 docs covering utility scripts, ptools, and automation. Added usage-pattern-details.md to server. 148 total docs (46 tool, 21 server, 9 memory, 9 scripts).
