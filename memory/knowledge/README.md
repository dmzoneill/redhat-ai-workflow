# Project Knowledge

This directory contains project-specific expertise organized by persona.

## Structure

```
knowledge/
└── personas/
    ├── developer/
    │   ├── automation-analytics-backend.yaml
    │   └── pdf-generator.yaml
    ├── devops/
    │   └── automation-analytics-backend.yaml
    ├── tester/
    │   └── automation-analytics-backend.yaml
    ├── incident/
    │   └── automation-analytics-backend.yaml
    └── release/
        └── automation-analytics-backend.yaml
```

## Knowledge Schema

Each knowledge file contains:

```yaml
metadata:
  project: string           # Project name from config.json
  persona: string           # Persona this knowledge is for
  last_updated: datetime    # When last modified
  last_scanned: datetime    # When project was last scanned
  confidence: float         # 0.0-1.0, increases with learning

architecture:
  overview: string          # Project description
  key_modules:              # Important directories/files
    - path: string
      purpose: string
      notes: string
  data_flow: string         # How data moves through the system
  dependencies: list        # Key dependencies

patterns:
  coding:                   # Code patterns
    - pattern: string
      example: string
      location: string
  testing:                  # Test patterns
    - pattern: string
      example: string
  deployment:               # Deploy patterns
    - pattern: string
      notes: string

gotchas:                    # Known issues/traps
  - issue: string
    reason: string
    solution: string

learned_from_tasks:         # Accumulated learnings
  - date: date
    task: string            # Issue key or description
    learning: string
```

## How Knowledge Grows

1. **Auto-scan on first encounter**: When you start working on a project
   with a persona that has no knowledge, it's automatically scanned.

2. **Continuous learning**: After completing tasks, the AI records
   learnings via `knowledge_learn()`.

3. **Manual updates**: You can add knowledge via `knowledge_update()`.

4. **Confidence increases**: As more learnings are added, confidence
   increases, indicating more reliable knowledge.

## Tools

- `knowledge_load(project, persona)` - Load knowledge into context
- `knowledge_scan(project)` - Scan project and generate knowledge
- `knowledge_update(project, persona, section, content)` - Update section
- `knowledge_query(project, persona, section)` - Query specific section
- `knowledge_learn(learning, task)` - Record a learning
- `knowledge_list()` - List all knowledge files
