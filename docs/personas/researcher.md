# Researcher Persona

Information gathering, research, and planning - the starting point for most work.

## Overview

The researcher persona is intentionally read-only focused. It provides tools for gathering information, searching code semantically, and planning before taking action. Switch to developer/devops when ready to implement.

## Tool Modules

| Module | Tools | Purpose |
|--------|-------|---------|
| workflow | 51 | Core system tools |
| code_search | 9 | Semantic code search |
| knowledge | 6 | Project knowledge |
| project | 5 | Project configuration |

**Total:** ~71 tools

## Key Skills

| Skill | Description |
|-------|-------------|
| research_topic | Deep dive with web + code search |
| compare_options | Compare approaches/libraries |
| summarize_findings | Create research summary |
| plan_implementation | Create implementation plan |
| gather_context | Gather context using semantic search |

## Use Cases

- Research before implementing
- Compare different approaches
- Find similar code patterns
- Plan implementation strategy
- Gather context for complex tasks

## Loading

```
persona_load("researcher")
```

## Transition to Action

When ready to implement:

```python
# Switch to developer for coding
persona_load("developer")

# Or switch to devops for infrastructure
persona_load("devops")
```

## See Also

- [Personas Overview](./README.md)
- [Code Search Tools](../tool-modules/code_search.md)
- [Knowledge System](../architecture/knowledge-system.md)
