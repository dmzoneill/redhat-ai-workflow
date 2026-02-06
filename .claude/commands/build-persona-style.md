---
name: build-persona-style
description: "Build a personalized AI persona from your Slack message history."
arguments:
  - name: months
  - name: persona_name
  - name: include_dms
  - name: include_channels
  - name: include_threads
  - name: skip_export
---
# Build Persona Style

Build a personalized AI persona from your Slack message history.

## Instructions

```text
skill_run("build_persona_style", '{"months": "", "persona_name": "", "include_dms": "", "include_channels": "", "include_threads": "", "skip_export": ""}')
```

## What It Does

Build a personalized AI persona from your Slack message history.

This skill:
1. Exports your Slack messages (DMs, channels, threads)
2. Analyzes your writing style patterns
3. Generates a persona YAML and markdown file

The resulting persona can be used to make AI responses sound like you.

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `months` | Number of months of message history to export (default: 6) | No |
| `persona_name` | Name for the generated persona (default: dave) | No |
| `include_dms` | Include direct messages (default: True) | No |
| `include_channels` | Include channel messages (default: True) | No |
| `include_threads` | Include thread replies (default: True) | No |
| `skip_export` | Skip export step (use existing corpus) | No |
