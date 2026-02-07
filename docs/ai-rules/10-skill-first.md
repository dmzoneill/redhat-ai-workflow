# CRITICAL: Skill-First Behavior

## The Golden Rule

**BEFORE attempting ANY task, ALWAYS check for a matching skill first.**

Skills are tested, reliable workflows that handle edge cases. Manual steps are error-prone.

## Decision Tree

When user requests an action:

```
1. Parse intent → What are they trying to do?
2. Check skills → Does skill_list() have a matching skill?
   ├─ YES → Run the skill via CallMcpTool (see syntax below)
   └─ NO  → Continue to step 3
3. Check persona → Do I have the right tools loaded?
   ├─ NO  → Load persona via CallMcpTool
   └─ YES → Proceed with manual steps
4. Execute → Only now attempt manual execution
```

## MCP Tool Call Syntax

**CRITICAL:** All workflow tools are called via `CallMcpTool`. The `inputs` parameter must be a **JSON string**.

```json
// skill_run - Execute a skill
CallMcpTool(
  server: "project-0-redhat-ai-workflow-aa_workflow",
  toolName: "skill_run",
  arguments: {
    "skill_name": "start_work",
    "inputs": "{\"issue_key\": \"AAP-12345\"}"  // JSON STRING, not object!
  }
)

// skill_list - List available skills
CallMcpTool(
  server: "project-0-redhat-ai-workflow-aa_workflow",
  toolName: "skill_list",
  arguments: {}
)

// persona_load - Load a persona
CallMcpTool(
  server: "project-0-redhat-ai-workflow-aa_workflow",
  toolName: "persona_load",
  arguments: {"persona": "developer"}
)
```

**Common Mistake:** Passing `inputs` as an object instead of a JSON string:
- ❌ WRONG: `"inputs": {"issue_key": "AAP-12345"}`
- ✅ RIGHT: `"inputs": "{\"issue_key\": \"AAP-12345\"}"`

## Intent → Skill Mapping

**IMPORTANT:** This is the primary lookup table. When a user request matches a phrase below,
run the corresponding skill immediately via `skill_run`. Do NOT attempt manual steps.

### Daily Rituals

| User Says | Skill | inputs JSON |
|-----------|-------|-------------|
| "morning briefing" / "good morning" / "start my day" | `coffee` | `{}` |
| "end of day" / "wrap up" / "EOD" | `beer` | `{}` |
| "standup" / "generate standup" / "what did I do?" | `standup_summary` | `{}` |
| "weekly summary" / "weekly report" | `weekly_summary` | `{}` |

### Development Workflow

| User Says | Skill | inputs JSON |
|-----------|-------|-------------|
| "start work on AAP-X" / "pick up issue" | `start_work` | `{"issue_key": "AAP-12345"}` |
| "create MR" / "open PR" / "open merge request" | `create_mr` | `{"issue_key": "AAP-12345"}` |
| "review this PR" / "review MR X" | `review_pr` | `{"mr_id": 1234}` |
| "review my local changes" / "pre-commit review" | `review_local_changes` | `{}` |
| "close issue" / "mark done" / "finish AAP-X" | `close_issue` | `{"issue_key": "AAP-12345"}` |
| "close MR" / "abandon MR" | `close_mr` | `{"mr_id": 1234}` |
| "mark MR ready" / "remove draft" / "undraft" | `mark_mr_ready` | `{"mr_id": 1234}` |
| "notify about MR" / "ask for review" | `notify_mr` | `{"mr_id": 1234}` |
| "rebase" / "rebase PR" / "rebase branch" | `rebase_pr` | `{"mr_id": 1234}` |
| "sync branch" / "pull latest" / "update from main" | `sync_branch` | `{}` |
| "update docs" / "check documentation" | `update_docs` | `{}` |
| "check my PRs" / "any MR feedback?" | `check_my_prs` | `{}` |
| "check MR feedback" / "review comments" | `check_mr_feedback` | `{}` |
| "hotfix" / "cherry-pick fix" / "backport" | `hotfix` | `{"commit": "abc123", "target_branch": "release-1.0"}` |
| "fix CVEs" / "fix vulnerabilities" / "CVE remediation" | `cve_fix` | `{}` |
| "audit PRs" / "check Jira links on MRs" | `pr_jira_audit` | `{}` |
| "clean up branches" / "delete merged branches" | `cleanup_branches` | `{}` |
| "autopilot" / "work on sprint issue" | `sprint_autopilot` | `{"issue_key": "AAP-12345"}` |

