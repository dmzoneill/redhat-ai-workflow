# /review-all-open

> Batch review all open Merge Requests (excluding your own).

## Overview

Batch review all open Merge Requests (excluding your own).

**Underlying Skill:** `review_all_prs`

This command is a wrapper that calls the `review_all_prs` skill. For detailed process information, see [skills/review_all_prs.md](../skills/review_all_prs.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `repo_name` | No | - |

## Usage

### Examples

```bash
skill_run("review_all_prs", '{}')
```

```bash
# Review specific repository
skill_run("review_all_prs", '{"repo_name": "automation-analytics-backend"}')

# Dry run (don't actually approve/comment)
skill_run("review_all_prs", '{"dry_run": true}')
```

## Process Flow

This command invokes the `review_all_prs` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /review-all-open]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call review_all_prs skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [review_all_prs skill documentation](../skills/review_all_prs.md).

## Details

## Instructions

Review all open MRs in the repository:

```
skill_run("review_all_prs", '{}')
```

This will:
1. List all open MRs (excluding yours)
2. For each MR:
   - Check commit format
   - Verify description
   - Check pipeline status
   - Analyze code patterns
3. Auto-approve clean MRs
4. Post feedback on MRs with issues
5. Send summary to team channel

## Options

```bash
# Review specific repository
skill_run("review_all_prs", '{"repo_name": "automation-analytics-backend"}')

# Dry run (don't actually approve/comment)
skill_run("review_all_prs", '{"dry_run": true}')
```

## Output

Summary of all reviewed MRs:
- ✅ Approved: X MRs
- 📝 Feedback posted: Y MRs
- ⏭️ Skipped (yours): Z MRs


## Related Commands

_(To be determined based on command relationships)_
