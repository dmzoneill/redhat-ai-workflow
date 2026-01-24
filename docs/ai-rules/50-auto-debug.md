# Auto-Debug: Self-Healing Tools

When an MCP tool fails (returns ❌), you can fix the tool itself.

## Workflow

1. **Tool fails** → Look for the hint: `💡 To auto-fix: debug_tool('tool_name')`
2. **Call debug_tool** → `debug_tool('bonfire_namespace_release', 'error message')`
3. **Analyze the source** → Compare error to code, identify the bug
4. **Propose a fix** → Show exact `search_replace` edit
5. **Ask user to confirm** → "Found bug: missing --force flag. Apply fix?"
6. **Apply and commit** → `git commit -m "fix(tool_name): description"`

## Example

```
Tool output: ❌ Failed to release namespace
             💡 To auto-fix: `debug_tool('bonfire_namespace_release')`

You: [call debug_tool('bonfire_namespace_release', 'Output is not a TTY. Aborting.')]

Claude: "I found the bug. The bonfire CLI prompts for confirmation but we're
         not passing --force. Here's the fix:

         File: tool_modules/aa-bonfire/src/tools.py
         - args = ['namespace', 'release', namespace]
         + args = ['namespace', 'release', namespace, '--force']

         Apply this fix?"

User: "yes"

Claude: [applies fix, commits, retries operation]
```

## Common Fixable Bugs

| Error Pattern | Likely Cause |
|---------------|--------------|
| "Output is not a TTY" | Missing --force/--yes flag |
| "Unknown flag: --state" | CLI syntax changed |
| "Unauthorized" | Auth not passed correctly |
| "manifest unknown" | Wrong image tag format |

## Check Known Issues First

Before debugging, check if we've seen this error before:

```python
check_known_issues(tool_name="bonfire_deploy", error_text="manifest unknown")
```

## Save Fixes for Future

After fixing a tool, save the pattern:

```python
learn_tool_fix(
    tool_name="bonfire_deploy",
    error_pattern="manifest unknown",
    root_cause="Short SHA doesn't exist in Quay",
    fix_description="Use full 40-char SHA"
)
```
