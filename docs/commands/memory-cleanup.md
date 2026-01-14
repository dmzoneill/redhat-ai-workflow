# /memory-cleanup

> Clean up stale entries from memory.

## Overview

Clean up stale entries from memory.

**Underlying Skill:** `memory_cleanup`

This command is a wrapper that calls the `memory_cleanup` skill. For detailed process information, see [skills/memory_cleanup.md](../skills/memory_cleanup.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `dry_run` | No | - |

## Usage

### Examples

```bash
skill_run("memory_cleanup", '{}')
```

```bash
skill_run("memory_cleanup", '{"dry_run": false}')
```

```bash
/memory-cleanup
```

## Process Flow

This command invokes the `memory_cleanup` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /memory-cleanup]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call memory_cleanup skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [memory_cleanup skill documentation](../skills/memory_cleanup.md).

## Details

## Usage

**Preview what would be removed (dry run - default):**
```
skill_run("memory_cleanup", '{}')
```text

**Actually remove stale entries:**
```
skill_run("memory_cleanup", '{"dry_run": false}')
```text

## What Gets Cleaned

- **Active Issues**: Issues with status "Done", "Closed", or "Resolved"
- **Open MRs**: MRs with pipeline status "merged" or "closed"
- **Ephemeral Namespaces**: Namespaces older than 7 days (configurable)

## Options

- `dry_run`: Preview changes without applying (default: true)
- `days`: Remove ephemeral namespaces older than this (default: 7)

## Example

```
/memory-cleanup
```

This shows what would be cleaned. Run with `dry_run: false` to apply.


## Related Commands

_(To be determined based on command relationships)_
