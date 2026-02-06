# Tool Discovery

## Why Discovery Matters

Tools are **dynamic** - they change when personas load. Never assume which tools are available. Always discover.

## Discovery Tools

| Tool | Purpose |
|------|---------|
| `tool_list()` | List all modules and their tool counts |
| `tool_list(module="git")` | List tools in a specific module |
| `skill_list()` | List available skills (workflows) |
| `persona_list()` | List available personas |

## Example Discovery Flow

```json
// 1. See what modules are loaded
tool_list()
// Returns: git (8 tools), jira (6 tools), gitlab (5 tools), ...

// 2. Explore a specific module
tool_list(module="git")
// Returns: git_status, git_diff, git_add, git_commit, git_push, ...

// 3. See available skills
skill_list()
// Returns: start_work, create_mr, coffee, beer, investigate_alert, ...
```

## Calling Tools

### Prefer Direct Calls (When Persona Loaded)

When a persona is loaded, call tools directly by name:

```python
git_status()                           # Clear in UI
jira_view_issue("AAP-12345")           # Shows actual tool name
kubectl_get_pods(namespace="...")      # Easy to understand
```

### Use tool_exec for Non-Loaded Modules

When you need a tool from a module not in the current persona:

```python
tool_exec("bonfire_deploy", '{"namespace": "ephemeral-xxx"}')
tool_exec("prometheus_alerts", '{"environment": "prod"}')
```

**Note:** `tool_exec` shows as "tool_exec" in the UI, making it less clear what's happening. Prefer loading the right persona when possible.

## Loading Different Tools

If you need tools from a different domain, load the appropriate persona:

```json
// Need k8s tools? Load devops
persona_load("devops")

// Need code review tools? Load developer
persona_load("developer")

// Need alerting tools? Load incident
persona_load("incident")
```

## Module Naming Convention

Tool modules follow a naming pattern:

| Suffix | Purpose | Example |
|--------|---------|---------|
| `_core` | Essential tools (5-10) | `git_core`, `jira_core` |
| `_basic` | Common tools (10-20) | `git_basic`, `k8s_basic` |
| `_extra` | Advanced tools | `git_extra`, `jira_extra` |
| `_style` | Style/formatting tools | `slack_style` |
| (none) | Alias for _basic | `git` = `git_basic` |

Personas typically load `_core` variants to stay under the 80-tool limit.
