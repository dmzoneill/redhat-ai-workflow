# 🧠 View Memory

View and manage the persistent memory system.

## Instructions

```python
skill_run("memory_view")
```

## Options

View specific sections:
```python
# Just current work
skill_run("memory_view", '{"section": "work"}')

# Just follow-ups
skill_run("memory_view", '{"section": "followups"}')

# Just environments
skill_run("memory_view", '{"section": "environments"}')

# Just patterns
skill_run("memory_view", '{"section": "patterns"}')
```

## Actions

Clear completed items:
```python
skill_run("memory_view", '{"action": "clear_completed"}')
```

Add a follow-up task:
```python
skill_run("memory_view", '{"action": "add_followup", "followup_text": "Review MR !1234", "followup_priority": "high"}')
```

Clean old session logs:
```python
skill_run("memory_view", '{"action": "clear_old_sessions"}')
```
