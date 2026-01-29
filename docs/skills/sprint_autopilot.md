# 🤖 sprint_autopilot

> Autonomous sprint issue processing with dynamic persona switching

## Overview

The `sprint_autopilot` skill orchestrates work on a single sprint issue from start to finish. It dynamically switches between personas as needed (developer for coding tasks, devops for deployment), checks git safety, analyzes issue clarity, sets up branches, researches the codebase, creates merge requests, and updates Jira with progress.

This skill is designed for semi-autonomous operation - it handles the setup and orchestration while actual implementation happens in a dedicated Cursor chat.

## Quick Start

```text
skill_run("sprint_autopilot", '{"issue_key": "AAP-12345"}')
```

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `issue_key` | string | Yes | - | Jira issue key (e.g., `AAP-12345`) |
| `repo_path` | string | No | `"."` | Path to the repository |
| `needs_deployment_check` | boolean | No | `false` | Whether to deploy to ephemeral for testing |
| `auto_stash` | boolean | No | `true` | Automatically stash uncommitted changes |
| `skip_clarity_check` | boolean | No | `false` | Skip the issue clarity check |

## What It Does

### Stage 1: Issue Analysis (Developer Persona)

1. **Load Developer Persona** - Ensures developer tools are available
2. **Safety Check** - Verifies git worktree is safe:
   - No rebase in progress
   - No merge conflicts
   - Not on protected branch (main/master/develop)
3. **Stash Changes** - Auto-stashes uncommitted work if present
4. **Analyze Issue** - Fetches issue details from Jira
5. **Check Clarity** - Evaluates if issue has enough detail:
   - Acceptance criteria
   - Detailed description
   - Technical context
6. **Request Clarification** - If unclear, adds a comment asking for more details

### Stage 2: Branch Setup (Developer Persona)

7. **Start Work** - Invokes `start_work` skill to create feature branch
8. **Extract Branch Name** - Captures the created branch name

### Stage 3: Code Research (Developer Persona)

9. **Research Codebase** - Uses semantic search to find relevant code
10. **Load Project Knowledge** - Retrieves patterns and gotchas
11. **Prepare Context** - Combines research for implementation

### Stage 4: Implementation

12. **Log Ready** - Marks issue as ready for implementation in dedicated chat

### Stage 5: MR Creation (Developer Persona)

13. **Check for Changes** - Verifies there are changes to commit
14. **Create MR** - Invokes `create_mr` skill to create merge request
15. **Extract MR Info** - Captures MR URL and ID

### Stage 6: Deployment Check (DevOps Persona)

16. **Switch to DevOps** - Loads devops persona for deployment tools
17. **Deploy to Ephemeral** - Invokes `test_mr_ephemeral` skill

### Stage 7: Finalize (Developer Persona)

18. **Switch Back** - Returns to developer persona
19. **Update Jira** - Adds MR link comment to issue
20. **Log Timeline** - Records MR creation event
21. **Generate Summary** - Creates final status report

## Example Usage

### Basic Usage

```python
skill_run("sprint_autopilot", '{"issue_key": "AAP-12345"}')
```

### With Deployment Check

```python
skill_run("sprint_autopilot", '{"issue_key": "AAP-12345", "needs_deployment_check": true}')
```

### Skip Clarity Check

```python
skill_run("sprint_autopilot", '{"issue_key": "AAP-12345", "skip_clarity_check": true}')
```

### Specific Repository

```python
skill_run("sprint_autopilot", '{"issue_key": "AAP-12345", "repo_path": "/home/user/src/backend"}')
```

## Example Output

### Successful Run

```text
## Sprint Autopilot Summary for AAP-12345

**Status:** MR Created
MR URL: https://gitlab.cee.redhat.com/automation-analytics/automation-analytics-backend/-/merge_requests/1502
Branch: aap-12345-add-billing-endpoint
```

### Waiting for Clarification

```text
## Sprint Autopilot Summary for AAP-12345

**Status:** Waiting for clarification
Reason: Missing: acceptance criteria, technical details
```

### Ready for Implementation

```text
## Sprint Autopilot Summary for AAP-12345

**Status:** Ready for implementation
Context has been prepared. Work can continue in a dedicated chat.
```

## Clarity Check Criteria

The skill evaluates issue clarity based on:

| Criterion | What It Looks For |
|-----------|-------------------|
| Acceptance Criteria | "acceptance criteria", "AC:", "requirements:", "given/when/then" |
| Description | Issue text longer than 200 characters |
| Technical Details | "api", "endpoint", "database", "function", "class", "component", "file", "test" |

If the issue lacks acceptance criteria AND doesn't have both a substantial description and technical details, clarification is requested.

## Git Safety Checks

| Condition | Result |
|-----------|--------|
| Rebase in progress | Abort with message |
| Merge in progress | Abort with message |
| On protected branch | Abort with message |
| Uncommitted changes | Auto-stash (if enabled) |

## MCP Tools Used

- `persona_load` - Switch between developer and devops personas
- `git_status` - Check worktree state
- `git_stash` - Stash uncommitted changes
- `jira_view_issue` - Fetch issue details
- `jira_add_comment` - Add clarification request or MR link
- `code_search` - Semantic codebase search
- `knowledge_query` - Load project patterns
- `skill_run` - Invoke sub-skills (start_work, create_mr, test_mr_ephemeral)
- `memory_append` - Log timeline events

## Related Skills

- [start_work](./start_work.md) - Create feature branch and set up for work
- [create_mr](./create_mr.md) - Create merge request
- [test_mr_ephemeral](./test_mr_ephemeral.md) - Deploy to ephemeral environment
- [jira_hygiene](./jira_hygiene.md) - Check and fix Jira issue quality
