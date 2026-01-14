# suggest_patterns

Auto-discover error patterns from tool failure history.

## Description

Analyzes `memory/learned/tool_failures.yaml` to find frequently occurring errors that aren't already captured in `patterns.yaml`.

The skill groups similar errors together and suggests new patterns when an error occurs 5+ times. Use this periodically to discover new patterns worth adding to memory.

## Usage

```python
skill_run("suggest_patterns", '{}')
```text

Or via slash command:

```
/learn-pattern  # After discovering a pattern, use this to save it
```text

## Inputs

This skill takes no inputs.

## How It Works

1. **Reads tool failure history** from `memory/learned/tool_failures.yaml`
2. **Groups similar errors** by pattern matching
3. **Filters out known patterns** already in `patterns.yaml`
4. **Suggests new patterns** that occur 5+ times
5. **Provides add commands** for each suggestion

## Output

The skill returns pattern suggestions with:

- **Pattern text** - The error pattern detected
- **Frequency** - How often it occurred
- **Recommended category** - Suggested category for the pattern
- **Tools affected** - Which tools generated this error
- **Example errors** - Sample error messages
- **Add command** - Ready-to-use `learn_pattern` command

## Example Output

```
## Pattern Discovery Results

Found **2** potential new patterns!

### 1. connection refused

**Frequency:** 8 occurrences
**Recommended category:** `network_errors`
**Tools affected:** kubectl_get_pods, prometheus_query

**Example errors:**
- `dial tcp: connection refused`
- `Unable to connect to the server: dial tcp 10.0.0.1:443: connection refused`

**To add this pattern:**
skill_run("learn_pattern", '{
  "pattern": "connection refused",
  "category": "network_errors",
  "meaning": "...",
  "fix": "...",
  "commands": ["..."]
}')
```

## Related Skills

- [learn_pattern](learn_pattern.md) - Save discovered patterns to memory
- [memory_view](memory_view.md) - View existing patterns
- [memory_cleanup](memory_cleanup.md) - Clean up stale entries

## Auto-Heal

This skill uses compute-only steps and does not require auto-healing.