### Jira / Issue Management

| User Says | Skill | inputs JSON |
|-----------|-------|-------------|
| "create Jira" / "file a bug" / "new issue" | `create_jira_issue` | `{"summary": "..."}` |
| "clone issue" / "duplicate issue" | `clone_jira_issue` | `{"issue_key": "AAP-12345"}` |
| "Jira hygiene" / "fix issue details" | `jira_hygiene` | `{"issue_key": "AAP-12345"}` |
| "hygiene all" / "check all my issues" | `jira_hygiene_all` | `{}` |
| "sprint planning" / "plan sprint" | `sprint_planning` | `{}` |
| "discovered work" / "sync discovered work" | `sync_discovered_work` | `{}` |
| "attach session to Jira" / "document on Jira" | `attach_session_to_jira` | `{"issue_key": "AAP-12345"}` |

### DevOps / Infrastructure

| User Says | Skill | inputs JSON |
|-----------|-------|-------------|
| "deploy MR X to ephemeral" / "test MR in ephemeral" | `test_mr_ephemeral` | `{"mr_id": 1454}` |
| "deploy to ephemeral" / "spin up env" | `deploy_to_ephemeral` | `{}` |
| "extend my namespace" / "extend ephemeral" | `extend_ephemeral` | `{"namespace": "ephemeral-xxx"}` |
| "environment overview" / "how's stage?" / "how's prod?" | `environment_overview` | `{"environment": "stage"}` |
| "check secrets" / "verify config" | `check_secrets` | `{"namespace": "..."}` |
| "restart pods" / "rollout restart" | `rollout_restart` | `{"deployment": "...", "namespace": "..."}` |
| "scale up" / "scale down" / "scale deployment" | `scale_deployment` | `{"deployment": "...", "replicas": 3}` |
| "check CI" / "pipeline status" / "why is CI failing?" | `check_ci_health` | `{}` |
| "retry pipeline" / "retry CI" / "rerun pipeline" | `ci_retry` | `{"mr_id": 1234}` |
| "cancel pipeline" / "stop pipeline" | `cancel_pipeline` | `{"run_name": "..."}` |
| "scan vulnerabilities" / "security scan" | `scan_vulnerabilities` | `{"image_tag": "..."}` |
| "check app-interface" / "app-interface validation" | `appinterface_check` | `{}` |
| "check integration tests" / "integration test status" | `check_integration_tests` | `{}` |

### Incident Response

| User Says | Skill | inputs JSON |
|-----------|-------|-------------|
| "what's firing?" / "check alerts" / "any alerts?" | `investigate_alert` | `{"environment": "stage"}` |
| "investigate Slack alert" / "look into this alert" | `investigate_slack_alert` | `{"message_text": "..."}` |
| "debug prod" / "investigate production issue" | `debug_prod` | `{"namespace": "..."}` |
| "silence alert" / "mute alert" | `silence_alert` | `{"alert_name": "...", "duration": "2h"}` |

### Release

| User Says | Skill | inputs JSON |
|-----------|-------|-------------|
| "release to prod" / "promote to production" | `release_to_prod` | `{}` |
| "release AA backend" / "release analytics" | `release_aa_backend_prod` | `{"commit_sha": "..."}` |
| "Konflux status" / "build status" | `konflux_status` | `{}` |

