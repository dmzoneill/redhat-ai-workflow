# Plans & Architecture Proposals

This directory contains design documents and implementation plans for future features.

## Active Plans

| Plan | Status | Phase | Description |
|------|--------|-------|-------------|
| [IDE Integrations](./ide-integrations.md) | ✅ Complete | Phase 6 Complete | VSCode/Cursor extension with status bar, tree view, dashboard |

## Plan Lifecycle

```text
📋 Planning → 🚧 In Progress → ✅ Complete → 📚 Archived
```

## IDE Integrations (Complete)

**Goal:** Enhance developer experience with IDE integration.

**Completed Features:**
- Status bar with Slack, Issue, Environment, MR indicators
- Tree view sidebar with active work, namespaces, alerts
- Command palette integration (11 commands)
- Toast notifications for alerts, pipelines, MR updates
- Dashboard webview with current work overview
- Skill execution visualizer (GitHub Actions style)

**Location:** `extensions/aa_workflow-vscode/`

## Creating New Plans

When proposing a new feature or architecture change:

1. Create a new `.md` file in this directory
2. Use the following template:

```markdown
# [Feature Name] Plan

## Overview
Brief description of what this plan proposes.

## Current State
What exists today.

## Target State
What we want to achieve.

## Implementation Phases
Detailed breakdown of work.

## Timeline
Estimated effort per phase.

## Risks & Mitigations
Potential issues and how to address them.

## See Also
Related documentation.
```

3. Update this README to add your plan to the Active Plans table
4. Discuss with the team before implementation

## See Also

- [Architecture Overview](../architecture/README.md)
- [Learning Loop](../learning-loop.md)
- [Development Guide](../DEVELOPMENT.md)
