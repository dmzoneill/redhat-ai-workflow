# 📋 jira_hygiene

> Validate and fix Jira issue quality

## Overview

The `jira_hygiene` skill validates that a Jira issue has all required fields properly filled out, and can auto-fix common issues.

## Quick Start

```
skill_run("jira_hygiene", '{"issue_key": "AAP-12345"}')
```

With auto-fix:

```
skill_run("jira_hygiene", '{"issue_key": "AAP-12345", "auto_fix": true}')
```

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `issue_key` | string | ✅ Yes | - | Jira issue key |
| `auto_fix` | boolean | No | `false` | Auto-fix issues |
| `auto_transition` | boolean | No | `false` | Auto-transition New→Refinement |

## Flow

```mermaid
flowchart TD
    START([Start]) --> GET[Get Issue Details]
    GET --> DESC[Check Description]
    DESC --> AC[Check Acceptance Criteria]
    AC --> PRIORITY[Check Priority]
    PRIORITY --> LABELS[Check Labels/Components]

    LABELS --> TYPE{Issue Type?}
    TYPE -->|Story| EPIC[Check Epic Link]
    TYPE -->|Bug/Task| SKIP_EPIC[Skip Epic Check]

    EPIC --> VERSION
    SKIP_EPIC --> VERSION

    VERSION[Check Fix Version] --> STATUS{In Progress?}
    STATUS -->|Yes| POINTS[Check Story Points]
    STATUS -->|No| MARKUP
    POINTS --> MARKUP

    MARKUP[Check Jira Markup] --> COMPILE[Compile Issues]

    COMPILE --> FIX{Auto-fix?}
    FIX -->|Yes| APPLY[Apply Fixes]
    FIX -->|No| REPORT[Report Only]

    APPLY --> TRANSITION{New + Complete?}
    REPORT --> TRANSITION

    TRANSITION -->|Yes| MOVE[→ Refinement]
    TRANSITION -->|No| DONE
    MOVE --> DONE([📋 Done])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style DONE fill:#10b981,stroke:#059669,color:#fff
    style APPLY fill:#10b981,stroke:#059669,color:#fff
```

## Checks Performed

| Check | Required For | Auto-Fixable |
|-------|--------------|--------------|
| Description | All | ⚠️ Template only |
| Acceptance Criteria | Stories | ⚠️ Template only |
| Priority | All | ✅ Default to Medium |
| Labels | All | ❌ |
| Components | All | ❌ |
| Epic Link | Stories | ❌ |
| Fix Version | All | ❌ |
| Story Points | In Progress Stories | ❌ |
| Jira Markup | All | ✅ Convert from Markdown |

## MCP Tools Used

- `jira_view_issue` - Get issue details
- `jira_view_issue_json` - Get raw fields
- `jira_update_issue` - Apply fixes

## Example Output

```
You: Check hygiene for AAP-12345

Claude: 📋 Jira Hygiene Check: AAP-12345

        Issue: "Implement new REST API endpoint"
        Type: Story | Status: New

        ────────────────────────────────

        ## Checks

        | Field | Status | Issue |
        |-------|--------|-------|
        | Description | ✅ | - |
        | Acceptance Criteria | ✅ | - |
        | Priority | ⚠️ | Not set |
        | Labels | ✅ | analytics |
        | Components | ✅ | Backend |
        | Epic Link | ❌ | Missing |
        | Fix Version | ⚠️ | Not set |

        ────────────────────────────────

        ## Summary

        - ✅ 4 checks passed
        - ⚠️ 2 warnings (fixable)
        - ❌ 1 error (needs manual fix)

        **Auto-fixable:** Priority (→ Medium)

        **Needs manual fix:**
        - Epic Link: Add to appropriate epic
```

## Related Skills

- [create_mr](./create_mr.md) - Runs hygiene before MR
- [start_work](./start_work.md) - Check when starting
