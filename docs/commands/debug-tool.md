# /debug-tool

> When a tool fails, use auto-debug to fix it AND save the learning.

## Overview

When a tool fails, use auto-debug to fix it AND save the learning.

## Arguments

No arguments required.

## Usage

### Examples

```bash
check_known_issues(tool_name="bonfire_deploy")
check_known_issues(error_text="manifest unknown")
```

```bash
❌ Failed to deploy
💡 To auto-fix: debug_tool('bonfire_deploy_aa')
```

```bash
debug_tool("bonfire_deploy_aa", "error message here")
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

## Step 1: Check Known Issues First
```
check_known_issues(tool_name="bonfire_deploy")
check_known_issues(error_text="manifest unknown")
```text

If a fix is known, apply it immediately!

## Step 2: If Unknown, Debug the Tool

When you see a failure like:
```
❌ Failed to deploy
💡 To auto-fix: debug_tool('bonfire_deploy_aa')
```text

Call debug_tool:
```
debug_tool("bonfire_deploy_aa", "error message here")
```text

I will:
1. Load the tool's source code
2. Analyze the error against the code
3. Propose a specific fix
4. Ask for confirmation before applying
5. Commit the fix and retry

## Step 3: Save the Learning!

After the fix works:
```
learn_tool_fix(
    tool_name="bonfire_deploy",
    error_pattern="manifest unknown",
    root_cause="Short SHA doesn't exist",
    fix_description="Use full 40-char SHA"
)
```text

This creates a **learning loop** - next time, `check_known_issues()` will find the fix!

## Common fixable bugs:
- Missing `--force` flag (TTY errors)
- Wrong CLI syntax
- Auth not passed correctly
- Image tag format issues

## The Learning Loop
```
Fail → check_known_issues() → debug_tool() → fix → learn_tool_fix() → ✓
           ↑                                              |
           └──────────── remembered forever ←─────────────┘
```


## Related Commands

_(To be determined based on command relationships)_
