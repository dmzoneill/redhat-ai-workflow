---
name: knowledge-list
description: "List all available knowledge files."
---
# Knowledge List

List all available knowledge files.

## Instructions

```text
knowledge_list()
```

## What It Shows

Lists all knowledge files organized by persona and project:

```
## 📚 Available Knowledge

### Developer
- automation-analytics-backend (2.3 KB, updated 2h ago)
- pdf-generator (1.1 KB, updated 1d ago)

### DevOps
- automation-analytics-backend (1.8 KB, updated 3h ago)

### Tester
- automation-analytics-backend (0.9 KB, updated 5d ago)

### Release
- automation-analytics-backend (1.2 KB, updated 1w ago)

*Total: 5 knowledge files*
```

## Knowledge Location

Knowledge files are stored at:
```
memory/knowledge/personas/{persona}/{project}.yaml
```

## See Also

- `/knowledge-load` - Load knowledge into context
- `/knowledge-scan` - Generate new knowledge
- `/bootstrap-knowledge` - Full knowledge generation
