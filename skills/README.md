# Skills

Skills are reusable workflows that combine multiple MCP tools with decision logic.
They can be invoked by agents or directly by the user.

## How Skills Work

1. **Skill Definition** - YAML file describing inputs, steps, and outputs
2. **Tool Composition** - Combines multiple MCP tools in sequence
3. **Decision Points** - Conditional logic based on tool outputs
4. **Output Format** - Structured results for next steps

## Available Skills

| Skill | Purpose | Tools Used |
|-------|---------|------------|
| `start_work.yaml` | Begin work on a Jira issue | jira, git, gitlab |
| `create_mr.yaml` | Create MR with proper format | git, gitlab, jira |
| `deploy_stage.yaml` | Deploy to stage environment | konflux, k8s, prometheus |
| `investigate_alert.yaml` | Investigate firing alerts | prometheus, k8s, kibana |
| `full_release.yaml` | Complete release workflow | konflux, quay, bonfire, appinterface |

## Usage

In chat:
```
Run skill: start_work with issue AAP-12345
```

Or reference in agent prompts:
```
Use the investigate_alert skill to check what's happening in production
```

## Skill Format

```yaml
name: skill_name
description: What this skill does
inputs:
  - name: input_name
    type: string
    required: true
steps:
  - tool: tool_name
    args:
      param: "{{ inputs.input_name }}"
    output: step1_result
  - condition: "{{ step1_result.success }}"
    then:
      - tool: next_tool
    else:
      - fail: "Step 1 failed"
outputs:
  - name: result
    value: "{{ step1_result }}"
```

