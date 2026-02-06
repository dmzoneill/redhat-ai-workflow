# Skill YAML Schema

> Structure and components of skill definition files

## Diagram

```mermaid
graph TB
    subgraph Root[Skill Root]
        NAME[name: string]
        DESC[description: string]
        INPUTS[inputs: list]
        STEPS[steps: list]
        ON_ERROR[on_error: string]
        NOTIFY[notify: list]
    end

    subgraph InputDef[Input Definition]
        I_NAME[name: string]
        I_TYPE[type: string]
        I_REQ[required: boolean]
        I_DEF[default: any]
        I_DESC[description: string]
    end

    subgraph StepDef[Step Definition]
        S_NAME[name: string]
        S_TOOL[tool: string]
        S_ARGS[args: dict]
        S_OUTPUT[output: string]
        S_ERROR[on_error: string]
        S_COND[condition: string]
        S_CONFIRM[confirm: object]
    end

    subgraph ConfirmDef[Confirm Definition]
        C_PROMPT[prompt: string]
        C_OPTS[options: list]
        C_DEF[default: string]
        C_TIMEOUT[timeout: int]
    end

    INPUTS --> InputDef
    STEPS --> StepDef
    S_CONFIRM --> ConfirmDef
```

## Complete Schema

```yaml
# Skill definition schema
name: string                    # Unique skill identifier
description: string             # Human-readable description

inputs:                         # Input parameters
  - name: string               # Parameter name
    type: string               # Type: string, int, bool, list, dict
    required: boolean          # Is required (default: false)
    default: any               # Default value
    description: string        # Parameter description

steps:                          # Execution steps
  - name: string               # Step name
    tool: string               # MCP tool to call
    args:                      # Tool arguments
      key: value               # Static or templated values
      key: "{{ inputs.param }}"  # Template reference
    output: string             # Variable name for result
    on_error: string           # Error handling: abort, continue, retry
    condition: string          # Jinja2 condition
    confirm:                   # Optional confirmation
      prompt: string           # Confirmation message
      options: list            # Available options
      default: string          # Default option
      timeout: int             # Timeout in seconds

on_error: string               # Global error handling
notify: list                   # Notification channels
```

## Template Syntax

```mermaid
flowchart TB
    subgraph Templates[Template Variables]
        INPUTS["{{ inputs.param }}"]
        OUTPUTS["{{ outputs.step_name }}"]
        STEPS["{{ steps.step_name.result }}"]
        ENV["{{ env.VAR_NAME }}"]
        CONFIG["{{ config.section.key }}"]
    end

    subgraph Filters[Jinja2 Filters]
        DEFAULT["| default('value')"]
        JSON["| tojson"]
        UPPER["| upper"]
        LOWER["| lower"]
    end

    Templates --> Filters
```

## Example Skill

```yaml
name: start_work
description: Start work on a Jira issue

inputs:
  - name: issue_key
    type: string
    required: true
    description: Jira issue key (e.g., AAP-12345)

steps:
  - name: fetch_issue
    tool: jira_view_issue
    args:
      issue_key: "{{ inputs.issue_key }}"
    output: issue

  - name: create_branch
    tool: git_create_branch
    args:
      name: "{{ inputs.issue_key | lower }}-{{ outputs.fetch_issue.summary | slugify }}"
    output: branch
    condition: "{{ outputs.fetch_issue.status == 'Open' }}"

  - name: transition_issue
    tool: jira_transition
    args:
      issue_key: "{{ inputs.issue_key }}"
      status: "In Progress"
    confirm:
      prompt: "Transition issue to In Progress?"
      options: [yes, no, skip]
      default: yes
      timeout: 30

on_error: abort
notify: [memory]
```

## Components

| Component | Location | Description |
|-----------|----------|-------------|
| Skill files | `skills/*.yaml` | Skill definitions |
| SkillEngine | `tool_modules/aa_workflow/src/skill_engine.py` | YAML parser |

## Related Diagrams

- [Skill Engine Architecture](./skill-engine-architecture.md)
- [Skill Execution Flow](./skill-execution-flow.md)
- [Common Skills](./common-skills.md)
