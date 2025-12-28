# Debug Failed Tool

When a tool fails, use auto-debug to fix it.

## When you see a failure like:
```
❌ Failed to deploy
💡 To auto-fix: debug_tool('bonfire_deploy_aa')
```

## Call debug_tool:
```
debug_tool("bonfire_deploy_aa", "error message here")
```

I will:
1. Load the tool's source code
2. Analyze the error against the code
3. Propose a specific fix
4. Ask for confirmation before applying
5. Commit the fix and retry

## Common fixable bugs:
- Missing `--force` flag (TTY errors)
- Wrong CLI syntax
- Auth not passed correctly
- Image tag format issues