### Research / Planning

| User Says | Skill | inputs JSON |
|-----------|-------|-------------|
| "plan implementation" / "how should I implement?" | `plan_implementation` | `{"goal": "..."}` |
| "research" / "investigate topic" | `research_topic` | `{"topic": "..."}` |
| "compare options" / "which approach?" | `compare_options` | `{"question": "..."}` |
| "summarize findings" / "wrap up research" | `summarize_findings` | `{"topic": "..."}` |
| "work analysis" / "activity report" | `work_analysis` | `{}` |

### Knowledge / Code Understanding

| User Says | Skill | inputs JSON |
|-----------|-------|-------------|
| "explain code" / "what does this do?" | `explain_code` | `{"file": "src/app.py", "lines": "10-50"}` |
| "find similar code" / "show me examples" | `find_similar_code` | `{"query": "..."}` |
| "gather context" / "what do we know about?" | `gather_context` | `{"query": "..."}` |
| "learn architecture" / "scan project structure" | `learn_architecture` | `{"project": "..."}` |
| "remember this fix" / "learn pattern" | `learn_pattern` | `{"pattern": "...", "fix": "..."}` |
| "suggest patterns" / "find common errors" | `suggest_patterns` | `{}` |

### Code Quality

| User Says | Skill | inputs JSON |
|-----------|-------|-------------|
| "slop scan" / "code quality scan" | `slop_scan` | `{}` |
| "fix slop" / "fix code quality issues" | `slop_fix` | `{}` |
| "trigger slop scan" / "scan code now" | `slop_scan_now` | `{}` |

### Notifications / Communication

| User Says | Skill | inputs JSON |
|-----------|-------|-------------|
| "notify team" / "send to Slack" | `notify_team` | `{"message": "..."}` |
| "add project" / "configure new repo" | `add_project` | `{"path": "..."}` |

### Calendar / Admin

| User Says | Skill | inputs JSON |
|-----------|-------|-------------|
| "schedule meeting" / "find time" | `schedule_meeting` | `{"title": "...", "attendees": "..."}` |
| "sync PTO" / "decline meetings on PTO days" | `sync_pto_calendar` | `{}` |
| "submit expense" / "expense report" | `submit_expense` | `{}` |
| "send reward" / "give recognition" | `reward_zone` | `{"recipient": "...", "message": "..."}` |

### Presentations

| User Says | Skill | inputs JSON |
|-----------|-------|-------------|
| "create presentation" / "new slides" | `create_slide_deck` | `{"title": "..."}` |
| "edit slides" / "update presentation" | `edit_slide_deck` | `{"presentation_id": "..."}` |
| "export slides" / "download as PDF" | `export_presentation` | `{"presentation_id": "..."}` |
| "list presentations" / "my slides" | `list_presentations` | `{}` |

### Memory

| User Says | Skill | inputs JSON |
|-----------|-------|-------------|
| "view memory" / "what's in memory?" | `memory_view` | `{}` |
| "clean memory" / "memory cleanup" | `memory_cleanup` | `{}` |
| "edit memory" / "update memory" | `memory_edit` | `{"file": "...", "action": "..."}` |

## Intent → Persona Mapping

If no skill matches, load the right persona for the domain:

| Intent Keywords | Load Persona |
|-----------------|--------------|
| deploy, ephemeral, namespace, bonfire, k8s | `devops` |
| code, MR, review, commit, branch | `developer` |
| alert, incident, outage, logs, prometheus | `incident` |
| release, prod, konflux, promote | `release` |

## Why Skills Over Manual Steps?

- Skills encode **tested, reliable workflows**
- Skills handle **edge cases** you'd forget
- Skills are **auditable and repeatable**
- Skills can **auto-heal** from known errors
- Skills **log to memory** for context

## NEVER Skip This Check

Even if you think you know how to do something manually, **check for a skill first**.
The skill may have important steps you'd miss.
