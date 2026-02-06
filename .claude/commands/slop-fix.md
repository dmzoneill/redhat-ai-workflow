---
name: slop-fix
description: "Auto-fix high-confidence slop findings in the codebase."
arguments:
  - name: dry_run
  - name: min_confidence
  - name: limit
  - name: commit
---
# Slop Fix

Auto-fix high-confidence slop findings in the codebase.

## Instructions

```text
skill_run("slop_fix", '{"dry_run": "", "min_confidence": "", "limit": "", "commit": ""}')
```

## What It Does

Auto-fix high-confidence slop findings in the codebase.

Only fixes issues with >90% confidence score:
- unused_imports: Remove import lines
- unused_variables: Remove or prefix with _
- bare_except: Change to except Exception:
- empty_except: Add logger.exception()
- dead_code: Remove unused functions/classes

Safe for automated runs - only applies deterministic fixes.

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `dry_run` | If true, show what would be fixed without applying | No |
| `min_confidence` | Minimum confidence threshold (0.0-1.0) (default: 0.9) | No |
| `limit` | Maximum findings to fix per run (default: 20) | No |
| `commit` | If true, commit changes to git (default: True) | No |
