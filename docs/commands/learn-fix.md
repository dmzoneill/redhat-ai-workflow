# /learn-fix

> Save a tool fix to memory so it's not repeated.

## Overview

Save a tool fix to memory so it's not repeated.

## Arguments

No arguments required.

## Usage

### Examples

```bash
/learn-fix

Tool: bonfire_deploy
Error: manifest unknown
Cause: Short SHA doesn't exist in Quay
Fix: Use full 40-char SHA
```

```bash
Tool fails → check_known_issues() → debug_tool() → fix → learn_tool_fix() → ✓
                    ↑                                            |
                    └────────── remembered for next time ←───────┘
```

## Process Flow

```mermaid
flowchart TD
    START([Start]) --> PROCESS[Process Command]
    PROCESS --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
```text

## Details

## Usage

After successfully fixing a tool, run this command to save the learning.

## What You'll Need

1. **Tool name** - The tool that was fixed (e.g., `bonfire_deploy`)
2. **Error pattern** - The error message that triggered the fix
3. **Root cause** - Why it failed
4. **Fix description** - What was changed

## Example

```
/learn-fix

Tool: bonfire_deploy
Error: manifest unknown
Cause: Short SHA doesn't exist in Quay
Fix: Use full 40-char SHA
```text

## The Learning Loop

```
Tool fails → check_known_issues() → debug_tool() → fix → learn_tool_fix() → ✓
                    ↑                                            |
                    └────────── remembered for next time ←───────┘
```

## Related Commands

- `/debug-tool` - Analyze and fix a failing tool
- `/memory` - View all memory including learned fixes
- `/memory-edit` - Manually edit memory entries


## Related Commands

_(To be determined based on command relationships)_
