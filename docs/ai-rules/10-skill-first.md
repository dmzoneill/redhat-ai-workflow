# CRITICAL: Skill-First Behavior

## The Golden Rule

**BEFORE attempting ANY task, ALWAYS check for a matching skill first.**

Skills are tested, reliable workflows that handle edge cases. Manual steps are error-prone.

## Decision Tree

When user requests an action:

```
1. Parse intent → What are they trying to do?
2. Check skills → Does skill_list() have a matching skill?
   ├─ YES → Run skill_run("skill_name", '{"params": "..."}')
   └─ NO  → Continue to step 3
3. Check persona → Do I have the right tools loaded?
   ├─ NO  → persona_load("devops") or appropriate persona
   └─ YES → Proceed with manual steps
4. Execute → Only now attempt manual execution
```

## Intent → Skill Mapping

| User Says | Skill | Example |
|-----------|-------|---------|
| "deploy MR X to ephemeral" | `test_mr_ephemeral` | `skill_run("test_mr_ephemeral", '{"mr_id": 1454}')` |
| "start work on AAP-X" | `start_work` | `skill_run("start_work", '{"issue_key": "AAP-12345"}')` |
| "create MR" / "open PR" | `create_mr` | `skill_run("create_mr", '{"issue_key": "AAP-12345"}')` |
| "what's firing?" / "check alerts" | `investigate_alert` | `skill_run("investigate_alert", '{"environment": "stage"}')` |
| "morning briefing" | `coffee` | `skill_run("coffee")` |
| "end of day" | `beer` | `skill_run("beer")` |
| "review this PR" | `review_pr` | `skill_run("review_pr", '{"mr_id": 1234}')` |
| "release to prod" | `release_to_prod` | `skill_run("release_to_prod")` |
| "extend my namespace" | `extend_ephemeral` | `skill_run("extend_ephemeral", '{"namespace": "ephemeral-xxx"}')` |

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
