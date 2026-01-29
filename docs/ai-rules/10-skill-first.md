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

| User Says | Skill | inputs JSON |
|-----------|-------|-------------|
| "deploy MR X to ephemeral" | `test_mr_ephemeral` | `{"mr_id": 1454}` |
| "start work on AAP-X" | `start_work` | `{"issue_key": "AAP-12345"}` |
| "create MR" / "open PR" | `create_mr` | `{"issue_key": "AAP-12345"}` |
| "what's firing?" / "check alerts" | `investigate_alert` | `{"environment": "stage"}` |
| "morning briefing" | `coffee` | `{}` |
| "end of day" | `beer` | `{}` |
| "review this PR" | `review_pr` | `{"mr_id": 1234}` |
| "release to prod" | `release_to_prod` | `{}` |
| "extend my namespace" | `extend_ephemeral` | `{"namespace": "ephemeral-xxx"}` |

## Intent → Persona Mapping

If no skill exists, load the right persona for the domain:

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
