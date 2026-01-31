# OpenCode Custom Commands

These custom commands integrate with the AI Workflow MCP server to provide one-command access to complex workflows.

## Available Commands

### Code Review Commands

- **`/review-mr-multiagent <MR_ID> [post]`** - Multi-agent code review (6 agents, ~1.8 min)
- **`/review <MR_ID>`** - Single-agent code review (faster, simpler)
- **`/review-all-open`** - Batch review all open MRs
- **`/check-my-prs`** - Check your MRs for feedback

### Workflow Commands

- **`/coffee`** - Morning briefing (calendar, email, PRs, alerts)
- **`/start-work <ISSUE_KEY>`** - Begin working on a Jira issue
- **`/create-mr <ISSUE_KEY>`** - Create merge request with validation
- **`/memory`** - View current work state
- **`/beer`** - End of day wrap-up and tomorrow prep

### Deployment Commands

- **`/deploy <MR_ID>`** - Deploy MR to ephemeral for testing
- **`/debug-prod <ENV>`** - Investigate production issues
- **`/investigate-alert <ENV>`** - Systematic alert investigation

## Examples

```bash
# Morning routine
/coffee

# Start working on an issue
/start-work AAP-12345

# Deploy your MR for testing
/deploy 1483

# Get comprehensive code review
/review-mr-multiagent 1483 true

# End of day wrap-up
/beer
```

## Multi-Agent Review Options

The `/review-mr-multiagent` command supports multiple configurations:

```bash
# Preview only (no posting)
/review-mr-multiagent 1483

# Post to MR
/review-mr-multiagent 1483 true
```

**Agents:**
- Architecture (Claude) - Design patterns, SOLID principles
- Security (Gemini) - Vulnerabilities, OWASP Top 10
- Performance (Claude) - Algorithm efficiency, scalability
- Testing (Gemini) - Test coverage, edge cases
- Documentation (Claude) - Comments, API docs
- Style (Gemini) - Naming conventions, consistency

## Technical Details

All commands use the MCP `skill_run()` function configured in `opencode.json`. Commands automatically:
- Load the correct persona (developer/devops)
- Execute pre-built, tested workflows
- Handle authentication and error cases
- Update memory and context

See `.opencode/commands/<name>.md` for individual command definitions.
