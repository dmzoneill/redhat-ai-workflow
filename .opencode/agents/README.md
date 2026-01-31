# OpenCode Agents for AI Workflow

These agents provide specialized capabilities for software development workflows on the Automation Analytics platform.

## Agent Types

### Primary Agents (Tab to switch)

**Developer** - Default coding agent
- Full git, GitLab, and Jira integration
- Code review and MR management
- Linting and code quality
- Use for: Daily development work

**DevOps** - Infrastructure and deployments
- Kubernetes and Bonfire operations
- Ephemeral environment management
- Container image verification
- Use for: Deployments, infrastructure work

### Subagents (@ mention to invoke)

**Core Development:**

**@incident** - Production incident response
- Read-only investigation tools
- Prometheus metrics and Kibana logs
- Alert analysis and mitigation
- Use for: Production emergencies

**@release** - Release management
- Konflux pipeline management
- Production deployment workflows
- Security scanning and validation
- Use for: Shipping releases

**@researcher** - Information gathering
- Read-only codebase exploration
- Semantic code search
- Knowledge management
- Use for: Planning, research, design

**@code** - Pure coding focus
- Git and linting only
- No issue tracking overhead
- Use for: Exploratory coding, refactoring

**@observability** - Monitoring and logs
- Metrics and log analysis
- Health checks and alerts
- Read-only investigation
- Use for: Proactive monitoring

**Administrative:**

**@admin** - Administrative tasks
- Expense submissions (Concur)
- Calendar and scheduling
- Team communication
- Use for: Operational tasks

**@meetings** - Meeting management
- Google Calendar operations
- Meeting scheduling and coordination
- Automated attendance
- Use for: Scheduling and calendar

**@performance** - Performance tracking
- PSE competency tracking
- Quarterly performance reviews
- Work metrics and analysis
- Use for: Performance reviews

**@presentations** - Slide decks
- Google Slides creation and editing
- Content gathering from projects
- Presentation design
- Use for: Creating presentations

**Project Management:**

**@project** - Project context
- Repository navigation
- Knowledge management
- Architectural documentation
- Use for: Understanding projects

**@workspace** - Multi-project coordination
- Workspace state management
- Cross-repository work
- Session synchronization
- Use for: Multi-project work

## Usage Examples

### Switch Primary Agent

```bash
# Use Tab key to cycle through primary agents
Tab    # Build → Plan → Build
```

### Invoke Subagent

```bash
# @ mention a subagent in your message
@researcher how does billing calculation work?
@incident investigate this production alert
@release what's the status of the current release?
```

### Navigation

When subagents create child sessions:
- `<Leader>+Right` - Cycle forward through sessions
- `<Leader>+Left` - Cycle backward through sessions

## Agent Capabilities

**Core Development:**

| Agent | Git | GitLab | Jira | K8s | Monitoring | Deploy | Other |
|-------|-----|--------|------|-----|------------|--------|-------|
| Developer | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | Lint, Code Search |
| DevOps | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ | Bonfire, Quay |
| Incident | ❌ | ❌ | ✅ | ✅ | ✅ | ❌ | Kibana, AlertMgr |
| Release | ✅ | ❌ | ✅ | ❌ | ❌ | ✅ | Konflux, Quay |
| Researcher | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | Code Search, Knowledge |
| Code | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | Lint, Make |
| Observability | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ | Kibana |

**Administrative:**

| Agent | Expenses | Calendar | Slides | Performance | Notes |
|-------|----------|----------|--------|-------------|-------|
| Admin | ✅ Concur | ✅ | ❌ | ❌ | Slack, Scheduler |
| Meetings | ❌ | ✅ | ❌ | ❌ | Meet Bot |
| Performance | ❌ | ❌ | ❌ | ✅ | PSE Tracking |
| Presentations | ❌ | ✅ | ✅ | ❌ | Content Gathering |

**Project Management:**

| Agent | Git | Code Search | Knowledge | Project Config |
|-------|-----|-------------|-----------|----------------|
| Project | ✅ | ✅ | ✅ | ✅ |
| Workspace | ❌ | ✅ | ✅ | ✅ |

## Workflow Examples

### Daily Development Flow

1. Start with **Developer** agent
2. Use `/coffee` command for morning briefing
3. `/start-work AAP-12345` to begin work
4. Code, commit, push
5. `/create-mr AAP-12345` to open MR
6. `/beer` for end-of-day wrap-up

### Testing a Feature

1. Use **Developer** agent
2. Create MR and get MR number
3. `/deploy 1483` to deploy to ephemeral
4. Test the feature
5. Get review with `/review 1483`

### Production Incident

1. Switch to **DevOps** or use **@incident**
2. `/investigate-alert stage` to analyze
3. Check logs and metrics
4. Apply mitigation
5. Document in Jira

### Release to Production

1. Use **@release** subagent
2. Verify release checklist
3. Use release skill to deploy
4. Monitor post-deployment
5. Send announcement

## Skills Integration

All agents have access to relevant skills via the MCP server. Use `skill_list()` to see available skills for the current agent.

Common skills:
- `coffee` - Morning briefing
- `beer` - End of day wrap-up
- `start_work` - Begin Jira issue
- `create_mr` - Create merge request
- `test_mr_ephemeral` - Deploy to ephemeral
- `review_pr` - Code review
- `investigate_alert` - Alert investigation

## Permissions

Each agent has tailored permissions:

**Core Development:**

| Agent | Write | Edit | Bash | Notes |
|-------|-------|------|------|-------|
| Developer | ✅ | Ask | Ask | Git commands allowed |
| DevOps | ✅ | Ask | Ask | kubectl --kubeconfig allowed |
| Incident | ❌ | ❌ | Ask | Read-only kubectl only |
| Release | ✅ | Ask | Ask | Git read commands allowed |
| Researcher | ❌ | ❌ | ❌ | Fully read-only |
| Code | ✅ | ✅ | ✅ | Git, make allowed |
| Observability | ❌ | ❌ | Ask | Read-only kubectl only |

**Administrative:**

| Agent | Write | Edit | Bash | Notes |
|-------|-------|------|------|-------|
| Admin | ❌ | ❌ | ❌ | Uses MCP tools only |
| Meetings | ❌ | ❌ | ❌ | Calendar API only |
| Performance | ✅ | ❌ | ❌ | Writes reports only |
| Presentations | ✅ | ❌ | ❌ | Slides API only |

**Project Management:**

| Agent | Write | Edit | Bash | Notes |
|-------|-------|------|------|-------|
| Project | ❌ | ❌ | ❌ | Read-only exploration |
| Workspace | ❌ | ❌ | ❌ | Coordination only |

## Creating Custom Agents

Create new agents with:

```bash
opencode agent create
```

Or manually create `.md` files in `.opencode/agents/` with YAML frontmatter.

## MCP Integration

All agents connect to the `aa_workflow` MCP server configured in `opencode.json`. The server dynamically loads tools based on the active persona.

See `config.json` for project configuration and `personas/` for source persona definitions.
